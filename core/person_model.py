"""人员特征档案与速度门控 —— 近场「宽度法」的两大支柱。

定位对应：`CHARTER.md`「范围内的」第 2 条几何测距的近场扩展。
设计讨论与用户决策见 2026-09-25 笔记（P1+ 方案）。

为什么需要这个模块
------------------
接触点法的几何下限（当前机位 1.85 m）以内，脚不在画面里，两条几何法都无解。
但近场恰恰是农业车跟随/避障最需要的区间。用户定的 P1+ 方案用三个纯软件手段
把盲区降级成「参考值」而不是「不可测」：

1. **宽度法兜底**（配合 ``core/calibration.GeometricRanger``）：
   脚出画、左右未裁时 ``Z = fx * W_真实 / 框宽``。其中 W_真实 不再拍脑袋填
   0.46 m，而是 ——
2. **人特征档案**：目标完整可见、接触点法出数的帧里顺手量出这个人的
   真实身高/肩宽（``W = D * 框宽px / fy``），滚动窗口取中位数、稳定后提交，
   之后宽度法用的就是「这个人自己的肩宽」。多个人靠外观直方图区分。
3. **速度门控**：人不可能瞬移。相邻两帧的距离变化隐含速度，超过人体极限
   （默认 8 m/s，博尔特冲刺也就 ~10 m/s）的一律拦下 —— 拦的是**跳变错值**，
   不是拦人。

三个组件都是**纯逻辑**（不碰 Qt、不碰线程），与 ``core/calibration`` 同风格，
可离线单测（``E:\\WorkBuddy-Work\\scripts\\verify_person_model.py``）。

⚠️ 精度声明：宽度法天生只有「参考级」（±15% 起步）。侧身时肩深 ~0.25 m
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

PERSON_PROFILE_VERSION = 1

# 采样合理性区间：身高/肩宽反解值落在外面说明这一帧有毛病（遮挡、非站姿、
# 类别误识别），直接丢样本 —— 绝不把离群值往档案里记。
PLAUSIBLE_HEIGHT_M = (0.90, 2.40)
PLAUSIBLE_WIDTH_M = (0.15, 1.00)


@dataclass
class PersonProfile:
    """一个人的可测特征：身高、肩宽、外观。

    「凭什么信这个数」：``n_updates`` 是提交进档案的**稳定窗口数**（每窗口
    ≥12 帧、CV≤5%），``updated_at`` 记最后一次提交时间 —— 排查时能回答
    「这个肩宽是什么时候、从多少帧里量出来的」。
    """

    profile_id: str = 'person-1'
    height_m: float = 0.0        # 真实身高（米），接触点法距离 × 框高px / fy
    width_m: float = 0.0         # 真实肩宽（米），接触点法距离 × 框宽px / fy
    appearance: list = field(default_factory=list)   # 512 维直方图（JSON 可存）
    n_updates: int = 0           # 提交次数（每次一个稳定窗口）
    updated_at: str = ''
    source: str = ''             # 样板来源说明（首次创建时记）

    def similarity(self, hist) -> float:
        if not self.appearance or hist is None:
            return 0.0
        return appearance_similarity(np.asarray(self.appearance, dtype=np.float64),
                                     np.asarray(hist, dtype=np.float64))


class PersonFeatureTracker:
    """从「完整可见且测距可信」的帧里持续量人，滚动窗口稳定后提交档案。

    工作流（每帧最多三件事，全部 <1 ms 量级）::

        tracker.observe(box, frame_rgb, now,
                        capture_ok=…, distance_m=…, fx=…, fy=…)

    1. 算外观直方图 -> 与已有档案匹配 -> 决定「当前是哪个人」（active）；
    2. ``capture_ok``（目标完整 + 接触点法可信，由调用方按可见性体检决定）
       时把 (身高, 肩宽, 外观) 存进滚动缓冲；
    3. 缓冲里攒够一个**静止稳定**的窗口（≥12 帧、身高 CV ≤5%）就提交 ——
       匹配上的人用 EMA 更新，匹配不上就新建档案（上限 5 个，挤掉最旧的）。

    为什么「稳定窗口」而不是逐帧 EMA：人在走动时框宽/框高本来就会抖，
    逐帧更新会把走姿的抖动永远洗进档案里。窗口 + CV 门槛等价于
    「让目标先站定一秒再量」—— 与安装参数自标定采样用同一套纪律
    （散布过大就拒收，不记脏点）。
    """

    JSON_VERSION = PERSON_PROFILE_VERSION

    def __init__(self, json_path: str, *,
                 max_profiles: int = 5,
                 match_threshold: float = 0.55,
                 commit_min_samples: int = 12,
                 window_s: float = 3.0,
                 height_cv_max: float = 0.05,
                 ema_alpha: float = 0.30):
        self.json_path = json_path
        self.max_profiles = max_profiles
        self.match_threshold = match_threshold
        self.commit_min_samples = commit_min_samples
        self.window_s = window_s
        self.height_cv_max = height_cv_max
        self.ema_alpha = ema_alpha

        self.profiles: list[PersonProfile] = []
        self.active: Optional[PersonProfile] = None
        self._samples: list[dict] = []      # {t, h, w, hist}
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
                    height_m=float(p.get('height_m', 0.0)),
                    width_m=float(p.get('width_m', 0.0)),
                    appearance=list(p.get('appearance', [])),
                    n_updates=int(p.get('n_updates', 0)),
                    updated_at=str(p.get('updated_at', '')),
                    source=str(p.get('source', '')),
                ))
            self.profiles = profiles
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

    # -- 每帧入口 ----------------------------------------------------------

    def observe(self, box: dict, frame_rgb, now: float, *,
                capture_ok: bool, distance_m: Optional[float],
                fx: float, fy: float) -> None:
        """每帧调用（有 person 检测时）。

        参数
        ----
        capture_ok : 本帧是否满足采样条件（完整可见 + 接触点法可信 + 静止）。
                     调用方按可见性体检与 RangingResult 决定，这里不重复判断
                     —— 判据与测距同源，避免两处各写一套。
        distance_m : 接触点法解出的距离（capture_ok=True 时必须非 None）。
        """
        hist = torso_appearance(frame_rgb, box)
        if hist is not None:
            self._match_active(hist)

        if not capture_ok or distance_m is None or distance_m <= 0:
            return
        if fx <= 0 or fy <= 0:
            return

        h_px = float(box.get('height', 0.0))
        w_px = float(box.get('width', 0.0))
        if h_px <= 0 or w_px <= 0:
            return
        h_m = distance_m * h_px / fy      # pinhole 反解（同 estimate_target_height）
        w_m = distance_m * w_px / fy      # 肩宽同理（见模块 docstring 的精度声明）
        if not (PLAUSIBLE_HEIGHT_M[0] <= h_m <= PLAUSIBLE_HEIGHT_M[1]):
            return
        if not (PLAUSIBLE_WIDTH_M[0] <= w_m <= PLAUSIBLE_WIDTH_M[1]):
            return

        self._samples.append({'t': now, 'h': h_m, 'w': w_m, 'hist': hist})
        self._trim(now)
        self._try_commit()

    def _trim(self, now: float) -> None:
        """滚动窗口：只留最近 window_s 秒内的样本。"""
        lo = now - self.window_s
        self._samples = [s for s in self._samples if s['t'] >= lo]

    def _try_commit(self) -> None:
        if len(self._samples) < self.commit_min_samples:
            return
        hs = np.array([s['h'] for s in self._samples])
        if hs.std() / max(hs.mean(), 1e-6) > self.height_cv_max:
            return                      # 窗口内身高还在抖（走动/遮挡），不提交

        h_new = float(np.median(hs))
        w_new = float(np.median([s['w'] for s in self._samples]))
        hists = [s['hist'] for s in self._samples if s['hist'] is not None]
        hist_new = None
        if hists:
            hist_new = np.mean(hists, axis=0)
            s = hist_new.sum()
            hist_new = hist_new / s if s > 0 else None

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
            p = PersonProfile(profile_id=pid, height_m=h_new, width_m=w_new,
                              appearance=hist_new.tolist() if hist_new is not None else [],
                              n_updates=1, updated_at=now_str,
                              source=f'{len(self._samples)} 帧稳定窗口自动提交')
            self.profiles.append(p)
            self.active = p
        self._samples = []
        self._dirty = True
        self.save()

    def _match_active(self, hist) -> None:
        """用外观直方图决定「现在画面里的人是档案里的谁」。

        匹配不上必须**清空 active**：画面里可能是没建档的新人。若不清空，
        下一次稳定窗口提交会把新人的身高/肩宽 EMA 进旧人的档案
        （宽度法从此用错肩宽），这是 verify_person_model C2 抓出的真 bug。
        宽度法随之回退默认肩宽，等新人自己的档案建立后自动恢复。
        """
        best, best_sim = None, 0.0
        for p in self.profiles:
            sim = p.similarity(hist)
            if sim > best_sim:
                best, best_sim = p, sim
        if best is not None and best_sim >= self.match_threshold:
            self.active = best
        else:
            self.active = None

    # -- 查询 --------------------------------------------------------------

    def current_width_m(self, default: float) -> float:
        """宽度法该用的肩宽：当前匹配到的人的档案值，否则默认值。"""
        if self.active is not None and self.active.width_m > 0:
            return float(self.active.width_m)
        return default

    def current_summary(self) -> str:
        """给状态栏/UI 的一句话总结（有没有量到人、量到了什么）。"""
        if self.active is None:
            if self._samples:
                return (f'正在建档（{len(self._samples)}/'
                        f'{self.commit_min_samples} 帧）……让目标完整入画并站定')
            return '人员特征：暂无档案（让目标完整入画站定约 1 秒即可建档）'
        p = self.active
        return (f'人员特征：{p.profile_id} 身高 {p.height_m:.2f} m / '
                f'肩宽 {p.width_m:.2f} m（{p.n_updates} 次窗口更新）')


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
