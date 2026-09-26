"""TTC 碰撞预警（离线优先）—— 基于距离变化率的碰撞时间估算与分级提示。

定位对应：`CHARTER.md`「范围内的」第 5 条（TTC 碰撞预警）。
本模块是**纯逻辑**（不碰 Qt、不碰线程），与 ``core/calibration``、
``core/person_model`` 同风格，可离线单测、可离线跑录制回放。

CHARTER 的原话是三个硬性要求，本模块逐一兑现
------------------------------------------------
1. **基于距离变化率**：TTC = 当前距离 / 接近速率。接近速率不是拿相邻
   两帧一减了事（单帧差分对测距噪声极其敏感，一帧抖动能把速度翻倍），
   而是**滑动窗口最小二乘拟合**距离-时间斜率 + **离群样本迭代剔除**：
   窗口默认 1.2 s，既压得住帧级噪声，又不至于把真实的加减速抹平；
   剔除逻辑见 ``TTCConfig.outlier_*`` 的注释（实测依据：近场方法切换
   会让距离序列在真值与假值间振荡）。
2. **分级提示**：四级，阈值各有依据（见 ``TTCLevel`` 注释）。
3. **目标关联用「IOU>0.3 + 类别一致」的单目标帧间守卫**：
   相邻两帧的检测框 IOU 低于门槛、或类别变了、或目标丢失超过
   ``max_gap_s`` —— 一律视为"不是同一个目标"，速度估计暂停重置。
   拦的是**关联错**（框跳到别人身上、检测闪断），不是拦目标本身。

离线优先（CHARTER 明确的顺序）
------------------------------
数据轨（frames.jsonl）已逐帧存距离与时间戳，无抖动、可反复验证。
所以第一站是 ``analyze_recording()``：拿一个录制会话目录离线算出
逐帧 TTC 序列。实时接入（主链路每帧喂给 ``TTCEstimator``）是随后
的事，届时 UI 层不需要新逻辑，只是把同一套类的输出画上去。

⚠️ 精度声明：TTC 的分母是接近速率、分子是距离，两者都带测距误差。
近场（接触点法几何下限以内）的距离是「参考级」（±15% 起步，见
person_model 模块注释），所以那里算出的 TTC 也只能是参考级——
``TTCResult.is_reference`` 会如实标记，绝不冒充精确值。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class TTCConfig:
    """TTC 估算的全部可调参数。集中放一处，方便回归测试锁参数。"""

    # -- 速度估计 ------------------------------------------------------------
    window_s: float = 1.2          # 滑动窗口长度（秒）。~4.7FPS 数据轨下约 5-6 个点
    min_points: int = 4            # 拟合前至少几个样本。注意不是 3：3 点会被最小
                                     # 二乘**完美**拟合（残差全零），离群剔除完全失效，
                                     # 一个假值就能把速度带偏（实测振荡序列里出现过
                                     # 真值 0.27 m/s 被拟成 1.18 m/s）。4 点起残差才
                                     # 有意义；剔除后允许降到 3 点出数。
    fit_floor: int = 3             # 剔除离群后至少剩几个点才肯出斜率
    min_closing_speed: float = 0.2  # 低于此接近速率（m/s）不算"在接近"，不产 TTC。
                                     # 取值依据：① 实测远场帧级测距抖动仅 ±0.05~0.08m
                                     # （2m 站定段 1.93~2.01），1.2s 窗口折算斜率噪声
                                     # std <0.05 m/s，0.2 是 4σ 以上，站定不会误报；
                                     # ② 真实慢走实测 0.27 m/s（19:45 录制走回段），
                                     # 门槛必须低于它才能抓到慢速接近。
    max_gap_s: float = 0.8         # 目标丢失超过该时长（秒）→ 窗口清空重来。
                                     # ~5FPS 下一帧间隔 ~0.2s，0.8s = 连丢 4 帧才判断连。

    # -- 离群样本剔除 ---------------------------------------------------------
    # 实测发现：近场走动时距离序列会在「宽度法参考值」与「漏网的接触点法假值」
    # 之间振荡（19:45 录制走回段 1.33↔1.95，帧间斜率高达 3.9 m/s）。
    # 拟合前迭代剔除残差超限的样本；本帧自身被剔除时不出 TTC（诚实原则：
    # 一个离群的测距帧不该冒充有效的碰撞时间）。
    outlier_abs_tol: float = 0.15   # 残差绝对下限（米）：实测真抖动 ±0.05~0.08m
                                     # 的约 2 倍。0.25 太宽——实测振荡序列里残差
                                     # +0.17 的假值会漏网并把速度从 0.27 拟到 0.49。
    outlier_rel_frac: float = 0.08  # 残差相对部分：max(0.15, 0.08×窗口中位距离)。
                                     # 远场框大、噪声绝对值大，纯绝对阈值会误杀。
                                     # 12% 实测给多了（近场 1.57m 中位→0.19，
                                     # 假值残差 0.17 恰好漏网）；8% 时近场由绝对
                                     # 下限 0.15 兜底，10m 远场仍有 0.8m 余量。

    # -- 目标关联守卫（CHARTER 原文要求）--------------------------------------
    iou_gate: float = 0.3          # 相邻帧框 IOU 门槛（CHARTER：IOU>0.3）
    require_same_class: bool = True  # CHARTER：类别一致

    # -- 分级阈值（秒）-------------------------------------------------------
    ttc_caution: float = 4.0       # ≤4.0s：提示（开始进入"值得关注"区间）
    ttc_warning: float = 2.5        # ≤2.5s：预警（Euro NCAP FCW 阈值量级）
    ttc_critical: float = 1.2       # ≤1.2s：危险（步行 1.5m/s 下约 1.8m，
                                   #   恰是近场兜底区，给兜底区一个明确的"危险"语义）

    # -- 参考级标记 ----------------------------------------------------------
    reference_below_m: float = 2.0  # 距离低于此（米）视为近场参考值区，
                                    # 对应 README「精确区 ≥约2.0m」口径


# ---------------------------------------------------------------------------
# 分级
# ---------------------------------------------------------------------------

class TTCLevel(Enum):
    """TTC 分级。``NONE`` 表示"无提示"，用 None 语义但保留枚举可显示。"""

    NONE = '无'          # >4s 或目标未在接近 —— 正常
    CAUTION = '提示'     # ≤4.0s —— 距离在缩短，留意
    WARNING = '预警'     # ≤2.5s —— 接近速率不掉就要撞了
    CRITICAL = '危险'    # ≤1.2s —— 需要立刻动作

    @property
    def rank(self) -> int:
        return {TTCLevel.NONE: 0, TTCLevel.CAUTION: 1,
                TTCLevel.WARNING: 2, TTCLevel.CRITICAL: 3}[self]


def classify_ttc(ttc: Optional[float], cfg: TTCConfig) -> TTCLevel:
    """把 TTC 数值映射到分级。``None``（不可算/未接近）→ NONE。"""
    if ttc is None or not math.isfinite(ttc):
        return TTCLevel.NONE
    if ttc <= cfg.ttc_critical:
        return TTCLevel.CRITICAL
    if ttc <= cfg.ttc_warning:
        return TTCLevel.WARNING
    if ttc <= cfg.ttc_caution:
        return TTCLevel.CAUTION
    return TTCLevel.NONE


# ---------------------------------------------------------------------------
# 结果
# ---------------------------------------------------------------------------

@dataclass
class TTCResult:
    """单帧的 TTC 估算结果。``available=False`` 表示本帧不出 TTC。"""

    t: float = 0.0                      # 帧时间戳（相对录制开始的秒）
    ttc: Optional[float] = None         # 碰撞时间（秒），None = 不可算/未接近
    level: TTCLevel = TTCLevel.NONE
    closing_speed: Optional[float] = None  # 接近速率（m/s），正数=在接近
    available: bool = False             # 本帧是否给出了有效 TTC
    is_reference: bool = False          # True = 分子/分母来自近场参考值区
    reason: str = ''                    # 不可算时给原因，UI/离线报告可直接用


# ---------------------------------------------------------------------------
# 目标关联守卫
# ---------------------------------------------------------------------------

def iou_xywh(a: Tuple[float, float, float, float],
             b: Tuple[float, float, float, float]) -> float:
    """两个 (x中心, y中心, 宽, 高) 框的 IOU。框不存在时调用方自行短路。"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    ax1, ax2, ay1, ay2 = ax - aw / 2, ax + aw / 2, ay - ah / 2, ay + ah / 2
    bx1, bx2, by1, by2 = bx - bw / 2, bx + bw / 2, by - bh / 2, by + bh / 2
    iw = min(ax2, bx2) - max(ax1, bx1)
    ih = min(ay2, by2) - max(ay1, by1)
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# 估算器（核心类，实时/离线共用）
# ---------------------------------------------------------------------------

