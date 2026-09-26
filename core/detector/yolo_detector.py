import os
import time
import cv2
import numpy as np
import onnxruntime as ort
from PySide6.QtCore import QObject, Slot, Signal,QThread
from .postprocess import postprocess_yolov8,postprocess_yolov5  # 导入后处理函数
from core.calibration import canonical_class_name


class ModelInitThread(QThread):
    """在**子线程**里建 ONNX Runtime 会话、读标签文件。

    ⚠️ 2026-09-23 修正：原先 ``run()`` 是个空壳（真正的加载代码被注释掉了），
    于是 ``ort.InferenceSession(...)`` 实际落在主线程的
    ``MainWindow.on_model_init_finished`` 里执行 —— 加载期间整个界面卡住。
    现在把「耗时的那一段」搬回本线程：主线程只做装配，
    ``load_model`` 直接采用这里建好的 session，不再重复建。
    """

    init_finished = Signal(bool, str, object)

    def __init__(self, model_path: str, hardware_accel='CPU', label_path: str = ''):
        super().__init__()
        self.model_path = model_path
        self.hardware_accel = hardware_accel
        self.label_path = label_path

    def run(self):
        try:
            if not self.model_path or not os.path.isfile(self.model_path):
                self.init_finished.emit(True, "未指定模型路径，跳过加载", None)
                return

            payload = {'session': None, 'labels': []}

            # 标签文件顺手在本线程读掉，主线程就不用再做文件 IO
            if self.label_path and os.path.isfile(self.label_path):
                with open(self.label_path, 'r', encoding='utf-8') as f:
                    payload['labels'] = [line.strip() for line in f
                                         if line.strip()]

            # 真正耗时的一段（建会话 + 图优化）。
            # 本机实测 yolov8n.onnx 约 0.23 s；模型更大或机器更忙时会显著变长，
            # 所以必须在子线程里做，绝不能留在主线程。
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = \
                ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.intra_op_num_threads = 4      # 用 4 核做推理
            sess_options.inter_op_num_threads = 1
            payload['session'] = ort.InferenceSession(
                self.model_path, sess_options,
                providers=['CPUExecutionProvider'])

            self.init_finished.emit(
                True,
                f"模型加载成功：{os.path.basename(self.model_path)}"
                f"（标签 {len(payload['labels'])} 个）",
                payload,
            )
        except Exception as e:
            self.init_finished.emit(False, f"模型加载失败：{str(e)}", None)


