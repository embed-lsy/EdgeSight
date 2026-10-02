from PySide6.QtWidgets import (QApplication,QPushButton,QBoxLayout,QWidget,QGroupBox,QLabel,
                               QMessageBox,QFileDialog,QStatusBar,QInputDialog,
                               QCheckBox,QDoubleSpinBox,QHBoxLayout,QComboBox)
from PySide6.QtCore import Qt,Slot,QTimer,QThread,Signal,QObject
from PySide6.QtGui import QIcon,QPixmap,QImage
from ui.Ui_EdgeSightMain import Ui_Form
from core.config.windows_global_params import GlobalParams
from core.camera.opencv_camera import CameraInitThread
from core.detector import ModelInitThread, YOLODetector
from core.calibration import (CameraCalibrator, CameraIntrinsics,
                              GeometricRanger, RangingConfig, RangingResult,
                              compute_box_visibility, solve_intrinsics,
                              solve_mount_params, save_mount_params,
                              load_mount_params, canonical_class_name,
                              display_class_name, FootClipHysteresis,
                              distances_from_box_height, BODY_SPAN_PRIOR_M,
                              BODY_SPAN_PRIOR_REL_SIGMA)
from core.person_model import PersonFeatureTracker, SpeedGate
from core.ttc import TTCEstimator, TTCResult, TTCLevel, classify_ttc
from core.ranging_filter import DistanceFilter
from core.recorder import Recorder, Replayer, FrameRecord
from core.reid_probe import ReidProbe
# OSNet 外观嵌入（CHARTER v1.4「特征指纹」第二步）：建档时提取、认人时比对。
# 与 reid_probe 的**区别要分清**：那个只落盘、不决策（定阈值用的原始数据）；
# 这个直接决定「本帧的人是不是追踪目标」，是档案的一部分。
from core.reid_osnet import DEFAULT_MODEL_PATH as REID_MODEL_PATH, OsnetEmbedder
# 摄像头设备识别（CHARTER「范围内的」第 1 条：内参按设备记忆）
from core.camera.device_identity import (IdentityReport, enumerate_cameras,
                                        resolve_active_device)
from core import camera_profiles as cam_profiles
from typing import Optional
from collections import deque
import sys
import cv2
import json
import numpy as np
import pyqtgraph as pg
import os
import time


# 嵌入来源标记：写进档案、匹配时逐条比对。换模型后旧嵌入与新嵌入**不同源**，
# 拿余弦去比会得到一个"看着正常"的怪值（同是 512 维、不报错）——
# 所以宁可让它们不可比（跳过），也不产出无意义的分数。
_REID_TAG = os.path.splitext(os.path.basename(REID_MODEL_PATH))[0]

# ---- 摄像头掉线自愈（2026-10-02 用户实测：挂机半小时后回来，画面与检测框冻结）----
# 根因：OpenCV 的 cap 在设备被系统挂起/重置后会**永久读不到帧**，而主循环原来
# 是 `if not ret: return` —— 不计数、不重连、不提示，于是画面永远停在最后一帧
# （连着上面那个检测框一起），看着就像「检测框不动、人也认不出来」。
# 所以掉线必须能被**发现**、**自愈**、并且**让用户看见**。
#
# 判定阈值为什么是 10 帧：摄像头偶发的单帧读取失败是正常抖动（实测千分之几），
# 连续 10 次（约 0.3 s）就几乎只可能是掉线。太灵敏会把正常抖动当成掉线，
# 反复 release/open 反而把画面搞断。
CAM_FAIL_STREAK = 10
# 重连退避：失败后隔多久再试（指数退避，上限 30 s）。
# 用退避而不是立刻重试，是因为设备刚掉线时驱动往往还没准备好，
# 立刻重试大概率再失败，白占一次「打开设备」的秒级开销。
CAM_RETRY_BASE_S = 2.0
CAM_RETRY_MAX_S = 30.0
# 背压：允许「正在算的那帧 + 排队的那帧」，再多就丢。
# 为什么不无条件排队：帧是**跨线程**投递给检测器的（主线程 emit →
# 检测器线程的事件队列）。一旦处理速度跟不上发帧速度，队列就会无限变长 ——
# 每帧 640x480x3 约 900 KB，半小时能堆到几万帧。表现不是报错，而是
# 「检测延迟越来越大」，用户看到的就是几帧之前的结果（框不动）。
# 丢旧帧保实时，是这类实时链路的标准做法：宁可少算几帧，也不能让延迟发散。
# 2 的依据：留 1 帧缓冲吸收抖动，再多的排队帧已经没有意义（结果出来就过期了）。
MAX_INFLIGHT_FRAMES = 2
# 检测心跳：摄像头在出帧，但超过这么久没有一次检测回调 = 检测链路失联。
# 依据：检测器每 4 帧必回调一次（无目标时发 None，见 YOLODetector.predict），
# 16 FPS 下约 0.25 s 一次；给 8 s 是留足「模型加载/换模型/系统卡顿」的余量。
DET_HEARTBEAT_TIMEOUT_S = 8.0

# 「已建档：xxx」这类一次性结论在标定页大字上保留的秒数。保护期内实时进度
# 刷新的**大字**不覆盖它 —— 否则刚响完提示音，下一次节流刷新（≤5 帧）就把
# 结论冲掉，用户根本看不到（verify_enroll_wiring 的 D/E 两项抓到过）。
_ENROLL_BIG_HOLD_S = 5.0


def _resolve_repo_path(path: str) -> str:
    """把「相对仓库根」的资源路径解析成绝对路径（本来就是绝对的则原样返回）。

    项目里所有资源路径都写成相对形式（``models/calib.json``、
    ``models/person_profile.json``），而它们相对的是**仓库根**，不是
    「当前工作目录」。从别处启动程序（快捷方式、IDE、桌面双击、别的项目
    的工作目录）时相对路径会解析到别的地方，而各处的失败方式**全是静默的**：

      · 标定加载不到  -> 以「本设备未标定」运行（至少还有提示）；
      · 人特征档案加载不到 -> 档案库为空、追踪目标为 None、**身份门整条失效**，
        近场框跨度法（横）回落默认肩宽 —— 界面一切正常，一句报错都没有。

    ``calib_path`` 早先已经单独打了这个补丁（见 ``load_calibration``），
    这里收成一个函数供各处共用，免得以后新加一条资源路径又漏一次。
    """
    if os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), path)


# ---------------------------------------------------------------------------
# 深度分析「距离曲线」的着色（pyqtgraph 颜色）。
# CHARTER v1.4：全链路唯一类别是「行人」，曲线只剩三种情形 ——
# 有读数（人）、没有读数（未知）、以及不该出现的类别名。
# 类别名统一走 canonical_class_name 归一化，保证换标签文件颜色不漂移。
# ---------------------------------------------------------------------------
_PERSON_PEN_COLOR = 'g'                  # 人：绿（与旧版距离曲线同色，观感延续）
_UNKNOWN_PEN_COLOR = (214, 40, 40)       # 「未知」固定红色（2026-09-26 用户定稿）：
                                         # 距离曲线上**没有读数**的帧画成红色 0 线。
                                         # 不用哈希兜底 —— str 哈希带进程随机盐，
                                         # 颜色会一次运行一个样。
_UNEXPECTED_PEN_COLOR = (130, 130, 130)  # 不该出现的类别名：只在「标签文件缺失」
                                         # 的降级路径上可能冒出来，给中性灰，
                                         # 以免与「无读数」的红混淆。


def _class_pen_color(cls_name):
    """距离曲线着色：单类别下只剩「人 / 未知」两种。"""
    canon = canonical_class_name(cls_name or '未知')
    if canon == 'person':
        return _PERSON_PEN_COLOR
    if canon == '未知':
        return _UNKNOWN_PEN_COLOR
    return _UNEXPECTED_PEN_COLOR


# ---------------------------------------------------------------------------
# 回放曲线「按 TTC 分级分段着色」的调色板。
# 与监视页 TTC 告警色、分析页阈值虚线**同源同值** —— 同一个分级在哪里都是
# 同一个颜色，否则"红色到底代表危险还是代表某一类目标"就说不清了。
# ---------------------------------------------------------------------------
_TTC_LEVEL_COLORS = {
    TTCLevel.NONE:     (130, 130, 130),   # 无告警（含未在接近/不可算）：中性灰
    TTCLevel.CAUTION:  (133, 79, 11),     # 提示  #854F0B
    TTCLevel.WARNING:  (153, 60, 29),     # 预警  #993C1D
    TTCLevel.CRITICAL: (163, 45, 45),     # 危险  #A32D2D
}


def _ttc_level_legend_name(level: TTCLevel, cfg) -> str:
    """图例文字带上阈值，看图就知道颜色对应哪一级、门槛是多少。"""
    return {
        TTCLevel.NONE: '无告警',
        TTCLevel.CAUTION: f'提示 ≤{cfg.ttc_caution:.1f}s',
        TTCLevel.WARNING: f'预警 ≤{cfg.ttc_warning:.1f}s',
        TTCLevel.CRITICAL: f'危险 ≤{cfg.ttc_critical:.1f}s',
    }[level]


# ---- 人特征档案里那两个尺寸数的**显示文案** --------------------------------
# ⚠️ 语义（2026-10-02 用户实测后定稿）：它们**不是身高 / 肩宽**，而是
# **检测框覆盖的真实尺寸** —— 纵 = 框顶到框底，横 = 框左到框右（含手臂与衣着）。
# 本项目检测器实测只框住身体约 1.42 m：底边在小腿（不在脚）、顶边在额头
# （不到头顶），所以纵跨度比真人矮约 21%（1.79 → 1.4177），横跨度比肩峰宽
# 大约 10~30%。这是**检测器的框法决定的，与标定好坏无关**，改标定也改不掉。
#
# 为什么必须改口径：界面原先写「身高 1.42 m」，用户拿卷尺一比差 0.37 m，
# 会判定成标定错了 —— 实测恰恰相反，1.4177 与先验 BODY_SPAN_PRIOR_M=1.41
# 只差 0.5%，说明建档链路是准的。错的只是**名字**。
#
# 内部键仍是 ``height_m`` / ``width_m``，**不许改**（JSON 存档、验收脚本、
# ``_sync_ranging_width`` 都按它读）—— 只改给人看的那层。
def _span_pair_text(height_m: float, width_m: float) -> str:
    """档案尺寸数的紧凑显示（列表行 / 弹窗 / 大字共用这一个入口）。"""
    return f'框跨度 {height_m:.2f} × {width_m:.2f} m'


def _span_note_text() -> str:
    """口径说明。凡是把这两个数单独摆给用户看的地方，都要带上这一句。"""
    return ('框跨度 = 检测框覆盖的真实尺寸（纵 × 横），非身高/肩宽 ——'
            ' 比真身高小约两成属正常')


# ---- 测距方法名的**显示文案** --------------------------------------------
# ``RangingResult.method`` 是**内部键**：建档门控按它比较
# （``res.method in ('接触点法', '两法一致')``），所以**不许改值**。
# 只改给人看的那层。
#
# ⚠️ 2026-10-02 核实更正：本机录制帧轨**不存** method —— 逐帧只落
# distance / distance_raw / 框 / 类别 / fps。所以「改名会读不出历史录制」
# 这个顾虑**不成立**（早先注释是这么写的，属未核实的推断）；真正不能改的
# 理由是上面那条**运行时比较**。
#
# 内部名为什么叫「高度法 / 宽度法」（2026-10-02 收正**：它们用的量其实是
# 同一件事的两头 —— 都是**检测框覆盖的真实尺寸**，只是一个取纵向（框高）、
# 一个取横向（框宽）。CHARTER 已统一叫「框跨度」，故显示名跟着改成
# 「框跨度法（纵）/（横）」，并保留「参考」后缀（近场降级值恒为参考级）。
#
# ⚠️ 下面这张表的**键必须是内部键原值**，不是显示名。踩过的坑（2026-10-02）：
# 一次批量改名脚本把键也一起换成了显示名，于是查表永远不命中、界面原样
# 吐出内部名 —— 看着像"改了没生效"，实则是把标的改没了。
_METHOD_DISPLAY = {
    '高度法': '框跨度法（纵）',
    '宽度法(参考)': '框跨度法（横·参考）',
    '宽度法': '框跨度法（横）',
}


def _method_display(method) -> str:
    """测距方法的显示名。未登记的值原样返回（不猜、不崩）。"""
    if not isinstance(method, str) or not method:
        return ''
    return _METHOD_DISPLAY.get(method.strip(), method.strip())


class CalibSolveThread(QThread):
    """把「求解相机内参」放到子线程执行。

    为什么必须异步（2026-09-23 用户实际故障）：``cv2.calibrateCamera`` 是
    **秒级长任务** —— 本机实测 50 帧 640x480 要 **17.06 s**。旧代码在按钮
    槽函数里同步调用，一点「求解并保存」整个界面就冻住十几秒不动。

    设计要点：
    - 只吃**快照**（点列表的拷贝）：线程在跑时主线程照旧接帧也不影响它；
    - 线程里只调纯函数 `solve_intrinsics`，不碰任何 Qt 控件；
    - 结果用信号回主线程，弹窗 / 写文件 / 改状态都在主线程做（Qt 要求）。
    """

    solved = Signal(object, str)          # (CameraIntrinsics | None, 错误信息)

    def __init__(self, object_points, image_points, image_size, parent=None):
        super().__init__(parent)
        self._objp = list(object_points)
        self._imgp = list(image_points)
        self._size = tuple(image_size) if image_size else (0, 0)

    def run(self):
        try:
            self.solved.emit(
                solve_intrinsics(self._objp, self._imgp, self._size), '')
        except Exception as e:
            self.solved.emit(None, str(e))


class DeviceIdentifyThread(QThread):
    """后台枚举摄像头设备（只有**兜底通路**才需要异步）。

    为什么路径要分开：Windows 上主通路（读注册表）实测 ~1.4 ms，比一次界面
    重绘还便宜，同步跑即可；但它在个别机器上会失败，兜底要调 PowerShell，
    实测 **4.9~6.8 s**。放在启动路径上同步跑，就是开窗即见的几秒卡顿。

    所以：快通路同步、慢通路异步（见 ``MainWindow._scan_camera_devices``）。
    """

    identified = Signal(object)          # IdentityReport

    def run(self):
        try:
            rep = enumerate_cameras(allow_slow_fallback=True)
        except Exception as e:                                   # noqa: BLE001
            # 线程里的异常不会自动冒到主线程，这里必须自己兜住，
            # 否则表现为「界面一直停在识别中」
            rep = IdentityReport(provider='', error=f'设备枚举异常：{e}')
        self.identified.emit(rep)


