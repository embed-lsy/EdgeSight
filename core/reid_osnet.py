"""OSNet ReID 外观嵌入 —— CHARTER v1.4「特征指纹」的第二步子路。

## ⚠️ 输入通道顺序：本模块收 **RGB**，不是 BGR

项目全域（``main_windows.py``、``core/camera``、录制回放）从 OpenCV 读出来的帧是
**BGR**，而本模块的 ``crop_person`` / ``to_model_input`` 按 **RGB** 做预处理
（OSNet 的预训练与评测口径）。所以调用方**必须**先转换：

    import cv2
    from core.reid_osnet import OsnetEmbedder

    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)   # ← 必须
    emb = embedder.embed(frame_rgb, box)

``core/reid_probe.py``（录制旁路）已按此约定在内部完成转换。

### 关于「传错会怎样」的实测边界（2026-09-27，**不是估计**）

曾经写在这段里的说法是「传错会让嵌入静默退化」—— **该说法未经实测，已撤回**。
实测（``verify_reid_probe.py`` 的 H 节，与既有基线同口径：4 个会话 × 10 帧）
把 BGR **故意**直传、不做任何转换，结果是：

| 输入 | within | cross | 分离度 | rank-1 |
|---|---|---|---|---|
| RGB（正确） | 0.593 | 0.502 | +0.090 | 38/40 = 95.0% |
| BGR（故意传错） | 0.617 | 0.523 | +0.094 | 38/40 = 95.0% |

**测不出可分辨的差别。** 但这**不能**推出「通道顺序无所谓」，理由是数据受限：

1. 该批录制里**没有第二位真人**，rank-1 衡量的只是「同一人跨会话的自我一致性」，
   两种顺序都已饱和在 95%，区分度被上限卡住；
2. 分离度差 0.004 落在 40 个查询点的噪声量级内。

所以本模块**仍按训练口径收 RGB** —— 依据是「与预训练口径一致」这个先验，
而不是实测增益。等有了含第二位真人的录制数据，这个对照需要重做；
在那之前，任何「BGR 也能用」或「BGR 会退化」的说法都**没有依据**。

## 为什么要有这个模块

现有 512 维躯干 HSV 直方图（``torso_appearance``）**认不出人**。用 ``recordings/``
下真实录制数据实测（2026-09-27，脚本 ``probe_appearance_feature.py``）：

- 同会话（同一人、时刻相近）平均相似度 **0.382**；
- 会话间（不同时间）**0.368** —— 两者几乎重合，分离度仅 **+0.014**；
- 多数同会话配对还落在匹配阈值 ``0.55`` **以下**：连自己都认不出来。

同口径下本模块（OSNet x0.25）实测：

- rank-1 判别率 **95.0%**（38/40）；
- 同会话 **0.593** / 会话间 **0.502**，分离度 **+0.090** —— 6.4 倍于 HSV。

⚠️ **上面这个「6.4 倍」只在"同人稳定性"这个口径下成立，不能读成
"认人能力强 6.4 倍"**：两侧量的都是同一个人的样本（该批录制里没有第二位
真人），比的是「同一人跨会话是否比同会话更远」，**不含任何"不同人分不分得开"
的信息**。异人分布至今无数据 —— 这也是认人门槛只能取占位值的根本原因。
判据要成立（CHARTER 第 42-43 行「未登记者 ≥9/10 拒绝」）必须先录到**第二位真人**。

## 与 ``torso_appearance`` 的语义差异（**数值不可跨比**）

1. **裁剪范围**：本模块用**整人框**（OSNet 训练时的输入口径）；
   ``torso_appearance`` 用框高 35%–70% 的**躯干带**。
2. **相似度定义**：本模块是**余弦相似度**（特征已 L2 归一化，取值 [-1, 1]，
   实践中多为 [0, 1]）；``torso_appearance`` 用 L1 距离归一（取值 [0, 1]）。

→ 两者的阈值必须**分别标定**，把 0.55 直接搬过来是错的。

## 模型来源与可信度

``models/reid/osnet_x0_25_msmt17.onnx``（886 KB，sha256 ``f3352b03…``）

- 取自 HuggingFace **kornia/osnet** 与 **anriha/osnet_x0_25_msmt17** 两个独立仓库，
  两处下载结果**字节级完全一致**（原始 sha256 ``e78604f4…``）—— 互为交叉验证；
- 输出 512 维**嵌入**而非分类 logits（末端为 ``Gemm(fc.0)`` → ``BatchNorm(fc.1)``
  → ``Relu``，classifier 已切掉），正是认人所需形态；
- 原始图输入被固定为 ``batch=16``（OSNet 内部池化用 ``Shape``/``Gather`` 导出所致）。
  入库版本已把输入/输出 batch 维度改写为符号 ``'batch'``，实测与原始图输出
  **逐位一致**（cosine ``1.000000``、max-abs-diff ``0``），并接受 1/3/16 任意批；
- **预训练权重、不训练** —— 符合 CHARTER「明确不做：训练 / 微调模型」。

## 实测性能（2026-09-27，本机 i5-13420H，4 线程，独立进程隔离测量）

| 输入 | 耗时（中位） | 单张摊销 |
|---|---|---|
| batch=1 | 5.8 ms | 5.8 ms |
| batch=3 | 15.4 ms | 5.1 ms |
| batch=16（原图） | 78.8 ms | 4.9 ms |

→ **单张约 6 ms**，相对 ≥15 FPS 的 66.7 ms 整链路预算，占比约 9%。

## 尚未定的事（**不要擅自填**）

匹配阈值与「匹配分级」（高/中/低置信）的切点**当前无数据支撑**：
录制主体很可能始终是同一个人，**没有「未登记者」的负样本**，
无法判定「≥9/10 正确拒绝」这一条（CHARTER 认人判据）。
→ 本模块只提供**特征提取**，不规定阈值；阈值待含第二位真人的录制数据到手后再定。
"""
from __future__ import annotations

