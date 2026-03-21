# 第一步：自动安装所有缺失依赖
import subprocess
import sys

def install_deps():
    deps = [
        "onnxscript>=0.1.0",  # 解决ModuleNotFoundError: onnxscript
        "onnx>=1.12.0",
        "torch>=2.0.0",
        "torchvision>=0.15.0"
    ]
    for dep in deps:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", dep, "--upgrade"])
            print(f"✅ 安装/升级 {dep} 成功")
        except Exception as e:
            print(f"⚠️  {dep} 安装失败（忽略，可能已存在）：{e}")

# 先安装依赖
install_deps()

# 第二步：导出float32输入的YOLOv5n ONNX模型
import torch

# 加载YOLOv5n模型（禁用AutoShape，避免导出报错）
model = torch.hub.load(
    'ultralytics/yolov5', 
    'yolov5n', 
    pretrained=True,
    trust_repo=True  # 解决信任仓库警告
)
model.eval()
model.float()  # 强制float32，禁用float16

# 移除AutoShape（关键！避免导出报错）
model = model.model

# 定义float32输入
dummy_input = torch.randn(1, 3, 640, 640, dtype=torch.float32)

# 导出ONNX（兼容旧版本ONNX Runtime）
torch.onnx.export(
    model,
    dummy_input,
    "yolov5n_fp32_final.onnx",
    input_names=["images"],
    output_names=["output"],
    opset_version=12,  # 关键：用opset 12，兼容所有ONNX Runtime版本
    do_constant_folding=True,
    verbose=False,
    export_params=True
)

print("\n🎉 导出成功！")
print("📁 float32输入的YOLOv5n ONNX模型路径：", "yolov5n_fp32_final.onnx")
print("👉 下一步：将该文件复制到 VisServo-Core\\models\\ 目录，运行INT8量化代码")