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
import math
import os
import time
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


# ---------------------------------------------------------------------------
# 类别名归一化（2026-09-25 22:14 录制实证：标签文件是用户可选的）
# ---------------------------------------------------------------------------
#
# 教训（session-20260925-221445/221525，人 0→2m→0 全程）：标签文件从英文
# ``coco_labels.txt`` 换成中文 ``coco_labels_cn.txt`` 后，检测回调给的类别名
# 变成「人」，而本模块所有 person 专属逻辑（宽度法近场兜底、反解身高判据、
# 宽高比体检、高度法）都在匹配英文 'person' —— **全部静默失效**，整段走路
# 过程 63%~68% 的帧判「不可测」（换标签前同类会话只有 15%~26%）。
# 而这不是罕见配置：models/labels/ 下两种标签文件并存，UI 上随手一切就中招。
#
# 修法：所有「按类别名查表/比较」的入口统一先过 ``canonical_class_name``。
# CHARTER v1.4（全链路唯一类别是「行人」）之后，归一化表只需保留 person 的
# 中英写法；其余类别名一律原样返回，落到下游兜底。TTC 走 class_id
# （整数），天然免疫。
CLASS_NAME_ALIASES = {
    # 中文 COCO 标签（coco_labels_cn.txt 实测用词） -> 规范英文名
    '人': 'person',
}


def canonical_class_name(name) -> str:
    """把标签文件给出的类别名归一化成模块内部用的规范英文名。**纯函数**。

    未知名字原样返回（交给下游的默认兜底，不猜、不抛异常）——
    标签文件是用户可换的，归一化层必须对没见过的名字保持惰性。
    """
    if not isinstance(name, str):
        return ''
    return CLASS_NAME_ALIASES.get(name.strip(), name.strip())


# ---------------------------------------------------------------------------
# 展示名（给人看的名字）—— 与 canonical_class_name 成对但方向相反
# ---------------------------------------------------------------------------
#
# canonical 是**内部**用的规范英文名（查表、比较、字典键全按它）；
# display 是**界面**上给人看的中文名。两者都吃「标签文件原文」这个输入。
#
# 为什么必须分开（2026-09-29 用户实测反馈：「目标距离分析曲线的人的曲线标签
# 怎么是 person」）：默认标签文件是 models/labels/coco80.txt（首行 'person'），
# 而曲线图例直接把这个内部名显示出来了 —— 同一张图上，一条线叫 'person'、
# 另一条「无读数」线叫中文『未知』，一中一英。内部名是**实现细节**
# （换标签文件就会变），不该泄漏进给人看的文字里。
#
# 惰性：没登记的名字原样返回（标签文件是用户可换的，展示层不猜、不崩）。
CLASS_DISPLAY_NAMES = {
    'person': '人',     # 与 models/labels/coco_labels_cn.txt 首行用词一致
}


def display_class_name(name) -> str:
    """把类别名翻成界面显示用的中文名。**纯函数**。

    先过 ``canonical_class_name`` 再查展示表，于是三种输入（英文标签文件
    的 ``'person'``、中文标签文件的 ``'人'``、未加载的 ``''``）都能落到
    同一个显示结果，且**幂等**（'人' 再翻一次还是 '人'）。

    ``'未知'`` 与未登记的名字原样返回 —— 前者是「无读数」档的既有文案，
    后者与 ``canonical_class_name`` 一样保持惰性。
    """
    if not isinstance(name, str):
        return ''
    s = name.strip()
    if not s:
        return ''
    return CLASS_DISPLAY_NAMES.get(canonical_class_name(s), s)


