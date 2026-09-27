# 目标类别的典型真实高度（米）。
#
# 这是测距精度的**首要来源**：由 pinhole 模型 Z = fy * H / h 可知，
# 距离与目标真实高度成正比 —— 高度估错 20%，距离就错 20%。
#
# CHARTER v1.4：全链路唯一类别是「行人」，本表因此只剩 person 一项。
# default_object_height 只服务一条**如实降级路径** —— 标签文件缺失时
# person 白名单建不起来（见 core/detector/yolo_detector._refresh_person_class_ids），
# 非 person 的框会漏进来，此时才用到下面的兜底高度。
#
# ⚠️ 已知不适用于本表的情况：人弯腰/坐姿、类别被误识别。这类误差只能靠
#    双源互检（CHARTER 第 4 条）暴露，无法在表里消除。
_OBJECT_HEIGHTS_DEFAULT = {
    'person': 1.70,      # 成年人站姿中位偏上
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
        # 置信度阈值 0.40（2026-09-26 用户反复实测定的值）：
        #   · 低于 0.40：会放进「肢体」而不是完整身体 —— 框不完整意味着
        #     框底边不是脚，接触点法/反解身高判据的前提就不成立，测距直接错；
        #   · 高于 0.40：无效帧明显增多（曲线断、TTC 无样本）。
        # 该阈值下**最小可检测距离约 0.57 m**（再近检测器不出框）——
        # 这是**检测器**的能力下限，不是测距算法的下限，不要试图往下救。
        self.confidence_thres=0.40
        self.nms_thres=0.45
        # 目标选择规则：类别收窄后只剩 0=最高置信度 这一条
        # （原 1=指定类别 已随多类别一并删除，见 core/detector/yolo_detector.select_target）。
        # 这个位置留给 v1.4 的「追踪目标选择」（CHARTER「范围内的」建档条）。
        self.target_select_rule=0
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
        self.camera_height=0.0               # 相机安装高度（米），卷尺量。0=未测量，
                                             # 此时地面接触点法不可用（CHARTER 第 2 条）
        self.height_tolerance=0.35           # 反解身高判据的容差：落在 ±35% 内视为合理
        self.object_heights=dict(_OBJECT_HEIGHTS_DEFAULT)
        self.default_object_height=1.50     # 单类别后只在「标签文件缺失」的降级路径上用到
        self.min_pixel_height=8              # 像素高度下限，低于此值不测距
        # 宽度法（近场参考值，2026-09-25 P1+）：脚出画、左右未裁时的兜底测法
        # Z = fx * 肩宽 / 框宽。肩宽优先取人特征档案（person_profile.json）
        # 里给当前目标量出的值；没有档案时用这个默认值。
        self.person_width_m=0.46
        self.person_profile_path='models/person_profile.json'
        self.distance=0.0                    # 当前目标解算距离（米），None 表示不可解算