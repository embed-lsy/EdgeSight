import sys
sys.path.append('/home/lsy/VisServo-Core')
from core.detector.ncnn_detector import NCNNDetector
import cv2
import numpy as np

# 配置路径
param = '/home/lsy/VisServo-Core/models/yolov8/yolov8n_simplified.ncnn.param'
bin = '/home/lsy/VisServo-Core/models/yolov8/yolov8n_simplified.ncnn.bin'
label = '/home/lsy/VisServo-Core/models/coco_labels.txt'  # 如果有标签文件

class DummyParams:
    detection_conf = 0.0
    target_select_rule = 0
    specific_class_id = -1
    inference_fps = 0

global_params = DummyParams()

detector = NCNNDetector(param, bin, label, global_params)
if detector.load_model():
    print("模型加载成功")
    # 读取一帧图像测试
    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()
    if ret:
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        detector.predict(frame_rgb)
    cap.release()
else:
    print("加载失败")