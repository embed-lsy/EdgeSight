"""
相机标定与几何测距。

定位对应：`CHARTER.md`「范围内的」第 1 条（真标定）+ 第 2 条（几何测距）。

设计说明
--------
替换原先的伪距公式 ``distance = base_width / detection_width``。
该公式有三个问题：

1. **基准宽度是手工填的常数**，与真实相机参数无关，换台相机就失效；
2. **假设目标物理宽度恒定**，但只对单一类别成立（人、车宽度差一个量级）；
3. **完全忽略相机俯仰角**，目标偏离画面中心时距离系统性偏大。

本模块改为两段式：

- **标定**：用棋盘格求解相机内参（fx, fy, cx, cy）与畸变系数，
  标定结果持久化为 JSON，换相机只需重标一次。
- **测距**：pinhole 投影的逆运算。已知目标真实高度 H 与像素高度 h，
  则距离 ``Z = fy * H / h``；再按目标底边相对主点的像素偏移，
  用俯仰角修正得到沿地面的水平距离。

公式推导（测距）
----------------
相机坐标系下，目标底部中点 ``(u, v)`` 对应一条射线。设相机光轴水平时:

    Z_cam = fy * H / h            # 沿光轴的深度
    Y_cam = (v - cy_px) * Z_cam / fy   # 目标底部相对主点的高度偏移

若相机有俯仰角 ``pitch``（向下为正），地面上的目标水平距离为:

    Z_ground = Z_cam * cos(pitch) + Y_cam_abs * sin(pitch)

即把「光轴深度」投影回地面。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from typing import Optional, Tuple

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class CameraIntrinsics:
    """相机内参。单位除注明外均为像素。"""

    fx: float = 0.0
    fy: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    dist_coeffs: list = field(default_factory=list)  # k1, k2, p1, p2, k3
    image_size: Tuple[int, int] = (0, 0)            # (width, height)
    rms_error: float = 0.0                          # 重投影误差，越小越好
    calibrated: bool = False

    def is_valid(self) -> bool:
        return (
            self.calibrated
            and self.fx > 0
            and self.fy > 0
            and self.image_size[0] > 0
            and self.image_size[1] > 0
        )


@dataclass
class RangingConfig:
    """几何测距所需的、代码里看不出来的约束。

    ``object_heights`` 是各类别目标的真实高度（米）。这是测距精度的**首要来源**，
    因为距离与目标真实高度成正比 —— 高度估错 20%，距离就错 20%。
    """

    object_heights: dict = field(default_factory=lambda: {
        # COCO 常见类别，单位：米。取该类别的中等偏上个体，偏保守。
        'person': 1.70,
        'bicycle': 1.00,
        'car': 1.50,
        'motorcycle': 1.10,
        'bus': 3.20,
        'truck': 3.20,
    })
    default_height: float = 1.50   # 类别未登记时的兜底高度
    pitch_deg: float = 0.0         # 相机俯仰角，向下为正，单位度
    min_pixel_height: int = 8      # 像素高度低于此值时不测距（噪声不可信）

    def height_for(self, class_name: str) -> float:
        return self.object_heights.get(class_name, self.default_height)

    @classmethod
    def from_params(cls, params) -> 'RangingConfig':
        """从 ``GlobalParams`` 构造。

        让 UI 上的调节项（俯仰角、高度表）与测距逻辑共用同一份数据，
        避免两处各写一份默认值、日后改一处忘另一处。
        """
        return cls(
            object_heights=dict(getattr(params, 'object_heights', {}) or {}),
            default_height=float(getattr(params, 'default_object_height', 1.50)),
            pitch_deg=float(getattr(params, 'pitch_deg', 0.0)),
            min_pixel_height=int(getattr(params, 'min_pixel_height', 8)),
        )


# ---------------------------------------------------------------------------
# 标定
# ---------------------------------------------------------------------------

MIN_CALIB_FRAMES = 4        # 少于 4 帧方程数不足，解必然退化


def solve_intrinsics(object_points, image_points, image_size) -> CameraIntrinsics:
    """由棋盘角点求解相机内参 —— **纯函数**，不碰 UI、不碰线程。

    为什么单独抽出来（CHARTER 开发纪律「先单独验证工具函数，再接上层」）：

    1. ``cv2.calibrateCamera`` 是**秒级长任务** —— 本机实测 50 帧 640x480
       耗时 **17.06 s**（见 `E:\\WorkBuddy-Work\\scripts\\measure_ui_block.py`）；
    2. 抽成纯函数后可以脱离 UI 单独测「解得对不对、要多久」；
    3. UI 里只把它丢进子线程执行，主线程全程不碰 OpenCV，界面不会被冻住。

    参数
    ----
    object_points : 各帧棋盘角点的世界坐标（z=0 平面）
    image_points  : 各帧检出的角点像素坐标，与 object_points 一一对应
    image_size    : (width, height)，像素
    """
    n = len(image_points)
    if n < MIN_CALIB_FRAMES:
        raise ValueError(
            f'标定帧数不足（当前 {n} 帧，至少需要 {MIN_CALIB_FRAMES} 帧，'
            f'建议 10 帧以上且棋盘格姿态有变化）'
        )
    if not image_size or image_size[0] <= 0 or image_size[1] <= 0:
        raise ValueError('没有可用的图像尺寸，请先采集帧')

    ret, mtx, dist, _, _ = cv2.calibrateCamera(
        object_points, image_points, image_size, None, None
    )

    return CameraIntrinsics(
        fx=float(mtx[0, 0]),
        fy=float(mtx[1, 1]),
        cx=float(mtx[0, 2]),
        cy=float(mtx[1, 2]),
        dist_coeffs=[float(v) for v in dist.ravel()],
        image_size=image_size,
        rms_error=float(ret),
        calibrated=True,
    )


class CameraCalibrator:
    """棋盘格标定器。

    使用流程::

        cal = CameraCalibrator(pattern_size=(9, 6), square_size=0.018)
        for frame in captures:
            ok = cal.add_frame(frame)      # 自动检测角点，返回是否成功
        intr = cal.calibrate()             # 求解内参
        cal.save('calib.json')

    其中 ``square_size`` 单位是**米**，必须与实物一致 —— 它决定了后续
    测距的尺度。填错的话，距离会等比例错。
    """

    def __init__(self, pattern_size: Tuple[int, int] = (9, 6),
                 square_size: float = 0.018):  # 18mm：与 EVALUATION.md 的 A4 打印图一致
        self.pattern_size = pattern_size      # 内角点数 (列, 行)
        self.square_size = square_size        # 方格边长，米
        self.object_points: list = []
        self.image_points: list = []
        self.image_size: Optional[Tuple[int, int]] = None
        self._last_corners = None
        self._last_preview = None

        # 棋盘格在世界坐标系中的 3D 点（z=0 平面）
        cols, rows = pattern_size
        objp = np.zeros((rows * cols, 3), np.float32)
        objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
        self._objp_template = objp * self.square_size

        # 角点检测的亚像素优化终止条件
        self._criteria = (
            cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001
        )

    # -- 采集 ---------------------------------------------------------------

    def add_frame(self, frame_bgr: np.ndarray) -> bool:
        """检测一帧中的棋盘格角点。返回 True 表示这一帧可用。"""
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        self.image_size = (gray.shape[1], gray.shape[0])

        found, corners = cv2.findChessboardCorners(
            gray, self.pattern_size,
            cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE,
        )
        if not found:
            self._last_corners = None
            self._last_preview = frame_bgr.copy()
            return False

        corners = cv2.cornerSubPix(
            gray, corners, (11, 11), (-1, -1), self._criteria
        )
        self.object_points.append(self._objp_template.copy())
        self.image_points.append(corners)
        self._last_corners = corners

        preview = frame_bgr.copy()
        cv2.drawChessboardCorners(preview, self.pattern_size, corners, found)
        self._last_preview = preview
        return True

    @property
    def frame_count(self) -> int:
        return len(self.image_points)

    def preview(self) -> Optional[np.ndarray]:
        """最近一帧的角点可视化（用于 UI 反馈标定质量）。"""
        return self._last_preview

    # -- 求解 ---------------------------------------------------------------

    def calibrate(self) -> CameraIntrinsics:
        """求解内参与畸变系数。建议至少 10 帧，且棋盘格姿态要有变化。

        ⚠️ 这是**同步阻塞**调用（本机实测 50 帧约 17 s）。
        UI 里不要直接调它 —— 必须走子线程（`CalibSolveThread`），
        否则整个界面会冻住十几秒（2026-09-23 用户实际故障）。
        """
        return solve_intrinsics(self.object_points, self.image_points,
                                self.image_size)

    # -- 持久化 -------------------------------------------------------------

    @staticmethod
    def save(intrinsics: CameraIntrinsics, path: str) -> None:
        payload = asdict(intrinsics)
        payload['image_size'] = list(payload['image_size'])
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    @staticmethod
    def load(path: str) -> Optional[CameraIntrinsics]:
        if not os.path.isfile(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['image_size'] = tuple(data.get('image_size', (0, 0)))
        known = {f for f in CameraIntrinsics.__dataclass_fields__}
        return CameraIntrinsics(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# 几何测距
# ---------------------------------------------------------------------------

class GeometricRanger:
    """由 2D 检测框 + 相机内参 + 目标真实高度，解算距离。

    对应 `CHARTER.md`「范围内的」第 2 条。
    与深度网络是**两种独立物理机制**，可交叉验证（第 4 条「双源互检」）。
    """

    def __init__(self, intrinsics: CameraIntrinsics,
                 config: Optional[RangingConfig] = None):
        self.intrinsics = intrinsics
        self.config = config or RangingConfig()

    def update_intrinsics(self, intrinsics: CameraIntrinsics) -> None:
        self.intrinsics = intrinsics

    def update_config(self, config: RangingConfig) -> None:
        """热更新测距参数（俯仰角在 UI 上调后立即生效，无需重标定）。"""
        self.config = config

    def distance(self, pixel_height: float, bottom_v: float,
                 class_name: str = '') -> Optional[float]:
        """解算目标到相机的水平距离（米）。

        参数
        ----
        pixel_height : 检测框的像素高度
        bottom_v     : 检测框**底边**中点的纵坐标（像素）—— 用底边而非中心，
                       因为底边对应目标与地面的接触点，才是真正的测距基准
        class_name   : 类别名，用于查表取真实高度

        返回 ``None`` 表示无法可靠测距（内参无效、目标太小等）。
        """
        if not self.intrinsics.is_valid():
            return None
        if pixel_height < self.config.min_pixel_height:
            return None

        real_h = self.config.height_for(class_name)
        fy = self.intrinsics.fy

        # 沿光轴的深度
        z_cam = fy * real_h / pixel_height

        # 目标底部相对主点的纵向偏移（向下为正）
        y_cam = (bottom_v - self.intrinsics.cy) * z_cam / fy

        # 俯仰角修正：把光轴深度投影回地面
        pitch = np.deg2rad(self.config.pitch_deg)
        z_ground = z_cam * np.cos(pitch) + abs(y_cam) * np.sin(pitch)

        return float(z_ground)

    def distance_from_box(self, box: dict, class_name: str = '') -> Optional[float]:
        """便捷入口：直接吃检测结果字典。

        ``box`` 需要 ``height`` 与 ``y``（框中心纵坐标）—— 与
        ``YOLODetector`` 产出的 ``detection_ready`` 字典字段一致。
        """
        return self.distance(
            pixel_height=box.get('height', 0.0),
            bottom_v=box.get('y', 0.0) + box.get('height', 0.0) / 2.0,
            class_name=class_name,
        )

    def focal_length_px(self) -> Optional[float]:
        """返回等效焦距（像素）。调试用。"""
        if not self.intrinsics.is_valid():
            return None
        return self.intrinsics.fy
