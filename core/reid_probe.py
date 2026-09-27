"""录制旁路：把每帧的 OSNet 外观嵌入**只记录、不决策**地落盘。

## 这个模块为什么存在

CHARTER v1.4 的「认人判据」（正面/背面各 10 次、≥8/10 认出；未登记者 ≥9/10 拒绝）
**当前没有数据可判** —— 录制主体很可能始终是同一个人，缺「未登记者」的负样本。
匹配阈值与「匹配分级」的高/中/低切点因此都没有依据。

本模块的任务就是**把定阈值所需的原始数据采下来**：每帧记一条该人的 OSNet 嵌入，
事后在离线脚本里算「同人配对相似度」与「异人配对相似度」两条分布，阈值与切点才谈得上。

## 硬边界：只记录，不决策

- ``submit()`` 的**返回值不携带任何判定**，主链路不得据此改变追踪/测距/UI 行为；
- 本模块不读 ``person_profile.json``，不写档案，不参与匹配分级；
- 训练/微调模型属 CHARTER「明确不做」——这里只用预训练权重做**推理**。

## 为什么不阻塞主链路

``OsnetEmbedder`` 单张约 6 ms（4 线程）/ 约 9 ms（2 线程，本机实测）。
检测回调跑在**主线程**（``detection_ready`` 是跨线程 queued signal），
直接在里面推理会卡界面。所以照搬 ``core/recorder.py`` 的做法：

- 主线程 ``submit()`` 只把「帧引用 + 框副本」放进**有界队列**（零图像处理，微秒级）；
- 独立 daemon 线程取帧 → 裁剪 → BGR→RGB → 批量推理 → 写 ``reid.jsonl``；
- 队列满则**丢弃并计数**（``dropped``），绝不反压主链路。

## 落盘格式

``<会话目录>/reid.jsonl``，每行一条：

    {"seq":18,"t":1.2043,"x":320.0,"y":240.0,"width":78.0,"height":196.0,
     "confidence":0.86,"class_name":"person","ms":4.51,"emb_b64":"..."}

``emb_b64`` 是 512 维 float32 的 base64（2048 字节 → 2732 ASCII 字符），**无损**；
比直接写 JSON 浮点数组紧凑约 2.5 倍。解码见本模块的 ``decode_embedding()``。

``seq`` 与 ``frames.jsonl`` **同源**（都取自 ``FrameRecord.seq``），
所以两轨可按 seq 精确关联（距离、时间戳、框都在 ``frames.jsonl`` 里，此处不重复存）。

``<会话目录>/reid_meta.json`` 记模型哈希、预处理口径、计数与耗时 —— 让半年后
的离线分析不必回头读代码就能还原当时的口径。

## 怎么用（主链路）

    probe = ReidProbe(session_dir)
    if probe.start():                      # 模型缺失/盘不可写时返回 False，不抛
        ...
        probe.submit(frame_bgr, target, seq=self._rec_seq, t=elapsed)
        ...
        stats = probe.stop()               # {'accepted','dropped','written','errors',...}
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from core.reid_osnet import (
    DEFAULT_MODEL_PATH,
    EMBED_DIM,
    INPUT_HW,
    MIN_BOX_H_PX,
    OsnetEmbedder,
    crop_person,
)

# 落盘文件名（与 ``frames.jsonl`` / ``meta.json`` 并列放在会话目录下）
REID_TRACK_NAME = 'reid.jsonl'
REID_META_NAME = 'reid_meta.json'

# 后台线程数。**刻意低于检测的 4 线程**：ReID 是旁路，检测是主链路，
# 两者同机并发时不能抢核。本机实测单张耗时（空载、独立进程、两轮一致）：
#   1 线程 23.7 / 29.6 ms   2 线程 9.2 / 9.0 ms   4 线程 5.9 / 6.0 ms
# 取 2：9 ms 远低于 30 FPS 的 33 ms 帧预算，且只占 2 个逻辑核。
DEFAULT_PROBE_THREADS = 2

# 队列深度。8 帧约 7 MB（640×480×3 的整帧引用），积压超限即丢帧并计数。
DEFAULT_QUEUE_SIZE = 8
# 单次推理最多凑多少张 —— 批处理摊销更好，但延迟不能太大。
DEFAULT_MAX_BATCH = 8


# ---------------------------------------------------------------------------
# 编解码（离线分析用，不依赖 cv2 / onnxruntime）
# ---------------------------------------------------------------------------

def encode_embedding(vec) -> str:
    """512 维 float32 → base64 字符串。**纯函数、无损**。"""
    a = np.asarray(vec, dtype=np.float32).ravel()
    return base64.b64encode(a.tobytes()).decode('ascii')


def decode_embedding(text: str) -> Optional[np.ndarray]:
    """base64 → ``(512,)`` float32。长度不符或解码失败时返回 ``None``。"""
    if not text:
        return None
    try:
        raw = base64.b64decode(text)
    except Exception:                                  # noqa: BLE001 - 损坏行不该炸掉整个分析
        return None
    a = np.frombuffer(raw, dtype=np.float32)
    if a.size != EMBED_DIM:
        return None
    return a.copy()                                    # frombuffer 是只读视图，拷一份更稳


def load_probe_track(session_dir: str) -> Tuple[dict, List[dict]]:
    """读一个会话的旁路轨 → ``(meta, records)``。

    ``records`` 每项为 ``{'seq','t','box','confidence','class_name','ms','emb'}``，
    ``emb`` 是 ``(512,)`` float32（已 L2 归一化）。坏行跳过并计数在 ``meta['bad_lines']``。
    供离线定阈值脚本使用，不需要 cv2 或 onnxruntime。
    """
    meta_path = os.path.join(session_dir, REID_META_NAME)
    jsonl_path = os.path.join(session_dir, REID_TRACK_NAME)
    meta: dict = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            meta = {'meta_read_error': f'{type(exc).__name__}: {exc}'}

    records: List[dict] = []
    bad = 0
    if os.path.isfile(jsonl_path):
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    emb = decode_embedding(row.get('emb_b64', ''))
                    if emb is None:
                        bad += 1
                        continue
                    records.append({
                        'seq': int(row.get('seq', 0)),
                        't': float(row.get('t', 0.0)),
                        'box': {k: float(row.get(k, 0.0))
                                for k in ('x', 'y', 'width', 'height')},
                        'confidence': float(row.get('confidence', 0.0)),
                        'class_name': str(row.get('class_name', '')),
                        'ms': float(row.get('ms', 0.0)),
                        'emb': emb,
                    })
                except (json.JSONDecodeError, TypeError, ValueError):
                    bad += 1
    meta['bad_lines'] = bad
    meta['record_count'] = len(records)
    return meta, records


def _file_sha256(path: str, chunk: int = 1 << 20) -> str:
    """文件 sha256；读不到时返回空串（不抛）。"""
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for blk in iter(lambda: f.read(chunk), b''):
                h.update(blk)
        return h.hexdigest()
    except OSError:
        return ''


# ---------------------------------------------------------------------------
# 旁路记录器
# ---------------------------------------------------------------------------

class ReidProbe:
    """把每帧的 ReID 嵌入写进会话目录的旁路轨。**只记录，不决策**。

    ``start()`` 失败（模型缺失、目录不可写）时返回 ``False`` 并在 ``last_error``
    里说明原因 —— 主链路应把它当成「本次不采数据」，而不是异常。
    """

    def __init__(self, session_dir: str, *,
                 model_path: Optional[str] = None,
                 threads: int = DEFAULT_PROBE_THREADS,
                 queue_size: int = DEFAULT_QUEUE_SIZE,
                 max_batch: int = DEFAULT_MAX_BATCH):
        self.session_dir = session_dir
        self.jsonl_path = os.path.join(session_dir, REID_TRACK_NAME)
        self.meta_path = os.path.join(session_dir, REID_META_NAME)
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.threads = int(threads)
        self.queue_size = int(queue_size)
        self.max_batch = int(max_batch)

        self._embedder: Optional[OsnetEmbedder] = None
        self._queue: Optional[queue.Queue] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._file = None
        self._lock = threading.Lock()
        self._running = False

        self._accepted = 0
        self._dropped = 0
        self._written = 0
        self._errors = 0
        self._infer_ms_total = 0.0
        # 稳态耗时（排除含「建 ORT 会话」开销的首批，见 _process_batch）。
        # 分子是**批**总耗时，分母是**帧**数 —— 摊销必须落在「每帧」上，
        # 否则批大小一变，同一个模型会报出完全不同的数（踩过：5 帧一批时
        # 报 54.8 ms，其实是 5 帧合计，每帧只有 11.0 ms）。
        self._steady_ms_total = 0.0
        self._steady_frames = 0
        self._steady_batches = 0
        self._steady_seen = False
        self._first_batch_ms = 0.0
        self._started_at = 0.0
        self._finished_at = 0.0
        self.last_error: Optional[str] = None

    # -- 生命周期 ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """准备工作：建文件、起写线程。**不建 ORT 会话**（那在写线程首次推理时做，
        否则主线程会被会话构建冻住 0.1–0.3 s）。"""
        if self._running:
            return False
        self._embedder = OsnetEmbedder(self.model_path, threads=self.threads)
        if not self._embedder.available():
            self.last_error = f'ReID 模型不存在，本次不采集：{self.model_path}'
            return False
        try:
            os.makedirs(self.session_dir, exist_ok=True)
            self._file = open(self.jsonl_path, 'w', encoding='utf-8')
        except OSError as exc:
            self.last_error = f'旁路文件无法写入：{type(exc).__name__}: {exc}'
            self._file = None
            return False

        self._queue = queue.Queue(maxsize=self.queue_size)
        self._stop_flag.clear()
        self._accepted = self._dropped = self._written = self._errors = 0
        self._infer_ms_total = 0.0
        self._steady_ms_total = 0.0
        self._steady_frames = 0
        self._steady_batches = 0
        self._steady_seen = False
        self._first_batch_ms = 0.0
        self._started_at = time.time()
        self._finished_at = 0.0
        self.last_error = None
        self._thread = threading.Thread(target=self._worker_loop,
                                        name='ReidProbeWriter', daemon=True)
        self._thread.start()
        self._running = True
        return True

    def stop(self) -> Dict[str, object]:
        """收尾：等写线程排空（最多 10 s）、写 ``reid_meta.json``、返回统计。"""
        if not self._running:
            return self.stats
        self._running = False
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=10.0)
            if self._thread.is_alive():
                self.last_error = (self.last_error
                                   or '写线程未在 10 s 内结束，已放弃等待')
            self._thread = None
        self._finished_at = time.time()
        leftover = self._queue.qsize() if self._queue is not None else 0
        if self._file is not None:
            try:
                self._file.flush()
            except OSError as exc:
                self.last_error = f'收尾 flush 失败：{exc}'
            finally:
                try:
                    self._file.close()
                finally:
                    self._file = None
        self._write_meta(leftover)
        return self.stats

    @property
    def stats(self) -> Dict[str, object]:
        """计数快照。**不表达任何判定**，只说明「采了多少、丢了多少、错了几条」。"""
        with self._lock:
            total_ms = self._infer_ms_total
        amortised = (round(self._steady_ms_total / self._steady_frames, 3)
                     if self._steady_frames else 0.0)
        return {
            'enabled': self._running or self._written > 0,
            'accepted': self._accepted,
            'dropped': self._dropped,
            'written': self._written,
            'errors': self._errors,
            'infer_ms_total': round(total_ms, 1),
            'infer_ms_amortised': amortised,
            'first_batch_ms': round(self._first_batch_ms, 1),
            'steady_batches': self._steady_batches,
            'steady_frames': self._steady_frames,
            'jsonl': self.jsonl_path,
            'last_error': self.last_error,
        }

    # -- 主链路接口（非阻塞）----------------------------------------------

    def submit(self, frame_bgr, box, *, seq: int, t: float,
               class_name: str = '') -> bool:
        """投一帧。**非阻塞、零图像处理**：只把帧引用与框副本入队。

        框高小于 ``MIN_BOX_H_PX`` 时直接早退（那种尺寸裁出来全是插值糊的，
        特征无意义，入队只是白耗 CPU）。队列满则丢弃并计数。

        ⚠️ 传进来的是 **BGR** 帧（项目惯例）；BGR→RGB 在写线程里做。
        """
        if not self._running or self._queue is None:
            return False
        if frame_bgr is None or not isinstance(box, dict):
            return False
        try:
            if float(box.get('height', 0.0) or 0.0) < MIN_BOX_H_PX:
                return False
        except (TypeError, ValueError):
            return False
        item = (frame_bgr, dict(box), int(seq), float(t), str(class_name or ''))
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self._dropped += 1
            return False
        self._accepted += 1
        return True

    # -- 写线程 -----------------------------------------------------------

    def _worker_loop(self) -> None:
        """独立线程：取帧 → 裁剪 → 转 RGB → 批量推理 → 写 jsonl。

        这里是**唯一**碰 ONNX 会话与文件的地方。
        """
        while not (self._stop_flag.is_set() and (self._queue is None
                                                or self._queue.empty())):
            batch = [self._get_one()]
            if batch[0] is None:
                batch = []
            while len(batch) < self.max_batch:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            if batch:
                self._process_batch(batch)

    def _get_one(self):
        """阻塞取一条；超时返回 ``None``（让循环回去检查停止标志）。"""
        try:
            return self._queue.get(timeout=0.2)
        except queue.Empty:
            return None

    def _process_batch(self, batch: Sequence[tuple]) -> None:
        if not batch:
            return
        if self._embedder is None:
            return
        crops = [crop_person(frame, box) for frame, box, _s, _t, _c in batch]
        # ⚠️ 项目帧是 BGR（OpenCV），OSNet 的训练/评测口径是 RGB，这里按口径转换。
        # 至于「不转会怎样」：现有数据上**测不出判别力差别**，但那只说明数据不够
        # （没有第二位真人，rank-1 已饱和在 95%）—— 详见 reid_osnet 模块 docstring
        # 的「实测边界」一节。不拿"测不出差别"当"可以省"。
        rgb = [None if c is None else cv2.cvtColor(c, cv2.COLOR_BGR2RGB)
               for c in crops]

        t0 = time.perf_counter()
        embs = self._embedder.embed_crops(rgb)
        batch_ms = (time.perf_counter() - t0) * 1000.0
        # 第一批含 ONNX 会话构建（0.1–0.3 s），混进摊销会把「稳态每帧耗时」
        # 报成十几毫秒的假值。所以首批单独记，稳态摊销只用后续批次。
        if not self._steady_seen:
            self._steady_seen = True
            self._first_batch_ms = batch_ms
        else:
            with self._lock:
                self._steady_ms_total += batch_ms
                self._steady_frames += len(batch)
                self._steady_batches += 1
        per_ms = batch_ms / max(len(batch), 1)

        if self._embedder.load_error:
            self.last_error = self._embedder.load_error
            self._errors += 1

        lines: List[str] = []
        for (frame, box, seq, t, cls), emb in zip(batch, embs):
            if emb is None:
                self._errors += 1
                continue
            lines.append(self._json_line(seq, t, box, cls, emb, per_ms))
        if not lines:
            return
        try:
            self._file.write(''.join(lines))
            self._file.flush()
        except (OSError, ValueError) as exc:
            self._errors += len(lines)
            self.last_error = f'写旁路轨失败：{type(exc).__name__}: {exc}'
            return
        with self._lock:
            self._written += len(lines)
            self._infer_ms_total += batch_ms
    @staticmethod
    def _json_line(seq: int, t: float, box: dict, cls: str,
                   emb, ms: float) -> str:
        payload = {
            'seq': int(seq),
            't': round(float(t), 4),
            'x': float(box.get('x', 0.0) or 0.0),
            'y': float(box.get('y', 0.0) or 0.0),
            'width': float(box.get('width', 0.0) or 0.0),
            'height': float(box.get('height', 0.0) or 0.0),
            'confidence': float(box.get('confidence', 0.0) or 0.0),
            'class_name': str(cls or ''),
            'ms': round(float(ms), 3),
            'emb_b64': encode_embedding(emb),
        }
        return json.dumps(payload, ensure_ascii=False) + '\n'

    # -- 元信息 -----------------------------------------------------------

    def _write_meta(self, leftover: int = 0) -> None:
        """写 ``reid_meta.json``：模型哈希 + 预处理口径 + 计数。

        目的是让半年后的离线分析**不必回头读代码**就能还原当时的口径
        （通道顺序、归一化、裁剪范围、线程数都是会静默影响数值的东西）。
        """
        stats = self.stats
        written = self._written
        meta = {
            'kind': 'reid-probe',
            'note': '旁路 —— 只记录，不参与任何追踪 / 测距 / 显示判定',
            'model': self.model_path,
            'model_sha256': _file_sha256(self.model_path),
            'emb_dim': EMBED_DIM,
            'emb_dtype': 'float32',
            'emb_encoding': 'base64 (numpy float32 .tobytes())',
            'input_hw': list(INPUT_HW),
            'color_project_frames': 'BGR (OpenCV 惯例)',
            'color_model_input': 'RGB (本模块内部 cv2.COLOR_BGR2RGB)',
            'normalize': 'uint8/255 -> ImageNet mean [0.485,0.456,0.406] / std [0.229,0.224,0.225]',
            'crop': 'whole person box, x/y 为框中心',
            'min_box_height_px': MIN_BOX_H_PX,
            'threads': self.threads,
            'queue_size': self.queue_size,
            'max_batch': self.max_batch,
            'seq_source': 'FrameRecord.seq —— 与同目录 frames.jsonl 同源，可按 seq 关联',
            'accepted': stats['accepted'],
            'dropped': stats['dropped'],
            'written': written,
            'errors': stats['errors'],
            'pending_at_stop': int(leftover),
            'infer_ms_total': stats['infer_ms_total'],
            'infer_ms_amortised': stats['infer_ms_amortised'],
            'first_batch_ms': stats['first_batch_ms'],
            'steady_batches': stats['steady_batches'],
            'steady_frames': stats['steady_frames'],
            'infer_ms_note': ('摊销只统计稳态批次，且分母是**帧数**（不是批数）；'
                              '首批含 ONNX 会话构建开销，单列在 first_batch_ms'),
            'started_at': self._started_at,
            'finished_at': self._finished_at,
            'duration_s': (round(self._finished_at - self._started_at, 2)
                           if self._started_at else 0.0),
            'last_error': self.last_error,
        }
        try:
            with open(self.meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            self.last_error = f'写旁路元信息失败：{exc}'


__all__ = [
    'DEFAULT_MAX_BATCH',
    'DEFAULT_PROBE_THREADS',
    'DEFAULT_QUEUE_SIZE',
    'REID_META_NAME',
    'REID_TRACK_NAME',
    'ReidProbe',
    'decode_embedding',
    'encode_embedding',
    'load_probe_track',
]
