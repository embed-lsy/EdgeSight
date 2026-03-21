import ncnn
import numpy as np
import time
import sys
import os

# 模型文件路径（当前目录）
param_file = 'yolov8n_simplified.ncnn.param'
bin_file = 'yolov8n_simplified.ncnn.bin'

# 检查文件是否存在
if not os.path.isfile(param_file):
    print(f"错误：找不到参数文件 {param_file}")
    sys.exit(1)
if not os.path.isfile(bin_file):
    print(f"错误：找不到权重文件 {bin_file}")
    sys.exit(1)

# 创建网络并设置线程数
net = ncnn.Net()
net.opt.num_threads = 4

print("正在加载模型...")
if net.load_param(param_file) != 0:
    print("加载参数文件失败")
    sys.exit(1)
if net.load_model(bin_file) != 0:
    print("加载权重文件失败")
    sys.exit(1)
print("模型加载成功")

# 输入输出名称（根据 .param 文件确认）
input_name = 'in0'
output_name = 'out0'

# 创建随机输入（模拟 640x640 RGB 图像）
img = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
mat_in = ncnn.Mat.from_pixels(img, ncnn.Mat.PixelType.PIXEL_RGB, 640, 640)

ex = net.create_extractor()
ex.input(input_name, mat_in)

# 预热（5次）
print("预热中...")
for i in range(5):
    ret, _ = ex.extract(output_name)
    if ret != 0:
        print(f"预热第 {i+1} 次失败，返回码 {ret}")
        sys.exit(1)

# 正式测速（20次）
print("开始测速...")
times = []
for i in range(20):
    start = time.time()
    ret, _ = ex.extract(output_name)
    if ret != 0:
        print(f"第 {i+1} 次推理失败，返回码 {ret}")
        sys.exit(1)
    times.append(time.time() - start)

avg_time_ms = sum(times) / len(times) * 1000
fps = 1000 / avg_time_ms
print(f"\n平均推理时间: {avg_time_ms:.2f} ms")
print(f"FPS: {fps:.2f}")
EOF