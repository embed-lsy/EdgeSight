"""Cohort 归一化 —— 用「这个场景里路人长什么样」给相似度重新定标。

## 要解决的问题

OSNet 嵌入的余弦相似度是**绝对值**：它只说「这两个向量夹角多小」，不知道
「在这个相机、这个安装角、这个光照下，**两个本来就不是同一个人**的向量
通常有多像」。

后果：一个固定阈值（如 0.50）在一台相机上合适，换台相机就错。而我们当前
唯一的锚点是「同一人跨会话实测中位 **0.502**」（``probe_osnet_reid.py``），
**异人分布一个样本都没有** —— 阈值到底是偏松还是偏紧，无法证伪。

## 做法：把「像路人」当作零基准

人脸识别里管这叫 **cohort normalization / T-norm**：不跟一个绝对分数线比，
而是先量出「这个人跟**无关人群**最多能有多像」，再把分数减去这个基准。

    s' = s − s_cohort_p90

其中 ``s_cohort_p90`` = probe 与本场景已积累的无标签嵌入池中相似度的
**90 分位**。语义变得直观：

- ``s'`` 接近 0 → 他"像路人"的最高水平也就这么像 → **大概率不是目标**
- ``s'`` 明显为正 → 他比这个场景里最像的路人**还要像** → 更像目标

好处是**不需要任何人配合录制**：系统运行时对每一帧人算嵌入，那些
「远远不像目标」的嵌入天然就是路人样本。

## ⚠️ 三条必须守住的边界（都有对应验证项）

1. **准入门槛要独立于归一化**。判断「这一帧能不能进池」用的必须是**原始**
   相似度（``admit_below``），**不能**用归一化后的分数 —— 否则
   「要算归一化得先有池、要有池得先归一化」形成自举循环。这是本模块
   唯一有真实崩溃风险的部位：准入门槛若偏松，**目标本人**会被收进池，
   于是「自己像自己」被减去，正样本分数被自己压低。
2. **库为空时不准入池**。没有可比档案 ⇒ 无法判断任何人像不像目标 ⇒
   此时若入池，收进去的多半就是目标本人（还没建档案时期的客观事实）。
   ``best_sim is None`` 一律拒绝。
3. **跨模型必须清池**。池是**统计量**，不像单条嵌入那样「跳过比较」就行：
   tag 一变，池内所有样本都不同源，混着算出来的分位数毫无意义。
   → 发现 tag 不符：**清空重建**，而不是保留。

## 不落盘（规避 CHARTER 第 89 行）

CHARTER 第 89 行：「**同时只维持 1 个身份**（被追踪者），其余人只做
「本帧比对」不留轨迹」。

本模块的池是**纯内存态**：进程退出即消失，**不写任何文件**；池里只有
**无标签、无身份、无位置、无时间线**的 512 维外观向量，不构成可回溯的
轨迹。判定为**不越界**；但这是边界解释，最终以 CHARTER 措辞为准
（见 ``notes`` 的提议）。

## 默认关

``PersonFeatureTracker`` 侧的接线开关默认 **off**、且本模块单独可用 ——
在「含第二位真人的录制」到手之前，归一化**有没有用、会不会误伤**都还没
实测判决，不能默认生效。
"""

from __future__ import annotations

import collections
import math
from typing import Optional

import numpy as np

from core.reid_osnet import embedding_similarity, l2_normalize

__all__ = [
    'COHORT_MAX_SIZE', 'COHORT_ADMIT_BELOW', 'COHORT_MIN_SIZE',
    'COHORT_QUANTILE', 'CohortPool', 'cohort_offset', 'normalize_score',
]

# 池容量。64 条 × 512 float32 ≈ 128 KB，内存可忽略；统计上 64 个样本
# 估 90 分位已够稳（经验上 ≥50 即可，见 verify_cohort_norm F 项）。
COHORT_MAX_SIZE = 64

# 准入门槛（**原始**余弦相似度）：低于此值才认为「远远不像目标」→ 收作路人样本。
# 取 0.30 的依据：同一人跨会话实测最低 0.38、p05 0.44（17 段回放数据），
# 0.30 在它下方留了余量；而正样本分布最低点以下才收，是「宁可漏收不可错收」
# 的方向选择 —— 错收代价（压低本人分数）远大于漏收（池小一点而已）。
COHORT_ADMIT_BELOW = 0.30

# 池小于此规模不给归一化：3 个样本的分位数没有统计意义，
# 此时**必须**返回 None 让上层回落原始分数，而不是拿 3 个数硬算。
COHORT_MIN_SIZE = 3

# 取「最像的那一档」用 90 分位而非最大值：最大值被单个噪声样本主导，
# 会被偶然一帧带偏整个偏移量。
COHORT_QUANTILE = 0.90


