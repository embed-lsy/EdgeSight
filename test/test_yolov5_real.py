import ncnn
import numpy as np
import sys

param = 'yolov5n_sim.ncnn.param'
bin = 'yolov5n_sim.ncnn.bin'
input_name = 'in0'
output_name = 'out0'

net = ncnn.Net()
net.opt.num_threads = 4
if net.load_param(param) != 0:
    print("加载参数失败")
    sys.exit(1)
if net.load_model(bin) != 0:
    print("加载权重失败")
    sys.exit(1)

# 创建随机输入
mat_in = ncnn.Mat.from_pixels(np.random.randint(0,255,(640,640,3),'uint8'), ncnn.Mat.PixelType.PIXEL_RGB, 640, 640)

ex = net.create_extractor()
ex.input(input_name, mat_in)
ret, mat_out = ex.extract(output_name)
if ret != 0:
    print("extract 失败")
    sys.exit(1)

# 将输出转为 numpy
out_np = np.array(mat_out)
print("输出形状:", out_np.shape)
print("输出数据类型:", out_np.dtype)
print("输出最小值:", out_np.min())
print("输出最大值:", out_np.max())
print("输出平均值:", out_np.mean())
print("前10个元素:", out_np.flatten()[:10])