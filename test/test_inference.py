import cv2
import numpy as np
import onnxruntime as ort
import time
import psutil
import os

# 配置
model_path = 'VisServo-Core\models\yolov8n_int8.onnx' 
camera_idx = 0
frame_skip = 2  # 每隔几帧推理一次，模拟你的 inference_interval

# 加载模型
print("Loading model...")
sess_options = ort.SessionOptions()
sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
session = ort.InferenceSession(model_path, sess_options, providers=['CPUExecutionProvider'])
input_name = session.get_inputs()[0].name
print("Model loaded.")

# 打开摄像头
cap = cv2.VideoCapture(camera_idx)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)  # 可以调整
cap.set(cv2.CAP_PROP_FPS, 30)

if not cap.isOpened():
    print("Cannot open camera")
    exit()

# 预热
print("Warming up...")
for _ in range(5):
    ret, frame = cap.read()
    if not ret:
        continue
    # 预处理（简化，只做resize和归一化，不画布填充）
    h, w = frame.shape[:2]
    target_size = 640
    scale = min(target_size / w, target_size / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(frame, (new_w, new_h))
    canvas = np.full((target_size, target_size, 3), 114, dtype=np.uint8)
    dw = (target_size - new_w) // 2
    dh = (target_size - new_h) // 2
    canvas[dh:dh+new_h, dw:dw+new_w] = resized
    blob = cv2.dnn.blobFromImage(canvas, 1/255.0, (target_size, target_size), swapRB=True, crop=False)
    input_tensor = blob.astype(np.float32)
    _ = session.run(None, {input_name: input_tensor})

print("Start testing...")
fps_list = []
frame_count = 0
last_time = time.time()
process = psutil.Process(os.getpid())

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1
    if frame_count % (frame_skip + 1) != 0:
        continue

    # 预处理（同上）
    start_pre = time.time()
    h, w = frame.shape[:2]
    target_size = 640
    scale = min(target_size / w, target_size / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(frame, (new_w, new_h))
    canvas = np.full((target_size, target_size, 3), 114, dtype=np.uint8)
    dw = (target_size - new_w) // 2
    dh = (target_size - new_h) // 2
    canvas[dh:dh+new_h, dw:dw+new_w] = resized
    blob = cv2.dnn.blobFromImage(canvas, 1/255.0, (target_size, target_size), swapRB=True, crop=False)
    input_tensor = blob.astype(np.float32)
    pre_time = time.time() - start_pre

    # 推理
    start_inf = time.time()
    outputs = session.run(None, {input_name: input_tensor})
    inf_time = time.time() - start_inf

    # 后处理
    start_post = time.time()
    # 这里可以调用你的 postprocess，但为了速度测试，可以跳过
    post_time = time.time() - start_post

    total_time = pre_time + inf_time + post_time
    fps = 1.0 / total_time
    fps_list.append(fps)

    if len(fps_list) % 30 == 0:
        avg_fps = sum(fps_list[-30:]) / 30
        mem = process.memory_info().rss / 1024 / 1024
        print(f"Avg FPS (last 30): {avg_fps:.2f}, Memory: {mem:.1f} MB, Pre: {pre_time*1000:.1f}ms, Inf: {inf_time*1000:.1f}ms, Post: {post_time*1000:.1f}ms")

    # 防止无限循环，可以设置一个帧数上限
    if frame_count > 500:
        break

cap.release()
print("Test finished.")