def cohort_offset(probe, pool, *, quantile: float = COHORT_QUANTILE
                  ) -> Optional[float]:
    """probe 与池内样本相似度的 ``quantile`` 分位。**纯函数**。

    返回值 = 「这个场景里，跟 probe 差不多像的人，最多能像到什么程度」。
    池为空、或池内样本与 probe 维度不符时返回 ``None``（上层据此回落）。

    **自相似样本会被排除**（``sim ≥ 1 − 1e-6``）。理由不是洁癖，是必须：
    若调用方先 ``observe`` 再 ``offset``，probe 自己就躺在池里，``sim=1.0``
    会把高分位顶满 —— 池越小越严重（池 6 条时 90 分位直接跳到 0.51，
    归一化彻底失效）。排除后**调用顺序无关**，无论先入池还是先归一化，
    结果一致。另一个同一人真出现在池里的情形也不会被误伤：
    余弦 1.0 意味着同一个向量，跳过它是对的。

    调用方**必须**保证 probe 与池内向量同源（同一嵌入模型）——
    跨模型防护在 :class:`CohortPool` 层，纯函数不做检查（它无从知道来源标签）。
    """
    if probe is None or not pool:
        return None
    p = np.asarray(probe, dtype=np.float32).ravel()
    if p.size == 0:
        return None
    sims = []
    for c in pool:
        c = np.asarray(c, dtype=np.float32).ravel()
        if c.size != p.size:
            continue                      # 维度不符：跳过，不污染统计量
        s = embedding_similarity(p, c)
        if s >= 1.0 - 1e-6:
            continue                      # 这是 probe 自己（见 docstring）
        sims.append(s)
    if not sims:
        return None
    q = float(min(max(quantile, 0.0), 1.0))
    return float(np.quantile(np.asarray(sims, dtype=np.float64), q))


def normalize_score(raw: float, offset: float) -> float:
    """平移归一化：``raw − offset``。**纯函数**。

    语义：``0`` = 「像路人最像的那个一样像」；``> 0`` = 比路人更像我；
    ``< 0`` = 还不如路人像。**不缩放** —— 平移单调、不放大噪声，
    阈值只需跟着平移同样的量，行为最好解释。

    这里**刻意没有**提供"线性映射到 [0,1]"的版本：那需要除以
    ``1 − offset``，而 ``offset`` 越接近 1 分母越小、测量噪声被放大越多
    （实测 offset=0.999999 时放大约 15 万倍）。平移版没有这个失效模式，
    UI 若要展示更直观的刻度，应同时显示 ``raw`` 与 ``offset`` 两个数，
    而不是把噪声放大后藏进一个"好看"的 0–1 值里。
    """
    return float(raw) - float(offset)


