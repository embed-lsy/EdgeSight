import onnx
import numpy as np
import cv2
import os
from onnxruntime.quantization import (
    quantize_static,
    CalibrationDataReader,
    QuantType,
    CalibrationMethod
)

# ====================== 配置（仅需修改这3行） ======================
FP32_ONNX_PATH = r"VisServo-Core\models\yolov5\yolov5n.onnx"  # 你的float32模型路径
INT8_ONNX_PATH = r"VisServo-Core\models\yolov5\yolov5n_int8.onnx"    # 量化后模型保存路径
CALIB_IMGS_DIR = r"VisServo-Core\test\calib_imgs"            # 校准图片目录

# ====================== 校准数据读取器（适配float32） ======================
class YOLOCalibReader(CalibrationDataReader):
    def __init__(self):
        self.img_paths = [os.path.join(CALIB_IMGS_DIR, f) for f in os.listdir(CALIB_IMGS_DIR) 
                        if f.endswith(('.jpg', '.png', '.jpeg'))] if os.path.exists(CALIB_IMGS_DIR) else []
        self.current_idx = 0
        # 验证校准数据
        if len(self.img_paths) == 0:
            raise ValueError(f"校准目录 {CALIB_IMGS_DIR} 中无图片，请放入100-200张测试图")

    def _preprocess(self, img_path):
        """YOLOv5标准预处理，输出float32"""
        img = cv2.imread(img_path)
        img = cv2.resize(img, (640, 640), interpolation=cv2.INTER_LINEAR)
        img = img[:, :, ::-1].transpose(2, 0, 1)  # BGR→RGB, HWC→CHW
        img = img.astype(np.float32) / 255.0      # 强制float32（关键）
        return np.expand_dims(img, 0)

    def get_next(self):
        if self.current_idx >= len(self.img_paths):
            return None
        input_data = self._preprocess(self.img_paths[self.current_idx])
        self.current_idx += 1
        return {"images": input_data}

# ====================== 执行INT8量化 ======================
def quantize_yolov5n():
    # 1. 验证输入模型
    if not os.path.exists(FP32_ONNX_PATH):
        raise FileNotFoundError(f"float32模型不存在：{FP32_ONNX_PATH}")
    model = onnx.load(FP32_ONNX_PATH)
    onnx.checker.check_model(model)
    print("✅ float32模型验证通过")

    # 2. 初始化校准器
    calib_reader = YOLOCalibReader()
    print(f"✅ 校准数据加载完成，共 {len(calib_reader.img_paths)} 张图片")

    # 3. 静态INT8量化（无类型冲突）
    quantize_static(
        model_input=FP32_ONNX_PATH,
        model_output=INT8_ONNX_PATH,
        calibration_data_reader=calib_reader,
        quant_format=QuantType.QInt8,
        op_types_to_quantize=['Conv', 'MatMul'],  # 只量化核心计算层
        weight_type=QuantType.QInt8,
        calibrate_method=CalibrationMethod.MinMax,
        use_external_data_format=False
    )

    # 4. 验证量化模型
    import onnxruntime as ort
    sess = ort.InferenceSession(INT8_ONNX_PATH, providers=['CPUExecutionProvider'])
    test_input = np.random.rand(1, 3, 640, 640).astype(np.float32)
    outputs = sess.run(None, {"images": test_input})
    print(f"✅ INT8量化完成！模型路径：{INT8_ONNX_PATH}")
    print(f"✅ 量化模型验证成功，输出形状：{outputs[0].shape}")

if __name__ == "__main__":
    quantize_yolov5n()