import os
import time
import cv2
import numpy as np
import ncnn
from PySide6.QtCore import QObject, Slot, Signal
from .postprocess import postprocess_yolov8_ncnn, postprocess_yolov5_ncnn  # 导入后处理函数

class NCNNDetector(QObject):
    # 与 YOLODetector 同口径（2026-09-26）：Signal(object) 让 emit(None)
    # 传到槽的就是 None，而不是被签名转换成的空字典。
    detection_ready = Signal(object)

    def __init__(self, param_path, bin_path, label_path, global_params, conf_thres=0.5, nms_thres=0.45,model_type='v5'):
        super().__init__()
        self.param_path = param_path
        self.bin_path = bin_path
        self.label_path = label_path
        self.conf_thres = conf_thres
        self.nms_thres = nms_thres
        self.model_type=model_type
        self.global_params = global_params
        self.net = None
        self.labels = []
        self.input_name = 'in0'      # 从 .param 确认
        self.output_name = 'out0'    # 从 .param 确认

    def load_model(self,preloaded_model=None):
        try:
            self.net = ncnn.Net()
            self.net.opt.num_threads = 4
            print(f"加载参数文件: {self.param_path}")
            if self.net.load_param(self.param_path) != 0:
                print("加载参数文件失败")
                return False
            print(f"加载权重文件: {self.bin_path}")
            if self.net.load_model(self.bin_path) != 0:
                print("加载权重文件失败")
                return False
            print("模型加载成功")
            if os.path.isfile(self.label_path):
                with open(self.label_path, 'r', encoding='utf-8') as f:
                    self.labels = [line.strip() for line in f]
                print(f"加载标签 {len(self.labels)} 个")
            return True
        except Exception as e:
            print(f'NCNN模型加载异常: {e}')
            return False

    @Slot(np.ndarray)
    def predict(self, frame):
        start_time = time.time()
        # 预处理（与之前相同）
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
        mat_in = ncnn.Mat.from_pixels(canvas, ncnn.Mat.PixelType.PIXEL_RGB, target_size, target_size)

        ex = self.net.create_extractor()
        ex.input(self.input_name, mat_in)
        ret, mat_out = ex.extract(self.output_name)
        if ret != 0:
            print("推理失败")
            return

        out_np = np.array(mat_out)  # 根据模型不同，形状可能是 (84,8400) 或 (25200,85) 或 (1,25200,85)

        # 根据模型类型选择后处理
        if self.model_type == 'v5':
            # YOLOv5 输出通常为 (1,25200,85) 或 (25200,85)
            if out_np.ndim == 3:
                out_np = out_np[0]  # 变成 (25200,85)
            outputs = [out_np[np.newaxis, :, :]]  # 包装为 (1,25200,85)
            detections = postprocess_yolov5_ncnn(outputs, (w, h), scale, dw, dh, self.conf_thres, self.nms_thres)
        elif self.model_type == 'v8':
            # YOLOv8 输出为 (84,8400)，需要添加 batch 维度
            if out_np.ndim == 2:
                out_np = out_np[np.newaxis, :, :]  # (1,84,8400)
            outputs = [out_np]
            detections = postprocess_yolov8_ncnn(outputs, (w, h), scale, dw, dh,
                                                  self.conf_thres, self.nms_thres)
        else:
            print(f"未知模型类型: {self.model_type}")
            return

        print(f"检测到 {len(detections)} 个目标")
        for i, d in enumerate(detections[:5]):  # 只打印前5个避免刷屏
            print(f"目标 {i}: x={d['x']}, y={d['y']}, w={d['width']}, h={d['height']}, conf={d['confidence']:.2f}")

        target = self.select_target(detections, (w, h))

        inference_time = time.time() - start_time
        self.global_params.inference_fps = 1.0 / inference_time if inference_time > 0 else 0.0
        self.detection_ready.emit(target)

    def select_target(self, detections, img_shape):
        if not detections:
            return None
        h, w = img_shape[:2]
        img_center = (w // 2, h // 2)
         # 过滤掉边界附近的框（例如距离边界小于20像素）
        filtered = [d for d in detections if d['x'] > 20 and d['x'] < w-20 and d['y'] > 20 and d['y'] < h-20]
        if not filtered:
            filtered = detections  # 如果没有框在内部，则用全部
        # 按置信度降序排序
        sorted_dets = sorted(filtered, key=lambda d: d['confidence'], reverse=True)
        max_conf = sorted_dets[0]['confidence']
        
        # 找出所有置信度接近最大值的框（允许微小误差）
        candidates = [d for d in sorted_dets if abs(d['confidence'] - max_conf) < 0.01]
        if len(candidates) == 1:
            return candidates[0]
        else:
            # 多个框置信度相同，选择离中心最近的
            return min(candidates, key=lambda d: (d['x']-img_center[0])**2 + (d['y']-img_center[1])**2)