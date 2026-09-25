"""按设备记忆的标定档案库 —— 「换相机自动认出来，没标定就提醒标定」。

为什么不是只把 ``calib.json`` 加个备注字段
------------------------------------------
因为要回答的问题变了。旧方案的隐含前提是「这台机器上只有一台相机」，
于是「换相机」这件事**在数据上不可见**：文件还是那个文件，程序照读不误。
一旦要支持多设备 / 换设备，就需要一张**按设备索引的表**，而不是一个文件。

为什么仍然保留 ``calib.json``
--------------------------
两个原因：① ``main_raspberry.py``（树莓派端，已冻结）仍按该路径读内参，
不能打断它；② 回滚安全 —— 新方案出问题时，旧文件还在。
所以写入时**两份都写**，读取时以档案库为准、旧文件作过渡。

档案库与安装参数为什么分开
------------------------
生命周期不同：内参跟**相机本体**走（换相机才重标），安装参数（H/θ）跟
**机位**走（挪相机才重做）。见 ``core/calibration.py`` 里的同款说明。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional, Tuple

from core.calibration import CameraIntrinsics

PROFILE_STORE_VERSION = 1
STORE_FILENAME = 'cameras.json'


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

def default_store_path(calib_path: str) -> str:
    """档案库与 ``calib.json`` 同目录 —— 一起备份、一起忽略，不会走散。"""
    return os.path.join(os.path.dirname(os.path.abspath(calib_path)),
                        STORE_FILENAME)


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------

def empty_store() -> dict:
    return {'version': PROFILE_STORE_VERSION, 'devices': {}, 'active': ''}


def load_store(path: str) -> dict:
    """读档案库。**任何异常都退化成空库，绝不抛**。

    理由：档案库坏了只应导致「要重新标定一次」，绝不能让程序起不来。
    这也是为什么不用 pickle、不用数据库 —— JSON 坏了肉眼能看懂、能手改。
    """
    if not path or not os.path.isfile(path):
        return empty_store()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return empty_store()
    if not isinstance(data, dict):
        return empty_store()
    devs = data.get('devices')
    if not isinstance(devs, dict):
        devs = {}
    return {
        'version': int(data.get('version', PROFILE_STORE_VERSION) or 1),
        'devices': {k: v for k, v in devs.items() if isinstance(v, dict) and k},
        'active': str(data.get('active', '') or ''),
    }


def save_store(path: str, store: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def get_profile(store: dict, fingerprint: str) -> Optional[dict]:
    if not fingerprint:
        return None
    prof = (store or {}).get('devices', {}).get(fingerprint)
    return prof if isinstance(prof, dict) else None


def set_active(store: dict, fingerprint: str) -> None:
    store['active'] = fingerprint or ''


def remove_profile(store: dict, fingerprint: str) -> bool:
    """删掉某台设备的标定（用户主动「重标」或清理时用）。"""
    devs = (store or {}).get('devices', {})
    if fingerprint in devs:
        del devs[fingerprint]
        if store.get('active') == fingerprint:
            store['active'] = ''
        return True
    return False


def profile_from_intrinsics(device, intrinsics: CameraIntrinsics,
                            note: str = '') -> dict:
    """把一次标定结果包成「属于某台设备」的档案。"""
    inner = asdict(intrinsics)
    inner['image_size'] = list(inner.get('image_size') or (0, 0))
    return {
        'name': getattr(device, 'name', '') or '',
        'hardware_id': getattr(device, 'hardware_id', '') or '',
        'instance_id': getattr(device, 'instance_id', '') or '',
        'service': getattr(device, 'service', '') or '',
        'fingerprint': getattr(device, 'fingerprint', '') or '',
        'image_size': list(intrinsics.image_size or (0, 0)),
        'rms_error': float(intrinsics.rms_error or 0.0),
        'calibrated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'note': note,
        'intrinsics': inner,
    }


def upsert_profile(store: dict, fingerprint: str, profile: dict) -> None:
    if not fingerprint or not isinstance(profile, dict):
        return
    store.setdefault('devices', {})[fingerprint] = profile
    set_active(store, fingerprint)


def profile_to_intrinsics(profile: dict) -> Optional[CameraIntrinsics]:
    """档案里的内参块还原成 ``CameraIntrinsics``；坏数据返回 None。"""
    if not isinstance(profile, dict):
        return None
    inner = profile.get('intrinsics')
    if not isinstance(inner, dict):
        return None
    data = dict(inner)
    data['image_size'] = tuple(data.get('image_size') or (0, 0))
    known = set(CameraIntrinsics.__dataclass_fields__)
    try:
        intr = CameraIntrinsics(**{k: v for k, v in data.items() if k in known})
    except (TypeError, ValueError):
        return None
    try:
        intr.fx = float(intr.fx)
        intr.fy = float(intr.fy)
        intr.cx = float(intr.cx)
        intr.cy = float(intr.cy)
        intr.rms_error = float(intr.rms_error or 0.0)
    except (TypeError, ValueError):
        return None
    return intr


def describe_profile(profile: dict) -> str:
    """一行说清「这份标定是什么时候、什么质量」。"""
    if not isinstance(profile, dict):
        return '无标定记录'
    when = profile.get('calibrated_at') or '时间未知'
    rms = profile.get('rms_error')
    sz = profile.get('image_size') or [0, 0]
    txt = f'已标定 {when}'
    if isinstance(rms, (int, float)):
        txt += f'，重投影误差 {rms:.3f} px'
    txt += f'，标定分辨率 {int(sz[0])}x{int(sz[1])}'
    return txt


# ---------------------------------------------------------------------------
# 给旧标定文件盖「设备戳」
# ---------------------------------------------------------------------------
#
# 为什么需要
# --------
# ``calib.json`` 是给旧版程序与树莓派端读的，本身不带设备信息。但这样会留一个
# 很顽固的漏洞：用户给相机 A 标定完，之后插上**另一台同分辨率**的相机 B，
# 判定会走到「沿用旧标定文件（未绑定设备）」—— 等于把 A 的内参用在 B 上，
# 距离系统性错，而用户很可能就按"先用着"过去了。
#
# 只要新版本标定过一次，就能顺手给文件盖个戳：以后插别的相机时，程序能明确说
# 「这份标定属于另一台相机」并**拒用**。戳是附加字段，旧代码读它时会被忽略
# （``CameraCalibrator.load`` 只取 dataclass 里有的字段），所以对老程序无害。

LEGACY_DEVICE_FIELD = 'device'
LEGACY_STAMP_TIME_FIELD = 'device_stamped_at'


def stamp_device(path: str, fingerprint: str) -> bool:
    """在标定文件里记下「这份标定属于哪台设备」。成功返回 True。

    先写临时文件再 ``os.replace``：避免写到一半断电留下半个 JSON
    —— 标定文件坏了会直接导致测距不可用，不能靠运气。
    """
    if not path or not fingerprint:
        return False
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    data[LEGACY_DEVICE_FIELD] = fingerprint
    data[LEGACY_STAMP_TIME_FIELD] = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def read_stamped_device(path: str) -> str:
    """读标定文件里的设备戳；没盖过戳或读不到时返回空串。"""
    if not path or not os.path.isfile(path):
        return ''
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return ''
    if not isinstance(data, dict):
        return ''
    return str(data.get(LEGACY_DEVICE_FIELD, '') or '')


# ---------------------------------------------------------------------------
# 判定：这次启动能不能直接用、要不要提醒标定
# ---------------------------------------------------------------------------

# 判定来源
SRC_DEVICE = 'device'   # 本设备自己的标定
SRC_LEGACY = 'legacy'   # 沿用旧的 calib.json（未绑定设备）
SRC_NONE = 'none'       # 没有可用标定


@dataclass
class CalibrationDecision:
    """「本次启动用哪份内参、要不要提醒标定」的完整结论 —— 纯数据，可单独验证。"""

    source: str = SRC_NONE
    intrinsics: Optional[CameraIntrinsics] = None   # None = 测距不可用
    status: str = ''            # 一行短状态，直接进 UI
    detail: str = ''            # 多行说明
    blocked_reason: str = ''    # 有标定文件但被拒用的原因（分辨率不符等）
    needs_calibration: bool = False
    can_bind_legacy: bool = False   # 是否可「把当前标定绑定到本设备」
    matched: bool = False           # 是否命中了本设备自己的档案

    @property
    def usable(self) -> bool:
        return self.intrinsics is not None and self.intrinsics.is_valid()


def _size_mismatch(a, b) -> bool:
    """两个分辨率是否不一致。任一未知（None/0）时不算不一致。"""
    try:
        aw, ah = int(a[0]), int(a[1])
        bw, bh = int(b[0]), int(b[1])
    except (TypeError, IndexError, ValueError):
        return False
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return (aw, ah) != (bw, bh)


def decide_calibration(store: dict,
                       fingerprint: str = '',
                       legacy: Optional[CameraIntrinsics] = None,
                       frame_size=None,
                       identity_known: bool = True,
                       legacy_device: str = '') -> CalibrationDecision:
    """决定用哪份内参。**纯函数** —— 不碰文件、不碰 UI。

    五条规则（按优先级）::

        1. 本设备档案存在且分辨率相符      -> 用它            （"已标定"）
        2. 本设备档案存在但分辨率不符      -> **拒用** + 提醒重标
        3. 旧文件盖上别的设备的戳          -> **拒用** + 提醒重标
        4. 没有本设备档案、旧文件可用      -> 暂用它 + 提醒绑定/重标
        5. 都没有                          -> 不装内参 + 提醒标定

    第 2 条是这个模块存在的**主要理由**：旧实现在这种情况下会照常使用旧内参，
    距离系统性错而界面零提示。宁可不给数字，也不给错数字 —— 与
    ``GeometricRanger`` 的「绝不返回兜底数字」是同一个原则。
    第 3 条堵的是最顽固的一种形态：给相机 A 标定后插上**同分辨率**的相机 B。

    第 4 条是**兼容**：老用户机器上只有一个 ``calib.json``（没盖过戳），
    一升级就要求重标不合理。所以先照旧能用（行为不变），但状态栏明确标注
    「未绑定设备」，并给一个「绑定到本设备」按钮把话说清楚。
    """
    prof = get_profile(store, fingerprint)
    if prof:
        intr = profile_to_intrinsics(prof)
        when = describe_profile(prof)
        if intr is None or not intr.is_valid():
            return CalibrationDecision(
                source=SRC_DEVICE, status='本设备的标定记录已损坏',
                detail=f'{when}\n记录里没有有效内参，请重新标定。',
                blocked_reason='档案内容无效', needs_calibration=True,
                matched=True)
        if _size_mismatch(intr.image_size, frame_size):
            return CalibrationDecision(
                source=SRC_DEVICE, status='标定分辨率与当前画面不符',
                detail=(f'本设备的标定是按 {intr.image_size[0]}x{intr.image_size[1]} 做的，'
                        f'当前画面是 {int(frame_size[0])}x{int(frame_size[1])}。\n'
                        f'内参随分辨率变化，套用会让距离整体偏掉 —— '
                        f'所以这份标定不启用。请重新标定。'),
                blocked_reason=(f'标定分辨率 {intr.image_size[0]}x{intr.image_size[1]}'
                                f' ≠ 当前画面 {int(frame_size[0])}x{int(frame_size[1])}'),
                needs_calibration=True, matched=True)
        return CalibrationDecision(
            source=SRC_DEVICE, intrinsics=intr, status='已标定（本设备）',
            detail=when + '。换相机不影响这份记录；挪相机只需重做安装参数。',
            matched=True)

    # ---- 没有本设备档案：看旧文件 ----
    if legacy is not None and legacy.is_valid():
        if legacy_device and fingerprint and legacy_device != fingerprint:
            # 旧文件盖着**别的设备**的戳：绝不能拿它的内参给当前相机用
            return CalibrationDecision(
                source=SRC_LEGACY, status='旧标定文件属于另一台相机',
                detail=(f'这个标定文件记着属于「{legacy_device}」，'
                        f'而当前相机是「{fingerprint}」。\n'
                        f'不同相机的内参不能混用（焦距、主点都不同），'
                        f'所以这份标定不启用。\n'
                        f'请对当前相机标定一次 —— 标完会按设备记住，'
                        f'以后换回来也自动可用。'),
                blocked_reason=f'旧标定文件属于另一台相机（{legacy_device}）',
                needs_calibration=True)
        if _size_mismatch(legacy.image_size, frame_size):
            return CalibrationDecision(
                source=SRC_LEGACY, status='旧标定文件与当前分辨率不符',
                detail=(f'旧标定文件是按 {legacy.image_size[0]}x{legacy.image_size[1]} 做的，'
                        f'当前画面是 {int(frame_size[0])}x{int(frame_size[1])}。\n'
                        f'这种情况不启用这份内参（否则距离会系统性偏）。\n'
                        f'请对当前相机重新标定一次，之后它会按设备记住。'),
                blocked_reason=(f'旧文件分辨率 {legacy.image_size[0]}x{legacy.image_size[1]}'
                                f' ≠ 当前画面 {int(frame_size[0])}x{int(frame_size[1])}'),
                needs_calibration=True)
        detail = (f'标定分辨率 {legacy.image_size[0]}x{legacy.image_size[1]}、'
                  f'重投影误差 {legacy.rms_error:.3f} px。\n'
                  f'这份标定还没有归到具体哪台设备名下 —— 本次先照旧使用。'
                  f'标定一次即可绑定到当前设备，之后换相机不会再混用。')
        if not identity_known:
            detail += '\n（读不到本机设备标识，暂时无法按设备区分。）'
        return CalibrationDecision(
            source=SRC_LEGACY, intrinsics=legacy,
            status='沿用旧标定文件（未绑定设备）', detail=detail,
            can_bind_legacy=True)

    # ---- 什么都没有 ----
    if not identity_known:
        detail = ('读不到本机设备标识，也没有可用的标定文件。\n'
                  '测距不可用（不会给出猜测值）。请先在「相机标定」里采帧求解。')
    else:
        detail = ('这台相机还没有标定过。\n'
                  '测距不可用（不会给出猜测值）—— '
                  '请把棋盘格放到画面里，点「开始采集」，采够 10 帧后点「求解并保存」；\n'
                  '解完的结果会按这台设备记住，以后插回来直接可用。')
    return CalibrationDecision(source=SRC_NONE, status='本设备未标定',
                               detail=detail, needs_calibration=True)
