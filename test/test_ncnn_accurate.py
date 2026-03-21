
import ncnn
import numpy as np
import time
import sys
import os

param_file = 'yolov8n_simplified.ncnn.param'
bin_file = 'yolov8n_simplified.ncnn.bin'

if not os.path.isfile(param_file) or not os.path.isfile(bin_file):
    print("模型文件不存在")
    sys.exit(1)

net = ncnn.Net()
net.opt.num_threads = 4

print("加载模型...")
if net.load_param(param_file) != 0 or net.load_model(bin_file) != 0:
    print("加载失败")
    sys.exit(1)

input_name = 'in0'
output_name = 'out0'

print("开始精确测速（100次推理，每次输入不同随机图像）...")
times = []

for i in range(100):
    # 每次生成新的随机图像，避免任何可能的缓存影响
    img = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
    mat_in = ncnn.Mat.from_pixels(img, ncnn.Mat.PixelType.PIXEL_RGB, 640, 640)

    ex = net.create_extractor()
    ex.input(input_name, mat_in)

    start = time.perf_counter()
    ret, _ = ex.extract(output_name)
    end = time.perf_counter()

    if ret != 0:
        print(f"推理失败，返回码 {ret}")
        sys.exit(1)

    elapsed_ms = (end - start) * 1000
    times.append(elapsed_ms)

    if (i+1) % 10 == 0:
        print(f"已完成 {i+1} 次，最近一次耗时: {elapsed_ms:.2f} ms")

avg_ms = sum(times) / len(times)
fps = 1000 / avg_ms
print(f"\n平均推理时间: {avg_ms:.2f} ms")
print(f"FPS: {fps:.2f}")

# 打印前10次和后10次的时间，观察是否有明显变化
print("\n前10次耗时 (ms):", [f"{t:.2f}" for t in times[:10]])
print("后10次耗时 (ms):", [f"{t:.2f}" for t in times[-10:]])
