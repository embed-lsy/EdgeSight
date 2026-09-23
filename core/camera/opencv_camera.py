import cv2
import platform
import time
from PySide6.QtCore import QThread, Signal
from typing import Optional

class CameraInitThread(QThread):# 针对一次性的耗时操作，放入子线程
    #自定义信号
    init_finished=Signal(bool,str)#qt中子线程不能直接操作UI，需通过Signal向主线程发送结果

    def __init__(self,camera_index:int,fps:int):
        super().__init__()# 调用QThread的构造函数
        self.camera_index=camera_index
        self.fps=fps
        self.cap:Optional[cv2.VideoCapture]=None#摄像头捕获对象cv2.VideoCapture是OpenCV的摄像头对象，这里先设置为NONE

    def run(self):
        """打开摄像头，必须**真正读出一帧**才算成功，否则换后端重试。

        可靠性要求（2026-09-23 用户明确要求「每次都必须能正常打开」）：
        1. 单一后端失败不能直接放弃 —— 依次尝试 DirectShow / MSMF / 自动；
        2. `isOpened()` 为真不代表有画面（Windows 上常见「开了但读不到帧」），
           必须 warm-up 试读若干帧，拿到有效帧才 emit 成功；
        3. 参数不要无脑设置 —— 见 `_tune_if_needed()`：实测每次 set() 约 1.4s，
           且该驱动会忽略 MJPG 请求，设了纯属白等；
        4. 打开被占用/未就绪时给驱动一点时间，读帧之间 sleep 再重试。
        """
        last_err = ""
        backends = self._backend_list()
        for bi, (name, api) in enumerate(backends):
            # 首选后端多给一次机会；后续后端各试一次，避免摄像头真的不在时
            # 让用户干等十几秒。
            for attempt in range(1, (2 if bi == 0 else 1) + 1):
                cap = None
                try:
                    cap = cv2.VideoCapture(self.camera_index, api)
                    if not cap.isOpened():
                        last_err = f"{name} 打不开设备"
                        cap.release()
                        time.sleep(0.5)
                        continue

                    self._tune_if_needed(cap)

                    ok, frame = self._warm_up(cap)
                    if ok:
                        self.cap = cap
                        h, w = frame.shape[0], frame.shape[1]
                        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
                        cc = "".join(chr((fourcc >> (8 * i)) & 0xFF)
                                     for i in range(4)) if fourcc else "?"
                        msg = (f"摄像头初始化成功（索引：{self.camera_index}，"
                               f"{name}，{w}x{h} {cc}）")
                        if attempt > 1:
                            msg += "（重试后成功）"
                        self.init_finished.emit(True, msg)
                        return

                    last_err = f"{name} 能打开但读不到画面"
                except Exception as e:                  # noqa: BLE001
                    last_err = f"{name} 异常：{e}"
                try:
                    if cap is not None:
                        cap.release()
                except Exception:                       # noqa: BLE001
                    pass
                time.sleep(0.6)                         # 给驱动/占用方释放的时间

        self.init_finished.emit(
            False,
            f"无法打开摄像头（索引：{self.camera_index}，已尝试 "
            f"{'/'.join(n for n, _ in backends)}）—— 最后错误：{last_err}")

    @staticmethod
    def _tune_if_needed(cap, target_w: int = 640, target_h: int = 480):
        """只在「当前分辨率明显过大」时才调分辨率。

        为什么不再无脑设置 FOURCC / 分辨率 / 帧率（2026-09-23 实测数据）：

        | 方式                  | 实际分辨率 | 实测FPS | 设置耗时 |
        |----------------------|-----------|--------|---------|
        | 不设任何参数           | 640x480 YUY2 | 16.5 | 0 ms |
        | 只设 FOURCC=MJPG      | 640x480 YUY2 | 16.7 | 1306 ms |
        | MJPG + 640x320 + fps | 640x360    | 16.7 | 4254 ms |

        即：MJPG 请求被该驱动静默忽略（读回仍是 YUY2）、帧率毫无提升，
        但每次 set() 都触发 DSHOW 重新协商、单项耗时约 1.4 秒 ——
        原来的写法白白拖慢启动 4 秒多，还顺带把画面变成 640x360。
        → 默认直接用驱动的原生分辨率；只有遇到明显超标的（大于 1.5 倍目标）
          才去设置一次，避免大画面拖慢推理。
        """
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if w > target_w * 1.5 or h > target_h * 1.5:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)

    @staticmethod
    def _backend_list():
        """按平台给出候选后端，从最可靠到最兜底。"""
        system = platform.system()
        if system == 'Windows':
            # DSHOW 最稳；MSMF 次之；CAP_ANY 兜底
            return [("DirectShow", cv2.CAP_DSHOW),
                    ("MSMF", cv2.CAP_MSMF),
                    ("自动", cv2.CAP_ANY)]
        if system == 'Linux':
            return [("V4L2", cv2.CAP_V4L2), ("自动", cv2.CAP_ANY)]
        return [("自动", cv2.CAP_ANY)]

    @staticmethod
    def _warm_up(cap, max_reads: int = 20):
        """试读直到拿到有效帧；返回 (是否成功, 帧)。"""
        for _ in range(max_reads):
            ok, frame = cap.read()
            if ok and frame is not None and getattr(frame, "size", 0) > 0:
                return True, frame
            time.sleep(0.05)
        return False, None
