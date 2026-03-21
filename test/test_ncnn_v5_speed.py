import ncnn
import numpy as np
import time
import sys

param = 'yolov5n.ncnn.param'
bin = 'yolov5n.ncnn.bin'

net = ncnn.Net()
net.opt.num_threads = 4
net.load_param(param)
net.load_model(bin)

# 创建随机输入 (640x640 RGB)
mat_in = ncnn.Mat.from_pixels(np.random.randint(0,255,(640,640,3),'uint8'), ncnn.Mat.PixelType.PIXEL_RGB, 640, 640)
ex = net.create_extractor()
ex.input('in0', mat_in)

# 预热
for _ in range(5):
    ex.extract('out0')

# 测速
times = []
for _ in range(20):
    start = time.perf_counter()
    ex.extract('out0')
    times.append(time.perf_counter() - start)

avg_time = sum(times) / len(times) * 1000
print(f'纯推理平均时间: {avg_time:.2f} ms, FPS: {1000/avg_time:.2f}')