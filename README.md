
# EdgeSight

一个跨平台的实时目标检测监控与分析系统，支持 Windows 与树莓派 Linux 双平台，集成 YOLOv5/v8 模型推理，提供可视化监控界面、深度数据分析及灵活的参数配置功能。

> **⚠️ 升级进行中**：本项目正在进行「单目视觉感知栈」升级（相机真标定、几何测距等能力，见 `CHARTER.md`）。
> **当前开发重心在 Windows 端**；树莓派 Linux 端（`main_raspberry.py`）代码冻结、**正在升级开发中**，
> 升级完成后再同步移植，期间其行为以 main 分支历史版本为准。


## 功能特性

### 监控界面
- 实时显示原始图像与 AI 处理后的图像
- 叠加显示检测框坐标（x, y）、置信度、目标类别
- 支持实时微调置信度阈值与 NMS 阈值
- 实时展示推理 FPS 与画面 FPS

### 深度分析界面
- 实时绘制检测框 x, y 坐标变化曲线并提供异常提示
- 同步展示检测框宽度/高度与目标距离的关联曲线
- 实时监控检测框置信度及其阈值变化趋势
- 绘制推理 FPS 波动曲线
- 可视化展示 CPU 与内存占用进度条

### 设置界面
- 灵活选择模型文件（支持 YOLOv5/v8 及其 INT8 量化模型）
  - Windows：仅支持 ONNX 格式
  - 树莓派 Linux：支持 ONNX 与 NCNN 格式
- 可选硬件加速器（CPU/GPU/NPU，依平台支持情况而定）
- 自定义目标选择规则（最高置信度/最接近中心/指定类别）
- 相机标定：棋盘格采集 → 求解内参 → 持久化（`models/calib.json`），标定状态实时显示
- 几何测距：基于内参与目标真实高度的 pinhole 逆运算，未标定时明确提示不可用（不输出猜测值）
- 支持设置基准宽度、采样频率
- 一键应用运行参数并重载模型
- 可自由开启/关闭深度分析模块


## 支持平台与模型

| 平台          | 支持模型格式   | 推荐推理引擎 |
|---------------|----------------|--------------|
| Windows       | ONNX           | OpenCV DNN / ONNX Runtime |
| 树莓派 Linux  | ONNX, NCNN     | NCNN (优先) / ONNX Runtime |


## 性能对比

以下为核心优化阶段的测试数据（基于 YOLOv8 模型）：

| 阶段          | 平台          | 模型       | 推理引擎    | FPS  | 优化说明                     |
|---------------|---------------|------------|-------------|------|------------------------------|
| 初始版本      | Windows PC    | YOLOv8     | ONNX Runtime | 10.0   | 基线版本                     |
| 量化优化      | Windows PC    | YOLOv8 INT8| OpenCV DNN  | 14.5  | 推理速度提升约 4 倍          |
| 引擎切换      | 树莓派 4B     | YOLOv8 INT8| NCNN        | 2.35 | 较 ONNX Runtime 提升约 3 倍  |
| 最终方案      | 树莓派 4B     | YOLOv5 INT8| NCNN        | 4.5 | 检测框/置信度正常，CPU 占用极低 |


## 安装与部署

### 环境依赖
- Python 3.8+
- PyQt6
- OpenCV
- ONNX Runtime (可选，用于 Windows/树莓派 ONNX 推理)
- NCNN (仅树莓派需要，用于 NCNN 模型推理)

### Windows 安装
```bash
# 克隆仓库
git clone https://github.com/fdagtfedshe/EdgeSight.git
cd EdgeSight

# 安装依赖
pip install PyQt6 opencv-python onnxruntime

# 运行程序
python main_windows.py
```

### 树莓派 Linux 安装
```bash
# 克隆仓库
git clone https://github.com/fdagtfedshe/EdgeSight.git
cd EdgeSight

# 安装基础依赖
pip install PyQt6 opencv-python

# 安装 ONNX Runtime (可选)
# 参考官方文档安装树莓派对应版本

# 安装 NCNN (可选，推荐)
# 参考 NCNN 官方文档编译安装树莓派版本

# 运行程序
python main_raspberry.py
python main_windows.py
```


## 使用说明

1. **选择模型与标签**：在“设置”界面选择对应的模型文件（.onnx/.param）与标签文件（.txt）。
2. **配置硬件与规则**：选择硬件加速器、目标选择规则，设置基准宽度等参数。
3. **相机标定（首次使用前必做一次）**：打印一张 9×6 内角点棋盘格（方格边长需与程序中设置一致），
   在“设置 → 相机标定”中填入棋盘格规格，点击“采集一帧”开始采集，
   让棋盘格在画面中变换位置与倾斜角（覆盖四角、至少 10 帧），点击“求解并保存”。
   内参会持久化，换相机才需重标。
4. **应用参数**：点击“一键标定”按钮使模型与运行参数生效（此按钮不做相机标定）。
5. **实时监控**：在“监控”界面查看检测结果，微调阈值以优化效果。
6. **深度分析**：在“深度分析”界面查看各指标曲线（含几何测距曲线），监控系统运行状态。


## 项目结构

```
EdgeSight/
├── core/                  # 核心功能模块
│   ├── calibration.py     # 相机标定与几何测距（pinhole 逆运算）
│   ├── camera/            # 相机驱动与图像采集
│   ├── config/            # 平台参数配置（Windows / 树莓派）
│   └── detector/          # 目标检测推理封装（ONNX Runtime / NCNN）
├── models/                # 模型文件存放目录（yolov5 / yolov8 / labels）
├── test/                  # 测试程序与脚本
├── ui/                    # Qt UI 界面代码
├── main_raspberry.py      # 树莓派 Linux 入口程序（冻结，升级中）
├── main_windows.py        # Windows 入口程序
├── CHARTER.md             # 项目定位文档
└── README.md
```


## 研发历程

1. **初始阶段**：基于 ONNX Runtime 部署 YOLOv8 模型，在 PC 和树莓派上运行，发现树莓派性能不理想。
2. **量化尝试**：切换至 OpenCV DNN 并将模型量化为 INT8，PC 端速度提升约 4 倍，但树莓派无明显改善。
3. **模型对比**：尝试 YOLOv5 及其 INT8 模型，效果均不如 YOLOv8，决定继续基于 YOLOv8 优化。
4. **参数调优**：在树莓派上测试 YOLOv8 INT8，通过降低帧率、优化 ONNX 线程等方式摸清最佳参数，但性能提升有限。
5. **引擎切换**：转向 NCNN 引擎，在树莓派上测试 YOLOv8 NCNN 模型，解决虚假 FPS 问题后，真实 FPS 达 2.35（约 3 倍提升），但部署后出现检测框异常、置信度恒为 1 的问题。
6. **问题排查**：推测与 softmax 层有关，尝试后处理移除 softmax 未解决，最终切换至 YOLOv5 NCNN 方案，纯脚本测试 FPS 达 59.52，部署至主程序后 FPS 稳定在 1.8-2.0，检测框与置信度正常，CPU 占用极低。


## 贡献

欢迎提交 Issue 或 Pull Request 来改进 EdgeSight！


## 许可证

[MIT License](LICENSE)