@dataclass
class _Sample:
    t: float
    distance: float


class TTCEstimator:
    """逐帧喂检测+测距，吐 TTC。

    用法（离线与实时同构）::

        est = TTCEstimator()
        for rec in records:
            r = est.update(t=rec.t, box=(rec.x, rec.y, rec.width, rec.height),
                           class_id=rec.class_id, has_target=rec.has_target,
                           distance=rec.distance)
            # r.available / r.ttc / r.level / r.reason ...

    内部只有一个滑动窗口（``deque``），无其它状态，重置即干净。
    """

    def __init__(self, cfg: Optional[TTCConfig] = None):
        self.cfg = cfg or TTCConfig()
        self._window: deque = deque()
        self._last_box: Optional[Tuple[float, float, float, float]] = None
        self._last_class: int = -1
        self._last_t: Optional[float] = None

    def reset(self) -> None:
        """清空窗口与关联状态（目标断连/换人后调用）。"""
        self._window.clear()
        self._last_box = None
        self._last_class = -1
        self._last_t = None

    def update(self, t: float, box: Tuple[float, float, float, float],
               class_id: int, has_target: bool,
               distance: Optional[float]) -> TTCResult:
        """喂入一帧，返回本帧 TTC 结果。"""
        cfg = self.cfg
        res = TTCResult(t=t)

        # -- 前置过滤：没目标 / 没距离，本帧必然不可算 -----------------------
        if not has_target:
            self._handle_lost(res, t, '无目标')
            return res
        if distance is None:
            self._handle_lost(res, t, '测距不可用')
            return res

        # -- 帧间守卫：IOU>0.3 + 类别一致 + 断连时长（CHARTER 原文要求）---------
        if self._last_box is not None and self._last_t is not None:
            gap_ok = (t - self._last_t) <= cfg.max_gap_s
            same_cls = (class_id == self._last_class) or not cfg.require_same_class
            ov = iou_xywh(self._last_box, box)
            if not gap_ok:
                self._window.clear()
                res.reason = '目标断连过久，速度窗口已重置'
            elif not same_cls:
                self._window.clear()
                res.reason = '检测类别变化，速度窗口已重置'
            elif ov <= cfg.iou_gate:
                self._window.clear()
                res.reason = f'帧间框交叠 {ov:.2f} ≤ {cfg.iou_gate}，疑似关联错误'
        if self._last_t is not None and (t - self._last_t) > cfg.max_gap_s:
            self._window.clear()

        # -- 滑动窗口收纳 + 裁剪 ---------------------------------------------
        self._window.append(_Sample(t=t, distance=float(distance)))
        cutoff = t - cfg.window_s
        while len(self._window) > 1 and self._window[0].t < cutoff:
            self._window.popleft()

        # 记住本帧，供下一帧做守卫
        self._last_box = box
        self._last_class = class_id
        self._last_t = t

        # -- 拟合：剔除离群样本后做距离-时间最小二乘 ----------------------------
        fit = self._robust_fit()
        if fit is None:
            res.reason = (res.reason or
                          '窗口内测距样本不足或互相矛盾（疑似方法切换/异常帧）')
            return res
        slope, current_kept = fit

        # slope = d(距离)/dt。接近中距离下降 → slope < 0 → 接近速率为正
        closing_speed = -slope
        res.closing_speed = closing_speed
        if closing_speed < cfg.min_closing_speed:
            res.reason = (f'接近速率 {closing_speed:.2f} m/s 低于门槛 '
                          f'{cfg.min_closing_speed}（未在接近或接近极慢）')
            return res

        # -- 本帧自身被剔除为离群 → 本帧不出 TTC（诚实原则）--------------------
        if not current_kept:
            res.reason = '本帧测距偏离窗口趋势（疑似方法切换/异常帧），不出 TTC'
            return res

        # -- TTC = 距离 / 接近速率 --------------------------------------------
        ttc = float(distance) / closing_speed
        if not math.isfinite(ttc) or ttc < 0:
            res.reason = 'TTC 数值非法'
            return res
        res.ttc = ttc
        res.level = classify_ttc(ttc, cfg)
        res.available = True
        res.is_reference = float(distance) < cfg.reference_below_m
        return res

    # -- 内部 -----------------------------------------------------------------

    def _handle_lost(self, res: TTCResult, t: float, why: str) -> None:
        """目标丢失：窗口保留（短暂丢帧不毁速度估计），只标记本帧不可算。"""
        res.reason = why
        # 真正的清空由断连时长守卫在目标回来时触发（update 里处理）。
        # 这里只推进"上次见到目标"的时间不合适——断连计时基准应停在
        # 最后一次有效帧上，所以什么都不动，让 gap 守卫自己判断。

    @staticmethod
    def _lsq_slope_from(pts: List[_Sample]) -> Optional[float]:
        if len(pts) < 2:
            return None
        n = len(pts)
        s_t = sum(p.t for p in pts)
        s_d = sum(p.distance for p in pts)
        s_tt = sum(p.t * p.t for p in pts)
        s_td = sum(p.t * p.distance for p in pts)
        denom = n * s_tt - s_t * s_t
        if abs(denom) < 1e-12:
            return None
        return (n * s_td - s_t * s_d) / denom

    def _robust_fit(self) -> Optional[Tuple[float, bool]]:
        """离群剔除后的窗口拟合。返回 ``(斜率, 本帧是否被保留)``；不可拟合返回 None。

        算法（窗口内点数 ≤6，平方级开销可忽略）：
        1. 样本数 < min_points（默认 4）直接不拟合——3 点会被完美拟合，
           残差全零，离群无从谈起；
        2. 对窗口样本做最小二乘；
        3. 残差超限（> max(abs_tol, rel_frac×窗口中位距离)）的样本里
           剔除残差最大的一个，重拟合；
        4. 反复迭代，直到无超限样本、或剩余点数降到 fit_floor、
           或本帧已被剔除（本帧被剔除时继续迭代没有意义，直接收尾判断）。
        """
        cfg = self.cfg
        pts = list(self._window)
        if len(pts) < cfg.min_points:
            return None
        med_d = sorted(p.distance for p in pts)[len(pts) // 2]
        tol = max(cfg.outlier_abs_tol, cfg.outlier_rel_frac * med_d)

        kept = pts
        slope = self._lsq_slope_from(kept)
        if slope is None:
            return None
        for _ in range(len(pts) - cfg.fit_floor):
            # 残差（拟合值与观测的差）
            def resid(p: _Sample) -> float:
                return p.distance - (slope * p.t + _intercept(kept, slope))

            worst = max(kept, key=lambda p: abs(resid(p)))
            if abs(resid(worst)) <= tol:
                break
            kept = [p for p in kept if p is not worst]
            if len(kept) < cfg.fit_floor:
                return None
            slope = self._lsq_slope_from(kept)
            if slope is None:
                return None

        current = pts[-1]  # 窗口按时间序追加，最后一个即本帧
        current_kept = any(p is current for p in kept)
        return slope, current_kept


def _intercept(pts: List[_Sample], slope: float) -> float:
    """给定斜率后按均值关系求截距：b = mean(d) - slope*mean(t)。"""
    mt = sum(p.t for p in pts) / len(pts)
    md = sum(p.distance for p in pts) / len(pts)
    return md - slope * mt


# ---------------------------------------------------------------------------
# 离线分析（CHARTER：先在录制回放上算）
# ---------------------------------------------------------------------------

def analyze_recording(session_dir: str,
                      cfg: Optional[TTCConfig] = None) -> List[TTCResult]:
    """对一个录制会话离线算逐帧 TTC。

    直接吃 ``Replayer`` 的数据轨（frames.jsonl），逐帧喂给
    ``TTCEstimator``——与实时路径完全同构，实时接入时零新逻辑。

    距离取会话的**规范距离**（``Replayer.canonical_distances()``）：新格式
    录制里就是当时实时链路用的去噪值；旧格式录制现场补做同参数去噪。
    **不拿原始测量值另算一套** —— 否则离线结论与当时屏幕上看到的对不上。
    """
    from core.recorder import Replayer  # 延迟导入：纯逻辑层不强制依赖 cv2

    rep = Replayer(session_dir)
    est = TTCEstimator(cfg)
    out: List[TTCResult] = []
    for rec, dist in zip(rep.records, rep.canonical_distances()):
        out.append(est.update(
            t=rec.t,
            box=(rec.x, rec.y, rec.width, rec.height),
            class_id=rec.class_id,
            has_target=rec.has_target,
            distance=dist,
        ))
    return out