class MainWindow(QWidget, Ui_Form):
    frame_signal = Signal(np.ndarray)  # 定义类属性

    def __init__(self):
        super(MainWindow, self).__init__()
        self.setupUi(self)
        self.setWindowTitle('EdgeSight — 单目视觉感知栈')
        # 初始化核心组件
        self.camera_index = 0
        self.cap = None
        # 摄像头掉线自愈状态（见模块顶 CAM_FAIL_STREAK 那段注释）
        self._cam_fail_streak = 0      # 连续读帧失败计数
        self._cam_reconnecting = False  # 重连进行中：避免每帧重复起线程
        self._cam_retry = 0            # 已重试次数（用于退避与提示）
        self._reconnect_thread = None  # 必须持有引用，否则线程会被 GC 掉
        self._last_detection_ts = None  # 检测心跳：最后一次收到检测结果的时间
        self._inflight_frames = 0       # 已投给检测器、还没回调的帧数（背压用）
        self._dropped_inference_frames = 0  # 因背压丢掉的帧数（如实计数，不静默）
        self.detector = None
        self.labels = []
        self.global_params = GlobalParams()  # 必须在init_camera前初始化
        self.frame_counter = 0
        self.inference_interval = 3  # 每5帧推理一次（0,1,2,3,4,5...）
        self.last_detection=None
        # 本帧「检测到的这个人不是追踪目标」的说明（None = 没这回事）。
        # 画面叠加与距离读数共用它：不是他 -> 不画框、不出数（2026-09-29 用户要求
        # 「没认出就把这个陌生人的检测框也扔掉，距离显示不可测，下面标注原因」）。
        self._identity_reject_note = None
        # 标定页专用的测距结果：**不受身份拦截影响**（2026-09-29 用户要求
        # 「标定页面不需要做追踪，只需要识别人并显示距离」）。拦截会把 res/dist
        # 抹成不可测 —— 那是监视页的口径；标定页要的是「这一帧测出来多少」，
        # 所以取的是拦截**之前**的结论（可见性体检 / 去噪 / 速度门控都已过）。
        self._calib_ranging = None
        self.is_loading_model=False
        # 标定状态：不采集时 calibrator 为 None，避免误采集普通帧
        self.calibrator = None
        # 是否正在采集标定帧。与 calibrator 分开：暂停采集不丢已采帧
        self._collecting = False
        # 是否正在子线程求解内参。求解期间禁止重复触发（实测 50 帧要十几秒）
        self._solving = False
        self._solve_thread = None
        # ------------------------------------------------------------------
        # 安装参数自标定（外参：相机安装高度 + 俯仰角）
        # ------------------------------------------------------------------
        # 已记录的采样点：[{'dist': 已知距离m, 'v': 底边像素均值, 'std': 散布px,
        #                  'n': 帧数}, ...]
        self._mount_marks = []
        self._marking = False        # 是否在采样窗口内
        self._mark_samples = []      # 采样窗口内收集到的框底边像素
        self._mark_distance = 0.0    # 本次采样对应的已知距离
        self._mark_timer = None
        # 正在把落盘的安装参数回填到控件期间为 True —— 用来区分「加载」与
        # 「用户手工修改」，避免启动时把加载动作当成用户改动又写回一次
        self._loading_mount = False
        # 几何测距器。先无内参构造，load_calibration() 后注入
        #
        # 第三个参数是「脚是否出画」的**带记忆**判定（2026-09-26 治本）：
        # 无记忆的硬阈值会让方法在阈值线上逐帧横跳 —— 实测四个「走回镜头」
        # 会话翻转 26/28/34/20 次，读数在框跨度法（横） 1.4 m 与接触点法假值 1.95 m
        # 之间交替，相邻帧斜率可达 3.9 m/s，TTC 与趋势估计整体被毒化。
        # 滞回在缓冲带内保持上一状态，把 N 次翻转收敛成 1 次真实过境。
        self.ranger = GeometricRanger(CameraIntrinsics(),
                                      RangingConfig.from_params(self.global_params),
                                      hysteresis=FootClipHysteresis())
        # ------------------------------------------------------------------
        # 人特征档案 + 速度门控（2026-09-25 P1+：近场框跨度法（横）的两大支柱）
        # ------------------------------------------------------------------
        # 档案：目标完整可见、接触点法出数的帧里顺手量这个人的**框跨度**
        # （纵 = 框顶到框底、横 = 框左到框右 —— ⚠️ 不是身高/肩宽，实测比真身高
        # 小约 0.37 m，见 ``_span_pair_text`` 的注释），稳定窗口提交后框跨度法（横）用的
        # 就是「这个人自己的框宽度」（而非默认 0.46 m），
        # 多人靠躯干外观直方图区分。门控：人不可能瞬移，相邻读数隐含速度
        # 超过人体极限（8 m/s）的一律拦下 —— 拦的是检测跳变错值。
        # CHARTER v1.4 起，档案还承担**身份**职责：嵌入用来认人、几何用来给
        # 近场框跨度法（横）一个「这个人自己的框宽度」。emb_tag 必须与建档时一致。
        # 路径必须**相对仓库根**解析（2026-09-30 修复）：原先把
        # ``person_profile_path``（'models/person_profile.json'）直接交给
        # tracker，等于按**当前工作目录**解析。从别处启动程序时档案读不到，
        # 而失败方式是静默的 —— ``load()`` 找不到文件就 return，档案库为空、
        # 追踪目标 None、身份门整条失效、近场框跨度法（横）回落 0.46，界面零提示。
        # 与 ``_calib_file`` 同款（那边早先已修，这边漏了）。
        self._person_tracker = PersonFeatureTracker(
            _resolve_repo_path(self.global_params.person_profile_path),
            emb_match_threshold=self.global_params.reid_match_threshold,
            emb_tag=_REID_TAG)
        # 路人池归一化（cohort）**默认关**，此处刻意不传 cohort_enabled ——
        # 依据是实测判决，不是保守：用 17 段历史回放（2054 条嵌入、全部同一人）
        # 留一交叉验证测得 —— 画面里只有目标一人时池**恒为空**（准入门槛 0.30
        # 下 32864 帧仅 2 帧入池且不足最小规模），归一化从不生效；而门槛一旦
        # 放松到 0.35，池立刻被**本人帧**填满，本人通过率从 59.8% 崩到 1.3%。
        # 也就是说：在"只有目标一人"的场景里它无收益，且门槛稍松即有害。
        # 它的收益依赖「场景里真会出现路人」这个**在历史录制里从未发生过**的前提。
        # 要开：加 cohort_enabled=True；并先读 core/reid_cohort.py 顶部关于
        # 「门槛仍是原始口径、未按偏移重标定」的说明（开了判定只会更严）。
        # 判决脚本：E:/WorkBuddy-Work/scripts/cohort_real_probe.py
        self._speed_gate = SpeedGate()
        self._last_profile_key = ''     # 防止建档提示刷屏
        # ------------------------------------------------------------------
        # 建档（CHARTER v1.4「范围内的」建档条：独立第三步，收在标定页）
        # ------------------------------------------------------------------
        # 与 reid_probe **各持一个 embedder**，不共用：
        #   · reid_probe 的在后台线程、与录制同开同关、只落盘；
        #   · 这个在**主线程**、只在建档会话中调用，用来把嵌入写进档案。
        # 单张约 9 ms（2 线程，本机实测），只在用户主动建档那几秒内发生。
        self._enroll_embedder = None
        self._enroll_ui_tick = 0        # 建档状态刷新节流（每 N 帧刷一次）
        self._enroll_commits_seen = 0   # 已播报过的提交次数（提示音去重，不重复响）
        self._enroll_failures_seen = 0  # 已播报过的建档失败次数（同上，另一条通道）
        self._enroll_last_error = ''
        # 「已建档：xxx」是一次性结论，给它一个保护期：期间实时进度刷新
        # 不许覆盖大字，否则结论立刻被冲掉（见 _ENROLL_BIG_HOLD_S 的注释）。
        self._enroll_big_hold_until = 0.0
        # ------------------------------------------------------------------
        # TTC 碰撞预警（2026-09-25，CHARTER「范围内的」第 5 条实时接入）
        # ------------------------------------------------------------------
        # 与离线分析（analyze_recording）共用同一个 TTCEstimator 类 ——
        # UI 侧零新逻辑，只是把检测回调里的距离序列喂进去。喂的是
        # **门控后的距离**：速度门控拦截的帧按「测距不可用」处理，
        # 不会让被拦的错值毒化速度估计。
        self._ttc = TTCEstimator()
        self._last_ttc_style = ''       # 分级色变了才 setStyleSheet（防每帧重绘）
        # 距离去噪（2026-09-26）：中值3+One Euro 串联，见 core/ranging_filter.py。
        # 滤波紧跟测距，输出的**规范距离是全链路唯一距离值** —— 速度门控、
        # 人特征档案、监视页读数、TTC、深度分析曲线、录制轨存的全都是它；
        # 原始值只作诊断字段留在录制里（distance_raw），实时逻辑一律不读。
        self._dist_filter = DistanceFilter()
        # 最后一帧的测距结果：标定判定被**异步复核**（相机打开完成）时要用它把
        # 原因行/悬停**原样重画**，不能拿 None 去刷 —— 否则读数文字留着上一帧的
        # 值、原因行却被擦空，界面变成「不可测」+ 没有原因（实测偶发踩到）
        self._last_ranging = None
        # 启动时若档案里已有匹配不上的旧人，肩宽保持默认值，等见到人再自动匹配
        # 录制回放（CHARTER 第 6 条）
        self.recorder = None          # 非录制时为 None，避免误调
        # ReID 旁路（CHARTER v1.4「认人判据」的数据采集）。**只记录，不决策**：
        # 与录制同开同关（不录制就没落点，也就不用白跑 OSNet）。见 core/reid_probe.py
        self._reid_probe = None
        self.replayer = None          # 回放器
        self.replay_timer = None      # 回放驱动定时器
        self.play_index = 0           # 回放进度（帧）
        self._replay_seeking = False  # 拖动进度条时抑制回写
        self._rec_seq = 0             # 录制帧序号
        self._rec_t0 = 0.0            # 录制起始时刻，用于数据轨时间戳

        # 初始化存储图表的环形缓冲区。
        # 2026-09-26 改版：目标位置/尺寸图删除，新增 TTC / 方法 / 类别轨迹。
        # 距离历史存**规范值**（去噪后，与监视页读数、TTC、判定同源）；
        # 类别与方法逐帧并行记录 —— 类别给距离曲线着色，方法只喂下方提示行
        # （2026-09-26：图上那几条方法竖虚线已删，见 init_analysis_plots 的注释）。
        self.history_len = 100
        self.sensor_history_conf = deque(maxlen=self.history_len)
        self.sensor_history_conf_thres = deque(maxlen=self.history_len)
        self.sensor_history_fps = deque(maxlen=self.history_len)
        self.target_distance = deque(maxlen=self.history_len)
        self.class_history = deque(maxlen=self.history_len)
        self.method_history = deque(maxlen=self.history_len)
        self.ttc_history = deque(maxlen=self.history_len)
        self.ttc_reason_history = deque(maxlen=self.history_len)
        self.time_history = deque(maxlen=self.history_len)
        self.time_counter = 0.0
        self._dist_curves = {}       # 类别名 -> 距离曲线
        # 距离图的图例要**自己管增删**：pyqtgraph 0.14 实测 setData([], [])
        # 不会撤掉图例项（LegendItem.items 仍持有），留下的是指向空曲线的
        # 死条目。_dist_legend_on = 当前已登记进图例的类别。
        self._dist_legend = None
        self._dist_legend_on = set()
        # 图例文字要**单独记一份**：LegendItem 没有 rename API（要改名只能
        # removeItem + addItem），所以得知道「现在挂着的这行字是哪一句」，
        # 才能判断追踪目标改了 / 指纹改名了之后要不要换（见 _dist_legend_sync）。
        # _dist_active = 当前真正有数据的类别，是图例同步的输入（也给
        # _dist_legend_refresh 用 —— 改选目标时要能不等 analysis_timer 就刷）。
        self._dist_legend_text = {}   # 类别 -> 当前登记在图例里的文字
        self._dist_active = set()
        self._ttc_threshold_lines = []   # [(y, InfiniteLine, TextItem)]
        # ---- 录制/回放曲线（「测距曲线（录制/回放）」那张图）------------------
        # 2026-09-26 改版：从「加载时一次性画满 + 播放时纹丝不动」改成
        # **增量追加、随进度揭示**，并且**录制时就实时画**。
        #   _curve_pts  已揭示的点 [(t, d, level), ...]（权威，测试读它）
        #   _curve_xy   分级 -> ([xs], [ys])，避免每次从 _curve_pts 重算
        #   _curve_items 分级 -> 曲线对象（pyqtgraph 一条线只有一个画笔，
        #                要在一根线上换色只能按分级分条画）
        self._curve_pts = []
        self._curve_xy = {}
        self._curve_items = {}
        self._curve_legend_done = False
        self._replay_ts = []          # 回放会话的**全量**曲线数据（加载时算一次）
        self._replay_ds = []
        self._replay_levels = []
        # 懒绘制（2026-09-26 用户要求：回放只加载当前页面的曲线，监视页
        # 不刷深度分析曲线，减少 UI 负担）。画面与回放曲线只在**对应页
        # 可见**时绘制；后台页只维护数据状态，切回该页时一次性补齐。
        self._last_display_bgr = None  # 最近一帧画面（BGR，供切回监控页补画）
        # 初始化状态栏
        self.status_bar=QStatusBar(self)
        self.layout().addWidget(self.status_bar)
        # ------------------------------------------------------------------
        # 摄像头设备识别（CHARTER「范围内的」第 1 条：内参按设备记忆）
        # ------------------------------------------------------------------
        # 为什么要「记设备」：内参跟着**相机本体**走。旧实现只有一个
        # models/calib.json，隐含假设「这台机器只有一台相机」—— 换一台
        # **同分辨率**的相机会静默沿用旧内参：距离系统性错、界面零提示
        # （相机的 _tune_if_needed 还会把画面调回 640x480，把尺寸凑巧对上，
        # 进一步掩盖问题）。现在按设备指纹分档存：换设备能认出来，
        # 没标定会提醒标定，分辨率不符会拒用而不是硬算。
        self._cam_store_path = None       # models/cameras.json
        self._cam_store = {}              # 档案库（按设备指纹分档）
        self._identity_report = None      # 上一次枚举结果（含通路与耗时）
        self._cam_active = None           # ActiveDevice：正在用的那台是谁、有多确定
        self._cam_decision = None         # CalibrationDecision：本次用哪份内参
        self._legacy_intrinsics = None    # 旧的单文件标定（兼容与过渡）
        self._identify_thread = None      # 兜底枚举线程（慢通路必须异步）
        self._loading_device = False      # 程序回填下拉框期间，挡住「用户选择」误判
        self._calib_prompted = False      # 「未标定」提醒每轮启动只弹一次
        #初始化UI
        self.init_ui()
        # 先为每个plot控件添加图例，确保曲线名字能显示
        self.plot_sensor_center.addLegend()
        self.plot_sensor_conf.addLegend()
        self._dist_legend = self.plot_target_distance.addLegend()
        self.plot_sensor_fps.addLegend()
        # 初始化分析曲线控件（确保UI已setupUi）
        # 2026-09-26 改版：原「目标位置分析」(x/y曲线) 改为 TTC 曲线，分级
        # 阈值虚线在 init_analysis_plots 里加；原「尺寸+距离」两图合并为单张
        # 距离图，曲线按目标类别着色、惰性创建（见 update_analysis_plots）。
        # connect='finite'：ttc_history 里"不可算"的帧记 NaN，曲线在那里断开。
        # 不能只靠 NaN —— pyqtgraph 默认的 'all' 会静默跳过 NaN 把两侧直连，
        # 于是"没有 TTC"的时段被画成一条连续的线（实测 0.14.0）。
        self._plot_ttc_curve = self.plot_sensor_center.plot(
            [], [], pen=pg.mkPen('g', width=2), name="TTC", connect='finite')
        self._plot_sensor_curve_conf = self.plot_sensor_conf.plot([], [], pen=pg.mkPen('b', width=2), name="检测框置信度")
        self._plot_sensor_curve_conf_thres = self.plot_sensor_conf.plot([], [], pen=pg.mkPen('r', width=2, style=Qt.DashLine), name="置信度阈值")
        self._plot_sensor_curve_fps = self.plot_sensor_fps.plot([], [], pen=pg.mkPen('y', width=2), name="检测框FPS")
        #信号绑定
        self.bind_model_thres_widgets_realtime()#实时生效
        self._build_dist_source_row()    # 最靠前：先决定「距离从哪来」
        # ⚠️ 这里**不再**建「已知相机高度」「框底边不在脚上（同时解抬升量）」
        # 两行 —— 2026-10-01 下线，原因见 _build_dist_source_row 的 docstring。
        # 标定只剩一条路：自标定，解 (落差, 俯仰角) 两个未知数。
        self.bind_calibration_widgets()#仅标定时生效
        self.bind_buttons()
        self.bind_other()
        #启动定时器
        self.setup_core_timers()
        #创建Detector线程，用于处理持续耗时的操作
        self.detector_thread=QThread()
        self.detector_thread.setObjectName('DetectorThread')
        #初始化摄像头和AI模型
        self.async_init_camera()
        self._apply_default_model_paths()
        self.async_init_ai_model()
        #延迟初始化图表
        self._analysis_plot_inited=False
       
    def setup_core_timers(self):
        #定时器更新监控界面数据
        self.update_timer=QTimer()
        self.update_timer.setInterval(int(1000 / self.global_params.sample_freq))  # 按采样频率更新
        self.update_timer.timeout.connect(self.update_monitor_data)
        self.update_timer.start()
        #摄像头画面刷新定时器
        # ⚠️ **必须显式设 PreciseTimer**。``QTimer()`` 默认是 CoarseTimer，
        #    它会向系统时钟粒度对齐 —— Windows 的粒度是 15.625 ms，于是 33 ms
        #    的间隔被拉到 **47.10 ms（21.23 FPS）**，这正是现场 18 个录制会话
        #    循环率上限 21.25 的来源。同间隔换 PreciseTimer 实测 33.01 ms
        #    （30.29 FPS）；在真实程序里改这一行实测循环 46.14 → 32.59 ms
        #    （21.7 → 30.7 FPS）。详见 README「帧率」一节。
        #    注意：它**只提高画面循环率**；界面「推理FPS」是检测单帧耗时的
        #    倒数、由检测线程自己决定，不随之变化。
        self.camera_timer=QTimer()
        self.camera_timer.setTimerType(Qt.PreciseTimer)
        self.camera_timer.setInterval(int(1000 / self.global_params.fps))
        self.camera_timer.timeout.connect(self.update_camera_frame)
        self.camera_timer.start()
        # 深度分析曲线动态刷新定时器
        self.analysis_timer = QTimer()
        self.analysis_timer.setInterval(50) 
        self.analysis_timer.timeout.connect(self.update_analysis_plots)
        # 资源监控定时器
        self.resource_timer=QTimer()
        self.resource_timer.setInterval(1000)
        self.resource_timer.timeout.connect(self.update_resource_usage)
        self.resource_timer.start()
        # 看门狗：1 秒一次，查检测链路心跳。
        # 摄像头掉线由主循环自己发现（update_camera_frame），但「画面在动、
        # 检测却不出结果」这种只有它能抓到 —— 用户看到的同样是「框不动」。
        self.watchdog_timer=QTimer()
        self.watchdog_timer.setInterval(1000)
        self.watchdog_timer.timeout.connect(self._check_detection_heartbeat)
        self.watchdog_timer.start()

    
    def init_ui(self):
        #系统参数
        self.slider_sample_freq.setValue(self.global_params.sample_freq)
        self.label_sample_freq.setText(f'{self.global_params.sample_freq}Hz')
        self.slider_base_width.setValue(self.global_params.base_width)
        self.label_base_width.setText(f'{self.global_params.base_width}px')
        #运动时数据
        self.lcd_centroid_x.display(self.global_params.detection_x)
        self.lcd_centroid_y.display(self.global_params.detection_y)
        self.lcd_fps.display(self.global_params.fps)
        self.lcd_reasoning.display(self.global_params.inference_fps)
        #检测配置
        self.slider_confidence_thres.setValue(int(self.global_params.confidence_thres*100))
        self.label_confidence_thres.setText(f'{self.global_params.confidence_thres:.1f}')
        self.slider_nms_thres.setValue(int(self.global_params.nms_thres*100))
        self.label_nms_thres.setText(f'{self.global_params.nms_thres:.1f}')
        #追踪目标选择（设置页）：下拉内容是**指纹档案列表**，不是固定规则
        self.refresh_track_target_combo()
        self.combo_hardware_accel.setCurrentText(self.global_params.hardware_accel)
        #推理结果
        self.lcd_credibility.display(self.global_params.credibility)
        #「目标类别」这一行有追踪目标时显示的是**身份**，不是类别名（见
        # target_category_text）。启动时也要按同一条规则写，否则重启后直到
        # 第一帧检测到来之前，这一行还停在 .ui 里写死的「--」。
        self.refresh_target_category_label()
        #相机标定：先认「本机是哪台相机」，再按设备取内参（见 load_calibration）
        self.load_calibration()
        #安装参数（相机高度 + 俯仰角）：与内参同理，落盘后启动即回填
        self.load_mount_params_ui()
        self.refresh_calib_widgets()
        self.refresh_camera_widgets()
        # 建档状态（标定页 ③）：启动时就把「档案库几条」如实显示出来，
        # 而不是留一句写死的「未开始」。
        self._refresh_enroll_status()
        # 指纹档案管理列表（设置页）：启动时填一次（内部会一并刷新追踪目标下拉）
        self.refresh_profiles_list()
    
    #摄像头线程启动
    def async_init_camera(self):
        self.status_bar.showMessage("正在初始化摄像头...")
        # 换视频源 = 换场景：「脚是否出画」的滞回状态属于上一段画面，必须清掉，
        # 否则新场景开头几帧会继承旧状态的判断（2026-09-26）。
        self.ranger.reset_foot_state()
        self.camera_thread = CameraInitThread(self.camera_index, self.global_params.fps)#摄像头初始化实例
        self.camera_thread.init_finished.connect(self.on_camera_init_finished)#绑定结束信号到回调函数，子线程和主线程通信的关键
        self.camera_thread.start()#启动后再run运行

    def on_camera_init_finished(self,success,message):#摄像头加载完成回调
        if success:
            self.cap = self.camera_thread.cap
            self.status_bar.showMessage(message, 3000)
            # 拿到真实画面尺寸后复核内参判定：启动时相机可能还没开，
            # 那时跳过分辨率校验，这里必须补上（标定分辨率≠当前分辨率是要拦的错）
            self.verify_calibration_against_frame()
        else:
            self.lbl_original.setText("摄像头未连接")
            self.lbl_process.setText('摄像头未连接')
            self.status_bar.showMessage(message, 5000)

    def async_init_ai_model(self,reload=False):
        self.is_loading_model=True

        if reload:
            # 先停止定时器
            if hasattr(self,'camera_timer') and self.camera_timer.isActive():
                self.camera_timer.blockSignals(True)# 暂时阻断摄像头定时器信号
            try:
                self.frame_signal.disconnect()# 阻断旧信号槽
            except:
                pass
            old = self.detector
            try:
                if old:
                    old.detection_ready.disconnect(self.on_detection_ready)
            except:
                pass
            # 常驻 detector_thread 不退出（退出+重建会在主线程上等待，卡界面），
            # 旧 detector 交给它所属线程的事件循环去删
            self.detector=None #去除旧对象
            if old is not None:
                old.deleteLater()

        self.status_bar.showMessage(
            "正在后台加载 AI 模型……（界面可继续操作，加载完自动生效）")
        self.model_thread = ModelInitThread(
            self.global_params.mode_path,
            self.global_params.hardware_accel,
            self.global_params.label_path,      # 标签文件也在子线程里读
        )
        self.model_thread.init_finished.connect(self.on_model_init_finished)
        self.model_thread.start()

    def on_model_init_finished(self,success,message,model=None):#模型加载完成回调
        print("检测线程启动状态：", self.detector_thread.isRunning())
        if success and self.global_params.mode_path:
            model_path_lower=self.global_params.mode_path.lower()
            if 'v5' in model_path_lower or 'yolov5' in model_path_lower:
                model_type='v5'
            elif 'v8' in model_path_lower or 'yolov8' in model_path_lower:
                model_type='v8'
            else:
                model_type='v5'
            self.detector=YOLODetector(
                self.global_params.mode_path,
                self.global_params.label_path,
                self.global_params,
                self.global_params.confidence_thres,
                self.global_params.nms_thres,
                self.global_params.hardware_accel,
                model_type=model_type
            )
            if self.detector.load_model(preloaded_model=model):
                self.detector.moveToThread(self.detector_thread)#将Detector对象移到子线程运行
                #创建信号槽连接，主线程向监测器线程发送视频帧
                self.frame_signal.connect(self.detector.predict)
                #检测器结果在发送到主线程进行处理
                self.detector.detection_ready.connect(self.on_detection_ready)
                if not self.detector_thread.isRunning():
                    self.detector_thread.start()
                # 标签与类别下拉跟着这次加载的模型走（不依赖用户手动选过标签）
                self.labels = list(self.detector.labels or [])
                self._save_model_settings()   # 记住这次生效的组合
                self.status_bar.showMessage('AI模型加载并初始化成功',3000)
            else:
                self.status_bar.showMessage('Detector加载模型失败', 5000)
        else:
            self.detector=None # 没有模型路径也要设为None避免报错

        self.status_bar.showMessage(message, 3000)
        #  恢复标志位于定时器信号
        self.is_loading_model = False
        if hasattr(self, 'camera_timer'):
            self.camera_timer.blockSignals(False)  # 恢复摄像头定时器的信号

    def init_analysis_plots(self):
        if self._analysis_plot_inited and self.global_params.plot_enable:
            return
        self._analysis_plot_inited=True
        # 绘图控件名以 ui/EdgeSightMain.ui 为准（2026-09-26 改版：
        # plot_sensor_shap 已随「目标尺寸」图一起删除，引用会 AttributeError）
        for plt in [self.plot_sensor_center, self.plot_target_distance,
                    self.plot_sensor_conf, self.plot_sensor_fps]:
            plt.showGrid(x=True, y=True)
            plt.setLabel('bottom', '时间')
            plt.setMouseEnabled(x=True, y=True)
        self.plot_sensor_center.setLabel('left', 'TTC (s)')
        self.plot_target_distance.setLabel('left', '距离 (m)')
        self.plot_sensor_conf.setLabel('left', '数值')
        self.plot_sensor_fps.setLabel('left', '数值')
        # TTC 分级阈值虚线（与 core/ttc.py 的 TTCConfig 同源，不另写一份数值）。
        # 标签用 ignoreBounds=True 加入：pyqtgraph 0.14 的 TextItem.dataBounds
        # 返回的是**锚点**，会被 ViewBox 当作一个数据点算进自动量程；而这些标签
        # 又要贴着「当前视野右缘/顶部」摆，于是量程推标签、标签再推量程 ——
        # 实测（probe_textitem_autorange.py）24 次刷新把 X 轴从 6.2 s 推到
        # 17.0 s，一路往外爬。ignoreBounds 让虚线只画、不参与量程。
        # 颜色与监视页 TTC 告警色一致（提示=琥珀 #854F0B、预警=#993C1D、危险=#A32D2D）。
        if not self._ttc_threshold_lines:
            cfg = self._ttc.cfg
            for y, color, name in (
                    (cfg.ttc_caution, '#854F0B', '提示'),
                    (cfg.ttc_warning, '#993C1D', '预警'),
                    (cfg.ttc_critical, '#A32D2D', '危险')):
                line = pg.InfiniteLine(
                    pos=y, angle=0,
                    pen=pg.mkPen(color, style=Qt.DashLine, width=1))
                txt = pg.TextItem(f'{name} {y:.1f}s', color=color, anchor=(1, 1))
                self.plot_sensor_center.addItem(line, ignoreBounds=True)
                self.plot_sensor_center.addItem(txt, ignoreBounds=True)
                self._ttc_threshold_lines.append((y, line, txt))
        # 曲线对象已在__init__初始化，这里只需清空数据
        self._plot_ttc_curve.setData([], [])
        self._plot_sensor_curve_conf.setData([], [])
        self._plot_sensor_curve_conf_thres.setData([], [])
        self._plot_sensor_curve_fps.setData([], [])
        for curve in self._dist_curves.values():
            curve.setData([], [])
        self._dist_active = set()
        self._dist_legend_sync(set())   # 图例跟数据一起清，别留死条目
        # 距离图**不再画方法切换竖虚线**（2026-09-26）：竖线的标签是普通 TextItem，
        # 它的 dataBounds 返回锚点 (0,1)，被 ViewBox 当成数据点 (x, 文字位置+1)
        # 算进 Y 量程；而位置又取自"当前视野顶 × 0.95"，形成正反馈
        # y ← 0.95·y + 1 + padding，收敛点约 30 m —— 0.5~4 m 的曲线被压成一条直线、
        # 标签全飘到 30 m 处互相重叠。方法信息改由下方提示行承载（同样的信息、
        # 不碰坐标轴）。TTC 阈值虚线保留，但标签已 ignoreBounds 处理。

    def update_analysis_plots(self):
        if not self._analysis_plot_inited and self.global_params.plot_enable:
            return
        ts = list(self.time_history)
        # TTC 曲线 + 阈值线标签（标签贴视野右上角，随缩放/平移跟随）
        self._plot_ttc_curve.setData(ts, list(self.ttc_history))
        vr = self.plot_sensor_center.getViewBox().viewRange()
        for y, _line, txt in self._ttc_threshold_lines:
            txt.setPos(vr[0][1], y)
        # 距离曲线（2026-09-26 用户定稿口径）：**未知也要画** ——
        # 没有读数的帧（未检出目标 / 检出但不可测）画进「未知」曲线：
        # **红色、距离值拉到 0**，图例标「未知」；有读数的帧画进「人」曲线
        # （单类别后只剩「人 / 未知」两种颜色）。「未知与类别曲线不能同时
        # 出现」指**同一时刻**只有一条线，不是整张图只准存在一种。
        # 整条时间线**连续不断点**：换段处两段**共享边界点**（新段起笔自
        # 旧段末点、旧段收笔到新段首点）—— 类别线落下到 0、再从 0 回到
        # 读数，视觉上是同一根线换了颜色；同一类别**再次出现**的多段之间
        # 用 NaN 隔开（connect='finite'），不会被连成横穿整图的直线
        # （与回放曲线的分级着色同一手法，见 README 里程碑第 14 条）。
        frames = []      # (t, key, val)：一帧只属于一条线
        for t, d, c in zip(ts, self.target_distance, self.class_history):
            if d is None or d != d:            # None / NaN → 这一帧没有读数
                frames.append((t, '未知', 0.0))
            else:
                # 键保留**标签文件原文**（coco80.txt 给 'person'、coco_labels_cn.txt
                # 给 '人'）—— 这是既有约定：归一化只发生在**用到它的地方**
                # （配色走 _class_pen_color、界面文字走 display_class_name），
                # 字典键本身不动（既有验收脚本按这个约定读 _dist_curves）。
                frames.append((t, c or '未知', float(d)))
        series = {}     # 类别名 -> [(x, y)…]（同一类别多段之间夹 NaN 点）
        for i, (t, key, val) in enumerate(frames):
            pts = series.setdefault(key, [])
            prev = frames[i - 1] if i > 0 else None
            if prev is not None and prev[1] != key:
                if pts:                                        # 本类别上一段先收尾
                    pts.append((float('nan'), float('nan')))
                pts.append((prev[0], prev[2]))                 # 起笔自旧段末点
                series[prev[1]].append((t, val))               # 旧段收笔到本段首点
            pts.append((t, val))
        for cls, pts in series.items():
            curve = self._dist_curves.get(cls)
            if curve is None:
                # **不传 name=**：图例登记统一收在 _dist_legend_sync 一处。
                # 原先 plot(name=display_class_name(cls)) 是**第二个**登记入口，
                # 于是「刚建立」与「滚出窗口后又回来」两条路径的文案得手工对齐
                # （2026-09-29 就是这样差点让图例退回内部名）。现在只留一个入口，
                # 文案改由 _dist_line_label 现场判定（要跟着追踪目标走）。
                # 字典键 / 配色仍用 cls 这个内部规范名 —— 内部名是标的（换标签
                # 文件不变、曲线对象要能跨会话复用），显示名只是给人看。
                curve = self.plot_target_distance.plot(
                    [], [], pen=pg.mkPen(_class_pen_color(cls), width=2),
                    connect='finite')
                self._dist_curves[cls] = curve
                if cls == '未知':
                    # 红色段压在类别线之上：拉到 0 / 回到读数的斜线务必显示红色
                    curve.setZValue(10)
            curve.setData([p[0] for p in pts], [p[1] for p in pts])
        for cls, curve in self._dist_curves.items():
            if cls not in series:
                curve.setData([], [])       # 该类别滚出窗口后清空
        self._dist_active = set(series)
        self._dist_legend_sync(self._dist_active)   # 图例跟随类别的出现/消失/改名
        # 方法信息只走下方提示行（图上不再画竖虚线，理由见 init_analysis_plots）
        # 置信度 / FPS 曲线
        self._plot_sensor_curve_conf.setData(ts, list(self.sensor_history_conf))
        self._plot_sensor_curve_conf_thres.setData(ts, list(self.sensor_history_conf_thres))
        self._plot_sensor_curve_fps.setData(ts, list(self.sensor_history_fps))
        # 更新提示行
        if not ts:
            self.label_prompt.setText('暂无TTC数据')
            if hasattr(self, 'label_method_prompt'):
                self.label_method_prompt.setText('暂无测距数据')
            self.label_conf.setText('—')
            return
        self._refresh_ttc_hint()
        if hasattr(self, 'label_method_prompt'):
            m = self.method_history[-1] if self.method_history else None
            if m and m != '不可测':
                self.label_method_prompt.setText(
                    f'当前测距方法：{_method_display(m)}')
            elif m == '不可测':
                self.label_method_prompt.setText(
                    '当前测距方法：不可测（原因见监视页读数下方）')
            else:
                self.label_method_prompt.setText('暂无测距数据')

        if len(self.sensor_history_conf) > 0 and self.sensor_history_conf[-1] < self.global_params.confidence_thres:
            self.label_conf.setText("置信度低于阈值！")
        else:
            self.label_conf.setText("置信度正常")

    def _dist_line_label(self, cls) -> str:
        """这条距离曲线在图例里该叫什么。**唯一**的文案出口。

        用户要求（2026-09-29）：
        > 我现在不是在做追踪吗，那距离分析曲线的标签就不应该是人或者 person，
        > 而应该是指纹的名字 lsy

        为什么「有读数」那条线可以直接写指纹名：身份拦截
        （``_identity_reject_reason``）已经把「本帧认出的是别人 / 谁都没认出」
        的帧一律抹成不可测，于是这条线上**只可能**是追踪目标本人的读数 ——
        写类别名（人 / person）等于把「我们其实知道他是谁」这个信息丢掉。
        没指定追踪目标时才退回类别显示名（「人」）。

        「未知」档不受影响：它装的是被拦截的帧与没测出来的帧，那些帧没有身份
        可言，恒显示「未知」。判据用 ``canonical_class_name``，与
        ``_class_pen_color`` 同源（红色那条 = 未知那条），不另写一套。

        ⚠️ 这是**显示层**翻译，字典键（``_dist_curves`` 的 cls）绝不动。
        若把指纹名写进 ``class_history`` 当键会坏两件事：① 改名（lsy → 别的）
        会让同一条线裂成两个键、图上冒出两条名字不同的线，而它们其实是同一个
        人的连续轨迹；② 新键在 ``_class_pen_color`` 里落到「未登记类别」的
        灰色分支 —— 人那条线会突然变灰。

        ⚠️ 副作用（已知、可接受）：文字是**当前**目标的名字，所以窗口里
        「指定追踪目标之前」那几秒的点，也会跟着被标成他。那些点原本是
        「一个人」（未必是他）。窗口只有 ``history_len`` 帧，且追踪目标
        通常一开始就选定；要彻底消除，得把每帧的身份记进历史（那又要面对
        上面两条问题）。此处选择显示层方案，并把这条写进 README。
        """
        if canonical_class_name(cls or '未知') == '未知':
            return display_class_name(cls)      # 无读数档恒为「未知」
        tgt = self._person_tracker.track_target()
        if tgt is not None and tgt.name:
            return tgt.name
        return display_class_name(cls)

    def _dist_legend_sync(self, active):
        """距离图的图例与「当前真正有数据的类别」严格一致，且文字跟着追踪目标走。

        pyqtgraph 0.14 实测：``setData([], [])`` **不会**撤掉图例项
        （``LegendItem.items`` 仍持有它），于是会出现「图例说有这类目标、
        线上却没数据」的死条目。图例是给人读「这条线是什么」的，条目必须
        和线上真有数据一一对应，所以这里显式增删。

        **改名必须撤了重加**：LegendItem 没有 rename API。少了这一步，
        用户在设置页改选追踪目标（或把指纹改名 lsy → 别的）之后，图例会一直
        停在旧名字上，而线上早就是另一个人的数据了 —— 这类「界面说的和图上
        画的是两回事」正是本项目最容易踩的坑（同 _set_match_line 的残留值）。
        """
        if self._dist_legend is None:
            return
        for cls in list(self._dist_legend_on):
            if cls not in active:
                curve = self._dist_curves.get(cls)
                if curve is not None:
                    self._dist_legend.removeItem(curve)
                self._dist_legend_on.discard(cls)
                self._dist_legend_text.pop(cls, None)
        for cls in active:
            curve = self._dist_curves.get(cls)
            if curve is None:
                continue
            label = self._dist_line_label(cls)
            if cls not in self._dist_legend_on:
                self._dist_legend.addItem(curve, label)
                self._dist_legend_on.add(cls)
                self._dist_legend_text[cls] = label
            elif self._dist_legend_text.get(cls) != label:
                # 目标换了 / 指纹改名了：LegendItem 无 rename API，撤了重加
                self._dist_legend.removeItem(curve)
                self._dist_legend.addItem(curve, label)
                self._dist_legend_text[cls] = label

    def _dist_legend_refresh(self):
        """按**当前**追踪目标重算图例文字（不等 analysis_timer）。

        改选目标 / 改名的当下就要显示对：深度分析页可能是后台，而后台
        ``analysis_timer`` 是停的（见 on_tab_changed），``update_analysis_plots``
        不会来刷 —— 用户切回该页时看到的会是一行旧名字。
        """
        self._dist_legend_sync(self._dist_active)

    def _refresh_ttc_hint(self):
        """TTC 分析图下方的告警提示（与监视页 TTC 同源：TTCResult → 分级）。"""
        if not self.ttc_history:
            self.label_prompt.setText('暂无TTC数据')
            return
        ttc = self.ttc_history[-1]
        if ttc != ttc:      # NaN：本帧无 TTC（未接近/不可算/数据不足）
            reason = self.ttc_reason_history[-1] if self.ttc_reason_history else ''
            self.label_prompt.setText(
                'TTC 告警：无' + (f'（{reason}）' if reason else ''))
            return
        cfg = self._ttc.cfg
        level = classify_ttc(ttc, cfg)
        if level == TTCLevel.CRITICAL:
            text = f'TTC 告警：危险（TTC {ttc:.1f} s ≤ {cfg.ttc_critical} s）'
        elif level == TTCLevel.WARNING:
            text = f'TTC 告警：预警（TTC {ttc:.1f} s ≤ {cfg.ttc_warning} s）'
        elif level == TTCLevel.CAUTION:
            text = f'TTC 告警：提示（TTC {ttc:.1f} s ≤ {cfg.ttc_caution} s）'
        else:
            text = f'TTC 告警：无（TTC {ttc:.1f} s）'
        self.label_prompt.setText(text)

    def update_resource_usage(self):
        if not self._analysis_plot_inited and self.global_params.plot_enable:
            return
        import psutil
        cpu_percent = psutil.cpu_percent()
        mem_percent = psutil.virtual_memory().percent
        self.progressBar_cpu.setValue(int(cpu_percent))
        self.progressBar_memory.setValue(int(mem_percent))

    def bind_buttons(self):
        self.QPuahButton_calibrate_status.clicked.connect(self.on_calibrate_clicked)
        self.btn_model_browse.clicked.connect(self.on_model_browse)
        self.btn_label_browse.clicked.connect(self.on_label_browse)
        self.btn_calib_capture.clicked.connect(self.on_calib_capture_clicked)
        self.btn_calib_solve.clicked.connect(self.on_calib_solve_clicked)
        # 录制回放（CHARTER 第 6 条）
        self.btn_rec_toggle.clicked.connect(self.on_rec_toggle)
        self.btn_play_pick.clicked.connect(self.on_play_pick)
        self.btn_play_toggle.clicked.connect(self.on_play_toggle)
        self.btn_play_stop.clicked.connect(self.on_play_stop)
        self.slider_play_pos.sliderMoved.connect(self.on_play_seek)
        self.tabWidget.currentChanged.connect(self.on_tab_change)

    def bind_model_thres_widgets_realtime(self):#更新标签与值
        self.slider_confidence_thres.valueChanged.connect(lambda v: self.update_param_realtime("confidence_thres", v/100, self.label_confidence_thres, "%.1f"))
        self.slider_nms_thres.valueChanged.connect(lambda v: self.update_param_realtime("nms_thres", v/100, self.label_nms_thres, "%.1f"))

    # 采样点的「距离从哪来」—— 决定用户要不要拿尺子
    DIST_MODE_ALL_MEASURED = 0   # 每个距离都用卷尺量
    DIST_MODE_ONE_MEASURED = 1   # 只量第 1 个，其余按框高比推
    DIST_MODE_NONE = 2           # 一个都不量（全自动）

    def _build_dist_source_row(self):
        """标定页 ② 组加一行「距离怎么来」—— 决定用户要不要拿尺子。

        为什么必须有这一行
        ------------------
        相机只能读到**角度**，读不到米。同一个画面既可以是「近处的小目标」，
        也可以是「远处的大目标」（尺度歧义，图像完全相同）。要把角度换算成米，
        必须有且只有一个绝对尺度来源：要么用户拿尺子量一个距离，要么靠
        「人大概有多大」这个先验。这一行就是让用户选尺度从哪来。

        三档的实测精度（2026-10-01 Monte Carlo：4000 次，框底/框顶各 1 px 噪声）
        ------------------------------------------------------------------------
            每个距离都量    95% 分位 |误差| 2.3%
            只量第 1 个     95% 分位 |误差| 2.4%   ← 与上一档几乎一样好
            一个都不量      95% 分位 |误差| 19.9%

        第二档为什么能追平第一档：其余点的距离按**框高比**推
        ``Z_i = Z_锚 × 框高_锚 / 框高_i``，比值里人体尺寸先验**完全抵消**，
        精度只受像素噪声 —— 实测由 4 m 推 5 m 偏差 0.004%。

        第三档的误差是**整体缩放**（各距离同一百分比），因为它完全来自
        「框覆盖的真实长度 ≈ ?」这个先验。换个高矮不同的人就可能偏这么多，
        这不是算法能修的；量一个真值距离就能把它整个消掉。

        ⚠️ 本行是**代码里动态建**的（不重新生成 Ui_*.py）。

        ⚠️ 2026-10-01 下线了另外两行（「已知相机高度（卷尺量）」「框底边不在
        脚上（同时解抬升量）」），标定只剩自标定一条路。下线原因：
        ----------------------------------------------------------------
        填相机高度**不提升**测距精度，却把人带进「公式里的高度 = 卷尺量到的
        安装高度」这个错误概念。公式要的是「相机到**框底边对应位置**的垂直
        落差」，只有框底边贴地时才等于安装高度；本项目实测两者差 0.25 m。
        勾了已知高度、只解俯仰角时，那段偏移会被**整个吸进角度**：解出的
        pitch=2.5°（真值 −0.9°），4 m 标定后 5 m 读 4.72（−5.6%）。
        自标定直接把落差解出来，绕开了这个坑，也不需要用户量高度。
        """
        self.combo_dist_source = QComboBox(self)
        self.combo_dist_source.addItems([
            '每个距离都用卷尺量（约 ±1%）',
            '只量第 1 个距离，其余自动推（约 ±1%）',
            '一个都不量 · 全自动（约 ±10%）',
        ])
        self.combo_dist_source.setCurrentIndex(self.DIST_MODE_ONE_MEASURED)
        self.combo_dist_source.setToolTip(
            '决定每个采样点的「已知距离」从哪来。\n\n'
            '· 只量第 1 个（推荐）：第 1 个点站到卷尺量好的位置（比如地上贴条\n'
            '  胶带标 4 m），之后换几个距离站着点「记为采样点」就行，不用再量。\n'
            '  程序按框高比推出其余点的距离 —— 实测精度与「每个都量」相同。\n\n'
            '· 一个都不量：连一个距离都不用知道，站几个不同位置各点一次即可。\n'
            '  代价是尺度只能靠「人大概有多大」这个先验，误差约 ±10%\n'
            '  （整体缩放：全量程偏同一个百分比）。换个人就可能偏这么多。\n\n'
            '· 每个都量：最传统，每个点都用卷尺量出距离。')
        self.combo_dist_source.currentIndexChanged.connect(
            self._sync_solve_button_enabled)
        self.combo_dist_source.currentIndexChanged.connect(
            self._update_mount_status)

        row = QHBoxLayout()
        row.addWidget(QLabel('距离来源：', self))
        row.addWidget(self.combo_dist_source)
        row.addStretch(1)
        # 插到「已记录采样点…」状态行之前
        self.verticalLayout_mount.insertLayout(
            self.verticalLayout_mount.count() - 1, row)

        # 把「要量的是哪一段距离」写死在界面上。
        # 原 .ui 只写了「已知距离（m）」五个字，而这里恰恰是最容易量错的地方：
        # 量成斜距（卷尺拉到镜头）或量到镜头中心都不对。镜头离地 0.98 m 时，
        # 站 4 m 处水平距离 4.00 m、斜距 4.12 m —— 差 12 cm，约 3%，
        # 且这个误差是**整体缩放**，量一次错就全量程都错。
        hint = getattr(self, 'label_mount_hint', None)
        if hint is not None:
            hint.setWordWrap(True)
            hint.setText(
                '① 要量的距离 = 「镜头正下方的地面点」 到人站的位置，'
                '沿地面量出来的水平距离。\n'
                '不是斜距，也不是到镜头的直线长度。做法：卷尺平铺在地上，'
                '起点对准镜头在地面的投影点（从镜头垂一根线到地面即可找到）。\n'
                '② **相机装多高不用量，也不用填** —— 测距要的是「相机到框底边'
                '对应位置的垂直落差」，它连同俯仰角一起由采样点解出来。\n'
                '③ 第 1 个点量完并「记为采样点」后，「已知距离」会自动置灰 —— '
                '后面几个点**不用再量**，但**必须换到明显不同的距离站好**'
                '（第 1 点在 4 m，第 2 点就站到 5 m 左右：两个点至少要拉开 '
                '1/4；原地不动或只挪一点点会被当成同一个点、或被求解拒答）。\n'
                '④ 解出来的「安装高度」若小于卷尺量到的高度（如 0.73 < 0.98），'
                '说明检测框底边没落在脚上 —— **这是正常的，不要改成卷尺值**。')
        # 同一件事写在控件上：解出的高度不是卷尺值，用户看到 0.73 会以为解错了
        spin_h = getattr(self, 'spin_camera_height', None)
        if spin_h is not None:
            spin_h.setToolTip(
                '相机到**框底边对应位置**的垂直落差（米），接触点法按 '
                'Z = 本值 / tan(俯角) 计算。\n\n'
                '⚠️ 它**不是**卷尺量到的安装高度：检测框底边不落在脚上时\n'
                '（本项目实测底边在小腿中部，卷尺 0.98 m 而这里解出 0.73 m），\n'
                '两者不相等，差的就是框底边离地的那一段。\n\n'
                '测距用的是这一个值 —— 把它改成卷尺量到的高度会让读数整体偏大。')

    # ------------------------------------------------------------------
    # ⚠️ 已下线（2026-10-01）：「已知相机高度（卷尺量）」与
    # 「框底边不在脚上（同时解抬升量）」两行。
    # 原因见 _build_dist_source_row 的 docstring：填相机高度**不提升**测距精度，
    # 还把用户带进「公式里的高度 = 卷尺量到的安装高度」这个错误概念 ——
    # 实测 4 m 单点标定 → 5 m 读 4.72（-5.6%）。
    # 标定现在只剩自标定一条路：解 (垂直落差, 俯仰角) 两个未知数。
    # ------------------------------------------------------------------

    def bind_calibration_widgets(self):#仅标定时生效
        self.slider_sample_freq.valueChanged.connect(lambda v:self.label_sample_freq.setText(f'{v}Hz'))
        self.slider_base_width.valueChanged.connect(lambda v:self.label_base_width.setText(f'{v}px'))
        self.spin_pitch_deg.valueChanged.connect(self.on_pitch_changed)
        self.spin_camera_height.valueChanged.connect(self.on_camera_height_changed)
        # ⚠️ 没有 spin_foot_offset 了 —— 抬升量已随「已知相机高度」一起下线，
        # 见 _build_dist_source_row 的 docstring。
        # 安装参数自标定（标定页 ②，2026-09-29 从监视页搬来）
        self.btn_mark_known.clicked.connect(self.on_mark_known_clicked)
        self.btn_solve_mount.clicked.connect(self.on_solve_mount_clicked)
        # 追踪目标选择（设置页，CHARTER v1.4「建档 + 追踪目标选择」）：
        # 下拉由**指纹档案列表**填充（不是固定规则选项），单选一个作为唯一
        # 追踪目标，选中即写入档案的 is_track_target 并落盘。名字可用右侧
        # 按钮改（用户可改指纹名）。原先的「目标选择规则」下拉已删除 ——
        # 单类别后规则只剩一条，检测器侧 select_target 恒取最高置信度。
        self.combo_track_target.currentIndexChanged.connect(
            self.on_track_target_changed)
        self.btn_rename_track_target.clicked.connect(
            self.on_rename_track_target_clicked)

        # 指纹档案管理（设置页，2026-09-29 新增）：查（列表 + 详情）/ 改（改名）/ 删。
        # 与上面「追踪目标选择」的分工：那边选「跟谁」，这边管档案本身的增删改。
        self.list_profiles.currentRowChanged.connect(self.on_profile_row_changed)
        self.btn_profile_rename.clicked.connect(self.on_profile_rename_clicked)
        self.btn_profile_delete.clicked.connect(self.on_profile_delete_clicked)
        self.btn_profile_refresh.clicked.connect(
            lambda _checked=False: self.refresh_profiles_list())

        # 建档（标定页 ③，CHARTER v1.4）：开始 / 结束建档会话。
        # 「采样点距离」手填框**不接信号** —— 检测回调每帧现读它的值，
        # 用户改了立刻生效，不需要额外的同步或重算。
        self.btn_enroll_toggle.clicked.connect(self.on_enroll_toggle_clicked)

        # 摄像头设备（标定页 ①）：像蓝牙那样按设备记标定
        self.combo_camera_device.currentIndexChanged.connect(
            self.on_camera_device_chosen)
        self.btn_camera_bind.clicked.connect(self.on_bind_camera_clicked)
        self.btn_camera_scan.clicked.connect(self.on_rescan_camera_clicked)

    def bind_other(self):
        self.tabWidget.currentChanged.connect(self.on_tab_change)

    # ------------------------------------------------------------------
    # 相机标定（CHARTER「范围内的」第 1 条）
    # ------------------------------------------------------------------
    def load_calibration(self):
        """按「本机是哪台相机」加载对应内参。

        与旧实现的区别
        -------------
        旧实现直接读 ``models/calib.json`` 就用 —— 隐含假设「这台机器上只有一台
        相机」。于是「换相机」这件事**在数据上不可见**：文件还是那个文件、程序
        照读不误，换一台**同分辨率**的相机就静默沿用旧内参，距离系统性错而界面
        零提示（相机自带的 ``_tune_if_needed()`` 还会把画面调回 640x480，让尺寸
        凑巧对上，把问题盖得更严实）。

        现在分三步：① 认设备 → ② 按设备指纹查档案库 → ③ 判定用不用。
        判定规则在 ``core.camera_profiles.decide_calibration``（纯函数，可单测）。

        没有标定不是错误 —— 只是测距不可用：这里只记录原因，不阻塞启动，
        UI 会明确显示「本设备未标定」，而不是静默给一个假距离。
        """
        # 相对仓库根解析，避免工作目录变化导致找不到（统一走 _resolve_repo_path）
        path = _resolve_repo_path(self.global_params.calib_path)
        self._calib_file = path
        # 安装参数（外参）与内参**同目录、分开存**：两者生命周期不同（内参跟相机走、
        # 安装参数跟机位走），合并会让「重标内参」把安装参数一起冲掉
        self._mount_file = os.path.join(os.path.dirname(path), 'mount.json')
        # 内参档案库：一台相机一条记录（与 calib.json 同目录，便于一起备份）
        self._cam_store_path = cam_profiles.default_store_path(path)
        self._cam_store = cam_profiles.load_store(self._cam_store_path)
        print(f'[设备] 标定档案库 {self._cam_store_path}：'
              f"{len(self._cam_store.get('devices', {}))} 台设备的记录")
        # 旧的单文件标定：仍要读（老用户机器上只有它），但**不再直接生效**
        self._legacy_intrinsics = CameraCalibrator.load(path)
        # 认设备，并据此决定用哪份内参
        self._scan_camera_devices()

    # ------------------------------------------------------------------
    # 摄像头设备识别：像蓝牙那样「记住每台设备」
    # ------------------------------------------------------------------

    def _scan_camera_devices(self):
        """枚举本机摄像头，并据此决定用哪份内参。

        快通路同步、慢通路异步
        -------------------
        Windows 主通路读注册表，实测 **1.4 ms**（``probe_identity_routes.py``），
        同步跑毫无存在感；兜底通路要调 PowerShell，实测 **4.9~6.8 s**，
        同步跑就是"开窗即卡几秒"。所以后者必须丢进 ``DeviceIdentifyThread``。
        """
        rep = enumerate_cameras(allow_slow_fallback=False)
        if rep.devices or not rep.error:
            # 有设备；或者「通路正常但本机确实没有摄像头」—— 都不需要慢查询
            self._apply_identity(rep)
            return
        # 注册表没结果：可能只是这条通路不可用（而不是真的没插相机）
        print(f'[设备] 注册表通路无结果（{rep.error or "无设备"}），转后台兜底查询')
        if self._identify_thread is not None and self._identify_thread.isRunning():
            return
        if hasattr(self, 'label_camera_status'):
            self.label_camera_status.setText(
                '正在识别摄像头……\n'
                '本机的注册表通路没读到设备，正在用备用通路查询（约需几秒）。')
        self._identify_thread = DeviceIdentifyThread(self)
        self._identify_thread.identified.connect(self._apply_identity)
        self._identify_thread.start()

    @Slot(object)
    def _apply_identity(self, rep):
        """拿到设备列表后：判定「现在用的是哪台」，再更新界面与内参。"""
        self._identity_report = rep
        chosen = self._chosen_fingerprint()
        act = resolve_active_device(rep,
                                    remembered=self._cam_store.get('active', ''),
                                    chosen=chosen)
        self._cam_active = act
        print(f'[设备] {rep.summary()} | 判定 {act.confidence}：{act.reason}')
        self.refresh_camera_widgets()
        self.apply_calibration_decision()

    def apply_calibration_decision(self, frame_size=None):
        """决定这次用哪份内参，并把结论落到测距器与界面。

        ``frame_size`` 未知（相机还没打开）时**跳过分辨率比对**，等
        ``on_camera_init_finished`` 拿到真实画面尺寸再复核一次
        （见 ``verify_calibration_against_frame``）。
        """
        act = getattr(self, '_cam_active', None)
        dev = act.device if act else None
        fp = dev.fingerprint if dev else ''
        # 旧标定文件上盖的设备戳：用来拦住「给相机 A 标完、插上同分辨率的相机 B
        # 仍照读旧文件」这个漏洞。**每次现读**而不是缓存 —— 盖戳发生在标定完成与
        # 手动绑定之后，缓存一旦忘了同步就会让这道闸门失效。
        stamped = cam_profiles.read_stamped_device(getattr(self, '_calib_file', ''))
        d = cam_profiles.decide_calibration(
            self._cam_store, fp, legacy=self._legacy_intrinsics,
            frame_size=frame_size, identity_known=bool(fp),
            legacy_device=stamped)
        self._cam_decision = d

        self.global_params.intrinsics = d.intrinsics
        self.global_params.calibrated = bool(d.usable)
        self.global_params.invalid_reason = ('' if d.usable
                                             else (d.blocked_reason or d.status))
        # ⚠️ 测距器**绝不能注入 None**：on_detection_ready 会无条件调它。
        # 不可用时注入「无效内参」（calibrated=False），各方法会自然返回
        # None / 明确原因，而不是崩在 None.is_valid() 上。
        self.ranger.update_intrinsics(d.intrinsics if d.usable
                                      else CameraIntrinsics())
        # ⚠️ 刷新测距控件时**必须带上最后一帧的结果**（不能留默认的 None）：
        # 不带会把原因行与悬停擦空，而读数文字仍留着上一帧的值 —— 界面于是
        # 变成「不可测」+ 一句原因都没有，正是「只看到不可测、不知为什么」那个
        # 老问题，且只在这个异步复核恰好插在两次检测之间时出现（偶发，实测踩到）。
        if not d.usable:
            # 内参不可用时读数必须与原因行同源：一起变成「不可测」，
            # 而不是把上一帧的旧数字留在界面上（显示与判定必须同源）
            self.label_distance_value.setText('不可测')
        self.refresh_distance_widgets(self._last_ranging)
        self.refresh_calib_widgets()
        # ⚠️ 必须连设备状态标签一起刷：判定可能在「相机打开后复核」时被改写
        # （例如分辨率此时才发现不符）。少了这一步，界面会停留在上一轮的文案上
        # —— 显示「已标定」而实际已拒用，是典型的"看着正常、其实不一致"。
        self.refresh_camera_widgets()

        if d.usable:
            self.status_bar.showMessage(
                f'内参已就绪（{d.status}）：fx={d.intrinsics.fx:.1f} '
                f'rms={d.intrinsics.rms_error:.3f}px', 6000)
        else:
            self.status_bar.showMessage(f'测距不可用：{d.status}', 10000)
        self._maybe_prompt_calibration()
        return d

    def verify_calibration_against_frame(self):
        """相机打开后，用**真实画面尺寸**复核一次内参判定。

        为什么必须复核：启动时相机可能还没打开，拿不到画面尺寸，只能跳过分辨率
        校验；而「标定分辨率 ≠ 当前分辨率」恰恰是要拦的那类静默错误 —— 内参随
        分辨率变化，套用会让距离整体偏。所以拿到尺寸后必须再判一次。
        """
        size = self._frame_size()
        if size is None:
            return
        d = self.apply_calibration_decision(frame_size=size)
        print(f'[设备] 画面 {size[0]}x{size[1]}，内参判定：{d.status}')
        if not d.usable and d.blocked_reason:
            self.status_bar.showMessage(f'测距不可用：{d.blocked_reason}', 15000)

    def _frame_size(self):
        """当前摄像头的实际画面尺寸；拿不到返回 None（不猜）。"""
        cap = getattr(self, 'cap', None)
        if cap is None:
            return None
        try:
            if not cap.isOpened():
                return None
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        except Exception:                                        # noqa: BLE001
            return None
        return (w, h) if w > 0 and h > 0 else None

    def _chosen_fingerprint(self) -> str:
        """用户在下拉框里指明过的设备指纹；没指明过返回空串。"""
        combo = getattr(self, 'combo_camera_device', None)
        if combo is None:
            return ''
        return str(combo.currentData() or '')

    def refresh_camera_widgets(self):
        """把「本机摄像头」与「本设备的标定状态」刷到标定页。

        ⚠️ 下拉框的语义必须说准：程序固定打开**索引 0**，所以选中项表达的是
        「我确认索引 0 就是这台」，而不是「选一下就能换相机」—— Windows 上取不到
        索引与设备名的对应关系（见 ``core/camera/device_identity.py`` 的说明）。
        让人误以为能切设备，比不提供这个控件更糟，所以文案里写清楚。
        """
        combo = getattr(self, 'combo_camera_device', None)
        label = getattr(self, 'label_camera_status', None)
        if combo is None or label is None:
            return
        rep = self._identity_report
        act = getattr(self, '_cam_active', None)

        self._loading_device = True
        try:
            combo.clear()
            if rep is None:
                combo.addItem('正在识别……', '')
            elif not rep.devices:
                combo.addItem('未检测到摄像头设备', '')
            else:
                for dv in rep.devices:
                    combo.addItem(dv.label(), dv.fingerprint)
                want = act.device.fingerprint if (act and act.device) else ''
                i = combo.findData(want)
                if i >= 0:
                    combo.setCurrentIndex(i)
        finally:
            self._loading_device = False

        lines = []
        if rep is None:
            lines.append('正在识别摄像头……')
        else:
            lines.append(rep.summary())
            if act is not None and act.device is not None:
                mark = '✓' if act.certain else '⚠'
                lines.append(f'{mark} 程序正在使用的设备：{act.device.name}'
                             f'（{act.reason}）')
                if not act.certain:
                    lines.append('　请在上面的下拉框里指明程序用的是哪一台，'
                                 '之后会记住。')
            elif act is not None:
                lines.append(f'⚠ {act.reason}')

        d = getattr(self, '_cam_decision', None)
        if d is not None:
            lines.append('')
            lines.append(f'标定：{d.status}')
            lines.append(d.detail)
        label.setText('\n'.join(lines))

        bind = getattr(self, 'btn_camera_bind', None)
        if bind is not None:
            bind.setEnabled(bool(d is not None and d.can_bind_legacy))

    @Slot(int)
    def on_camera_device_chosen(self, index):
        """用户在下拉框里指明了「程序正在用的那一台」。"""
        if getattr(self, '_loading_device', False):
            return                        # 程序回填，不是用户操作
        fp = str(self.combo_camera_device.itemData(index) or '')
        if not fp:
            return
        if self._cam_store.get('active', '') != fp:
            cam_profiles.set_active(self._cam_store, fp)
            self._persist_camera_store()
        rep = self._identity_report or IdentityReport()
        self._cam_active = resolve_active_device(
            rep, remembered=self._cam_store.get('active', ''), chosen=fp)
        print(f'[设备] 用户指定：{self._cam_active.reason}')
        self.refresh_camera_widgets()
        self.apply_calibration_decision(self._frame_size())

    @Slot()
    def on_rescan_camera_clicked(self):
        """重新枚举一次（插拔设备后用）。快通路是毫秒级的，点它不用等。"""
        self.status_bar.showMessage('正在重新检测摄像头设备……', 3000)
        self._scan_camera_devices()

    @Slot()
    def on_bind_camera_clicked(self):
        """把当前已加载的旧标定认到本设备名下。

        场景：老用户机器上只有一个 ``calib.json``（未绑定任何设备）。重标一次
        当然最干净，但"我确定就是这台相机、不想重标"是合理诉求 —— 那就让这句话
        变成一个**明确的动作**，而不是靠程序默认猜。所以这里要用户主动确认，
        并且**分辨率对不上就拒绝绑定**（绑了也是在给自己埋雷）。
        """
        act = getattr(self, '_cam_active', None)
        dev = act.device if act else None
        if dev is None or not dev.fingerprint:
            self._warn('绑定标定', '还认不出本机摄像头是哪一台，无法绑定。\n'
                                   '请先点「重新检测设备」。')
            return
        intr = self._legacy_intrinsics
        if intr is None or not intr.is_valid():
            self._warn('绑定标定', '当前没有可用的标定文件，请先标定一次。')
            return
        size = self._frame_size()
        if size is not None and tuple(intr.image_size) != tuple(size):
            self._warn('绑定标定',
                       f'这份标定是按 {intr.image_size[0]}x{intr.image_size[1]} 做的，'
                       f'当前画面是 {size[0]}x{size[1]}，分辨率不一致，不能绑定。\n'
                       f'请对当前相机重新标定一次。')
            return
        try:
            cam_profiles.upsert_profile(
                self._cam_store, dev.fingerprint,
                cam_profiles.profile_from_intrinsics(dev, intr,
                                                     note='由旧标定文件绑定'))
            self._persist_camera_store()
            # 同 on_calib_solved：绑定也要给旧文件盖戳。否则用户"绑定"完这台，
            # 之后插上另一台同分辨率相机时，旧文件仍是"无主的"，判定又会走
            # 「暂用未绑定文件」——等于白绑一次。
            cam_profiles.stamp_device(self._calib_file, dev.fingerprint)
        except OSError as e:
            self._warn('绑定标定', f'写入档案库失败：{e}')
            return
        self.refresh_camera_widgets()
        self.apply_calibration_decision(size)
        self._info('绑定标定',
                   f'已把当前标定绑定到「{dev.name}」。\n\n'
                   f'以后插别的相机不会再用到这份内参；插回这台则自动可用。')

    def _persist_camera_store(self):
        """档案库落盘。失败只降级（本次仍生效），不阻断使用。"""
        path = getattr(self, '_cam_store_path', None)
        if not path:
            return
        try:
            cam_profiles.save_store(path, self._cam_store)
        except OSError as e:
            self.status_bar.showMessage(
                f'标定档案保存失败：{e}（本次仍已生效）', 8000)

    def _maybe_prompt_calibration(self):
        """没有可用标定时提醒标定 —— 每轮启动只弹一次。"""
        d = getattr(self, '_cam_decision', None)
        if d is None or d.usable or self._calib_prompted:
            return
        self._calib_prompted = True
        act = getattr(self, '_cam_active', None)
        name = act.device.name if (act and act.device) else '本机摄像头'
        # 延迟到事件循环：构造期间弹模态框会挡在窗口显示之前，观感很差
        QTimer.singleShot(0, lambda: self._notify_calibration_needed(name, d))

    def _notify_calibration_needed(self, name, decision):
        self._warn(
            '需要标定相机',
            f'这台相机（{name}）还没有可用的内参，测距不可用'
            f'（程序不会给出猜测值）。\n\n'
            f'原因：{decision.status}\n\n'
            f'要做什么：切到「标定」页 → ① 棋盘标定组 → 把棋盘格放进画面 →\n'
            f'点「开始采集」（采够 10 帧）→ 点「求解并保存」。\n\n'
            f'标定一次即可：结果会按这台设备记住，以后插回来直接可用。')

    def _warn(self, title, text):
        """统一的警告弹窗出口 —— 便于自动化验证时替换掉阻塞式对话框。"""
        QMessageBox.warning(self, title, text)

    def _info(self, title, text):
        QMessageBox.information(self, title, text)


    def load_mount_params_ui(self):
        """把落盘的安装参数（相机高度 + 俯仰角）回填到标定页，并立即生效。

        为什么要有这一步
        ---------------
        安装参数原先只活在内存里（``GlobalParams``）：自标定解出来只写进控件，
        程序一关就没了 —— 下次启动得重解一遍。开发者本机不容易察觉（每次都现场
        标），但换台机器、换个人用，就变成「棋盘标完还得再搞一次」，而它本来
        只需要做一次。内参有 ``models/calib.json``，安装参数同样该有。

        回填走**与手工填写同一条通路**（``setValue`` -> ``valueChanged`` ->
        重建 ``RangingConfig``），所以没有额外的「应用」按钮；``_loading_mount``
        在此期间挡住落盘，避免把「加载」当成「用户改动」再写一次。

        ⚠️ 但那条通路**在本函数被调用时还没接通**：``init_ui()`` 跑在
        ``bind_calibration_widgets()`` **之前**，此刻 ``valueChanged`` 还没有
        连到槽函数 —— 只 ``setValue`` 会得到一个**控件显示对了、而
        ``global_params`` 还是 0** 的静默失效（实测踩到：界面显示 1.20 m，
        测距侧仍认为「未填安装高度」，接触点法直接不可用）。
        所以下面除了 ``setValue``，还**显式同步一次** global_params 与 ranger。
        """
        path = getattr(self, '_mount_file', None)
        if not path:
            return
        data = load_mount_params(path)
        if not data:
            return
        h0 = float(data['camera_height'])
        # 向后兼容：旧文件里可能带 foot_offset_m（「框底边抬升量」，随
        # 「已知相机高度」一起下线）。几何用的是落差 (H − off)，把抬升量
        # **折进**相机高度、抬升量归零，结果与旧文件完全等价。
        off0 = float(data.get('foot_offset_m', 0.0) or 0.0)
        h0_eff = max(0.0, h0 - off0)
        self._loading_mount = True
        try:
            self.spin_camera_height.setValue(h0_eff)
            self.spin_pitch_deg.setValue(float(data['pitch_deg']))
        finally:
            self._loading_mount = False
        h = float(self.spin_camera_height.value())
        p = float(self.spin_pitch_deg.value())
        off = 0.0

        # 显式生效（不能依赖 valueChanged —— 见上面的 ⚠️）。三步与
        # on_pitch_changed / on_camera_height_changed 保持完全一致，
        # 保证「加载出来的」与「手工填的」走到同一个内部状态。
        self.global_params.camera_height = h
        self.global_params.pitch_deg = p
        self.global_params.foot_offset_m = off
        self.ranger.update_config(RangingConfig.from_params(self.global_params))
        self.refresh_distance_widgets(self._last_ranging)

        src = data.get('source') or '已保存'
        when = data.get('saved_at') or '—'
        self.status_bar.showMessage(
            f'已加载安装参数：垂直落差 {h:.2f} m、俯仰角 {p:.1f}°'
            f'（{src} @ {when}）', 6000)
        print(f'[安装参数] 加载 {path}  H={h:.2f} m  θ={p:.1f}°  '
              f'source={src} saved_at={when}')

    def _persist_mount_params(self, source: str):
        """把当前控件的安装参数落盘。

        取**控件值**而不是 ``global_params``：控件精度（高度 2 位、俯仰角 1 位）
        才是实际生效的值，存下来才能与「下次启动看到的数」一致 —— 否则会出现
        「存的是 1.2365、显示的是 1.24」这类对不上的情况。

        落盘失败**不阻断测距**：参数已在内存中生效，只是下次要重填，属于降级而非故障。
        """
        if getattr(self, '_loading_mount', False):
            return
        path = getattr(self, '_mount_file', None)
        if not path:
            return
        try:
            save_mount_params(path, self.spin_camera_height.value(),
                              self.spin_pitch_deg.value(), source=source,
                              foot_offset_m=0.0)
        except OSError as e:
            self.status_bar.showMessage(f'安装参数保存失败：{e}（本次仍已生效）', 8000)

    def refresh_calib_widgets(self):
        """把标定状态同步到设置页。

        注意顺序：**采集进度优先**。本函数在切到「设置」页签时也会被调用，
        若把进度提示写在前面，用户切换一次页签就会看到"未标定…"而以为帧丢了。
        """
        if self.global_params.calibrated:
            intr = self.global_params.intrinsics
            self.label__calibrate_status.setText('已标定')
            info = (
                f'fx={intr.fx:.1f}  fy={intr.fy:.1f}  '
                f'cx={intr.cx:.1f}  cy={intr.cy:.1f}\n'
                f'重投影误差 {intr.rms_error:.3f} px '
                f'（<0.5 优 / <1.0 可接受）'
            )
        else:
            self.label__calibrate_status.setText('未标定')
            reason = self.global_params.invalid_reason or '未标定'
            info = (
                f'{reason}。测距不可用（不会给出猜测值）。\n'
                f'请让棋盘格在画面中变换位置与倾斜角，至少采集 10 帧后求解。'
            )

        n = self._calib_frame_count()
        self.btn_calib_solve.setEnabled(n > 0)
        if n > 0:
            state = '采集中' if getattr(self, '_collecting', False) else '已暂停采集'
            info = (f'{state}：已采集 {n} 帧（没有丢弃）。\n'
                    f'点「求解并保存」解算内参；想补采就再点「开始采集」。')
        self.label_calib_info.setText(info)

    def _make_calibrator(self):
        cols = self.spin_pattern_cols.value()
        rows = self.spin_pattern_rows.value()
        square_m = self.spin_square_mm.value() / 1000.0
        return CameraCalibrator(pattern_size=(cols, rows), square_size=square_m)

    def _calib_frame_count(self) -> int:
        return self.calibrator.frame_count if self.calibrator is not None else 0

    def _set_collecting(self, collecting: bool):
        """切换「采集中/已暂停」状态，并同步按钮文字与「求解并保存」的可用性。"""
        self._collecting = collecting
        self.btn_calib_capture.setText('停止采集' if collecting else '开始采集')
        self.btn_calib_solve.setEnabled(self._calib_frame_count() > 0)

    @Slot()
    def on_calib_capture_clicked(self):
        """开始/暂停采集。只在采集状态下接帧，避免误采普通画面。

        ⚠️ 暂停**绝不清空已采帧**（2026-09-23 用户实际故障）：
        采到 50 帧后点了一下这个按钮（当时它写着"停止采集"），再去求解，
        弹出"还没有采集到有效帧"，整场白采。根因就是旧代码在这里
        ``self.calibrator = None``，把已采的 50 帧连同标定器一起丢了，
        而界面只提示"已停止采集。"，用户根本不知道帧没了。
        现在改成：暂停只停止接帧，帧留着，随时可求解或继续补采。
        """
        if self.cap is None or not self.cap.isOpened():
            QMessageBox.warning(self, '标定错误', '摄像头未连接，无法进行标定！')
            return

        if not getattr(self, '_collecting', False):
            if self.calibrator is None:          # 只在没有存量帧时新建
                self.calibrator = self._make_calibrator()
            self._set_collecting(True)
            n = self._calib_frame_count()
            head = f'继续采集中（已有 {n} 帧）' if n else '采集中'
            self.label_calib_info.setText(
                f'{head}：请让棋盘格在画面中变换位置与倾斜角。（已采集 {n} 帧）')
        else:
            self._set_collecting(False)
            n = self._calib_frame_count()
            self.label_calib_info.setText(
                f'已暂停采集，已保留 {n} 帧（没有丢弃）。\n'
                f'点「求解并保存」解算内参；想补采就再点「开始采集」。')

    @Slot()
    def on_calib_solve_clicked(self):
        """求解内参并持久化 —— **丢到子线程去解**，界面不冻。

        2026-09-23 修正：旧代码在这里同步调 ``self.calibrator.calibrate()``，
        而 ``cv2.calibrateCamera`` 实测 50 帧要 **17 s**，点一下按钮整个界面
        就卡住十几秒不动。现在本槽函数只做「停接帧 → 丢线程 → 立刻返回」，
        结果由 ``on_calib_solved`` 处理。
        """
        if self._solving:
            return                       # 已在求解，忽略重复点击

        if self.calibrator is None or self.calibrator.frame_count == 0:
            QMessageBox.warning(
                self, '标定错误',
                '还没有采集到有效帧。\n\n'
                '请先点「开始采集」，让棋盘格完整出现在画面里；\n'
                '提示出现「检测到棋盘格 ✓」后才算采到一帧。')
            return

        # 求解期间停止接帧（避免边解边往点列表里加），但**帧全部保留**
        self._set_collecting(False)
        self._solving = True
        self.btn_calib_solve.setEnabled(False)

        n = self.calibrator.frame_count
        self.label_calib_info.setText(
            f'正在求解内参……（共 {n} 帧）\n'
            f'实测 50 帧约需十几秒；界面可以继续操作，解完会自动弹结果。')
        self.status_bar.showMessage(f'正在后台求解相机内参（{n} 帧）……')

        self._solve_thread = CalibSolveThread(
            self.calibrator.object_points, self.calibrator.image_points,
            self.calibrator.image_size, self)
        self._solve_thread.solved.connect(self.on_calib_solved)
        self._solve_thread.start()

    @Slot(object, str)
    def on_calib_solved(self, intr, err):
        """求解线程回主线程的结果处理：写盘、生效、体检、汇报。

        线程里不碰任何 Qt 控件；弹窗/写文件/改状态一律回到主线程做。
        """
        self._solving = False
        self.status_bar.clearMessage()
        self.btn_calib_solve.setEnabled(self._calib_frame_count() > 0)

        if intr is None:
            self.label_calib_info.setText(
                f'求解失败：{err}\n（已采的帧仍保留，可补采后重试）')
            QMessageBox.critical(self, '标定失败', f'求解内参出错：{err}')
            return

        try:
            CameraCalibrator.save(intr, self._calib_file)
        except Exception as e:
            self.label_calib_info.setText(f'内参写不进去：{e}（已采的帧仍保留）')
            QMessageBox.critical(self, '标定失败', f'标定文件写入失败：{e}')
            return

        # 同时按**设备**记一份 —— 这是「换相机自动认出来」的关键一步。
        # 只写 calib.json 的话，下次插上另一台相机仍会照读这份内参。
        act = getattr(self, '_cam_active', None)
        dev = act.device if act else None
        bound = bool(dev is not None and dev.fingerprint)
        bind_note = ''
        if bound:
            try:
                cam_profiles.upsert_profile(
                    self._cam_store, dev.fingerprint,
                    cam_profiles.profile_from_intrinsics(dev, intr, note='本机标定'))
                self._persist_camera_store()
                # 顺手给 calib.json 盖个设备戳。旧程序读它时会被忽略（
                # CameraCalibrator.load 只取 dataclass 里有的字段），所以对
                # 树莓派端与旧版无害；但新版本据此能拦住最顽固的一种误用：
                # 给相机 A 标完，插上**另一台同分辨率**的相机 B —— 没有戳时
                # 判定只能含糊地"暂用旧文件"，有了戳就能明确拒用。
                cam_profiles.stamp_device(self._calib_file, dev.fingerprint)
                bind_note = (f'\n\n已按设备记住：{dev.name}\n'
                             f'（指纹 {dev.fingerprint}）\n'
                             f'以后插别的相机不会误用这份内参。')
                print(f'[设备] 标定已绑定到 {dev.name} / {dev.fingerprint}')
            except OSError as e:
                bind_note = f'\n\n⚠️ 按设备保存失败：{e}（文件版标定仍已保存）'
                self.status_bar.showMessage(f'按设备保存失败：{e}', 8000)
        else:
            bind_note = ('\n\n⚠️ 没能识别出本机摄像头，这份标定**无法按设备记住**，'
                         '换相机时可能被误用。请点「重新检测设备」后再标一次。')

        # 求解成功后立即生效，不必重启；统一走判定函数（单一出口，避免两处各写一份状态）
        self._legacy_intrinsics = intr
        self.calibrator = None            # 成功后清空：下次「开始采集」是全新一轮
        self._set_collecting(False)
        self.apply_calibration_decision(self._frame_size())

        w, h = intr.image_size
        warns = []
        if intr.rms_error >= 1.0:
            warns.append(f'重投影误差 {intr.rms_error:.3f} px 偏高（>1.0 已不可接受）')
        if not (0.15 * w < intr.cx < 0.85 * w) or not (0.15 * h < intr.cy < 0.85 * h):
            warns.append(f'主点 (cx={intr.cx:.0f}, cy={intr.cy:.0f}) 明显偏离画面中心'
                         f'（画面 {w}x{h}）')
        # fx/fy 合理区间：rms 和主点都看不出"焦距发疯"。实测 8 帧姿态不变时
        # 能解出 fx=40847 而 rms 才 0.21 —— 那是退化解，拿去测距全是废数。
        # 正常焦距落在 [0.2·宽, 4·宽]（对 640 宽即 128~2560 px，
        # 覆盖约 15°~120° 水平视场角），出界基本就是退化或尺寸记录错了。
        if not (0.2 * w <= intr.fx <= 4.0 * w) or not (0.2 * h <= intr.fy <= 4.0 * h):
            warns.append(f'焦距 fx={intr.fx:.0f}, fy={intr.fy:.0f} 超出合理区间'
                         f'（{0.2 * w:.0f}~{4.0 * w:.0f} px）—— 解出了退化解，'
                         f'这份数据不可用于测距，必须重采')

        detail = (f'内参已保存到：\n{self._calib_file}\n\n'
                  f'fx={intr.fx:.1f}  fy={intr.fy:.1f}\n'
                  f'cx={intr.cx:.1f}  cy={intr.cy:.1f}\n'
                  f'重投影误差={intr.rms_error:.3f} px' + bind_note)

        if warns:
            QMessageBox.warning(
                self, '标定完成，但质量存疑',
                detail + '\n\n' + '\n'.join('· ' + s for s in warns) +
                '\n\n常见原因：棋盘姿态变化不够（只在同一角度平移），或画面模糊、反光。\n'
                '建议重采：让棋盘走遍画面四角，并做出明显倾斜（左右各约 20°）。\n'
                '（结果已保存，可以先用；想重标就再点「开始采集」。）')
        else:
            quality = '优' if intr.rms_error < 0.5 else '可接受'
            QMessageBox.information(self, '标定完成', detail + f'\n\n质量：{quality}')

    @Slot()
    def on_pitch_changed(self, value):
        """俯仰角改了立即重建测距配置 —— 不需要重标定。"""
        self.global_params.pitch_deg = float(value)
        self.ranger.update_config(RangingConfig.from_params(self.global_params))
        self._persist_mount_params('手工填写')

    @Slot()
    def on_camera_height_changed(self, value):
        """相机安装高度改了立即重建测距配置 —— 不需要重标定。

        这是地面接触点法（CHARTER 第 2 条）唯一的安装参数：卷尺量一次镜头中心
        到地面的高度。填 0 视为「未测量」，此时接触点法与反解判据都不可用，
        部分可见的目标会明确显示「不可测」，而不是按某个默认身高硬算。
        """
        self.global_params.camera_height = float(value)
        self.ranger.update_config(RangingConfig.from_params(self.global_params))
        self.refresh_distance_widgets(self._last_ranging)
        self._persist_mount_params('手工填写')

    def _ranging_tooltip(self, res=None):
        """距离读数的悬停说明。

        优先级：**为什么不可测 > 安装参数填没填**。UI 上位置有限，但"为什么"
        必须能查到 —— 否则用户只看到"不可测"，分不清是没填安装高度、
        还是目标只露出一部分。这直接对应 CHARTER 里"不给猜测值"的要求。
        """
        if res is not None and res.reason:
            return res.reason
        h = self.global_params.camera_height
        if h <= 0:
            return ('未填相机安装高度：只能对完整可见的目标测距（框跨度法）。\n'
                    '可以用卷尺量一次镜头中心到地面的高度填上，也可以在'
                    '「安装参数自标定」里把目标摆到已知距离反解出来；\n'
                    '填好后即可对部分可见的目标测距（如头顶出画的人）。')
        # 俯仰角误差敏感度 ≈ 0.01745·Z/H（每 1°）—— 与 H 成反比，装得越高越不敏感。
        # 这里算的是 10 m 处的值，用来提醒用户「角度别量错」。
        sens = 0.01745 * 10.0 / h * 100.0
        return (f'相机安装高度 {h:.2f} m，已启用地面接触点法。\n'
                f'10 m 处每 1° 的俯仰角误差约带来 {sens:.0f}% 距离误差'
                f'（装得越高越不敏感）。\n'
                f'高度与俯仰角都可由「安装参数自标定」反解，不必手工量。')

    def refresh_distance_widgets(self, res=None):
        """把距离读数的**悬停说明**与**界面上那行原因**成对刷新。

        为什么要成对：悬停要鼠标停上去才看得见，而"为什么不可测"是用户
        当下就要知道的信息 —— 实测有人因为只看到「不可测」而怀疑是自己
        模型选错了。两者都从同一份 ``RangingResult`` 取，**同源**才不会
        一个说 A、一个说 B（显示与判定不同源，之前在设备状态标签上踩过一次）。
        """
        self.label_distance_value.setToolTip(self._ranging_tooltip(res))
        self.label_distance_reason.setText(self._ranging_reason_text(res))

    def refresh_ttc_widgets(self, res: TTCResult):
        """刷新碰撞预警读数行（值 + 分级着色）与原因小字。

        显示规则（与离线分析同一套分级语义）：

        - **可用**：``TTC x.x s（分级）``。参考级（近场框跨度法（横）距离 < 约 2 m）
          额外加「？」，与距离读数的参考值标记同款 —— 不冒充精确值；
        - **不可用**：值落回 ``--``，原因小字给出**为什么**（样本不足 /
          未在接近 / 本帧离群 / 测距不可用…）。无目标时原因也清空 ——
          「没有目标」是常态而非异常，每帧写一句只会刷屏。

        分级着色只在**级别变化**时 setStyleSheet（防每帧重绘抖动）：
        提示=琥珀、预警=深橙、危险=红；「无」恢复默认色。
        """
        if res.available:
            txt = f'TTC {res.ttc:.1f} s（{res.level.value}）'
            if res.is_reference:
                txt += ' ？'
            self.label_ttc_value.setText(txt)
            self.label_ttc_reason.setText(
                '参考级：近场框跨度法（横）距离算出的碰撞时间（±15% 起步），'
                '仅供参考' if res.is_reference else '')
        else:
            self.label_ttc_value.setText('--')
            self.label_ttc_reason.setText(
                '' if '无目标' in res.reason else res.reason)
        style = {
            TTCLevel.CRITICAL: 'font-weight: bold; font-size: 12pt; '
                               'color: #A32D2D;',
            TTCLevel.WARNING: 'font-weight: bold; font-size: 12pt; '
                              'color: #993C1D;',
            TTCLevel.CAUTION: 'font-weight: bold; font-size: 12pt; '
                              'color: #854F0B;',
            TTCLevel.NONE: 'font-weight: bold; font-size: 12pt;',
        }[res.level if res.available else TTCLevel.NONE]
        if style != self._last_ttc_style:
            self.label_ttc_value.setStyleSheet(style)
            self._last_ttc_style = style

    def _ranging_reason_text(self, res=None) -> str:
        """距离读数下面那行小字：把「为什么」直接摆在界面上，而不是只藏在悬停里。

        三层，与 ``_ranging_tooltip`` 同源：

        ① **内参不可用**（没标定 / 分辨率不符 / 属于另一台相机）—— 这是最根本
           的一条，任何目标都测不了，所以优先显示，并指向「设置」页；
        ② **本帧目标自己的原因**（``RangingResult.reason``）—— 「脚被画面下边界
           裁掉（目标太近）」「框底边落在相机水平线以上，不可能踩在地面上」等；
        ③ **正常出数** —— 报出所用方法，让人知道这个数是靠哪条路给的
           （接触点法靠脚，框跨度法靠全身框 + 档案里量出的框跨度）。
        """
        if not self.global_params.calibrated:
            why = self.global_params.invalid_reason or '未标定'
            return f'{why} —— 内参不可用，测距已停（见「设置」页）'
        if res is not None and res.reason:
            return res.reason
        if res is not None and res.distance is not None:
            return f'（{_method_display(res.method)}）'
        return ''

    # ------------------------------------------------------------------
    # 安装参数自标定（外参：相机安装高度 + 俯仰角）
    # ------------------------------------------------------------------
    # 为什么是「标定」而不是「手工填」
    # ------------------------------
    # 接触点法 Z = H_相机 / tan(俯仰角 + atan((v_底 − cy)/fy)) 需要两个量：
    # 相机装多高、朝下多少度。卷尺与量角器都能量，但**俯仰角精度极敏感** ——
    # 10 m 处每 1° 约带来 0.01745·Z/H 的距离误差（H=0.7 m 时就是 25%/1°），
    # 而角度恰好是最难量准的那个。反过来，把目标摆到**卷尺已知的距离**上、
    # 读出框底边像素，两个已知距离就能把 (H, 俯仰角) 同时解出来
    # （见 core/calibration.solve_mount_params）—— 相机装多高都能解。
    #
    # 为什么采一段而不是取一帧：底边像素是观测量，它的随机误差直接进解算
    # （1 px 噪声 -> 俯仰角约 ±0.13°）。所以取 ~1 秒窗口的均值，并用散布
    # 判断目标是否静止；散布过大就拒收这一次，而不是记一个脏点。

    MARK_WINDOW_MS = 1000        # 采样窗口长度（毫秒）
    MARK_MIN_FRAMES = 5          # 窗口内至少收到几帧有效检测
    MARK_MAX_SPREAD_PX = 3.0     # 底边像素散布上限：超过说明目标在动

    @Slot()
    def on_mark_known_clicked(self):
        """记一个「已知距离」采样点（窗口内取平均，避免单帧噪声）。"""
        if not self.global_params.calibrated or self.global_params.intrinsics is None:
            QMessageBox.warning(
                self, '安装参数自标定',
                '相机还没标定，没有可用内参，无法解算安装参数。\n'
                '请先在「标定」页 ① 棋盘标定组里完成棋盘格标定。')
            return
        if self.global_params.detection_height <= 0:
            QMessageBox.warning(
                self, '安装参数自标定',
                '当前没有检测到目标，无法采样。\n\n'
                '请让目标（人 / 椅子等）完整出现在画面里并保持静止，再点本按钮。')
            return
        self._marking = True
        self._mark_samples = []
        self._mark_distance = float(self.spin_known_dist.value())
        self.btn_mark_known.setEnabled(False)
        if self._dist_mode() == self.DIST_MODE_NONE:
            self.label_mount_status.setText(
                '正在采样（全自动档：不用量距离）……请让目标静止，'
                '再换一个距离采下一个点')
        else:
            self.label_mount_status.setText(
                f'正在采样 {self._mark_distance:.2f} m 处的目标……请让目标静止')
        if self._mark_timer is not None:
            self._mark_timer.stop()
        self._mark_timer = QTimer(self)
        self._mark_timer.setSingleShot(True)
        self._mark_timer.timeout.connect(self.on_mark_finished)
        self._mark_timer.start(self.MARK_WINDOW_MS)

    @Slot()
    def on_mark_finished(self):
        """采样窗口结束：先查帧数与散布，合格才记为一个采样点。"""
        self._marking = False
        self.btn_mark_known.setEnabled(True)
        samples = self._mark_samples
        self._mark_samples = []
        z = self._mark_distance

        if len(samples) < self.MARK_MIN_FRAMES:
            self.label_mount_status.setText(
                f'采样失败：这 {self.MARK_WINDOW_MS / 1000:.0f} 秒里只检测到 '
                f'{len(samples)} 帧（至少需要 {self.MARK_MIN_FRAMES} 帧）。'
                f'请让目标完整出现在画面里再重试。')
            return
        # 兼容两种元素形态（dict = 现在；float = 只记底边的旧格式）
        def _field(key, alt):
            return [s[key] if isinstance(s, dict) else alt(s) for s in samples]

        arr = np.asarray(_field('bottom', lambda s: float(s)), dtype=float)
        spread = float(arr.std())
        if spread > self.MARK_MAX_SPREAD_PX:
            self.label_mount_status.setText(
                f'采样失败：框底边像素散布 {spread:.1f} px 偏大'
                f'（> {self.MARK_MAX_SPREAD_PX:.0f} px），目标可能在移动。'
                f'请让目标静止后重新采样。')
            return

        rec = {'dist': z, 'v': float(arr.mean()),
               'std': spread, 'n': len(arr)}
        if samples and isinstance(samples[0], dict):
            tops = np.asarray(_field('top', lambda s: float('nan')), dtype=float)
            hs = np.asarray(_field('h', lambda s: float('nan')), dtype=float)
            ws = np.asarray(_field('w', lambda s: float('nan')), dtype=float)
            rec.update({
                'top': float(np.nanmean(tops)),
                'box_h': float(np.nanmean(hs)),
                'box_w': float(np.nanmean(ws)),
                'clip_bottom': any(bool(s.get('clip_bottom')) for s in samples),
                'clip_top': any(bool(s.get('clip_top')) for s in samples),
            })
        # 这一点的距离要不要用户量 —— 由「距离来源」决定：
        #   全自动档一个都不用；「只量第 1 个」档只在还没有已知点时才问。
        # 没量距离的点的距离后面由 distances_from_box_height 从框高推出来。
        mode = int(self.combo_dist_source.currentIndex())
        n_known = sum(1 for m in self._mount_marks
                      if m.get('dist') is not None)
        if mode == self.DIST_MODE_NONE or (
                mode == self.DIST_MODE_ONE_MEASURED and n_known >= 1):
            rec['dist'] = None
        else:
            rec['dist'] = float(z)

        # 同一位置重复标记 -> 覆盖。没量距离的点只能靠框高判重（框高 ∝ 1/距离）。
        new_h = rec.get('box_h') or 0.0
        if rec['dist'] is None:
            self._mount_marks = [
                m for m in self._mount_marks
                if m.get('dist') is not None
                or abs((m.get('box_h') or 0.0) - new_h) > 0.03 * max(new_h, 1.0)]
        else:
            self._mount_marks = [
                m for m in self._mount_marks
                if m.get('dist') is None or abs(m['dist'] - z) > 0.05]
        self._mount_marks.append(rec)
        # 按框高降序 = 按距离升序。这样「没量距离的点」也能排进正确次序
        # （dist 可能是 None，不能拿来排序）。
        self._mount_marks.sort(key=lambda m: -float(m.get('box_h') or 0.0))
        self._sync_solve_button_enabled()
        self._update_mount_status()

    def _dist_mode(self) -> int:
        """「距离来源」下拉的当前档位。控件还没建好时按「每个都量」处理（旧行为）。"""
        combo = getattr(self, 'combo_dist_source', None)
        if combo is None:
            return self.DIST_MODE_ALL_MEASURED
        return int(combo.currentIndex())

    def _sync_dist_input_enabled(self):
        """「已知距离」输入框这一轮要不要填 —— 由「距离来源」与已有采样点决定。

        全自动档永远不用填；「只量第 1 个」档在已经有已知点之后也不用再填，
        这样用户换位置时不用再去找卷尺。
        """
        spin = getattr(self, 'spin_known_dist', None)
        if spin is None:
            return
        mode = self._dist_mode()
        if mode == self.DIST_MODE_NONE:
            spin.setEnabled(False)
        elif mode == self.DIST_MODE_ONE_MEASURED:
            n_known = sum(1 for m in self._mount_marks
                          if m.get('dist') is not None)
            spin.setEnabled(n_known == 0)
        else:
            spin.setEnabled(True)

    def _sync_solve_button_enabled(self):
        """「求解」按钮的可用条件 —— 只取决于「距离来源」这一个下拉。

        要解 (垂直落差, 俯仰角) 两个未知数，就需要**两个不同距离**的采样点；
        但这两点的距离不一定要用户量 —— 见 ``_build_dist_source_row``：

            每个距离都量   -> 至少 2 个**已知**距离
            只量第 1 个    -> 至少 1 个已知距离 + 总共 2 个点
            一个都不量     -> 总共 2 个点即可（距离全靠框高先验推）
        """
        n_total = len(self._mount_marks)
        n_known = sum(1 for m in self._mount_marks if m.get('dist') is not None)
        mode = self._dist_mode()
        if mode == self.DIST_MODE_ALL_MEASURED:
            ok = n_known >= 2
        elif mode == self.DIST_MODE_ONE_MEASURED:
            ok = n_known >= 1 and n_total >= 2
        else:
            ok = n_total >= 2
        self.btn_solve_mount.setEnabled(ok)

    def _update_mount_status(self):
        """把已记录的采样点回显到「标定」页 ② 组的粗体状态行（含还差几个、能不能求解）。"""
        marks = self._mount_marks
        self._sync_dist_input_enabled()

        def one(m):
            d = m.get('dist')
            head = f"距离 {d:.2f} m" if d else "距离 自动推"
            s = (f"{head} → 底边 {m['v']:.0f} px"
                 f"（{m['n']} 帧，散布 {m['std']:.1f} px）")
            # 框高是「框底边到底是不是脚」的唯一自查依据，必须上屏
            if m.get('box_h'):
                s += f"、框高 {m['box_h']:.0f} px"
            if m.get('clip_bottom'):
                s += ' ⚠️贴底'
            if m.get('clip_top'):
                s += ' ⚠️贴顶'
            return s

        text = '已记录采样点：' + '、'.join(one(m) for m in marks)
        # 「距离来源」回显：让用户清楚这一轮要不要拿尺子、代价是多少
        _mode = self._dist_mode()
        _n_known = sum(1 for m in marks if m.get('dist') is not None)
        if _mode == self.DIST_MODE_ALL_MEASURED:
            text += '\n距离来源：每个点都用卷尺量（约 ±1%）'
        elif _mode == self.DIST_MODE_ONE_MEASURED:
            text += ('\n距离来源：只量第 1 个，其余按框高比自动推（约 ±1%）'
                     + ('—— 已知距离已够：**换到明显不同的距离**站好直接点，'
                        '不用再量（原地不动会被当成同一个点）'
                        if _n_known else '—— 下一个点请用卷尺量出距离'))
        else:
            text += (f'\n距离来源：全自动，一个都不用量（约 ±'
                     f'{BODY_SPAN_PRIOR_REL_SIGMA * 100:.0f}%，是整体缩放；'
                     f'量一个距离即可降到 ±1%）')
        if any(m.get('clip_bottom') for m in marks):
            text += ('\n⚠️ 有点贴到画面底缘了 —— 那种点「框底边」不是脚，'
                     '喂进解算会解出假答案。请换个更远的距离重采该点。')
        elif len(marks) < 2:
            _kd = [m['dist'] for m in marks if m.get('dist')]
            _tip = ('' if not _kd
                    else f'：已采 {max(_kd):.2f} m，下一个点请站到 '
                         f'{max(_kd) * 1.25:.2f} m 左右 —— **明显更远**，'
                         f'别只挪一点点，也别更近（近了会贴到画面底缘）')
            text += (f'\n还差 {2 - len(marks)} 个：换一个**明显不同**的距离'
                     f'{_tip}，站定后点「记为采样点」')
        elif len(marks) == 2:
            text += ('\n可以点「求解安装参数」。注意两点**无法自查**标记错误'
                     '（如把膝盖当成脚），建议再补一个距离做三点')
        else:
            text += '\n可以点「求解安装参数」'
        self.label_mount_status.setText(text)

    @Slot()
    def on_solve_mount_clicked(self):
        """由采样点反解 (垂直落差, 俯仰角)，并写回标定页立即生效。

        「垂直落差」= 相机到**框底边对应位置**的垂直距离。框底边不在脚上时
        它小于卷尺量到的安装高度（本项目实测 0.73 vs 卷尺 0.98）—— 这是
        测距公式真正需要的那个量，别拿卷尺值去覆盖它。
        """
        intr = self.global_params.intrinsics
        if intr is None or not intr.is_valid():
            QMessageBox.warning(self, '安装参数自标定',
                                '相机未标定（没有可用内参），无法解算安装参数。')
            return
        # ---- 采样点的距离从哪来 ----------------------------------------
        # 「每个都量」档：直接用用户填的距离。
        # 「只量第 1 个」档：其余点的距离按**框高比**推（精度与量的几乎相同）。
        # 「全自动」档：全部靠人体尺寸先验推（误差约 ±10%，整体缩放）。
        mode = self._dist_mode()
        scale_rel_sigma = 0.0
        if mode == self.DIST_MODE_ALL_MEASURED:
            marks = [(m['dist'], m['v']) for m in self._mount_marks
                     if m.get('dist') is not None]
        elif mode == self.DIST_MODE_ONE_MEASURED:
            anchors = [m for m in self._mount_marks
                       if m.get('dist') is not None]
            if not anchors:
                QMessageBox.warning(
                    self, '安装参数自标定',
                    '「只量第 1 个距离」这一档要求**至少有一个点**是用卷尺量的。\n'
                    '请站到卷尺量好的位置再采一次，或把「距离来源」改成全自动。')
                return
            anchor = anchors[0]
            marks = []
            for m in self._mount_marks:
                if m.get('dist') is not None:
                    marks.append((float(m['dist']), float(m['v'])))
                else:
                    sub, _ = distances_from_box_height([m], intr,
                                                       anchor=anchor)
                    marks.extend(sub)
        else:
            marks, scale_rel_sigma = distances_from_box_height(
                self._mount_marks, intr)
        if len(marks) < 2:
            self.label_mount_status.setText(
                f'求解未通过：有效采样点只有 {len(marks)} 个，至少需要 2 个')
            QMessageBox.warning(
                self, '安装参数自标定',
                f'有效采样点只有 {len(marks)} 个（至少需要 2 个不同距离的采样点）。\n'
                '请换一个距离再点一次「记为采样点」。')
            return
        # 距离由框高推出来的两档，采样点只能在「不贴画面底缘」的窄区间里取，
        # 达不到默认的 1.5 倍跨度门槛 —— 见 MOUNT_MIN_DIST_SPAN 的注释。
        span_gate = None if mode == self.DIST_MODE_ALL_MEASURED else 1.2
        sol = solve_mount_params(marks, intr, min_dist_span=span_gate)
        if not sol.ok:
            self.label_mount_status.setText(f'求解未通过：{sol.reason}')
            QMessageBox.warning(
                self, '安装参数自标定',
                f'{sol.reason}\n\n已记录的采样点保留，可补采后重试。')
            return

        # 写回标定页：与手工填写走**同一条通路**（控件 valueChanged -> 重建
        # 测距配置）。控件精度（高度 2 位、俯仰角 1 位）会截断解出的值，
        # 所以按截断后的值再显式同步一次，避免"显示的值"与"实际生效的值"不一致。
        self.spin_camera_height.setValue(round(sol.camera_height, 2))
        self.spin_pitch_deg.setValue(round(sol.pitch_deg, 1))
        h_applied = float(self.spin_camera_height.value())
        pitch_applied = float(self.spin_pitch_deg.value())
        self.global_params.camera_height = h_applied
        self.global_params.pitch_deg = pitch_applied
        self.global_params.foot_offset_m = 0.0
        self.ranger.update_config(RangingConfig.from_params(self.global_params))
        self.refresh_distance_widgets(self._last_ranging)
        # 落盘。上面两个 setValue 已经各自触发过一次落盘（来源会被记成「手工填写」），
        # 这里再用正确来源覆盖写一次 —— 文件很小，一次多余写入换来源标注准确，划算。
        self._persist_mount_params('自标定')

        h_eff = h_applied
        sens = (0.01745 * 10.0 / h_eff * sol.sigma_pitch * 100.0
                if h_eff > 0 else float('nan'))
        self.label_mount_status.setText(
            f'已解出：垂直落差 {h_applied:.2f} m、俯仰角 {pitch_applied:.1f}°'
            f'（残差 {sol.residual_px:.2f} px，用了 {sol.n_points} 个采样点）')
        # 全自动档：必须把「误差从哪来、有多大、怎么消掉」说清楚 ——
        # 用户没拿尺子，就得知道自己拿到的是什么精度的数。
        if scale_rel_sigma > 0:
            scale_line = (
                f'\n⚠️ 本轮**没有用尺子**：距离尺度来自人体尺寸先验'
                f'（框覆盖的真实长度按 {BODY_SPAN_PRIOR_M:.2f} m 估算）。\n'
                f'    测距误差约 ±{scale_rel_sigma * 100:.0f}%'
                f'（95% 分位约 ±{scale_rel_sigma * 200:.0f}%），'
                f'而且是**整体缩放** —— 全量程偏同一个百分比。\n'
                f'    这个误差来自「人有多高多宽」的个体差异，不是算法能修的；\n'
                f'    量一个已知距离重标一次即可降到 ±1% 左右。\n')
        else:
            scale_line = ''
        QMessageBox.information(
            self, '安装参数自标定',
            f'{sol.detail}\n\n'
            f'估计精度（按底边定位误差 1 px 估计）：\n'
            f'    垂直落差 ±{sol.sigma_height * 100:.1f} cm\n'
            f'    俯仰角   ±{sol.sigma_pitch:.2f}°\n'
            f'{scale_line}\n'
            f'已写入「标定」页 ② 组的安装参数：垂直落差 {h_applied:.2f} m、'
            f'俯仰角 {pitch_applied:.1f}°'
            + '，已立即生效。\n'
            + f'按这两个数，10 m 处由俯仰角误差贡献的距离误差约 {sens:.1f}%。')

    # ------------------------------------------------------------------
    # 录制回放（CHARTER「范围内的」第 6 条）
    # ------------------------------------------------------------------

    @Slot()
    def on_rec_toggle(self):
        """开始/结束录制。"""
        if self.recorder is None:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        if self.cap is None or not self.cap.isOpened():
            QMessageBox.warning(self, '录制错误', '摄像头未连接，无法录制。')
            return
        if not hasattr(self, 'current_frame') or self.current_frame is None:
            QMessageBox.warning(self, '录制错误', '还没有可用画面，请稍候再试。')
            return

        root = self._recordings_dir()
        try:
            self.recorder = Recorder(root=root, fps=float(self.global_params.fps))
            h, w = self.current_frame.shape[:2]
            session_dir = self.recorder.start(
                (h, w, 3),
                calibrated=self.global_params.calibrated,
                distance_source='filtered',   # 数据轨 distance 存规范值（去噪后）
            )
        except Exception as e:
            self.recorder = None
            QMessageBox.critical(self, '录制失败', f'无法开始录制：{e}')
            return

        self._rec_seq = 0
        self._rec_t0 = time.time()
        # ReID 旁路：与录制**同开同关**。start() 失败（模型缺失 / 盘不可写）时
        # 只是本次不采数据，不阻断录制 —— 它是旁路，不是主链路的依赖。
        self._reid_probe = ReidProbe(session_dir)
        if self._reid_probe.start():
            self.status_bar.showMessage(
                'ReID 旁路已启用（只记录外观特征，不参与追踪判定）', 5000)
        else:
            self.status_bar.showMessage(
                f'ReID 旁路未启用：{self._reid_probe.last_error}', 8000)
            self._reid_probe = None
        # 录制时曲线**实时增长**（用户要求）：从空开始，每帧追加一个点，
        # 时间轴用「距开始录制的秒数」—— 与数据轨 FrameRecord.t 同一个式子，
        # 所以录完自动挂回放时曲线与进度条严丝合缝，不需要重画。
        self._curve_clear()
        self.btn_rec_toggle.setText('停止录制')
        self.label_rec_status.setText('● 录制中')
        self.label_rec_info.setText(
            f'正在录制到：\n{session_dir}\n'
            f'未标定，测距值不可信' if not self.global_params.calibrated else
            f'正在录制到：\n{session_dir}\n已标定，测距值可用'
        )
        self.status_bar.showMessage('开始录制', 3000)

    def stop_recording(self):
        if self.recorder is None:
            return
        # 先收 ReID 旁路：它往**同一个会话目录**写，必须在 recorder 收尾前停掉，
        # 否则可能往已收尾的会话里追加残行。
        reid_stats = self._stop_reid_probe()
        try:
            meta = self.recorder.stop()
        except Exception as e:
            QMessageBox.critical(self, '录制失败', f'收尾出错：{e}')
            self.recorder = None
            self.btn_rec_toggle.setText('开始录制')
            self.label_rec_status.setText('空闲')
            return

        session_dir = self.recorder.session_dir
        self.recorder = None
        self.btn_rec_toggle.setText('开始录制')
        self.label_rec_status.setText('空闲')

        warn = ''
        if meta.dropped_frames > 0:
            # 丢帧必须明说：录像的实际内容与时长不符，使用者有权知道
            warn = f'\n⚠ 有 {meta.dropped_frames} 帧因写盘队列溢出被丢弃（帧率过高或磁盘慢）'
        if not meta.calibrated_at_record:
            warn += '\n⚠ 录制时未标定，本次数据轨的距离值全部为 None'

        reid_note = self._reid_note(reid_stats)
        self.label_rec_info.setText(
            f'已保存：\n{session_dir}\n'
            f'时长 {meta.duration_s:.1f}s，视频 {meta.frame_count} 帧，'
            f'数据轨 {meta.data_count} 条{warn}{reid_note}'
        )
        QMessageBox.information(
            self, '录制完成',
            f'时长 {meta.duration_s:.1f}s\n'
            f'视频帧数 {meta.frame_count}\n'
            f'数据轨记录 {meta.data_count}\n'
            f'丢帧 {meta.dropped_frames}{warn}{reid_note}'
        )
        # 录完自动挂到回放器上 —— 之前要手动再点「选择录制」，容易以为没存上
        # keep_curve=True：曲线在录制过程中已经实时画出来了，别在停止这一刻清掉
        if self._load_replay_session(session_dir, keep_curve=True):
            self.status_bar.showMessage(
                f'录制完成，已自动加载回放：{meta.session}', 5000)

    def _stop_reid_probe(self):
        """收尾 ReID 旁路并返回统计。**无旁路 / 出错时都返回 None**，绝不抛 —— 旁路
        出问题不许炸主链路。"""
        if self._reid_probe is None:
            return None
        try:
            stats = self._reid_probe.stop()
        except Exception as e:                     # noqa: BLE001 - 旁路不外溢异常
            print(f'[ReID 旁路] 收尾出错：{e}')
            stats = None
        self._reid_probe = None
        return stats

    @staticmethod
    def _reid_note(stats) -> str:
        """把旁路统计转成一行可读说明（信息栏与完成对话框共用）。无旁路时返回空串。"""
        if not stats:
            return ''
        written = int(stats.get('written', 0) or 0)
        if written <= 0:
            why = stats.get('last_error') or '本段没有可用的人体框'
            return f'\nReID 旁路：未记录到有效条目（{why}）'
        return (f'\nReID 旁路已记录 {written} 条外观特征'
                f'（丢弃 {stats.get("dropped", 0)}、失败 {stats.get("errors", 0)}，'
                f'摊销 {stats.get("infer_ms_amortised", 0)} ms/帧）')

    def _recordings_dir(self) -> str:
        """录制根目录固定在仓库下 recordings/（已在 .gitignore 中）。"""
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'recordings')
        os.makedirs(root, exist_ok=True)
        return root

    @Slot()
    def on_play_pick(self):
        """选择一次录制：列出现有会话（带摘要）让用户挑，不再浏览目录。

        旧版用目录选择框 —— 用户容易选到 recordings 根目录（没有
        video.avi，加载失败），或者不知道要进哪个目录。列表直接给摘要。
        """
        root = self._recordings_dir()
        sessions = Replayer.list_sessions(root)
        if not sessions:
            QMessageBox.information(self, '没有录制',
                                    f'{root} 下没有找到录制（需含 video.avi）。')
            return

        items = []
        for d in sessions:
            try:
                rp = Replayer(d)
                m = rp.meta
                items.append(f'{m.session}  ·  {m.duration_s:.0f}s · '
                             f'{m.frame_count} 帧 · 数据 {len(rp.records)} 条'
                             + ('  ⚠ 丢帧' if m.dropped_frames else ''))
            except Exception:                                  # noqa: BLE001
                items.append(os.path.basename(d))

        choice, ok = QInputDialog.getItem(
            self, '选择录制', '选中要回放的录制：', items, len(items) - 1,
            False)
        if not ok:
            return
        d = sessions[items.index(choice)]
        if self._load_replay_session(d):
            self.status_bar.showMessage(
                f'已加载录制：{self.replayer.meta.session}', 3000)

    def _load_replay_session(self, session_dir: str, keep_curve: bool = False) -> bool:
        """把一个录制会话挂到回放器上。失败弹窗说明原因并返回 False。

        失败时保留之前已加载的会话（换片失败不应该把手头的片也弄丢）。

        ``keep_curve=True`` 用于「录完自动挂回放」：曲线在录制过程中已经实时
        长出来了，没必要在停止那一刻清空再重画一遍（见 _prepare_replay_curve）。
        """
        # 回放中直接换片：先停定时器，避免旧定时器继续驱动
        if self.replay_timer is not None and self.replay_timer.isActive():
            self.replay_timer.stop()
            self.btn_play_toggle.setText('播放')
        if not self.camera_timer.isActive():
            self.camera_timer.start()
        try:
            replayer = Replayer(session_dir)
        except Exception as e:
            QMessageBox.critical(self, '加载失败', f'无法读取录制：{e}')
            return False
        if not replayer.open():
            QMessageBox.critical(self, '加载失败', 'video.avi 无法打开。')
            return False
        # 换片时关掉上一个会话的视频句柄（否则反复选片会漏文件句柄）
        if self.replayer is not None:
            self.replayer.close()
        self.replayer = replayer
        self.play_index = 0
        total = self.replayer.total_frames
        self.label_play_pos.setText(f'0/{total}')
        self.label_play_info.setText(
            f'已加载：{self.replayer.meta.session}\n'
            f'时长 {self.replayer.meta.duration_s:.1f}s · '
            f'视频 {self.replayer.meta.frame_count} 帧 · '
            f'数据轨 {len(self.replayer.records)} 条 · '
            f'丢帧 {self.replayer.meta.dropped_frames}'
        )
        # 曲线数据算一次；画多少由播放进度决定（进度 0 → 曲线为空）
        self._prepare_replay_curve(keep=keep_curve)
        self.show_replay_summary()
        return True

    @Slot()
    def on_play_toggle(self):
        """播放/暂停。回放由 QTimer 驱动，与摄像头取帧同构。"""
        if self.replayer is None:
            QMessageBox.information(self, '未加载录制', '请先选择一次录制。')
            return

        if self.replay_timer is not None and self.replay_timer.isActive():
            self.replay_timer.stop()
            self.btn_play_toggle.setText('继续播放')
            return

        if self.replayer.finished:
            self.replayer.seek(0)
            self.play_index = 0
            self._curve_follow_replay(0)   # 从头播 → 曲线也从头长

        if self.replay_timer is None:
            self.replay_timer = QTimer()
            self.replay_timer.timeout.connect(self.on_replay_tick)
        # 间隔按**会话真实帧率**（帧数/真实时长）而不是相机设置里的 fps：
        # VideoWriter 用名义 30 fps 写文件头，本机实际只写出约 18.6 fps ——
        # 按 30 播就是 1.6 倍快放（376 帧的真实会话长 20.17 s，快放只剩 12.5 s），
        # 曲线与进度条再怎么同步也是"一起快放"。回放要按录时的速度走。
        self.replay_timer.setInterval(self.replayer.frame_interval_ms)

        # 回放期间停掉摄像头取帧，避免两路画面互相覆盖
        if self.camera_timer.isActive():
            self.camera_timer.stop()
        self.replay_timer.start()
        self.btn_play_toggle.setText('暂停')

    @Slot()
    def on_play_stop(self):
        if self.replay_timer is not None and self.replay_timer.isActive():
            self.replay_timer.stop()
        self.btn_play_toggle.setText('播放')
        if self.replayer is not None:
            self.replayer.seek(0)
            self.play_index = 0
            self.label_play_pos.setText(f'0/{self.replayer.total_frames}')
            # 进度条归零 → 曲线也归零（用户要求的"曲线与进度条同步"）。
            # 进度条本身也必须归零：以前只重置了标签与 play_index，进度条停在
            # 最右端，于是"停止后进度条在末尾、曲线是空的"——仍然是不同步。
            # 注意这里是 setValue（不触发 sliderMoved），不会反过来调用 seek。
            self.slider_play_pos.setValue(0)
            self._curve_follow_replay(0)
        # 恢复实时画面
        if not self.camera_timer.isActive():
            self.camera_timer.start()

    def on_replay_tick(self):
        """回放一帧：画面走显示路径，数据走与实时相同的回调。"""
        if self.replayer is None:
            # 防御：回放器已被释放但定时器仍在跳（例如切换/关闭竞态）
            if self.replay_timer is not None and self.replay_timer.isActive():
                self.replay_timer.stop()
            return
        frame, rec = self.replayer.read()
        if frame is None:
            if self.replay_timer is not None:
                self.replay_timer.stop()
            self.btn_play_toggle.setText('播放')
            if not self.camera_timer.isActive():
                self.camera_timer.start()
            self.status_bar.showMessage('回放结束', 3000)
            return

        self.play_index = self.replayer.position

        # 把数据轨记录还原成检测字典，复用实时链路的展示与绘图逻辑。
        # **先还原状态、再画帧**：画面上的框与距离标签必须就是这一帧的数据
        # （原先先画后赋值，框和读数都比画面滞后一帧）。
        # 距离取**规范值**（canonical_distance_at_frame）：新格式录制里就是当时
        # 屏幕上的那个数，旧格式现场补做同参数去噪 —— 与曲线、摘要同源。
        # ⚠️ 必须用**帧序号**取（不是记录下标）：视频轨与数据轨不是一比一
        #    （376 帧 vs 94 条记录），旧写法用帧序号当记录下标，后 75% 的播放
        #    时间全部拿到 None —— 画面无框、无距离，正是"只有进度条在动"的来源。
        target = None
        if rec is not None and rec.has_target:
            target = {
                'x': rec.x, 'y': rec.y, 'width': rec.width,
                'height': rec.height, 'confidence': rec.confidence,
                'class_id': rec.class_id,
            }
            self.last_detection = target
            self.global_params.detection_x = rec.x
            self.global_params.detection_y = rec.y
            self.global_params.detection_width = rec.width
            self.global_params.detection_height = rec.height
            self.global_params.detection_conf = rec.confidence
            self.global_params.target_category = rec.class_name or '未知'
            self.global_params.distance = self.replayer.canonical_distance_at_frame(
                self.play_index - 1)
        else:
            self.last_detection = None
            self.global_params.distance = None

        # 回放路径没有「认人」这回事（重识别在本项目里只记录、不在回放里判定），
        # 所以身份拦截必须**显式关掉** —— 否则会把实时画面留下的红字带进回放。
        self._identity_reject_note = None
        # 标定页那份「拦截前测距结论」同理清掉：回放没有实时测距，标定页该读的是
        # 录制里的规范距离（_refresh_calib_distance 的兜底分支）。
        self._calib_ranging = None
        self._display_frame(frame)

        if not self._replay_seeking:
            # 曲线随进度揭示：与进度条同一个时间基，同一帧推进同一个点数
            self._curve_follow_replay(self.play_index - 1)
            total = self.replayer.total_frames
            self.label_play_pos.setText(f'{self.play_index}/{total}')
            if total > 0:
                self.slider_play_pos.setValue(int(self.play_index / total * 1000))

    def _display_frame(self, frame_bgr):
        """把一帧 BGR 画到界面上（实时与回放共用）。

        懒绘制（2026-09-26 用户要求）：画面控件不在当前页时只保存帧引用、
        跳过 cvtColor/copy/两次 setPixmap（SmoothTransformation 缩放是 UI 大头），
        切回时由 on_tab_change 用最近一帧补画。
        检测/测距/录制等数据链路不经过这里，后台照常运转。

        2026-09-29：新增「标定」页预览。采样点标定与建档都**必须看着画面**
        （要确认目标完整入画、人确实站在卷尺那个点上），所以这两组控件从
        监视页搬进标定页之后，新页必须自带一块画面 —— 否则等于把功能搬瘸了。

        页判定用**控件身份**，不用下标也不用中文标题：下标插页就错位；标题
        在 Designer 里改一个字就静默失效（本页实际叫「监视」，而代码里曾按
        「监控」比对 —— 一旦改成读 tabText 判断，监视页会直接不再刷新画面，
        且不报错）。
        """
        self._last_display_bgr = frame_bgr
        page = self.tabWidget.currentWidget()
        if page is not self.tab_monitor and page is not self.tab_calib:
            return
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        # 叠加重绘走哪条口径由**当前页**决定（2026-09-29 用户要求）：
        #   监视页 = 追踪口径 —— 认不出就丢框、写 Not Target；
        #   标定页 = 只识人不追踪 —— 有框就画框，谁在画面里都画。
        # 标定页之所以不能沿用追踪口径：①②③ 三步都要**看着画面确认目标完整
        # 入画**，而追踪口径会把「不是追踪目标」的人连框一起抹掉 —— 用户站到
        # 镜头前却看不到框，等于没法标定。用户原话：「标定页面的画面不能和监控
        # 页面下的 AI 处理后的画面一样，标定页面不需要做追踪，只需要识别人并
        # 显示距离就行了」。
        draw_img = self._draw_overlay(frame_rgb, track=(page is self.tab_monitor))

        if page is self.tab_monitor:
            h, w, ch = frame_rgb.shape
            qt_img = QImage(frame_rgb.data, w, h, ch * w, QImage.Format_RGB888)
            self.lbl_original.setPixmap(QPixmap.fromImage(qt_img).scaled(
                self.lbl_original.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            target_lbl = self.lbl_process
        else:
            target_lbl = self.lbl_calib_view
            self._refresh_calib_distance()

        h2, w2, ch2 = draw_img.shape
        qt_img2 = QImage(draw_img.data, w2, h2, ch2 * w2, QImage.Format_RGB888)
        target_lbl.setPixmap(QPixmap.fromImage(qt_img2).scaled(
            target_lbl.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _refresh_calib_distance(self):
        """把标定页右侧那个大号距离数字刷成当前值。

        取值优先级：① 实时链路存下的 `_calib_ranging`（拦截前的测距结论）；
        ② 回放链路没有实时测距，退回录制里的**规范距离**（与曲线/摘要同源）。
        两者都没有就是「不可测」—— 与监视页读数用 `RangingResult.display()`，
        同一套文案（存疑带「？」，不隐藏数据）。
        """
        res = self._calib_ranging
        if res is not None:
            txt = res.display()
            # 悬停说明复用监视页那一份（同源），省得「为什么不可测」在标定页查不到
            tip = self._ranging_tooltip(res)
        else:
            d = self.global_params.distance
            txt = f'{d:.2f} m' if d is not None else '不可测'
            tip = ''
        if self.lbl_calib_distance.text() != txt:
            self.lbl_calib_distance.setText(txt)
        self.lbl_calib_distance.setToolTip(tip)

    def _draw_overlay(self, frame_rgb, track=True):
        """在 RGB 帧副本上画检测框与读数，返回副本。**不改动入参**。

        ``track``：监视页传 True（追踪口径），标定页传 False（只识人口径）。
        标定页不做追踪 —— 有检测框就画，不看「是不是追踪目标」。

        三种状态（互斥，且与「出不出数」同源 —— 画面与读数不能各说各话）：

        ① 检测到的**不是**追踪目标：不画框。画上去等于向用户宣称「这就是他」，
           而距离那一侧已经按「不可测」处理了，两边必须一致（2026-09-29 用户：
           「没认出就把这个陌生人的检测框也扔掉」）。**仅追踪口径有这一态**。
        ② 有可用目标：画框 + 类别/置信度/距离。
        ③ 本帧没有目标：写「No Target」。
        """
        draw_img = frame_rgb.copy()
        if track and self._identity_reject_note:
            # 字必须是 ASCII：cv2.putText 只认 Hershey 字库，写中文会渲染成一串问号。
            # ⚠️ 这里是 **RGB** 缓冲（入参已由 BGR 转过），(255,165,0) 才是橙；
            #    写成 (0,165,255) 会变蓝。（下面 'No Target' 那行是 BGR 口径的
            #    遗留写法，实际显示为蓝 —— 本轮不动它，改它属于另一件事。）
            cv2.putText(draw_img, 'Not Target', (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 165, 0), 2)
        # 画框判据与目标过滤同源（2026-09-26：原先写死 >=0.3，置信度 0.65 的
        # 误检在阈值调到 0.7 后照样画框 —— 滑块形同虚设的直接原因之一）。
        # 回放路径的 last_detection 也走这里，行为一致：当前阈值就是显示过滤器。
        elif self.last_detection and self.last_detection.get('confidence', 0) \
                >= self.global_params.confidence_thres:
            target = self.last_detection
            x, y = target['x'], target['y']
            w_box = target.get('width', 40)
            h_box = target.get('height', 40)
            conf = target['confidence']
            # ⚠️ 这里**故意不套** display_class_name：框上的字由 cv2.putText 画，
            # 它只认 Hershey 字库，写中文会渲染成一串「?」（同本方法开头
            # 'Not Target' 那行的注释）。所以框上保留标签文件原文（默认
            # 'person'），与 Qt 渲染的图例 /「目标类别」行（都显示「人」）
            # 刻意不同 —— 想要框上也是中文，得改走 Qt 绘制，那是另一件事。
            name = self.global_params.target_category or '未知'
            dist = self.global_params.distance
            label = f'{name} {conf:.2f}'
            if dist is not None:
                label += f' {dist:.2f}m'
            top_left = (int(x - w_box / 2), int(y - h_box / 2))
            bottom_right = (int(x + w_box / 2), int(y + h_box / 2))
            cv2.rectangle(draw_img, top_left, bottom_right, (0, 255, 0), 2)
            size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(draw_img, (top_left[0], top_left[1] - size[1] - 5),
                          (top_left[0] + size[0], top_left[1]), (0, 255, 0), -1)
            cv2.putText(draw_img, label, (top_left[0], top_left[1] - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        else:
            cv2.putText(draw_img, 'No Target', (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        return draw_img

    @Slot(int)
    def on_play_seek(self, value):
        """拖动进度条定位。曲线**立刻**揭示到该位置（可当缩略图用：拖到最右
        就看到整段曲线，不用等播完）。"""
        if self.replayer is None:
            return
        total = self.replayer.total_frames
        if total <= 0:
            return
        target_idx = int(value / 1000 * (total - 1))
        self._replay_seeking = True
        try:
            self.replayer.seek(target_idx)
            self.play_index = target_idx
            self.label_play_pos.setText(f'{target_idx}/{total}')
            self._curve_follow_replay(target_idx)
        finally:
            self._replay_seeking = False

    def show_replay_summary(self):
        """回放数据的统计摘要（整段会话的统计 + 坐标轴设置）。

        曲线**不在这里画**（2026-09-26 改版）：曲线数据的准备在
        ``_prepare_replay_curve``（加载会话时算一次），画多少由**回放进度**
        决定（``_curve_follow_replay``）。理由：用户要的是「曲线与进度条同时
        加载」，而不是加载时一次画满、播放时纹丝不动 —— 旧实现就是后者，
        表现出来的现象正是「点播放只有进度条在动」。切页签重进时也不该把
        曲线重置回起点，所以这里只刷文字与轴标签。

        曲线的口径仍是**规范距离**（去噪后）按 TTC 分级分段着色，
        且只画有值的点：距离为 None 的帧不画 0 —— 0 米是"有效但错误"的读数，
        None 是"没有读数"，两者在图上必须可区分。
        """
        if self.replayer is None:
            return
        s = self.replayer.summary()
        dist_txt = '不可解算'
        if s['distance_min'] is not None:
            dist_txt = f'{s["distance_min"]:.2f} ~ {s["distance_max"]:.2f} m'
        conf_txt = ('—' if s['confidence_mean'] is None
                    else f'{s["confidence_mean"]:.3f}')
        calib_txt = '已标定' if s['calibrated_at_record'] else '未标定（距离不可信）'
        # 旧格式录制（数据轨存的是未去噪测量值）会在此注明曲线是补做去噪的 ——
        # 不注明的话，人无法从界面上判断这条曲线和当时屏幕上的是不是同一个数。
        src_txt = ('' if s.get('distance_source') == 'filtered'
                   else ' · 曲线为回放时补做去噪（旧格式录制）')
        self.label_replay_summary.setText(
            f'会话 {s["session"]} · 时长 {s["duration_s"]:.1f}s · '
            f'视频 {s["frame_count"]} 帧 · 数据轨 {s["data_count"]} 条 · '
            f'丢帧 {s["dropped_frames"]}\n'
            f'有目标 {s["target_frames"]} 帧 · 可测距 {s["ranged_frames"]} 帧 · '
            f'距离范围 {dist_txt} · 平均置信度 {conf_txt} · 录制时{calib_txt}'
            f'{src_txt}'
        )

        self.plot_replay_distance.setLabel('bottom', '时间', units='s')
        self.plot_replay_distance.setLabel('left', '距离', units='m')
        self.plot_replay_distance.showGrid(x=True, y=True)

    def _replay_ttc_levels(self):
        """对回放会话逐帧算 TTC 分级，返回与 ``canonical_distance_series()``
        的 ``ds`` 等长的分级列表。

        喂给 ``TTCEstimator`` 的就是**同一条规范距离序列**（与实时链路同一个
        类、同一套阈值），于是颜色回答的是"这段数据当时触发了哪一级告警"，
        而不是另一套离线重算出来的结论。
        """
        est = TTCEstimator()
        levels = []
        for rec, d in zip(self.replayer.records,
                          self.replayer.canonical_distances()):
            res = est.update(
                t=rec.t,
                box=(rec.x, rec.y, rec.width, rec.height),
                class_id=rec.class_id,
                has_target=rec.has_target,
                distance=d,
            )
            if d is not None:          # 只保留曲线上的点，与 ds 对齐
                levels.append(res.level)
        return levels

    # ---- 录制/回放曲线：按 TTC 分级分段着色（增量追加）----------------------
    #
    # 为什么要从「整条重画」改成「增量追加」（2026-09-26 用户反馈驱动）：
    #   ① 用户要的是**曲线与进度条同步增长**，而不是加载时一次画满、
    #      播放时纹丝不动（旧实现就是后者 —— 点播放只有进度条在动）。
    #   ② 逐帧揭示时若每次 removeItem + 新建 N 个段对象，长会话下每帧
    #      都要重建几十个 item，纯浪费 CPU；追加则是 O(1) 一笔。
    #   ③ 录制时也要画同一条曲线，两条路径共用同一套「揭示到第几个点」模型，
    #      时间基统一为**会话真实秒**（与数据轨 FrameRecord.t 同一个口径）。
    #
    # 为什么「一个分级一条 item」还不够，必须再用 NaN 断开（同日二次反馈）：
    #   pyqtgraph 的画笔是**每条 item 一个颜色**，所以「一根线换色」只能拆成
    #   多条 item —— 但拆法有两种，第一种是错的：
    #     ✗ 把同一分级的**所有**点攒进一个 item：pyqtgraph 按数组顺序连折线，
    #       同一个分级在一段会话里出现多段不相邻区间时（实测最近一次录制：
    #       灰色 4 段、预警 2 段、危险 2 段），同色两段之间会被拉出一条
    #       **横穿整幅图**的直线 —— 用户看到的就是「应该是一条线，怎么有
    #       好多条线」。
    #     ✓ 在那条 item 里、每段末尾补一个 **NaN** 收尾，并让 item 用
    #       ``connect='finite'``：栅格化时 NaN 前后不再相连，同色的多段各自
    #       独立。已实测（`probe_curve_break.py`）：`finite` + NaN → 路径断成
    #       2 条独立子路径；`all` + NaN → 仍是一条（**只加 NaN 不够**）。
    #   这样 item 数恒 ≤ 4（每个分级一条），图例天然是「每级一行」，
    #   不必手工维护；视觉上就是「一条曲线，颜色分段」。

    def _curve_item(self, level):
        """取该 TTC 分级对应的曲线对象；没有就建（图例只在建立时登记一次）。

        level 是 ``TTCLevel`` 枚举，颜色与监视页告警色同值（见
        ``_TTC_LEVEL_COLORS``），图例文案带各级阈值（``_ttc_level_legend_name``）。

        ``connect='finite'`` 是必须的：它让同一条 item 里被 NaN 隔开的多段
        各自独立成线（见本节顶部说明），少了它就只剩一条横穿线。
        """
        item = self._curve_items.get(level)
        if item is None:
            if not self._curve_legend_done:
                self.plot_replay_distance.addLegend()
                self._curve_legend_done = True
            item = self.plot_replay_distance.plot(
                [], [], pen=pg.mkPen(_TTC_LEVEL_COLORS[level], width=2),
                name=_ttc_level_legend_name(level, self._ttc.cfg),
                connect='finite')
            self._curve_items[level] = item
        return item

    def _curve_clear(self):
        """清空曲线（换会话 / 重新播放 / 停止回放）。"""
        self._curve_pts = []
        self._curve_xy = {}
        for item in self._curve_items.values():
            item.setData([], [])

    def _curve_push(self, t, d, level):
        """追加一个点。

        换级时做两件事，缺一不可：

        ① **旧分级补一个 NaN 收尾** —— 把该分级**已画过的段**封口，否则它
           与「本分级以后再出现的新段」会被连成一条横穿线（见本节顶部说明）。
        ② **新分级复制上一段末点**作起点 —— 否则换色处会断开，看着像丢帧。
        """
        prev = self._curve_pts[-1] if self._curve_pts else None
        turning = prev is not None and prev[2] != level
        self._curve_pts.append((t, d, level))
        # 懒绘制：回放页不可见时只维护状态、不碰图（setData 会触发
        # pyqtgraph 的数据拷贝与重绘准备，后台白白消耗主线程）；
        # 切回回放页时 _repaint_replay_curve 一次性补齐。
        paint = self._replay_tab_visible()
        if turning:
            pxs, pys = self._curve_xy[prev[2]]      # prev 一定 push 过
            pxs.append(t)
            pys.append(float('nan'))
            if paint:
                self._curve_item(prev[2]).setData(pxs, pys)
        xs, ys = self._curve_xy.setdefault(level, ([], []))
        if turning:
            xs.append(prev[0])
            ys.append(prev[1])
        xs.append(t)
        ys.append(d)
        if paint:
            self._curve_item(level).setData(xs, ys)


    def _curve_rebuild(self, points):
        """按给定点序列重建整条曲线（往回拖进度条时用）。"""
        self._curve_clear()
        for t, d, lv in points:
            self._curve_push(t, d, lv)

    def _curve_follow_replay(self, frame_index):
        """把曲线揭示到 ``frame_index`` 这一帧（与进度条同一个时间基）。

        常态是**前进**（只补差量）；往回拖进度条时点数变少 → 重建；
        停止回放 = 揭示到第 0 帧 = 清空 —— 于是「进度条在哪，曲线就到哪」。
        """
        if self.replayer is None or not self._replay_ts:
            return
        want = self.replayer.points_upto_frame(frame_index)
        cur = len(self._curve_pts)
        if want == cur:
            return
        pts = list(zip(self._replay_ts, self._replay_ds, self._replay_levels))
        if want < cur:
            self._curve_rebuild(pts[:want])
        else:
            for p in pts[cur:want]:
                self._curve_push(*p)

    def _prepare_replay_curve(self, keep=False):
        """加载会话后准备曲线数据（全量算一次，含逐帧 TTC 分级）。

        ``keep=True`` 用于「录完自动挂回放」：曲线在录制时已经实时长出来，
        而且用的就是同一批数据，没必要在停止那一刻清空再画一遍。
        """
        ts, ds = self.replayer.canonical_distance_series()
        levels = self._replay_ttc_levels()
        self._replay_ts, self._replay_ds, self._replay_levels = ts, ds, levels
        if keep and ts:
            self._curve_rebuild(list(zip(ts, ds, levels)))
        else:
            self._curve_clear()

    def update_param_realtime(self,param_name,value,label,fmt):
        setattr(self.global_params,param_name,value)
        label.setText(fmt % value)

     
    #界面交互
    def _replay_tab_visible(self):
        """回放页当前是否可见 —— 懒绘制开关。

        同 :meth:`_display_frame`：按**控件身份**判断。原先写死
        ``currentIndex() == 3``，本次插页插在末尾所以侥幸没坏，
        但只要以后在它前面插一页就会静默判错页。
        """
        return self.tabWidget.currentWidget() is self.tab_record

    def _repaint_replay_curve(self):
        """切回回放页时把曲线数据一次性刷到图上（懒绘制补齐）。

        后台期间 ``_curve_push`` 只维护 ``_curve_xy`` 状态、不碰图；
        这里全量 setData 一次，数据本来就是现成的。
        """
        if not self._curve_xy:
            # 没有数据也要清掉图上残留（换会话后切页的场景）
            for item in self._curve_items.values():
                item.setData([], [])
            return
        for level, (xs, ys) in self._curve_xy.items():
            self._curve_item(level).setData(xs, ys)

    @Slot(int)
    def on_tab_change(self,index):
        # 用**控件身份**判断当前页（2026-09-29）。原先用硬编码下标表
        # tab_name=['监控','深度分析','设置','录制回放']，加一页直接 IndexError；
        # 一度改成读 tabText，又踩到「表里写『监控』、标题其实是『监视』」的
        # 漂移 —— 监视页会静默不再刷新画面。控件对象两个坑都不怕。
        page = self.tabWidget.widget(index)
        print(f"当前选项卡：{self.tabWidget.tabText(index)}")
        if page is self.tab_monitor or page is self.tab_calib:
            # 懒绘制补齐：后台期间画面没画，切回来用最近一帧补上
            # （last_detection / global_params 的状态一直在更新，补画的
            #  框与读数就是最新状态，不是过期画面）
            if self._last_display_bgr is not None:
                self._display_frame(self._last_display_bgr)
            if page is self.tab_calib:
                # 建档的大字、匹配行、阻塞原因都在标定页，切过来要按最新状态重画
                self._refresh_enroll_status()
        elif page is self.tab_analysis:
            self.init_analysis_plots()
            if not self.analysis_timer.isActive():
                self.analysis_timer.start()
            return
        # 非深度分析页一律停曲线刷新（2026-09-26 修）：
        # 旧写法把 stop 放在 elif 链的最后一段，而「设置」「录制回放」都有
        # 自己的分支 —— 从深度分析切到这两页时 stop 永远走不到，每 50ms
        # 白刷 4 张不可见的图（回放也不喂分析历史，刷的还是同一批旧数据）。
        # 对照实测（measure_replay_tick.py，回放单帧预算=录时真实帧间隔 67ms）：
        #   全开（真实使用状态） 单帧中位 42.3ms · P90 95.5ms · 23% 帧超预算
        #   停掉 analysis_timer  单帧中位 37.2ms · P90 64.7ms ·  3% 帧超预算
        # 这正是"回放遇到大范围移动会卡一下"的主因之一。
        if self.analysis_timer.isActive():
            self.analysis_timer.stop()
        if page is self.tab_setting:
            self.refresh_calib_widgets()
            self.refresh_camera_widgets()
            # 档案管理列表：切回来重画（建档、删除、改名都可能发生在别的页）
            self.refresh_profiles_list()
        elif page is self.tab_record:
            # 懒绘制补齐：后台期间曲线只记数据没画图，切回来全量刷一次
            self._repaint_replay_curve()
            if self.replayer is not None:
                self.show_replay_summary()
                
    @Slot()
    def on_calibrate_clicked(self):
        """应用设置页的参数并重载模型。

        注意：这里**不做相机标定**。相机内参由「相机标定」分组的
        「求解并保存」负责，因为那是需要棋盘格的独立流程。
        本按钮只负责把界面上改过的运行参数落到 GlobalParams 并生效，
        避免"标定"一词同时指两件事（旧版本的问题）。
        """
        self.label__calibrate_status.setText("参数应用中……")
        self.QPuahButton_calibrate_status.setEnabled(False)
        QApplication.processEvents()

        try:
            self.global_params.sample_freq=self.slider_sample_freq.value()
            self.global_params.base_width=self.slider_base_width.value()
            self.global_params.hardware_accel=self.combo_hardware_accel.currentText()
            self.global_params.mode_path=self.label_model_path.text()
            self.global_params.label_path=self.label_label_path.text()
            self.global_params.plot_enable=self.checkBox.isChecked()

            self.update_timer.setInterval(int(1000/self.global_params.sample_freq))
            self.async_init_ai_model(reload=True)#重新加载模型

            # 测距配置跟着一起刷新（俯仰角可能也改过）
            self.ranger.update_config(RangingConfig.from_params(self.global_params))
            QTimer.singleShot(2000,self.finish_calibration)
        except Exception as e:
            self.label__calibrate_status.setText('参数应用失败')
            QMessageBox.critical(self,'参数应用失败',f'过程出错：{str(e)}')
            self.QPuahButton_calibrate_status.setEnabled(True)
    
    def finish_calibration(self):#不阻塞主线程
        self.QPuahButton_calibrate_status.setEnabled(True)
        QMessageBox.information(self,'参数已应用','运行参数已更新并生效')
        self.refresh_calib_widgets()   # 标定状态回到真实值，而不是被这里改写
        self.refresh_track_target_combo()  # 档案可能已变（新目标建档），重填列表

    # ------------------------------------------------------------------
    # 默认模型 / 上次选择（models/settings.json，已 gitignore）
    # ------------------------------------------------------------------

    @staticmethod
    def _model_settings_path() -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'models', 'settings.json')

    # Windows 端实测最佳的默认组合（README 横评：43~47 ms/帧）
    DEFAULT_MODEL = os.path.join('models', 'yolov8', 'yolov8n.onnx')
    DEFAULT_LABELS = os.path.join('models', 'labels', 'coco80.txt')

    def _resolve_model_paths(self):
        """决定启动时用哪套模型路径：上次的选择 > 默认最佳 > 空。

        上次的选择记录在 models/settings.json（点「应用参数」成功后写入）；
        文件已不存在时视为失效，退回默认。
        """
        base = os.path.dirname(os.path.abspath(__file__))
        default_model = os.path.normpath(
            os.path.join(base, self.DEFAULT_MODEL))
        default_labels = os.path.normpath(
            os.path.join(base, self.DEFAULT_LABELS))

        last_model, last_labels = '', ''
        try:
            with open(self._model_settings_path(), 'r',
                      encoding='utf-8') as f:
                data = json.load(f)
            last_model = data.get('model_path', '')
            last_labels = data.get('label_path', '')
        except (OSError, ValueError):
            pass
        if not os.path.isfile(last_model):
            last_model = ''
        if not os.path.isfile(last_labels):
            last_labels = ''

        model = last_model or (default_model if os.path.isfile(default_model)
                               else '')
        labels = last_labels or (default_labels if os.path.isfile(default_labels)
                                else '')
        return model, labels, bool(last_model)   # (路径, 标签, 来自上次选择)

    def _apply_default_model_paths(self):
        """启动时把模型路径填进参数与控件 —— 让「打开就能用」成为默认行为。"""
        model, labels, from_last = self._resolve_model_paths()
        if model:
            self.global_params.mode_path = model
            self.label_model_path.setText(model)
        if labels:
            self.global_params.label_path = labels
            self.label_label_path.setText(labels)
        if model:
            where = '上次选择' if from_last else '默认模型'
            self.status_bar.showMessage(
                f'使用{where}：{os.path.basename(model)}（后台加载中）', 5000)

    def _save_model_settings(self):
        """记住这次生效的模型组合，下次启动直接用（不用再选）。"""
        data = {
            'model_path': self.global_params.mode_path,
            'label_path': self.global_params.label_path,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        try:
            os.makedirs(os.path.dirname(self._model_settings_path()),
                        exist_ok=True)
            tmp = self._model_settings_path() + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._model_settings_path())
        except OSError as e:
            print(f'模型设置落盘失败（不影响本次使用）：{e}')

    @Slot()        
    def on_model_browse(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择AI模型文件", "", "模型文件 (*.onnx *.tflite *.engine);;所有文件 (*.*)")
        if file_path:
            self.label_model_path.setText(file_path)
            self.global_params.mode_path=file_path
           
    @Slot()
    def on_label_browse(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择标签文件", "", "标签文件 (*.txt);;所有文件 (*.*)")
        if file_path:
            self.label_label_path.setText(file_path)
            self.global_params.label_path=file_path
            try:
                with open(file_path,'r',encoding='utf-8') as f:
                    self.labels=[line.strip() for line in f]
                print(f'加载了{len(self.labels)}个标签')
                self.status_bar.showMessage(f'加载标签成功：{len(self.labels)}个', 3000)
            except Exception as e:
                print(f'加载标签失败：{str(e)}')
                self.labels=[]
                self.status_bar.showMessage(f'加载标签失败：{str(e)}', 5000)
                
    # ------------------------------------------------------------------
    # 指纹档案管理（设置页，2026-09-29 新增：查 / 改 / 删）
    # ------------------------------------------------------------------
    # 与「追踪目标选择」的分工：那边选「跟谁」，这边管档案本身的增删改。
    # 删除走二次确认 —— 它立刻写盘、不可撤销，且删掉的是「重新站一次才能
    # 再建回来」的东西（档案里存着嵌入向量，重建要重新站定采样）。
    def refresh_profiles_list(self):
        """把档案库重填进列表，并同步详情与按钮可用性。

        重填期间屏蔽 ``currentRowChanged``：``clear()/addItem()`` 会先产生
        「-1 行」再产生「0 行」两个瞬态选中，不屏蔽的话详情区会闪，
        而且会把用户刚选的行重置掉。
        选中项按 ``profile_id`` 还原，而不是按下标 —— 删除一条后下标会整体位移。
        """
        lst = self.list_profiles
        keep = self._selected_profile_id()
        lst.blockSignals(True)
        try:
            lst.clear()
            for p in self._person_tracker.profiles:
                lst.addItem(self._profile_row_text(p))
                item = lst.item(lst.count() - 1)
                item.setData(Qt.UserRole, p.profile_id)
                item.setToolTip(self._person_tracker.profile_tooltip(p))
            if keep:
                row = next((i for i in range(lst.count())
                            if lst.item(i).data(Qt.UserRole) == keep), -1)
                if row >= 0:
                    lst.setCurrentRow(row)
        finally:
            lst.blockSignals(False)

        if lst.count() == 0:
            self.label_profile_detail.setText(
                '档案库为空。到「标定」页第三步「指纹建档」让被登记者站一次。')
            self.btn_profile_rename.setEnabled(False)
            self.btn_profile_delete.setEnabled(False)
        else:
            if lst.currentRow() < 0:
                lst.setCurrentRow(0)
            self.on_profile_row_changed(lst.currentRow())
        # 「追踪目标选择」下拉与这份列表同源，一起刷新 —— 否则删掉当前追踪
        # 目标后，下拉里还留着一个已经不存在的选项。
        self.refresh_track_target_combo()

    def _profile_row_text(self, p) -> str:
        """列表里的一行。★ 标出追踪目标，嵌入有无也写出来 ——
        「这条档案能不能认人」取决于有没有嵌入，不该藏在详情里。"""
        mark = '★' if p.is_track_target else '　'
        emb = '嵌入✓' if p.embedding else '无嵌入'
        return (f'{mark} {p.name}　{_span_pair_text(p.height_m, p.width_m)}'
                f'　{emb}')

    def _selected_profile_id(self) -> str:
        lst = self.list_profiles
        row = lst.currentRow()
        if row < 0 or row >= lst.count():
            return ''
        return str(lst.item(row).data(Qt.UserRole) or '')

    def _find_profile(self, profile_id):
        for p in self._person_tracker.profiles:
            if p.profile_id == profile_id:
                return p
        return None

    @Slot(int)
    def on_profile_row_changed(self, row: int):
        """选中一条 -> 在下方显示它的来历（凭什么信这条档案）。"""
        p = self._find_profile(self._selected_profile_id())
        has = p is not None
        self.btn_profile_rename.setEnabled(has)
        self.btn_profile_delete.setEnabled(has)
        if not has:
            self.label_profile_detail.setText('（未选中档案）')
            return
        emb = (f'{len(p.embedding)} 维' if p.embedding else '无 —— 匹配会退回直方图')
        origin = ('主动建档' if p.is_enrolled else '自动（v1 老档案，已不再自动建档）')
        lines = [
            f'档案 ID：{p.profile_id}',
            f'来源：{origin}　建档于 {p.enrolled_at or "—"}　最近更新 {p.updated_at or "—"}',
            f'样本：{p.n_updates} 个稳定窗口（每窗口 ≥12 帧、框跨度 CV ≤5%）',
            f'外观嵌入：{emb}　模型 {p.emb_model or "—"}',
            f'追踪目标：{"是" if p.is_track_target else "否"}',
        ]
        if p.height_m < self._person_tracker.enroll_height_m[0] or \
                p.height_m > self._person_tracker.enroll_height_m[1]:
            lo, hi = self._person_tracker.enroll_height_m
            lines.append(f'⚠️ 框跨度（纵）{p.height_m:.2f} m 不在 {lo:.2f}–{hi:.2f} m 内'
                         f'（本档案建于加这道闸之前）—— 建议删掉重新建档')
        if p.source:
            lines.append(f'备注：{p.source}')
        self.label_profile_detail.setText('\n'.join(lines))

    @Slot()
    def on_profile_rename_clicked(self):
        p = self._find_profile(self._selected_profile_id())
        if p is None:
            return
        new_name, ok = QInputDialog.getText(
            self, '重命名指纹',
            f'给这条指纹起个名字（当前：{p.name}）。\n留空 = 恢复显示档案 ID。',
            text=p.display_name)
        if not ok:
            return
        if not self._person_tracker.rename_profile(p.profile_id, new_name):
            QMessageBox.warning(self, '重命名失败', f'档案 {p.profile_id} 不在库里。')
            return
        self.status_bar.showMessage(f'已改名：{p.name}', 4000)
        self.refresh_profiles_list()

    @Slot()
    def on_profile_delete_clicked(self):
        p = self._find_profile(self._selected_profile_id())
        if p is None:
            return
        extra = ''
        if p.is_track_target:
            extra = ('\n\n⚠️ 它是当前的追踪目标 —— 删除会同时取消「追踪目标」指定，'
                     '近场框跨度法（横）将回退默认框宽度 0.46 m。')
        ans = QMessageBox.question(
            self, '删除这条指纹档案？',
            f'将删除：{p.name}\n'
            f'{_span_pair_text(p.height_m, p.width_m)}　'
            f'档案 ID：{p.profile_id}{extra}\n\n'
            f'删除会**立刻写盘、不可撤销** —— 之后要重新站到镜头前建档才能恢复。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        name = p.name
        if not self._person_tracker.delete_profile(p.profile_id):
            QMessageBox.warning(self, '删除失败', f'档案 {p.profile_id} 不在库里。')
            return
        self.status_bar.showMessage(f'已删除档案：{name}', 5000)
        self.refresh_profiles_list()

    # ------------------------------------------------------------------
    # 追踪目标选择（CHARTER v1.4「建档 + 追踪目标选择」）
    # ------------------------------------------------------------------
    def target_category_text(self) -> str:
        """监视页「目标类别」该显示什么（2026-09-29 用户要求）。

        用户原话：「没有追踪目标时显示类别，有追踪目标时显示身份，这样也可以
        判断追踪是否生效」—— 所以这一行有目标时就答**是谁**，没有目标时才
        退回类别名（CHARTER v1.4 全链路唯一类别是「行人」）。

        为什么要把「追踪中 / 本帧未认出 / 画面无人」三种状态都摆出来：
        CHARTER「匹配分级」要求高置信锁定、中置信标「存疑」、低置信报丢失。
        这里只给最粗的一档「是不是他」，够用户判断**追踪有没有生效**；
        细分的分数与门槛在标定页 ③ 组的匹配行（``match_line()``）里。

        匹配状态取自 ``_person_tracker.active``，是**上一帧**的结论（匹配在
        本帧 observe() 里才更新，而本标签在测距之前就写了）。差一帧
        （30 FPS 下 33 ms）不影响人眼判断，也避免了为一句话去重排整条链路。
        """
        tgt = self._person_tracker.track_target()
        if tgt is None:
            # 类别名走 display_class_name：内部规范名（'person'）不进界面，
            # 与距离曲线图例同一口径（2026-09-29 用户反馈「怎么是 person」）。
            return display_class_name(self.global_params.target_category) or '未知'
        if self.global_params.detection_height <= 0:
            return f'{tgt.name}（画面无人）'
        active = self._person_tracker.active
        if active is not None and active.profile_id == tgt.profile_id:
            return f'{tgt.name}（追踪中）'
        return f'{tgt.name}（本帧未认出）'

    def refresh_target_category_label(self):
        """把上面那句刷进监视页。UI 刷新点统一收在这里，免得文案两处漂移。

        **变了才 setText**：本函数每帧都会被调到（有过目标的分支与没过目标的分支
        各一次），而无变化时的 setText 会白白触发一次 QLabel 重绘。
        """
        txt = self.target_category_text()
        if txt != self.label_target_category.text():
            self.label_target_category.setText(txt)

    def _set_match_line(self, text):
        """把匹配行写进「标定」页 ③ 组。**变了才 setText**（理由同上）。

        这行原本只在「检测到人」的分支里刷新，没检测到人时**停在上一次的
        数值上**。2026-09-29 用户指着空画面读「整个画面就算没人也有 0.44」——
        那个 0.44 是上一帧的残留，不是当场算出来的。残留值比不显示更坏：
        它会让人据此判断「阈值是不是太松」，而那个判断本身建立在假数据上。
        """
        if text != self.label_enroll_match.text():
            self.label_enroll_match.setText(text)

    def _identity_reject_reason(self):
        """本帧画面里的人**不是**追踪目标 -> 返回可直接显示的原因；否则 None。

        CHARTER「范围内的」第 4 条要求「只对被追踪的这一个出数」（原文：「匹配
        分级：高置信锁定并测距 / 中置信继续跟随但标『存疑』且 TTC 不出数 /
        低置信报『目标丢失』；重识别缓冲仅对**被追踪的这一个个体**生效」）。
        ``PersonFeatureTracker.ranging_width_m()`` 的 ⚠️ 也把这条边界写明了：
        「当前帧里的目标是不是追踪目标本人、该不该出数，由上层负责，不在这里
        拦」—— 本函数就是那个上层。

        拦下去的代价（先摆明，免得以为是白拦）：同一个人跨会话本来就只有约
        94% 的帧过门槛（session-20260929-131735 实测 234/249 = 94.0%，当天
        同一段连续命中 207 帧），被拦的帧距离会掉到「不可测」。这是用户明确
        要求的行为 —— 宁可不出数，也不拿别人的框出数。真要放宽，唯一正确的
        做法是**用真人数据标定门槛**，不是在这里开口子。

        什么时候**不**拦（每一条都有具体理由，少一条就会误伤）：
        - 没指定追踪目标 —— 不存在「是不是他」这回事，行为与改造前完全一致；
        - 正在建档会话里 —— 刚开档的人当然还匹配不上任何档案，拦掉就没法建档；
        - 正在记采样点标定 —— 自标定观测的是**框底边像素**，与画面里是谁无关
          （用户会把目标摆到卷尺已知距离处，那个人不一定已建档）；
        - 本帧**没算过**认人 —— 「没算」（不是人 / 相机未标定 / 框无效）不等于
          「算出来不是他」，拦下去会把未标定或空画面的整屏都黑掉；
        - 走的是**直方图路线**（档案没有可比嵌入 / 嵌入模型缺失）—— 那条路是
          「模型缺失时行为仍可解释」的兜底，实测命中率 **0%**（session-20260929-131735
          250 帧全未过 0.55 门槛，中位 0.283），拿它当「不是他」的依据等于把所有
          画面一律拦掉。判据只认 ``source == 'embedding'``；
        - 库里**没有一条可比档案**（例如换过嵌入模型的老档案）—— 认人这条路
          根本没跑通，不能说「不是他」，否则老档案一律全黑。
        """
        t = self._person_tracker
        tgt = t.track_target()
        if tgt is None or t.enrolling or self._marking:
            return None
        fi = t.frame_identity()
        if not fi.get('computed') or int(fi.get('comparable', 0) or 0) <= 0:
            return None
        if fi.get('source') != 'embedding':
            return None
        if fi.get('matched') is tgt:
            return None

        matched = fi.get('matched')
        score, thr = fi.get('score'), fi.get('threshold')
        if matched is not None:
            head = f'本帧匹配到的是「{matched.name}」，不是追踪目标「{tgt.name}」'
        elif score is None or thr is None:
            head = f'本帧这个人和追踪目标「{tgt.name}」对不上'
        else:
            head = (f'本帧这个人和追踪目标「{tgt.name}」对不上'
                    f'（相似度 {score:.3f} < 门槛 {thr:.3f}）')
        return f'{head} —— 已丢弃这个检测框，距离按不可测'

    def _sync_ranging_width(self):
        """把「框跨度法（横）该用谁的框宽度」同步给测距器。

        档案里那个数叫 ``width_m``，但它是**检测框覆盖的真实宽度**（含手臂与
        衣着），不是肩峰宽 —— 界面一律显示「框跨度·横」，见 ``_span_pair_text``。

        调用时机：① 每帧检测回调的**最前面**（不看本帧画面，见下）；
        ② 用户切换/取消追踪目标时（不必等下一帧，标定页也要立刻跟）。

        规则只有一条：**认「指定的追踪目标」**（2026-09-30 用户要求：
        「有追踪目标的时候用目标的肩宽，没有的时候就不用动」）：
          · 指定了追踪目标        -> 该目标档案里量出的框宽度（建档的意义就在这）
          · 未指定 / 目标还没量到 -> 全局默认 0.46 m，**不借用**别人的
        见 ``PersonFeatureTracker.ranging_width_m()``。

        为什么每帧都算、且不看本帧画面：目标走出画面时若不刷新，
        ``ranger.config`` 会**停在上一个目标的值上** —— 此后取消追踪目标、
        或到标定页看距离，用的还是那个人的肩宽，而且不报错。

        为什么**不写回** ``global_params.person_width_m``：那是「用户默认值」
        （``RangingConfig.from_params()`` 从它取值），一旦被写成某个档案的
        肩宽就再也回不去 —— 换目标时会拿**上一个人的**肩宽当默认值，正是
        要避免的那类静默串人。两处职责分开：

          · ``self.ranger.config.person_width_m``  = 本帧实际生效值（每帧刷新）
          · ``self.global_params.person_width_m``  = 用户默认值（只由设置页写）
        """
        self.ranger.config.person_width_m = self._person_tracker.ranging_width_m(
            self.global_params.person_width_m)

    def refresh_track_target_combo(self):
        """用指纹档案列表重填「追踪目标选择」下拉。

        列表内容 = ``models/person_profile.json`` 里的档案（**单选**）。
        重填期间屏蔽信号：``clear()/addItems()`` 会触发 ``currentIndexChanged``，
        产生「索引 0 的瞬态选中」——那会把用户的追踪目标悄悄改成第一条档案。
        当前选中项从档案里的 ``is_track_target`` 反读（文件才是唯一真相），
        并在末尾把 ``global_params.track_target_id`` 同步成它。
        """
        # 重填之前先同步一次肩宽：本函数会因为「档案被删 / 从文件反读到别的
        # 目标」而改变「追谁」，而它下面有早退分支（无档案时 return），
        # 放在开头才能覆盖所有路径。见 _sync_ranging_width。
        self._sync_ranging_width()
        combo = self.combo_track_target
        combo.blockSignals(True)
        try:
            combo.clear()
            profiles = list(self._person_tracker.profiles)
            if not profiles:
                combo.addItem('（尚无指纹档案）')
                self.global_params.track_target_id = ''
                self.btn_rename_track_target.setEnabled(False)
                # 档案删光了 -> 已经没有追踪目标，距离曲线的图例要退回类别名
                # （留着刚才那个人名就成了死名字）。这条早退分支原先直接 return，
                # 会漏掉末尾那次刷新，所以这里单独补一次。
                self._dist_legend_refresh()
                return
            self.btn_rename_track_target.setEnabled(True)
            target = self._person_tracker.track_target()
            for p in profiles:
                combo.addItem(self._person_tracker.profile_label(p))
                combo.setItemData(combo.count() - 1, p.profile_id, Qt.UserRole)
                combo.setItemData(combo.count() - 1,
                                  self._person_tracker.profile_tooltip(p),
                                  Qt.ToolTipRole)
            if target is not None:
                idx = next((i for i in range(combo.count())
                            if combo.itemData(i, Qt.UserRole) == target.profile_id),
                           -1)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                # 档案存在但都还没被指定 -> 停下并明说，不替用户默认选一个
                combo.insertItem(0, '（未指定追踪目标）')
                combo.setItemData(0, '', Qt.UserRole)
                combo.setCurrentIndex(0)
            self.global_params.track_target_id = (
                combo.itemData(combo.currentIndex(), Qt.UserRole) or '')
        finally:
            combo.blockSignals(False)
        # 下拉重填后「追谁」可能变了（档案被删、或用户改了指定），监视页那行
        # 跟着走 —— 它显示的可能是身份而不是类别名。距离曲线的图例同理：
        # 「有读数」那条线的名字现在就是追踪目标的名字（_dist_line_label），
        # 换人 / 改名 / 取消都要立刻反映，不能等下一次 analysis_timer。
        self.refresh_target_category_label()
        self._dist_legend_refresh()

    def on_track_target_changed(self, index):
        """用户在下拉里换了追踪目标：写进档案（单选）并落盘。

        这里是「追踪目标选择」的**唯一写入点** —— 落盘的是档案的
        ``is_track_target``，``global_params.track_target_id`` 只是它在
        内存里的镜像（重启后由 ``refresh_track_target_combo`` 从文件读回）。
        """
        pid = self.combo_track_target.itemData(index, Qt.UserRole) or ''
        if not pid:
            self._person_tracker.set_track_target('')
            self.global_params.track_target_id = ''
            self._sync_ranging_width()      # 立刻回默认肩宽，不等下一帧
            self.refresh_target_category_label()
            self._dist_legend_refresh()     # 取消指定 -> 图例退回类别名「人」
            self.status_bar.showMessage(
                '已取消追踪目标：不再做身份拦截，近场框跨度法（横）改用默认框宽度 0.46 m',
                6000)
            return
        hit = self._person_tracker.set_track_target(pid)
        if hit is None:
            self.status_bar.showMessage(
                f'指定追踪目标失败：档案 {pid} 不在库里', 6000)
            self.refresh_track_target_combo()
            return
        self.global_params.track_target_id = pid
        self._sync_ranging_width()          # 换目标立刻换肩宽，不等下一帧（防串人）
        # 立刻反映到监视页 —— 不让用户以为「选了没生效、得等下一帧」
        self.refresh_target_category_label()
        self._dist_legend_refresh()     # 距离曲线图例：那条线现在叫他的名字
        self.status_bar.showMessage(
            f'追踪目标已指定：{hit.name}（'
            f'{_span_pair_text(hit.height_m, hit.width_m)}）'
            f'—— 近场框跨度法（横）改用该框跨度', 6000)

    def on_rename_track_target_clicked(self):
        """改指纹的显示名（用户可改）。名字写进档案的 ``display_name`` 并落盘。"""
        pid = self.combo_track_target.currentData(Qt.UserRole) or ''
        if not pid:
            QMessageBox.information(self, '重命名指纹', '请先选中一条指纹档案。')
            return
        old = ''
        for p in self._person_tracker.profiles:
            if p.profile_id == pid:
                old = p.name
                break
        new_name, ok = QInputDialog.getText(
            self, '重命名指纹', f'给这条指纹起个名字（当前：{old}）：', text=old)
        if not ok:
            return
        if not self._person_tracker.rename_profile(pid, new_name):
            QMessageBox.warning(self, '重命名失败', f'档案 {pid} 不在库里。')
            return
        self.refresh_track_target_combo()
        self.status_bar.showMessage(
            f'指纹已重命名：{old} → {self.combo_track_target.currentText()}', 5000)

    # ------------------------------------------------------------------
    # 建档（CHARTER v1.4「范围内的」建档条：独立第三步，收在标定页）
    #
    # 为什么必须有这个入口：``PersonFeatureTracker.observe()`` 的被动路径
    # **只认人、不采样、不落盘** —— 也就是说，没有这条链路就永远不会有档案，
    # 「追踪目标选择」下拉恒空、匹配永远对着空库跑。建档是人主动触发的一步。
    # ------------------------------------------------------------------

    @Slot()
    def on_enroll_toggle_clicked(self):
        """开始 / 结束建档会话。

        只在这里决定开不开：建档是**明确动作**，不会自己发生
        （2026-09-27 把「自动建档」从被动路径上撤掉，见 person_model 类 docstring）。
        """
        t = self._person_tracker
        if t.enrolling:
            t.end_enrollment()
            self._refresh_enroll_status()
            self.status_bar.showMessage(
                f'建档已结束 —— 档案库共 {len(t.profiles)} 条', 6000)
            return

        # 先把「为什么可能采不到」讲清楚，而不是让用户站那儿空等。
        manual = float(self.spin_enroll_distance.value())
        if manual <= 0 and not self.ranger.intrinsics.is_valid():
            QMessageBox.information(
                self, '还不能建档',
                '采样点距离留 0 时，框跨度要靠测距值反解，而当前内参不可用。\n\n'
                '两条路选一条：\n'
                '  1. 先在本页上方「① 棋盘标定」与「② 采样点标定」做完；\n'
                '  2. 或在上面「采样点距离」里填一个卷尺量到的距离（米），'
                '用这个已知距离反解 —— 这样不需要标定。')
            return

        t.begin_enrollment()
        self._enroll_ui_tick = 0
        self._enroll_commits_seen = int(t.enroll_progress().get('commits', 0))
        self._enroll_failures_seen = int(
            t.enroll_progress().get('failures', 0))
        self._enroll_last_error = ''
        self._refresh_enroll_status()
        self.status_bar.showMessage(
            '建档已开始：让被登记者完整入画、站定约 3 秒（可连续给多人建档）', 8000)

    def _refresh_enroll_status(self, extra: str = ''):
        """把建档状态刷到标定页：按钮文字 + **大字** + 明细行。

        「大字」是 CHARTER 要求的界面提醒之一（另一条是提示音，见
        ``_poll_enroll_commits``）。``extra`` 非空时用它覆盖大字 ——
        用于「已建档：xxx」「建档失败：xxx」这类一次性结论，否则显示实时进度。
        """
        t = self._person_tracker
        self.btn_enroll_toggle.setText('结束建档' if t.enrolling else '开始建档')
        if extra:
            self._enroll_big_hold_until = time.monotonic() + _ENROLL_BIG_HOLD_S
            big = extra
        elif t.enrolling and time.monotonic() < self._enroll_big_hold_until:
            big = None              # 结论还在保护期内：只刷按钮与明细行
        elif t.enrolling:
            pr = t.enroll_progress()
            if pr['samples'] > 0:
                # 把**实时反解值**摆在最显眼处：本次那个反解成 1.22 m 的档案
                # 之所以能悄悄存进去，就是因为建档全程看不到这个数。
                head = (f'正在建档 {pr["samples"]}/{pr["required"]} 帧　'
                        f'反解框跨度（纵）{pr["height_m"]:.2f} m')
            else:
                head = '正在建档：等待目标入画'
            big = head + (f'（画面里是 {pr["active_name"]}）'
                          if pr['active_name'] else '')
        else:
            n = len(t.profiles)
            big = f'未开始　（档案库 {n} 条）' if n else '未开始　（档案库为空）'
        if big is not None:
            self.label_enroll_status.setText(big)
        self.label_enroll_match.setText(self._enroll_detail_line(t))

    def _enroll_detail_line(self, t) -> str:
        """大字下面那行：匹配结果 + 建档实时反解值 + 阻塞原因。

        为什么合成一行：这几个数只有放在一起才能回答「为什么还没成」——
        分数够却没提交 = 几何不对；反解值越界 = 直接看到是哪个数不合法；
        分数不够 = 认人不行。原先的失败路径全是裸 return，界面上什么都不说。
        """
        parts = [t.match_line()]
        pr = t.enroll_progress()
        if pr['enrolling']:
            lo, hi = pr['enroll_height_range']
            wlo, whi = pr['enroll_width_range']
            if pr['samples'] > 0:
                parts.append(
                    f'反解：框跨度 纵 {pr["height_m"]:.2f} m（要求 {lo:.2f}–{hi:.2f}）／'
                    f'横 {pr["width_m"]:.2f} m（要求 {wlo:.2f}–{whi:.2f}）'
                    f'　采样 {pr["samples"]}/{pr["required"]} 帧')
            if pr['block_text']:
                parts.append(f'⚠️ {pr["block_text"]}')
        return '\n'.join(parts)

    def _poll_enroll_commits(self):
        """建档结论播报：成功 -> 响一声 + 大字确认；失败 -> 响两声 + 说明原因。

        **不改变任何追踪/测距行为**，只把结论说清楚。
        提示音用 ``QApplication.beep()``：零新依赖、跨平台（CHARTER 建档条要求）。

        两条通道各用各的序号去重（commits / failures），互不影响 ——
        同一次会话里成功与失败可能交替发生。
        """
        t = self._person_tracker
        pr = t.enroll_progress()
        n = int(pr.get('commits', 0))
        if n > self._enroll_commits_seen:
            self._enroll_commits_seen = n
            QApplication.beep()
            p = t.active
            if p is not None:
                self._refresh_enroll_status(
                    f'已建档 · {p.name}　'
                    f'{_span_pair_text(p.height_m, p.width_m)}\n'
                    f'{_span_note_text()}')
            else:
                self._refresh_enroll_status(f'已建档（第 {n} 条）')
            return
        # 失败**必须说出来**：原先的复核不通过是裸 return，用户只会看到
        # 「怎么一直不成功」而拿不到原因（2026-09-29 用户实际遇到的就是这个）。
        f = pr.get('last_failure') or {}
        seq = int(f.get('seq', 0))
        if seq > self._enroll_failures_seen:
            self._enroll_failures_seen = seq
            QApplication.beep()
            QApplication.beep()
            self._refresh_enroll_status(
                f'建档失败（第 {seq} 次）：{f.get("text", "")}\n'
                f'这次**没有**写进档案 —— 按上面那句话改，然后重新站定')

    def _embed_for_enroll(self, frame_bgr, box):
        """为建档提取一帧 OSNet 嵌入。**任何失败都返回 None，绝不中断建档**。

        嵌入只是「认人」的增强：拿不到时几何特征照样建档，匹配自动退回
        HSV 直方图路子。所以这里不抛异常、不弹窗，只把原因记进
        ``_enroll_last_error`` 供排查。
        """
        if frame_bgr is None or not isinstance(box, dict):
            return None
        if self._enroll_embedder is None:
            # 2 线程：OSNet 单张约 9 ms，够用且只占 2 个逻辑核。
            # 旧注释写「检测占 4、再往上加会互相抢核（本机实测）」—— 2026-09-29
            # 五组对照实测不成立：检测 8 线程 + OSNet 2 线程**满速并发**时，
            # 检测单帧只慢 ±3%（噪声量级，且真实旁路是每 4 帧一次、远低于满速）。
            self._enroll_embedder = OsnetEmbedder(threads=2)
        if not self._enroll_embedder.available():
            self._enroll_last_error = f'嵌入模型缺失：{REID_MODEL_PATH}'
            return None
        try:
            # ⚠️ 项目帧是 BGR（OpenCV 惯例），OSNet 的训练/评测口径是 RGB。
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        except cv2.error as exc:
            self._enroll_last_error = f'BGR→RGB 失败：{exc}'
            return None
        emb = self._enroll_embedder.embed(rgb, box)
        if emb is None:
            self._enroll_last_error = (self._enroll_embedder.load_error
                                       or '嵌入提取失败')
        return emb

    # 「指定类别」下拉及其槽函数（on_specific_class_changed /
    # update_specific_class_combo）已随类别收窄删除（CHARTER v1.4）。
    # 「目标选择规则」下拉也被本节取代 —— 规则只剩「最高置信度」一条，
    # 检测器侧 select_target 恒取最高置信度。

            
    def on_detection_ready(self,target):#检测结果回调
        # 检测心跳：无论有没有目标都打点。predict 末尾是无条件 emit，
        # 所以「长时间没打点」= 链路断了，不是「画面里没人」。
        self._last_detection_ts = time.monotonic()
        # 一帧已出结果，释放一个在途名额（背压的另一半）
        if self._inflight_frames > 0:
            self._inflight_frames -= 1

        # 本帧的「不是追踪目标」说明先清空，由下面的身份判定重新写。
        # 不清就会停在上一次的结论上：画面里的框已经没了，红字却还写着
        # 「非追踪目标」，或者反过来 —— 残留结论比不显示更容易骗人。
        self._identity_reject_note = None

        # 框跨度法（横）用谁的肩宽：每帧先定一次（不看本帧画面，理由见 _sync_ranging_width）
        self._sync_ranging_width()

        if target and target['confidence']>=self.global_params.confidence_thres:# 增加置信度过滤，低于阈值视为无目标
            self.last_detection = target   # 过滤后的目标才进画面叠加（2026-09-26：
                                            # 之前无条件记录，低于阈值的椅子误检照样画框，
                                            # 用户调阈值「看起来没用」的直接原因之一）
            self.global_params.detection_x = target['x']
            self.global_params.detection_y = target['y']
            self.global_params.detection_width = target.get('width', 0)
            self.global_params.detection_height = target.get('height', 0)
            self.global_params.detection_conf = target['confidence']
            self.global_params.detection_class = target['class_id']

             # 类别名显示
            if self.detector and hasattr(self.detector, 'labels') and self.detector.labels:
                if target['class_id'] < len(self.detector.labels):
                    self.global_params.target_category = self.detector.labels[target['class_id']]
                else:
                    self.global_params.target_category = '未知'
            else:
                self.global_params.target_category = '未知'
            self.lcd_credibility.display(self.global_params.detection_conf)
            # 显示值可能是身份而不是类别名（指定了追踪目标时），统一走这条路
            self.refresh_target_category_label()
        else:
            self.last_detection = None    # 与上方配对：低于阈值 = 无目标，别留旧框
            self.global_params.detection_x = 320  # 重置为画面中心
            self.global_params.detection_y = 240
            self.global_params.detection_width = 0
            self.global_params.detection_height = 0
            self.global_params.detection_conf = 0.0
            self.global_params.detection_class = -1
            self.global_params.target_category = '未知'
            self.global_params.base_width=0.0
            self.lcd_credibility.display(0)
            # 无目标时这一行原本**不刷新**（停在上一次的值）。指定了追踪目标后
            # 必须刷 —— 否则人走出画面，标签还写着「张三（追踪中）」，等于骗人。
            self.refresh_target_category_label()
        
        # 几何测距：**常开**。测距是门槛判据「UI 实时显示测距值」的核心输出，
        # 不应依赖「是否启用深度分析」或「是否在录制」。
        #
        # 这里走 measure_from_box 而不是 distance_from_box：前者在出数之前先过
        # 可见性体检与反解判据，目标只露出一部分（贴脸、被挡到腰/膝）时明确返回
        # 「不可测 + 原因」。检测框是**可见部分**的包围盒，直接拿框高套公式
        # 会给出看着正常、却差几倍的错值（实测"贴脸"那格虚大 1248%）。
        res = None
        if self.global_params.detection_height > 0:
            res = self.ranger.measure_from_box(
                target if isinstance(target, dict) else {},
                self.global_params.target_category,
            )
        dist = res.distance if res is not None else None
        now_mono = time.monotonic()

        # ---- 距离去噪：紧跟测距，输出即"规范距离"（2026-09-26）---------------
        # 中值3 + One Euro 串联（core/ranging_filter.py，参数经 104005 会话重放
        # 扫参选定）。**位置很关键**：放在测距之后、其余一切之前，于是整条链路
        # 自始至终只有一个距离值 —— 速度门控、人特征档案、监视页读数、TTC、
        # 深度分析曲线、录制轨存的全都是它。
        #
        # 为什么不放在门控之后（原先的位置）：门控会把单帧尖刺判成"跳变错值"，
        # 被拦的帧 dist=None → 滤波器复位 → 平滑历史被一个假值清空。先滤波则
        # 中值窗先吃掉孤立尖刺，门控只在**持续**的跳变上触发（真正该拦的情形），
        # 复位也随之只发生在目标真的换人时。
        #
        # 原始值只留一份给录制轨做诊断（distance_raw），实时逻辑一律不读。
        raw_dist = dist
        if dist is not None:
            dist = self._dist_filter.update(now_mono, dist)
            if res is not None and res.distance is not None:
                res.distance = dist   # 显示与判定同源：读数/悬停/原因行一起用规范值
        else:
            self._dist_filter.reset()

        # ---- 速度门控 + 人特征档案（2026-09-25 P1+）------------------------
        # 门控在人身上：人不可能瞬移，1.5→10 m 的跳变只可能是检测跳变/抓错框，
        # 拦下并给出原因（拦的是错值，不是拦人）。非 person 目标（车等）相对
        # 速度可以更高，不套人的极限。
        # 归一化后再比（标签文件可能是中文 coco_labels_cn.txt，「人」≠'person'，
        # 不归一化会让速度门控与人特征档案整体静默失效 —— 2026-09-25 22:14 录制实证）
        is_person = (canonical_class_name(self.global_params.target_category)
                     == 'person')
        if dist is not None and is_person:
            verdict = self._speed_gate.check(dist, now_mono)
            if not verdict.ok:
                res = RangingResult(reason=verdict.reason)
                dist = None
                # 门控判"这不是同一个目标"→ 滤波器里那段历史同样不可信，一起复位
                # （否则被否定的读数仍在平滑状态里，会拖歪后续帧）。
                self._dist_filter.reset()
            elif verdict.reason:
                # 重新锚定（丢失超时 / 连续一致的新轨迹）：读数保留，说明进状态栏
                self.status_bar.showMessage(verdict.reason, 4000)
        else:
            self._speed_gate.miss(now_mono)

        # 人特征档案：**只认人，不建档**（2026-09-27 起）。每帧仍算一次外观
        # 做匹配（回答「本帧画面里的人是不是追踪目标」）；但**采样与落盘只在
        # 主动建档会话中进行**（begin_enrollment()，标定页 ③）。
        # 关闭被动自动建档的原因见 core/person_model.py 类 docstring 的 ⚠️ 段。
        if is_person and isinstance(target, dict) \
                and self.global_params.detection_height > 0 \
                and self.ranger.intrinsics.is_valid():
            frame_bgr = getattr(self, 'current_frame', None)
            vis = compute_box_visibility(
                target, self.ranger.intrinsics.image_size)
            whole = bool(vis.checked and not (
                vis.touches_top or vis.touches_bottom
                or vis.touches_left or vis.touches_right))

            # 采样点距离：手填 > 0 时**优先用手填值**（CHARTER 建档条：
            # 「采样点距离由用户手填」—— 有了它，没标定也能建档）；
            # 为 0 则用接触点法解出的值，并要求这次解算可信。
            # 「可信」的判据与测距同源，不另写一套，免得两处判据漂移。
            manual_d = float(self.spin_enroll_distance.value())
            if manual_d > 0:
                distance_used, capture_ok = manual_d, whole
            else:
                distance_used = dist
                capture_ok = bool(
                    whole and dist is not None and res is not None
                    and res.trusted
                    and res.method in ('接触点法', '两法一致'))

            # 不合格时把**具体原因**算出来一起传下去：建档会话里界面会显示它。
            # 原先这些判据在 person_model 里都是裸 return，用户在镜头前只能空等，
            # 分不清是贴边、太远、还是距离不可信 —— 2026-09-29 实测的反馈缺陷。
            bits = []
            if not whole:
                clip = [n for n, hit in (('头顶', vis.touches_top),
                                         ('脚', vis.touches_bottom),
                                         ('左侧', vis.touches_left),
                                         ('右侧', vis.touches_right)) if hit]
                bits.append(f'目标{"、".join(clip)}贴到画面边缘，请后退一些'
                            if clip else '目标未完整入画')
            if manual_d <= 0:
                if dist is None:
                    bits.append('本帧距离不可信 —— 可在上面填一个卷尺量到的距离，'
                                '绕过标定')
                elif res is not None and not res.trusted:
                    bits.append('距离解算不可信' +
                                (f'（{res.reason}）' if res.reason else ''))
                elif res is not None and res.method not in ('接触点法', '两法一致'):
                    bits.append(f'当前测距走的是「{_method_display(res.method)}」，'
                                f'建档要求接触点法')
            capture_note = '；'.join(bits)

            # OSNet 嵌入：建档会话需要；追踪时如果档案库里有可比嵌入也必须提，
            # 否则 _match_active 会回落到 HSV 直方图 —— 该路线在实测中命中率
            # 为 0%（session-20260929-131735，250 帧全未过 0.55 门槛），
            # 而同一批数据的 OSNet 路线命中 94.0%。
            # 路人池（cohort 归一化）同样需要嵌入。
            emb = None
            has_emb_profile = any(
                bool((p.embedding or []) and p.emb_model == self._person_tracker.emb_tag)
                for p in self._person_tracker.profiles)
            if (self._person_tracker.enrolling and capture_ok) or has_emb_profile:
                emb = self._embed_for_enroll(frame_bgr, target)

            self._person_tracker.observe(
                target, frame_bgr, now_mono,
                capture_ok=capture_ok, distance_m=distance_used,
                fx=self.ranger.intrinsics.fx, fy=self.ranger.intrinsics.fy,
                embedding=emb, capture_note=capture_note)
            # 肩宽的取用已在**本回调开头**统一做过（每帧一次，不看画面）。
            # 这里不再重复赋值 —— 放在 observe() 之后有一个额外的坑：参数
            # 指定的追踪目标走出画面时本分支根本不进，配置就会残留他的值。

            # 换人提示（只在新面孔出现时说一次，不刷屏）。措辞保持中性 ——
            # 这里既可能是刚建档的人，也可能是匹配上的旧档案。
            #
            # ⚠️「近场框跨度法（横）改用该框跨度」这句**只在 p 就是追踪目标时成立**：
            # 框跨度法（横）现在只认追踪目标的框宽度（ranging_width_m）。画面里匹配到
            # 的若是别人，测距用的仍是默认 0.46 m —— 提示必须跟实际一致，
            # 否则又是一处「界面说改了、其实没改」，与刚才修掉的那个同类。
            p = self._person_tracker.active
            key = p.profile_id if p is not None else ''
            if key and key != self._last_profile_key:
                self._last_profile_key = key
                tail = ('—— 近场框跨度法（横）改用该框跨度'
                        if self._person_tracker.track_target() is p
                        else '—— 框跨度法（横）仍用默认 0.46 m（未把他指定为追踪目标）')
                self.status_bar.showMessage(
                    f'人员特征：{p.name}（'
                    f'{_span_pair_text(p.height_m, p.width_m)}）{tail}', 6000)
                # 新档案进了库 -> 设置页「追踪目标选择」下拉要跟着长出来，
                # 否则用户得等下次「应用参数」才看得见它（死列表问题）。
                self.refresh_track_target_combo()

            # 提交播报**不节流**：提交是稀疏事件（一次站定才一次），漏掉它
            # 用户就听不到提示音。判断本身只是比两个整数，成本可忽略。
            if self._person_tracker.enrolling:
                self._poll_enroll_commits()
            # UI 重绘才节流（setText 没必要 30 Hz 跑）。匹配行平时也刷 ——
            # 它回答「本帧是不是追踪目标」，是用户判断阈值松紧的唯一线索。
            self._enroll_ui_tick += 1
            if self._enroll_ui_tick % 5 == 0:
                if self._person_tracker.enrolling:
                    self._refresh_enroll_status()
                else:
                    self._set_match_line(self._person_tracker.match_line())

            # ---- 只为被追踪的这一个出数（CHARTER「范围内的」第 4 条）--------
            # 本帧认出来的是别人、或者谁都没认出来 -> 这个框不是追踪目标，
            # **不出数**：画面不画框（见 _draw_overlay）、距离按「不可测」处理，
            # 原因写进读数下面那行（用户 2026-09-29 要求）。
            #
            # 为什么连距离一起拦：距离 / 速度门控 / TTC 全都是**针对这一个体**
            # 的量，套在别人身上给出来的数字看着正常、实际是另一个人的 ——
            # 比「不可测」更坏，与 1.4 节「门控拦的是错值，不是拦人」同一条理。
            # 位置必须在 observe() 之后（判定在那里才产生）、在下面所有消费点
            # 之前（global_params.distance / TTC / 曲线 / 录制 / 读数）。
            # 标定页要用**拦截前**的测距结论（它不做追踪，见 _refresh_calib_distance）：
            # 拦截把 res/dist 抹成不可测是监视页的口径，标定页要的是「这一帧测出来
            # 多少」。所以在这里、在下面那条拦截之前，把结论原样存一份。
            self._calib_ranging = res
            reject_note = self._identity_reject_reason()
            if reject_note:
                self._identity_reject_note = reject_note
                res = RangingResult(reason=reject_note)
                dist = None
                # 框不是追踪目标 -> 滤波器里那段历史同样不可信，一起复位。
                # 不复位的话，人回到画面里时中值窗里还留着**别人的**距离，
                # 头几帧会给出一个看着正常、其实是路人位置的读数。
                self._dist_filter.reset()
                # 速度门控同理：别人走过的距离不能当成本人的锚点
                self._speed_gate.miss(now_mono)
        else:
            # 没走进匹配链路时**必须明说**，不能留旧分数 —— 匹配行只在上面
            # 那条分支里重算，不刷就停在上一次的数值上。2026-09-29 用户据此
            # 读成「画面里没人也有 0.44」，而 0.44 其实是残留。这条残留会
            # 直接误导「阈值松不松」的判断，所以三种原因分别说清。
            if is_person and not self.ranger.intrinsics.is_valid():
                self._set_match_line('匹配：相机未标定，认人未计算')
            elif is_person:
                self._set_match_line('匹配：本帧无可用检测框，未计算')
            else:
                self._set_match_line('匹配：本帧画面里没有人，未计算')
            # 标定页那份结论同理必须清掉：留着就会显示上一个人的读数，和画面里
            # 现在这个框对不上。三种情形（不是人 / 无框 / 未标定）一律清空，
            # 标定页随即退回读 `global_params.distance`（通常也是「不可测」）。
            self._calib_ranging = None
        # 到这里 dist 已是全链路唯一的规范距离（去噪在测距之后立即完成，
        # 见上方「距离去噪」段）：门控/人档案/读数/TTC/曲线/录制都用它。
        self.global_params.distance = dist

        # ---- TTC 碰撞预警（2026-09-25 实时接入）---------------------------
        # 喂门控后的距离（被速度门控拦截的帧 dist=None → 按测距不可用处理）。
        # has_target 的口径与测距一致：过置信度阈值且框高 > 0。
        # 时基用 monotonic（回调节奏 = 检测帧率），与离线用的录制相对时间
        # 同构 —— TTCEstimator 只关心差值。
        ttc_res = self._ttc.update(
            t=now_mono,
            box=(self.global_params.detection_x,
                 self.global_params.detection_y,
                 self.global_params.detection_width,
                 self.global_params.detection_height),
            class_id=self.global_params.detection_class,
            has_target=bool(self.global_params.detection_height > 0
                            and target is not None
                            and isinstance(target, dict)
                            and target.get('confidence', 0.0)
                            >= self.global_params.confidence_thres),
            distance=dist,
        )
        self.refresh_ttc_widgets(ttc_res)

        # 实时距离读数（监视页「目标位置」分组，CHARTER 门槛判据）
        # display() 在存疑时给 "5.00 m？"、不可测时给 "不可测"，都不隐藏数据
        self.label_distance_value.setText(res.display() if res is not None else '不可测')
        # 悬停说明 + 界面上那行「为什么」一起刷（同源，见 refresh_distance_widgets）
        # 同时记下这一帧的结果：标定判定异步复核时要用它原样重画，别把原因擦掉
        self._last_ranging = res
        self.refresh_distance_widgets(res)

        # 安装参数自标定：采样窗口内收集「框底边像素」（只收真的检测到目标的帧）。
        # 底边像素是自标定的观测量，它的随机误差直接进解算 —— 所以取一段窗口
        # 的平均值，并在收尾时用散布判断目标是否静止。
        # ⚠️ 2026-09-30：除了底边，还要留**框高**。只记底边的话，一旦结果可疑
        # 就无从判断「框底边到底是不是脚」—— 而那正是自标定唯一的观测前提。
        # 有了框高就能离线用「身高 1.79 / 框高」反推距离做独立校验。
        if self._marking and isinstance(target, dict) \
                and self.global_params.detection_height > 0:
            _h = float(self.global_params.detection_height)
            _yc = float(target.get('y', 0.0))
            self._mark_samples.append({
                'bottom': _yc + _h / 2.0,
                'top': _yc - _h / 2.0,
                'h': _h,
                'w': float(self.global_params.detection_width),
                # 贴边 = 脚/头可能已被画面截断，这种点的「底边」不是地面点
                'clip_bottom': _yc + _h / 2.0 >= (
                    self.global_params.intrinsics.image_size[1] - 2.0)
                if self.global_params.intrinsics is not None else False,
                'clip_top': _yc - _h / 2.0 <= 2.0,
            })

        if self.global_params.plot_enable:
            # 不可测的帧记 **NaN**：历史里保住「没有读数」的语义，不伪装成 0。
            # 显示归显示 —— update_analysis_plots 把这些帧映射成「未知」段：
            # 红色、值拉到 0、整条时间线不断点（2026-09-26 用户定稿：
            # 未知要画出来标红，而不是断开或消失）。
            # TTC 轨迹同一个口径（那里也记 NaN）。
            self.sensor_history_conf.append(self.global_params.detection_conf)
            self.sensor_history_fps.append(self.global_params.inference_fps)
            self.target_distance.append(
                float(dist) if dist is not None else float('nan'))
            # 类别轨迹（距离曲线按类别着色）+ 方法轨迹（只喂下方提示行）
            self.class_history.append(self.global_params.target_category or '未知')
            self.method_history.append(
                '不可测' if dist is None or res is None
                else (res.method or '几何测距'))
            # TTC 轨迹：不可算的帧记 NaN → 配合曲线的 connect='finite' 断线，
            # 不冒充 0 秒（单记 NaN 不够，见 __init__ 里该曲线的注释）
            self.ttc_history.append(
                ttc_res.ttc if ttc_res.available else float('nan'))
            self.ttc_reason_history.append(
                '' if ttc_res.available else (ttc_res.reason or '目标未在接近'))
            self.time_history.append(self.time_counter)
            self.sensor_history_conf_thres.append(self.global_params.confidence_thres)
            self.time_counter += 1.0 / self.global_params.sample_freq

        # 录制：数据轨与视频轨分开存，此处只追加一条记录（非阻塞）。
        # distance 存**规范值**（去噪后、与当时屏幕/判定同源的那个数），
        # distance_raw 只作诊断（事后重调滤波器参数用，实时逻辑不读）。
        if self.recorder is not None:
            self._rec_seq += 1
            self.recorder.push_record(FrameRecord.from_detection(
                seq=self._rec_seq,
                t=time.time() - self._rec_t0,
                target=target if isinstance(target, dict) else None,
                class_name=self.global_params.target_category,
                distance=dist,
                distance_raw=raw_dist,
                inference_fps=self.global_params.inference_fps,
            ))
            # ---- ReID 旁路（CHARTER v1.4「认人判据」的数据采集）------------
            # **只记录，不决策**：submit() 的返回值不参与任何判定，它只把
            # 「帧引用 + 框副本」塞进有界队列，裁剪 / BGR→RGB / 推理全在写线程，
            # 所以主线程开销是微秒级、不卡界面（见 core/reid_probe.py）。
            # seq 与上面那条 FrameRecord **同值**，两轨可按 seq 精确关联。
            if self._reid_probe is not None and is_person:
                self._reid_probe.submit(
                    getattr(self, 'current_frame', None), target,
                    seq=self._rec_seq,
                    t=time.time() - self._rec_t0,
                    class_name=self.global_params.target_category,
                )
            # 录制中同步画曲线（用户要求）。只记**有读数**的点，与回放曲线
            # （canonical_distance_series 跳过 None）口径一致；时间轴与上面
            # push_record 的 t 同式，所以录完切回放时曲线不用重画就对得上。
            # 分级用同一帧的 TTC 结果 → 录制时就能看见哪几段进入提示/预警/危险。
            if dist is not None:
                self._curve_push(time.time() - self._rec_t0, dist,
                                 ttc_res.level)

    def _on_calib_frame(self, frame_bgr):
        """标定采集回调：检测棋盘格角点并给出实时反馈。

        角点检测是 CPU 密集操作，用计数节流（每 10 帧检一次），
        否则会拖垮摄像头预览帧率、用户反而对不准。
        """
        self._calib_tick = getattr(self, '_calib_tick', 0) + 1
        if self._calib_tick % 10 != 0:
            return
        try:
            ok = self.calibrator.add_frame(frame_bgr)
        except Exception as e:
            print(f'[标定] 采集帧出错：{e}')
            return
        n = self.calibrator.frame_count
        self.btn_calib_solve.setEnabled(n > 0)   # 有帧就能求解，不必先暂停采集
        tip = ('帧数已够，可点「求解并保存」' if n >= 10
               else '建议继续变换姿态，覆盖画面四角与倾斜')
        if ok:
            self.label_calib_info.setText(
                f'已采集 {n} 帧（当前帧检测到棋盘格 ✓）\n{tip}')
        else:
            self.label_calib_info.setText(
                f'已采集 {n} 帧（当前帧未检测到棋盘格）\n'
                f'请让棋盘格完整入画、光照均匀、避免反光')

    def update_monitor_data(self):
        # 更新坐标
        self.lcd_centroid_x.display(self.global_params.detection_x)
        self.lcd_centroid_y.display(self.global_params.detection_y)
        # 更新FPS
        self.lcd_fps.display(self.global_params.fps)
        self.lcd_reasoning.display(self.global_params.inference_fps)

    # -- 摄像头掉线自愈 -------------------------------------------------------
    def _note_camera_lost(self, reason):
        """发现摄像头失联：放掉旧句柄、给用户看得见的提示、起线程重连。"""
        if self._cam_reconnecting:
            return                      # 已经在重连了，别每帧重复起线程
        self._cam_reconnecting = True
        self._cam_retry += 1
        # ⚠️ 旧句柄必须先放掉：DirectShow 是独占的，不 release 就去开新的，
        #    新句柄必然打不开（设备忙），重连就永远失败。
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        self.cap = None
        self._show_camera_banner(
            f'摄像头无画面（{reason}）\n正在重连…（第 {self._cam_retry} 次）')
        self.status_bar.showMessage(
            f'摄像头无画面：{reason}，正在重连（第 {self._cam_retry} 次）', 10000)
        self._start_camera_reconnect()

    def _start_camera_reconnect(self):
        """在子线程里重开摄像头 —— 打开要秒级（后端重试更久），不能堵主循环。"""
        th = CameraInitThread(self.camera_index, self.global_params.fps)
        th.init_finished.connect(
            lambda ok, msg: self._on_camera_reopened(ok, msg, th))
        self._reconnect_thread = th      # 必须持有引用，否则线程会被 GC
        th.start()

    def _on_camera_reopened(self, success, message, thread):
        if success:
            self.cap = thread.cap
            self._cam_reconnecting = False
            self._cam_fail_streak = 0
            self._cam_retry = 0
            self._reconnect_thread = None
            self.status_bar.showMessage(f'摄像头已恢复：{message}', 5000)
            # 驱动重置后分辨率可能回到默认，内参是否还适用要重新判一次
            try:
                self.verify_calibration_against_frame()
            except Exception:
                pass
            return
        # 失败：指数退避后重试。不立刻重试，是因为设备刚掉线时驱动多半还没
        # 准备好，立刻开大概率再失败，白付一次秒级的打开开销。
        delay = min(CAM_RETRY_BASE_S * (2 ** (self._cam_retry - 1)),
                    CAM_RETRY_MAX_S)
        self._show_camera_banner(
            f'摄像头无画面\n重连失败（第 {self._cam_retry} 次），'
            f'{delay:.0f} 秒后重试')
        self.status_bar.showMessage(
            f'摄像头重连失败（第 {self._cam_retry} 次），{delay:.0f} s 后重试',
            10000)
        QTimer.singleShot(int(delay * 1000), self._start_camera_reconnect)

    def _show_camera_banner(self, text):
        """画面区大字提示。QLabel 有 pixmap 时 setText 不显示，必须先 clear。"""
        for lbl in (getattr(self, 'lbl_process', None),
                    getattr(self, 'lbl_original', None)):
            if lbl is None:
                continue
            try:
                lbl.clear()
                lbl.setText(text)
            except Exception:
                pass

    def _check_detection_heartbeat(self):
        """摄像头在出帧，但检测链路长时间没有结果 —— 要说出来，不能装作正常。

        依据：检测器每 4 帧**必**回调一次（没目标时发 None，见
        ``YOLODetector.predict`` 末尾的无条件 emit），所以「长时间没回调」
        只可能是链路断了，不是「画面里没人」。
        """
        if (self.cap is None or self.detector is None or self.is_loading_model
                or self._last_detection_ts is None):
            return
        gap = time.monotonic() - self._last_detection_ts
        if gap > DET_HEARTBEAT_TIMEOUT_S:
            # 顺手松开背压：在途计数若因为「回调没回来」卡住，不重置的话
            # 就永远不再投帧了 —— 那么看门狗自己反倒成了新的死锁。
            if self._inflight_frames > 0:
                self._inflight_frames = 0
            self.status_bar.showMessage(
                f'检测链路无响应：已 {gap:.0f} s 没有新的检测结果', 3000)

    def update_camera_frame(self):
        # 掉线自愈（2026-10-02）：cap 为 None / 已关闭 / 连续读不到帧，都走
        # 看门狗。原先这里三处都是「静默 return」—— 挂机半小时后设备被系统
        # 挂起，画面就永远停在最后一帧，用户回来看到的就是「框不动、认不出人」。
        if self.cap is None or not self.cap.isOpened():
            self._note_camera_lost('摄像头未打开')
            return

        ret, frame = self.cap.read()
        if not ret:
            self._cam_fail_streak += 1
            if self._cam_fail_streak >= CAM_FAIL_STREAK:
                self._note_camera_lost('摄像头读不到画面')
            return
        self._cam_fail_streak = 0
        try:
            # 标定采集中：把当前帧喂给标定器，不改动显示逻辑。
            # ⚠️ 门条件必须是「采集中且标定器存在」，不能只看 calibrator 是否为 None：
            # 「停止采集」只把 _collecting 置回 False（帧全部保留），若这里不看这个标志，
            # 暂停后仍会持续接帧 —— 与按钮语义和文档不符，且会立刻覆盖掉
            # 「已暂停采集，已保留 N 帧」这句提示，用户又会以为帧丢了。
            if self.calibrator is not None and getattr(self, '_collecting', False):
                self._on_calib_frame(frame)

            # 录制：投入写盘队列（非阻塞，满则丢帧并计数）
            if self.recorder is not None:
                self.recorder.push_frame(frame)

            # 保留 RGB 副本供检测线程使用
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.current_frame = frame_rgb.copy()
            # 显示复用统一入口（实时与回放共用同一套绘制逻辑）
            self._display_frame(frame)
        except Exception as e:
            print(f"帧处理出错：{e}")

        #向检测器子线程发送帧数据
        if self.detector and self.detector_thread.isRunning() and not self.is_loading_model:
            self.frame_counter+=1
            if self.frame_counter % (self.inference_interval + 1) == 0:
                # 背压（见模块顶 MAX_INFLIGHT_FRAMES）：处理不过来就丢这一帧，
                # 而不是让它排进队列把延迟越拖越大。丢多少如实计数，不静默。
                if self._inflight_frames >= MAX_INFLIGHT_FRAMES:
                    self._dropped_inference_frames += 1
                    return
                self._inflight_frames += 1
                self.frame_signal.emit(frame_rgb.copy())

    def closeEvent(self, event):
        # 停止采集，避免关闭时还持有标定器
        self.calibrator = None
        self._collecting = False
        # 安装参数自标定的采样窗口：关窗时停掉定时器，避免回调打到已销毁的控件
        self._marking = False
        if self._mark_timer is not None and self._mark_timer.isActive():
            self._mark_timer.stop()
        # 求解线程可能正卡在 cv2.calibrateCamera（十几秒），**必须等它退出**，
        # 否则关窗时线程还在跑会崩。顺便断开信号：关窗口不该再弹标定结果。
        th = getattr(self, '_solve_thread', None)
        if th is not None and th.isRunning():
            try:
                th.solved.disconnect()
            except (RuntimeError, TypeError):
                pass
            print('[标定] 关闭时等待求解线程结束……')
            th.wait()
        # 摄像头重连线程可能正卡在后端重试（十几秒），关窗前必须断开并等它
        rt = getattr(self, '_reconnect_thread', None)
        if rt is not None and rt.isRunning():
            try:
                rt.init_finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            rt.wait(3000)
        # 设备枚举线程（兜底通路走 PowerShell，可能正卡在几秒的查询上）
        it = getattr(self, '_identify_thread', None)
        if it is not None and it.isRunning():
            try:
                it.identified.disconnect()
            except (RuntimeError, TypeError):
                pass
            it.wait(3000)
        # 模型加载线程同理（在子线程里建 ORT 会话）
        mt = getattr(self, 'model_thread', None)
        if mt is not None and mt.isRunning():
            mt.wait()
        # 录制中关闭：必须收尾落盘，否则数据轨丢失、视频文件损坏
        if self.recorder is not None:
            try:
                meta = self.recorder.stop()
                print(f'[录制] 关闭时收尾：{meta.frame_count} 帧，'
                      f'{meta.data_count} 条记录，丢帧 {meta.dropped_frames}')
            except Exception as e:
                print(f'[录制] 关闭收尾失败：{e}')
            self.recorder = None
        # 回放收尾
        if self.replay_timer is not None and self.replay_timer.isActive():
            self.replay_timer.stop()
        if self.replayer is not None:
            self.replayer.close()
            self.replayer = None
        # 停止所有定时器（含看门狗，否则回调会打到已销毁的控件）
        for timer in [self.update_timer, self.camera_timer, self.analysis_timer,
                      getattr(self, 'watchdog_timer', None)]:
            if timer is not None and timer.isActive():
                timer.stop()
        # 释放摄像头
        if self.cap is not None and self.cap.isOpened():
            self.cap.release()
        # 等待子线程结束
        if hasattr(self, 'camera_thread') and self.camera_thread.isRunning():
            self.camera_thread.quit()
            self.camera_thread.wait(1000)
        if hasattr(self, 'model_thread') and self.model_thread.isRunning():
            self.model_thread.quit()
            self.model_thread.wait(1000)
        event.accept()
            
if __name__=='__main__':
    app=QApplication(sys.argv)
    window=MainWindow()
    window.show()
    app.exec()