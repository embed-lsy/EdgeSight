"""录制与回放。

定位对应：`CHARTER.md`「范围内的」第 6 条（录制回放）。

为什么需要它
------------
CHARTER 的成功判据里有一条是「**有录制回放：能录一段视频并事后回放分析，
不依赖现场路况即可演示**」。这条不是锦上添花 —— 它解决的是两个真实约束：

1. **本机只有摄像头、没有车**：几何测距的精度依赖目标处在真实距离上，
   而现场路况不可复现。录下来才能反复标定与调参。
2. **面试演示需要确定性**：现场拿摄像头对着桌子演示，效果不可控。
   回放一段已知距离的录制，是唯一能稳定复现的演示方式。

设计要点
--------
**双轨设计——视频轨与数据轨分离**

- **视频轨**：MJPG 编码写入 AVI，只存画面。这是"能看见"的部分。
- **数据轨**：JSONL 逐行追加，每帧记录检测框、测距值、时间戳。这是"能算"的部分。

之所以不把检测框烧进视频：那样标注信息会被编码进像素，事后无法重新调参、
无法重新测距、无法做双源互检的对比分析。分开存之后，**回放可以拿新参数
重新解算旧数据** —— 这正是"事后分析"的价值所在。

**写盘不阻塞主链路**

主链路要求 ≥8 FPS（CHARTER 门槛判据）。视频编码是 CPU 密集操作，
如果在 `update_camera_frame` 里同步 `writer.write()`，会直接拖垮帧率。
所以采用**队列 + 独立写盘线程**：主线程只做 `put_nowait`，
队列满了就丢帧并计数（丢帧比卡顿好，且丢帧数会显示在 UI 上，不隐瞒）。

**关于丢帧的诚实原则**

队列溢出时不是静默丢弃：`dropped_frames` 会累加并在 UI 显示。
一个"录了 100 帧但丢了 30 帧"的录制，和"录了 70 帧"是不同的事实，
使用者有权知道。
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# 录制文件布局
# ---------------------------------------------------------------------------
#
#   recordings/<会话名>/
#   ├── video.avi        视频轨（MJPG）
#   ├── frames.jsonl     数据轨（每行一个 JSON）
#   └── meta.json        会话元信息（开始时间、分辨率、帧数、丢帧数…）
#
# 用一个目录而不是单个文件：数据轨可追加、可单独解析，
# 视频编码失败也不至于连数据一起毁掉。
# ---------------------------------------------------------------------------


@dataclass
class RecordingMeta:
    """录制会话的元信息。写入 meta.json，回放时用于校验。"""

    session: str = ''                 # 会话名（目录名）
    started_at: float = 0.0           # Unix 时间戳
    finished_at: float = 0.0
    width: int = 0
    height: int = 0
    fps_nominal: float = 30.0         # 写入 VideoWriter 的名义帧率
    frame_count: int = 0              # 实际写入视频的帧数
    data_count: int = 0               # 实际写入数据轨的记录数
    dropped_frames: int = 0           # 队列溢出丢弃数
    duration_s: float = 0.0
    calibrated_at_record: bool = False  # 录制时是否已标定（决定测距值是否可信）
    note: str = ''

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


@dataclass
class FrameRecord:
    """单帧的数据轨记录。

    字段对齐 ``YOLODetector.detection_ready`` 的字典结构，
    这样回放时可以直接把这条记录喂回既有的展示逻辑，不需要另写一套解析。
    """

    seq: int = 0                      # 帧序号（从 0 开始）
    t: float = 0.0                    # 相对录制开始的秒数
    wall_t: float = 0.0               # Unix 时间戳
    has_target: bool = False
    x: float = 0.0                    # 检测框中心 x
    y: float = 0.0                    # 检测框中心 y
    width: float = 0.0
    height: float = 0.0
    confidence: float = 0.0
    class_id: int = -1
    class_name: str = ''
    distance: Optional[float] = None  # 几何测距结果（米），None = 不可解算
    inference_fps: float = 0.0

    @classmethod
    def from_detection(cls, seq: int, t: float, target: Optional[dict],
                       class_name: str, distance: Optional[float],
                       inference_fps: float) -> 'FrameRecord':
        rec = cls(seq=seq, t=t, wall_t=time.time(),
                  inference_fps=float(inference_fps or 0.0))
        if target:
            rec.has_target = True
            rec.x = float(target.get('x', 0.0))
            rec.y = float(target.get('y', 0.0))
            rec.width = float(target.get('width', 0.0))
            rec.height = float(target.get('height', 0.0))
            rec.confidence = float(target.get('confidence', 0.0))
            rec.class_id = int(target.get('class_id', -1))
            rec.class_name = class_name or ''
            rec.distance = None if distance is None else float(distance)
        return rec


# ---------------------------------------------------------------------------
# 录制器
# ---------------------------------------------------------------------------

class Recorder:
    """把摄像头流与检测/测距结果落盘。

    用法::

        rec = Recorder(root='recordings', fps=30.0)
        rec.start(frame.shape)          # 开始（此时才创建目录与 writer）
        rec.push_frame(frame_bgr)       # 主链路每帧调用，非阻塞
        rec.push_record(record)         # 检测结果到达时调用
        meta = rec.stop()               # 结束并返回统计
    """

    def __init__(self, root: str = 'recordings', fps: float = 30.0,
                 queue_size: int = 300):
        """``queue_size`` 是写盘队列容量。

        默认 300 帧 ≈ 30FPS 下 10 秒缓冲。这个值的取舍：
        太小（如 60）→ 磁盘偶发卡顿就丢帧；太大 → 磁盘持续跟不上时
        会先囤积大量内存帧再集体丢弃，且"录制中"的帧数与实际写入
        差距拉大。10 秒缓冲足够跨过系统级抖动，又不至于囤积过多内存。
        （640×320×3 的帧一帧约 0.6MB，300 帧约 180MB 上限。）
        """
        self.root = root
        self.fps = float(fps)
        self.queue_size = queue_size

        self.session: Optional[str] = None
        self.session_dir: Optional[str] = None
        self._queue: Optional[queue.Queue] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._writer: Optional[cv2.VideoWriter] = None

        self._frame_count = 0
        self._dropped = 0
        self._records: List[FrameRecord] = []
        self._lock = threading.Lock()

        self.meta = RecordingMeta()
        self._running = False

    # -- 生命周期 -----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def dropped_frames(self) -> int:
        return self._dropped

    @property
    def record_count(self) -> int:
        return len(self._records)

    def start(self, frame_shape, calibrated: bool = False,
              session: Optional[str] = None) -> str:
        """开始录制。``frame_shape`` 是 (h, w, c)，用于初始化 VideoWriter。"""
        if self._running:
            raise RuntimeError('已在录制中')

        h, w = frame_shape[0], frame_shape[1]
        stamp = time.strftime('%Y%m%d-%H%M%S')
        self.session = session or f'session-{stamp}'
        self.session_dir = os.path.join(self.root, self.session)
        os.makedirs(self.session_dir, exist_ok=True)

        video_path = os.path.join(self.session_dir, 'video.avi')
        # MJPG + AVI 是 OpenCV 在 Windows 上最稳的组合，不依赖额外编解码器
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        self._writer = cv2.VideoWriter(video_path, fourcc, self.fps, (w, h))
        if not self._writer.isOpened():
            raise RuntimeError(f'无法创建视频文件：{video_path}')

        self.meta = RecordingMeta(
            session=self.session,
            started_at=time.time(),
            width=w, height=h,
            fps_nominal=self.fps,
            calibrated_at_record=calibrated,
        )

        self._queue = queue.Queue(maxsize=self.queue_size)
        self._stop_flag.clear()
        self._frame_count = 0
        self._dropped = 0
        self._records = []

        self._thread = threading.Thread(target=self._writer_loop,
                                        name='RecorderWriter', daemon=True)
        self._thread.start()
        self._running = True
        return self.session_dir

    def push_frame(self, frame_bgr: np.ndarray) -> bool:
        """主链路投入一帧。**非阻塞**：队列满则丢帧并计数，返回 False。"""
        if not self._running or self._queue is None:
            return False
        try:
            self._queue.put_nowait(frame_bgr)
            self._frame_count += 1
            return True
        except queue.Full:
            self._dropped += 1
            return False

    def push_record(self, record: FrameRecord) -> None:
        """记录一帧的检测/测距数据。与视频帧分开存，互不阻塞。"""
        if not self._running:
            return
        with self._lock:
            self._records.append(record)

    def stop(self) -> RecordingMeta:
        """结束录制，等待写盘线程收尾，落盘数据轨与元信息。"""
        if not self._running:
            return self.meta

        self._running = False
        self._stop_flag.set()

        # 等队列排空（最多 10 秒，避免卡死界面）
        if self._thread is not None:
            self._thread.join(timeout=10.0)

        if self._writer is not None:
            self._writer.release()
            self._writer = None

        self.meta.finished_at = time.time()
        self.meta.frame_count = self._frame_count
        self.meta.dropped_frames = self._dropped
        self.meta.data_count = len(self._records)
        self.meta.duration_s = (self.meta.finished_at - self.meta.started_at
                                if self.meta.started_at else 0.0)

        self._write_data_track()
        self._write_meta()
        return self.meta

    # -- 内部 ---------------------------------------------------------------

    def _writer_loop(self) -> None:
        """独立线程：从队列取帧写视频。这里是唯一碰 VideoWriter 的地方。"""
        while not (self._stop_flag.is_set() and self._queue.empty()):
            try:
                frame = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if self._writer is not None:
                    self._writer.write(frame)
            except Exception as e:
                print(f'[录制] 写帧失败：{e}')

    def _write_data_track(self) -> None:
        if not self.session_dir:
            return
        path = os.path.join(self.session_dir, 'frames.jsonl')
        with open(path, 'w', encoding='utf-8') as f:
            for rec in self._records:
                f.write(json.dumps(asdict(rec), ensure_ascii=False) + '\n')

    def _write_meta(self) -> None:
        if not self.session_dir:
            return
        path = os.path.join(self.session_dir, 'meta.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.meta.to_json())


# ---------------------------------------------------------------------------
# 回放
# ---------------------------------------------------------------------------

class Replayer:
    """读取一次录制，按原始节奏吐出帧与记录。

    不使用 QThread —— 回放由主线程的 QTimer 驱动（与摄像头取帧同构），
    这样回放路径和实时路径在 UI 层共用同一套显示逻辑，
    避免"实时能跑、回放跑不了"这类只在演示时暴露的问题。
    """

    def __init__(self, session_dir: str):
        self.session_dir = session_dir
        self.meta = self._load_meta()
        self.records: List[FrameRecord] = self._load_records()
        self._cap: Optional[cv2.VideoCapture] = None
        self._index = 0

    # -- 加载 ---------------------------------------------------------------

    def _load_meta(self) -> RecordingMeta:
        path = os.path.join(self.session_dir, 'meta.json')
        if not os.path.isfile(path):
            return RecordingMeta(session=os.path.basename(self.session_dir))
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        known = set(RecordingMeta.__dataclass_fields__)
        return RecordingMeta(**{k: v for k, v in data.items() if k in known})

    def _load_records(self) -> List[FrameRecord]:
        path = os.path.join(self.session_dir, 'frames.jsonl')
        if not os.path.isfile(path):
            return []
        out: List[FrameRecord] = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue   # 容忍写到一半的行，不因一行坏掉整个回放
                known = set(FrameRecord.__dataclass_fields__)
                out.append(FrameRecord(**{k: v for k, v in data.items()
                                          if k in known}))
        return out

    @staticmethod
    def list_sessions(root: str) -> List[str]:
        """列出 root 下所有看起来像录制会话的目录（含 video.avi）。"""
        if not os.path.isdir(root):
            return []
        out = []
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, 'video.avi')):
                out.append(d)
        return out

    # -- 播放控制 -----------------------------------------------------------

    @property
    def total_frames(self) -> int:
        if self.meta.frame_count:
            return int(self.meta.frame_count)
        return len(self.records)

    @property
    def position(self) -> int:
        return self._index

    @property
    def finished(self) -> bool:
        return self._index >= self.total_frames

    @property
    def progress(self) -> float:
        total = self.total_frames
        return (self._index / total) if total else 0.0

    def open(self) -> bool:
        path = os.path.join(self.session_dir, 'video.avi')
        self._cap = cv2.VideoCapture(path)
        self._index = 0
        return bool(self._cap is not None and self._cap.isOpened())

    def read(self):
        """读下一帧。返回 ``(frame_bgr, record_or_None)``，结束后返回 (None, None)。"""
        if self._cap is None:
            return None, None
        ok, frame = self._cap.read()
        if not ok:
            return None, None
        idx = self._index
        self._index += 1
        rec = None
        if 0 <= idx < len(self.records):
            rec = self.records[idx]
        return frame, rec

    def seek(self, index: int) -> bool:
        """跳转到指定帧。用于在分析曲线上点选定位。"""
        if self._cap is None:
            return False
        index = max(0, min(index, max(self.total_frames - 1, 0)))
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        self._index = index
        return True

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # -- 分析辅助 -----------------------------------------------------------

    def distance_series(self):
        """返回 (时间序列, 距离序列)，跳过不可解算的帧。

        只回传有值的点：测距不可用时不应在曲线上画 0 ——
        0 米是一个"有效的错误读数"，而 None 是"没有读数"，两者不能混。
        """
        ts, ds = [], []
        for r in self.records:
            if r.distance is not None:
                ts.append(r.t)
                ds.append(r.distance)
        return ts, ds

    def summary(self) -> Dict[str, Any]:
        """回放数据的统计摘要，用于事后分析面板。"""
        with_dist = [r for r in self.records if r.distance is not None]
        confs = [r.confidence for r in self.records if r.has_target]
        return {
            'session': self.meta.session,
            'duration_s': self.meta.duration_s,
            'frame_count': self.meta.frame_count,
            'data_count': len(self.records),
            'dropped_frames': self.meta.dropped_frames,
            'calibrated_at_record': self.meta.calibrated_at_record,
            'target_frames': sum(1 for r in self.records if r.has_target),
            'ranged_frames': len(with_dist),
            'distance_min': min((r.distance for r in with_dist), default=None),
            'distance_max': max((r.distance for r in with_dist), default=None),
            'confidence_mean': (sum(confs) / len(confs)) if confs else None,
        }
