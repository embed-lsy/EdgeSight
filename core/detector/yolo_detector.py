import os
import time
import cv2
import numpy as np
import onnxruntime as ort
from PySide6.QtCore import QObject, Slot, Signal,QThread
from .postprocess import postprocess_yolov8,postprocess_yolov5  # 导入后处理函数


class ModelInitThread(QThread):
    init_finished = Signal(bool, str, object)

    def __init__(self, model_path: str, hardware_accel='CPU'):
        super().__init__()
        self.model_path = model_path
        self.hardware_accel = hardware_accel

    def run(self):
        try:
            if not self.model_path or not os.path.isfile(self.model_path):
                self.init_finished.emit(True, "未指定模型路径，跳过加载", None)
                return
            '''
            self.init_finished.emit(True, "开始加载模型……", None)
            model = cv2.dnn.readNetFromONNX(self.model_path)
            model.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            if self.hardware_accel == 'CPU':
                model.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            elif self.hardware_accel == 'GPU':
                model.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
            elif self.hardware_accel == 'NPU':
                model.setPreferableTarget(cv2.dnn.DNN_TARGET_MYRIAD)
            '''
            self.init_finished.emit(True, f"模型加载成功：{os.path.basename(self.model_path)}", None)
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

    def load_model(self, preloaded_model=None):
        try:
            import onnxruntime as ort
            sess_options=ort.SessionOptions()
            sess_options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.intra_op_num_threads=4# 使用4核CPU进行推理
            sess_options.inter_op_num_threads=1
            self.session=ort.InferenceSession(self.model_path,sess_options,providers=['CPUExecutionProvider'])
            if os.path.isfile(self.label_path):
                with open(self.label_path, 'r', encoding='utf-8') as f:
                    self.labels = [line.strip() for line in f]
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
        # 调用后处理函数
        if self.model_type == 'v5':
            detections = postprocess_yolov5(outputs, (w, h), scale, dw, dh, self.conf_thres, self.nms_thres)
        elif self.model_type == 'v8':
            detections = postprocess_yolov8(outputs, (w, h), scale, dw, dh, self.conf_thres, self.nms_thres)
        target = self.select_target(detections, (w, h))
        inference_time = time.time() - start_time
        self.global_params.inference_fps = 1.0/inference_time if inference_time > 0 else 0.0
        self.detection_ready.emit(target)

    def select_target(self, detections, img_shape):
        # 这个方法保持原样
        if not detections:
            return None
        if not self.global_params.detection_conf:
            return max(detections, key=lambda d: d['confidence'])
        rule = self.global_params.target_select_rule
        specific_class = self.global_params.specific_class_id
        h, w = img_shape[:2]
        img_center = (w // 2, h // 2)
        if rule == 0:
            return max(detections, key=lambda d: d['confidence'])
        elif rule == 1:
            return max(detections, key=lambda d: d['width'] * d['height'])
        elif rule == 2:
            def distance_to_center(d):
                cx, cy = d['x'], d['y']
                return (cx - img_center[0])**2 + (cy - img_center[1])**2
            return min(detections, key=distance_to_center)
        elif rule == 3:
            filtered = [d for d in detections if d['class_id'] == specific_class]
            if filtered:
                return max(filtered, key=lambda d: d['confidence'])
            else:
                return None
        else:
            return max(detections, key=lambda d: d['confidence'])