@dataclass
class RangingConfig:
    """几何测距所需的、代码里看不出来的约束。

    ``object_heights`` 是各类别目标的真实高度（米）。这是测距精度的**首要来源**，
    因为距离与目标真实高度成正比 —— 高度估错 20%，距离就错 20%。
    """

    object_heights: dict = field(default_factory=lambda: {
        # CHARTER v1.4：唯一类别是「行人」，单位米，取中等偏上个体，偏保守。
        'person': 1.70,
    })
    pitch_deg: float = 0.0         # 相机俯仰角，向下为正，单位度
    camera_height: float = 0.0     # 相机安装高度（米），卷尺量。0 = 未测量，接触点法不可用
    # 框底边相对**地面**的抬升量（米）—— 见 FOOT_OFFSET_MAX_M 的注释。
    foot_offset_m: float = 0.0
    min_pixel_height: int = 8      # 像素高度低于此值时不测距（噪声不可信）
    # 框宽高比先验 (下限, 上限)，用于判断「框底边是否真的是脚」。
    # 站立的人约 0.30~0.45，只有脸入画时接近 1.0，据此识别「框不是全身」。
    # （v1.4 类别收窄后，原先"不登记 car / bus"的理由随多类别一起消失。）
    # 上限 0.90（2026-09-26 实测修正）：0.75 会把**近场正常大框**整段误杀 ——
    # session-20260926-152834 里人走近后框 353x453~433x456（宽高比 0.76~0.95），
    # 这批帧脚未判出画（底缘欠检 26 px > 12 px 容差）走不了宽度法，又被
    # 0.75 上限拦掉，形成近场死区（该会话 46% 帧测不出距离的主因，曲线
    # 因此变成台阶、TTC 全程无告警）。person 是三维目标，走近时透视使
    # 可见宽度（含摆臂）涨得比可见高度快，0.76~0.89 属正常行走形态；
    # >0.90 仍按原意拦「横向的手、极端特写」。
    aspect_limits: dict = field(default_factory=lambda: {'person': (0.15, 0.90)})
    # 「反解判据」的容差：反解出的身高允许偏离登记身高的比例。
    # 这是判定「框底边到底是不是脚」的**主力判据**（见 estimate_target_height）；
    # 上表的 aspect_limits 因实测判别力为零，已降级为兜底。
    # 0.35 的依据：person 登记 1.70 -> 允许 [1.11, 2.30]，
    # 既能容纳 1.4 m 的矮个子与 2.0 m 的高个子，又能拦住实测中
    # 「被挡到腰 3.88 m」「只有下巴 3.58 m」这类不完整框。
    height_tolerance: float = 0.35
    # 宽度法（近场参考值，2026-09-25 P1+）：**已填安装高度**、脚出画（框底边被
    # 下沿裁掉）、左右未裁、且**框顶边在相机水平线以上**（`top_may_be_head`）
    # 时的兜底测法 Z = fx * W_真实 / 框宽。
    # 「顶边在水平线以上」是硬前提：相机只 0.64~1.2 m 高而人头在 1.4~2.0 m，
    # 头顶必定高于相机；只贴着下沿、顶边却掉到水平线以下的框是「不完整的
    # 目标」（上半身/一张脸），框宽不是肩宽，用它算会给出危险的错值
    # （实测 2 m 的目标被算成 4.54 m）。
    # W_真实 只认**指定的追踪目标**：指定了就用该目标档案
    # （models/person_profile.json）里量出的肩宽，否则用这里的默认值
    # （2026-09-30 收紧，此前会在未指定目标时借用「本帧匹配上的人」的值）。
    # 调用方每帧刷新一次，见 MainWindow._sync_ranging_width。
    person_width_m: float = 0.46   # 成年人肩宽默认值（米），参考级精度
    min_pixel_width: int = 40      # 框宽低于此值不启用宽度法（噪声不可信）

    def height_for(self, class_name: str) -> Optional[float]:
        """该类别登记的真实高度（米）。**未登记返回 None，不再给兜底值。**

        历史实现查不到表项时回落到 ``default_height``（1.50 m）—— 那等于
        **编一个身高去算距离**，与 CHARTER 第 4 条「拿不到可靠值就说不可测」
        直接冲突（2026-09-27 用户明确要求：非 person 拒绝出距离，已删除）。
        调用方必须自己处理 None（见 ``distance`` 与 ``measure_from_box``）。
        """
        return self.object_heights.get(canonical_class_name(class_name))

    @classmethod
    def from_params(cls, params) -> 'RangingConfig':
        """从 ``GlobalParams`` 构造。

        让 UI 上的调节项（俯仰角、高度表）与测距逻辑共用同一份数据，
        避免两处各写一份默认值、日后改一处忘另一处。
        """
        return cls(
            object_heights={
                canonical_class_name(k): v
                for k, v in (getattr(params, 'object_heights', {}) or {}).items()
            },
            # 无 default_height：v1.4 起类别未登记一律拒绝出距离（见 height_for）
            pitch_deg=float(getattr(params, 'pitch_deg', 0.0)),
            camera_height=float(getattr(params, 'camera_height', 0.0)),
            foot_offset_m=float(getattr(params, 'foot_offset_m', 0.0)),
            height_tolerance=float(getattr(params, 'height_tolerance', 0.35)),
            min_pixel_height=int(getattr(params, 'min_pixel_height', 8)),
            person_width_m=float(getattr(params, 'person_width_m', 0.46)),
            min_pixel_width=int(getattr(params, 'min_pixel_width', 40)),
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

        cal = CameraCalibrator(pattern_size=(9, 6), square_size=0.0171)
        for frame in captures:
            ok = cal.add_frame(frame)      # 自动检测角点，返回是否成功
        intr = cal.calibrate()             # 求解内参
        cal.save('calib.json')

    其中 ``square_size`` 单位是**米**，必须与实物一致 —— 它决定了后续
    测距的尺度。填错的话，距离会等比例错。
    """

    def __init__(self, pattern_size: Tuple[int, int] = (9, 6),
                 square_size: float = 0.0171):  # 17.1mm：本机打印机 100% 打印后的实测方格
                                                 # （配套棋盘图按 18mm 设计，打印会被缩放 → 以校验尺实量为准）
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
# 安装参数自标定（外参：相机安装高度 + 俯仰角）
# ---------------------------------------------------------------------------
#
# 为什么需要它
# ------------
# 接触点法 ``Z = H_相机 / tan(俯仰角 + atan((v_底 - cy)/fy))`` 里有两个**必须
# 事先知道**的量：相机装多高、相机朝下多少度。上一版要求用卷尺 + 量角器手工量，
# 于是出现两个问题：
#
#   1. 卷尺量高度麻烦，量角器量俯仰角更麻烦，而且俯仰角**精度极敏感** ——
#      10 m 处每 1° 的俯仰角偏差约带来 ``0.0175 × Z / H`` 的距离误差
#      （H=0.7 m 时就是 25%/1°）。
#   2. 手工量的角度不可复核，装完不知道对不对。
#
# 反过来想：把目标摆到**卷尺已知的距离 Z** 上、读出它的**框底边像素 v**，
# 这两个量就把 (H, 俯仰角) 约束住了 —— 因为底边贴地时有
#
#     v = cy + fy · tan(atan(H/Z) − 俯仰角)
#
# 一个已知距离给一个方程、两个未知数，所以**两个已知距离就能同时解出 H 与
# 俯仰角**，三个以上做最小二乘。整个过程不需要量角器，也不需要把相机装到
# 某个特定高度 —— 装多高都能解出来。这正好消掉上面两个问题。

MOUNT_MIN_POINTS = 2          # 两个未知数 -> 至少两个已知距离
MOUNT_MIN_DIST_SPAN = 1.5     # 最远/最近已知距离的比值下限：低于此值解算病态
# ⚠️ 这条门槛在「窄量程」场景里达不到：量程上限 5 m 且画面下沿只能看到
# 3.43 m 以外的地面时，两个采样点最多只能拉开 5/3.43 = 1.46 倍。
# 这类场景由调用方用 ``min_dist_span=`` 放宽（实测 1.25 倍跨度下，1 px
# 噪声导致的测距误差 95% 分位 2.3%，对 3.5~5 m 量程够用），代价是
# **不能外推到采样区间之外**。
MOUNT_RESIDUAL_MAX_PX = 5.0   # 拟合残差上限：超过说明采样点本身不自洽
MOUNT_PITCH_RANGE_DEG = (-40.0, 75.0)   # 俯仰角搜索范围（向下为正）
# 相机安装高度的物理合理范围（车/机器人/桌面支架）。它不是「精度余量」，
# 而是**排除多解**用的：两点标定时方程组是二次的，存在**两个数学上同样成立**
# 的解 —— 实测真值 (0.70 m, 2°) 会同时解出 (28.6 m, 68.7°)，两组都能让两个
# 采样点严格吻合。超出此上限的解按「不可信」剔除，两点才可能唯一。
MOUNT_HEIGHT_RANGE_M = (0.05, 5.0)
# 次优解与最优解的残差之差小于此值 -> 认为两个解同样吻合 -> 拒答（歧义）
MOUNT_AMBIGUITY_PX = 0.5
# 「已知相机高度」模式下，各采样点独立反解出的俯仰角的散布上限（度）。
# 超过 => 「框底边 = 脚」这个前提不成立（或某个已知距离填错），必须拒答 ——
# 否则就是在用一组互相矛盾的观测给一个看起来很自信的答案。
MOUNT_FIXED_PITCH_SPREAD_DEG = 1.5
# ---------------------------------------------------------------------------
# 框底边抬升量（foot_offset_m）──「框底边 == 脚」这个前提的修正项
# ---------------------------------------------------------------------------
# 接触点法唯一的假设是「框底边中点落在地面上」。2026-10-01 用
# ``recordings/session-20261001-101102``（0→4 m 站定→4.5 m 站定→回 0）
# 实测：**这条假设在本项目的检测器上不成立**。
#
# 硬证据（不依赖内参与俯仰角）：4 m 与 4.5 m 两处框底边只差 16.0 px；
# 若相机高度真是卷尺量到的 0.98 m，俯仰角从 −5° 扫到 +5°，这个差值应当在
# 20.4~22.3 px。反解出的**等效**相机高度恒为 0.731~0.743 m —— 与 cy、pitch
# 都无关。抽出视频帧放大脚部：绿框底边停在脚上方约小腿中部。
#
# 于是相机高度没错、俯仰角没错，错的是「把小腿当成脚」。正确几何是
# ``Z = (H_相机 − h_off) / tan(俯角)``，即**把有效相机高度降低 h_off**。
# 这正是旧标定 (0.74/−0.9°) 能复现 4 m/4.5 m 的原因：它碰巧用等效高度把
# 这 0.24 m 补偿掉了 —— 补偿正确，但「相机高度 0.74」这个数是假的。
#
# 允许范围的下限不为 0 是为了防止退化：u → 0 时 α → 0，接触点法发散。
FOOT_OFFSET_MIN_M = 0.0
FOOT_OFFSET_MAX_M = 1.2           # 超过 1.2 m 说明解歪了（人腿没这么长）
# 解「俯仰角 + 抬升量」时两个已知距离的最小间隔（米）。比 MOUNT_MIN_DIST_SPAN
# 温和得多：那里要撑开 (H, θ) 的强耦合，这里高度已知、耦合弱（实测 4.0/4.5 m
# 跨度仅 1.125 就能把等效高度定到 0.2 mm）。这条只挡「同一点采了两次」。
MOUNT_OFFSET_MIN_DIST_GAP_M = 0.3

# ---- 「不拿尺子」标定所需的人体尺寸先验 --------------------------------
# 相机只能读到**角度**，读不到米：同一个画面既可以是「近处的小目标」，
# 也可以是「远处的大目标」（尺度歧义）。要把角度换算成米，必须有且只有一个
# 绝对尺度来源 —— 要么用户拿尺子量一个距离，要么靠「人大概有多高」这个先验。
#
# 下面这个数是「检测框覆盖的真实垂直长度」的先验（米）。注意它**不是人的身高**：
# 实测本项目检测器只框住身体 1.41 m（底边在小腿、顶边在额头），不是 1.79 m。
BODY_SPAN_PRIOR_M = 1.41
# 这个先验的个体差异（1σ，相对值）。成人身高/肩宽的散布在 ±10% 量级，
# 检测器框住哪一段也随人和姿态变 —— 保守取 10%。
#
# ⚠️ 它造成的误差是**整体缩放**：解出的等效高度按同一比例偏大/偏小，
# 全量程误差是同一个百分比（2026-10-01 Monte Carlo 实测：各距离 ±10.0%，
# 95% 分位 19.9%）。所以只要**量一个真值距离**就能把它整个消掉 —— 这就是
# 「只量一个距离」模式能做到 ±1% 的原因（第二个点的距离用框高比推，与先验无关）。
BODY_SPAN_PRIOR_REL_SIGMA = 0.10


@dataclass
class MountSolution:
    """安装参数自标定的结果 —— 含「凭什么信这个数」。"""

    ok: bool = False
    camera_height: float = 0.0     # 米
    pitch_deg: float = 0.0         # 度，向下为正（与设置页同向）
    foot_offset_m: float = 0.0     # 框底边抬升量（米），见 FOOT_OFFSET_MAX_M 注释
    residual_px: float = 0.0       # 各采样点「预测底边像素 - 实测底边像素」的均方根
    n_points: int = 0
    dist_span: float = 0.0         # 最远/最近已知距离之比，越大越可信
    sigma_height: float = 0.0      # 相机高度的标准差（米），由假设的像素噪声传播
    sigma_pitch: float = 0.0       # 俯仰角的标准差（度）
    sigma_foot_offset: float = 0.0  # 抬升量的标准差（米）
    reason: str = ''               # ok=False 时：为什么不能用
    detail: str = ''               # ok=True 时：给用户看的结论


def solve_pitch_and_foot_offset(marks, intrinsics, fixed_height_m: float,
                                sigma_px: float = 1.0) -> MountSolution:
    """固定相机高度，由「已知距离 + 框底边像素」**同时**解 (俯仰角, 框底边抬升量)。

    ⚠️ **UI 已于 2026-10-01 下线**：标定页现在只做自标定（解「垂直落差 +
    俯仰角」），不再让用户填相机高度。本函数保留给**离线分析与回归测试**
    （比如回答"检测器到底把框底边放在人身哪个高度"），不要在 UI 里恢复。
    下线原因：填相机高度不提升测距精度，却把人带进「公式里的高度 = 卷尺
    量到的安装高度」这个错误概念 —— 实测 4 m 单点标定 → 5 m 读 4.72。

    为什么必须同时解这两个，而不是「只解俯仰角」
    ------------------------------------------------
    ``solve_mount_params(fixed_height_m=...)`` 只解俯仰角，前提是
    「框底边 == 地面接触点」。2026-10-01 实测这个前提不成立（底边落在离地
    0.249 m 的小腿中部），于是那 0.249 m 被**整个吸收进俯仰角**：解出的
    +1.9° 不是真实俯仰角，而是一个只在标定点成立的补偿值 —— 4 m +4.7%、
    4.5 m +2.1%、5 m 0%，误差单调收敛到标定点，正是这个机制的指纹。

    这里的正确做法是把缺失的物理量补回来，而不是让俯仰角背锅：
    ``Z = (H − h_off) / tan(θ + β)``，未知数变成 (θ, h_off) 两个，
    由**两个**已知距离解出。解出后相机高度仍保持卷尺量到的真实值。

    数学结构（与两未知数模式同构，只是把 H 换成有效高度 u = H − h_off）
    ------------------------------------------------------------------
    每个采样点给一条方程 ``u = Z_i · tan(θ + β_i)``，残差取**像素域**
    ``cy + fy·tan(atan2(u, Z_i) − θ) − v_i``。两点即可解，且不再存在
    「高度与角度互相补偿」的假解 —— 因为高度已经由卷尺钉死。

    ⚠️ 为什么**不做** ``MOUNT_MIN_DIST_SPAN`` 那样的跨度门槛：那条门槛是
    为 (H, θ) 的强耦合设的；这里高度已知，两个未知数的耦合弱得多
    （实测 4.0 / 4.5 m 两个点、跨度仅 1.125 就能把等效高度定到 0.2 mm）。
    改用「解出的 σ 是否过大」来判定病态，比拍一个跨度下限更本质。

    返回 ``MountSolution``；``ok=False`` 时 ``reason`` 说明为什么不能给答案。
    """
    if intrinsics is None or not intrinsics.is_valid():
        return MountSolution(ok=False, reason='相机未标定，无法解算安装参数')
    cy = float(intrinsics.cy)
    fy = float(intrinsics.fy)
    if fy <= 0:
        return MountSolution(ok=False, reason='内参 fy 非法')

    pts = []
    for m in marks or []:
        try:
            z, v = float(m[0]), float(m[1])
        except (TypeError, IndexError, ValueError):
            continue
        if z > 0 and np.isfinite(v):
            pts.append((z, v))
    zs = np.array([p[0] for p in pts], dtype=float) if pts else np.array([])
    vs = np.array([p[1] for p in pts], dtype=float) if pts else np.array([])
    span = float(zs.max() / zs.min()) if len(pts) >= 2 else 0.0

    H = float(fixed_height_m) if fixed_height_m is not None else 0.0
    if not np.isfinite(H) or H <= 0:
        return MountSolution(ok=False, n_points=len(pts), dist_span=span,
                             reason=f'已知相机高度 {fixed_height_m!r} 不合法')
    if len(pts) < 2:
        return MountSolution(
            ok=False, n_points=len(pts), dist_span=span,
            reason='解「俯仰角 + 框底边抬升量」需要 2 个已知距离（两个未知数），'
                   f'当前只有 {len(pts)} 个。请换一个距离再采一次'
                   '（例如 4 m 与 5 m）')
    if float(zs.max() - zs.min()) < MOUNT_OFFSET_MIN_DIST_GAP_M:
        return MountSolution(
            ok=False, n_points=len(pts), dist_span=span,
            reason=f'两个已知距离太接近（相差 {float(zs.max()-zs.min()):.2f} m，'
                   f'需要 ≥ {MOUNT_OFFSET_MIN_DIST_GAP_M:.1f} m）：'
                   '这样解不出唯一的俯仰角与抬升量')

    # 有效高度 u = H − h_off 的允许区间：抬升量必须非负、且不超过人腿长度
    u_lo = max(0.05, H - FOOT_OFFSET_MAX_M)
    u_hi = H
    if u_lo >= u_hi:
        return MountSolution(
            ok=False, n_points=len(pts), dist_span=span,
            reason=f'相机高度 {H:.2f} m 太低：抬升量的可解区间为空')

    betas = np.arctan2(vs - cy, fy)
    min_alpha = np.deg2rad(MIN_CONTACT_ANGLE_DEG)
    max_alpha = np.deg2rad(89.0)

    def predict(u, theta_rad):
        """给定 (有效高度, 俯仰角)，预测各采样点的底边像素。"""
        return cy + fy * np.tan(np.arctan2(u, zs) - theta_rad)

    def residual(u, theta_rad):
        return predict(u, theta_rad) - vs

    # ---- 1. 粗搜：俯仰角网格，每个角度取「使残差最小」的有效高度作种子 ----
    lo_d, hi_d = MOUNT_PITCH_RANGE_DEG
    ths = np.arange(lo_d, hi_d + 1e-9, 0.25)
    u0s = np.full(ths.shape, np.nan)
    costs = np.full(ths.shape, np.inf)
    for i, th_deg in enumerate(ths):
        th = np.deg2rad(th_deg)
        alpha = th + betas                      # 各点的视线俯角
        if np.any(alpha <= min_alpha) or np.any(alpha >= max_alpha):
            continue
        u0 = float(np.mean(zs * np.tan(alpha)))
        if not (1e-3 < u0 < 1e4):
            continue
        u0s[i] = u0
        costs[i] = float(np.sum(residual(u0, th) ** 2))

    seeds = [i for i in range(1, len(ths) - 1)
             if np.isfinite(costs[i]) and np.isfinite(costs[i - 1])
             and np.isfinite(costs[i + 1])
             and costs[i] <= costs[i - 1] and costs[i] <= costs[i + 1]]
    if np.any(np.isfinite(costs)):
        seeds.append(int(np.argmin(costs)))
    seeds = sorted(set(seeds))

    # ---- 2. 精修：Gauss-Newton（数值 Jacobian，2 个未知数） ----
    def refine(u0, th0):
        u, th = float(u0), float(th0)
        for _ in range(80):
            r = residual(u, th)
            eps_u, eps_t = max(u * 1e-6, 1e-9), 1e-7
            j_u = (residual(u + eps_u, th) - r) / eps_u
            j_t = (residual(u, th + eps_t) - r) / eps_t
            J = np.column_stack([j_u, j_t])
            try:
                delta, *_ = np.linalg.lstsq(J, -r, rcond=None)
            except np.linalg.LinAlgError:
                break
            step_u, step_t = float(delta[0]), float(delta[1])
            if abs(step_u) > 0.5:
                step_u = math.copysign(0.5, step_u)
            if abs(step_t) > 0.1:
                step_t = math.copysign(0.1, step_t)
            u += step_u
            th += step_t
            if not (1e-3 < u < 1e4):
                u = min(max(u, 1e-3), 1e4)
            if abs(step_u) < 1e-10 and abs(step_t) < 1e-13:
                break
        return u, th

    found = []
    for i in seeds:
        if not np.isfinite(u0s[i]):
            continue
        u, th = refine(u0s[i], np.deg2rad(float(ths[i])))
        th_deg = float(np.rad2deg(th))
        if not (u_lo <= u <= u_hi) or not (lo_d <= th_deg <= hi_d):
            continue
        alpha = th + betas
        if np.any(alpha <= min_alpha) or np.any(alpha >= max_alpha):
            continue
        r = residual(u, th)
        found.append((float(np.sqrt(np.mean(r ** 2))), u, th, th_deg))

    uniq = []
    for cand in sorted(found, key=lambda s: s[0]):
        if all(abs(cand[1] - x[1]) > 0.01 or abs(cand[3] - x[3]) > 0.1
               for x in uniq):
            uniq.append(cand)

    if not uniq:
        return MountSolution(
            ok=False, n_points=len(pts), dist_span=span,
            reason=f'解不出物理合理的俯仰角与抬升量（抬升量需在 0~'
                   f'{FOOT_OFFSET_MAX_M:.1f} m、俯仰角需在 '
                   f'{lo_d:.0f}~{hi_d:.0f}°）：请检查「已知距离」是否填对、'
                   f'标记时目标是否真的站在该距离处')

    rms, u, th, th_deg = uniq[0]

    # ---- 3. 歧义裁决：两个解同样吻合时不给结论（宁可拒答） ----
    for rms2, u2, th2, th2_deg in uniq[1:]:
        if rms2 <= rms + MOUNT_AMBIGUITY_PX and rms2 <= 1.0:
            return MountSolution(
                ok=False, camera_height=H, pitch_deg=th_deg,
                foot_offset_m=H - u, residual_px=rms,
                n_points=len(pts), dist_span=span,
                reason=(f'这组已知距离有**两个同样吻合**的解'
                        f'（俯仰角 {th_deg:.1f}° / 抬升 {H - u:.2f} m 与 '
                        f'俯仰角 {th2_deg:.1f}° / 抬升 {H - u2:.2f} m），'
                        f'无法唯一确定。请再补一个已知距离'))

    r = residual(u, th)
    if rms > MOUNT_RESIDUAL_MAX_PX:
        return MountSolution(
            ok=False, camera_height=H, pitch_deg=th_deg,
            foot_offset_m=H - u, residual_px=rms,
            n_points=len(pts), dist_span=span,
            reason=(f'拟合残差 {rms:.1f} px 过大（上限 '
                    f'{MOUNT_RESIDUAL_MAX_PX:.0f} px）：这组采样点自身不自洽 —— '
                    f'常见原因是「已知距离」填错，或两段采样不是同一个姿态'))

    # ---- 4. 不确定度：由 Jacobian 把像素噪声传到 (u, 俯仰角) ----
    eps_u, eps_t = max(u * 1e-6, 1e-9), 1e-7
    j_u = (residual(u + eps_u, th) - r) / eps_u
    j_t = (residual(u, th + eps_t) - r) / eps_t
    J = np.column_stack([j_u, j_t])
    dof = max(len(pts) - 2, 1)
    sigma2 = max(float(np.sum(r ** 2)) / dof, float(sigma_px) ** 2)
    try:
        cov = sigma2 * np.linalg.inv(J.T @ J)
        sig_u = float(np.sqrt(max(cov[0, 0], 0.0)))
        sig_t = float(np.rad2deg(np.sqrt(max(cov[1, 1], 0.0))))
    except np.linalg.LinAlgError:
        sig_u, sig_t = float('nan'), float('nan')

    off = float(H - u)
    # 病态判定：σ 比抬升量本身还大 => 这两点撑不住两个未知数
    if np.isfinite(sig_u) and sig_u > max(0.15, abs(off)):
        return MountSolution(
            ok=False, camera_height=H, pitch_deg=th_deg, foot_offset_m=off,
            residual_px=rms, n_points=len(pts), dist_span=span,
            sigma_pitch=sig_t, sigma_foot_offset=sig_u,
            reason=(f'解出的抬升量不确定度过大（±{sig_u:.2f} m，'
                    f'而解出值本身 {off:.2f} m）：两个已知距离撑不住两个未知数，'
                    f'请拉开距离（推荐 3 m 与 5 m）再采'))

    detail = (f'已按「已知相机高度 {H:.2f} m」同时解出：俯仰角 {th_deg:.2f}°、'
              f'框底边抬升 {off:.3f} m（有效相机高度 {u:.3f} m，'
              f'残差 {rms:.2f} px，{len(pts)} 个采样点）。\n'
              f'相机高度保持卷尺量到的真实值，不再靠俯仰角补偿底边偏移 —— '
              f'所以离开标定点也不会发散。')
    return MountSolution(ok=True, camera_height=H, pitch_deg=th_deg,
                         foot_offset_m=off, residual_px=rms, n_points=len(pts),
                         dist_span=span, sigma_height=0.0, sigma_pitch=sig_t,
                         sigma_foot_offset=sig_u, detail=detail)


def distances_from_box_height(marks, intrinsics,
                              span_prior_m: float | None = None,
                              anchor: dict | None = None,
                              ) -> tuple[list, float]:
    """由「框高像素」反推各采样点的距离 —— **不拿尺子**标定的关键一步。**纯函数**。

    为什么能用框高代替尺子
    ----------------------
    同一目标站得越远，框越矮，且 ``Z × 框高px ≈ fy × 框覆盖的真实长度``
    （严格说是 ``Z = fy × span / 框高px``）。于是有两种用法：

    - **给了 ``anchor``**（某个已知距离的采样点）：其余点按**框高比**推
      ``Z_i = Z_anchor × 框高_anchor / 框高_i``。比值里人体尺寸先验**完全抵消**，
      所以精度只受像素噪声 —— 实测由 4 m 推 5 m 偏差 **0.004%**。
      👉 这就是「只量一个距离」模式：精度与「每个距离都量」几乎相同
      （Monte Carlo：95% 分位 2.4% vs 2.3%）。
    - **不给 ``anchor``**（全自动）：``Z_i = fy × span_prior / 框高_i``，
      尺度完全来自人体尺寸先验，误差 = 先验误差（约 ±10%），且是**整体缩放**。

    ``marks``：``_mount_marks`` 里的字典（需含 ``box_h`` 与 ``v``）。
    返回 ``([(距离_m, 框底边_v), ...], 距离的相对标准差)``；
    相对标准差 0 表示尺度由已知距离钉死，非 0 表示尺度来自先验。
    """
    if intrinsics is None or not intrinsics.is_valid():
        return [], 0.0
    fy = float(intrinsics.fy)
    if fy <= 0:
        return [], 0.0

    span = float(span_prior_m or BODY_SPAN_PRIOR_M)
    if not np.isfinite(span) or span <= 0:
        span = BODY_SPAN_PRIOR_M

    az = ah = 0.0
    if anchor is not None:
        try:
            az = float(anchor.get('dist', 0.0))
            ah = float(anchor.get('box_h', 0.0))
        except (TypeError, ValueError):
            az = ah = 0.0
        if not (np.isfinite(az) and az > 0 and np.isfinite(ah) and ah > 0):
            return [], 0.0

    out = []
    for m in marks or []:
        if not isinstance(m, dict):
            continue
        try:
            h = float(m.get('box_h'))
            v = float(m.get('v'))
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(h) and h > 0 and np.isfinite(v)):
            continue
        z = (az * ah / h) if anchor is not None else (fy * span / h)
        if np.isfinite(z) and 0 < z < 1e4:
            out.append((z, v))
    return out, (0.0 if anchor is not None else BODY_SPAN_PRIOR_REL_SIGMA)


def solve_mount_params(marks, intrinsics,
                       sigma_px: float = 1.0,
                       fixed_height_m: float | None = None,
                       solve_foot_offset: bool = False,
                       min_dist_span: float | None = None) -> MountSolution:
    """由「已知距离 + 框底边像素」反解安装参数。**纯函数**。

    ``marks``：``[(已知距离_m, 框底边像素_v), ...]``，至少 2 组，**推荐 3 组**。

    ``fixed_height_m`` / ``solve_foot_offset``：⚠️ **UI 已于 2026-10-01 下线**
    （标定页只剩自标定），这两个参数**保留给离线分析与回归测试**，不要在
    UI 里恢复它们 —— 理由见 ``solve_pitch_and_foot_offset`` 的 docstring。
    语义仍照旧：给了 ``fixed_height_m`` 就固定相机高度、只解俯仰角；再给
    ``solve_foot_offset=True`` 则改为同时解 (俯仰角, 框底边抬升量)。

    ⚠️ **两未知数模式在「采样跨度小」时会退化（2026-09-30 实测）**：真值
    ``(0.98 m, ~2°)`` 与 ``(0.74 m, -0.9°)`` 在 4.0/4.5/5.0 m 三个采样点上
    **都吻合**（残差 3.4 px，低于 ``MOUNT_RESIDUAL_MAX_PX``），但外推到 10 m
    差 57%。也就是说：**残差小只说明采样区间内自洽，不能说明外推可信**。
    别指望"同时用框顶 + 框底"能救 —— 判别式 ``atan(H/Z) − atan((H−h)/Z)``
    在 ``H = 身高/2`` 处取极大，相机装在人身高一半时 1 px 噪声就能让解崩掉。

    做法（先粗搜枚举全部候选解、再逐个 Gauss-Newton 精修，全程只依赖 numpy、
    无随机性）：

    1. 粗搜俯仰角网格，对每个角度取「使预测像素残差最小」的高度作种子；
    2. 保留**所有候选**（不只最优）—— 两点标定时方程组是二次的，数学上存在
       两个解。实测真值 (0.70 m, 2°) 会同时解出 (28.6 m, 68.7°)，两组都让
       两个采样点严格吻合。只留最优解会在像素噪声下随机跳到错误那一支
       （实测真值 1.2 m/20° 时会解成 8.7 m ± 7.7 m）；
    3. 按物理合理范围 ``MOUNT_HEIGHT_RANGE_M`` 剔除不可信解，再对剩下的解做
       **歧义裁决**：若两个解同样吻合，拒答并要求补点；
    4. 误差函数取**像素域**残差 ``Σ(v_pred − v_实测)²``，因为 v 才是被测量的量；
    5. 由最终 Jacobian 传播像素噪声，给出 (H, 俯仰角) 的标准差 —— 这样
       UI 能直接告诉用户「用这两个距离解，精度大致是多少」。

    拒绝给出结果的情形（``ok=False``）：内参无效、采样点少于 2 组、
    两组距离太接近（解算病态）、存在两个同样吻合的解（歧义）、
    拟合残差过大（采样点本身不自洽，例如标记时框底边并不在地面上）。

    ⚠️ **一致性检查需要 3 个点**：2 个点永远能严格拟合（方程数 = 未知数），
    所以「残差」在两点时恒为 0，暴露不了「把膝盖当脚标了」这类错误。
    这是数学上的限制，不是实现取舍 —— 所以操作上推荐 2 m / 5 m / 10 m 三点。

    实测（``E:\\WorkBuddy-Work\\scripts\\verify_mount_selfcal.py``）：
    由真值正算采样点再反解，多点组合均精确复原（残差 ~1e-14 px）；
    1 px 像素噪声下 200 次 Monte Carlo 无偏、散布与自报 σ 同量级。
    """
    if intrinsics is None or not intrinsics.is_valid():
        return MountSolution(ok=False, reason='相机未标定，无法自标定安装参数')
    cy = float(intrinsics.cy)
    fy = float(intrinsics.fy)
    if fy <= 0:
        return MountSolution(ok=False, reason='内参 fy 非法')

    pts = []
    for m in marks or []:
        try:
            z, v = float(m[0]), float(m[1])
        except (TypeError, IndexError, ValueError):
            continue
        if z > 0 and np.isfinite(v):
            pts.append((z, v))
    zs = np.array([p[0] for p in pts], dtype=float) if pts else np.array([])
    vs = np.array([p[1] for p in pts], dtype=float) if pts else np.array([])
    span = float(zs.max() / zs.min()) if len(pts) >= 2 else 0.0

    # ---- 0. 已知相机高度 -> 只解俯仰角（1 个未知数）------------------------
    # 这条分支是**退化问题的唯一可靠解法**（2026-09-30 实测）：
    # 两个未知数 (H, pitch) 只靠「框底边像素」约束时，H 与 pitch 强耦合 ——
    # 实测真值 (0.98 m, ~2°) 会解出同样吻合的 (0.74 m, -0.9°)，残差仅 3.4 px
    # （< MOUNT_RESIDUAL_MAX_PX），但外推到 10 m 会读成 15.7 m（+57%）。
    # 相机高度是**唯一能用卷尺直接量到**的外参（俯仰角量不了），所以把它
    # 作为已知量固定下来，就只剩 1 个未知数：一个采样点即可解、且解唯一。
    if fixed_height_m is not None:
        # 同时解「抬升量」：底边不在脚上时，只解俯仰角会让偏移被吸进角度里
        if solve_foot_offset:
            return solve_pitch_and_foot_offset(pts, intrinsics,
                                               fixed_height_m, sigma_px)
        # ⚠️ 只解俯仰角也要 **2 个采样点**（2026-10-01 用户实测踩坑后加的硬门槛）。
        # 1 个点数学上够解（1 个未知数），但**无法自查「框底边 = 脚」这个前提**：
        # 前提不成立时，那段偏移会被整个吸进俯仰角，得到一个只在标定点成立、
        # 离开就单调发散的补偿值 —— 实测 4 m 单点标定解出 pitch=2.5°（真值
        # -0.915°），4 m 读 4.000 但 5 m 读 4.721（-5.6%）。
        if len(pts) < 2:
            return MountSolution(
                ok=False, n_points=len(pts), dist_span=span,
                reason=('「已知高度 + 只解俯仰角」需要**至少 2 个采样点**。\n'
                        '1 个点虽然能解出角度，但无法自查「框底边是否真是脚」——'
                        '若底边其实不在脚上，偏移会被整个吸进角度，得到一个只在'
                        '标定点成立、离开就发散的值（实测：4 m 标定后 5 m 偏 -5.6%）。\n'
                        '请再采一个不同的距离，或勾上「框底边不在脚上（同时解抬升量）」。'))
        H = float(fixed_height_m)
        if not np.isfinite(H) or H <= 0:
            return MountSolution(ok=False, n_points=len(pts), dist_span=span,
                                 reason=f'已知相机高度 {fixed_height_m!r} 不合法')
        betas = np.arctan2(vs - cy, fy)
        # α_i = atan(H/Z_i) 是视线俯角，β_i 是「底边相对光轴」的偏角，
        # 两者之差就是俯仰角 —— 每个采样点各给一个独立估计。
        th_each = np.rad2deg(np.arctan2(H, zs) - betas)
        if np.any(th_each <= MOUNT_PITCH_RANGE_DEG[0]) \
                or np.any(th_each >= MOUNT_PITCH_RANGE_DEG[1]):
            return MountSolution(
                ok=False, n_points=len(pts), dist_span=span,
                reason=(f'按相机高度 {H:.2f} m 反解出的俯仰角超出合理范围'
                        f'（{float(np.min(th_each)):.1f}~{float(np.max(th_each)):.1f}°）：'
                        f'请核对「已知距离」与相机高度是否填对'))
        th_deg = float(np.mean(th_each))
        spread = float(np.std(th_each)) if len(th_each) > 1 else 0.0
        pred = cy + fy * np.tan(np.arctan2(H, zs) - np.deg2rad(th_deg))
        rms = float(np.sqrt(np.mean((pred - vs) ** 2)))

        # 一致性检查：各点独立解出的俯仰角**必须一致**。不一致说明观测不成立
        # （框底边其实不是脚 / 已知距离填错），这时候给答案就是给错的自信。
        if len(th_each) > 1 and spread > MOUNT_FIXED_PITCH_SPREAD_DEG:
            return MountSolution(
                ok=False, camera_height=H, pitch_deg=th_deg, residual_px=rms,
                n_points=len(pts), dist_span=span,
                reason=(f'各采样点反解出的俯仰角不一致（散布 {spread:.2f}° > '
                        f'{MOUNT_FIXED_PITCH_SPREAD_DEG:.1f}°，逐点值：'
                        + '、'.join(f'{t:.2f}°' for t in th_each)
                        + f'）。这说明「框底边 = 脚/地面接触点」这个前提不成立，'
                          f'或某个「已知距离」填错了。\n'
                          f'若确认距离没填错，请勾上「框底边不在脚上（同时解抬升量）」'
                          f'再求解 —— 那样相机高度保持卷尺量到的真实值，'
                          f'由抬升量吸收这段偏移，离开标定点也不会发散。'))
        if rms > MOUNT_RESIDUAL_MAX_PX:
            return MountSolution(
                ok=False, camera_height=H, pitch_deg=th_deg, residual_px=rms,
                n_points=len(pts), dist_span=span,
                reason=(f'按相机高度 {H:.2f} m 拟合的残差 {rms:.2f} px 过大'
                        f'（> {MOUNT_RESIDUAL_MAX_PX:.0f} px）：采样点之间不自洽'))
        # 不确定度：1 px 底边误差 -> 俯仰角误差（各点独立估计的标准误）
        if len(th_each) > 1:
            sig_t = float(np.std(th_each, ddof=1) / math.sqrt(len(th_each)))
        else:
            d_alpha = fy / (fy ** 2 + (vs[0] - cy) ** 2)      # dv=1px 的 dβ
            sig_t = float(np.rad2deg(d_alpha)) * float(sigma_px)
        detail = (f'已按「已知相机高度 {H:.2f} m」只解俯仰角：{th_deg:.2f}°'
                  f'（残差 {rms:.2f} px，{len(pts)} 个采样点'
                  + (f'，逐点俯仰角散布 {spread:.2f}°' if len(th_each) > 1 else '')
                  + '）。\n只解一个未知数，所以**没有**高度/角度耦合的歧义，'
                    '也不需要多个距离撑开跨度。')
        if len(th_each) == 1:
            detail += ('\n⚠️ 只有一个采样点，无法自查「框底边是否真是脚」——'
                       '建议再采一个距离复核。')
        return MountSolution(ok=True, camera_height=H, pitch_deg=th_deg,
                             residual_px=rms, n_points=len(pts), dist_span=span,
                             sigma_height=0.0, sigma_pitch=sig_t, detail=detail)

    # 两未知数模式：方程数必须 ≥ 未知数
    if len(pts) < MOUNT_MIN_POINTS:
        return MountSolution(ok=False, n_points=len(pts), dist_span=span,
                             reason=f'至少需要 {MOUNT_MIN_POINTS} 个已知距离'
                                    f'（当前 {len(pts)} 个）：要解「垂直落差 + '
                                    f'俯仰角」两个未知数，就得有两个不同距离'
                                    f'的采样点。请换一个距离再采一次')
    # 跨度门槛可按场景放宽 —— 见 MOUNT_MIN_DIST_SPAN 的注释：1.5 这条门槛
    # 在「量程只有 3.5~5 m」这类场景里根本达不到（画面下沿能看到的最近地面
    # 都 3.43 m，两个点最多拉开 1.46 倍）。那种场景由调用方传入更小的值。
    need_span = float(MOUNT_MIN_DIST_SPAN if min_dist_span is None
                      else min_dist_span)
    if span < need_span:
        return MountSolution(ok=False, n_points=len(pts), dist_span=span,
                             reason=(f'已知距离太接近（最远/最近 = {span:.2f}，'
                                     f'需要 ≥ {need_span:.2f}）：'
                                     f'这样解不出唯一的高度与俯仰角。'
                                     f'请让两个采样点拉开更大距离'))
    # 观测角 beta_i = atan((v_i - cy)/fy)，即「该底边相对光轴偏了多少」
    betas = np.arctan2(vs - cy, fy)

    def predict(H, theta_rad):
        """给定 (H, 俯仰角)，预测各采样点的底边像素。"""
        return cy + fy * np.tan(np.arctan2(H, zs) - theta_rad)

    def residual(H, theta_rad):
        return predict(H, theta_rad) - vs

    # ---- 1. 粗搜：俯仰角网格，每个角度取「使预测残差最小」的高度作种子 ----
    # 注意要**保留全部候选**（不只最优那个）：两点标定存在两个数学解，
    # 只取全场最优会在噪声下随机跳到错误的那一支（实测过：真值 1.2 m/20°
    # 时解成 8.7 m ± 7.7 m）。所以先枚举所有局部极小，逐个精修，再按物理
    # 范围筛选、按歧义检查裁决。
    lo_d, hi_d = MOUNT_PITCH_RANGE_DEG
    min_alpha = np.deg2rad(MIN_CONTACT_ANGLE_DEG)
    max_alpha = np.deg2rad(89.0)
    ths = np.arange(lo_d, hi_d + 1e-9, 0.25)
    h0s = np.full(ths.shape, np.nan)
    costs = np.full(ths.shape, np.inf)
    for i, th_deg in enumerate(ths):
        th = np.deg2rad(th_deg)
        alpha = th + betas                  # 各点的视线俯角
        if np.any(alpha <= min_alpha) or np.any(alpha >= max_alpha):
            continue
        h0 = float(np.mean(zs * np.tan(alpha)))   # 由 H = Z·tan(α) 直接给初值
        if not (1e-3 < h0 < 1e4):
            continue
        h0s[i] = h0
        costs[i] = float(np.sum(residual(h0, th) ** 2))

    seeds = [i for i in range(1, len(ths) - 1)
             if np.isfinite(costs[i]) and np.isfinite(costs[i - 1])
             and np.isfinite(costs[i + 1])
             and costs[i] <= costs[i - 1] and costs[i] <= costs[i + 1]]
    if np.any(np.isfinite(costs)):
        seeds.append(int(np.argmin(costs)))
    seeds = sorted(set(seeds))

    # ---- 2. 精修：Gauss-Newton（数值 Jacobian，2 个未知数，收敛极快） ----
    def refine(H0, th0):
        H, th = float(H0), float(th0)
        for _ in range(80):
            r = residual(H, th)
            eps_h, eps_t = max(H * 1e-6, 1e-9), 1e-7
            j_h = (residual(H + eps_h, th) - r) / eps_h
            j_t = (residual(H, th + eps_t) - r) / eps_t
            J = np.column_stack([j_h, j_t])
            try:
                delta, *_ = np.linalg.lstsq(J, -r, rcond=None)
            except np.linalg.LinAlgError:
                break
            step_h, step_t = float(delta[0]), float(delta[1])
            # 限步长，防止从远处一步跨过极值点
            if abs(step_h) > 1.0:
                step_h = math.copysign(1.0, step_h)
            if abs(step_t) > 0.1:
                step_t = math.copysign(0.1, step_t)
            H += step_h
            th += step_t
            if H <= 0:
                H = 1e-3
            if abs(step_h) < 1e-10 and abs(step_t) < 1e-13:
                break
        return H, th

    h_lo, h_hi = MOUNT_HEIGHT_RANGE_M
    found = []           # (rms, H, th, th_deg)
    for i in seeds:
        if not np.isfinite(h0s[i]):
            continue
        H, th = refine(h0s[i], np.deg2rad(float(ths[i])))
        th_deg = float(np.rad2deg(th))
        if not (h_lo <= H <= h_hi) or not (lo_d <= th_deg <= hi_d):
            continue
        alpha = th + betas
        if np.any(alpha <= min_alpha) or np.any(alpha >= max_alpha):
            continue
        r = residual(H, th)
        found.append((float(np.sqrt(np.mean(r ** 2))), H, th, th_deg))

    # 去重（同一个解的多个种子）
    uniq = []
    for cand in sorted(found, key=lambda s: s[0]):
        if all(abs(cand[1] - u[1]) > 0.01 or abs(cand[3] - u[3]) > 0.1
               for u in uniq):
            uniq.append(cand)

    if not uniq:
        return MountSolution(
            ok=False, n_points=len(pts), dist_span=span,
            reason=(f'解不出物理合理的安装参数（相机高度需在 '
                    f'{h_lo:.2f}~{h_hi:.2f} m，俯仰角需在 '
                    f'{lo_d:.0f}~{hi_d:.0f}°）：请检查「已知距离」是否填对、'
                    f'标记时目标是否真的站在该距离处'))

    rms, H, th, th_deg = uniq[0]

    # ---- 3. 歧义裁决：两个解同样吻合时不给结论（宁可拒答） ----
    for rms2, H2, th2, th2_deg in uniq[1:]:
        if rms2 <= rms + MOUNT_AMBIGUITY_PX and rms2 <= 1.0:
            return MountSolution(
                ok=False, camera_height=H, pitch_deg=th_deg, residual_px=rms,
                n_points=len(pts), dist_span=span,
                reason=(f'这组已知距离有**两个同样吻合**的解'
                        f'（{H:.2f} m / {th_deg:.1f}° 与 '
                        f'{H2:.2f} m / {th2_deg:.1f}°），无法唯一确定。'
                        f'请再补一个已知距离 —— 推荐摆 2 m / 5 m / 10 m 三点'))

    r = residual(H, th)

    # ---- 4. 不确定度：由 Jacobian 把像素噪声传到 (H, 俯仰角) ----
    # σ² 取「假设像素噪声」与「实际残差」的较大者：只有 2 个点时残差必然为 0，
    # 那时只能按假设噪声给量级，不能假装精度无穷高。
    eps_h, eps_t = max(H * 1e-6, 1e-9), 1e-7
    j_h = (residual(H + eps_h, th) - r) / eps_h
    j_t = (residual(H, th + eps_t) - r) / eps_t
    J = np.column_stack([j_h, j_t])
    dof = max(len(pts) - 2, 1)
    sigma2 = max(float(np.sum(r ** 2)) / dof, float(sigma_px) ** 2)
    try:
        cov = sigma2 * np.linalg.inv(J.T @ J)
        sig_h = float(np.sqrt(max(cov[0, 0], 0.0)))
        sig_t = float(np.rad2deg(np.sqrt(max(cov[1, 1], 0.0))))
    except np.linalg.LinAlgError:
        sig_h, sig_t = float('nan'), float('nan')

    if rms > MOUNT_RESIDUAL_MAX_PX:
        return MountSolution(
            ok=False, camera_height=H, pitch_deg=th_deg, residual_px=rms,
            n_points=len(pts), dist_span=span, sigma_height=sig_h,
            sigma_pitch=sig_t,
            reason=(f'拟合残差 {rms:.1f} px 过大（上限 '
                    f'{MOUNT_RESIDUAL_MAX_PX:.0f} px）：这组采样点自身不自洽 —— '
                    f'常见原因是标记时框底边并不在地面上（目标被遮挡、'
                    f'只露出上半身），或「已知距离」填错。请重新采样'))

    detail = (f'已解出：相机安装高度 {H:.3f} m、俯仰角 {th_deg:.2f}°，'
              f'残差 {rms:.2f} px（{len(pts)} 个采样点，'
              f'最远/最近 = {span:.2f}）')
    if len(pts) == MOUNT_MIN_POINTS:
        detail += '。两点只能保证与这两个距离吻合，建议再补一个已知距离复核'
    return MountSolution(ok=True, camera_height=H, pitch_deg=th_deg,
                         residual_px=rms, n_points=len(pts), dist_span=span,
                         sigma_height=sig_h, sigma_pitch=sig_t, detail=detail)


# ---------------------------------------------------------------------------
# 安装参数持久化（外参：相机安装高度 + 俯仰角）
# ---------------------------------------------------------------------------
#
# 为什么必须落盘
# ------------
# 内参有 ``models/calib.json`` 持久化，安装参数却只活在内存里（``GlobalParams``），
# 于是**每次启动程序都要重新解一遍或重新填一遍** —— 这正是「棋盘标完之后
# 还要再搞一次」的繁琐来源。两者同属「装一次、长期用」的量，必须一起落盘。
#
# 为什么与内参分开存
# --------------
# 两者的**生命周期不同**：内参跟**相机本体**走（换相机才重标），安装参数跟
# **机位**走（挪相机才重做）。合成一个文件会让「重标内参」把安装参数一并冲掉，
# 反过来也是 —— 而这两件事恰好是部署时最常各自发生一次的动作。
#
# 为什么只存两个数字却要单独一个文件
# -----------------------------
# 「解出来的安装参数」是**证据链的一部分**：它必须能回答「这组 H/θ 是怎么来的、
# 什么时候定的」。所以除了两个数值，还记来源（自标定 / 手工填写）与时间戳 ——
# 排查「距离集体偏大」时，第一个要问的就是「H/θ 是什么时候、怎么来的」。

MOUNT_PARAMS_VERSION = 1


def save_mount_params(path: str, camera_height: float, pitch_deg: float,
                      source: str = '', note: str = '',
                      foot_offset_m: float = 0.0) -> None:
    """把安装参数写入 JSON。**任何一次求解成功或手工修改后都应调用**。

    只做落盘，不做校验 —— 校验在 ``solve_mount_params`` 里已经做过，
    这里再拦一次会让「手工填一个中间值先看看效果」这种正常操作变得不可能。
    """
    payload = {
        'version': MOUNT_PARAMS_VERSION,
        'camera_height': round(float(camera_height), 4),
        'pitch_deg': round(float(pitch_deg), 4),
        # 框底边抬升量（2026-10-01）：底边不在脚上时，接触点法按
        # Z = (H − h_off)/tan(α) 修正。默认 0.0 —— 旧文件读回来行为不变。
        'foot_offset_m': round(float(foot_offset_m or 0.0), 4),
        'source': source,
        'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'note': note,
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_mount_params(path: str) -> Optional[dict]:
    """读取安装参数。文件不存在或损坏都返回 ``None``（视为「还没定过」）。

    与内参加载一样：**读不到不是错误**，只是「安装参数未知」，此时接触点法
    明确不可用，而不是拿一个默认值硬算。所以这里吞掉解析异常，交由调用方
    按「无参数」处理。
    """
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    out = {}
    for k in ('camera_height', 'pitch_deg'):
        try:
            out[k] = float(data.get(k, 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
    # 抬升量是**可选字段**（旧版本的文件里没有）：读不到按 0 处理，
    # 即「框底边 == 脚」的旧行为 —— 升级不能让已标定的机位悄悄变掉。
    try:
        out['foot_offset_m'] = float(data.get('foot_offset_m', 0.0) or 0.0)
    except (TypeError, ValueError):
        out['foot_offset_m'] = 0.0
    if not math.isfinite(out['foot_offset_m']) or out['foot_offset_m'] < 0:
        out['foot_offset_m'] = 0.0
    if out['camera_height'] < 0 or not math.isfinite(out['camera_height']):
        return None
    if not math.isfinite(out['pitch_deg']):
        return None
    out['source'] = str(data.get('source', '') or '')
    out['saved_at'] = str(data.get('saved_at', '') or '')
    out['note'] = str(data.get('note', '') or '')
    return out


# ---------------------------------------------------------------------------
# 可见性体检 —— 出数字之前的检查（不检查就出数 = 在零证据下自信地给错值）
# ---------------------------------------------------------------------------

EDGE_TOL_PX = 2.0             # 框边距画面边界多少像素内算「贴边」
# ⚠️ 底边单独用更大的容差（2026-09-25 19:45 录制实证）：
# 「被画面裁掉的目标，其框边必然贴在画面边界上」这个假设**对底边不成立**——
# YOLO 在画面底缘有系统性欠检。用真实走近录像（session-20260925-194532，
# 人从 2 m 走到贴脸）逐帧核对：脚早已出画的帧，检测框底边实测落在
# 464~475 px（画面高 480），欠检幅度 5~16 px，**永远够不到 2 px 容差线**。
# 后果是接触点法把这些「假底边」当真脚读，任何 <1.9 m 的距离都被算成
# 几何下限 ~1.9 m —— 用户走回镜头的整段读数冻结在 1.8/1.9。
# 12 px 的依据：覆盖实测欠检的主区间（5~12 px），同时小于 2 m 处真脚点的
# 安全余量（2 m 时真底边 ≈461 px、距底缘 19 px），不误伤已验收的 2 m 测量。
FOOT_CLIP_TOL_PX = 12.0       # 框底边距画面底边多少像素内视为「脚可能被裁」
# ⚠️ 滞回带宽（2026-09-26 用户授权治本，实录选参）：
# 上面那个 12 px 是**无记忆的硬阈值**，而实测底边帧间抖动中位 2.5~4.0 px、
# P90 11~17 px、最大 25~45 px（四个「走回镜头」会话），阈值线正好落在这片
# 抖动里 → `touches_bottom` 逐帧翻转，四个会话分别翻转 26/28/34/20 次。
# 它一侧是接触点法（脚出画时读假底边、读数冻结在几何下限 ~1.95 m），另一侧
# 是宽度法（1.3~1.6 m）；每切一次就是一次读数跳变，相邻帧斜率可达 3.9 m/s，
# 把 TTC / 趋势估计整体毒化。中值滤波只能压孤立尖刺，对这种「边界处来回切」
# 无能为力 —— 治本靠滞回：进入用 468、退出用 468−本值，带内保持上一状态。
# 12 px 的依据：覆盖实测抖动的 P90（11~17 px）主区间，把「真实过境」与
# 「噪声抖动」分开。代价是退出略滞后（读数在带内沿用参考级），实测代价见
# `E:\WorkBuddy-Work\scripts\analyze_foot_state_flip.py` 的「改判帧」列。
FOOT_CLIP_HYST_PX = 12.0      # 已判「脚出画」后，底边须再往回收这么多像素才恢复
MIN_CONTACT_ANGLE_DEG = 1.0   # 接触点法的最小俯角：低于此值地面交点趋近无穷远
MUTUAL_CHECK_RATIO = 0.30     # 双源互检：两法差异超过此比例即标「存疑」


@dataclass
class VisibilityReport:
    """一次检测框的可见性体检结果。

    为什么必须有这一步
    ------------------
    检测框是**可见部分的最小包围盒**，不是物体的完整轮廓 —— 目标只要露出一
    部分就会被框出来。``core/detector/postprocess.py`` 用 ``np.clip`` / ``min``
    把框压在画面内，所以**被画面裁掉的目标，其框边通常停在画面边界附近**。
    ⚠️ 但「必然贴在边界上」是理想化假设：YOLO 在画面底缘有 5~16 px 的
    系统性欠检（2026-09-25 录制实证），所以底边判定用专用容差
    ``FOOT_CLIP_TOL_PX``，见常量注释。

    而两条测距法都隐含「框是完整的」这个前提：

    * 高度法   ``Z = fy * H_目标 / 框高`` —— 要求框高 == 目标全身的像素高
    * 接触点法 ``Z = H_相机 / tan(俯角)`` —— 要求框底边 == 目标与地面的接触点

    框不完整时两法都会给出**自信的错值**。实测（``E:\\WorkBuddy-Work\\scripts\\
    verify_box_truncation.py``）：只有脸入画时，真实 0.40 m 被算成 2.96 m，
    误差 +639%，而且没有任何报错。所以顺序必须是「先体检、再决定出不出数」。
    """

    touches_top: bool = False      # 框上边贴画面顶边 -> 头顶被裁
    touches_bottom: bool = False  # 框下边贴/接近画面底边 -> 脚可能被裁（含
                                   # 检测器底缘欠检带，见 FOOT_CLIP_TOL_PX）
    touches_left: bool = False
    touches_right: bool = False
    aspect: float = 0.0            # 框宽 / 框高
    checked: bool = False          # 是否真的做了体检（不知道画面尺寸时为 False）

    @property
    def height_method_ok(self) -> bool:
        """高度法用整个框高，所以上下边都不能被裁。"""
        if not self.checked:
            return True
        return not (self.touches_top or self.touches_bottom)

    @property
    def ground_contact_ok(self) -> bool:
        """接触点法只要求**脚**可见 —— 头顶被裁不影响，这是它的相对优势。"""
        if not self.checked:
            return True
        return not self.touches_bottom

    def edge_text(self) -> str:
        names = []
        if self.touches_top:
            names.append('上')
        if self.touches_bottom:
            names.append('下')
        if self.touches_left:
            names.append('左')
        if self.touches_right:
            names.append('右')
        return ''.join(names)


def compute_box_visibility(box: dict, image_size,
                           tol: float = EDGE_TOL_PX) -> VisibilityReport:
    """由检测框 + 画面尺寸判定「框的哪条边被画面裁掉」。**纯函数**。

    ``box`` 用 ``YOLODetector`` 的字段（``x``/``y`` 是中心，``width``/``height``
    是尺寸），与 ``distance_from_box`` 保持一致。

    ⚠️ 底边用专用容差 ``FOOT_CLIP_TOL_PX``（12 px），不是其它边的 2 px ——
    YOLO 在画面底缘欠检 5~16 px（见该常量的注释），2 px 会把「脚已被裁」
    的框放过，让接触点法读假底边（实测整段走近过程读数冻结在 1.9 m）。
    """
    if not image_size or len(image_size) < 2:
        return VisibilityReport()
    img_w, img_h = float(image_size[0]), float(image_size[1])
    if img_w <= 0 or img_h <= 0:
        return VisibilityReport()

    cx = float(box.get('x', 0.0))
    cy = float(box.get('y', 0.0))
    w = float(box.get('width', 0.0))
    h = float(box.get('height', 0.0))

    x1, y1 = cx - w / 2.0, cy - h / 2.0
    x2, y2 = cx + w / 2.0, cy + h / 2.0

    return VisibilityReport(
        touches_top=y1 <= tol,
        touches_bottom=y2 >= img_h - max(tol, FOOT_CLIP_TOL_PX),
        touches_left=x1 <= tol,
        touches_right=x2 >= img_w - tol,
        aspect=(w / h) if h > 0 else 0.0,
        checked=True,
    )


class FootClipHysteresis:
    """「脚是否已出画」的**带记忆**判定 —— 治方法逐帧横跳（2026-09-26）。

    问题（实录量化，`E:\\WorkBuddy-Work\\scripts\\analyze_foot_state_flip.py`）
    -------------------------------------------------------------------------
    原先 `touches_bottom` 是一个**无记忆的硬阈值**：`y2 >= img_h - 12`。而实测
    底边帧间抖动中位 2.5~4.0 px、P90 11~17 px、最大 25~45 px（四个「人从远处
    走回镜头」会话），阈值线正好落在这片抖动里：四个会话分别翻转
    **26 / 28 / 34 / 20** 次。每一次翻转都是一次方法切换，而两侧读数差得很远：

    * 接触点法 —— 精确级，但脚出画时读到的是检测器截出来的**假底边**，
      任何比几何下限更近的距离都被算成下限（~1.95 m，实测整段冻结）；
    * 宽度法 —— 参考级（`Z = fx·肩宽/框宽`），给出 1.3~1.6 m。

    于是距离序列在 1.4 / 1.95 之间逐帧交替，**相邻帧斜率可达 3.9 m/s**，
    把一切吃距离序列求导的下游（TTC / 速度 / 趋势）整体毒化。

    为什么靠滤波解决不了
    --------------------
    中值窗压的是**单帧孤立的尖刺**；而这里是「边界处连续多帧来回切」——
    持续性的、方向上交替的、不是孤立尖刺。窗口只能把它延后（群延迟），
    消不掉。

    滞回怎么治
    ----------
    进入与退出用**两条不同的线**，中间是缓冲带，状态在带内保持不变：

    * 进入「脚出画」：``y2 >= img_h - tol_px``（= 468，与原硬阈值**完全相同**，
      所以「假底边不能当真脚」那条已验收的修复一字未改）；
    * 退出（脚回到画面内）：``y2 <= img_h - tol_px - hyst_px``（= 456）;
    * 带内（456 < y2 < 468）：**保持上一帧状态** —— 这就是「记忆」。

    效果是把 N 次翻转收敛成 1 次真实过境。真实过境仍有跳变，但只有一次，
    后续由 `core/ranging_filter.py` 的中值+One Euro 平滑掉。

    语义边界（重要）
    ----------------
    * 「无目标」（``y2 is None``）**保持状态，不当成脚的回落** —— 目标暂时丢失
      不等于脚回到了画面里。上层另有丢失重锚（`SpeedGate`）。
    * 「换人 / 换目标」要显式 ``reset``，否则新目标的初始状态会继承旧轨迹。
    * 它**只回答「脚出没出画」这一个问题**，不参与「框是否完整」的其它判断
      （顶边、左右边、宽高比一律仍按逐帧体检走）。
    """

    def __init__(self, tol_px: float = FOOT_CLIP_TOL_PX,
                 hyst_px: float = FOOT_CLIP_HYST_PX):
        if hyst_px < 0:
            raise ValueError('hyst_px 不能为负（负值会让退出线落在进入线下方，'
                             '状态将永不退出）')
        self.tol_px = float(tol_px)
        self.hyst_px = float(hyst_px)
        self._state: dict = {}

    # -- 只读视图（测试与诊断用，不参与判定）--
    def line(self, img_h: float) -> Tuple[float, float]:
        """返回 ``(进入线, 退出线)`` 的绝对行号，便于日志与测试核对。"""
        enter = float(img_h) - self.tol_px
        return enter, enter - self.hyst_px

    def state(self, key) -> bool:
        """当前状态（未见过该 key 时为 False）。"""
        return bool(self._state.get(key, False))

    def update(self, key, y2: Optional[float], img_h: Optional[float]) -> bool:
        """喂入本帧底边行号，返回本帧的「脚出画」判定（含记忆）。

        ``y2`` 为 ``None``（无目标）或 ``img_h`` 无效时**保持状态不变**。
        """
        st = bool(self._state.get(key, False))
        if y2 is None or not img_h or float(img_h) <= 0:
            self._state[key] = st
            return st
        enter, exit_ = self.line(float(img_h))
        if y2 >= enter:
            st = True
        elif y2 <= exit_:
            st = False
        self._state[key] = st
        return st

    def reset(self, key=None) -> None:
        """清状态。``key=None`` 清全部（换目标 / 回放跳转 / 换视频源时调用）。"""
        if key is None:
            self._state.clear()
        else:
            self._state.pop(key, None)

    def snapshots(self) -> dict:
        """当前所有 key 的状态快照（诊断用）。"""
        return dict(self._state)


def distance_from_ground_contact(v_bottom: float, intrinsics,
                                 camera_height: float,
                                 pitch_deg: float = 0.0,
                                 foot_offset_m: float = 0.0) -> Optional[float]:
    """地面接触点法（CHARTER「范围内的」第 2 条 ②）。**纯函数**。

    ``Z = (H_相机 − h_抬升) / tan(俯仰角 + atan((v_底 - cy) / fy))``

    两个关键性质：

    1. **不需要目标高度** —— 所以对未登记类别（椅子、小狗……）同样有效，
       这正好回答「不可能一直按人的标准算」。
    2. **不需要任何「地面识别」** —— 代码里没有地面分割、没有平面拟合、
       没有地平面检测。只有一条假设：*框底边中点落在地面上*。
       ``H_相机`` 由卷尺量得，与目标有多高、画面里有没有地面纹理都无关。

    ⚠️ ``foot_offset_m``（框底边抬升量，2026-10-01 实测引入）
    -----------------------------------------------------------------
    上面第 2 条里的假设「框底边 == 地面接触点」**在实测检测器上不成立**：
    4 m / 4.5 m 两段稳态帧放大脚部可见，绿框底边停在脚上方约小腿中部，
    反解出的等效相机高度恒为 0.731~0.743 m（与 cy、pitch 都无关），
    而卷尺量到的真实光心高度是 0.98 m —— 差 0.249 m 就是这段抬升量。

    几何上它把公式改成 ``Z = (H − h_off) / tan(α)``：底边对应的是目标身上
    离地 ``h_off`` 高的一点，相机到该点的垂直落差就是 ``H − h_off``。
    **默认 0.0，行为与引入前完全一致**（既有回归不受影响）。

    返回 ``None`` 表示这条假设无法成立（未装相机高度、视线接近水平、内参无效）。
    """
    if intrinsics is None or not intrinsics.is_valid():
        return None
    if camera_height is None or camera_height <= 0:
        return None

    fy = float(intrinsics.fy)
    if fy <= 0:
        return None

    off = float(foot_offset_m or 0.0)
    if not np.isfinite(off) or off < 0:
        return None
    h_eff = float(camera_height) - off
    if h_eff <= 0:
        # 抬升量不比相机高度还大 —— 那意味着底边在相机上方，接触点法无解
        return None

    angle = np.deg2rad(float(pitch_deg)) + np.arctan2(
        float(v_bottom) - float(intrinsics.cy), fy)
    if angle <= np.deg2rad(MIN_CONTACT_ANGLE_DEG):
        # 视线接近水平或朝上：与地面的交点不存在（或远到无意义）
        return None
    return float(h_eff / np.tan(angle))


def bottom_may_touch_ground(v_bottom: float, cy: float, fy: float,
                            pitch_deg: float = 0.0) -> bool:
    """框底边是否落在相机水平线**以下**（即可能踩在地面上）。**纯函数**。

    **不需要任何类别先验**的硬判据：底边若在相机水平线以上，「底边贴地」
    这条假设物理上不可能成立（要与地面相交，视线必须朝下）。
    实测「被挡到腰」那一格（底边落在画面中心线上方）就靠它拦下 ——
    旧实现会输出 6.38 m，真实 3.00 m。
    """
    angle = np.deg2rad(float(pitch_deg)) + np.arctan2(
        float(v_bottom) - float(cy), float(fy))
    return bool(angle > np.deg2rad(MIN_CONTACT_ANGLE_DEG))


def top_may_be_head(v_top: float, cy: float, fy: float,
                    pitch_deg: float = 0.0) -> bool:
    """框顶边是否落在相机水平线**以上**（即这一点可能比相机高）。**纯函数**。

    ``bottom_may_touch_ground`` 的镜像判据，用于**近场宽度法**的前提检查。

    物理依据：本项目机位下相机只有 0.64~1.2 m 高，而成年人的头顶在
    1.4~2.0 m —— **头顶必定高于相机**，所以「框顶边」这条视线必须朝上
    （俯仰角 + 像素偏移的合成角 < 0）。顶边若落在水平线以下，说明框的顶
    根本不是头顶（多半只框到上半身/一张脸），它的**框宽也就不是肩宽**。

    实测踩过：笔记本机位（H=0.70 m、俯仰 0°）下喂一个「顶边在 v=468、
    底边被画面下沿裁掉」的框，旧实现按框宽算出 **4.54 m**（目标实际只有
    2 m 远）——方向危险的错值。加上本判据后该框被拒（顶边在水平线以下）。
    """
    angle = np.deg2rad(float(pitch_deg)) + np.arctan2(
        float(v_top) - float(cy), float(fy))
    return bool(angle < 0.0)


def estimate_target_height(v_bottom: float, pixel_height: float,
                           intrinsics, camera_height: float,
                           pitch_deg: float = 0.0,
                           foot_offset_m: float = 0.0) -> Optional[float]:
    """反解「若框底边贴地，目标应有多高」—— 判定底边语义的主力判据。**纯函数**。

    先由接触点法得到距离 ``Z``，再由框高反推身高：``H = 框高 × Z / fy``。

    ⚠️ 为什么**不能**图省事写成 ``H = H_相机 / k``（``k = (v_底 - cy) / 框高``）：
    那个简化式**只在俯仰角为 0 时成立**。实测本机标定后（pitch=4°、H=1.0 m），
    5.00 m 处一个完整的人会被简化式算成 **2.65 m** —— 凭空多出 56% 余量，
    于是把好目标也拒掉（回归验证时当场暴露）。走接触点法没有这个偏差。

    拿反解值与类别登记身高比：落在合理区间 -> 底边大概率是脚；
    偏离 -> 框不完整，拒绝出数。实测
    （``E:\\WorkBuddy-Work\\scripts\\verify_box_bottom_semantics.py``）
    三个「旧实现会输错数字」的场景全部被拦下（被挡到腰由
    ``bottom_may_touch_ground`` 拦、被挡到膝上 3.88 m、只有下巴 3.57 m），
    而完整的成年人、1.40 m 矮个子、头顶被裁的人都照常放行。

    返回 ``None`` 表示无法反解（内参无效 / 未填相机高度 / 底边在水平线以上
    / 框高非正）。

    ⚠️ ``foot_offset_m`` 必须与 ``distance_from_ground_contact`` 传同一个值：
    底边抬升会让 ``Z`` 变小，本函数反解出的高度随之变小 —— 这正是它该有的
    行为（框覆盖的身体部分比「脚到头顶」短）。默认 0.0 = 旧行为。
    """
    if pixel_height is None or pixel_height <= 0:
        return None
    z = distance_from_ground_contact(v_bottom, intrinsics, camera_height,
                                     pitch_deg, foot_offset_m)
    if z is None:
        return None
    fy = float(intrinsics.fy)
    if fy <= 0:
        return None
    return float(pixel_height) * z / fy


@dataclass
class RangingResult:
    """一次测距的完整结论 —— 不只是数字，还包括「凭什么给这个数字」。"""

    distance: Optional[float] = None    # 米；None = 不可测
    method: str = ''                    # '接触点法' / '高度法' / '两法一致'
    trusted: bool = True                # False = 存疑（两法打架）
    reason: str = ''                    # 不可测或存疑的原因，供 UI 直接显示

    def display(self) -> str:
        """UI 用的短文本。存疑加「？」而不是隐藏 —— 让人知道有数据但不可全信。"""
        if self.distance is None:
            return '不可测'
        return f'{self.distance:.2f} m' + ('' if self.trusted else '？')


# ---------------------------------------------------------------------------
# 几何测距
# ---------------------------------------------------------------------------

class GeometricRanger:
    """由 2D 检测框 + 相机内参 + 目标真实高度，解算距离。

    对应 `CHARTER.md`「范围内的」第 2 条。
    与深度网络是**两种独立物理机制**，可交叉验证（第 4 条「双源互检」）。
    """

    def __init__(self, intrinsics: CameraIntrinsics,
                 config: Optional[RangingConfig] = None,
                 hysteresis: Optional[FootClipHysteresis] = None):
        self.intrinsics = intrinsics
        self.config = config or RangingConfig()
        # 「脚是否出画」的带记忆判定（2026-09-26 治本）。
        # 传 None 则退回无记忆硬阈值（旧行为）—— 单帧调用、离线测试用得上；
        # 实时链路**必须**给一个，否则方法会在阈值线上逐帧横跳（见该类 docstring）。
        self.hysteresis = hysteresis

    def reset_foot_state(self, key=None) -> None:
        """清「脚出画」状态。换目标 / 回放跳转 / 换视频源时调用。"""
        if self.hysteresis is not None:
            self.hysteresis.reset(key)

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

        返回 ``None`` 表示无法可靠测距（内参无效、目标太小、类别未登记真实高度）。
        """
        if not self.intrinsics.is_valid():
            return None
        if pixel_height < self.config.min_pixel_height:
            return None

        real_h = self.config.height_for(class_name)
        if real_h is None:
            # 类别未登记真实高度 -> 不出数。**不给兜底身高**：用一个编造的身高
            # 算出来的距离看着正常、却可能差几倍（见 height_for docstring）。
            return None
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

    def _distance_from_width(self, pixel_width: float) -> Optional[float]:
        """宽度法（近场参考值）：``Z = fx * 肩宽 / 框宽``。

        与高度法完全对称的投影修正（光轴深度 -> 地面距离），只是把
        「目标真实高度」换成「目标真实宽度」、框高换成框宽。

        为什么敢在脚出画时用它：框是**可见部分**的包围盒，脚出画只说明
        下边被裁；左右未裁时框宽仍等于这个人的真实可见宽度 —— 这个量
        没有被「太近」破坏。高度法/接触点法用的量（框高/框底边）才是
        被破坏的。

        精度天花板（写死成参考级的理由）：
        · 肩宽来自档案或默认 0.46 m，本身就是估计值；
        · 人一转身，「可见宽度」从肩宽变成肩深（~0.25 m），差近一倍；
        · 抬臂/拎物让框宽虚大。所以调用方必须标 ``trusted=False``。

        ⚠️ 不做俯仰修正（与高度法不同）：修正项需要 ``bottom_v`` 对应
        目标真实落点，而宽度法只在**脚出画**时启用 —— 那时 bottom_v 是
        被画面裁出来的假边，拿它修正等于用一个已知错误的量加戏。
        """
        if not self.intrinsics.is_valid():
            return None
        fx = float(self.intrinsics.fx)
        if fx <= 0 or pixel_width is None or pixel_width <= 0:
            return None
        return float(fx * self.config.person_width_m / pixel_width)

    def measure_from_box(self, box: dict, class_name: str = '',
                         image_size=None, track_key: Optional[str] = None
                         ) -> RangingResult:
        """综合入口：先体检可见性，再选方法出数，最后两法互检。

        优先级（接触点法优先，因为它不依赖目标高度）::

            脚可见且已量相机高度 -> 接触点法
            脚不可见但框完整     -> 高度法（仅限已登记真实高度的类别）
            框底边进底缘带（脚贴近画面底缘或已出画）、左右未裁、
                 顶边在相机水平线以上 -> 宽度法（仅限 person，**参考级**：
                 肩宽可能是估计值、侧身会高估，恒标 trusted=False）
            两法都算得出         -> 互检，差异超阈值标「存疑」
            都不行               -> 不可测，并把原因说到点子上

        **绝不返回兜底数字**：拿不到可靠值就明确说「不可测」。

        ``track_key``：传给 ``FootClipHysteresis`` 的状态键。默认用归一化后的
        类别名 —— 不同类别（人 / 椅子）各自维护状态，互不污染。
        本项目的定位是**单目标帧间守卫**（CHARTER「范围内的」第 5 条），
        同类多目标不在范围内；真需要时由调用方传显式 key。
        """
        if not self.intrinsics.is_valid():
            return RangingResult(reason='相机未标定')

        # 类别名归一化：标签文件可能给中文（coco_labels_cn.txt），而下面的
        # 宽度法门 / 身高表 / 宽高比表全部按规范英文名匹配（2026-09-25 22:14
        # 录制实证：不归一化时 person 专属逻辑整体静默失效）。
        class_name = canonical_class_name(class_name)

        # ---- 类别门（CHARTER v1.4：全链路唯一类别 = 行人）--------------------
        # 非 person 一律**拒绝出距离**，包括接触点法。接触点法本身与目标高度
        # 无关，几何上对任何「踩在地上的物体」都成立 —— 但它给出的只是
        # 「画面里某个点在几米外」，而本项目的下游（TTC、追踪目标、录制数据轨、
        # 人特征档案）全部按「人在哪」来解释这个数。放行非 person 等于让下游
        # 拿到一个语义不明的距离（2026-09-27 用户明确要求拒出）。
        #
        # 这里也是唯一一处「类别白名单」的强制点：高度法/宽度法/宽高比体检
        # 各自的门都靠表项存在与否，分散在多处；集中在这里，新增方法不会再漏。
        #
        # 触发这条门的现实路径有两条：
        #   · 标签文件缺失 -> 目标类别为「未知」（person 白名单建不起来，
        #     非 person 的框会漏进来，见 detector._refresh_person_class_ids）；
        #   · 标签文件被换成非 COCO 的、或类别确实不是人。
        # 两条都不该给数字 —— 后者是定位外的目标，前者连「是不是人」都不知道。
        if class_name not in self.config.object_heights:
            if not class_name or class_name == '未知':
                return RangingResult(
                    reason='目标类别未知（标签文件未加载或类别不在高度表内）：'
                           '本项目只测行人，拒出距离。请到设置页确认标签文件已加载')
            return RangingResult(
                reason=f'「{class_name}」不是登记类别（本项目只测行人），拒出距离')

        h_px = float(box.get('height', 0.0))
        w_px = float(box.get('width', 0.0))
        if h_px < self.config.min_pixel_height:
            return RangingResult(reason=f'目标太小（框高 {h_px:.0f} px）')

        if image_size is None:
            image_size = self.intrinsics.image_size
        vis = compute_box_visibility(box, image_size)
        bottom_v = float(box.get('y', 0.0)) + h_px / 2.0

        # ---- 「脚是否已出画」的**带记忆**判定（2026-09-26 治本）------------
        # 无记忆的硬阈值会让方法在阈值线上逐帧横跳（实测四个会话翻转
        # 26/28/34/20 次，读数在 1.4 / 1.95 m 之间交替，相邻帧斜率 3.9 m/s）。
        # 滞回在带内保持上一状态，把 N 次翻转收敛成 1 次真实过境。
        # 进入线与原硬阈值完全相同 → 「假底边不能当真脚」那条修复未被改动。
        #
        # 未配置滞回（离线单帧测试）或没做体检时退回 ``vis.touches_bottom``，
        # 即完全等于旧行为 —— 保证既有回归的语义不变。
        foot_out = vis.touches_bottom
        if (self.hysteresis is not None and vis.checked
                and image_size is not None):
            img_h = float(image_size[1])
            foot_out = self.hysteresis.update(
                track_key if track_key is not None else class_name,
                bottom_v, img_h)

        # ---- 主力判据：框底边到底能不能踩在地面上 ----
        # 实测三种「旧实现会输出错值」的情形全部靠这一段拦下：
        #     被挡到腰（底边落在画面中心线上方）-> bottom_may_touch_ground 硬判据
        #     被挡到膝上 -> 反解 3.88 m（真实 3.00 m 的人）
        #     只有下巴   -> 反解 3.57 m（真实 0.50 m）
        # 必须**直接拒出数**，不能只标「存疑」—— 标存疑仍会把错值显示出去。
        #
        # 前提「框上边 == 目标头顶、下边 == 脚」只在上下边都没被画面裁掉时
        # 成立。上边被裁 -> 反解出的身高必然偏小；下边被裁 -> 底边不是脚，
        # 交给后面的边界门控给出更准确的理由（「脚被画面下边界裁掉」）。
        if (vis.checked and not vis.touches_top and not foot_out
                and self.config.camera_height > 0
                and self.intrinsics.is_valid()):
            if not bottom_may_touch_ground(bottom_v, self.intrinsics.cy,
                                           self.intrinsics.fy,
                                           self.config.pitch_deg):
                return RangingResult(
                    reason=('框底边落在相机水平线以上，不可能踩在地面上：'
                            '目标不完整'))
            h_est = estimate_target_height(bottom_v, h_px, self.intrinsics,
                                           self.config.camera_height,
                                           self.config.pitch_deg,
                                           self.config.foot_offset_m)
            h_ref = self.config.object_heights.get(class_name)
            if h_est is not None and h_ref:
                lo_h = h_ref * (1.0 - self.config.height_tolerance)
                hi_h = h_ref * (1.0 + self.config.height_tolerance)
                if not (lo_h <= h_est <= hi_h):
                    return RangingResult(
                        reason=(f'若框底边贴地，目标应有 {h_est:.2f} m 高，'
                                f'超出「{class_name}」的合理范围 '
                                f'{lo_h:.2f}~{hi_h:.2f} m：目标可能不完整'))

        # ---- 框底边进底缘带（脚可能被裁，2026-09-25 实证冻结读数后收紧）----
        # 这一段必须排在宽高比体检**之前**：近场的人框天然不满足
        # 「站立的人 0.15~0.75」的宽高比先验（贴脸时框占满画面、宽高比 >1），
        # 若先过体检会把宽度法唯一能出数的路径整个拦掉。
        #
        # 触发条件是 ``foot_out``（= 滞回判定；无滞回时等于 ``vis.touches_bottom``）：
        # 底边距画面底边 ≤ FOOT_CLIP_TOL_PX（12 px）即进入，且**进入后要退回到
        # 468−FOOT_CLIP_HYST_PX 才恢复** —— 见 ``FootClipHysteresis`` docstring。
        # 为什么不能像以前那样只认「底边真的贴到 480」—— YOLO 在
        # 画面底缘欠检 5~16 px，被裁的脚给出的假底边落在 464~475，2 px 容差
        # 永远拦不住；接触点法读到假底边就会把任何 <1.9 m 的距离算成几何下限
        # ~1.9 m（19:45 录制：用户从 2 m 走回贴脸，整段读数冻结在 1.9 附近）。
        # 宁可把「脚可能还在画面里」的帧也降级成参考/警报，也不给冻结的错值。
        #
        # 宽度法（近场参考值，2026-09-25 P1+）：只要左右没被裁，框宽就是
        # 「这个人真实的可见宽度」—— 对正对/背对相机站立的人即肩宽（含臂）。
        # 这是几何法对近场的**最后一条路**，天生参考级：
        #   · 侧身时可见深度只有 ~0.25 m，会把距离**高估近一倍**
        #     （方向危险：以为远、实际近），所以恒标 trusted=False；
        #   · 抬臂/拎东西时框宽虚大 -> 距离偏近（方向安全）。
        # 缓解：跟随场景几乎都是背后跟（肩面朝相机，宽度法最准姿态），
        # 且指定了追踪目标时肩宽用**该目标档案里量出的值**（而非猜 0.46）。
        #
        # ⚠️ 前提：① 已填相机安装高度 —— 理由见下；② 框的**顶边必须落在相机
        # 水平线以上**（``top_may_be_head``）。依据是几何：本项目机位相机只有
        # 0.64~1.2 m 高，人的头顶在 1.4~2.0 m，**头顶必定高于相机**，所以框
        # 顶边的视线必须朝上。实测一个「顶边在画面内、底边被下沿裁掉」的不完整
        # 框（只框到上半身）会被宽度法算成 4.54 m（目标实际 2 m）—— 方向危险的
        # 错值；加上本判据即被拒。
        # 本机位下真正的近场框（整个人撑满画面）必然满足：脚出画的临界
        # 1.85 m 远小于头顶出画的临界 3.6 m，所以脚出画的人头也出画，
        # 框顶边在画面顶边（远高于水平线）。
        # ① 的理由：「脚是否出画」这件事本身要靠安装参数才判得准（见 1.85 m 那个
        # 临界）；安装参数没填时，全链路本来就给不出任何距离，这时最有用的一句话
        # 是「去填/去自标定安装参数」，而不是先给一个来路不明的参考值。
        if foot_out:
            if (class_name == 'person' and self.config.camera_height > 0
                    and top_may_be_head(
                        bottom_v - h_px, self.intrinsics.cy, self.intrinsics.fy,
                        self.config.pitch_deg)
                    and not vis.touches_left and not vis.touches_right
                    and w_px >= self.config.min_pixel_width):
                d_width = self._distance_from_width(w_px)
                if d_width is not None:
                    if d_width < 0.5:
                        # 距离近到 <0.5 m 时宽度法的误差已盖过信号
                        # （肩宽假设错 10% 就是 5 cm 以上），且这个量级
                        # 对控制端只剩一个语义：立即减速。给定性警报，
                        # 不给一个看起来精确的错值。
                        return RangingResult(
                            reason=('目标过近（宽度法估算 <0.5 m）：'
                                    '进入减速/制动区，不建议再接近'))
                    return RangingResult(
                        distance=d_width, method='宽度法(参考)', trusted=False,
                        reason=(f'参考值（宽度法）：脚贴近画面底缘或已出画，'
                                f'几何法已不可信，改按肩宽 '
                                f'{self.config.person_width_m:.2f} m 估算；'
                                f'侧身时可能高估近一倍，仅供减速参考'))
            # 宽度法也失效：框左右都贴边，或框宽已占满画面宽度的大头
            # （目标近到只剩躯干撑满画面）—— 这时给定性警报比给一个不可信
            # 的数更有用：刹车不需要精确值。
            # 「占满画面宽度」不能只看 touches_left/right：YOLO 在画面右缘
            # 也有欠检（实测贴脸帧右缘欠检可达 37 px），框宽占比是更稳的判据。
            fills_width = (vis.checked and image_size is not None
                          and w_px >= 0.85 * float(image_size[0]))
            if (vis.touches_left and vis.touches_right) or fills_width:
                return RangingResult(
                    reason=('目标过近（检测框已占满画面，宽度法也失效）：'
                            '进入减速/制动区'))
            # ---- 到这里宽度法不可用，只剩「把原因说到点子上」 ----
            # 判序（每条都对应实测出现过的一种画面）：
            #   ① 左右被裁     -> 横移出画，框宽已不是肩宽
            #   ② 未填安装高度 -> 接触点法无从下手（先说清缺什么）
            #   ③ 上下都贴边   -> 目标太近、整个人撑满画面（**最有用的一句**）
            #   ④ 顶边在水平线以下 -> 框的顶不是头顶，框不完整（别谎称「脚被裁」）
            #   ⑤ 其余只贴下沿 -> 底端无法确认，说明白而不是给数
            # ③ 必须排在后面几条前面：H = 0.64 m、俯仰 5° 的机位下，人走到脚
            # 出画（1.85 m）时头顶必然早已出画（头顶出画临界在 3.6 m），笼统的
            # 「超出画面上下边界」会把真正有用的一句（脚被裁 = 太近）永远挡在
            # 后面（实测踩过）。反过来 ④ 也不能省：顶边掉到水平线以下的框
            # 不是「太近」，是「检测框不完整」，说成「太近」会把用户引向错误处置。
            if vis.touches_left or vis.touches_right:
                return RangingResult(
                    reason='脚贴近画面底缘或已被裁，且检测框左/右被裁'
                           '（目标贴近画面边缘），宽度法不可用')
            if self.config.camera_height <= 0:
                return RangingResult(reason='脚贴近画面底缘或已被裁，且未填相机安装高度')
            if vis.touches_top:
                return RangingResult(
                    reason='脚贴近画面底缘或已被裁（目标太近，整个人撑满了画面）：'
                           '两条几何法都以「框底边 = 脚」为前提，脚不在画面里就无解')
            if not top_may_be_head(bottom_v - h_px, self.intrinsics.cy,
                                   self.intrinsics.fy, self.config.pitch_deg):
                return RangingResult(
                    reason='检测框顶边落在相机水平线以下：目标框不完整'
                           '（人的头顶必定高于相机，多半只框到上半身/头部），'
                           '框宽不能当作肩宽，无法可靠测距')
            return RangingResult(
                reason='框底边贴近画面底缘，无法确认目标底端（脚）未被裁：'
                       '目标可能较近，也可能恰好站在最近可测距离上；'
                       '为保证不出错值，此帧不给数')

        # ---- 以下都在「脚未出画」的前提下执行 -------------------------------
        # 上面那个 ``if foot_out:`` 块每条分支都 return，所以走到这里必有
        # ``foot_out is False``；而滞回的退出线在进入线**上方**，因此
        # ``foot_out`` 为假 ⇒ ``vis.touches_bottom`` 也为假 ⇒ 下面用到的
        # ``height_method_ok`` / ``ground_contact_ok`` 都成立（已体检时）。
        # 滞回只覆盖「脚出画」这一个判定，其它边一律仍按逐帧体检走。

        # ---- 兜底体检：宽高比（判别力有限，不作主力） ----
        # 实测被挡到腰 0.56、只有下巴 0.60 都落在「站立的人」区间内，全部逃过；
        # 它只能拦 aspect > 0.9 的极端情形（横向的手、极端特写）。
        lim = self.config.aspect_limits.get(class_name)
        if lim and vis.checked:
            lo, hi = lim
            if not (lo <= vis.aspect <= hi):
                return RangingResult(
                    reason=(f'框形状不像全身（宽高比 {vis.aspect:.2f}，'
                            f'{class_name} 正常 {lo:.2f}~{hi:.2f}），目标可能不完整'))

        # 高度法：要求框完整（类别已在方法开头过门 —— 未登记者根本走不到这里）
        d_height = None
        if vis.height_method_ok and class_name in self.config.object_heights:
            d_height = self.distance(pixel_height=h_px, bottom_v=bottom_v,
                                     class_name=class_name)

        # 接触点法：只要求脚可见
        d_contact = None
        if vis.ground_contact_ok:
            d_contact = distance_from_ground_contact(
                bottom_v, self.intrinsics, self.config.camera_height,
                self.config.pitch_deg, self.config.foot_offset_m)

        if d_contact is not None and d_height is not None:
            diff = abs(d_contact - d_height) / max(d_contact, d_height)
            if diff > MUTUAL_CHECK_RATIO:
                return RangingResult(
                    distance=d_contact, method='接触点法', trusted=False,
                    reason=(f'两法不一致（高度法 {d_height:.2f} m / '
                            f'接触点法 {d_contact:.2f} m）：目标可能不完整或姿态异常'))
            return RangingResult(distance=d_contact, method='两法一致')

        if d_contact is not None:
            return RangingResult(distance=d_contact, method='接触点法')
        if d_height is not None:
            return RangingResult(distance=d_height, method='高度法')

        # ---- 都不行：把原因说到点子上，绝不给兜底数字 ----
        # 「类别不在高度表内」的分支在方法开头已由类别门拦下，这里不再重复。
        if self.config.camera_height <= 0:
            return RangingResult(reason='未填相机安装高度')
        return RangingResult(reason='测距条件不足')

    def focal_length_px(self) -> Optional[float]:
        """返回等效焦距（像素）。调试用。"""
        if not self.intrinsics.is_valid():
            return None
        return self.intrinsics.fy
