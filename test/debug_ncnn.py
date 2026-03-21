
import ncnn
import numpy as np
import sys
import os

# 模型文件
param_file = 'yolov8n_simplified.ncnn.param'
bin_file = 'yolov8n_simplified.ncnn.bin'

# 检查文件
if not os.path.isfile(param_file):
    print(f"错误: 找不到 {param_file}")
    sys.exit(1)
if not os.path.isfile(bin_file):
    print(f"错误: 找不到 {bin_file}")
    sys.exit(1)

print("文件存在，大小:", os.path.getsize(param_file), os.path.getsize(bin_file))

# 创建网络
net = ncnn.Net()
net.opt.num_threads = 4

print("加载参数文件...")
if net.load_param(param_file) != 0:
    print("加载参数文件失败")
    sys.exit(1)

print("加载权重文件...")
if net.load_model(bin_file) != 0:
    print("加载权重文件失败")
    sys.exit(1)

print("模型加载成功")

# 输入输出名称
input_name = 'in0'
output_name = 'out0'

# 创建随机输入
import numpy as np
img = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
mat_in = ncnn.Mat.from_pixels(img, ncnn.Mat.PixelType.PIXEL_RGB, 640, 640)

ex = net.create_extractor()
ex.input(input_name, mat_in)

# 执行一次推理
print("执行推理...")
ret, mat_out = ex.extract(output_name)
if ret != 0:
    print(f"推理失败，返回码 {ret}")
    sys.exit(1)

# 查看输出信息
print("输出 Mat 信息:")
print("  dims:", mat_out.dims)
print("  w:", mat_out.w)
print("  h:", mat_out.h)
print("  c:", mat_out.c)
print("  elemsize:", mat_out.elemsize)
print("  total:", mat_out.total())

# 将输出转换为 numpy 数组并打印形状
out_np = np.array(mat_out)
print("输出 numpy 形状:", out_np.shape)
print("输出 numpy 数据类型:", out_np.dtype)
print("前10个元素:", out_np.flatten()[:10])

print("调试完成")


