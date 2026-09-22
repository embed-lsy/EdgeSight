# 各目标类别的典型真实高度（米）。
#
# 这是测距精度的**首要来源**：由 pinhole 模型 Z = fy * H / h 可知，
# 距离与目标真实高度成正比 —— 高度估错 20%，距离就错 20%。
# 因此这里只登记"高度稳定、可查证"的类别；查不到的走 default_object_height 兜底。
#
# ⚠️ 已知不适用于本表的情况：人弯腰/坐姿、车辆载重导致姿态变化、
#    类别被误识别。这类误差只能靠双源互检（CHARTER 第 4 条）暴露，无法在表里消除。
_OBJECT_HEIGHTS_DEFAULT = {
    'person': 1.70,      # 成年人站姿中位偏上
    'bicycle': 1.00,     # 含骑行者的整体高度下限
    'car': 1.50,         # 轿车车顶高度
    'motorcycle': 1.10,
    'bus': 3.20,
    'truck': 3.20,
}


class GlobalParams:
    def __init__(self):
        #运动时数据
        self.detection_x=320
        self.detection_y=240
        self.detection_width=0
        self.detection_height=0
        self.detection_conf=0.0
        self.detection_class=-1
        self.fps=30          #摄像头帧率
        self.inference_fps=0 #模型推理FPS
        #检测配置
        self.sample_freq=30  #数据采样频率，单位Hz
        self.base_width=100 #目标基准宽度（旧伪距公式遗留，已被真标定取代，保留备用）
        self.confidence_thres=0.25
        self.nms_thres=0.45
        self.target_select_rule=0
        self.specific_class='笔记本电脑'
        self.specific_class_id=-1
        self.plot_enable=False
        #AI模型配置
        self.mode_path=''
        self.label_path=''
        self.hardware_accel='CPU'
        #推理结果
        self.credibility=0.0
        self.target_category='未知'
        # ------------------------------------------------------------------
        # 相机标定与几何测距（CHARTER「范围内的」第 1、2 条）
        # ------------------------------------------------------------------
        self.calib_path='models/calib.json'  # 标定结果持久化路径
        self.intrinsics=None                 # CameraIntrinsics，启动时尝试加载
        self.calibrated=False                # 是否已有可用内参（区别于旧版的"参数已应用"）
        self.invalid_reason=''               # 内参不可用时的原因，供 UI 显示
        self.pitch_deg=0.0                   # 相机俯仰角，向下为正，单位度
        self.object_heights=dict(_OBJECT_HEIGHTS_DEFAULT)
        self.default_object_height=1.50
        self.min_pixel_height=8              # 像素高度下限，低于此值不测距
        self.distance=0.0                    # 当前目标解算距离（米），None 表示不可解算