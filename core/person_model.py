"""人员特征档案与速度门控 —— 近场「框跨度法（横）」的两大支柱。

定位对应：`CHARTER.md`「范围内的」第 2 条几何测距的近场扩展。
设计讨论与用户决策见 2026-09-25 笔记（P1+ 方案）。

为什么需要这个模块
------------------
接触点法的几何下限（当前机位 1.85 m）以内，脚不在画面里，两条几何法都无解。
但近场恰恰是农业车跟随/避障最需要的区间。用户定的 P1+ 方案用三个纯软件手段
把盲区降级成「参考值」而不是「不可测」：

1. **框跨度法（横）兜底**（配合 ``core/calibration.GeometricRanger``）：
   脚出画、左右未裁时 ``Z = fx * W_真实 / 框宽``。其中 W_真实 不再拍脑袋填
   0.46 m，而是 ——
2. **人特征档案**：目标完整可见、接触点法出数的帧里顺手量出这个人的
   框跨度（``W = D * 框宽px / fy``），滚动窗口取中位数、稳定后提交，
   之后框跨度法（横）用的就是「这个人自己的框宽度」。多个人靠外观直方图区分。
   ⚠️ 注意量的是**检测框覆盖的真实尺寸**，不是身高/肩宽 —— 见 ``PersonProfile``
   那两个字段的注释（2026-10-02 定稿）。
3. **速度门控**：人不可能瞬移。相邻两帧的距离变化隐含速度，超过人体极限
   （默认 8 m/s，博尔特冲刺也就 ~10 m/s）的一律拦下 —— 拦的是**跳变错值**，
   不是拦人。

三个组件都是**纯逻辑**（不碰 Qt、不碰线程），与 ``core/calibration`` 同风格，
可离线单测（``E:\\WorkBuddy-Work\\scripts\\verify_person_model.py``）。

CHARTER v1.4 之后，档案还承担**身份**职责：「追踪目标选择」（设置页）
从本模块的档案列表里**单选**一条作为唯一追踪目标（``is_track_target``），
且名字可由用户改（``display_name``）。**档案仍是同一个文件**
（``models/person_profile.json``，v2 结构），不另建平行档案库 —— 见
CHARTER「范围内的」建档条：补 ``display_name`` / ``is_track_target`` / 来源标记。

⚠️ 精度声明：框跨度法（横）天生只有「参考级」（±15% 起步）。侧身时肩深 ~0.25 m
（肩宽的 ~55%），会把距离**高估近一倍** —— 方向危险（以为远、实际近）。
缓解：跟随场景几乎都是从背后跟（肩面朝相机），且结果恒标「参考」、
``trusted=False``，绝不喂给需要精度的下游当精确值用。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from typing import Optional

import cv2
import numpy as np

# 嵌入相似度只是**点积**（纯数学）。借自 ``core.reid_osnet`` 是为了全项目只有
# 一份实现。注意该模块顶层**不 import onnxruntime**（会话延迟到 ``load()`` 才建），
# 所以本模块仍然是「纯逻辑、可离线单测」的 —— 这条 import 不会拉起重型依赖。
from core.reid_cohort import (
    COHORT_ADMIT_BELOW, COHORT_MAX_SIZE, COHORT_QUANTILE,
    CohortPool, normalize_score,
)
from core.reid_osnet import embedding_similarity


# ---------------------------------------------------------------------------
# 外观特征：躯干 HSV 直方图（区分不同的人）
# ---------------------------------------------------------------------------

# 躯干采样带（占框高的比例）：避开头部/背景（上）与腿部/地面（下），
# 取躯干为主的中间段；横向各收 20%，削掉背景边缘。
_TORSO_Y_RANGE = (0.35, 0.70)
_TORSO_X_MARGIN = 0.20
_HIST_BINS = (8, 8, 8)          # H/S/V 各 8 桶 -> 512 维
_MIN_ROI_PX = 8                # ROI 比这还小就不算特征（噪声主导）


def torso_appearance(frame_rgb, box):
    """取躯干带的 HSV 直方图，L1 归一化。**纯函数**。

    返回 512 维 ``np.ndarray``；框太小 / 帧无效时返回 ``None``。

    为什么取躯干而不是整个人：人头（发型/帽子）与腿部（裤鞋）随姿态变化大，
    躯干衣着才是同一个人跨帧最稳定的视觉特征。为什么用 HSV 而不是 BGR：
    色调对光照亮度变化相对稳，比 BGR 的三通道抖动小得多。
    """
    if frame_rgb is None or box is None:
        return None
    h_px = float(box.get('height', 0.0))
    w_px = float(box.get('width', 0.0))
    cx = float(box.get('x', 0.0))
    cy = float(box.get('y', 0.0))
    if h_px < _MIN_ROI_PX * 3 or w_px < _MIN_ROI_PX * 3:
        return None

    fh, fw = frame_rgb.shape[:2]
    x1 = int(round(cx - w_px / 2.0 + w_px * _TORSO_X_MARGIN))
    x2 = int(round(cx + w_px / 2.0 - w_px * _TORSO_X_MARGIN))
    y1 = int(round(cy - h_px / 2.0 + h_px * _TORSO_Y_RANGE[0]))
    y2 = int(round(cy - h_px / 2.0 + h_px * _TORSO_Y_RANGE[1]))
    x1, x2 = max(0, x1), min(fw, x2)
    y1, y2 = max(0, y1), min(fh, y2)
    if x2 - x1 < _MIN_ROI_PX or y2 - y1 < _MIN_ROI_PX:
        return None

    roi = frame_rgb[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, list(_HIST_BINS),
                        [0, 180, 0, 256, 0, 256])
    hist = hist.ravel().astype(np.float64)
    s = hist.sum()
    if s <= 0:
        return None
    return hist / s


def appearance_similarity(a, b) -> float:
    """两个外观特征的相似度，∈ [0, 1]。**纯函数**。

    用 ``1 - 0.5 * Σ|a-b|``（L1 距离归一）：同一个人同衣着稳定在 0.6+，
    换个人换身衣服一般 < 0.5 —— 阈值取 0.55（见 ``PersonFeatureTracker``）。
    """
    if a is None or b is None:
        return 0.0
    return float(1.0 - 0.5 * np.abs(a - b).sum())


# ---------------------------------------------------------------------------
# 人特征档案
# ---------------------------------------------------------------------------

# v3（2026-09-27）：档案新增 ``embedding`` / ``emb_model``（OSNet 外观嵌入）。
# v1/v2 老档案读进来这两个字段为空 -> 匹配自动回落 HSV 直方图，不报错、不崩。
PERSON_PROFILE_VERSION = 3

# 采样合理性区间：框跨度反解值落在外面说明这一帧有毛病（遮挡、非站姿、
# 类别误识别），直接丢样本 —— 绝不把离群值往档案里记。
# 这是**逐帧**的宽区间：它的职责只是丢掉这一帧，代价极小，所以放得宽。
PLAUSIBLE_HEIGHT_M = (0.90, 2.40)
PLAUSIBLE_WIDTH_M = (0.15, 1.00)

# 建档（写进档案）用的**严区间**（2026-09-29 新增）。与上面宽区间的区别：
#   宽区间 = 这一帧丢不丢（代价：少采一帧）
#   严区间 = 要不要落盘（代价：**一个错值会一直留在库里**，而 width_m 之后
#            一直参与近场框跨度法（横）测距 —— 存错了就一直算错，且不报错）
# 所以严区间取「成年作业人员」的真实范围，宁可这次建档失败并说清原因。
#
# 区间**名义上**按「成人身高集中在 1.50~1.90 m」取，1.40/2.00 是留了余量的边 ——
# 但它实际卡的是**框跨度**（比身高小约 0.37 m），口径对不上，见下面「已知代价」。
#
# 肩宽这一栏**不能用「双肩峰间宽」**（成人 0.35~0.41 m）：本模块取的是
# **检测框宽**反解的宽度，而框宽含手臂与衣着，天然比肩宽大 20~50%。
# 所以改用**本机实测**定区间：17 段历史录制里「四条边都没贴画面」的 406 帧，
# 反解宽度 p05=0.377 / 中位 0.484 / p95=0.681（脚本
# E:\WorkBuddy-Work\scripts\analyze_enroll_plausibility.py）。
# 区间取 [0.28, 0.75]，在实测 p05/p95 外各留一点余量。
# ⚠️ 一开始按「肩宽」写成 [0.30, 0.58]，实测立刻证明它偏紧：会把约 15% 的
# 正常帧当成不合格。这类「把物理量搞错对象」的错，只能靠实测分布发现。
#
# ⚠️ 已知代价，必须说清（2026-10-02 用户实测后**改判**）：
# 本机历史录制（17 段）里，未贴边帧的反解值中位只有 **1.337 m**
# （p95=1.597，最高 1.765），**没有一帧达到 1.6**。原先记为「反解链路系统性
# 偏低」—— **这个归因是错的**。真因：反解出的本来就是**框跨度**（底边在小腿、
# 顶边在额头），比真身高小约 0.37 m 属正常。中位 1.337 m 对应真身高约
# 1.71 m，完全合理；不是链路有偏差，是**拿身高的尺子量了框跨度**。
#
# 后果：**这个区间下限偏严**。1.79 m 的人反解 1.4177 只是勉强过关；
# 1.50 m 的人框跨度约 1.13 m，会被这道闸拒掉并提示「不在 1.40–2.00 内」。
# 按框跨度口径重取应是约 **(1.10, 1.60)**（= 身高 1.50~2.00 各减 0.37）。
# ⚠️ **数值本次不动** —— 放宽阈值是行为变更，要用户拍板，不擅自改。
#
# 保留「宁可拒」的取舍：反解错的跨度同时意味着宽度也错（两者同源、同一个框），
# 与其静默存一个会毒化近场测距的值，不如明确说「这次没成、为什么」。
ENROLL_HEIGHT_M = (1.40, 2.00)
ENROLL_WIDTH_M = (0.28, 0.75)

# 反解精度下限：框高越小，「distance × h_px / fy」的相对误差越大
# （h_px=40 时 2 px 的框边抖动就是 5%）。与 reid_osnet.MIN_BOX_H_PX(32)
# 同量级，但这里要的是**量体精度**而不是「能不能提特征」，所以略严。
ENROLL_MIN_BOX_H_PX = 40.0


@dataclass
class PersonProfile:
    """一个人的可测特征：身高、肩宽、外观，以及它的**身份与登记信息**。

    「凭什么信这个数」：``n_updates`` 是提交进档案的**稳定窗口数**（每窗口
    ≥12 帧、CV≤5%），``updated_at`` 记最后一次提交时间 —— 排查时能回答
    「这个肩宽是什么时候、从多少帧里量出来的」。

    身份字段（CHARTER v1.4「建档 + 追踪目标选择」）：
    ``display_name`` 用户可改的名字（空 = 未命名，UI 回落到 ``profile_id``）；
    ``is_track_target`` 是否被指定为**唯一**追踪目标（单选，全库最多一条为真）；
    ``enroll_source`` / ``enrolled_at`` 区分「用户主动建档」与「追踪时被动
    自动建档」—— 这两种来源必须能分开：前者才是 CHARTER 说的「事先登记」，
    后者只是「这个人出现过」的证据，认人可信度不同。
    """

    profile_id: str = 'person-1'
    display_name: str = ''       # 用户可改的名字；'' = 未命名，显示时回落 profile_id
    is_track_target: bool = False  # 唯一追踪目标标记（单选）
    # ⚠️ 这两个数**不是身高 / 肩宽**，是**检测框覆盖的真实尺寸**（2026-10-02 定稿）：
    #   纵 = 框顶到框底，横 = 框左到框右（含手臂与衣着）。
    # 实测本项目检测器只框住身体约 1.42 m —— 底边在小腿（不在脚）、顶边在
    # 额头（不到头顶），所以纵跨度比真人矮约 21%（真身高 1.79 → 反解 1.4177，
    # 与先验 ``BODY_SPAN_PRIOR_M = 1.41`` 只差 0.5%）；横跨度含手臂，比肩峰宽
    # 大约 10~30%。**这是检测器的框法决定的，与标定好坏无关**，改标定改不掉。
    #
    # 字段名保留 ``height_m`` / ``width_m`` **不动**：它是 JSON 存档键，验收
    # 脚本与 ``main_windows._sync_ranging_width`` 都按它读。要改的是**给人看
    # 的那层** —— 界面一律显示「框跨度」（见 ``_span_pair_text``）。
    height_m: float = 0.0        # 框跨度·纵（米），接触点法距离 × 框高px / fy
    width_m: float = 0.0         # 框跨度·横（米），接触点法距离 × 框宽px / fx
    appearance: list = field(default_factory=list)   # 512 维 HSV 直方图（JSON 可存）
    embedding: list = field(default_factory=list)    # 512 维 OSNet 嵌入（L2 归一）
    n_updates: int = 0           # 提交次数（每次一个稳定窗口）
    updated_at: str = ''
    source: str = ''             # 样板来源说明（首次创建时记）
    enrolled_at: str = ''        # 主动建档时间；'' = 尚未主动登记
    enroll_source: str = 'auto'  # 'manual' 用户建档 / 'auto' 被动自动建档
    emb_model: str = ''          # embedding 出自哪个模型；换模型后旧嵌入不可比

    def similarity(self, hist) -> float:
        """与 **HSV 直方图**（``appearance`` 字段）的相似度，∈ [0, 1]。

        ⚠️ **只接受 HSV 直方图**。要比 OSNet 嵌入请用 ``embedding_similarity()``：
        两者**都是 512 维、都被归一化到 norm=1**，传错**既不抛异常、数值也不显异常**
        —— 只会静默得到无意义的数。字段是分开的（``appearance`` / ``embedding``），
        别手动把嵌入塞进 ``appearance``。
        """
        if not self.appearance or hist is None:
            return 0.0
        return appearance_similarity(np.asarray(self.appearance, dtype=np.float64),
                                     np.asarray(hist, dtype=np.float64))

    def embedding_similarity(self, emb) -> float:
        """与 **OSNet 嵌入**（``embedding`` 字段）的余弦相似度，∈ [-1, 1]。

        ⚠️ **判别力相对 ``similarity()`` 强多少，至今没有可信数字。**
        曾经写在这里的「实测 6.4 倍（+0.090 vs +0.014）」**已撤回** ——
        那个探针脚本（``probe_osnet_reid.py``）两侧量到的都是**同一个人**的
        样本，得到的是「同一人跨时间/光照/衣着的**稳定性**」，
        **不是「不同人之间的可分性」**。真实异人分布至今没有数据
        （历史 17 段录制里只有一个人，见 ``contact_sheet.png``）。
        能说的只有：两者都远谈不上可依赖，而 OSNet 至少在同人回访上分得开。

        档案里没有嵌入（v1/v2 老档案）时返回 ``0.0``，调用方据此回落 HSV 路子。
        """
        if not self.embedding or emb is None:
            return 0.0
        return embedding_similarity(np.asarray(self.embedding, dtype=np.float32),
                                    np.asarray(emb, dtype=np.float32))

    @property
    def name(self) -> str:
        """显示用名字：用户改过就用改过的，没改过就用 profile_id。"""
        return self.display_name or self.profile_id

    @property
    def is_enrolled(self) -> bool:
        """是否是「事先登记」的档案（区别于追踪时被动自动建档）。"""
        return self.enroll_source == 'manual'


class PersonFeatureTracker:
    """从「完整可见且测距可信」的帧里持续量人，滚动窗口稳定后提交档案。

    工作流（每帧最多三件事，全部 <1 ms 量级）::

        tracker.observe(box, frame_rgb, now,
                        capture_ok=…, distance_m=…, fx=…, fy=…)

    1. 算外观直方图 -> 与已有档案匹配 -> 决定「当前是哪个人」（active）；
    2. **仅在主动建档会话中**（调用过 ``begin_enrollment()`` 之后）：
       ``capture_ok``（目标完整 + 接触点法可信，由调用方按可见性体检决定）
       时把 (身高, 肩宽, 外观) 存进滚动缓冲；
    3. 同样仅在建档会话中，缓冲里攒够一个**静止稳定**的窗口（≥12 帧、
       身高 CV ≤5%）才提交 —— 匹配上的人用 EMA 更新，匹配不上就新建档案。

    ⚠️ **被动路径不建档**（2026-09-27 改正，对 CHARTER v1.4「建档」条）：
    原先任何人只要在画面里站定约 1 秒就会被**自动**记入档案 —— 那是 2026-09-25
    为「框跨度法（横）需要一个肩宽」顺手加的机制，与 v1.4「建档是用户主动走的独立第三步
    （Q1=A 事先登记）」**方向相反**：它会把路过的人写进库、还会挤掉真正登记的目标，
    而用户从未要求过。现在：**没调用 ``begin_enrollment()`` 就只认人、不采样、
    不落盘**，档案只能由主动建档产生。

    为什么「稳定窗口」而不是逐帧 EMA：人在走动时框宽/框高本来就会抖，
    逐帧更新会把走姿的抖动永远洗进档案里。窗口 + CV 门槛等价于
    「让目标先站定一秒再量」—— 与安装参数自标定采样用同一套纪律
    （散布过大就拒收，不记脏点）。
    """

    JSON_VERSION = PERSON_PROFILE_VERSION

    def __init__(self, json_path: str, *,
                 max_profiles: int = 5,
                 match_threshold: float = 0.55,
                 emb_match_threshold: float = 0.50,
                 emb_tag: str = '',
                 commit_min_samples: int = 12,
                 window_s: float = 3.0,
                 height_cv_max: float = 0.05,
                 ema_alpha: float = 0.30,
                 enroll_height_m: tuple = ENROLL_HEIGHT_M,
                 enroll_width_m: tuple = ENROLL_WIDTH_M,
                 enroll_min_box_h_px: float = ENROLL_MIN_BOX_H_PX,
                 cohort_enabled: bool = False,
                 cohort_admit_below: float = COHORT_ADMIT_BELOW,
                 cohort_quantile: float = COHORT_QUANTILE,
                 cohort_max_size: int = COHORT_MAX_SIZE):
        """
        match_threshold
            **HSV 直方图**路子的阈值（L1 相似度）。沿用旧值 0.55。
        emb_match_threshold
            **OSNet 嵌入**路子的阈值（余弦）。⚠️ 这是**占位值，不是校准值**：
            取 0.50 的锚点是「同一人跨会话实测中位 0.502」（``probe_osnet_reid.py``）；
            取略低是为了先保证「认得出自己」。**异人分布当前无数据**
            （录制里只有一个人，缺负样本），所以偏松或偏紧都无法证伪。
            待含第二位真人的录制到手后重新标定 —— 在那之前 UI 会同时显示
            实际分数，让「认不出」和「门槛定错」能被人看出来。
        emb_tag
            嵌入来源标记（建议用模型文件名）。档案里记它、匹配时比它 ——
            换模型后旧嵌入与新嵌入不同源，必须拒绝比较而不是算个数出来。
        enroll_height_m / enroll_width_m / enroll_min_box_h_px
            **建档复核区间**（2026-09-29 新增）：攒够稳定窗口后、落盘之前，
            反解出的身高/肩宽必须落在这里面，否则**这一次建档失败**并给出
            原因，而不是把可疑值静默写进库。
            为什么要这一步：这两个数之后一直参与近场框跨度法（横）测距，**存错了
            就一直算错、而且不报错**。默认值见 ``ENROLL_HEIGHT_M`` 等常量的
            注释（含「本机反解系统性偏低、所以这个区间偏严」的已知代价）。
            三个参数都可配置 —— 它们刻的是「作业人员」这个场景假设，
            不是本机标定结果。
        cohort_enabled
            **路人池归一化开关，默认关**（``core/reid_cohort.py``）。开启后，
            匹配分数会减去「本场景里路人最多能像到什么程度」再与门槛比，
            让门槛跨场景可比。**默认关的理由是实测判决、不是保守**：
            用 17 段历史回放（2054 条嵌入、全部同一人）做留一交叉验证测得
            —— 画面里只有目标一人时，池**恒为空**（准入门槛 0.30 下 32864
            帧仅 2 帧入池且不足 3 条），归一化从不生效；而门槛一旦放松到
            0.35，池立刻被**本人帧**填满，本人通过率从 59.8% 崩到 1.3%。
            也就是说：**在"只有目标一人"的场景里它无收益，且门槛稍松即有害**。
            它的收益完全依赖「场景里真会出现路人」这个尚未发生过的前提。
            脚本：``cohort_real_probe.py``（判决）、``verify_cohort_norm.py``（单测）。

            ⚠️ **开启后门槛含义会变，且当前阈值未按新口径重标定**：判定用的是
            ``raw − offset``，而 ``emb_match_threshold``（0.50）是**原始口径**
            定的 —— 等价于把实际门槛抬到 ``0.50 + offset``。实测本人帧的
            offset 约 0.09，即实际门槛约 0.59，**判定只会更严、不会更松**。
            要正确使用，阈值必须用**含路人**的录制在归一化口径下重新校准；
            在那之前 ``match_line()`` 会把「门槛为原始口径，未按偏移重标定」
            写在分数后面，免得「原始 0.58 过了 0.50 却判不通过」被当成 bug 查。
        cohort_admit_below / cohort_quantile / cohort_max_size
            路人池参数，见 ``core/reid_cohort.py``。
        """
        self.json_path = json_path
        self.max_profiles = max_profiles
        self.match_threshold = match_threshold
        self.emb_match_threshold = emb_match_threshold
        self.emb_tag = emb_tag
        self.commit_min_samples = commit_min_samples
        self.window_s = window_s
        self.height_cv_max = height_cv_max
        self.ema_alpha = ema_alpha
        # 建档复核区间（落盘前的最后一道闸，见 __init__ docstring）
        self.enroll_height_m = tuple(enroll_height_m)
        self.enroll_width_m = tuple(enroll_width_m)
        self.enroll_min_box_h_px = float(enroll_min_box_h_px)

        # 路人池（cohort 归一化）。**无论开关是否打开都建对象** —— 它是一个
        # 空 deque，代价可忽略；这样开关可以运行期翻转，不必重建 tracker。
        self.cohort_enabled = bool(cohort_enabled)
        self._cohort = CohortPool(max_size=cohort_max_size,
                                  admit_below=cohort_admit_below,
                                  quantile=cohort_quantile,
                                  model_tag=self.emb_tag)

        self.profiles: list[PersonProfile] = []
        self.active: Optional[PersonProfile] = None
        self._samples: list[dict] = []      # {t, h, w, hist, emb}
        self._enrolling = False             # 是否处于「主动建档会话」中
        self._last_match: dict = {}         # 最近一次匹配的路线/分数/门槛
        # 本帧「认人」的结论快照（``computed=False`` 表示这一帧没算过）。
        # 为什么不能直接用 ``active``：那是"最近一次算过的结论"，本帧若没算
        # （不是人 / 相机未标定 / 框无效）它会**保留上一帧的值**，上层就分不清
        # 「算出来不是追踪目标」与「本帧根本没算」—— 而这两种情况该不该拦
        # 是相反的（见 main_windows._identity_reject_reason 的两条「不拦」）。
        self._frame_identity: dict = self._no_identity()
        self._commits = 0                   # 累计提交次数（UI 据此播报提示音）
        # 建档反馈（2026-09-29）：这两个字段的存在本身就是为了「别静默」——
        # 原先 observe()/ _try_commit() 的每个不通过分支都是裸 return，
        # 用户站在镜头前只能空等，分不清是没采到、采了不合格、还是程序坏了。
        self._last_block: dict = {}         # 本帧为何没采样（逐帧更新，会自清）
        self._failures = 0                  # 复核不通过的累计次数
        self._last_failure: dict = {}       # 最近一次失败（带递增 seq，供 UI 一次性播报）
        # 失败后「等站位真的变了再采」的参照值（失败时的反解身高中位，米）。
        # 为什么需要它：失败会清空窗口，但**紧接着的几帧还是旧姿态**（用户
        # 要先看到提示、再挪位置），它们会被采进新窗口，于是新窗口里旧/新两段
        # 数据混着，cv 一直超标 -> 界面继续喊「站定别动」，而用户明明站着不动。
        # 实测（verify_calib_tab_wiring.py E 组）：不设这道闸，改好姿势后仍要等
        # window_s=3.0 s 旧帧滚出去才可能提交，期间提示是错的。
        self._await_change: Optional[float] = None
        self._dirty = False
        self.load()

    # -- 持久化 -----------------------------------------------------------

    def load(self) -> None:
        """读档案。读不到不是错误（第一次用还没有档案），返回空列表。"""
        if not os.path.isfile(self.json_path):
            return
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            profiles = []
            for p in data.get('profiles', []):
                profiles.append(PersonProfile(
                    profile_id=str(p.get('profile_id', '')),
                    display_name=str(p.get('display_name', '') or ''),
                    is_track_target=bool(p.get('is_track_target', False)),
                    height_m=float(p.get('height_m', 0.0)),
                    width_m=float(p.get('width_m', 0.0)),
                    appearance=list(p.get('appearance', [])),
                    # v3 之前的老档案没有嵌入 -> 空列表，匹配自动回落 HSV
                    embedding=list(p.get('embedding', []) or []),
                    n_updates=int(p.get('n_updates', 0)),
                    updated_at=str(p.get('updated_at', '')),
                    source=str(p.get('source', '')),
                    enrolled_at=str(p.get('enrolled_at', '')),
                    # v1 老档案没有字段 -> 它们都是追踪时被动建档的
                    enroll_source=str(p.get('enroll_source', 'auto') or 'auto'),
                    emb_model=str(p.get('emb_model', '') or ''),
                ))
            self.profiles = profiles
            # 唯一性自愈：文件被手改/合并过可能出现多条 is_track_target，
            # 只保留第一条（否则「追踪目标选择」的语义就破了）。
            seen = False
            for p in self.profiles:
                if p.is_track_target:
                    if seen:
                        p.is_track_target = False
                    seen = True
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            self.profiles = []

    def save(self) -> None:
        payload = {
            'version': self.JSON_VERSION,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'profiles': [asdict(p) for p in self.profiles],
        }
        d = os.path.dirname(os.path.abspath(self.json_path))
        os.makedirs(d, exist_ok=True)
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        self._dirty = False

    # -- 主动建档会话（CHARTER v1.4「建档」） ------------------------------

    def begin_enrollment(self) -> None:
        """开启**主动建档会话**：此后 ``observe()`` 才开始采样、攒窗口、落盘。

        重复调用幂等（已在会话中就不清空已采样本，避免误操作把进度扔掉）。
        """
        if not self._enrolling:
            self._enrolling = True
            self._samples = []
            # 重新开始一次会话 = 用户确实改变了什么，失败后的等待解除。
            self._await_change = None

    def end_enrollment(self) -> None:
        """结束建档会话：停止采样。未成窗口的样本一并作废。"""
        self._enrolling = False
        self._samples = []
        self._await_change = None

    @property
    def enrolling(self) -> bool:
        """是否正在主动建档会话中（界面据此显示"正在建档"状态）。"""
        return self._enrolling

    def enroll_progress(self) -> dict:
        """建档进度快照，供 UI 显示大字状态与匹配分数。**不表达判定**。

        ``samples``/``required`` 是「已采帧数 / 提交门槛」；
        ``active_name`` 为空表示本帧没匹配上任何人；
        ``match_*`` 是最近一次匹配走的哪条路、分数多少、门槛多少、有几条可比档案
        —— 阈值未校准期间，这是判断「认不出」还是「门槛定错」的唯一依据。
        """
        m = self._last_match or {}
        b = self._last_block or {}
        hs = [s['h'] for s in self._samples]
        ws = [s['w'] for s in self._samples]
        return {
            'enrolling': self._enrolling,
            'commits': self._commits,
            'samples': len(self._samples),
            'required': self.commit_min_samples,
            'profiles': len(self.profiles),
            'active_name': self.active.name if self.active is not None else '',
            'match_source': str(m.get('source', '')),
            'match_score': float(m.get('score', 0.0)),
            'match_threshold': float(m.get('threshold', 0.0)),
            'match_comparable': int(m.get('comparable', 0)),
            # -- 建档反馈（2026-09-29）：界面据此回答「为什么还没成」--
            'block_code': str(b.get('code', '')),
            'block_text': str(b.get('text', '')),
            # 窗口内反解值的中位：**建档时就看得见**，不用等提交后才知道
            # 「怎么只有 1.2 m」—— 这正是本次录到一个可疑档案却毫无察觉的根因。
            'height_m': float(np.median(hs)) if hs else 0.0,
            'width_m': float(np.median(ws)) if ws else 0.0,
            'failures': int(self._failures),
            'last_failure': dict(self._last_failure) if self._last_failure else {},
            # 失败后正在等「站位改变」时，这里是非 None 的参照身高（米）
            'await_change': self._await_change,
            'enroll_height_range': tuple(self.enroll_height_m),
            'enroll_width_range': tuple(self.enroll_width_m),
        }

    # -- 每帧入口 ----------------------------------------------------------

    @staticmethod
    def _no_identity() -> dict:
        """「本帧没算过认人」的判定快照（``computed=False``）。"""
        return {'computed': False, 'matched': None, 'score': None, 'raw': None,
                'threshold': None, 'comparable': 0, 'source': ''}

    def frame_identity(self) -> dict:
        """**本帧** ``observe()`` 里真算出来的身份判定（不是 ``active``）。

        字段：``computed`` 本帧是否真算了认人；``matched`` 算出来的那个人
        （``None`` = 谁都没匹配上，与"没算"由 ``computed`` 区分）；
        ``score`` / ``threshold`` / ``comparable`` / ``source`` 与
        ``match_line()`` 同源，便于上层把「为什么拦」说清。

        为什么要单独开一个入口而不复用 ``active``：``active`` 是"最近一次
        算过的结论"，本帧没算时它保留旧值；上层据此拦「不该出数的框」时，
        必须能分辨「算出来不是他」与「本帧根本没算」，否则相机未标定、
        画面里没人这些情形会被误判成"不是追踪目标"而把整屏拦掉。

        职责边界与 ``ranging_width_m()`` 的 ⚠️ 对齐：本模块只给**结论**，
        「该不该出数」由上层决定。
        """
        return dict(self._frame_identity)

    def observe(self, box: dict, frame_rgb, now: float, *,
                capture_ok: bool, distance_m: Optional[float],
                fx: float, fy: float, embedding=None,
                capture_note: str = '') -> None:
        """每帧调用（有 person 检测时）。

        参数
        ----
        capture_ok : 本帧是否满足采样条件（完整可见 + 距离可信 + 静止）。
                     调用方按可见性体检与 RangingResult 决定，这里不重复判断
                     —— 判据与测距同源，避免两处各写一套。
        distance_m : 实际用于反解的真实距离（米）。可以是接触点法解出的，
                     也可以是用户在标定页手填的采样点距离（调用方决定用哪个）。
                     ``capture_ok=True`` 时必须非 None。
        embedding  : 本帧该人的 OSNet 嵌入（512 维、L2 归一），没有就传 ``None``。
                     **由调用方提取**：本模块刻意不 import onnxruntime，
                     保持纯逻辑、可离线单测。传了它，匹配就走嵌入路子。
        capture_note
            ``capture_ok=False`` 时**为什么不合格**的人话说明（调用方最清楚
            是贴边还是距离不可信）。建档会话里会被记进进度快照，界面据此
            告诉用户「该怎么办」而不是让他空等 —— 空字符串表示调用方没提供，
            本模块用一句通用文案兜底。
        """
        hist = torso_appearance(frame_rgb, box)
        # 先复位成「本帧没算」，只有真算了才填 —— 不复位就会把上一帧的结论
        # 当成本帧的，上层据此拦框时会把"没算"读成"不是他"。
        self._frame_identity = self._no_identity()
        if hist is not None or embedding is not None:
            self._match_active(hist, embedding)
            self._feed_cohort(embedding)
            m = self._last_match or {}
            self._frame_identity = {
                'computed': True,
                'matched': self.active,
                'score': m.get('score'),
                'raw': m.get('raw'),
                'threshold': m.get('threshold'),
                'comparable': int(m.get('comparable', 0) or 0),
                'source': m.get('source', ''),
            }

        # 被动路径到此为止：只认人（更新 active），不采样、不落盘。
        # 建档必须由主动会话开启 —— 见类 docstring 的 ⚠️ 说明。
        if not self._enrolling:
            return

        # 以下是建档会话的采样链路。**每个不通过分支都要留下原因** ——
        # 原先全是裸 return，界面上什么都看不到，用户只能站在镜头前空等，
        # 分不清「没采到」「采了但不合格」「程序坏了」（2026-09-29 实录反馈）。
        if not capture_ok or distance_m is None or distance_m <= 0:
            self._note_block('not_ready', capture_note or
                             '目标未完整入画，或本帧距离不可信')
            return
        if fx <= 0 or fy <= 0:
            self._note_block('no_intrinsics', '内参不可用（未标定，或标定文件无效）')
            return

        h_px = float(box.get('height', 0.0))
        w_px = float(box.get('width', 0.0))
        if h_px <= 0 or w_px <= 0:
            self._note_block('bad_box', '检测框尺寸无效')
            return
        if h_px < self.enroll_min_box_h_px:
            self._note_block(
                'box_too_small',
                f'目标太小（框高 {h_px:.0f} px < {self.enroll_min_box_h_px:.0f} px）'
                f'—— 走近一些再站定')
            return
        h_m = distance_m * h_px / fy      # pinhole 反解（同 estimate_target_height）
        # ⚠️ 宽度是**横向**尺寸，投影要用 fx，不是 fy（2026-09-30 修）。
        # 针孔模型：x_img = cx + fx·X/Z、y_img = cy ± fy·Y/Z —— 横纵各用各的
        # 焦距，而近场框跨度法（横）测距用的是 fx（GeometricRanger._distance_from_width）。
        # 原先这里跟高度共用 fy，两边口径不一致：拿这样算出的档案值去测距，会
        # 系统性偏小 fx/fy = 1.4%（方向：以为远、实际近）。数值不大，但方向不
        # 安全，且属于「同一件事两处各写一套」那类该顺手清掉的不一致。
        # 已落盘的旧档案按旧口径（差异 1.4%），不追溯重算。
        w_m = distance_m * w_px / fx
        if not (PLAUSIBLE_HEIGHT_M[0] <= h_m <= PLAUSIBLE_HEIGHT_M[1]):
            self._note_block(
                'implausible_h',
                f'本帧反解身高 {h_m:.2f} m 超出采样范围 '
                f'{PLAUSIBLE_HEIGHT_M[0]:.2f}–{PLAUSIBLE_HEIGHT_M[1]:.2f} m')
            return
        if not (PLAUSIBLE_WIDTH_M[0] <= w_m <= PLAUSIBLE_WIDTH_M[1]):
            self._note_block(
                'implausible_w',
                f'本帧反解肩宽 {w_m:.2f} m 超出采样范围 '
                f'{PLAUSIBLE_WIDTH_M[0]:.2f}–{PLAUSIBLE_WIDTH_M[1]:.2f} m')
            return

        # 上次「失败」之后，先等用户真的改变站位，再开始干净的一次采样。
        # 判据复用 height_cv_max（不新造魔数）：反解身高相对失败时相差超过它，
        # 就认为人换位置了。不设这道闸的话，失败后那几帧旧姿态会与新姿态混在
        # 同一个窗口里，cv 持续超标 -> 界面一直喊「站定别动」（见 __init__ 注释）。
        if self._await_change is not None:
            ref = self._await_change
            if abs(h_m - ref) / max(ref, 1e-6) <= self.height_cv_max:
                self._note_block(
                    'await_change',
                    f'上次失败时的反解身高是 {ref:.2f} m，本帧 {h_m:.2f} m，'
                    f'相差不足 {self.height_cv_max * 100:.0f}% —— '
                    f'换个站位/距离（走近或退后）再站定，旧窗口已经清空')
                return
            # 确实变了 -> 解除等待，之后的帧开始干净的一次
            self._await_change = None

        self._samples.append({'t': now, 'h': h_m, 'w': w_m,
                              'hist': hist, 'emb': embedding})
        self._last_block = {}       # 本帧采样成功 -> 清掉上一帧的阻塞说明
        self._trim(now)
        self._try_commit()

    def _note_block(self, code: str, text: str) -> None:
        """记下「本帧为什么没采样」。逐帧覆盖，采样成功时由调用处清空。

        与 :meth:`_fail_commit` 的区别：这是**阻塞**（当前帧不合格，继续等就有
        可能过），那是**失败**（攒够帧了但结论不合理，用户必须改变什么）。
        界面用两种语气呈现，避免把「继续站着」和「站起来重来」混为一谈。
        """
        self._last_block = {'code': code, 'text': text}

    def _trim(self, now: float) -> None:
        """滚动窗口：只留最近 window_s 秒内的样本。"""
        lo = now - self.window_s
        self._samples = [s for s in self._samples if s['t'] >= lo]

    def _try_commit(self) -> None:
        if len(self._samples) < self.commit_min_samples:
            return
        hs = np.array([s['h'] for s in self._samples])
        cv = hs.std() / max(hs.mean(), 1e-6)
        if cv > self.height_cv_max:
            # 窗口内身高还在抖（走动/遮挡）。这**不是失败**：窗口保留，
            # 站定不动就会过 —— 所以用阻塞语气而不是失败语气。
            self._note_block(
                'unstable',
                f'目标还在动（身高波动 {cv * 100:.0f}% > '
                f'{self.height_cv_max * 100:.0f}%）—— 站定别动，程序在等稳定')
            return

        h_new = float(np.median(hs))
        w_new = float(np.median([s['w'] for s in self._samples]))

        # ---- 落盘前的最后一道闸（2026-09-29 新增）------------------------
        # 为什么必须有：h_new/w_new 写进档案后会**一直**参与近场框跨度法（横）测距
        # （ranging_width_m 取档案里的 width_m）。存错一次，此后每一帧都错，
        # 而且不报错、看起来一切正常。宁可这次建档失败并说清原因。
        # 判据用身高而不是肩宽打头，是因为身高的真实范围有公认区间，
        # 而「检测框宽当肩宽」本身带系统偏差、范围更松、判别力更弱。
        lo, hi = self.enroll_height_m
        if not (lo <= h_new <= hi):
            self._fail_commit(
                'implausible_height',
                f'反解身高 {h_new:.2f} m 不在 {lo:.2f}–{hi:.2f} m 之间'
                f'（本次 {len(self._samples)} 帧窗口）',
                h_ref=h_new)
            return
        lo, hi = self.enroll_width_m
        if not (lo <= w_new <= hi):
            self._fail_commit(
                'implausible_width',
                f'反解肩宽 {w_new:.2f} m 不在 {lo:.2f}–{hi:.2f} m 之间'
                f'（本次 {len(self._samples)} 帧窗口）',
                h_ref=h_new)
            return
        hists = [s['hist'] for s in self._samples if s['hist'] is not None]
        hist_new = None
        if hists:
            hist_new = np.mean(hists, axis=0)
            s = hist_new.sum()
            hist_new = hist_new / s if s > 0 else None

        # 嵌入同理取窗口内平均。平均向量**必须重新 L2 归一化** ——
        # 余弦相似度的前提是两侧都已归一化，省掉这一步会让分数整体偏小、
        # 阈值随之失准（而且不报错）。
        embs = [s['emb'] for s in self._samples if s.get('emb') is not None]
        emb_new = None
        if embs:
            m = np.mean(np.stack([np.asarray(e, dtype=np.float32) for e in embs]), axis=0)
            norm = float(np.linalg.norm(m))
            if norm > 1e-12:
                emb_new = m / norm

        a = self.ema_alpha
        now_str = time.strftime('%Y-%m-%d %H:%M:%S')
        if self.active is not None:
            p = self.active
            if p.height_m <= 0:
                p.height_m, p.width_m = h_new, w_new
            else:
                p.height_m = float((1 - a) * p.height_m + a * h_new)
                p.width_m = float((1 - a) * p.width_m + a * w_new)
            if hist_new is not None:
                if p.appearance:
                    old = np.asarray(p.appearance, dtype=np.float64)
                    merged = (1 - a) * old + a * hist_new
                    p.appearance = merged.tolist()
                else:
                    p.appearance = hist_new.tolist()
            if emb_new is not None:
                if p.embedding:
                    old_e = np.asarray(p.embedding, dtype=np.float32)
                    merged_e = (1 - a) * old_e + a * emb_new
                    norm = float(np.linalg.norm(merged_e))
                    p.embedding = ((merged_e / norm) if norm > 1e-12
                                   else merged_e).tolist()
                else:
                    p.embedding = emb_new.tolist()
                p.emb_model = self.emb_tag
            p.n_updates += 1
            p.updated_at = now_str
        else:
            # 新人：档案满则挤掉更新时间最早的那个（跟随场景最多三五个人）
            if len(self.profiles) >= self.max_profiles:
                self.profiles.sort(key=lambda q: q.updated_at)
                victim = self.profiles.pop(0)
                if self.active is victim:
                    self.active = None
            pid = f'person-{len(self.profiles) + 1}-{int(time.time())}'
            note = f'主动建档：{len(self._samples)} 帧稳定窗口'
            if emb_new is None:
                # 嵌入取不到（模型缺失/框太小）不该让建档失败 —— 几何特征
                # 本身就够近场框跨度法（横）用，只是匹配能力退回 HSV 那一路。
                note += '（无嵌入，仅几何 + 直方图）'
            p = PersonProfile(profile_id=pid, height_m=h_new, width_m=w_new,
                              appearance=hist_new.tolist() if hist_new is not None else [],
                              embedding=emb_new.tolist() if emb_new is not None else [],
                              n_updates=1, updated_at=now_str,
                              source=note,
                              enroll_source='manual',
                              enrolled_at=now_str,
                              emb_model=self.emb_tag if emb_new is not None else '')
            self.profiles.append(p)
            self.active = p
        self._samples = []
        self._last_block = {}           # 提交成功 -> 清掉阻塞说明
        self._dirty = True
        # 提交次数只增不减、跨会话累计。UI 记住上次的值，变大才播报一次
        # —— 这样「提示音」不会随刷新重复响，也不需要额外的状态通道。
        self._commits += 1
        # 建档是用户明确的动作，**立刻落盘**：等下一个动作才写的话，
        # 中途关程序就把刚建的档丢了（而用户以为已经建好了）。
        self.save()

    def _fail_commit(self, code: str, text: str, h_ref: float = None) -> None:
        """建档复核不通过：**不写档案**，记一次失败供界面播报，并清空窗口。

        为什么清空窗口：不清的话下一个 tick 会拿着同一批数据再失败一次，
        每秒刷几十遍提示音 —— 用户会以为程序卡死了。清空后要重新攒够帧
        才会再判，也就自然把提示降频成「每尝试一次说一次」。

        ``seq`` 是给界面用的：它按序号去重，保证同一批数据只播报一次。

        ``h_ref`` 是失败时窗口的反解身高中位。它被记进 ``_await_change``：
        此后**反解身高与它相差不超过 ``height_cv_max`` 的帧一律只阻塞、不采样**
        —— 否则用户改好姿势前那几帧旧姿态会和新姿态混进同一个窗口，
        让界面在用户已经站对之后还继续喊「站定别动」。
        """
        self._samples = []
        self._failures += 1
        self._last_failure = {
            'seq': self._failures,
            'code': code,
            'text': text,
            'at': time.strftime('%H:%M:%S'),
        }
        self._await_change = float(h_ref) if h_ref else None
        self._last_block = {}           # 失败已单独播报，阻塞说明让位

    def _match_active(self, hist, embedding=None) -> None:
        """决定「现在画面里的人是档案里的谁」。

        **优先用 OSNet 嵌入**（判别力**未经异人样本验证**，见
        ``PersonProfile.embedding_similarity`` 的 ⚠️）；嵌入不可用时**回落**
        HSV 直方图 —— 回落不是"降级凑合"，而是保证「模型缺失时行为仍可解释」。

        匹配不上必须**清空 active**：画面里可能是没建档的新人。若不清空，
        下一次稳定窗口提交会把新人的身高/肩宽 EMA 进旧人的档案
        （框跨度法（横）从此用错肩宽），这是 verify_person_model C2 抓出的真 bug。
        框跨度法（横）随之回退默认肩宽，等新人自己的档案建立后自动恢复。

        每次匹配都把「用了哪条路、分数多少、门槛多少、有几条可比档案」记进
        ``self._last_match`` —— 阈值未校准期间，这是唯一能让人判断
        「到底是认不出，还是门槛定错了」的依据（UI 会显示它）。
        """
        if embedding is not None:
            best, best_sim, comparable = None, 0.0, 0
            for p in self.profiles:
                # 跨模型不可比：换过嵌入模型后，旧档案里的向量与当前向量不同源，
                # 余弦值毫无意义且**不会报错** —— 直接跳过，比出个数更危险。
                if not p.embedding or p.emb_model != self.emb_tag:
                    continue
                comparable += 1
                sim = p.embedding_similarity(embedding)
                if sim > best_sim:
                    best, best_sim = p, sim
            # ⚠️ 没有可比档案时 raw 必须是 ``None``，**不能是 0.0**：
            # 0.0 在路人池里是"远不像目标"，会被准入（0.0 < admit_below），
            # 于是**还没建档时期的目标本人**被收进池，之后拿他自己的分数
            # 减他自己。这是接线层特有的陷阱 —— reid_cohort 内部的准入防护
            # 只认 ``None``（它无从知道"0.0 是因为无从判断还是真的不像"）。
            raw = best_sim if comparable > 0 else None
            offset = None
            if self.cohort_enabled and raw is not None:
                offset = self._cohort.offset(embedding)
            if raw is None:
                score = 0.0
            elif offset is not None:
                score = normalize_score(raw, offset)
            else:
                score = raw
            self.active = (best if (best is not None
                                    and score >= self.emb_match_threshold)
                           else None)
            self._last_match = {
                'source': 'embedding', 'score': round(score, 4),
                'raw': (round(raw, 4) if raw is not None else None),
                'offset': (round(offset, 4) if offset is not None else None),
                'cohort_enabled': self.cohort_enabled,
                'cohort_size': len(self._cohort),
                'threshold': self.emb_match_threshold,
                'comparable': comparable,
            }
            return

        best, best_sim = None, 0.0
        for p in self.profiles:
            sim = p.similarity(hist)
            if sim > best_sim:
                best, best_sim = p, sim
        self.active = (best if (best is not None
                                and best_sim >= self.match_threshold) else None)
        self._last_match = {
            'source': 'hist', 'score': round(best_sim, 4),
            'threshold': self.match_threshold,
            'comparable': sum(1 for p in self.profiles if p.appearance),
        }

    def _feed_cohort(self, embedding) -> None:
        """把本帧嵌入喂给路人池。**必须在 ``_match_active`` 之后调用** ——
        准入要用的 ``raw`` 是刚算出来的「与档案库最高相似度」。

        三条早退，每条都有实际理由：
        - 开关关（默认）：零开销，不产生任何池状态；
        - 没有嵌入：池的统计量只对嵌入路子有意义，HSV 那路的分数不可比；
        - ``raw is None``（库为空 / 无可比档案）：**无法判断**这一帧像不像
          目标，此时入池会把目标本人收进来（见 ``_match_active`` 的 ⚠️）。
        """
        if not self.cohort_enabled or embedding is None:
            return
        raw = self._last_match.get('raw')
        if raw is None:
            return
        self._cohort.observe(embedding, raw, model_tag=self.emb_tag)

    # -- 追踪目标（CHARTER v1.4「建档 + 追踪目标选择」，单选）----------------

    def track_target(self) -> Optional[PersonProfile]:
        """当前被指定的追踪目标。全库最多一条；没指定返回 ``None``。"""
        for p in self.profiles:
            if p.is_track_target:
                return p
        return None

    def set_track_target(self, profile_id: str) -> Optional[PersonProfile]:
        """把追踪目标切换为 ``profile_id``（**单选**：其余一律清零），并落盘。

        传空串 = 取消指定。``profile_id`` 不在库里时**什么都不改并返回 None**
        —— 宁可不动作，也不留下两条 ``is_track_target``（那会让「追谁」变成
        不确定，与 CHARTER 的「行为确定性」相悖）。
        """
        hit = None
        if profile_id:
            for p in self.profiles:
                if p.profile_id == profile_id:
                    hit = p
                    break
            if hit is None:
                return None
        for p in self.profiles:
            p.is_track_target = (p is hit)
        self._dirty = True
        self.save()
        return hit

    def rename_profile(self, profile_id: str, new_name: str) -> bool:
        """改指纹的显示名（用户可改）。去首尾空白；全空白 = 清回未命名。落盘。"""
        for p in self.profiles:
            if p.profile_id == profile_id:
                p.display_name = (new_name or '').strip()
                self._dirty = True
                self.save()
                return True
        return False

    def delete_profile(self, profile_id: str) -> bool:
        """删除一条档案并**立刻落盘**。找不到返回 ``False``，什么都不改。

        为什么要清 ``active``：它可能正指向被删的那条。留着会让后续
        ``ranging_width_m()`` 从一个已不在库里的对象取肩宽 —— 界面看着
        「没目标了」，测距却还在用一个被删的人的数，属于最难查的那类不一致。

        删除是破坏性动作，所以这里直接 ``save()`` 而不是只置 ``_dirty``：
        用户点了删就是删，不能等到下次别的动作才写盘。
        """
        for i, p in enumerate(self.profiles):
            if p.profile_id == profile_id:
                if self.active is p:
                    self.active = None
                self.profiles.pop(i)
                self._dirty = True
                self.save()
                return True
        return False

    def profile_label(self, p: PersonProfile) -> str:
        """下拉框里的一行文字。来源标记放在这里 —— 用户要能一眼看出
        「这条是事先登记的」还是「追踪时被动攒出来的」，两者可信度不同。"""
        origin = '已建档' if p.is_enrolled else '自动'
        return f'{p.name}（{origin}）'

    def profile_tooltip(self, p: PersonProfile) -> str:
        """悬停说明：把「凭什么信这条档案」讲清楚。"""
        upd = p.updated_at or '—'
        n = f'{p.n_updates} 个稳定窗口' if p.n_updates else '尚未量到稳定值'
        if p.is_enrolled:
            origin = f'事先建档于 {p.enrolled_at or "—"}'
        else:
            origin = f'追踪时自动建档（{p.source or "—"}）'
        return (f'{p.name}\n档案 ID：{p.profile_id}\n{origin}\n'
                f'身高 {p.height_m:.2f} m ／肩宽 {p.width_m:.2f} m\n'
                f'样本：{n}，最近更新 {upd}')

    # -- 查询 --------------------------------------------------------------

    def current_width_m(self, default: float) -> float:
        """「本帧匹配到的那个人」的档案肩宽，没有则 ``default``。

        ⚠️ **不参与测距**（2026-09-30 起）。测距取谁的肩宽只走
        ``ranging_width_m()`` —— 那里只认「指定的追踪目标」。
        本方法保留给 UI/诊断回答「本帧匹配上了谁、他肩宽多少」，
        不要再把它接回测距链路：那会让近场读数随画面里恰好匹配上的人漂移。
        """
        if self.active is not None and self.active.width_m > 0:
            return float(self.active.width_m)
        return default

    def ranging_width_m(self, default: float) -> float:
        """**测距实际取用**的肩宽（CHARTER v1.4「追踪目标选择」的生效点）。

        指定了追踪目标 -> **恒用该目标档案里的肩宽**。这正是建档的意义：
        用「这个人自己的肩宽」去测，而不是猜 0.46 m、也不是用画面里恰好
        匹配上的别人 —— 后者会让近场读数随路人漂移。

        未指定追踪目标 -> 用 ``default``（全局默认 0.46 m）。
        目标档案还没量到肩宽（``width_m <= 0``）-> **同样用 ``default``**，
        绝不借用画面里别人的档案值。

        ⚠️ 2026-09-30 语义收紧（用户要求：「有追踪目标的时候用目标的肩宽，
        没有的时候就不用动」）：
        · 旧实现后两种情形回落到 ``current_width_m()``，即「本帧外观匹配到
          的那个人」的档案值 —— 等于「画面里有人跟档案对得上就用他的肩宽」，
          不管他是不是你要追的那个人。没指定目标时画面里是谁本来就不确定，
          拿一个来路不明的人的肩宽去测距，会把「换人了」变成「距离漂了」，
          而且不报错，属于最难查的那类不一致；换目标时更会串成上一个人的。
        · 现在**只认「指定的追踪目标」这一条来源**，其余一律用默认值。
          代价是「没指定目标时不享受档案精度」，换来的是确定性。

        ⚠️ 职责边界：本函数只管**取谁的肩宽**。当前帧里的目标是不是追踪
        目标本人、该不该出数，属**匹配分级**（CHARTER「范围内的」第 4 条）
        的判定，由上层负责，不在这里拦。
        """
        target = self.track_target()
        if target is not None and target.width_m > 0:
            return float(target.width_m)
        return float(default)

    def current_summary(self) -> str:
        """给状态栏/UI 的一句话总结（有没有量到人、量到了什么）。"""
        target = self.track_target()
        if target is not None:
            if self.active is target:
                return (f'追踪目标：{target.name}（本帧已认出）身高 '
                        f'{target.height_m:.2f} m / 肩宽 {target.width_m:.2f} m')
            if self.active is not None:
                return (f'追踪目标：{target.name}（本帧未认出，画面里是'
                        f'{self.active.name}）')
            return f'追踪目标：{target.name}（本帧未匹配到）'
        if self.active is None:
            if self._samples:
                return (f'正在建档（{len(self._samples)}/'
                        f'{self.commit_min_samples} 帧）……让目标完整入画并站定')
            return ('人员特征：暂无档案 —— 到「标定」页走 ③ 指纹建档'
                    '（本程序不会自动建档）')
        p = self.active
        return (f'人员特征：{p.name} 身高 {p.height_m:.2f} m / '
                f'肩宽 {p.width_m:.2f} m（{p.n_updates} 次窗口更新）'
                f'｜未指定追踪目标')

    def match_line(self) -> str:
        """最近一次匹配的一行说明（路线 + 分数 + 门槛 + 可比档案数 + 路人池）。

        **阈值未校准期间这是必需的**：只报「未认出」会让人以为是特征不行，
        把分数和门槛一起摆出来，才能分辨「分数低」还是「门槛定错」。

        开了路人池归一化时，**原始分数与偏移量都要摆出来** —— 归一化生效会
        让显示的分数不再等于「嵌入本身的相似度」，只报一个数就分不清
        「像得不够」还是「被池吃掉了」。
        """
        m = self._last_match or {}
        if not m:
            return '匹配：本帧未计算'
        src = '嵌入(余弦)' if m.get('source') == 'embedding' else '直方图(L1)'
        if int(m.get('comparable', 0)) == 0:
            return f'匹配：{src} —— 库里 {len(self.profiles)} 条档案，无一条可比'
        line = (f'匹配：{src} {m.get("score", 0.0):.3f} / 门槛 '
                f'{m.get("threshold", 0.0):.3f}（可比档案 '
                f'{m.get("comparable", 0)} 条）')
        if m.get('cohort_enabled'):
            off = m.get('offset')
            size = int(m.get('cohort_size', 0))
            if off is None:
                line += f'｜路人池 {size} 条未够，未归一化'
            else:
                raw = m.get('raw')
                tail = f'｜路人池 {size} 条 偏移 {off:.3f}'
                if raw is not None:
                    tail += f'（原始 {raw:.3f}）'
                # ⚠️ 归一化生效后判定口径变了：门槛仍是**原始口径**的 0.50，
                # 拿归一化分数去比它，等价于把实际门槛抬到 0.50+偏移。
                # 这必须明说 —— 否则「原始 0.58 明明过了 0.50 却判不通过」
                # 会被当成 bug 去查。
                tail += '｜门槛为原始口径，未按偏移重标定'
                line += tail
        return line

    def cohort_line(self) -> str:
        """路人池状态一行（给 UI 常显）。关的时候**明确说关**，不留空白 ——
        否则「没显示」会被读成「池是空的」。"""
        if not self.cohort_enabled:
            return '路人池：未启用（cohort 归一化默认关）'
        return self._cohort.line()


# ---------------------------------------------------------------------------
# 速度门控：人不可能瞬移
# ---------------------------------------------------------------------------

@dataclass
class GateVerdict:
    """一次门控裁决。``ok=False`` 时这个距离值必须拦下（显示原因，不给数）。"""

    ok: bool = True
    reason: str = ''            # 拦截原因 / 重新锚定说明（给 UI 原因行用）


class SpeedGate:
    """相邻读数隐含速度超过人体极限 -> 拦下。**拦的是跳变错值，不是拦人**。

    物理依据：人冲刺极限 ~10 m/s（博尔特 44 km/h 瞬时），日常场景取
    8 m/s 留余量。1.5 m -> 10 m 的跳变隐含速度远超此值 —— 只可能是检测跳帧、
    框抓错（把背景物框成目标）、类别误识别，恰好都是**自信错值**的来源。
    这正是 ``monocular-ranging-guard`` 的核心原则：错误数字比没有数字危险。

    两个必要的「逃生门」，防止门控把真变化也永远拦死：

    1. **丢失重锚**：目标消失超 ``lost_reset_s``（默认 2 s）后，下一个读数
       无条件接受为新锚点 —— 人可能真的走了、换了一个人进来；
    2. **连续一致重锚**：被拦的值若连续 ``rebaseline_min`` 帧互相一致
       （±15% 带内），说明画面里换了一段连续的新轨迹（新人入画、或之前的
       锚点本身是错的）—— 接受它作为新锚点，并提示 UI。

    ⚠️ 单目标假设：跟随场景同一时间只跟一个主目标（置信度最高的框）。
    多目标切换会被「连续一致重锚」接住，代价是最多 3 帧的延迟。
    """

    def __init__(self, *, v_max_mps: float = 8.0,
                 lost_reset_s: float = 2.0,
                 rebaseline_min: int = 3,
                 rebaseline_band: float = 0.15,
                 min_dt_s: float = 1e-3):
        self.v_max = float(v_max_mps)
        self.lost_reset_s = float(lost_reset_s)
        self.rebaseline_min = int(rebaseline_min)
        self.rebaseline_band = float(rebaseline_band)
        self.min_dt_s = float(min_dt_s)

        self._last_d: Optional[float] = None
        self._last_t: Optional[float] = None
        self._pending: list[float] = []    # 被拦的连续候选值

    def reset(self) -> None:
        self._last_d = None
        self._last_t = None
        self._pending = []

    def miss(self, now: float) -> None:
        """本帧没有可信读数（没检测到 / 不可测）。只推进「丢失计时」。"""
        if self._last_t is not None and now - self._last_t > self.lost_reset_s:
            self.reset()

    def check(self, distance: float, now: float) -> GateVerdict:
        """裁决一个新读数。注意 ``now`` 必须单调（``time.monotonic()``）。"""
        if self._last_d is None or self._last_t is None:
            self._last_d, self._last_t = float(distance), now
            self._pending = []
            return GateVerdict()

        dt = now - self._last_t
        if dt < self.min_dt_s:
            dt = self.min_dt_s
        if dt > self.lost_reset_s:
            # 目标丢失太久：新读数无条件当新锚点
            self._last_d, self._last_t = float(distance), now
            self._pending = []
            return GateVerdict(reason=f'目标丢失 {dt:.1f} s，距离已重新锚定')

        speed = abs(distance - self._last_d) / dt
        if speed <= self.v_max:
            self._last_d, self._last_t = float(distance), now
            self._pending = []
            return GateVerdict()

        # ---- 拦截：先看是否构成「连续一致的新轨迹」 ----
        # 「互相一致」= 尾部候选值的极差相对最大值不超过 ±15% 带
        # （例 [10.0,10.2,10.1] 一致；[6,12,15] 极差占 60%，不一致）。
        self._pending.append(float(distance))
        tail = self._pending[-self.rebaseline_min:]
        if (len(tail) >= self.rebaseline_min
                and (max(tail) - min(tail)) / max(tail) <= self.rebaseline_band):
            new_d = float(np.median(tail))
            self._last_d, self._last_t = new_d, now
            self._pending = []
            return GateVerdict(
                reason=(f'连续 {len(tail)} 帧一致，已接受新距离段 '
                        f'{new_d:.2f} m（画面里可能是另一个目标）'))

        # 拦下这个值，但**时间基准必须推进**：否则 dt 会随时间累积，
        # 走到 0.5 s 后随便多远的跳变都满足速度门槛，门控形同虚设。
        self._last_t = now
        return GateVerdict(
            ok=False,
            reason=(f'速度门控拦截：{dt:.2f} s 内 {self._last_d:.2f}→'
                    f'{distance:.2f} m（隐含 {speed:.0f} m/s，'
                    f'超过人体极限 {self.v_max:.0f} m/s，多半是检测跳变/抓错框）'))
