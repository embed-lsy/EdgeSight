class GlobalParams:
    def __init__(self):
        #运动时数据
        self.detection_x=320
        self.detection_y=240
        self.detection_width=0
        self.detection_height=0
        self.detection_conf=0.0
        self.detection_class=-1
        self.fps=30          #摄像头帧率
        self.inference_fps=0 #模型推理FPS
        #检测配置
        self.sample_freq=30  #数据采样频率，单位Hz
        self.base_width=100 #目标基准宽度
        self.confidence_thres=0.25
        self.nms_thres=0.45
        self.target_select_rule=0
        self.specific_class='笔记本电脑'
        self.specific_class_id=-1
        self.plot_enable=False
        #AI模型配置
        self.mode_path=''
        self.label_path=''
        self.hardware_accel='CPU'
        #推理结果
        self.credibility=0.0
        self.target_category='未知'