import os
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

# 模型位置：相对仓库根。默认按本文件位置推导，避免依赖调用方的 CWD。
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_PATH = os.path.join(os.path.dirname(_HERE), 'models', 'reid',
                                  'osnet_x0_25_msmt17.onnx')

# OSNet 的标准输入口径：高 256 × 宽 128（**人体框**的长宽比，不是 1:1）
INPUT_HW: Tuple[int, int] = (256, 128)

# ImageNet 归一化（OSNet 官方预处理）
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)

# 与 ``person_model._MIN_ROI_PX`` 对齐的下限：比这还小的框放大到 128×256
# 全是插值糊出来的，特征没有意义。
MIN_CROP_PX = 8
# 框高低于此值直接放弃：整人框被 resize 到 256 像素高时，
# 原图不足 32 px 意味着放大 >8 倍，细节已不可恢复。
MIN_BOX_H_PX = 32

# 本默认值只影响「不显式传 threads」的调用方；实际用法都**显式传 2**
# （建档嵌入器见 main_windows.py，录制旁路见 core/reid_probe.py）。
# 旧注释断言「本机实测 4 线程与 8 线程无显著差异」—— 2026-09-29 重测
# **不成立**：检测 4 → 8 线程快 16.5%（79.4 → 66.3 ms），与 OSNet 2 线程
# 满速并发时仍快 12.4%（77.3 → 67.7 ms），抢核代价只有 ±3%。
# 见 README「帧率」一节。
DEFAULT_THREADS = 4

EMBED_DIM = 512


# ---------------------------------------------------------------------------
# 纯函数：裁剪与预处理
# ---------------------------------------------------------------------------