class YOLODetector(QObject):
    detection_ready = Signal(dict)

    def __init__(self, model_path, label_path, global_params, conf_thres=0.5, nms_thres=0.45, hardware_accel='CPU',model_type='v8'):
        super().__init__()
        self.model_path = model_path
        self.label_path = label_path
        self.conf_thres = conf_thres
        self.nms_thres = nms_thres
        self.hardware_accel = hardware_accel
        self.model = None
        self.labels = []
        self.global_params = global_params
        self.model_type=model_type
        # CHARTER v1.3：全链路唯一类别是「行人」。标签文件载入后由
        # _refresh_person_class_ids() 算出 person 的 class_id 白名单；
        # None = 标签不可用（无法确定哪个 id 是 person，此时不过滤并
        # 在 _refresh 里说明，不瞎猜 COCO id 0）。
        self._person_class_ids = None

    def _refresh_person_class_ids(self):
        """从当前标签文件算出 person 的 class_id 集合（CHARTER v1.3）。

        中英文标签都过 ``canonical_class_name`` 归一化（coco80.txt 的
        ``person`` 与 coco_labels_cn.txt 的 ``人`` 都命中）。
        标签为空 → 白名单置 None（后处理不过滤）。这是**如实降级**：
        没有标签就无从知道哪个 id 是行人，宁可不过滤也不猜
        「id 0 就是 person」—— 换标签文件的自由是用户的。
        """
        ids = frozenset(
            i for i, name in enumerate(self.labels)
            if canonical_class_name(name) == 'person')
        self._person_class_ids = ids if ids else None

    def load_model(self, preloaded_model=None):
        """加载模型。

        ``preloaded_model`` 是 ``ModelInitThread`` 在子线程里备好的
        ``{'session': InferenceSession, 'labels': [...]}``。
        **传了就直接采用，不在本方法里重建会话** —— 因为本方法可能在主线程
        被调用，重建会话（秒级）会把界面冻住。
        """
        try:
            if (isinstance(preloaded_model, dict)
                    and preloaded_model.get('session') is not None):
                self.session = preloaded_model['session']
                self.labels = list(preloaded_model.get('labels') or [])
                if not self.labels and os.path.isfile(self.label_path):
                    with open(self.label_path, 'r', encoding='utf-8') as f:
                        self.labels = [line.strip() for line in f if line.strip()]
                self._refresh_person_class_ids()
                return True

            import onnxruntime as ort
            sess_options=ort.SessionOptions()
            sess_options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.intra_op_num_threads=4# 使用4核CPU进行推理
            sess_options.inter_op_num_threads=1
            self.session=ort.InferenceSession(self.model_path,sess_options,providers=['CPUExecutionProvider'])
            if os.path.isfile(self.label_path):
                with open(self.label_path, 'r', encoding='utf-8') as f:
                    self.labels = [line.strip() for line in f]
            self._refresh_person_class_ids()
            return True
        except Exception as e:
            print(f'模型加载失败：{str(e)}')
            return False

    @Slot(np.ndarray)
    def predict(self, frame):
        start_time = time.time()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        h, w = frame.shape[:2]
        target_size = 640
        scale = min(target_size / w, target_size / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        resized = cv2.resize(frame, (new_w, new_h))
        canvas = np.full((target_size, target_size, 3), 114, dtype=np.uint8)
        dw = (target_size - new_w) // 2
        dh = (target_size - new_h) // 2
        canvas[dh:dh+new_h, dw:dw+new_w] = resized
        blob = cv2.dnn.blobFromImage(canvas, 1/255.0, (target_size, target_size), swapRB=True, crop=False)
        input_tensor=blob.astype(np.float32)
        # ONNX Runtime 推理
        input_name=self.session.get_inputs()[0].name
        outputs = self.session.run(None, {input_name: input_tensor})
        pred=outputs[0]
        if pred.shape[1]==8400 and pred.shape[2]==84:
            pred=pred.transpose(0,2,1)
        # 阈值每帧从 global_params 现读（2026-09-26 修复）：构造参数只是初值。
        # 之前把 conf/nms 拷进 self.conf_thres 后就再不更新，监视页滑块
        # 形同虚设 —— NMS 阈值只在检测器里生效，完全调不动；置信度阈值
        # 虽在 UI 层还有一道过滤，但低于阈值的框仍会进 NMS 与目标选择，
        # 且画面叠加框走的是不过滤的 last_detection（已同日修复）。
        conf_thres = getattr(self.global_params, 'confidence_thres',
                             self.conf_thres)
        nms_thres = getattr(self.global_params, 'nms_thres', self.nms_thres)
        # 调用后处理函数。v8 传 person 白名单（CHARTER v1.3 唯一类别；
        # 非行人框在 NMS 之前就被滤掉）。v5 路径本期不改（主链路是 v8）。
        if self.model_type == 'v5':
            detections = postprocess_yolov5(outputs, (w, h), scale, dw, dh, conf_thres, nms_thres)
        elif self.model_type == 'v8':
            detections = postprocess_yolov8(outputs, (w, h), scale, dw, dh,
                                            conf_thres, nms_thres,
                                            keep_class_ids=self._person_class_ids)
        target = self.select_target(detections, (w, h))
        inference_time = time.time() - start_time
        self.global_params.inference_fps = 1.0/inference_time if inference_time > 0 else 0.0
        self.detection_ready.emit(target)

    def select_target(self, detections, img_shape):
        """按选择规则从本帧检测里挑出唯一跟踪目标。

        2026-09-26 修复两处：
        1. 旧版开头有 ``if not self.global_params.detection_conf: return 最高置信度``
           —— ``detection_conf`` 是**当前目标置信度的显示值**（初值 0.0、
           无目标帧被清 0），却被当成"规则开关"用。程序启动后它几乎恒为 0，
           于是设置页选什么规则都静默走最高置信度 —— "检测配置没有生效"
           的直接原因。现在规则每帧无条件生效。
        2. 规则精简为两条（用户建议，旧"最大面积/最接近中心"已从 UI 删除）：
           0 = 最高置信度（默认）；1 = 指定类别（按 specific_class_id 过滤，
           同类多框取置信度最高，无该类则本帧无目标）。
           旧值 1/2/3 兜底按规则 0 处理（target_select_rule 不持久化，
           重启必为 0，不存在旧值残留）。
        """
        if not detections:
            return None
        rule = getattr(self.global_params, 'target_select_rule', 0)
        if rule == 1:
            specific_class = getattr(self.global_params, 'specific_class_id', -1)
            filtered = [d for d in detections if d['class_id'] == specific_class]
            if not filtered:
                return None
            return max(filtered, key=lambda d: d['confidence'])
        return max(detections, key=lambda d: d['confidence'])