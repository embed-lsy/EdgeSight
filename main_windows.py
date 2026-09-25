from PySide6.QtWidgets import QApplication,QPushButton,QBoxLayout,QWidget,QGroupBox,QLabel,QMessageBox,QFileDialog,QStatusBar,QInputDialog
from PySide6.QtCore import Qt,Slot,QTimer,QThread,Signal,QObject
from PySide6.QtGui import QIcon,QPixmap,QImage
from ui.Ui_EdgeSightMain import Ui_Form
from core.config.windows_global_params import GlobalParams
from core.camera.opencv_camera import CameraInitThread
from core.detector import ModelInitThread, YOLODetector
from core.calibration import (CameraCalibrator, CameraIntrinsics,
                              GeometricRanger, RangingConfig, solve_intrinsics,
                              solve_mount_params, save_mount_params,
                              load_mount_params)
from core.recorder import Recorder, Replayer, FrameRecord
# 摄像头设备识别（CHARTER「范围内的」第 1 条：内参按设备记忆）
from core.camera.device_identity import (IdentityReport, enumerate_cameras,
                                        resolve_active_device)
from core import camera_profiles as cam_profiles
from typing import Optional
from collections import deque
import sys
import cv2
import json
import numpy as np
import pyqtgraph as pg
import os
import time


class CalibSolveThread(QThread):
    """把「求解相机内参」放到子线程执行。

    为什么必须异步（2026-09-23 用户实际故障）：``cv2.calibrateCamera`` 是
    **秒级长任务** —— 本机实测 50 帧 640x480 要 **17.06 s**。旧代码在按钮
    槽函数里同步调用，一点「求解并保存」整个界面就冻住十几秒不动。

    设计要点：
    - 只吃**快照**（点列表的拷贝）：线程在跑时主线程照旧接帧也不影响它；
    - 线程里只调纯函数 `solve_intrinsics`，不碰任何 Qt 控件；
    - 结果用信号回主线程，弹窗 / 写文件 / 改状态都在主线程做（Qt 要求）。
    """

    solved = Signal(object, str)          # (CameraIntrinsics | None, 错误信息)

    def __init__(self, object_points, image_points, image_size, parent=None):
        super().__init__(parent)
        self._objp = list(object_points)
        self._imgp = list(image_points)
        self._size = tuple(image_size) if image_size else (0, 0)

    def run(self):
        try:
            self.solved.emit(
                solve_intrinsics(self._objp, self._imgp, self._size), '')
        except Exception as e:
            self.solved.emit(None, str(e))


class DeviceIdentifyThread(QThread):
    """后台枚举摄像头设备（只有**兜底通路**才需要异步）。

    为什么路径要分开：Windows 上主通路（读注册表）实测 ~1.4 ms，比一次界面
    重绘还便宜，同步跑即可；但它在个别机器上会失败，兜底要调 PowerShell，
    实测 **4.9~6.8 s**。放在启动路径上同步跑，就是开窗即见的几秒卡顿。

    所以：快通路同步、慢通路异步（见 ``MainWindow._scan_camera_devices``）。
    """

    identified = Signal(object)          # IdentityReport

    def run(self):
        try:
            rep = enumerate_cameras(allow_slow_fallback=True)
        except Exception as e:                                   # noqa: BLE001
            # 线程里的异常不会自动冒到主线程，这里必须自己兜住，
            # 否则表现为「界面一直停在识别中」
            rep = IdentityReport(provider='', error=f'设备枚举异常：{e}')
        self.identified.emit(rep)