def crop_person(frame_rgb, box) -> Optional[np.ndarray]:
    """按检测框裁出**整人**区域（RGB）。**纯函数**。

    ``box`` 与项目其余部分同构：``{'x','y','width','height'}``，``x/y`` 是**中心点**。
    框太小 / 输入无效 / 裁剪后为空时返回 ``None``。

    为什么裁整框而不是躯干带：OSNet 是在**整人框**上训练的，
    喂躯干带属于训练-推理口径不一致，会让嵌入退化（实测中未采用该做法的原因）。
    """
    if frame_rgb is None or box is None:
        return None
    h_px = float(box.get('height', 0.0) or 0.0)
    w_px = float(box.get('width', 0.0) or 0.0)
    if h_px < MIN_BOX_H_PX or w_px < MIN_CROP_PX:
        return None
    cx = float(box.get('x', 0.0) or 0.0)
    cy = float(box.get('y', 0.0) or 0.0)

    fh, fw = frame_rgb.shape[:2]
    x1 = max(0, int(round(cx - w_px / 2.0)))
    x2 = min(fw, int(round(cx + w_px / 2.0)))
    y1 = max(0, int(round(cy - h_px / 2.0)))
    y2 = min(fh, int(round(cy + h_px / 2.0)))
    if x2 - x1 < MIN_CROP_PX or y2 - y1 < MIN_CROP_PX:
        return None
    crop = frame_rgb[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    return crop


def to_model_input(crop_rgb) -> Optional[np.ndarray]:
    """RGB 裁剪图 → OSNet 输入张量 ``(3, 256, 128)`` float32。**纯函数**。

    流程：resize 到 256×128 → ``uint8`` 归一化到 [0,1] → ImageNet 均值方差 →
    通道前置（HWC→CHW）。注意 OpenCV 的 ``resize`` 收 ``(width, height)``，
    与 ``INPUT_HW`` 的 ``(height, width)`` 顺序相反，这里已按正确顺序传入。
    """
    if crop_rgb is None or crop_rgb.size == 0:
        return None
    h, w = INPUT_HW
    img = cv2.resize(crop_rgb, (w, h), interpolation=cv2.INTER_LINEAR)
    arr = img.astype(np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)               # HWC -> CHW
    arr = (arr - _MEAN) / _STD
    return np.ascontiguousarray(arr, dtype=np.float32)


def l2_normalize(vec):
    """按行 L2 归一化。**纯函数**。零向量原样返回（不产生 NaN）。"""
    a = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(a, axis=-1, keepdims=True)
    return a / np.maximum(norm, 1e-12)


def embedding_similarity(a, b) -> float:
    """两个**已 L2 归一化**嵌入的余弦相似度，∈ [-1, 1]。**纯函数**。

    任一为 ``None`` 时返回 ``0.0``（与 ``appearance_similarity`` 的约定一致）。
    """
    if a is None or b is None:
        return 0.0
    va = np.asarray(a, dtype=np.float32).ravel()
    vb = np.asarray(b, dtype=np.float32).ravel()
    if va.size == 0 or vb.size != va.size:
        return 0.0
    return float(np.clip(np.dot(va, vb), -1.0, 1.0))


# ---------------------------------------------------------------------------
# 嵌入器
# ---------------------------------------------------------------------------

class OsnetEmbedder:
    """OSNet 嵌入器。**延迟建会话**：构造对象不加载模型，首次 ``embed`` 才建。

    与 ``core/detector/yolo_detector.py`` 同样的理由 —— 建会话是耗时动作
    （本机约 0.1–0.3 s），放在主线程会冻界面。
    """

    def __init__(self, model_path: Optional[str] = None, *,
                 threads: int = DEFAULT_THREADS):
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.threads = int(threads)
        self._session = None
        self._input_name = None
        self.load_error: Optional[str] = None

    # -- 生命周期 ---------------------------------------------------------

    def available(self) -> bool:
        """模型文件是否就位（不建会话）。"""
        return os.path.isfile(self.model_path)

    def load(self) -> bool:
        """建 ONNX Runtime 会话。已建则直接返回 True。失败返回 False 并记 ``load_error``。"""
        if self._session is not None:
            return True
        if not self.available():
            self.load_error = f'模型文件不存在：{self.model_path}'
            return False
        try:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            opts.intra_op_num_threads = self.threads
            opts.inter_op_num_threads = 1
            self._session = ort.InferenceSession(
                self.model_path, opts, providers=['CPUExecutionProvider'])
            self._input_name = self._session.get_inputs()[0].name
            self.load_error = None
            return True
        except Exception as exc:                       # noqa: BLE001 - 如实上报
            self.load_error = f'{type(exc).__name__}: {exc}'
            self._session = None
            return False

    # -- 推理 -------------------------------------------------------------

    def embed(self, frame_rgb, box) -> Optional[np.ndarray]:
        """单个人裁剪框 → 512 维 L2 归一化嵌入；不可用时返回 ``None``。"""
        out = self.embed_many([(frame_rgb, box)])
        return out[0]

    def embed_many(self, items: Sequence[Tuple[object, dict]]) -> List[Optional[np.ndarray]]:
        """批量提取。``items`` 是 ``[(frame_rgb, box), ...]``，**帧须为 RGB**。

        返回与 ``items`` **等长**的列表，取不到的槽位为 ``None``
        —— 调用方按位置对应，不需要自己再对齐一次。

        整批一次推理：批大小为 1 时约 6 ms，为 3 时约 15 ms（本机实测），
        所以「多人共帧」场景批处理比逐张更省。
        """
        if not items:
            return []
        return self.embed_crops([crop_person(f, b) for f, b in items])

    def embed_crops(self, crops_rgb: Sequence[Optional[object]]) -> List[Optional[np.ndarray]]:
        """**已裁剪**的 RGB 图列表 → 嵌入列表（等长，失败槽位 ``None``）。

        给「裁剪与推理分离」的调用方用：例如录制旁路 ``core/reid_probe.py``
        在后台线程里持有裁剪图，避免重复裁剪。
        """
        result: List[Optional[np.ndarray]] = [None] * len(crops_rgb)
        tensors, slots = [], []
        for idx, crop in enumerate(crops_rgb):
            t = to_model_input(crop)
            if t is None:
                continue
            tensors.append(t)
            slots.append(idx)
        if not tensors:
            return result
        embs = self.embed_tensors(tensors)
        for k, idx in enumerate(slots):
            e = embs[k]
            if e is not None:
                result[idx] = e
        return result

    def embed_tensors(self, tensors: Sequence[np.ndarray]) -> List[Optional[np.ndarray]]:
        """**已预处理**的 ``(3, 256, 128)`` 张量列表 → 一次批量推理。

        返回等长列表；会话不可用、推理异常、或输出行数与送入不符时**整批**返回
        ``None`` —— 宁可整体放弃，也不把错位的特征按位置发出去。
        """
        result: List[Optional[np.ndarray]] = [None] * len(tensors)
        if not tensors:
            return result
        if not self.load():
            return result

        batch = np.stack(list(tensors), axis=0)
        try:
            raw = self._session.run(None, {self._input_name: batch})[0]
        except Exception as exc:                       # noqa: BLE001 - 如实上报
            self.load_error = f'推理失败：{type(exc).__name__}: {exc}'
            return result
        emb = l2_normalize(np.asarray(raw, dtype=np.float32))
        if emb.shape[0] != len(tensors):
            self.load_error = (f'输出行数 {emb.shape[0]} 与送入 {len(tensors)} 不符')
            return result
        for k in range(len(tensors)):
            result[k] = emb[k]
        return result


__all__ = [
    'DEFAULT_MODEL_PATH',
    'DEFAULT_THREADS',
    'EMBED_DIM',
    'INPUT_HW',
    'MIN_BOX_H_PX',
    'MIN_CROP_PX',
    'OsnetEmbedder',
    'crop_person',
    'embedding_similarity',
    'l2_normalize',
    'to_model_input',
]