class CohortPool:
    """无标签路人嵌入池 —— 内存态、FIFO 容量、带准入门槛与跨模型防护。

    生命周期与 ``PersonFeatureTracker`` 一致（随它构造/销毁），**不落盘**。
    所有失效路径（池空、池太小、维度不符、tag 不符）都返回 ``None``，
    调用方**必须**回落原始分数 —— 本类**永不**返回一个"看着正常"的假值。
    """

    def __init__(self, *, max_size: int = COHORT_MAX_SIZE,
                 admit_below: float = COHORT_ADMIT_BELOW,
                 min_size: int = COHORT_MIN_SIZE,
                 quantile: float = COHORT_QUANTILE,
                 model_tag: str = ''):
        self.max_size = int(max_size)
        self.admit_below = float(admit_below)
        self.min_size = int(min_size)
        self.quantile = float(quantile)
        self.model_tag = str(model_tag or '')
        self._pool: collections.deque = collections.deque(maxlen=self.max_size)
        # 观测计数：准入被拒 / 入池 / 因无标签被拒 —— 排查用，UI 可显示
        self.n_seen = 0
        self.n_admitted = 0
        self.n_rejected_too_similar = 0
        self.n_rejected_no_label = 0
        self.n_cleared = 0

    # -- 写入 --------------------------------------------------------------

    def observe(self, emb, best_sim: Optional[float], *,
                model_tag: Optional[str] = None) -> bool:
        """喂一帧的嵌入 + 它与**档案库**的最高原始相似度。入池返回 True。

        ``best_sim is None`` 表示「库为空 / 无可比档案」—— 此时**无法判断**
        这一帧像不像目标，**一律不准入池**（本模块 docstring 边界 2：
        否则会把还没建档时期的目标本人收进来，之后拿他的分数减他自己）。
        ``NaN`` / ``±inf`` 同样拒收：``nan >= admit_below`` 为 False，
        不显式拦就会溜过准入门槛。

        **与 :meth:`offset` 的调用顺序无关** —— 即便本帧先入池再算偏移，
        :func:`cohort_offset` 会排除自相似样本（见其 docstring），
        不会出现「拿自己当自己的参照」。推荐顺序仍是
        「先 :meth:`offset` / :meth:`normalize` 判身份，再决定是否入池」，
        因为那更符合「先判定、后入库」的语义。

        过长的向量、非有限值一律拒绝 —— 池是统计量的来源，
        一条脏数据会通过分位数污染所有人。
        """
        if model_tag is not None and str(model_tag) != self.model_tag:
            # 跨模型：池内全部样本不同源，统计量作废。清空重建（边界 3）。
            self.clear()
            self.model_tag = str(model_tag)
        self.n_seen += 1
        if emb is None:
            return False
        v = np.asarray(emb, dtype=np.float32).ravel()
        if v.size == 0 or not np.all(np.isfinite(v)):
            return False
        if best_sim is None:
            self.n_rejected_no_label += 1
            return False
        try:
            s = float(best_sim)
        except (TypeError, ValueError):
            self.n_rejected_no_label += 1
            return False
        # NaN / ±inf 必须显式拦：``nan >= 0.30`` 求值为 **False**，
        # 于是 NaN 会溜过下面那道"太像就拒收"的门被收进池
        # （verify_cohort_norm F4 抓到的真缺陷）。
        if not math.isfinite(s):
            self.n_rejected_no_label += 1
            return False
        if s >= self.admit_below:
            # 已经够像目标了 —— 可能是目标本人，宁可漏收不可错收
            self.n_rejected_too_similar += 1
            return False
        hint = self._dim_hint()
        # 池空时 hint 为 None = 还没定基准维度，任何维度都收（首条定基准）。
        # ⚠️ 这里**必须**先判 None 再比 —— 写成 ``v.shape[0] != self._dim_hint()``
        # 会让池空时 ``int != None`` 恒真，池永远攒不起来（本模块自查抓到的缺陷）。
        if hint is not None and int(v.shape[0]) != hint:
            return False                  # 维度与本池既有样本不符
        self._pool.append(l2_normalize(v))
        self.n_admitted += 1
        return True

    def _dim_hint(self) -> Optional[int]:
        """池内既有样本的维度；池空时返回 None（表示"任何维度都收"）。"""
        if not self._pool:
            return None
        return int(np.asarray(self._pool[0]).shape[0])

    # -- 读取 --------------------------------------------------------------

    def offset(self, emb) -> Optional[float]:
        """probe 的 cohort 偏移量；池不足/不可用时 ``None``（**必须**回落）。"""
        if len(self._pool) < self.min_size:
            return None
        return cohort_offset(emb, list(self._pool), quantile=self.quantile)

    def normalize(self, emb, raw: float) -> Optional[float]:
        """一步到位：返回平移归一化后的分数；池不足时 ``None``。"""
        off = self.offset(emb)
        if off is None:
            return None
        return normalize_score(raw, off)

    def __len__(self) -> int:
        return len(self._pool)

    def __bool__(self) -> bool:
        return len(self._pool) > 0

    def ready(self) -> bool:
        """池是否已够规模、可提供归一化。"""
        return len(self._pool) >= self.min_size

    # -- 维护 --------------------------------------------------------------

    def clear(self) -> None:
        """清空池与统计量。跨模型重建、用户手动重置时用。"""
        had = len(self._pool)
        self._pool.clear()
        if had:
            self.n_cleared += 1

    def stats(self) -> dict:
        """一行状态：池规模 + 准入计数。UI/日志可显示，便于判断池是否在正常工作。"""
        return {
            'size': len(self._pool),
            'max_size': self.max_size,
            'ready': self.ready(),
            'model_tag': self.model_tag,
            'admit_below': self.admit_below,
            'quantile': self.quantile,
            'seen': self.n_seen,
            'admitted': self.n_admitted,
            'rejected_too_similar': self.n_rejected_too_similar,
            'rejected_no_label': self.n_rejected_no_label,
            'cleared': self.n_cleared,
        }

    def line(self) -> str:
        """给人看的一行 —— 与 ``PersonFeatureTracker.match_line()`` 风格一致。"""
        s = self.stats()
        if not s['ready']:
            return (f'路人池：{s["size"]}/{s["max_size"]} 条'
                    f'（不足 {self.min_size} 条，暂不归一化）')
        return (f'路人池：{s["size"]}/{s["max_size"]} 条'
                f'（准入 {s["admitted"]}｜太像被拒 {s["rejected_too_similar"]}'
                f'｜无标签被拒 {s["rejected_no_label"]}）')
