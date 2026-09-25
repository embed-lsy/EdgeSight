"""摄像头设备识别 —— 「像蓝牙那样记住每台设备」的底座。

解决什么问题
------------
标定结果（内参）是**跟着相机本体**走的：换一台相机，旧的 fx/fy/cx/cy 就作废。
但旧实现只有一个 ``models/calib.json``，程序**不知道自己正在用哪台相机**，
于是会产生两种静默错误：

1. 换了一台**同分辨率**的相机 —— 旧内参被照常沿用，距离系统性错，界面零提示；
2. 相机自带的 ``_tune_if_needed()`` 把过大画面调回 640x480，让尺寸**恰好**
   对得上，把「换了设备」这件事掩盖掉。

所以要「按设备记忆」，先得能回答「现在这台是谁」。本模块只做这一件事：
**枚举本机摄像头，给出稳定指纹与人可读名字**。它不碰标定、不碰 UI。

为什么不用 OpenCV
----------------
实测（``E:\\WorkBuddy-Work\\scripts\\probe_camera_identity.py``）：
OpenCV 没有任何可用的设备名属性 —— ``cv2`` 里含 ``DEVICE`` 的常量全是
Android / iOS / 工业相机（XIMEA）专用，桌面平台的 ``VideoCapture``
**拿不到人可读设备名**。所以必须走系统层枚举。

为什么 Windows 用注册表而不是 PowerShell（实测数据）
--------------------------------------------------
``E:\\WorkBuddy-Work\\scripts\\probe_identity_routes.py`` 四条通路实测中位耗时：

    R. 注册表直读 DeviceClasses        1.4 ms   ← 采用
    W. wmic                          2185 ms   Win11 已移除，返回 0 行
    P. Get-PnpDevice                 4864 ms   **部分机器上根本没有该模块**
    C. Get-CimInstance + 类过滤       6842 ms

PowerShell 通路除了慢 3000 倍，还有两个坑：本机 ``Get-PnpDevice`` 模块缺失
（白等 6.1 s 拿到 0 条），以及它默认按 UTF-8 解码 GBK 输出会抛
``UnicodeDecodeError``。所以注册表是主通路，PowerShell 只在注册表不可用时兜底。

两个必须记住的实测教训
--------------------
1. **不能拿 ``ContainerID`` 当指纹**：本机枚举出的 7 个设备该值全是
   ``{00000000-0000-0000-ffff-ffffffffffff}`` 占位符，毫无区分度。
2. **不能按 ``Image`` 类枚举**：该类混着**指纹识别器**等非摄像头设备
   （本机实测 ``Githon M3078DNA``）。同一接口类 GUID 下还混着**麦克风端点**
   （Intel 智音技术），必须靠 ``ClassGUID`` / ``Service`` 区分开。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 设备接口类：KS 类别 "Audio/Video Capture"。摄像头与麦克风都挂在这里，
# 所以它只能用来「找到候选」，不能用来「判定是摄像头」。
GUID_INTERFACE_VIDEO_CAPTURE = '{65e8773d-8f56-11d0-a3b9-00a0c9223196}'

# PnP 类 GUID：用来把麦克风端点排除掉。
GUID_CLASS_CAMERA = '{ca3e7ab9-b4c3-4ae6-8251-579ef933890f}'   # Win10+ 摄像头
GUID_CLASS_IMAGE = '{6bdd1fc6-810f-11d0-bec7-08002be2092f}'    # 旧版「图像设备」
GUID_CLASS_MEDIA = '{4d36e96c-e325-11ce-bfc1-08002be10318}'    # 媒体/音频（麦克风）

# 驱动服务名：USB 摄像头几乎都是这两个之一（UVC 标准）。
VIDEO_SERVICES = ('usbvideo', 'uvcvideo')

_REG_VIDEO_CAPTURE = ('SYSTEM\\CurrentControlSet\\Control\\DeviceClasses'
                      '\\' + GUID_INTERFACE_VIDEO_CAPTURE)
_REG_ENUM = 'SYSTEM\\CurrentControlSet\\Enum'

DEFAULT_LINUX_SYSFS = '/sys/class/video4linux'


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class CameraDevice:
    """一台摄像头设备。``fingerprint`` 是进档案库的钥匙，其余只给人看。"""

    fingerprint: str = ''
    name: str = ''
    hardware_id: str = ''        # 如 USB\VID_13D3&PID_54B1&MI_00（不含端口后缀）
    instance_id: str = ''        # 如 USB\VID_13D3&PID_54B1&MI_00\6&2aab9560&0&0000
    index: Optional[int] = None  # 设备索引；**只有 Linux 能精确给出**，Windows 为 None
    service: str = ''            # 驱动服务名（usbvideo 等），排查用
    class_guid: str = ''
    provider: str = ''           # 由哪条通路枚举出来的，排查用

    def label(self) -> str:
        """下拉框里给人看的一行。"""
        if self.index is not None:
            return f'{self.name}（索引 {self.index}）'
        return self.name or self.fingerprint


@dataclass
class IdentityReport:
    """一次枚举的完整结果 —— 含「凭什么这么说」。"""

    devices: List[CameraDevice] = field(default_factory=list)
    provider: str = ''           # registry / pnp / cim / sysfs / 空
    error: str = ''              # 非空 = 枚举失败（区别于「枚举成功但没有设备」）
    ms: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.error

    def summary(self) -> str:
        if self.error:
            return f'设备枚举失败（{self.provider or "无可用通路"}）：{self.error}'
        if not self.devices:
            return f'未检测到摄像头设备（{self.provider}，{self.ms:.0f} ms）'
        names = '、'.join(d.name or d.hardware_id for d in self.devices)
        return (f'检测到 {len(self.devices)} 台：{names}'
                f'（{self.provider}，{self.ms:.0f} ms）')


@dataclass
class ActiveDevice:
    """「程序正在用的那台是谁」的结论。"""

    device: Optional[CameraDevice] = None
    confidence: str = 'none'     # 见下面 CONF_* 常量
    reason: str = ''

    @property
    def certain(self) -> bool:
        """是否**确定**程序打开的设备就是这一台。"""
        return self.confidence in (CONF_UNIQUE, CONF_CHOSEN)

    @property
    def usable(self) -> bool:
        """指纹是否可用于档案库查表（存疑也能用，只是要如实标注）。"""
        return self.device is not None and bool(self.device.fingerprint)


# 置信度：能确定 / 用户指定 / 记住的（多设备下假定）/ 多设备但不知道是哪台 / 没设备 / 平台不支持
CONF_UNIQUE = 'unique'
CONF_CHOSEN = 'chosen'
CONF_REMEMBERED = 'remembered'
CONF_AMBIGUOUS = 'ambiguous'
CONF_NONE = 'none'
CONF_UNSUPPORTED = 'unsupported'

CONF_TEXT = {
    CONF_UNIQUE: '本机仅一台，已确认',
    CONF_CHOSEN: '已按你的指定确认',
    CONF_REMEMBERED: '多台设备，按上次记住的一台',
    CONF_AMBIGUOUS: '多台设备，无法确定程序用的是哪一台',
    CONF_NONE: '未检测到摄像头',
    CONF_UNSUPPORTED: '本平台/环境读不到设备标识',
}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def normalize_name(raw: str) -> str:
    """把 INF 资源引用还原成人可读名字。

    注册表里 ``FriendlyName`` 常是 ``@oem205.inf,%DeviceDesc_RGB_IC%;Integrated Camera``
    这种形式：``;`` 后面才是真名，前面是驱动 INF 里的资源索引。
    直接显示会很难看，而且用户根本对不上自己插的是哪台。
    """
    if not raw:
        return ''
    s = str(raw).strip()
    if ';' in s:
        tail = s.rsplit(';', 1)[1].strip()
        if tail:
            s = tail
    return s.strip()


def normalize_hardware_id(hwid: str) -> str:
    """``USB\\VID_13D3&PID_54B1&MI_00`` -> ``usb:vid_13d3&pid_54b1&mi_00``

    只保留标识性字符（字母数字、``&``、``_``、``:``），避免不同系统上
    反斜杠/大小写写法不同导致指纹对不上、档案库查不到自己的标定。
    """
    if not hwid:
        return ''
    s = str(hwid).strip().lower().replace('\\', ':')
    keep = []
    for ch in s:
        if ch.isalnum() or ch in '&_:-':
            keep.append(ch)
    return ''.join(keep)


def fingerprint_for(hardware_id: str = '', instance_id: str = '',
                    name: str = '') -> str:
    """算设备指纹。**优先硬件 ID**（同型号多台也能区分到型号级）。

    为什么不用完整实例路径做主键：USB 设备的实例路径尾段（``6&2aab9560&0&0000``）
    是**端口哈希**，把相机换个 USB 口就会变 —— 拿它当主键会导致「换了插口就
    认不出自己的标定」。带序列号的设备尾段是序列号（稳定），但绝大多数
    UVC 摄像头不提供序列号，所以统一以硬件 ID 为准，实例路径只作补充记录。
    """
    hw = normalize_hardware_id(hardware_id)
    if hw:
        return hw
    inst = normalize_hardware_id(instance_id)
    if inst:
        return inst
    if name:
        return 'name:' + normalize_name(name).lower()
    return ''


def _decode_console(raw: bytes) -> str:
    """按系统本地编码解码子进程输出。

    Windows 控制台默认 GBK；用 UTF-8 硬解会抛 ``UnicodeDecodeError``
    （实测踩到，线程里报错还会被吞掉，表现为「莫名其妙拿不到结果」）。
    """
    if not raw:
        return ''
    enc = sys.getencoding() if hasattr(sys, 'getencoding') else None
    for codec in (enc, 'gbk', 'utf-8'):
        if not codec:
            continue
        try:
            return raw.decode(codec)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')


def _run_powershell(cmd: str, timeout: float = 20.0) -> Tuple[str, str]:
    """跑一段 PowerShell，返回 (stdout, 错误说明)。**慢，只作兜底**。"""
    try:
        p = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive',
             '-ExecutionPolicy', 'Bypass', '-Command', cmd],
            capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except subprocess.TimeoutExpired:
        return '', f'PowerShell 超时（>{timeout:.0f}s）'
    except FileNotFoundError as e:
        return '', f'找不到 powershell.exe：{e}'
    except OSError as e:
        return '', f'PowerShell 启动失败：{e}'
    out = _decode_console(p.stdout)
    # 注意：PowerShell 单引号字符串里 `` `t `` 不会被转义成制表符（实测踩到），
    # 所以调用方一律用双引号拼格式化字符串。
    if p.returncode != 0 and not out.strip():
        return out, f'退出码 {p.returncode}：{_decode_console(p.stderr).strip()[:200]}'
    return out, ''


# ---------------------------------------------------------------------------
# Windows：注册表直读（主通路）
# ---------------------------------------------------------------------------

def _read_reg_values(path: str) -> dict:
    """读一个注册表键的全部值；失败返回 ``{}``。"""
    import winreg
    out = {}
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError:
        return out
    try:
        i = 0
        while True:
            try:
                name, val, _typ = winreg.EnumValue(k, i)
            except OSError:
                break
            i += 1
            out[name] = val
    finally:
        winreg.CloseKey(k)
    return out


def decode_interface_key(interface_key: str) -> str:
    """把 DeviceClasses 子键名还原成设备实例路径。

    ``##?#USB#VID_13D3&PID_54B1&MI_00#6&2aab9560&0&0000#{65e8773d-...}``
      -> ``USB\\VID_13D3&PID_54B1&MI_00\\6&2aab9560&0&0000``

    注册表把路径首部 ``\\\\?\\`` 转义成了 ``##?#``，中间的 ``\\`` 全写成 ``#``，
    末尾再挂一个接口类 GUID。**这里很容易拼错** —— 拼错的表现是
    ``系统找不到指定的文件``，看上去像权限问题，其实是路径构造错了。
    """
    if not interface_key:
        return ''
    s = str(interface_key)
    if s.startswith('##?#'):
        s = s[4:]
    elif s.startswith('#'):
        s = s[1:]
    parts = s.split('#')
    if parts and parts[-1].startswith('{'):
        parts = parts[:-1]
    return '\\'.join(p for p in parts if p)


def _looks_like_camera(values: dict) -> Tuple[bool, str]:
    """按注册表值判断这是不是一个**摄像头**（而非麦克风端点等）。

    为什么要判：同一个接口类 GUID 下既挂着摄像头，也挂着麦克风
    （本机实测 7 个条目里 6 个是 Intel 智音技术的音频端点）。
    只看接口类会把麦克风当摄像头记进档案库。

    返回 (是否摄像头, 判定依据)。
    """
    guid = str(values.get('ClassGUID', '') or '').strip().lower()
    service = str(values.get('Service', '') or '').strip().lower()
    if service in VIDEO_SERVICES:
        return True, f'Service={service}'
    if guid == GUID_CLASS_CAMERA:
        return True, 'PnP 类=Camera'
    if guid == GUID_CLASS_IMAGE:
        return True, 'PnP 类=图像设备（旧版命名）'
    if guid == GUID_CLASS_MEDIA:
        return False, '媒体/音频类（麦克风端点）'
    if not guid:
        return False, '无 ClassGUID，无法判定'
    return False, f'未知类 {guid}'


def enumerate_windows_registry() -> IdentityReport:
    """注册表直读枚举摄像头。**本机实测 1.4 ms**。

    速度是这里的硬指标：它会跑在启动路径上，任何一次慢查询都是用户可见的卡顿。
    """
    t0 = time.perf_counter()
    devices: List[CameraDevice] = []
    skipped: List[str] = []
    try:
        import winreg
    except ImportError:                                   # 非 Windows
        return IdentityReport(provider='registry',
                              error='当前平台没有 winreg（非 Windows）')

    try:
        h = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REG_VIDEO_CAPTURE)
    except FileNotFoundError:
        # 这个类键不存在 = 本机从来没注册过视频采集接口 = **确实没有摄像头**。
        # 这跟「通路不可用」是两回事：把它当错误会让上层白跑一次 5~7 秒的
        # PowerShell 兜底查询（实测每轮启动都白等），所以这里明确返回「空但不是错」。
        return IdentityReport(devices=[], provider='registry', error='',
                              ms=(time.perf_counter() - t0) * 1000)
    except OSError as e:
        return IdentityReport(
            provider='registry',
            error=f'打不开设备接口键（{e}）',
            ms=(time.perf_counter() - t0) * 1000)

    keys = []
    try:
        i = 0
        while True:
            try:
                keys.append(winreg.EnumKey(h, i))
            except OSError:
                break
            i += 1
    finally:
        winreg.CloseKey(h)

    for sub in keys:
        # 有的系统把实例路径直接写成值，优先用它（比解析键名可靠）
        vals = _read_reg_values(f'{_REG_VIDEO_CAPTURE}\\{sub}')
        inst = str(vals.get('DeviceInstance', '') or '') or decode_interface_key(sub)
        if not inst:
            skipped.append(f'{sub[:40]}…（无法还原实例路径）')
            continue
        full = _read_reg_values(f'{_REG_ENUM}\\{inst}')
        if not full:      # Enum 键读不到：设备已拔出但接口项残留
            skipped.append(f'{inst}（Enum 键不存在，可能已拔出）')
            continue
        merged = dict(full)
        merged.update({k: v for k, v in vals.items() if k not in full})
        is_cam, why = _looks_like_camera(merged)
        if not is_cam:
            skipped.append(f'{normalize_name(full.get("FriendlyName", "")) or inst}'
                           f'（{why}）')
            continue
        hwid = inst.rsplit('\\', 1)[0]        # 去掉端口后缀，取硬件 ID
        devices.append(CameraDevice(
            fingerprint=fingerprint_for(hwid, inst, ''),
            name=(normalize_name(merged.get('FriendlyName', ''))
                  or normalize_name(merged.get('DeviceDesc', ''))
                  or hwid),
            hardware_id=hwid,
            instance_id=inst,
            index=None,            # Windows 上 DSHOW 顺序未知，见 resolve_active_device
            service=str(merged.get('Service', '') or ''),
            class_guid=str(merged.get('ClassGUID', '') or ''),
            provider='registry',
        ))

    rep = IdentityReport(devices=devices, provider='registry',
                         ms=(time.perf_counter() - t0) * 1000)
    if skipped:
        rep.error = ''       # 跳过的不是错误，但要能查到跳过了什么
        rep.__dict__['skipped'] = skipped
    return rep


def enumerate_windows_pnp() -> IdentityReport:
    """PowerShell 兜底通路（**5~7 秒**，只在注册表通路失败时用）。

    只用 ``Camera`` 类 —— 加上 ``Image`` 会把指纹识别器等非摄像头设备
    一起收进来（本机实测踩到）。
    """
    t0 = time.perf_counter()
    # 优先 Get-PnpDevice；部分机器没有该模块（本机就是），再退到 CIM
    out, err = _run_powershell(
        "Get-PnpDevice -Class Camera -ErrorAction SilentlyContinue |"
        " ForEach-Object { \"{0}`t{1}`t{2}\" -f $_.Status,$_.FriendlyName,"
        "$_.InstanceId }")
    provider = 'pnp'
    if err or not out.strip():
        out2, err2 = _run_powershell(
            "Get-CimInstance Win32_PnPEntity -Filter \"PNPClass='Camera'\" "
            "-ErrorAction SilentlyContinue | ForEach-Object {"
            " \"{0}`t{1}`t{2}\" -f $_.Status,$_.Name,$_.PNPDeviceID }")
        provider = 'cim'
        if out2.strip():
            out, err = out2, ''
        else:
            return IdentityReport(
                provider=provider, error=err or err2 or '两条 PowerShell 通路都没结果',
                ms=(time.perf_counter() - t0) * 1000)

    devices = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split('\t')]
        if len(parts) < 3 or not parts[2]:
            continue
        inst, name = parts[2], normalize_name(parts[1])
        hwid = inst.rsplit('\\', 1)[0]
        devices.append(CameraDevice(
            fingerprint=fingerprint_for(hwid, inst, name),
            name=name or hwid, hardware_id=hwid, instance_id=inst,
            index=None, provider=provider))
    return IdentityReport(devices=devices, provider=provider,
                          ms=(time.perf_counter() - t0) * 1000)


# ---------------------------------------------------------------------------
# Linux：sysfs 直读（索引可精确对应）
# ---------------------------------------------------------------------------

def enumerate_linux(sysfs_root: str = DEFAULT_LINUX_SYSFS) -> IdentityReport:
    """读 ``/sys/class/video4linux/videoN`` 枚举摄像头。

    Linux 上的好处是 ``videoN`` 的下标**就是** OpenCV 的 ``camera_index``，
    所以这里能给出精确的索引映射（Windows 给不出）。

    ``sysfs_root`` 可注入 —— 这样解析逻辑能在非 Linux 机器上用假目录结构验证，
    不必真的找一台树莓派。
    """
    t0 = time.perf_counter()
    if not os.path.isdir(sysfs_root):
        return IdentityReport(provider='sysfs',
                              error=f'没有 {sysfs_root}（非 Linux 或内核未启用 v4l2）',
                              ms=(time.perf_counter() - t0) * 1000)

    devices = []
    for entry in sorted(os.listdir(sysfs_root)):
        if not entry.startswith('video'):
            continue
        try:
            index = int(entry[5:])
        except ValueError:
            index = None
        dir_path = os.path.join(sysfs_root, entry)
        name = ''
        try:
            with open(os.path.join(dir_path, 'name'), 'r',
                      encoding='utf-8', errors='replace') as f:
                name = normalize_name(f.read())
        except OSError:
            pass

        # 沿 device 目录向上找 USB 设备节点（idVendor/idProduct/serial）
        vid = pid = serial = ''
        try:
            node = os.path.realpath(os.path.join(dir_path, 'device'))
            for _ in range(4):            # 接口 -> 设备，最多上溯几层
                if os.path.isfile(os.path.join(node, 'idVendor')):
                    vid = _read_text(os.path.join(node, 'idVendor'))
                    pid = _read_text(os.path.join(node, 'idProduct'))
                    serial = _read_text(os.path.join(node, 'serial'))
                    break
                parent = os.path.dirname(node)
                if parent == node:
                    break
                node = parent
        except OSError:
            pass

        if vid and pid:
            hwid = f'USB\\VID_{vid.upper()}&PID_{pid.upper()}'
            if serial:
                hwid += f'\\{serial}'
        else:
            hwid = f'linux\\{entry}'
        devices.append(CameraDevice(
            fingerprint=fingerprint_for(hwid, f'linux\\{entry}', name),
            name=name or entry, hardware_id=hwid,
            instance_id=f'linux\\{entry}', index=index, provider='sysfs'))
    return IdentityReport(devices=devices, provider='sysfs',
                          ms=(time.perf_counter() - t0) * 1000)


def _read_text(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read().strip()
    except OSError:
        return ''


# ---------------------------------------------------------------------------
# 跨平台入口 + 「现在用的是哪台」的判定
# ---------------------------------------------------------------------------

def enumerate_cameras(allow_slow_fallback: bool = True) -> IdentityReport:
    """枚举本机摄像头。Windows 走注册表（ms 级），失败才退到 PowerShell（秒级）。"""
    if sys.platform.startswith('win'):
        rep = enumerate_windows_registry()
        if rep.devices or not allow_slow_fallback:
            return rep
        rep2 = enumerate_windows_pnp()
        if rep2.devices:
            return rep2
        # 两条都不行：把两条的错误都带出去，别只报一条
        rep2.error = (rep2.error or '') + f'（注册表通路：{rep.error or "无设备"}）'
        return rep2
    if sys.platform.startswith('linux'):
        return enumerate_linux()
    return IdentityReport(provider='', error=f'暂不支持在该平台枚举摄像头（{sys.platform}）')


def resolve_active_device(report: IdentityReport,
                          remembered: str = '',
                          chosen: str = '') -> ActiveDevice:
    """判断「程序打开的那台相机」是哪一台。**纯函数，可单独验证**。

    分级（不装懂 —— 不确定就说不确定）：

    * ``chosen``    用户在下拉框里指定过 -> 直接采用（最可信）
    * ``unique``    本机只有一台 -> 索引 0 必然是它
    * ``remembered``多台，但上次记住的那台在列表里 -> 采用，标注「假定」
    * ``ambiguous`` 多台且不知道是哪台 -> **返回 None**，要求用户指定
    * ``none``      没检测到设备
    * ``unsupported``枚举失败/平台不支持

    为什么不猜：索引与设备名字的对应关系在 Windows 上**取不到**
    （DirectShow 顺序不对外暴露，OpenCV 也不给设备名）。猜错就是把 A 相机的
    内参用在 B 相机上 —— 正是本模块要消灭的那类静默错误。
    """
    if report.error and not report.devices:
        return ActiveDevice(None, CONF_UNSUPPORTED, report.error)
    devs = list(report.devices)

    if chosen:
        for d in devs:
            if d.fingerprint == chosen:
                return ActiveDevice(d, CONF_CHOSEN, f'你指定了「{d.label()}」')
        return ActiveDevice(None, CONF_AMBIGUOUS,
                            f'指定过的设备「{chosen}」当前不在列表里')
    if not devs:
        return ActiveDevice(None, CONF_NONE, '未检测到摄像头设备')
    if len(devs) == 1:
        return ActiveDevice(devs[0], CONF_UNIQUE, '本机只有一台摄像头')

    if remembered:
        for d in devs:
            if d.fingerprint == remembered:
                return ActiveDevice(d, CONF_REMEMBERED,
                                    f'多台摄像头，沿用上次记住的「{d.label()}」')
    return ActiveDevice(None, CONF_AMBIGUOUS,
                        f'检测到 {len(devs)} 台摄像头，无法确定程序用的是哪一台')
