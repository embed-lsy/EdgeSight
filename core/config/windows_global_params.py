# 目标类别的典型真实高度（米）。
#
# 这是测距精度的**首要来源**：由 pinhole 模型 Z = fy * H / h 可知，
# 距离与目标真实高度成正比 —— 高度估错 20%，距离就错 20%。
#
# CHARTER v1.4：全链路唯一类别是「行人」，本表因此只剩 person 一项。
#
# **表外类别一律拒绝出距离**（2026-09-27 用户明确要求）。原先有一条
# 「标签文件缺失时用 default_object_height 兜底」的降级路径，现已删除：
# 表外类别可能不是人（定位外目标），也可能是标签没加载导致类别未知 ——
# 两种情形都拿不到「这个目标真实有多高」，给数字就是编数。
# 标签缺失时正确行为是**如实报不可测**并提示去设置页检查标签文件。
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
        # 追踪目标选择（CHARTER v1.4「建档 + 追踪目标选择」）：设置页**单选**
        # 一条指纹档案作为唯一追踪目标，这里存它的 profile_id；'' = 未指定。
        # 原先的「目标选择规则」（0=最高置信度 / 1=指定类别）已随类别收窄删除：
        # 单类别下规则只剩一条，检测器侧 select_target 现在恒取最高置信度。
        self.track_target_id=''
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
        # 框底边抬升量（米）：检测框底边并不落在脚上时（2026-10-01 实测，底边在
        # 离地 0.249 m 的小腿中部），接触点法按 Z=(H−h_off)/tan(α) 修正。
        # 0 = 「框底边 == 脚」的旧行为。由「已知相机高度 + 解抬升量」标定得出。
        self.foot_offset_m=0.0
        self.height_tolerance=0.35           # 反解身高判据的容差：落在 ±35% 内视为合理
        self.object_heights=dict(_OBJECT_HEIGHTS_DEFAULT)
        self.min_pixel_height=8              # 像素高度下限，低于此值不测距
        # 宽度法（近场参考值，2026-09-25 P1+）：脚出画、左右未裁时的兜底测法
        # Z = fx * 肩宽 / 框宽。肩宽取自哪里只有两条分支（2026-09-30 收紧，
        # 见 PersonFeatureTracker.ranging_width_m 与 MainWindow._sync_ranging_width）：
        #   · 指定了追踪目标 -> 该目标档案（person_profile.json）里量出的肩宽；
        #   · 未指定 / 目标还没量到 -> **就用下面这个默认值**，不借用画面里
        #     恰好匹配上的人的档案值（用户要求：「有追踪目标的时候用目标的
        #     肩宽，没有的时候就不用动」）。
        # ⚠️ 这是「用户默认值」，运行时**绝不会被改写成某个档案的肩宽** ——
        # 每帧实际生效值在 ranger.config.person_width_m。两处职责别混：
        # 混在一起会让「换目标/取消目标」后仍沿用上一个人的肩宽，且不报错。
        self.person_width_m=0.46
        # 相对仓库根解析（不走当前工作目录），见 main_windows._resolve_repo_path
        self.person_profile_path='models/person_profile.json'
        # OSNet 外观嵌入的匹配阈值（余弦）。⚠️ **占位值，不是校准值**：
        # 取 0.50 的锚点是「同一人跨会话实测中位 0.502」（probe_osnet_reid.py）；
        # 取略低是为了先保证「认得出自己」。**异人分布当前无数据**
        # （既有录制里只有一个人，缺负样本），所以偏松偏紧都无法证伪。
        # 待含第二位真人的录制到手后重新标定 —— 在那之前 UI 会同时显示
        # 实际分数与门槛，让「认不出」和「门槛定错」能被分辨。
        self.reid_match_threshold=0.50
        self.distance=0.0                    # 当前目标解算距离（米），None 表示不可解算