class MainWindow(QWidget, Ui_Form):
    frame_signal = Signal(np.ndarray)  # 定义类属性

    def __init__(self):
        super(MainWindow, self).__init__()
        self.setupUi(self)
        self.setWindowTitle('EdgeSight — 单目视觉感知栈')
        # 初始化核心组件
        self.camera_index = 0
        self.cap = None
        self.detector = None
        self.labels = []
        self.global_params = GlobalParams()  # 必须在init_camera前初始化
        self.frame_counter = 0
        self.inference_interval = 3  # 每5帧推理一次（0,1,2,3,4,5...）
        self.last_detection=None
        self.is_loading_model=False
        # 标定状态：不采集时 calibrator 为 None，避免误采集普通帧
        self.calibrator = None
        # 是否正在采集标定帧。与 calibrator 分开：暂停采集不丢已采帧
        self._collecting = False
        # 是否正在子线程求解内参。求解期间禁止重复触发（实测 50 帧要十几秒）
        self._solving = False
        self._solve_thread = None
        # ------------------------------------------------------------------
        # 安装参数自标定（外参：相机安装高度 + 俯仰角）
        # ------------------------------------------------------------------
        # 已记录的采样点：[{'dist': 已知距离m, 'v': 底边像素均值, 'std': 散布px,
        #                  'n': 帧数}, ...]
        self._mount_marks = []
        self._marking = False        # 是否在采样窗口内
        self._mark_samples = []      # 采样窗口内收集到的框底边像素
        self._mark_distance = 0.0    # 本次采样对应的已知距离
        self._mark_timer = None
        # 正在把落盘的安装参数回填到控件期间为 True —— 用来区分「加载」与
        # 「用户手工修改」，避免启动时把加载动作当成用户改动又写回一次
        self._loading_mount = False
        # 几何测距器。先无内参构造，load_calibration() 后注入
        self.ranger = GeometricRanger(CameraIntrinsics(),
                                      RangingConfig.from_params(self.global_params))
        # 录制回放（CHARTER 第 6 条）
        self.recorder = None          # 非录制时为 None，避免误调
        self.replayer = None          # 回放器
        self.replay_timer = None      # 回放驱动定时器
        self.play_index = 0           # 回放进度（帧）
        self._replay_seeking = False  # 拖动进度条时抑制回写
        self._rec_seq = 0             # 录制帧序号
        self._rec_t0 = 0.0            # 录制起始时刻，用于数据轨时间戳

        # 初始化存储图表的环形缓冲区
        self.history_len = 100
        self.sensor_history_x = deque(maxlen=self.history_len)
        self.sensor_history_y = deque(maxlen=self.history_len)
        self.sensor_history_wide = deque(maxlen=self.history_len)
        self.sensor_history_hight = deque(maxlen=self.history_len)
        self.sensor_history_conf = deque(maxlen=self.history_len)
        self.sensor_history_conf_thres = deque(maxlen=self.history_len)
        self.sensor_history_fps = deque(maxlen=self.history_len)
        self.target_distance = deque(maxlen=self.history_len)
        self.time_history = deque(maxlen=self.history_len)
        self.time_counter = 0.0
        # 初始化状态栏
        self.status_bar=QStatusBar(self)
        self.layout().addWidget(self.status_bar)
        # ------------------------------------------------------------------
        # 摄像头设备识别（CHARTER「范围内的」第 1 条：内参按设备记忆）
        # ------------------------------------------------------------------
        # 为什么要「记设备」：内参跟着**相机本体**走。旧实现只有一个
        # models/calib.json，隐含假设「这台机器只有一台相机」—— 换一台
        # **同分辨率**的相机会静默沿用旧内参：距离系统性错、界面零提示
        # （相机的 _tune_if_needed 还会把画面调回 640x480，把尺寸凑巧对上，
        # 进一步掩盖问题）。现在按设备指纹分档存：换设备能认出来，
        # 没标定会提醒标定，分辨率不符会拒用而不是硬算。
        self._cam_store_path = None       # models/cameras.json
        self._cam_store = {}              # 档案库（按设备指纹分档）
        self._identity_report = None      # 上一次枚举结果（含通路与耗时）
        self._cam_active = None           # ActiveDevice：正在用的那台是谁、有多确定
        self._cam_decision = None         # CalibrationDecision：本次用哪份内参
        self._legacy_intrinsics = None    # 旧的单文件标定（兼容与过渡）
        self._identify_thread = None      # 兜底枚举线程（慢通路必须异步）
        self._loading_device = False      # 程序回填下拉框期间，挡住「用户选择」误判
        self._calib_prompted = False      # 「未标定」提醒每轮启动只弹一次
        #初始化UI
        self.init_ui()
        # 先为每个plot控件添加图例，确保曲线名字能显示
        self.plot_sensor_center.addLegend()
        self.plot_sensor_shap.addLegend()
        self.plot_sensor_conf.addLegend()
        self.plot_target_distance.addLegend()
        self.plot_sensor_fps.addLegend()
        # 初始化分析曲线控件（确保UI已setupUi）
        self._plot_sensor_curve_x = self.plot_sensor_center.plot([], [], pen=pg.mkPen('r', width=2), name="检测框X坐标")
        self._plot_sensor_curve_y = self.plot_sensor_center.plot([], [], pen=pg.mkPen('g', width=2), name="检测框Y坐标")
        self._plot_sensor_curve_wide = self.plot_sensor_shap.plot([], [], pen=pg.mkPen('c', width=2), name="检测框宽度")
        self._plot_sensor_curve_hight = self.plot_sensor_shap.plot([], [], pen=pg.mkPen('m', width=2), name="检测框高度")
        self._plot_target_distance = self.plot_target_distance.plot([], [], pen=pg.mkPen('g', width=2), name="目标距离")
        self._plot_sensor_curve_conf = self.plot_sensor_conf.plot([], [], pen=pg.mkPen('b', width=2), name="检测框置信度")
        self._plot_sensor_curve_conf_thres = self.plot_sensor_conf.plot([], [], pen=pg.mkPen('r', width=2, style=Qt.DashLine), name="置信度阈值")
        self._plot_sensor_curve_fps = self.plot_sensor_fps.plot([], [], pen=pg.mkPen('y', width=2), name="检测框FPS")
        #信号绑定
        self.bind_model_thres_widgets_realtime()#实时生效
        self.bind_calibration_widgets()#仅标定时生效
        self.bind_buttons()
        self.bind_other()
        #启动定时器
        self.setup_core_timers()
        #创建Detector线程，用于处理持续耗时的操作
        self.detector_thread=QThread()
        self.detector_thread.setObjectName('DetectorThread')
        #初始化摄像头和AI模型
        self.async_init_camera()
        self._apply_default_model_paths()
        self.async_init_ai_model()
        #延迟初始化图表
        self._analysis_plot_inited=False
       
    def setup_core_timers(self):
        #定时器更新监控界面数据
        self.update_timer=QTimer()
        self.update_timer.setInterval(int(1000 / self.global_params.sample_freq))  # 按采样频率更新
        self.update_timer.timeout.connect(self.update_monitor_data)
        self.update_timer.start()
        #摄像头画面刷新定时器
        self.camera_timer=QTimer()
        self.camera_timer.setInterval(int(1000 / self.global_params.fps))
        self.camera_timer.timeout.connect(self.update_camera_frame)
        self.camera_timer.start()
        # 深度分析曲线动态刷新定时器
        self.analysis_timer = QTimer()
        self.analysis_timer.setInterval(50) 
        self.analysis_timer.timeout.connect(self.update_analysis_plots)
        # 资源监控定时器
        self.resource_timer=QTimer()
        self.resource_timer.setInterval(1000)
        self.resource_timer.timeout.connect(self.update_resource_usage)
        self.resource_timer.start()

    
    def init_ui(self):
        #系统参数
        self.slider_sample_freq.setValue(self.global_params.sample_freq)
        self.label_sample_freq.setText(f'{self.global_params.sample_freq}Hz')
        self.slider_base_width.setValue(self.global_params.base_width)
        self.label_base_width.setText(f'{self.global_params.base_width}px')
        #运动时数据
        self.lcd_centroid_x.display(self.global_params.detection_x)
        self.lcd_centroid_y.display(self.global_params.detection_y)
        self.lcd_fps.display(self.global_params.fps)
        self.lcd_reasoning.display(self.global_params.inference_fps)
        #检测配置
        self.slider_confidence_thres.setValue(int(self.global_params.confidence_thres*100))
        self.label_confidence_thres.setText(f'{self.global_params.confidence_thres:.1f}')
        self.slider_nms_thres.setValue(int(self.global_params.nms_thres*100))
        self.label_nms_thres.setText(f'{self.global_params.nms_thres:.1f}')
        self.combo_target_select_rule.setCurrentIndex(self.global_params.target_select_rule)
        self.combo_hardware_accel.setCurrentText(self.global_params.hardware_accel)
        #推理结果
        self.lcd_credibility.display(self.global_params.credibility)
        self.label_target_category.setText(self.global_params.target_category)
        self.update_specific_class_combo()
        #相机标定：先认「本机是哪台相机」，再按设备取内参（见 load_calibration）
        self.load_calibration()
        #安装参数（相机高度 + 俯仰角）：与内参同理，落盘后启动即回填
        self.load_mount_params_ui()
        self.refresh_calib_widgets()
        self.refresh_camera_widgets()
    
    #摄像头线程启动
    def async_init_camera(self):
        self.status_bar.showMessage("正在初始化摄像头...")
        self.camera_thread = CameraInitThread(self.camera_index, self.global_params.fps)#摄像头初始化实例
        self.camera_thread.init_finished.connect(self.on_camera_init_finished)#绑定结束信号到回调函数，子线程和主线程通信的关键
        self.camera_thread.start()#启动后再run运行

    def on_camera_init_finished(self,success,message):#摄像头加载完成回调
        if success:
            self.cap = self.camera_thread.cap
            self.status_bar.showMessage(message, 3000)
            # 拿到真实画面尺寸后复核内参判定：启动时相机可能还没开，
            # 那时跳过分辨率校验，这里必须补上（标定分辨率≠当前分辨率是要拦的错）
            self.verify_calibration_against_frame()
        else:
            self.lbl_original.setText("摄像头未连接")
            self.lbl_process.setText('摄像头未连接')
            self.status_bar.showMessage(message, 5000)

    def async_init_ai_model(self,reload=False):
        self.is_loading_model=True

        if reload:
            # 先停止定时器
            if hasattr(self,'camera_timer') and self.camera_timer.isActive():
                self.camera_timer.blockSignals(True)# 暂时阻断摄像头定时器信号
            try:
                self.frame_signal.disconnect()# 阻断旧信号槽
            except:
                pass
            old = self.detector
            try:
                if old:
                    old.detection_ready.disconnect(self.on_detection_ready)
            except:
                pass
            # 常驻 detector_thread 不退出（退出+重建会在主线程上等待，卡界面），
            # 旧 detector 交给它所属线程的事件循环去删
            self.detector=None #去除旧对象
            if old is not None:
                old.deleteLater()

        self.status_bar.showMessage(
            "正在后台加载 AI 模型……（界面可继续操作，加载完自动生效）")
        self.model_thread = ModelInitThread(
            self.global_params.mode_path,
            self.global_params.hardware_accel,
            self.global_params.label_path,      # 标签文件也在子线程里读
        )
        self.model_thread.init_finished.connect(self.on_model_init_finished)
        self.model_thread.start()

    def on_model_init_finished(self,success,message,model=None):#模型加载完成回调
        print("检测线程启动状态：", self.detector_thread.isRunning())
        if success and self.global_params.mode_path:
            model_path_lower=self.global_params.mode_path.lower()
            if 'v5' in model_path_lower or 'yolov5' in model_path_lower:
                model_type='v5'
            elif 'v8' in model_path_lower or 'yolov8' in model_path_lower:
                model_type='v8'
            else:
                model_type='v5'
            self.detector=YOLODetector(
                self.global_params.mode_path,
                self.global_params.label_path,
                self.global_params,
                self.global_params.confidence_thres,
                self.global_params.nms_thres,
                self.global_params.hardware_accel,
                model_type=model_type
            )
            if self.detector.load_model(preloaded_model=model):
                self.detector.moveToThread(self.detector_thread)#将Detector对象移到子线程运行
                #创建信号槽连接，主线程向监测器线程发送视频帧
                self.frame_signal.connect(self.detector.predict)
                #检测器结果在发送到主线程进行处理
                self.detector.detection_ready.connect(self.on_detection_ready)
                if not self.detector_thread.isRunning():
                    self.detector_thread.start()
                # 标签与类别下拉跟着这次加载的模型走（不依赖用户手动选过标签）
                self.labels = list(self.detector.labels or [])
                self.update_specific_class_combo()
                self._save_model_settings()   # 记住这次生效的组合
                self.status_bar.showMessage('AI模型加载并初始化成功',3000)
            else:
                self.status_bar.showMessage('Detector加载模型失败', 5000)
        else:
            self.detector=None # 没有模型路径也要设为None避免报错

        self.status_bar.showMessage(message, 3000)
        #  恢复标志位于定时器信号
        self.is_loading_model = False
        if hasattr(self, 'camera_timer'):
            self.camera_timer.blockSignals(False)  # 恢复摄像头定时器的信号

    def init_analysis_plots(self):
        if self._analysis_plot_inited and self.global_params.plot_enable:
            return
        self._analysis_plot_inited=True
        # 绘图控件名以 ui/EdgeSightMain.ui 为准（plot_sensor/plot_error/plot_control
        # 是旧版命名，命名修正后已不存在，引用会直接 AttributeError）
        for plt in [self.plot_sensor_center, self.plot_sensor_shap,
                    self.plot_target_distance, self.plot_sensor_conf,
                    self.plot_sensor_fps]:
            plt.showGrid(x=True, y=True)
            plt.setLabel('bottom', '时间')
            plt.setLabel('left', '数值')
            plt.addLegend()
            plt.setMouseEnabled(x=True, y=True)
        # 曲线对象已在__init__初始化，这里只需清空数据
        self._plot_sensor_curve_x.setData([], [])
        self._plot_sensor_curve_y.setData([], [])
        self._plot_sensor_curve_wide.setData([], [])
        self._plot_sensor_curve_hight.setData([], [])
        self._plot_sensor_curve_conf.setData([], [])
        self._plot_sensor_curve_fps.setData([], [])
        self._plot_target_distance.setData([], [])
        self._plot_sensor_curve_conf_thres.setData([], [])
       
    def update_analysis_plots(self):
        if not self._analysis_plot_inited and self.global_params.plot_enable:
            return
        # 更新曲线
        self._plot_sensor_curve_x.setData(list(self.time_history), list(self.sensor_history_x))
        self._plot_sensor_curve_y.setData(list(self.time_history), list(self.sensor_history_y))
        self._plot_sensor_curve_wide.setData(list(self.time_history), list(self.sensor_history_wide))
        self._plot_sensor_curve_hight.setData(list(self.time_history), list(self.sensor_history_hight))
        self._plot_sensor_curve_conf.setData(list(self.time_history), list(self.sensor_history_conf))
        self._plot_sensor_curve_fps.setData(list(self.time_history), list(self.sensor_history_fps))
        self._plot_target_distance.setData(list(self.time_history), list(self.target_distance))
        self._plot_sensor_curve_conf_thres.setData(list(self.time_history), list(self.sensor_history_conf_thres))
        # 更新提示（历史为空时直接返回，否则 last_x 未定义抛 UnboundLocalError，
        # 分析定时器每 50ms 触发一次，会刷屏报错）
        if len(self.sensor_history_x) == 0:
            self.label_prompt.setText('暂无目标数据')
            # 空状态下置信度状态不能沿用上一轮的"正常"，否则自相矛盾
            self.label_conf.setText('—')
            return
        last_x = self.sensor_history_x[-1]
        last_y = self.sensor_history_y[-1]
        warnings = []
        if last_x < 50:
            warnings.append("左侧丢失风险")
        elif last_x > 590:
            warnings.append("右侧丢失风险")
        if last_y < 40:
            warnings.append("顶部丢失风险")
        elif last_y > 440:
            warnings.append("底部丢失风险")
        self.label_prompt.setText(" | ".join(warnings) if warnings else "位置正常")
        
        if len(self.sensor_history_conf) > 0 and self.sensor_history_conf[-1] < self.global_params.confidence_thres:
            self.label_conf.setText("置信度低于阈值！")
        else:
            self.label_conf.setText("置信度正常")
    
    
    def update_resource_usage(self):
        if not self._analysis_plot_inited and self.global_params.plot_enable:
            return
        import psutil
        cpu_percent = psutil.cpu_percent()
        mem_percent = psutil.virtual_memory().percent
        self.progressBar_cpu.setValue(int(cpu_percent))
        self.progressBar_memory.setValue(int(mem_percent))

    def bind_buttons(self):
        self.QPuahButton_calibrate_status.clicked.connect(self.on_calibrate_clicked)
        self.btn_model_browse.clicked.connect(self.on_model_browse)
        self.btn_label_browse.clicked.connect(self.on_label_browse)
        self.btn_calib_capture.clicked.connect(self.on_calib_capture_clicked)
        self.btn_calib_solve.clicked.connect(self.on_calib_solve_clicked)
        # 录制回放（CHARTER 第 6 条）
        self.btn_rec_toggle.clicked.connect(self.on_rec_toggle)
        self.btn_play_pick.clicked.connect(self.on_play_pick)
        self.btn_play_toggle.clicked.connect(self.on_play_toggle)
        self.btn_play_stop.clicked.connect(self.on_play_stop)
        self.slider_play_pos.sliderMoved.connect(self.on_play_seek)
        self.tabWidget.currentChanged.connect(self.on_tab_change)

    def bind_model_thres_widgets_realtime(self):#更新标签与值
        self.slider_confidence_thres.valueChanged.connect(lambda v: self.update_param_realtime("confidence_thres", v/100, self.label_confidence_thres, "%.1f"))
        self.slider_nms_thres.valueChanged.connect(lambda v: self.update_param_realtime("nms_thres", v/100, self.label_nms_thres, "%.1f"))

    def bind_calibration_widgets(self):#仅标定时生效
        self.slider_sample_freq.valueChanged.connect(lambda v:self.label_sample_freq.setText(f'{v}Hz'))
        self.slider_base_width.valueChanged.connect(lambda v:self.label_base_width.setText(f'{v}px'))
        self.spin_pitch_deg.valueChanged.connect(self.on_pitch_changed)
        self.spin_camera_height.valueChanged.connect(self.on_camera_height_changed)
        # 安装参数自标定（监视页）：由「已知距离 + 框底边像素」反解 (H, 俯仰角)
        self.btn_mark_known.clicked.connect(self.on_mark_known_clicked)
        self.btn_solve_mount.clicked.connect(self.on_solve_mount_clicked)
        # 摄像头设备（设置页）：像蓝牙那样按设备记标定
        self.combo_camera_device.currentIndexChanged.connect(
            self.on_camera_device_chosen)
        self.btn_camera_bind.clicked.connect(self.on_bind_camera_clicked)
        self.btn_camera_scan.clicked.connect(self.on_rescan_camera_clicked)

    def bind_other(self):
        self.tabWidget.currentChanged.connect(self.on_tab_change)

    # ------------------------------------------------------------------
    # 相机标定（CHARTER「范围内的」第 1 条）
    # ------------------------------------------------------------------
    def load_calibration(self):
        """按「本机是哪台相机」加载对应内参。

        与旧实现的区别
        -------------
        旧实现直接读 ``models/calib.json`` 就用 —— 隐含假设「这台机器上只有一台
        相机」。于是「换相机」这件事**在数据上不可见**：文件还是那个文件、程序
        照读不误，换一台**同分辨率**的相机就静默沿用旧内参，距离系统性错而界面
        零提示（相机自带的 ``_tune_if_needed()`` 还会把画面调回 640x480，让尺寸
        凑巧对上，把问题盖得更严实）。

        现在分三步：① 认设备 → ② 按设备指纹查档案库 → ③ 判定用不用。
        判定规则在 ``core.camera_profiles.decide_calibration``（纯函数，可单测）。

        没有标定不是错误 —— 只是测距不可用：这里只记录原因，不阻塞启动，
        UI 会明确显示「本设备未标定」，而不是静默给一个假距离。
        """
        path = self.global_params.calib_path
        if not os.path.isabs(path):
            # 相对仓库根解析，避免工作目录变化导致找不到
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
        self._calib_file = path
        # 安装参数（外参）与内参**同目录、分开存**：两者生命周期不同（内参跟相机走、
        # 安装参数跟机位走），合并会让「重标内参」把安装参数一起冲掉
        self._mount_file = os.path.join(os.path.dirname(path), 'mount.json')
        # 内参档案库：一台相机一条记录（与 calib.json 同目录，便于一起备份）
        self._cam_store_path = cam_profiles.default_store_path(path)
        self._cam_store = cam_profiles.load_store(self._cam_store_path)
        print(f'[设备] 标定档案库 {self._cam_store_path}：'
              f"{len(self._cam_store.get('devices', {}))} 台设备的记录")
        # 旧的单文件标定：仍要读（老用户机器上只有它），但**不再直接生效**
        self._legacy_intrinsics = CameraCalibrator.load(path)
        # 认设备，并据此决定用哪份内参
        self._scan_camera_devices()

    # ------------------------------------------------------------------
    # 摄像头设备识别：像蓝牙那样「记住每台设备」
    # ------------------------------------------------------------------

    def _scan_camera_devices(self):
        """枚举本机摄像头，并据此决定用哪份内参。

        快通路同步、慢通路异步
        -------------------
        Windows 主通路读注册表，实测 **1.4 ms**（``probe_identity_routes.py``），
        同步跑毫无存在感；兜底通路要调 PowerShell，实测 **4.9~6.8 s**，
        同步跑就是"开窗即卡几秒"。所以后者必须丢进 ``DeviceIdentifyThread``。
        """
        rep = enumerate_cameras(allow_slow_fallback=False)
        if rep.devices or not rep.error:
            # 有设备；或者「通路正常但本机确实没有摄像头」—— 都不需要慢查询
            self._apply_identity(rep)
            return
        # 注册表没结果：可能只是这条通路不可用（而不是真的没插相机）
        print(f'[设备] 注册表通路无结果（{rep.error or "无设备"}），转后台兜底查询')
        if self._identify_thread is not None and self._identify_thread.isRunning():
            return
        if hasattr(self, 'label_camera_status'):
            self.label_camera_status.setText(
                '正在识别摄像头……\n'
                '本机的注册表通路没读到设备，正在用备用通路查询（约需几秒）。')
        self._identify_thread = DeviceIdentifyThread(self)
        self._identify_thread.identified.connect(self._apply_identity)
        self._identify_thread.start()

    @Slot(object)
    def _apply_identity(self, rep):
        """拿到设备列表后：判定「现在用的是哪台」，再更新界面与内参。"""
        self._identity_report = rep
        chosen = self._chosen_fingerprint()
        act = resolve_active_device(rep,
                                    remembered=self._cam_store.get('active', ''),
                                    chosen=chosen)
        self._cam_active = act
        print(f'[设备] {rep.summary()} | 判定 {act.confidence}：{act.reason}')
        self.refresh_camera_widgets()
        self.apply_calibration_decision()

    def apply_calibration_decision(self, frame_size=None):
        """决定这次用哪份内参，并把结论落到测距器与界面。

        ``frame_size`` 未知（相机还没打开）时**跳过分辨率比对**，等
        ``on_camera_init_finished`` 拿到真实画面尺寸再复核一次
        （见 ``verify_calibration_against_frame``）。
        """
        act = getattr(self, '_cam_active', None)
        dev = act.device if act else None
        fp = dev.fingerprint if dev else ''
        # 旧标定文件上盖的设备戳：用来拦住「给相机 A 标完、插上同分辨率的相机 B
        # 仍照读旧文件」这个漏洞。**每次现读**而不是缓存 —— 盖戳发生在标定完成与
        # 手动绑定之后，缓存一旦忘了同步就会让这道闸门失效。
        stamped = cam_profiles.read_stamped_device(getattr(self, '_calib_file', ''))
        d = cam_profiles.decide_calibration(
            self._cam_store, fp, legacy=self._legacy_intrinsics,
            frame_size=frame_size, identity_known=bool(fp),
            legacy_device=stamped)
        self._cam_decision = d

        self.global_params.intrinsics = d.intrinsics
        self.global_params.calibrated = bool(d.usable)
        self.global_params.invalid_reason = ('' if d.usable
                                             else (d.blocked_reason or d.status))
        # ⚠️ 测距器**绝不能注入 None**：on_detection_ready 会无条件调它。
        # 不可用时注入「无效内参」（calibrated=False），各方法会自然返回
        # None / 明确原因，而不是崩在 None.is_valid() 上。
        self.ranger.update_intrinsics(d.intrinsics if d.usable
                                      else CameraIntrinsics())
        self.refresh_distance_widgets()
        self.refresh_calib_widgets()
        # ⚠️ 必须连设备状态标签一起刷：判定可能在「相机打开后复核」时被改写
        # （例如分辨率此时才发现不符）。少了这一步，界面会停留在上一轮的文案上
        # —— 显示「已标定」而实际已拒用，是典型的"看着正常、其实不一致"。
        self.refresh_camera_widgets()

        if d.usable:
            self.status_bar.showMessage(
                f'内参已就绪（{d.status}）：fx={d.intrinsics.fx:.1f} '
                f'rms={d.intrinsics.rms_error:.3f}px', 6000)
        else:
            self.status_bar.showMessage(f'测距不可用：{d.status}', 10000)
        self._maybe_prompt_calibration()
        return d

    def verify_calibration_against_frame(self):
        """相机打开后，用**真实画面尺寸**复核一次内参判定。

        为什么必须复核：启动时相机可能还没打开，拿不到画面尺寸，只能跳过分辨率
        校验；而「标定分辨率 ≠ 当前分辨率」恰恰是要拦的那类静默错误 —— 内参随
        分辨率变化，套用会让距离整体偏。所以拿到尺寸后必须再判一次。
        """
        size = self._frame_size()
        if size is None:
            return
        d = self.apply_calibration_decision(frame_size=size)
        print(f'[设备] 画面 {size[0]}x{size[1]}，内参判定：{d.status}')
        if not d.usable and d.blocked_reason:
            self.status_bar.showMessage(f'测距不可用：{d.blocked_reason}', 15000)

    def _frame_size(self):
        """当前摄像头的实际画面尺寸；拿不到返回 None（不猜）。"""
        cap = getattr(self, 'cap', None)
        if cap is None:
            return None
        try:
            if not cap.isOpened():
                return None
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        except Exception:                                        # noqa: BLE001
            return None
        return (w, h) if w > 0 and h > 0 else None

    def _chosen_fingerprint(self) -> str:
        """用户在下拉框里指明过的设备指纹；没指明过返回空串。"""
        combo = getattr(self, 'combo_camera_device', None)
        if combo is None:
            return ''
        return str(combo.currentData() or '')

    def refresh_camera_widgets(self):
        """把「本机摄像头」与「本设备的标定状态」刷到设置页。

        ⚠️ 下拉框的语义必须说准：程序固定打开**索引 0**，所以选中项表达的是
        「我确认索引 0 就是这台」，而不是「选一下就能换相机」—— Windows 上取不到
        索引与设备名的对应关系（见 ``core/camera/device_identity.py`` 的说明）。
        让人误以为能切设备，比不提供这个控件更糟，所以文案里写清楚。
        """
        combo = getattr(self, 'combo_camera_device', None)
        label = getattr(self, 'label_camera_status', None)
        if combo is None or label is None:
            return
        rep = self._identity_report
        act = getattr(self, '_cam_active', None)

        self._loading_device = True
        try:
            combo.clear()
            if rep is None:
                combo.addItem('正在识别……', '')
            elif not rep.devices:
                combo.addItem('未检测到摄像头设备', '')
            else:
                for dv in rep.devices:
                    combo.addItem(dv.label(), dv.fingerprint)
                want = act.device.fingerprint if (act and act.device) else ''
                i = combo.findData(want)
                if i >= 0:
                    combo.setCurrentIndex(i)
        finally:
            self._loading_device = False

        lines = []
        if rep is None:
            lines.append('正在识别摄像头……')
        else:
            lines.append(rep.summary())
            if act is not None and act.device is not None:
                mark = '✓' if act.certain else '⚠'
                lines.append(f'{mark} 程序正在使用的设备：{act.device.name}'
                             f'（{act.reason}）')
                if not act.certain:
                    lines.append('　请在上面的下拉框里指明程序用的是哪一台，'
                                 '之后会记住。')
            elif act is not None:
                lines.append(f'⚠ {act.reason}')

        d = getattr(self, '_cam_decision', None)
        if d is not None:
            lines.append('')
            lines.append(f'标定：{d.status}')
            lines.append(d.detail)
        label.setText('\n'.join(lines))

        bind = getattr(self, 'btn_camera_bind', None)
        if bind is not None:
            bind.setEnabled(bool(d is not None and d.can_bind_legacy))

    @Slot(int)
    def on_camera_device_chosen(self, index):
        """用户在下拉框里指明了「程序正在用的那一台」。"""
        if getattr(self, '_loading_device', False):
            return                        # 程序回填，不是用户操作
        fp = str(self.combo_camera_device.itemData(index) or '')
        if not fp:
            return
        if self._cam_store.get('active', '') != fp:
            cam_profiles.set_active(self._cam_store, fp)
            self._persist_camera_store()
        rep = self._identity_report or IdentityReport()
        self._cam_active = resolve_active_device(
            rep, remembered=self._cam_store.get('active', ''), chosen=fp)
        print(f'[设备] 用户指定：{self._cam_active.reason}')
        self.refresh_camera_widgets()
        self.apply_calibration_decision(self._frame_size())

    @Slot()
    def on_rescan_camera_clicked(self):
        """重新枚举一次（插拔设备后用）。快通路是毫秒级的，点它不用等。"""
        self.status_bar.showMessage('正在重新检测摄像头设备……', 3000)
        self._scan_camera_devices()

    @Slot()
    def on_bind_camera_clicked(self):
        """把当前已加载的旧标定认到本设备名下。

        场景：老用户机器上只有一个 ``calib.json``（未绑定任何设备）。重标一次
        当然最干净，但"我确定就是这台相机、不想重标"是合理诉求 —— 那就让这句话
        变成一个**明确的动作**，而不是靠程序默认猜。所以这里要用户主动确认，
        并且**分辨率对不上就拒绝绑定**（绑了也是在给自己埋雷）。
        """
        act = getattr(self, '_cam_active', None)
        dev = act.device if act else None
        if dev is None or not dev.fingerprint:
            self._warn('绑定标定', '还认不出本机摄像头是哪一台，无法绑定。\n'
                                   '请先点「重新检测设备」。')
            return
        intr = self._legacy_intrinsics
        if intr is None or not intr.is_valid():
            self._warn('绑定标定', '当前没有可用的标定文件，请先标定一次。')
            return
        size = self._frame_size()
        if size is not None and tuple(intr.image_size) != tuple(size):
            self._warn('绑定标定',
                       f'这份标定是按 {intr.image_size[0]}x{intr.image_size[1]} 做的，'
                       f'当前画面是 {size[0]}x{size[1]}，分辨率不一致，不能绑定。\n'
                       f'请对当前相机重新标定一次。')
            return
        try:
            cam_profiles.upsert_profile(
                self._cam_store, dev.fingerprint,
                cam_profiles.profile_from_intrinsics(dev, intr,
                                                     note='由旧标定文件绑定'))
            self._persist_camera_store()
            # 同 on_calib_solved：绑定也要给旧文件盖戳。否则用户"绑定"完这台，
            # 之后插上另一台同分辨率相机时，旧文件仍是"无主的"，判定又会走
            # 「暂用未绑定文件」——等于白绑一次。
            cam_profiles.stamp_device(self._calib_file, dev.fingerprint)
        except OSError as e:
            self._warn('绑定标定', f'写入档案库失败：{e}')
            return
        self.refresh_camera_widgets()
        self.apply_calibration_decision(size)
        self._info('绑定标定',
                   f'已把当前标定绑定到「{dev.name}」。\n\n'
                   f'以后插别的相机不会再用到这份内参；插回这台则自动可用。')

    def _persist_camera_store(self):
        """档案库落盘。失败只降级（本次仍生效），不阻断使用。"""
        path = getattr(self, '_cam_store_path', None)
        if not path:
            return
        try:
            cam_profiles.save_store(path, self._cam_store)
        except OSError as e:
            self.status_bar.showMessage(
                f'标定档案保存失败：{e}（本次仍已生效）', 8000)

    def _maybe_prompt_calibration(self):
        """没有可用标定时提醒标定 —— 每轮启动只弹一次。"""
        d = getattr(self, '_cam_decision', None)
        if d is None or d.usable or self._calib_prompted:
            return
        self._calib_prompted = True
        act = getattr(self, '_cam_active', None)
        name = act.device.name if (act and act.device) else '本机摄像头'
        # 延迟到事件循环：构造期间弹模态框会挡在窗口显示之前，观感很差
        QTimer.singleShot(0, lambda: self._notify_calibration_needed(name, d))

    def _notify_calibration_needed(self, name, decision):
        self._warn(
            '需要标定相机',
            f'这台相机（{name}）还没有可用的内参，测距不可用'
            f'（程序不会给出猜测值）。\n\n'
            f'原因：{decision.status}\n\n'
            f'要做什么：切到「设置」页 →「相机标定」→ 把棋盘格放进画面 →\n'
            f'点「开始采集」（采够 10 帧）→ 点「求解并保存」。\n\n'
            f'标定一次即可：结果会按这台设备记住，以后插回来直接可用。')

    def _warn(self, title, text):
        """统一的警告弹窗出口 —— 便于自动化验证时替换掉阻塞式对话框。"""
        QMessageBox.warning(self, title, text)

    def _info(self, title, text):
        QMessageBox.information(self, title, text)


    def load_mount_params_ui(self):
        """把落盘的安装参数（相机高度 + 俯仰角）回填到设置页，并立即生效。

        为什么要有这一步
        ---------------
        安装参数原先只活在内存里（``GlobalParams``）：自标定解出来只写进控件，
        程序一关就没了 —— 下次启动得重解一遍。开发者本机不容易察觉（每次都现场
        标），但换台机器、换个人用，就变成「棋盘标完还得再搞一次」，而它本来
        只需要做一次。内参有 ``models/calib.json``，安装参数同样该有。

        回填走**与手工填写同一条通路**（``setValue`` -> ``valueChanged`` ->
        重建 ``RangingConfig``），所以没有额外的「应用」按钮；``_loading_mount``
        在此期间挡住落盘，避免把「加载」当成「用户改动」再写一次。

        ⚠️ 但那条通路**在本函数被调用时还没接通**：``init_ui()`` 跑在
        ``bind_calibration_widgets()`` **之前**，此刻 ``valueChanged`` 还没有
        连到槽函数 —— 只 ``setValue`` 会得到一个**控件显示对了、而
        ``global_params`` 还是 0** 的静默失效（实测踩到：界面显示 1.20 m，
        测距侧仍认为「未填安装高度」，接触点法直接不可用）。
        所以下面除了 ``setValue``，还**显式同步一次** global_params 与 ranger。
        """
        path = getattr(self, '_mount_file', None)
        if not path:
            return
        data = load_mount_params(path)
        if not data:
            return
        self._loading_mount = True
        try:
            self.spin_camera_height.setValue(float(data['camera_height']))
            self.spin_pitch_deg.setValue(float(data['pitch_deg']))
        finally:
            self._loading_mount = False
        h = float(self.spin_camera_height.value())
        p = float(self.spin_pitch_deg.value())

        # 显式生效（不能依赖 valueChanged —— 见上面的 ⚠️）。三步与
        # on_pitch_changed / on_camera_height_changed 保持完全一致，
        # 保证「加载出来的」与「手工填的」走到同一个内部状态。
        self.global_params.camera_height = h
        self.global_params.pitch_deg = p
        self.ranger.update_config(RangingConfig.from_params(self.global_params))
        self.refresh_distance_widgets()

        src = data.get('source') or '已保存'
        when = data.get('saved_at') or '—'
        self.status_bar.showMessage(
            f'已加载安装参数：相机高度 {h:.2f} m、俯仰角 {p:.1f}°'
            f'（{src} @ {when}）', 6000)
        print(f'[安装参数] 加载 {path}  H={h:.2f} m  θ={p:.1f}°  '
              f'source={src} saved_at={when}')

    def _persist_mount_params(self, source: str):
        """把当前控件的安装参数落盘。

        取**控件值**而不是 ``global_params``：控件精度（高度 2 位、俯仰角 1 位）
        才是实际生效的值，存下来才能与「下次启动看到的数」一致 —— 否则会出现
        「存的是 1.2365、显示的是 1.24」这类对不上的情况。

        落盘失败**不阻断测距**：参数已在内存中生效，只是下次要重填，属于降级而非故障。
        """
        if getattr(self, '_loading_mount', False):
            return
        path = getattr(self, '_mount_file', None)
        if not path:
            return
        try:
            save_mount_params(path, self.spin_camera_height.value(),
                              self.spin_pitch_deg.value(), source=source)
        except OSError as e:
            self.status_bar.showMessage(f'安装参数保存失败：{e}（本次仍已生效）', 8000)

    def refresh_calib_widgets(self):
        """把标定状态同步到设置页。

        注意顺序：**采集进度优先**。本函数在切到「设置」页签时也会被调用，
        若把进度提示写在前面，用户切换一次页签就会看到"未标定…"而以为帧丢了。
        """
        if self.global_params.calibrated:
            intr = self.global_params.intrinsics
            self.label__calibrate_status.setText('已标定')
            info = (
                f'fx={intr.fx:.1f}  fy={intr.fy:.1f}  '
                f'cx={intr.cx:.1f}  cy={intr.cy:.1f}\n'
                f'重投影误差 {intr.rms_error:.3f} px '
                f'（<0.5 优 / <1.0 可接受）'
            )
        else:
            self.label__calibrate_status.setText('未标定')
            reason = self.global_params.invalid_reason or '未标定'
            info = (
                f'{reason}。测距不可用（不会给出猜测值）。\n'
                f'请让棋盘格在画面中变换位置与倾斜角，至少采集 10 帧后求解。'
            )

        n = self._calib_frame_count()
        self.btn_calib_solve.setEnabled(n > 0)
        if n > 0:
            state = '采集中' if getattr(self, '_collecting', False) else '已暂停采集'
            info = (f'{state}：已采集 {n} 帧（没有丢弃）。\n'
                    f'点「求解并保存」解算内参；想补采就再点「开始采集」。')
        self.label_calib_info.setText(info)

    def _make_calibrator(self):
        cols = self.spin_pattern_cols.value()
        rows = self.spin_pattern_rows.value()
        square_m = self.spin_square_mm.value() / 1000.0
        return CameraCalibrator(pattern_size=(cols, rows), square_size=square_m)

    def _calib_frame_count(self) -> int:
        return self.calibrator.frame_count if self.calibrator is not None else 0

    def _set_collecting(self, collecting: bool):
        """切换「采集中/已暂停」状态，并同步按钮文字与「求解并保存」的可用性。"""
        self._collecting = collecting
        self.btn_calib_capture.setText('停止采集' if collecting else '开始采集')
        self.btn_calib_solve.setEnabled(self._calib_frame_count() > 0)

    @Slot()
    def on_calib_capture_clicked(self):
        """开始/暂停采集。只在采集状态下接帧，避免误采普通画面。

        ⚠️ 暂停**绝不清空已采帧**（2026-09-23 用户实际故障）：
        采到 50 帧后点了一下这个按钮（当时它写着"停止采集"），再去求解，
        弹出"还没有采集到有效帧"，整场白采。根因就是旧代码在这里
        ``self.calibrator = None``，把已采的 50 帧连同标定器一起丢了，
        而界面只提示"已停止采集。"，用户根本不知道帧没了。
        现在改成：暂停只停止接帧，帧留着，随时可求解或继续补采。
        """
        if self.cap is None or not self.cap.isOpened():
            QMessageBox.warning(self, '标定错误', '摄像头未连接，无法进行标定！')
            return

        if not getattr(self, '_collecting', False):
            if self.calibrator is None:          # 只在没有存量帧时新建
                self.calibrator = self._make_calibrator()
            self._set_collecting(True)
            n = self._calib_frame_count()
            head = f'继续采集中（已有 {n} 帧）' if n else '采集中'
            self.label_calib_info.setText(
                f'{head}：请让棋盘格在画面中变换位置与倾斜角。（已采集 {n} 帧）')
        else:
            self._set_collecting(False)
            n = self._calib_frame_count()
            self.label_calib_info.setText(
                f'已暂停采集，已保留 {n} 帧（没有丢弃）。\n'
                f'点「求解并保存」解算内参；想补采就再点「开始采集」。')

    @Slot()
    def on_calib_solve_clicked(self):
        """求解内参并持久化 —— **丢到子线程去解**，界面不冻。

        2026-09-23 修正：旧代码在这里同步调 ``self.calibrator.calibrate()``，
        而 ``cv2.calibrateCamera`` 实测 50 帧要 **17 s**，点一下按钮整个界面
        就卡住十几秒不动。现在本槽函数只做「停接帧 → 丢线程 → 立刻返回」，
        结果由 ``on_calib_solved`` 处理。
        """
        if self._solving:
            return                       # 已在求解，忽略重复点击

        if self.calibrator is None or self.calibrator.frame_count == 0:
            QMessageBox.warning(
                self, '标定错误',
                '还没有采集到有效帧。\n\n'
                '请先点「开始采集」，让棋盘格完整出现在画面里；\n'
                '提示出现「检测到棋盘格 ✓」后才算采到一帧。')
            return

        # 求解期间停止接帧（避免边解边往点列表里加），但**帧全部保留**
        self._set_collecting(False)
        self._solving = True
        self.btn_calib_solve.setEnabled(False)

        n = self.calibrator.frame_count
        self.label_calib_info.setText(
            f'正在求解内参……（共 {n} 帧）\n'
            f'实测 50 帧约需十几秒；界面可以继续操作，解完会自动弹结果。')
        self.status_bar.showMessage(f'正在后台求解相机内参（{n} 帧）……')

        self._solve_thread = CalibSolveThread(
            self.calibrator.object_points, self.calibrator.image_points,
            self.calibrator.image_size, self)
        self._solve_thread.solved.connect(self.on_calib_solved)
        self._solve_thread.start()

    @Slot(object, str)
    def on_calib_solved(self, intr, err):
        """求解线程回主线程的结果处理：写盘、生效、体检、汇报。

        线程里不碰任何 Qt 控件；弹窗/写文件/改状态一律回到主线程做。
        """
        self._solving = False
        self.status_bar.clearMessage()
        self.btn_calib_solve.setEnabled(self._calib_frame_count() > 0)

        if intr is None:
            self.label_calib_info.setText(
                f'求解失败：{err}\n（已采的帧仍保留，可补采后重试）')
            QMessageBox.critical(self, '标定失败', f'求解内参出错：{err}')
            return

        try:
            CameraCalibrator.save(intr, self._calib_file)
        except Exception as e:
            self.label_calib_info.setText(f'内参写不进去：{e}（已采的帧仍保留）')
            QMessageBox.critical(self, '标定失败', f'标定文件写入失败：{e}')
            return

        # 同时按**设备**记一份 —— 这是「换相机自动认出来」的关键一步。
        # 只写 calib.json 的话，下次插上另一台相机仍会照读这份内参。
        act = getattr(self, '_cam_active', None)
        dev = act.device if act else None
        bound = bool(dev is not None and dev.fingerprint)
        bind_note = ''
        if bound:
            try:
                cam_profiles.upsert_profile(
                    self._cam_store, dev.fingerprint,
                    cam_profiles.profile_from_intrinsics(dev, intr, note='本机标定'))
                self._persist_camera_store()
                # 顺手给 calib.json 盖个设备戳。旧程序读它时会被忽略（
                # CameraCalibrator.load 只取 dataclass 里有的字段），所以对
                # 树莓派端与旧版无害；但新版本据此能拦住最顽固的一种误用：
                # 给相机 A 标完，插上**另一台同分辨率**的相机 B —— 没有戳时
                # 判定只能含糊地"暂用旧文件"，有了戳就能明确拒用。
                cam_profiles.stamp_device(self._calib_file, dev.fingerprint)
                bind_note = (f'\n\n已按设备记住：{dev.name}\n'
                             f'（指纹 {dev.fingerprint}）\n'
                             f'以后插别的相机不会误用这份内参。')
                print(f'[设备] 标定已绑定到 {dev.name} / {dev.fingerprint}')
            except OSError as e:
                bind_note = f'\n\n⚠️ 按设备保存失败：{e}（文件版标定仍已保存）'
                self.status_bar.showMessage(f'按设备保存失败：{e}', 8000)
        else:
            bind_note = ('\n\n⚠️ 没能识别出本机摄像头，这份标定**无法按设备记住**，'
                         '换相机时可能被误用。请点「重新检测设备」后再标一次。')

        # 求解成功后立即生效，不必重启；统一走判定函数（单一出口，避免两处各写一份状态）
        self._legacy_intrinsics = intr
        self.calibrator = None            # 成功后清空：下次「开始采集」是全新一轮
        self._set_collecting(False)
        self.apply_calibration_decision(self._frame_size())

        w, h = intr.image_size
        warns = []
        if intr.rms_error >= 1.0:
            warns.append(f'重投影误差 {intr.rms_error:.3f} px 偏高（>1.0 已不可接受）')
        if not (0.15 * w < intr.cx < 0.85 * w) or not (0.15 * h < intr.cy < 0.85 * h):
            warns.append(f'主点 (cx={intr.cx:.0f}, cy={intr.cy:.0f}) 明显偏离画面中心'
                         f'（画面 {w}x{h}）')
        # fx/fy 合理区间：rms 和主点都看不出"焦距发疯"。实测 8 帧姿态不变时
        # 能解出 fx=40847 而 rms 才 0.21 —— 那是退化解，拿去测距全是废数。
        # 正常焦距落在 [0.2·宽, 4·宽]（对 640 宽即 128~2560 px，
        # 覆盖约 15°~120° 水平视场角），出界基本就是退化或尺寸记录错了。
        if not (0.2 * w <= intr.fx <= 4.0 * w) or not (0.2 * h <= intr.fy <= 4.0 * h):
            warns.append(f'焦距 fx={intr.fx:.0f}, fy={intr.fy:.0f} 超出合理区间'
                         f'（{0.2 * w:.0f}~{4.0 * w:.0f} px）—— 解出了退化解，'
                         f'这份数据不可用于测距，必须重采')

        detail = (f'内参已保存到：\n{self._calib_file}\n\n'
                  f'fx={intr.fx:.1f}  fy={intr.fy:.1f}\n'
                  f'cx={intr.cx:.1f}  cy={intr.cy:.1f}\n'
                  f'重投影误差={intr.rms_error:.3f} px' + bind_note)

        if warns:
            QMessageBox.warning(
                self, '标定完成，但质量存疑',
                detail + '\n\n' + '\n'.join('· ' + s for s in warns) +
                '\n\n常见原因：棋盘姿态变化不够（只在同一角度平移），或画面模糊、反光。\n'
                '建议重采：让棋盘走遍画面四角，并做出明显倾斜（左右各约 20°）。\n'
                '（结果已保存，可以先用；想重标就再点「开始采集」。）')
        else:
            quality = '优' if intr.rms_error < 0.5 else '可接受'
            QMessageBox.information(self, '标定完成', detail + f'\n\n质量：{quality}')

    @Slot()
    def on_pitch_changed(self, value):
        """俯仰角改了立即重建测距配置 —— 不需要重标定。"""
        self.global_params.pitch_deg = float(value)
        self.ranger.update_config(RangingConfig.from_params(self.global_params))
        self._persist_mount_params('手工填写')

    @Slot()
    def on_camera_height_changed(self, value):
        """相机安装高度改了立即重建测距配置 —— 不需要重标定。

        这是地面接触点法（CHARTER 第 2 条）唯一的安装参数：卷尺量一次镜头中心
        到地面的高度。填 0 视为「未测量」，此时接触点法与反解判据都不可用，
        部分可见的目标会明确显示「不可测」，而不是按某个默认身高硬算。
        """
        self.global_params.camera_height = float(value)
        self.ranger.update_config(RangingConfig.from_params(self.global_params))
        self.refresh_distance_widgets()
        self._persist_mount_params('手工填写')

    def _ranging_tooltip(self, res=None):
        """距离读数的悬停说明。

        优先级：**为什么不可测 > 安装参数填没填**。UI 上位置有限，但"为什么"
        必须能查到 —— 否则用户只看到"不可测"，分不清是没填安装高度、
        还是目标只露出一部分。这直接对应 CHARTER 里"不给猜测值"的要求。
        """
        if res is not None and res.reason:
            return res.reason
        h = self.global_params.camera_height
        if h <= 0:
            return ('未填相机安装高度：只能对完整可见的目标测距（高度法）。\n'
                    '可以用卷尺量一次镜头中心到地面的高度填上，也可以在'
                    '「安装参数自标定」里把目标摆到已知距离反解出来；\n'
                    '填好后即可对部分可见的目标测距（如头顶出画的人）。')
        # 俯仰角误差敏感度 ≈ 0.01745·Z/H（每 1°）—— 与 H 成反比，装得越高越不敏感。
        # 这里算的是 10 m 处的值，用来提醒用户「角度别量错」。
        sens = 0.01745 * 10.0 / h * 100.0
        return (f'相机安装高度 {h:.2f} m，已启用地面接触点法。\n'
                f'10 m 处每 1° 的俯仰角误差约带来 {sens:.0f}% 距离误差'
                f'（装得越高越不敏感）。\n'
                f'高度与俯仰角都可由「安装参数自标定」反解，不必手工量。')

    def refresh_distance_widgets(self, res=None):
        """把距离读数的**悬停说明**与**界面上那行原因**成对刷新。

        为什么要成对：悬停要鼠标停上去才看得见，而"为什么不可测"是用户
        当下就要知道的信息 —— 实测有人因为只看到「不可测」而怀疑是自己
        模型选错了。两者都从同一份 ``RangingResult`` 取，**同源**才不会
        一个说 A、一个说 B（显示与判定不同源，之前在设备状态标签上踩过一次）。
        """
        self.label_distance_value.setToolTip(self._ranging_tooltip(res))
        self.label_distance_reason.setText(self._ranging_reason_text(res))

    def _ranging_reason_text(self, res=None) -> str:
        """距离读数下面那行小字：把「为什么」直接摆在界面上，而不是只藏在悬停里。

        三层，与 ``_ranging_tooltip`` 同源：

        ① **内参不可用**（没标定 / 分辨率不符 / 属于另一台相机）—— 这是最根本
           的一条，任何目标都测不了，所以优先显示，并指向「设置」页；
        ② **本帧目标自己的原因**（``RangingResult.reason``）—— 「脚被画面下边界
           裁掉（目标太近）」「框底边落在相机水平线以上，不可能踩在地面上」等；
        ③ **正常出数** —— 报出所用方法，让人知道这个数是靠哪条路给的
           （接触点法靠脚，高度法靠全身框 + 登记身高）。
        """
        if not self.global_params.calibrated:
            why = self.global_params.invalid_reason or '未标定'
            return f'{why} —— 内参不可用，测距已停（见「设置」页）'
        if res is not None and res.reason:
            return res.reason
        if res is not None and res.distance is not None:
            return f'（{res.method}）'
        return ''

    # ------------------------------------------------------------------
    # 安装参数自标定（外参：相机安装高度 + 俯仰角）
    # ------------------------------------------------------------------
    # 为什么是「标定」而不是「手工填」
    # ------------------------------
    # 接触点法 Z = H_相机 / tan(俯仰角 + atan((v_底 − cy)/fy)) 需要两个量：
    # 相机装多高、朝下多少度。卷尺与量角器都能量，但**俯仰角精度极敏感** ——
    # 10 m 处每 1° 约带来 0.01745·Z/H 的距离误差（H=0.7 m 时就是 25%/1°），
    # 而角度恰好是最难量准的那个。反过来，把目标摆到**卷尺已知的距离**上、
    # 读出框底边像素，两个已知距离就能把 (H, 俯仰角) 同时解出来
    # （见 core/calibration.solve_mount_params）—— 相机装多高都能解。
    #
    # 为什么采一段而不是取一帧：底边像素是观测量，它的随机误差直接进解算
    # （1 px 噪声 -> 俯仰角约 ±0.13°）。所以取 ~1 秒窗口的均值，并用散布
    # 判断目标是否静止；散布过大就拒收这一次，而不是记一个脏点。

    MARK_WINDOW_MS = 1000        # 采样窗口长度（毫秒）
    MARK_MIN_FRAMES = 5          # 窗口内至少收到几帧有效检测
    MARK_MAX_SPREAD_PX = 3.0     # 底边像素散布上限：超过说明目标在动

    @Slot()
    def on_mark_known_clicked(self):
        """记一个「已知距离」采样点（窗口内取平均，避免单帧噪声）。"""
        if not self.global_params.calibrated or self.global_params.intrinsics is None:
            QMessageBox.warning(
                self, '安装参数自标定',
                '相机还没标定，没有可用内参，无法解算安装参数。\n'
                '请先在「设置 → 相机标定」里完成棋盘格标定。')
            return
        if self.global_params.detection_height <= 0:
            QMessageBox.warning(
                self, '安装参数自标定',
                '当前没有检测到目标，无法采样。\n\n'
                '请让目标（人 / 椅子等）完整出现在画面里并保持静止，再点本按钮。')
            return
        self._marking = True
        self._mark_samples = []
        self._mark_distance = float(self.spin_known_dist.value())
        self.btn_mark_known.setEnabled(False)
        self.label_mount_status.setText(
            f'正在采样 {self._mark_distance:.2f} m 处的目标……请让目标静止')
        if self._mark_timer is not None:
            self._mark_timer.stop()
        self._mark_timer = QTimer(self)
        self._mark_timer.setSingleShot(True)
        self._mark_timer.timeout.connect(self.on_mark_finished)
        self._mark_timer.start(self.MARK_WINDOW_MS)

    @Slot()
    def on_mark_finished(self):
        """采样窗口结束：先查帧数与散布，合格才记为一个采样点。"""
        self._marking = False
        self.btn_mark_known.setEnabled(True)
        samples = self._mark_samples
        self._mark_samples = []
        z = self._mark_distance

        if len(samples) < self.MARK_MIN_FRAMES:
            self.label_mount_status.setText(
                f'采样失败：这 {self.MARK_WINDOW_MS / 1000:.0f} 秒里只检测到 '
                f'{len(samples)} 帧（至少需要 {self.MARK_MIN_FRAMES} 帧）。'
                f'请让目标完整出现在画面里再重试。')
            return
        arr = np.asarray(samples, dtype=float)
        spread = float(arr.std())
        if spread > self.MARK_MAX_SPREAD_PX:
            self.label_mount_status.setText(
                f'采样失败：框底边像素散布 {spread:.1f} px 偏大'
                f'（> {self.MARK_MAX_SPREAD_PX:.0f} px），目标可能在移动。'
                f'请让目标静止后重新采样。')
            return

        # 同一个距离重复标记 -> 覆盖，避免列表里堆互相矛盾的点
        self._mount_marks = [m for m in self._mount_marks
                             if abs(m['dist'] - z) > 0.05]
        self._mount_marks.append({'dist': z, 'v': float(arr.mean()),
                                  'std': spread, 'n': len(arr)})
        self._mount_marks.sort(key=lambda m: m['dist'])
        self.btn_solve_mount.setEnabled(len(self._mount_marks) >= 2)
        self._update_mount_status()

    def _update_mount_status(self):
        """把已记录的采样点回显到监视页（含还差几个、能不能求解）。"""
        marks = self._mount_marks
        text = '已记录采样点：' + '、'.join(
            f"距离 {m['dist']:.2f} m → 底边 {m['v']:.0f} px"
            f"（{m['n']} 帧，散布 {m['std']:.1f} px）" for m in marks)
        if len(marks) < 2:
            text += (f'\n还差 {2 - len(marks)} 个：换一个距离'
                     f'（推荐 5 m、10 m）再点一次「记为采样点」')
        elif len(marks) == 2:
            text += ('\n可以点「求解安装参数」。注意两点**无法自查**标记错误'
                     '（如把膝盖当成脚），建议再补一个距离做三点')
        else:
            text += '\n可以点「求解安装参数」'
        self.label_mount_status.setText(text)

    @Slot()
    def on_solve_mount_clicked(self):
        """由采样点反解 (相机安装高度, 俯仰角)，并写回设置页立即生效。"""
        intr = self.global_params.intrinsics
        if intr is None or not intr.is_valid():
            QMessageBox.warning(self, '安装参数自标定',
                                '相机未标定（没有可用内参），无法解算安装参数。')
            return
        marks = [(m['dist'], m['v']) for m in self._mount_marks]
        sol = solve_mount_params(marks, intr)
        if not sol.ok:
            self.label_mount_status.setText(f'求解未通过：{sol.reason}')
            QMessageBox.warning(
                self, '安装参数自标定',
                f'{sol.reason}\n\n已记录的采样点保留，可补采后重试。')
            return

        # 写回设置页：与手工填写走**同一条通路**（控件 valueChanged -> 重建
        # 测距配置）。控件精度（高度 2 位、俯仰角 1 位）会截断解出的值，
        # 所以按截断后的值再显式同步一次，避免"显示的值"与"实际生效的值"不一致。
        self.spin_camera_height.setValue(round(sol.camera_height, 2))
        self.spin_pitch_deg.setValue(round(sol.pitch_deg, 1))
        h_applied = float(self.spin_camera_height.value())
        pitch_applied = float(self.spin_pitch_deg.value())
        self.global_params.camera_height = h_applied
        self.global_params.pitch_deg = pitch_applied
        self.ranger.update_config(RangingConfig.from_params(self.global_params))
        self.refresh_distance_widgets()
        # 落盘。上面两个 setValue 已经各自触发过一次落盘（来源会被记成「手工填写」），
        # 这里再用正确来源覆盖写一次 —— 文件很小，一次多余写入换来源标注准确，划算。
        self._persist_mount_params('自标定')

        sens = (0.01745 * 10.0 / h_applied * sol.sigma_pitch * 100.0
                if h_applied > 0 else float('nan'))
        self.label_mount_status.setText(
            f'已解出：安装高度 {h_applied:.2f} m、俯仰角 {pitch_applied:.1f}°'
            f'（残差 {sol.residual_px:.2f} px，用了 {sol.n_points} 个采样点）')
        QMessageBox.information(
            self, '安装参数自标定',
            f'{sol.detail}\n\n'
            f'估计精度（按底边定位误差 1 px 估计）：\n'
            f'    相机高度 ±{sol.sigma_height * 100:.1f} cm\n'
            f'    俯仰角   ±{sol.sigma_pitch:.2f}°\n\n'
            f'已写入「设置 → 相机标定」：安装高度 {h_applied:.2f} m、'
            f'俯仰角 {pitch_applied:.1f}°，已立即生效。\n'
            f'按这两个数，10 m 处由俯仰角误差贡献的距离误差约 {sens:.1f}%。')

    # ------------------------------------------------------------------
    # 录制回放（CHARTER「范围内的」第 6 条）
    # ------------------------------------------------------------------

    @Slot()
    def on_rec_toggle(self):
        """开始/结束录制。"""
        if self.recorder is None:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        if self.cap is None or not self.cap.isOpened():
            QMessageBox.warning(self, '录制错误', '摄像头未连接，无法录制。')
            return
        if not hasattr(self, 'current_frame') or self.current_frame is None:
            QMessageBox.warning(self, '录制错误', '还没有可用画面，请稍候再试。')
            return

        root = self._recordings_dir()
        try:
            self.recorder = Recorder(root=root, fps=float(self.global_params.fps))
            h, w = self.current_frame.shape[:2]
            session_dir = self.recorder.start(
                (h, w, 3),
                calibrated=self.global_params.calibrated,
            )
        except Exception as e:
            self.recorder = None
            QMessageBox.critical(self, '录制失败', f'无法开始录制：{e}')
            return

        self._rec_seq = 0
        self._rec_t0 = time.time()
        self.btn_rec_toggle.setText('停止录制')
        self.label_rec_status.setText('● 录制中')
        self.label_rec_info.setText(
            f'正在录制到：\n{session_dir}\n'
            f'未标定，测距值不可信' if not self.global_params.calibrated else
            f'正在录制到：\n{session_dir}\n已标定，测距值可用'
        )
        self.status_bar.showMessage('开始录制', 3000)

    def stop_recording(self):
        if self.recorder is None:
            return
        try:
            meta = self.recorder.stop()
        except Exception as e:
            QMessageBox.critical(self, '录制失败', f'收尾出错：{e}')
            self.recorder = None
            self.btn_rec_toggle.setText('开始录制')
            self.label_rec_status.setText('空闲')
            return

        session_dir = self.recorder.session_dir
        self.recorder = None
        self.btn_rec_toggle.setText('开始录制')
        self.label_rec_status.setText('空闲')

        warn = ''
        if meta.dropped_frames > 0:
            # 丢帧必须明说：录像的实际内容与时长不符，使用者有权知道
            warn = f'\n⚠ 有 {meta.dropped_frames} 帧因写盘队列溢出被丢弃（帧率过高或磁盘慢）'
        if not meta.calibrated_at_record:
            warn += '\n⚠ 录制时未标定，本次数据轨的距离值全部为 None'

        self.label_rec_info.setText(
            f'已保存：\n{session_dir}\n'
            f'时长 {meta.duration_s:.1f}s，视频 {meta.frame_count} 帧，'
            f'数据轨 {meta.data_count} 条{warn}'
        )
        QMessageBox.information(
            self, '录制完成',
            f'时长 {meta.duration_s:.1f}s\n'
            f'视频帧数 {meta.frame_count}\n'
            f'数据轨记录 {meta.data_count}\n'
            f'丢帧 {meta.dropped_frames}{warn}'
        )
        # 录完自动挂到回放器上 —— 之前要手动再点「选择录制」，容易以为没存上
        if self._load_replay_session(session_dir):
            self.status_bar.showMessage(
                f'录制完成，已自动加载回放：{meta.session}', 5000)

    def _recordings_dir(self) -> str:
        """录制根目录固定在仓库下 recordings/（已在 .gitignore 中）。"""
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'recordings')
        os.makedirs(root, exist_ok=True)
        return root

    @Slot()
    def on_play_pick(self):
        """选择一次录制：列出现有会话（带摘要）让用户挑，不再浏览目录。

        旧版用目录选择框 —— 用户容易选到 recordings 根目录（没有
        video.avi，加载失败），或者不知道要进哪个目录。列表直接给摘要。
        """
        root = self._recordings_dir()
        sessions = Replayer.list_sessions(root)
        if not sessions:
            QMessageBox.information(self, '没有录制',
                                    f'{root} 下没有找到录制（需含 video.avi）。')
            return

        items = []
        for d in sessions:
            try:
                rp = Replayer(d)
                m = rp.meta
                items.append(f'{m.session}  ·  {m.duration_s:.0f}s · '
                             f'{m.frame_count} 帧 · 数据 {len(rp.records)} 条'
                             + ('  ⚠ 丢帧' if m.dropped_frames else ''))
            except Exception:                                  # noqa: BLE001
                items.append(os.path.basename(d))

        choice, ok = QInputDialog.getItem(
            self, '选择录制', '选中要回放的录制：', items, len(items) - 1,
            False)
        if not ok:
            return
        d = sessions[items.index(choice)]
        if self._load_replay_session(d):
            self.status_bar.showMessage(
                f'已加载录制：{self.replayer.meta.session}', 3000)

    def _load_replay_session(self, session_dir: str) -> bool:
        """把一个录制会话挂到回放器上。失败弹窗说明原因并返回 False。

        失败时保留之前已加载的会话（换片失败不应该把手头的片也弄丢）。
        """
        # 回放中直接换片：先停定时器，避免旧定时器继续驱动
        if self.replay_timer is not None and self.replay_timer.isActive():
            self.replay_timer.stop()
            self.btn_play_toggle.setText('播放')
        if not self.camera_timer.isActive():
            self.camera_timer.start()
        try:
            replayer = Replayer(session_dir)
        except Exception as e:
            QMessageBox.critical(self, '加载失败', f'无法读取录制：{e}')
            return False
        if not replayer.open():
            QMessageBox.critical(self, '加载失败', 'video.avi 无法打开。')
            return False
        self.replayer = replayer
        self.play_index = 0
        total = self.replayer.total_frames
        self.label_play_pos.setText(f'0/{total}')
        self.label_play_info.setText(
            f'已加载：{self.replayer.meta.session}\n'
            f'时长 {self.replayer.meta.duration_s:.1f}s · '
            f'视频 {self.replayer.meta.frame_count} 帧 · '
            f'数据轨 {len(self.replayer.records)} 条 · '
            f'丢帧 {self.replayer.meta.dropped_frames}'
        )
        self.show_replay_summary()
        return True

    @Slot()
    def on_play_toggle(self):
        """播放/暂停。回放由 QTimer 驱动，与摄像头取帧同构。"""
        if self.replayer is None:
            QMessageBox.information(self, '未加载录制', '请先选择一次录制。')
            return

        if self.replay_timer is not None and self.replay_timer.isActive():
            self.replay_timer.stop()
            self.btn_play_toggle.setText('继续播放')
            return

        if self.replayer.finished:
            self.replayer.seek(0)
            self.play_index = 0

        if self.replay_timer is None:
            self.replay_timer = QTimer()
            interval = int(1000 / max(self.global_params.fps, 1))
            self.replay_timer.setInterval(interval)
            self.replay_timer.timeout.connect(self.on_replay_tick)

        # 回放期间停掉摄像头取帧，避免两路画面互相覆盖
        if self.camera_timer.isActive():
            self.camera_timer.stop()
        self.replay_timer.start()
        self.btn_play_toggle.setText('暂停')

    @Slot()
    def on_play_stop(self):
        if self.replay_timer is not None and self.replay_timer.isActive():
            self.replay_timer.stop()
        self.btn_play_toggle.setText('播放')
        if self.replayer is not None:
            self.replayer.seek(0)
            self.play_index = 0
            self.label_play_pos.setText(f'0/{self.replayer.total_frames}')
        # 恢复实时画面
        if not self.camera_timer.isActive():
            self.camera_timer.start()

    def on_replay_tick(self):
        """回放一帧：画面走显示路径，数据走与实时相同的回调。"""
        if self.replayer is None:
            # 防御：回放器已被释放但定时器仍在跳（例如切换/关闭竞态）
            if self.replay_timer is not None and self.replay_timer.isActive():
                self.replay_timer.stop()
            return
        frame, rec = self.replayer.read()
        if frame is None:
            if self.replay_timer is not None:
                self.replay_timer.stop()
            self.btn_play_toggle.setText('播放')
            if not self.camera_timer.isActive():
                self.camera_timer.start()
            self.status_bar.showMessage('回放结束', 3000)
            return

        self.play_index = self.replayer.position
        self._display_frame(frame)

        # 把数据轨记录还原成检测字典，复用实时链路的展示与绘图逻辑
        target = None
        if rec is not None and rec.has_target:
            target = {
                'x': rec.x, 'y': rec.y, 'width': rec.width,
                'height': rec.height, 'confidence': rec.confidence,
                'class_id': rec.class_id,
            }
            self.last_detection = target
            self.global_params.detection_x = rec.x
            self.global_params.detection_y = rec.y
            self.global_params.detection_width = rec.width
            self.global_params.detection_height = rec.height
            self.global_params.detection_conf = rec.confidence
            self.global_params.target_category = rec.class_name or '未知'
            # 回放时不重算距离，直接用录制时的值 —— 保证"看到的就是当时算的"
            self.global_params.distance = rec.distance
        else:
            self.last_detection = None
            self.global_params.distance = None

        if not self._replay_seeking:
            total = self.replayer.total_frames
            self.label_play_pos.setText(f'{self.play_index}/{total}')
            if total > 0:
                self.slider_play_pos.setValue(int(self.play_index / total * 1000))

    def _display_frame(self, frame_bgr):
        """把一帧 BGR 画到界面上（实时与回放共用）。"""
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        qt_img = QImage(frame_rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self.lbl_original.setPixmap(QPixmap.fromImage(qt_img).scaled(
            self.lbl_original.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

        draw_img = frame_rgb.copy()
        if self.last_detection and self.last_detection.get('confidence', 0) >= 0.3:
            target = self.last_detection
            x, y = target['x'], target['y']
            w_box = target.get('width', 40)
            h_box = target.get('height', 40)
            conf = target['confidence']
            name = self.global_params.target_category or '未知'
            dist = self.global_params.distance
            label = f'{name} {conf:.2f}'
            if dist is not None:
                label += f' {dist:.2f}m'
            top_left = (int(x - w_box / 2), int(y - h_box / 2))
            bottom_right = (int(x + w_box / 2), int(y + h_box / 2))
            cv2.rectangle(draw_img, top_left, bottom_right, (0, 255, 0), 2)
            size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(draw_img, (top_left[0], top_left[1] - size[1] - 5),
                          (top_left[0] + size[0], top_left[1]), (0, 255, 0), -1)
            cv2.putText(draw_img, label, (top_left[0], top_left[1] - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        else:
            cv2.putText(draw_img, 'No Target', (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        h2, w2, ch2 = draw_img.shape
        qt_img2 = QImage(draw_img.data, w2, h2, ch2 * w2, QImage.Format_RGB888)
        self.lbl_process.setPixmap(QPixmap.fromImage(qt_img2).scaled(
            self.lbl_process.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @Slot(int)
    def on_play_seek(self, value):
        """拖动进度条定位。"""
        if self.replayer is None:
            return
        total = self.replayer.total_frames
        if total <= 0:
            return
        target_idx = int(value / 1000 * (total - 1))
        self._replay_seeking = True
        try:
            self.replayer.seek(target_idx)
            self.play_index = target_idx
            self.label_play_pos.setText(f'{target_idx}/{total}')
        finally:
            self._replay_seeking = False

    def show_replay_summary(self):
        """回放数据的统计摘要 + 测距曲线。

        曲线只画有值的点：距离为 None 的帧不画 0 ——
        0 米是"有效但错误"的读数，None 是"没有读数"，两者在图上必须可区分。
        """
        if self.replayer is None:
            return
        s = self.replayer.summary()
        dist_txt = '不可解算'
        if s['distance_min'] is not None:
            dist_txt = f'{s["distance_min"]:.2f} ~ {s["distance_max"]:.2f} m'
        conf_txt = ('—' if s['confidence_mean'] is None
                    else f'{s["confidence_mean"]:.3f}')
        calib_txt = '已标定' if s['calibrated_at_record'] else '未标定（距离不可信）'
        self.label_replay_summary.setText(
            f'会话 {s["session"]} · 时长 {s["duration_s"]:.1f}s · '
            f'视频 {s["frame_count"]} 帧 · 数据轨 {s["data_count"]} 条 · '
            f'丢帧 {s["dropped_frames"]}\n'
            f'有目标 {s["target_frames"]} 帧 · 可测距 {s["ranged_frames"]} 帧 · '
            f'距离范围 {dist_txt} · 平均置信度 {conf_txt} · 录制时{calib_txt}'
        )

        ts, ds = self.replayer.distance_series()
        if not hasattr(self, '_replay_curve'):
            self.plot_replay_distance.addLegend()
            self._replay_curve = self.plot_replay_distance.plot(
                [], [], pen=pg.mkPen('g', width=2), name='几何测距')
        self._replay_curve.setData(ts, ds)
        self.plot_replay_distance.setLabel('bottom', '时间', units='s')
        self.plot_replay_distance.setLabel('left', '距离', units='m')
        self.plot_replay_distance.showGrid(x=True, y=True)

    def update_param_realtime(self,param_name,value,label,fmt):
        setattr(self.global_params,param_name,value)
        label.setText(fmt % value)

     
    #界面交互
    @Slot(int)
    def on_tab_change(self,index):
        tab_name=['监控','深度分析','设置','录制回放']
        currebt_tab=tab_name[index]
        print(f"当前选项卡：{currebt_tab}")
        if currebt_tab=='深度分析':
            self.init_analysis_plots()
            if not self.analysis_timer.isActive():
                self.analysis_timer.start()
        elif currebt_tab=='设置':
            self.refresh_calib_widgets()
            self.refresh_camera_widgets()
        elif currebt_tab=='录制回放':
            if self.replayer is not None:
                self.show_replay_summary()
        elif self.analysis_timer.isActive() and currebt_tab!='深度分析' and self.global_params.plot_enable:
            self.analysis_timer.stop()     
                
    @Slot()
    def on_calibrate_clicked(self):
        """应用设置页的参数并重载模型。

        注意：这里**不做相机标定**。相机内参由「相机标定」分组的
        「求解并保存」负责，因为那是需要棋盘格的独立流程。
        本按钮只负责把界面上改过的运行参数落到 GlobalParams 并生效，
        避免"标定"一词同时指两件事（旧版本的问题）。
        """
        self.label__calibrate_status.setText("参数应用中……")
        self.QPuahButton_calibrate_status.setEnabled(False)
        QApplication.processEvents()

        try:
            self.global_params.sample_freq=self.slider_sample_freq.value()
            self.global_params.base_width=self.slider_base_width.value()
            self.global_params.target_select_rule=self.combo_target_select_rule.currentIndex()
            self.global_params.hardware_accel=self.combo_hardware_accel.currentText()
            self.global_params.mode_path=self.label_model_path.text()
            self.global_params.label_path=self.label_label_path.text()
            self.global_params.specific_class = self.combo_specific_class.currentText()
            self.global_params.plot_enable=self.checkBox.isChecked()

            self.update_timer.setInterval(int(1000/self.global_params.sample_freq))
            self.async_init_ai_model(reload=True)#重新加载模型

            if hasattr(self,'labels') and self.labels and len(self.labels)>0:#仅有标签时更新指定类别参数
                self.global_params.specific_class_id=self.combo_specific_class.currentIndex()
                self.global_params.specific_class=self.combo_specific_class.currentText()
            else:
                self.global_params.specific_class_id=-1
                self.global_params.specific_class='无标签'
            # 测距配置跟着一起刷新（俯仰角可能也改过）
            self.ranger.update_config(RangingConfig.from_params(self.global_params))
            QTimer.singleShot(2000,self.finish_calibration)
        except Exception as e:
            self.label__calibrate_status.setText('参数应用失败')
            QMessageBox.critical(self,'参数应用失败',f'过程出错：{str(e)}')
            self.QPuahButton_calibrate_status.setEnabled(True)
    
    def finish_calibration(self):#不阻塞主线程
        self.QPuahButton_calibrate_status.setEnabled(True)
        QMessageBox.information(self,'参数已应用','运行参数已更新并生效')
        self.refresh_calib_widgets()   # 标定状态回到真实值，而不是被这里改写

    # ------------------------------------------------------------------
    # 默认模型 / 上次选择（models/settings.json，已 gitignore）
    # ------------------------------------------------------------------

    @staticmethod
    def _model_settings_path() -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'models', 'settings.json')

    # Windows 端实测最佳的默认组合（README 横评：43~47 ms/帧）
    DEFAULT_MODEL = os.path.join('models', 'yolov8', 'yolov8n.onnx')
    DEFAULT_LABELS = os.path.join('models', 'labels', 'coco80.txt')

    def _resolve_model_paths(self):
        """决定启动时用哪套模型路径：上次的选择 > 默认最佳 > 空。

        上次的选择记录在 models/settings.json（点「应用参数」成功后写入）；
        文件已不存在时视为失效，退回默认。
        """
        base = os.path.dirname(os.path.abspath(__file__))
        default_model = os.path.normpath(
            os.path.join(base, self.DEFAULT_MODEL))
        default_labels = os.path.normpath(
            os.path.join(base, self.DEFAULT_LABELS))

        last_model, last_labels = '', ''
        try:
            with open(self._model_settings_path(), 'r',
                      encoding='utf-8') as f:
                data = json.load(f)
            last_model = data.get('model_path', '')
            last_labels = data.get('label_path', '')
        except (OSError, ValueError):
            pass
        if not os.path.isfile(last_model):
            last_model = ''
        if not os.path.isfile(last_labels):
            last_labels = ''

        model = last_model or (default_model if os.path.isfile(default_model)
                               else '')
        labels = last_labels or (default_labels if os.path.isfile(default_labels)
                                else '')
        return model, labels, bool(last_model)   # (路径, 标签, 来自上次选择)

    def _apply_default_model_paths(self):
        """启动时把模型路径填进参数与控件 —— 让「打开就能用」成为默认行为。"""
        model, labels, from_last = self._resolve_model_paths()
        if model:
            self.global_params.mode_path = model
            self.label_model_path.setText(model)
        if labels:
            self.global_params.label_path = labels
            self.label_label_path.setText(labels)
        if model:
            where = '上次选择' if from_last else '默认模型'
            self.status_bar.showMessage(
                f'使用{where}：{os.path.basename(model)}（后台加载中）', 5000)

    def _save_model_settings(self):
        """记住这次生效的模型组合，下次启动直接用（不用再选）。"""
        data = {
            'model_path': self.global_params.mode_path,
            'label_path': self.global_params.label_path,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        try:
            os.makedirs(os.path.dirname(self._model_settings_path()),
                        exist_ok=True)
            tmp = self._model_settings_path() + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._model_settings_path())
        except OSError as e:
            print(f'模型设置落盘失败（不影响本次使用）：{e}')

    @Slot()        
    def on_model_browse(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择AI模型文件", "", "模型文件 (*.onnx *.tflite *.engine);;所有文件 (*.*)")
        if file_path:
            self.label_model_path.setText(file_path)
            self.global_params.mode_path=file_path
           
    @Slot()
    def on_label_browse(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择标签文件", "", "标签文件 (*.txt);;所有文件 (*.*)")
        if file_path:
            self.label_label_path.setText(file_path)
            self.global_params.label_path=file_path
            try:
                with open(file_path,'r',encoding='utf-8') as f:
                    self.labels=[line.strip() for line in f]
                print(f'加载了{len(self.labels)}个标签')
                self.status_bar.showMessage(f'加载标签成功：{len(self.labels)}个', 3000)
            except Exception as e:
                print(f'加载标签失败：{str(e)}')
                self.labels=[]
                self.status_bar.showMessage(f'加载标签失败：{str(e)}', 5000)
            self.update_specific_class_combo()
                
    def update_specific_class_combo(self):
        self.combo_specific_class.clear()#清空下拉框，确保状态统一
        if hasattr(self, 'labels') and self.labels and len(self.labels)>0:
            self.combo_specific_class.addItems(self.labels)
            class_id=self.global_params.specific_class_id
            if class_id is not None and 0 <= class_id < len(self.labels):
                self.combo_specific_class.setCurrentIndex(class_id)
            else:
                self.global_params.specific_class_id=0
                self.combo_specific_class.setCurrentIndex(0)
                self.global_params.specific_class=self.labels[0]
        else:
            self.combo_specific_class.addItem('无标签')
            self.global_params.specific_class_id=-1
            self.global_params.specific_class='无标签'

            
    def on_detection_ready(self,target):#检测结果回调

        self.last_detection=target

        if target and target['confidence']>=self.global_params.confidence_thres:# 增加置信度过滤，低于阈值视为无目标
            self.global_params.detection_x = target['x']
            self.global_params.detection_y = target['y']
            self.global_params.detection_width = target.get('width', 0)
            self.global_params.detection_height = target.get('height', 0)
            self.global_params.detection_conf = target['confidence']
            self.global_params.detection_class = target['class_id']

             # 类别名显示
            if self.detector and hasattr(self.detector, 'labels') and self.detector.labels:
                if target['class_id'] < len(self.detector.labels):
                    self.global_params.target_category = self.detector.labels[target['class_id']]
                else:
                    self.global_params.target_category = '未知'
            else:
                self.global_params.target_category = '未知'
            self.lcd_credibility.display(self.global_params.detection_conf)
            self.label_target_category.setText(self.global_params.target_category)
        else:
            self.global_params.detection_x = 320  # 重置为画面中心
            self.global_params.detection_y = 240
            self.global_params.detection_width = 0
            self.global_params.detection_height = 0
            self.global_params.detection_conf = 0.0
            self.global_params.detection_class = -1
            self.global_params.target_category = '未知'
            self.global_params.base_width=0.0
            self.lcd_credibility.display(0)
        
        # 几何测距：**常开**。测距是门槛判据「UI 实时显示测距值」的核心输出，
        # 不应依赖「是否启用深度分析」或「是否在录制」。
        #
        # 这里走 measure_from_box 而不是 distance_from_box：前者在出数之前先过
        # 可见性体检与反解判据，目标只露出一部分（贴脸、被挡到腰/膝）时明确返回
        # 「不可测 + 原因」。检测框是**可见部分**的包围盒，直接拿框高套公式
        # 会给出看着正常、却差几倍的错值（实测"贴脸"那格虚大 1248%）。
        res = None
        if self.global_params.detection_height > 0:
            res = self.ranger.measure_from_box(
                target if isinstance(target, dict) else {},
                self.global_params.target_category,
            )
        dist = res.distance if res is not None else None
        self.global_params.distance = dist

        # 实时距离读数（监视页「目标位置」分组，CHARTER 门槛判据）
        # display() 在存疑时给 "5.00 m？"、不可测时给 "不可测"，都不隐藏数据
        self.label_distance_value.setText(res.display() if res is not None else '不可测')
        # 悬停说明 + 界面上那行「为什么」一起刷（同源，见 refresh_distance_widgets）
        self.refresh_distance_widgets(res)

        # 安装参数自标定：采样窗口内收集「框底边像素」（只收真的检测到目标的帧）。
        # 底边像素是自标定的观测量，它的随机误差直接进解算 —— 所以取一段窗口
        # 的平均值，并在收尾时用散布判断目标是否静止。
        if self._marking and isinstance(target, dict) \
                and self.global_params.detection_height > 0:
            self._mark_samples.append(
                float(target.get('y', 0.0))
                + float(self.global_params.detection_height) / 2.0)

        if self.global_params.plot_enable:
            # 距离为 None 时曲线落 0（pyqtgraph 不画 None），但状态栏与录制
            # 里的值保持 None —— 绝不把"没有读数"伪装成"读到 0 米"
            distance = dist if dist is not None else 0.0
            self.sensor_history_x.append(self.global_params.detection_x)
            self.sensor_history_y.append(self.global_params.detection_y)
            self.sensor_history_wide.append(self.global_params.detection_width)
            self.sensor_history_hight.append(self.global_params.detection_height)
            self.sensor_history_conf.append(self.global_params.detection_conf)
            self.sensor_history_fps.append(self.global_params.inference_fps)
            self.target_distance.append(distance)
            self.time_history.append(self.time_counter)
            self.sensor_history_conf_thres.append(self.global_params.confidence_thres)
            self.time_counter += 1.0 / self.global_params.sample_freq

        # 录制：数据轨与视频轨分开存，此处只追加一条记录（非阻塞）
        if self.recorder is not None:
            self._rec_seq += 1
            self.recorder.push_record(FrameRecord.from_detection(
                seq=self._rec_seq,
                t=time.time() - self._rec_t0,
                target=target if isinstance(target, dict) else None,
                class_name=self.global_params.target_category,
                distance=dist,
                inference_fps=self.global_params.inference_fps,
            ))
            
    def _on_calib_frame(self, frame_bgr):
        """标定采集回调：检测棋盘格角点并给出实时反馈。

        角点检测是 CPU 密集操作，用计数节流（每 10 帧检一次），
        否则会拖垮摄像头预览帧率、用户反而对不准。
        """
        self._calib_tick = getattr(self, '_calib_tick', 0) + 1
        if self._calib_tick % 10 != 0:
            return
        try:
            ok = self.calibrator.add_frame(frame_bgr)
        except Exception as e:
            print(f'[标定] 采集帧出错：{e}')
            return
        n = self.calibrator.frame_count
        self.btn_calib_solve.setEnabled(n > 0)   # 有帧就能求解，不必先暂停采集
        tip = ('帧数已够，可点「求解并保存」' if n >= 10
               else '建议继续变换姿态，覆盖画面四角与倾斜')
        if ok:
            self.label_calib_info.setText(
                f'已采集 {n} 帧（当前帧检测到棋盘格 ✓）\n{tip}')
        else:
            self.label_calib_info.setText(
                f'已采集 {n} 帧（当前帧未检测到棋盘格）\n'
                f'请让棋盘格完整入画、光照均匀、避免反光')

    def update_monitor_data(self):
        # 更新坐标
        self.lcd_centroid_x.display(self.global_params.detection_x)
        self.lcd_centroid_y.display(self.global_params.detection_y)
        # 更新FPS
        self.lcd_fps.display(self.global_params.fps)
        self.lcd_reasoning.display(self.global_params.inference_fps)

    def update_camera_frame(self):
        if self.cap is None or not self.cap.isOpened():
            return

        ret, frame = self.cap.read()
        if not ret:
            return
        try:
            # 标定采集中：把当前帧喂给标定器，不改动显示逻辑。
            # ⚠️ 门条件必须是「采集中且标定器存在」，不能只看 calibrator 是否为 None：
            # 「停止采集」只把 _collecting 置回 False（帧全部保留），若这里不看这个标志，
            # 暂停后仍会持续接帧 —— 与按钮语义和文档不符，且会立刻覆盖掉
            # 「已暂停采集，已保留 N 帧」这句提示，用户又会以为帧丢了。
            if self.calibrator is not None and getattr(self, '_collecting', False):
                self._on_calib_frame(frame)

            # 录制：投入写盘队列（非阻塞，满则丢帧并计数）
            if self.recorder is not None:
                self.recorder.push_frame(frame)

            # 保留 RGB 副本供检测线程使用
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.current_frame = frame_rgb.copy()
            # 显示复用统一入口（实时与回放共用同一套绘制逻辑）
            self._display_frame(frame)
        except Exception as e:
            print(f"帧处理出错：{e}")

        #向检测器子线程发送帧数据
        if self.detector and self.detector_thread.isRunning() and not self.is_loading_model:
            self.frame_counter+=1
            if self.frame_counter % (self.inference_interval + 1) == 0:
                self.frame_signal.emit(frame_rgb.copy())

    def closeEvent(self, event):
        # 停止采集，避免关闭时还持有标定器
        self.calibrator = None
        self._collecting = False
        # 安装参数自标定的采样窗口：关窗时停掉定时器，避免回调打到已销毁的控件
        self._marking = False
        if self._mark_timer is not None and self._mark_timer.isActive():
            self._mark_timer.stop()
        # 求解线程可能正卡在 cv2.calibrateCamera（十几秒），**必须等它退出**，
        # 否则关窗时线程还在跑会崩。顺便断开信号：关窗口不该再弹标定结果。
        th = getattr(self, '_solve_thread', None)
        if th is not None and th.isRunning():
            try:
                th.solved.disconnect()
            except (RuntimeError, TypeError):
                pass
            print('[标定] 关闭时等待求解线程结束……')
            th.wait()
        # 设备枚举线程（兜底通路走 PowerShell，可能正卡在几秒的查询上）
        it = getattr(self, '_identify_thread', None)
        if it is not None and it.isRunning():
            try:
                it.identified.disconnect()
            except (RuntimeError, TypeError):
                pass
            it.wait(3000)
        # 模型加载线程同理（在子线程里建 ORT 会话）
        mt = getattr(self, 'model_thread', None)
        if mt is not None and mt.isRunning():
            mt.wait()
        # 录制中关闭：必须收尾落盘，否则数据轨丢失、视频文件损坏
        if self.recorder is not None:
            try:
                meta = self.recorder.stop()
                print(f'[录制] 关闭时收尾：{meta.frame_count} 帧，'
                      f'{meta.data_count} 条记录，丢帧 {meta.dropped_frames}')
            except Exception as e:
                print(f'[录制] 关闭收尾失败：{e}')
            self.recorder = None
        # 回放收尾
        if self.replay_timer is not None and self.replay_timer.isActive():
            self.replay_timer.stop()
        if self.replayer is not None:
            self.replayer.close()
            self.replayer = None
        # 停止所有定时器
        for timer in [self.update_timer, self.camera_timer, self.analysis_timer]:
            if timer.isActive():
                timer.stop()
        # 释放摄像头
        if self.cap is not None and self.cap.isOpened():
            self.cap.release()
        # 等待子线程结束
        if hasattr(self, 'camera_thread') and self.camera_thread.isRunning():
            self.camera_thread.quit()
            self.camera_thread.wait(1000)
        if hasattr(self, 'model_thread') and self.model_thread.isRunning():
            self.model_thread.quit()
            self.model_thread.wait(1000)
        event.accept()
            
if __name__=='__main__':
    app=QApplication(sys.argv)
    window=MainWindow()
    window.show()
    app.exec()