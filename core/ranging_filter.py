# -*- coding: utf-8 -*-
"""距离序列去噪：中值滤波（窗 5）+ One Euro 自适应低通，串联。

为什么是这两个（2026-09-26，实测 session-20260926-104005 定的）
----------------------------------------------------------------
- 原始帧间跳变中位 7.5 cm、P90 32 cm、最大 83 cm；大尖刺全部集中在
  1.2~2 m「脚出画↔全身入画」的方法切换区 —— 属于**离群脉冲**。中值滤波
  专杀单帧尖刺，窗取 3 而不是 5：窗 5 的群延迟约 2 帧（步行速度下 ≈12 cm
  滞后，TTC 的速度估计会被拖歪），窗 3 延迟 1 帧且同样能杀单帧尖刺。
- 中值之后剩下的连续抖动（检测框 1~3 px 抖动经反比关系放大）用 One Euro
  低通压掉：它按信号速度自适应调整截止频率 —— 站定时强平滑、快走时低
  滞后，纯标量运算（边缘设备友好），天然支持变帧率（检测 11~14 fps 波动）。
- One Euro 出处：Casiez et al., CHI 2012。
- 参数经 104005 会话逐帧重放扫参选定（verify_denoise.py）：中值3 +
  min_cutoff 0.3 + beta 4 —— 方向反转 42→12，对齐后与中位参考偏差
  ~2 cm/帧，滞后 1 帧；剩余反转集中在切换区（两方法系统偏差在交替，
  那是滞回切换要治的，滤波治不了也不该治）。

边界语义
--------
- 输入 ``None``（不可测）→ 输出 ``None`` 并**复位**：「没有读数」绝不能
  被平滑成「有个读数」。目标恢复后滤波器从新值重新起步。
- **全链路只有一个距离值**（2026-09-26 明确）：滤波器紧跟在测距之后，
  输出即"规范距离"——速度门控、人特征档案、监视页读数、TTC、深度分析
  曲线、录制轨存的都是它。不存在"UI 看去噪值、判定/存档用原始值"的两套数。
  原始测量值只在录制轨里留一份诊断字段（``FrameRecord.distance_raw``），
  供事后重新调滤波器参数，实时逻辑一律不读。
- 去噪的**目的**是拿到更接近真值的距离，不是把曲线画光滑：滤波值参与
  判定，所以"平滑"必须建立在"更准"之上（滞回切换治的是方法切换处的
  系统偏差，那属于测距层的根因修复，见 README 的后续计划）。
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional


class _LowPass:
    """一阶低通（标量）。首个样本直通，不做平滑。"""

    def __init__(self) -> None:
        self.y: Optional[float] = None

    def __call__(self, x: float, alpha: float) -> float:
        self.y = x if self.y is None else alpha * x + (1.0 - alpha) * self.y
        return self.y

    def reset(self) -> None:
        self.y = None


class OneEuroFilter:
    """One Euro Filter（Casiez et al. 2012），标量版。

    Parameters
    ----------
    min_cutoff:
        静止（导数≈0）时的截止频率（Hz）。越小平滑越狠。
    beta:
        速度系数：截止频率 = min_cutoff + beta·|速度估计|。
        信号单位是米/秒时 beta 取个位数量级（0.007 那种默认值是给
        像素级光标信号用的，距离信号直接搬会形同不滤）。
    d_cutoff:
        速度估计自身的低通截止频率（Hz），一般不动。
    """

    def __init__(self, min_cutoff: float = 0.3, beta: float = 4.0,
                 d_cutoff: float = 1.0) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x = _LowPass()
        self._dx = _LowPass()
        self._x_prev: Optional[float] = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x: float, dt: float) -> float:
        """喂一个样本。``dt`` 是与上一样本的时间差（秒），必须 > 0。"""
        if self._x_prev is None:
            dx = 0.0
        else:
            dx = (x - self._x_prev) / dt
        self._x_prev = x
        edx = self._dx(dx, self._alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self._x(x, self._alpha(cutoff, dt))

    def reset(self) -> None:
        self._x.reset()
        self._dx.reset()
        self._x_prev = None


class DistanceFilter:
    """距离去噪：中值（窗 5）→ One Euro，串联。

    用法::

        f = DistanceFilter()
        out = f.update(t, dist)   # t 用单调时钟（秒）；dist None → None
    """

    def __init__(self, median_window: int = 3,
                 min_cutoff: float = 0.3, beta: float = 4.0) -> None:
        self._buf: deque = deque(maxlen=max(1, int(median_window)))
        self._euro = OneEuroFilter(min_cutoff=min_cutoff, beta=beta)
        self._last_t: Optional[float] = None

    def update(self, t: float, dist: Optional[float]) -> Optional[float]:
        """喂一帧。``dist`` 为 None 时复位并返回 None。"""
        if dist is None or not math.isfinite(dist):
            self.reset()
            return None
        self._buf.append(float(dist))
        ordered = sorted(self._buf)
        med = ordered[len(ordered) // 2]
        if self._last_t is None:
            dt = 0.2            # 首帧无差分可用，按典型检测间隔兜底
        else:
            dt = t - self._last_t
            if dt <= 0:
                dt = 1e-3       # 时钟重复/回退：退化为近似瞬时的强平滑
        out = self._euro.filter(med, dt)
        self._last_t = t
        return out

    def reset(self) -> None:
        """复位（目标丢失 / 不可测后调用，避免旧状态污染新目标）。"""
        self._buf.clear()
        self._euro.reset()
        self._last_t = None
