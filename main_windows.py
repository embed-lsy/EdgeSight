from PySide6.QtWidgets import QApplication,QPushButton,QBoxLayout,QWidget,QGroupBox,QLabel,QMessageBox,QFileDialog,QStatusBar
from PySide6.QtCore import Qt,Slot,QTimer,QThread,Signal,QObject
from PySide6.QtGui import QIcon,QPixmap,QImage
from ui.Ui_EdgeSightMain import Ui_Form
from core.config.windows_global_params import GlobalParams
from core.camera.opencv_camera import CameraInitThread
from core.detector import ModelInitThread, YOLODetector
from core.calibration import (CameraCalibrator, CameraIntrinsics,
                              GeometricRanger, RangingConfig, solve_intrinsics,
                              solve_mount_params)
from core.recorder import Recorder, Replayer, FrameRecord
from typing import Optional
from collections import deque
import sys
import cv2
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
        #相机标定：把已保存的内参加载进来，并刷新 UI 显示
        self.load_calibration()
        self.refresh_calib_widgets()
    
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
            try:
                if self.detector:
                    self.detector.detection_ready.disconnect(self.on_detection_ready)
            except:
                pass
            
            if hasattr(self,'detector_thread') and self.detector_thread.isRunning():
                self.detector_thread.quit()
                if not self.detector_thread.wait(5000):
                    self.detector_thread.terminate()#强制终止
                    self.detector_thread.wait()
            
            self.detector=None #去除旧对象

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
       
    def bind_other(self):
        self.tabWidget.currentChanged.connect(self.on_tab_change)

    # ------------------------------------------------------------------
    # 相机标定（CHARTER「范围内的」第 1 条）
    # ------------------------------------------------------------------
    def load_calibration(self):
        """从磁盘加载内参，并注入测距器。

        没有标定文件不是错误 —— 只是测距不可用。所以这里只记录原因，
        不阻塞启动。UI 上会明确显示"未标定"，而不是静默给一个假距离。
        """
        path = self.global_params.calib_path
        if not os.path.isabs(path):
            # 相对仓库根解析，避免工作目录变化导致找不到
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
        self._calib_file = path

        intr = CameraCalibrator.load(path)
        if intr is None:
            self.global_params.intrinsics = None
            self.global_params.calibrated = False
            self.global_params.invalid_reason = '未找到标定文件'
            return

        self.global_params.intrinsics = intr
        self.global_params.calibrated = intr.is_valid()
        if intr.is_valid():
            self.global_params.invalid_reason = ''
            self.ranger.update_intrinsics(intr)
            self.status_bar.showMessage(
                f'已加载相机内参 fx={intr.fx:.1f} fy={intr.fy:.1f} '
                f'重投影误差={intr.rms_error:.3f}px', 5000)
            print(f'[标定] 加载 {path}  fx={intr.fx:.2f} fy={intr.fy:.2f} '
                  f'rms={intr.rms_error:.4f} size={intr.image_size}')
        else:
            self.global_params.invalid_reason = '标定文件内容无效'

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

        # 求解成功后立即生效，不必重启
        self.global_params.intrinsics = intr
        self.global_params.calibrated = intr.is_valid()
        self.global_params.invalid_reason = ''
        self.ranger.update_intrinsics(intr)
        self.calibrator = None            # 成功后清空：下次「开始采集」是全新一轮
        self._set_collecting(False)
        self.refresh_calib_widgets()

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
                  f'重投影误差={intr.rms_error:.3f} px')

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

    @Slot()
    def on_camera_height_changed(self, value):
        """相机安装高度改了立即重建测距配置 —— 不需要重标定。

        这是地面接触点法（CHARTER 第 2 条）唯一的安装参数：卷尺量一次镜头中心
        到地面的高度。填 0 视为「未测量」，此时接触点法与反解判据都不可用，
        部分可见的目标会明确显示「不可测」，而不是按某个默认身高硬算。
        """
        self.global_params.camera_height = float(value)
        self.ranger.update_config(RangingConfig.from_params(self.global_params))
        self.label_distance_value.setToolTip(self._ranging_tooltip())

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
        self.label_distance_value.setToolTip(self._ranging_tooltip())

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
            f'已保存：{self.recorder.session_dir if self.recorder else ""}\n'
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

    def _recordings_dir(self) -> str:
        """录制根目录固定在仓库下 recordings/（已在 .gitignore 中）。"""
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'recordings')
        os.makedirs(root, exist_ok=True)
        return root

    @Slot()
    def on_play_pick(self):
        """选择一次录制。优先弹目录选择，列出 recordings 下已存在的会话。"""
        root = self._recordings_dir()
        sessions = Replayer.list_sessions(root)
        if not sessions:
            QMessageBox.information(self, '没有录制',
                                    f'{root} 下没有找到录制（需含 video.avi）。')
            return
        d = QFileDialog.getExistingDirectory(
            self, '选择录制目录', sessions[-1],
            QFileDialog.Option.ShowDirsOnly)
        if not d:
            return
        try:
            self.replayer = Replayer(d)
        except Exception as e:
            QMessageBox.critical(self, '加载失败', f'无法读取录制：{e}')
            self.replayer = None
            return

        if not self.replayer.open():
            QMessageBox.critical(self, '加载失败', 'video.avi 无法打开。')
            self.replayer = None
            return

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
        self.status_bar.showMessage(f'已加载录制：{self.replayer.meta.session}', 3000)

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
        self.label_distance_value.setToolTip(self._ranging_tooltip(res))

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