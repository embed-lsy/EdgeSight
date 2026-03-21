import cv2
import platform
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

    def run(self):#线程人口，调用start后自动执行，只执行一次用于线程初始化
        try:
            # 尝试初始化摄像头用DirectShow后端，避免Windows摄像头占用问题
            if platform.system()=='Windows':
                self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            elif platform.system()=='Linux':
                self.cap=cv2.VideoCapture(self.camera_index,cv2.CAP_V4L2)
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(self.camera_index)
                if not self.cap.isOpened():
                    self.init_finished.emit(False, "无法打开摄像头（索引：{}）".format(self.camera_index))
                    return
            # 配置摄像头参数
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 320)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
            self.cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'))#强制使用MJPG编码，提升兼容性和帧率
            self.init_finished.emit(True, "摄像头初始化成功（索引：{}）".format(self.camera_index))#发送信号通知主线程
        except Exception as e:
            self.init_finished.emit(False, "摄像头初始化失败：{}".format(str(e)))
