from PySide6.QtWidgets import QApplication,QPushButton,QBoxLayout,QWidget,QGroupBox,QLabel,QMessageBox,QFileDialog,QStatusBar
from PySide6.QtCore import Qt,Slot,QTimer,QThread,Signal,QObject
from PySide6.QtGui import QIcon,QPixmap,QImage
from ui.Ui_VisServoControl import Ui_Form
from core.config.raspberry_global_params import GlobalParams
from core.camera.opencv_camera import CameraInitThread
from core.detector import ModelInitThread, YOLODetector
from typing import Optional
from collections import deque
from core.detector.ncnn_detector import NCNNDetector
import sys
import cv2
import numpy as np
import pyqtgraph as pg
import os
import time
import platform

class MainWindow(QWidget, Ui_Form):
    frame_signal = Signal(np.ndarray)  # 定义类属性
    def __init__(self):
        super(MainWindow, self).__init__()
        self.setupUi(self)
        self.setWindowTitle('AI边缘视角伺服控制系统')
        # 初始化核心组件
        self.camera_index = 0
        self.cap = None
        self.detector = None
        self.labels = []
        self.global_params = GlobalParams()  # 必须在init_camera前初始化
        self.frame_counter = 0
        self.inference_interval = 2  # 推理间隔
        self.last_detection=None
        self.is_loading_model=False
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

        self.status_bar.showMessage("正在初始化AI模型...")
        self.model_thread = ModelInitThread(self.global_params.mode_path,self.global_params.hardware_accel)
        self.model_thread.init_finished.connect(self.on_model_init_finished)
        self.model_thread.start()

    def on_model_init_finished(self,success,message,model=None):#模型加载完成回调
        print("检测线程启动状态：", self.detector_thread.isRunning())
        if success and self.global_params.mode_path:
            model_path=self.global_params.mode_path
            model_path_lower=self.global_params.mode_path.lower()

            if model_path.endswith('.param'):# NCNN模型
                if 'v5' in model_path_lower or 'yolov5' in model_path_lower:
                    model_type='v5'
                elif 'v8' in model_path_lower or 'yolov8' in model_path_lower:
                    model_type='v8'
                else:
                    model_type='v5'#默认v5

                bin_path=model_path.replace('.param','.bin')
                self.detector=NCNNDetector(
                    self.global_params.mode_path,
                    bin_path,
                    self.global_params.label_path,
                    self.global_params,
                    self.global_params.confidence_thres,
                    self.global_params.nms_thres,
                    model_type=model_type
                )
            else:# ONNX模型
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
        for plt in [self.plot_sensor, self.plot_error, self.plot_control]:
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
        # 更新提示
        if len(self.sensor_history_x) > 0:
            last_x=self.sensor_history_x[-1]
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
        self.tabWidget.currentChanged.connect(self.on_tab_change)

    def bind_model_thres_widgets_realtime(self):#更新标签与值
        self.slider_confidence_thres.valueChanged.connect(lambda v: self.update_param_realtime("confidence_thres", v/100, self.label_confidence_thres, "%.1f"))
        self.slider_nms_thres.valueChanged.connect(lambda v: self.update_param_realtime("nms_thres", v/100, self.label_nms_thres, "%.1f"))

    def bind_calibration_widgets(self):#仅标定时生效
        self.slider_sample_freq.valueChanged.connect(lambda v:self.label_sample_freq.setText(f'{v}Hz'))
        self.slider_base_width.valueChanged.connect(lambda v:self.label_base_width.setText(f'{v}px'))
       
    def bind_other(self):
        self.tabWidget.currentChanged.connect(self.on_tab_change)

    def update_param_realtime(self,param_name,value,label,fmt):
        setattr(self.global_params,param_name,value)
        label.setText(fmt % value)
        
     
    #界面交互
    @Slot(int)
    def on_tab_change(self,index):
        tab_name=['监控','深度分析','设置']
        currebt_tab=tab_name[index]
        print(f"当前选项卡：{currebt_tab}")
        if currebt_tab=='深度分析':
            self.init_analysis_plots()
            if not self.analysis_timer.isActive():
                self.analysis_timer.start()
        elif currebt_tab=='设置':
            self.label__calibrate_status.setText('未标定')
        elif self.analysis_timer.isActive() and currebt_tab!='深度分析' and self.global_params.plot_enable:
            self.analysis_timer.stop()     
                
    @Slot()
    def on_calibrate_clicked(self):
        if not self.cap or not self.cap.isOpened():
            QMessageBox.warning(self, "标定错误", "摄像头未连接，无法进行标定！")
            return
        
        
        self.label__calibrate_status.setText("标定中……")
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
            QTimer.singleShot(2000,self.finish_calibration)
        except Exception as e:
            self.global_params.calibrated=False
            self.label__calibrate_status.setText('未标定')
            QMessageBox.critical(self,'标定失败',f'标定过程出错：{str(e)}')
            self.QPuahButton_calibrate_status.setEnabled(True)
    
    def finish_calibration(self):#不阻塞主线程
        self.global_params.calibrated = True
        self.label__calibrate_status.setText('已标定')
        QMessageBox.information(self,'标定完成','所有参数已更新并生效')
        self.QPuahButton_calibrate_status.setEnabled(True)

    @Slot()        
    def on_model_browse(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择AI模型文件", "", "模型文件 (*.onnx *.tflite *.engine *.param *.bin);;所有文件 (*.*)")
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
        
        if self.global_params.plot_enable:
            if self.global_params.base_width is not None and self.global_params.detection_width > 0:
                distance=self.global_params.base_width / self.global_params.detection_width 
            else:
                distance=0.0
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
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.current_frame = frame_rgb.copy()
            # 显示原始图像
            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w
            qt_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            self.lbl_original.setPixmap(QPixmap.fromImage(qt_img).scaled(self.lbl_original.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
            # 绘制检测结果到处理图像
            draw_img = frame_rgb.copy()  # 复制一份用于绘制
            if hasattr(self, 'last_detection') and self.last_detection and self.last_detection['confidence'] >= 0.3:
                target = self.last_detection
                x, y = target['x'], target['y']
                w_box, h_box = target.get('width', 40), target.get('height', 40)
                conf = target['confidence']
                class_id = target['class_id']
                
                # 获取类别名
                if self.detector and hasattr(self.detector, 'labels') and self.detector.labels:
                    if class_id < len(self.detector.labels):
                        label = f"{self.detector.labels[class_id]} {conf:.2f}"
                    else:
                        label = f"未知 {conf:.2f}"
                else:
                    label = f"未知 {conf:.2f}"
                
                # 绘制矩形框
                top_left = (int(x - w_box/2), int(y - h_box/2))
                bottom_right = (int(x + w_box/2), int(y + h_box/2))
                cv2.rectangle(draw_img, top_left, bottom_right, (0, 255, 0), 2)
                
                # 绘制标签背景
                label_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(draw_img,
                            (top_left[0], top_left[1] - label_size[1] - 5),
                            (top_left[0] + label_size[0], top_left[1]),
                            (0, 255, 0), -1)
                # 绘制文字
                cv2.putText(draw_img, label,(top_left[0], top_left[1] - 5),cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
            else:
                cv2.putText(draw_img, 'No Target',(10, 30), cv2.FONT_HERSHEY_SIMPLEX,0.7, (0, 0, 255), 2)
                self.label_target_category.setText('未知')
            
            # 显示处理图像
            h2, w2, ch2 = draw_img.shape
            bytes_per_line2 = ch2 * w2
            qt_img2 = QImage(draw_img.data, w2, h2, bytes_per_line2, QImage.Format_RGB888)
            self.lbl_process.setPixmap(QPixmap.fromImage(qt_img2).scaled(self.lbl_process.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            print(f"帧处理出错：{e}")

        #向检测器子线程发送帧数据
        if self.detector and self.detector_thread.isRunning() and not self.is_loading_model:
            self.frame_counter+=1
            if self.frame_counter % (self.inference_interval + 1) == 0:
                self.frame_signal.emit(frame_rgb.copy())

    def closeEvent(self, event):
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