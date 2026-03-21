import ncnn

param = 'yolov5n_sim.ncnn.param'
bin = 'yolov5n_sim.ncnn.bin'

net = ncnn.Net()
if net.load_param(param) != 0:
    print("加载参数失败")
    exit()
if net.load_model(bin) != 0:
    print("加载权重失败")
    exit()

print("可用输入名称：")
for i in range(net.input_count()):
    print(net.input_name(i))

print("可用输出名称：")
for i in range(net.output_count()):
    print(net.output_name(i))