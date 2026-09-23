# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'EdgeSightMain.ui'
##
## Created by: Qt User Interface Compiler version 6.10.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFrame, QGroupBox, QHBoxLayout, QLCDNumber,
    QLabel, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSlider, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget)

from pyqtgraph import PlotWidget

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(1024, 695)
        Form.setMinimumSize(QSize(1024, 600))
        Form.setStyleSheet(u"QWidget {\n"
"    /* \u539f\u6709\u7b80\u7ea6\u9752\u7070\u6e10\u53d8\u80cc\u666f\uff0c\u4fdd\u6301\u4e0d\u53d8 */\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a4050, stop:1 #2f3446);\n"
"    color: #e0e8f0;\n"
"    font-family: \"Microsoft YaHei UI\";\n"
"    font-size: 14px;\n"
"}\n"
"\n"
"/* ========== QTabWidget \u6837\u5f0f\uff08\u4fdd\u6301\u4e0d\u53d8\uff09 ========== */\n"
"QTabWidget {\n"
"    border: none; /* \u53bb\u6389\u9ed8\u8ba4\u8fb9\u6846\uff0c\u7b80\u7ea6 */\n"
"}\n"
"QTabBar {\n"
"    background: #2f3446; /* \u548c\u4e3b\u80cc\u666f\u5e95\u5c42\u7edf\u4e00 */\n"
"}\n"
"QTabBar::tab {\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #373c4e, stop:1 #2f3446);\n"
"    color: #e0e8f0;\n"
"    padding: 8px 20px; /* \u5185\u8fb9\u8ddd\u9002\u4e2d\uff0c\u9ad8\u7ea7\u611f */\n"
"    margin-right: 2px; /* \u6807\u7b7e\u95f4\u5fae\u5c0f\u95f4\u8ddd\uff0c\u4e0d\u62e5\u6324 */\n"
"    border-top-left-radius: 6px;\n"
"    border-top-right-radius: 6px;\n"
"    bor"
                        "der: none;\n"
"}\n"
"QTabBar::tab:selected {\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4299e120, stop:1 #3182ce15); /* \u4f4e\u9971\u548c\u84dd\u6e10\u53d8\uff0c\u4e0d\u7a81\u5140 */\n"
"    color: #a7c0ff; /* \u6d45\u84dd\u6587\u5b57\uff0c\u7a81\u51fa\u9009\u4e2d\u6001 */\n"
"    border-bottom: 2px solid #4299e1; /* \u5e95\u90e8\u7ec6\u84dd\u7ebf\uff0c\u7b80\u7ea6\u9ad8\u7ea7 */\n"
"}\n"
"QTabBar::tab:hover:!selected {\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #41485c, stop:1 #373c4e);\n"
"}\n"
"QTabWidget::pane {\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a4050, stop:1 #2f3446); /* \u548c\u4e3b\u80cc\u666f\u7edf\u4e00 */\n"
"    border: 1px solid #4a5568; /* \u7ec6\u8fb9\u6846\uff0c\u589e\u5f3a\u5c42\u6b21\u611f */\n"
"    border-radius: 6px;\n"
"    margin-top: -2px; /* \u8d34\u5408\u9009\u4e2d\u6807\u7b7e\u7684\u5e95\u90e8\u84dd\u7ebf\uff0c\u65e0\u95f4\u9699 */\n"
"}\n"
"\n"
"/* ========== \u6838\u5fc3\u4fee\u6539\uff1aQScrollArea"
                        " \u6eda\u52a8\u6761\uff08\u9002\u914d\u89e6\u6478\u5c4f\uff09 ========== */\n"
"QScrollArea {\n"
"    border: none; /* \u53bb\u6389\u9ed8\u8ba4\u8fb9\u6846\uff0c\u7b80\u7ea6 */\n"
"}\n"
"QScrollArea > QWidget > QWidget {\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a4050, stop:1 #2f3446); /* \u548c\u4e3b\u80cc\u666f\u7edf\u4e00 */\n"
"}\n"
"/* \u5782\u76f4\u6eda\u52a8\u6761\uff08\u89e6\u6478\u5c4f\u9002\u914d\uff1a\u5bbd\u5ea6\u4ece12px\u219224px\uff0c\u66f4\u6613\u89e6\u78b0\uff09 */\n"
"QScrollBar:vertical {\n"
"    width: 24px; /* \u5173\u952e\uff1a\u589e\u5927\u6eda\u52a8\u6761\u5bbd\u5ea6\uff0c\u9002\u914d\u89e6\u6478\u5c4f */\n"
"    background: #2f3446; /* \u548c\u80cc\u666f\u5e95\u5c42\u7edf\u4e00 */\n"
"    border-radius: 12px; /* \u5706\u89d2\u968f\u5bbd\u5ea6\u540c\u6b65\u589e\u5927\uff0c\u4fdd\u6301\u6bd4\u4f8b */\n"
"    margin: 0px 4px 0px 4px; /* \u5fae\u5c0f\u8fb9\u8ddd\uff0c\u4e0d\u8d34\u8fb9 */\n"
"}\n"
"/* \u5782\u76f4\u6eda\u52a8\u6761\u6ed1\u5757\uff08\u5173\u952e\uff1a"
                        "\u589e\u5927\u5c3a\u5bf8\uff0c\u6700\u5c0f\u9ad8\u5ea6\u4ece20px\u219240px\uff09 */\n"
"QScrollBar::handle:vertical {\n"
"    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4a5568, stop:1 #3a4050); /* \u9752\u7070\u6e10\u53d8\u4e0d\u53d8 */\n"
"    border-radius: 10px; /* \u6ed1\u5757\u5706\u89d2\u7a0d\u5c0f\u4e8e\u6eda\u52a8\u6761\uff0c\u66f4\u7cbe\u81f4 */\n"
"    min-height: 40px; /* \u5173\u952e\uff1a\u589e\u5927\u6ed1\u5757\u6700\u5c0f\u9ad8\u5ea6\uff0c\u89e6\u6478\u5c4f\u6613\u70b9\u51fb */\n"
"    margin: 4px 2px 4px 2px; /* \u6ed1\u5757\u548c\u6eda\u52a8\u6761\u95f4\u7559\u7a7a\u9699\uff0c\u66f4\u6613\u8bc6\u522b */\n"
"}\n"
"/* \u6eda\u52a8\u6761\u6ed1\u5757\u60ac\u505c */\n"
"QScrollBar::handle:vertical:hover {\n"
"    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #546078, stop:1 #4a5568);\n"
"}\n"
"/* \u9690\u85cf\u6eda\u52a8\u6761\u4e0a\u4e0b\u7bad\u5934\uff08\u4fdd\u6301\u7b80\u7ea6\uff09 */\n"
"QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {\n"
"    height"
                        ": 0px;\n"
"}\n"
"/* \u6c34\u5e73\u6eda\u52a8\u6761\uff08\u89e6\u6478\u5c4f\u9002\u914d\uff1a\u9ad8\u5ea6\u4ece12px\u219224px\uff09 */\n"
"QScrollBar:horizontal {\n"
"    height: 24px; /* \u5173\u952e\uff1a\u589e\u5927\u6c34\u5e73\u6eda\u52a8\u6761\u9ad8\u5ea6 */\n"
"    background: #2f3446;\n"
"    border-radius: 12px;\n"
"    margin: 4px 0px 4px 0px;\n"
"}\n"
"QScrollBar::handle:horizontal {\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4a5568, stop:1 #3a4050);\n"
"    border-radius: 10px;\n"
"    min-width: 40px; /* \u5173\u952e\uff1a\u589e\u5927\u6c34\u5e73\u6ed1\u5757\u6700\u5c0f\u5bbd\u5ea6 */\n"
"    margin: 2px 4px 2px 4px;\n"
"}\n"
"QScrollBar::sub-line:horizontal, QScrollBar::add-line:horizontal {\n"
"    width: 0px;\n"
"}\n"
"\n"
"/* RadioButton \u6837\u5f0f\uff08\u4fdd\u6301\u4e0d\u53d8\uff09 */\n"
"QRadioButton {\n"
"    color: #e0e8f0; /* \u6587\u5b57\u8272\u548c\u6574\u4f53\u7edf\u4e00 */\n"
"    font-family: \"Microsoft YaHei UI\";\n"
"    font-size: 14px;\n"
"}\n"
"QRadioB"
                        "utton::indicator {\n"
"    width: 14px;\n"
"    height: 14px;\n"
"    border-radius: 7px; /* \u5706\u5f62 */\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #373c4e, stop:1 #2f3446); /* \u548c\u80cc\u666f\u547c\u5e94 */\n"
"    border: 1px solid #4a5568; /* \u7ec6\u8fb9\u6846\uff0c\u4fdd\u6301\u9ad8\u7ea7\u611f */\n"
"}\n"
"QRadioButton::indicator:checked {\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4299e1, stop:1 #3182ce); /* \u9ad8\u7ea7\u84dd\u6e10\u53d8\uff0c\u4e0d\u523a\u773c */\n"
"    border: 1px solid #58a6ff; /* \u6d45\u84dd\u8fb9\u6846\uff0c\u589e\u5f3a\u5c42\u6b21\u611f */\n"
"}\n"
"QRadioButton::indicator:hover {\n"
"    border-color: #66b2ff;\n"
"}\n"
"\n"
"/* \u6309\u94ae\u3001\u8f93\u5165\u6846\u6837\u5f0f\uff08\u4fdd\u6301\u4e0d\u53d8\uff09 */\n"
"QPushButton {\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #41485c, stop:1 #373c4e);\n"
"    border: 1px solid #4a5568;\n"
"    border-radius: 6px;\n"
"    padding: 6px 12px;\n"
"    co"
                        "lor: #e0e8f0;\n"
"    font-family: \"Microsoft YaHei UI\";\n"
"    font-size: 14px;\n"
"}\n"
"QPushButton:hover {\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4a5568, stop:1 #41485c);\n"
"    border-color: #546078;\n"
"}\n"
"\n"
"QLineEdit, QTextEdit {\n"
"    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #363b4b, stop:1 #2f3446);\n"
"    border: 1px solid #444c5f;\n"
"    border-radius: 4px;\n"
"    padding: 4px;\n"
"    color: #e0e8f0;\n"
"    font-family: \"Microsoft YaHei UI\";\n"
"    font-size: 14px;\n"
"}")
        self.verticalLayout_10 = QVBoxLayout(Form)
        self.verticalLayout_10.setObjectName(u"verticalLayout_10")
        self.tabWidget = QTabWidget(Form)
        self.tabWidget.setObjectName(u"tabWidget")
        self.tabWidget.setMinimumSize(QSize(0, 0))
        self.tab_monitor = QWidget()
        self.tab_monitor.setObjectName(u"tab_monitor")
        self.horizontalLayout_7 = QHBoxLayout(self.tab_monitor)
        self.horizontalLayout_7.setObjectName(u"horizontalLayout_7")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.frame = QFrame(self.tab_monitor)
        self.frame.setObjectName(u"frame")
        self.frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.frame.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_13 = QVBoxLayout(self.frame)
        self.verticalLayout_13.setObjectName(u"verticalLayout_13")
        self.groupBox_5 = QGroupBox(self.frame)
        self.groupBox_5.setObjectName(u"groupBox_5")
        self.groupBox_5.setMinimumSize(QSize(100, 0))
        self.verticalLayout_3 = QVBoxLayout(self.groupBox_5)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.lbl_original = QLabel(self.groupBox_5)
        self.lbl_original.setObjectName(u"lbl_original")
        self.lbl_original.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout_3.addWidget(self.lbl_original)


        self.verticalLayout_13.addWidget(self.groupBox_5)

        self.groupBox_6 = QGroupBox(self.frame)
        self.groupBox_6.setObjectName(u"groupBox_6")
        self.verticalLayout = QVBoxLayout(self.groupBox_6)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.lbl_process = QLabel(self.groupBox_6)
        self.lbl_process.setObjectName(u"lbl_process")
        self.lbl_process.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout.addWidget(self.lbl_process)


        self.verticalLayout_13.addWidget(self.groupBox_6)


        self.horizontalLayout.addWidget(self.frame)

        self.frame_4 = QFrame(self.tab_monitor)
        self.frame_4.setObjectName(u"frame_4")
        self.frame_4.setFrameShape(QFrame.Shape.StyledPanel)
        self.frame_4.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_2 = QVBoxLayout(self.frame_4)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.frame_5 = QFrame(self.frame_4)
        self.frame_5.setObjectName(u"frame_5")
        self.frame_5.setFrameShape(QFrame.Shape.StyledPanel)
        self.frame_5.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_4 = QVBoxLayout(self.frame_5)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.groupBox_targetpos = QGroupBox(self.frame_5)
        self.groupBox_targetpos.setObjectName(u"groupBox_targetpos")
        self.groupBox_targetpos.setMinimumSize(QSize(0, 100))
        self.verticalLayout_5 = QVBoxLayout(self.groupBox_targetpos)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.label = QLabel(self.groupBox_targetpos)
        self.label.setObjectName(u"label")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_2.addWidget(self.label)

        self.lcd_centroid_x = QLCDNumber(self.groupBox_targetpos)
        self.lcd_centroid_x.setObjectName(u"lcd_centroid_x")

        self.horizontalLayout_2.addWidget(self.lcd_centroid_x)

        self.label_2 = QLabel(self.groupBox_targetpos)
        self.label_2.setObjectName(u"label_2")
        self.label_2.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_2.addWidget(self.label_2)

        self.lcd_centroid_y = QLCDNumber(self.groupBox_targetpos)
        self.lcd_centroid_y.setObjectName(u"lcd_centroid_y")

        self.horizontalLayout_2.addWidget(self.lcd_centroid_y)


        self.verticalLayout_5.addLayout(self.horizontalLayout_2)

        self.horizontalLayout_22 = QHBoxLayout()
        self.horizontalLayout_22.setObjectName(u"horizontalLayout_22")
        self.horizontalLayout_20 = QHBoxLayout()
        self.horizontalLayout_20.setObjectName(u"horizontalLayout_20")
        self.label_17 = QLabel(self.groupBox_targetpos)
        self.label_17.setObjectName(u"label_17")
        self.label_17.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_20.addWidget(self.label_17)

        self.lcd_credibility = QLCDNumber(self.groupBox_targetpos)
        self.lcd_credibility.setObjectName(u"lcd_credibility")
        self.lcd_credibility.setProperty(u"value", 0.000000000000000)

        self.horizontalLayout_20.addWidget(self.lcd_credibility)


        self.horizontalLayout_22.addLayout(self.horizontalLayout_20)

        self.horizontalLayout_21 = QHBoxLayout()
        self.horizontalLayout_21.setObjectName(u"horizontalLayout_21")
        self.label_19 = QLabel(self.groupBox_targetpos)
        self.label_19.setObjectName(u"label_19")
        self.label_19.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_21.addWidget(self.label_19)

        self.label_target_category = QLabel(self.groupBox_targetpos)
        self.label_target_category.setObjectName(u"label_target_category")
        self.label_target_category.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_21.addWidget(self.label_target_category)


        self.horizontalLayout_22.addLayout(self.horizontalLayout_21)


        self.verticalLayout_5.addLayout(self.horizontalLayout_22)

        self.horizontalLayout_distance = QHBoxLayout()
        self.horizontalLayout_distance.setObjectName(u"horizontalLayout_distance")
        self.label_distance_title = QLabel(self.groupBox_targetpos)
        self.label_distance_title.setObjectName(u"label_distance_title")
        self.label_distance_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_distance.addWidget(self.label_distance_title)

        self.label_distance_value = QLabel(self.groupBox_targetpos)
        self.label_distance_value.setObjectName(u"label_distance_value")
        self.label_distance_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_distance_value.setStyleSheet(u"font-weight: bold; font-size: 14pt;")

        self.horizontalLayout_distance.addWidget(self.label_distance_value)


        self.verticalLayout_5.addLayout(self.horizontalLayout_distance)


        self.verticalLayout_4.addWidget(self.groupBox_targetpos)

        self.groupBox_10 = QGroupBox(self.frame_5)
        self.groupBox_10.setObjectName(u"groupBox_10")
        self.verticalLayout_6 = QVBoxLayout(self.groupBox_10)
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.label_23 = QLabel(self.groupBox_10)
        self.label_23.setObjectName(u"label_23")

        self.horizontalLayout_3.addWidget(self.label_23)

        self.slider_confidence_thres = QSlider(self.groupBox_10)
        self.slider_confidence_thres.setObjectName(u"slider_confidence_thres")
        self.slider_confidence_thres.setMinimum(10)
        self.slider_confidence_thres.setMaximum(90)
        self.slider_confidence_thres.setPageStep(1)
        self.slider_confidence_thres.setValue(50)
        self.slider_confidence_thres.setOrientation(Qt.Orientation.Horizontal)

        self.horizontalLayout_3.addWidget(self.slider_confidence_thres)

        self.label_confidence_thres = QLabel(self.groupBox_10)
        self.label_confidence_thres.setObjectName(u"label_confidence_thres")

        self.horizontalLayout_3.addWidget(self.label_confidence_thres)


        self.verticalLayout_6.addLayout(self.horizontalLayout_3)

        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.label_25 = QLabel(self.groupBox_10)
        self.label_25.setObjectName(u"label_25")

        self.horizontalLayout_4.addWidget(self.label_25)

        self.slider_nms_thres = QSlider(self.groupBox_10)
        self.slider_nms_thres.setObjectName(u"slider_nms_thres")
        self.slider_nms_thres.setMinimumSize(QSize(0, 0))
        self.slider_nms_thres.setMinimum(30)
        self.slider_nms_thres.setMaximum(70)
        self.slider_nms_thres.setPageStep(1)
        self.slider_nms_thres.setValue(45)
        self.slider_nms_thres.setSliderPosition(45)
        self.slider_nms_thres.setOrientation(Qt.Orientation.Horizontal)

        self.horizontalLayout_4.addWidget(self.slider_nms_thres)

        self.label_nms_thres = QLabel(self.groupBox_10)
        self.label_nms_thres.setObjectName(u"label_nms_thres")

        self.horizontalLayout_4.addWidget(self.label_nms_thres)


        self.verticalLayout_6.addLayout(self.horizontalLayout_4)


        self.verticalLayout_4.addWidget(self.groupBox_10)

        self.groupBox_4 = QGroupBox(self.frame_5)
        self.groupBox_4.setObjectName(u"groupBox_4")
        self.verticalLayout_8 = QVBoxLayout(self.groupBox_4)
        self.verticalLayout_8.setObjectName(u"verticalLayout_8")
        self.horizontalLayout_23 = QHBoxLayout()
        self.horizontalLayout_23.setObjectName(u"horizontalLayout_23")
        self.label_21 = QLabel(self.groupBox_4)
        self.label_21.setObjectName(u"label_21")
        self.label_21.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_23.addWidget(self.label_21)

        self.lcd_reasoning = QLCDNumber(self.groupBox_4)
        self.lcd_reasoning.setObjectName(u"lcd_reasoning")

        self.horizontalLayout_23.addWidget(self.lcd_reasoning)


        self.verticalLayout_8.addLayout(self.horizontalLayout_23)

        self.horizontalLayout_6 = QHBoxLayout()
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.label_9 = QLabel(self.groupBox_4)
        self.label_9.setObjectName(u"label_9")
        self.label_9.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_6.addWidget(self.label_9)

        self.lcd_fps = QLCDNumber(self.groupBox_4)
        self.lcd_fps.setObjectName(u"lcd_fps")

        self.horizontalLayout_6.addWidget(self.lcd_fps)


        self.verticalLayout_8.addLayout(self.horizontalLayout_6)


        self.verticalLayout_4.addWidget(self.groupBox_4)


        self.verticalLayout_2.addWidget(self.frame_5)


        self.horizontalLayout.addWidget(self.frame_4)

        self.horizontalLayout.setStretch(0, 5)
        self.horizontalLayout.setStretch(1, 5)

        self.horizontalLayout_7.addLayout(self.horizontalLayout)

        self.tabWidget.addTab(self.tab_monitor, "")
        self.tab_analysis = QWidget()
        self.tab_analysis.setObjectName(u"tab_analysis")
        self.verticalLayout_12 = QVBoxLayout(self.tab_analysis)
        self.verticalLayout_12.setObjectName(u"verticalLayout_12")
        self.frame_2 = QFrame(self.tab_analysis)
        self.frame_2.setObjectName(u"frame_2")
        self.frame_2.setFrameShape(QFrame.Shape.StyledPanel)
        self.frame_2.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_18 = QVBoxLayout(self.frame_2)
        self.verticalLayout_18.setObjectName(u"verticalLayout_18")
        self.verticalLayout_11 = QVBoxLayout()
        self.verticalLayout_11.setObjectName(u"verticalLayout_11")
        self.horizontalLayout_8 = QHBoxLayout()
        self.horizontalLayout_8.setObjectName(u"horizontalLayout_8")
        self.groupBox_7 = QGroupBox(self.frame_2)
        self.groupBox_7.setObjectName(u"groupBox_7")
        self.verticalLayout_16 = QVBoxLayout(self.groupBox_7)
        self.verticalLayout_16.setObjectName(u"verticalLayout_16")
        self.verticalLayout_15 = QVBoxLayout()
        self.verticalLayout_15.setObjectName(u"verticalLayout_15")
        self.plot_sensor_center = PlotWidget(self.groupBox_7)
        self.plot_sensor_center.setObjectName(u"plot_sensor_center")
        font = QFont()
        font.setFamilies([u"Microsoft YaHei UI"])
        font.setStyleStrategy(QFont.NoAntialias)
        self.plot_sensor_center.setFont(font)

        self.verticalLayout_15.addWidget(self.plot_sensor_center)

        self.horizontalLayout_15 = QHBoxLayout()
        self.horizontalLayout_15.setObjectName(u"horizontalLayout_15")
        self.label_5 = QLabel(self.groupBox_7)
        self.label_5.setObjectName(u"label_5")
        self.label_5.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_15.addWidget(self.label_5)

        self.label_prompt = QLabel(self.groupBox_7)
        self.label_prompt.setObjectName(u"label_prompt")
        self.label_prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_15.addWidget(self.label_prompt)

        self.horizontalLayout_15.setStretch(0, 2)
        self.horizontalLayout_15.setStretch(1, 8)

        self.verticalLayout_15.addLayout(self.horizontalLayout_15)

        self.verticalLayout_15.setStretch(0, 8)
        self.verticalLayout_15.setStretch(1, 2)

        self.verticalLayout_16.addLayout(self.verticalLayout_15)


        self.horizontalLayout_8.addWidget(self.groupBox_7)

        self.groupBox_8 = QGroupBox(self.frame_2)
        self.groupBox_8.setObjectName(u"groupBox_8")
        self.horizontalLayout_5 = QHBoxLayout(self.groupBox_8)
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.plot_sensor_shap = PlotWidget(self.groupBox_8)
        self.plot_sensor_shap.setObjectName(u"plot_sensor_shap")

        self.horizontalLayout_5.addWidget(self.plot_sensor_shap)

        self.plot_target_distance = PlotWidget(self.groupBox_8)
        self.plot_target_distance.setObjectName(u"plot_target_distance")

        self.horizontalLayout_5.addWidget(self.plot_target_distance)


        self.horizontalLayout_8.addWidget(self.groupBox_8)

        self.horizontalLayout_8.setStretch(0, 4)
        self.horizontalLayout_8.setStretch(1, 6)

        self.verticalLayout_11.addLayout(self.horizontalLayout_8)

        self.horizontalLayout_9 = QHBoxLayout()
        self.horizontalLayout_9.setObjectName(u"horizontalLayout_9")
        self.groupBox_9 = QGroupBox(self.frame_2)
        self.groupBox_9.setObjectName(u"groupBox_9")
        self.verticalLayout_19 = QVBoxLayout(self.groupBox_9)
        self.verticalLayout_19.setObjectName(u"verticalLayout_19")
        self.verticalLayout_17 = QVBoxLayout()
        self.verticalLayout_17.setObjectName(u"verticalLayout_17")
        self.plot_sensor_conf = PlotWidget(self.groupBox_9)
        self.plot_sensor_conf.setObjectName(u"plot_sensor_conf")

        self.verticalLayout_17.addWidget(self.plot_sensor_conf)

        self.horizontalLayout_16 = QHBoxLayout()
        self.horizontalLayout_16.setObjectName(u"horizontalLayout_16")
        self.label_6 = QLabel(self.groupBox_9)
        self.label_6.setObjectName(u"label_6")
        self.label_6.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_16.addWidget(self.label_6)

        self.label_conf = QLabel(self.groupBox_9)
        self.label_conf.setObjectName(u"label_conf")
        self.label_conf.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_16.addWidget(self.label_conf)

        self.horizontalLayout_16.setStretch(0, 2)
        self.horizontalLayout_16.setStretch(1, 8)

        self.verticalLayout_17.addLayout(self.horizontalLayout_16)

        self.verticalLayout_17.setStretch(0, 8)
        self.verticalLayout_17.setStretch(1, 2)

        self.verticalLayout_19.addLayout(self.verticalLayout_17)


        self.horizontalLayout_9.addWidget(self.groupBox_9)

        self.groupBox_13 = QGroupBox(self.frame_2)
        self.groupBox_13.setObjectName(u"groupBox_13")
        self.verticalLayout_14 = QVBoxLayout(self.groupBox_13)
        self.verticalLayout_14.setObjectName(u"verticalLayout_14")
        self.horizontalLayout_14 = QHBoxLayout()
        self.horizontalLayout_14.setObjectName(u"horizontalLayout_14")
        self.plot_sensor_fps = PlotWidget(self.groupBox_13)
        self.plot_sensor_fps.setObjectName(u"plot_sensor_fps")

        self.horizontalLayout_14.addWidget(self.plot_sensor_fps)

        self.verticalLayout_9 = QVBoxLayout()
        self.verticalLayout_9.setObjectName(u"verticalLayout_9")
        self.horizontalLayout_10 = QHBoxLayout()
        self.horizontalLayout_10.setObjectName(u"horizontalLayout_10")
        self.label_3 = QLabel(self.groupBox_13)
        self.label_3.setObjectName(u"label_3")

        self.horizontalLayout_10.addWidget(self.label_3)

        self.progressBar_cpu = QProgressBar(self.groupBox_13)
        self.progressBar_cpu.setObjectName(u"progressBar_cpu")
        self.progressBar_cpu.setValue(24)

        self.horizontalLayout_10.addWidget(self.progressBar_cpu)


        self.verticalLayout_9.addLayout(self.horizontalLayout_10)

        self.horizontalLayout_13 = QHBoxLayout()
        self.horizontalLayout_13.setObjectName(u"horizontalLayout_13")
        self.label_4 = QLabel(self.groupBox_13)
        self.label_4.setObjectName(u"label_4")

        self.horizontalLayout_13.addWidget(self.label_4)

        self.progressBar_memory = QProgressBar(self.groupBox_13)
        self.progressBar_memory.setObjectName(u"progressBar_memory")
        self.progressBar_memory.setValue(24)

        self.horizontalLayout_13.addWidget(self.progressBar_memory)


        self.verticalLayout_9.addLayout(self.horizontalLayout_13)

        self.verticalLayout_9.setStretch(0, 4)
        self.verticalLayout_9.setStretch(1, 4)

        self.horizontalLayout_14.addLayout(self.verticalLayout_9)

        self.horizontalLayout_14.setStretch(0, 6)
        self.horizontalLayout_14.setStretch(1, 4)

        self.verticalLayout_14.addLayout(self.horizontalLayout_14)


        self.horizontalLayout_9.addWidget(self.groupBox_13)

        self.horizontalLayout_9.setStretch(0, 4)
        self.horizontalLayout_9.setStretch(1, 6)

        self.verticalLayout_11.addLayout(self.horizontalLayout_9)

        self.verticalLayout_11.setStretch(0, 5)
        self.verticalLayout_11.setStretch(1, 5)

        self.verticalLayout_18.addLayout(self.verticalLayout_11)


        self.verticalLayout_12.addWidget(self.frame_2)

        self.tabWidget.addTab(self.tab_analysis, "")
        self.tab_setting = QWidget()
        self.tab_setting.setObjectName(u"tab_setting")
        self.verticalLayout_20 = QVBoxLayout(self.tab_setting)
        self.verticalLayout_20.setObjectName(u"verticalLayout_20")
        self.scrollArea = QScrollArea(self.tab_setting)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents = QWidget()
        self.scrollAreaWidgetContents.setObjectName(u"scrollAreaWidgetContents")
        self.scrollAreaWidgetContents.setGeometry(QRect(0, 0, 986, 623))
        self.verticalLayout_25 = QVBoxLayout(self.scrollAreaWidgetContents)
        self.verticalLayout_25.setObjectName(u"verticalLayout_25")
        self.groupBox_11 = QGroupBox(self.scrollAreaWidgetContents)
        self.groupBox_11.setObjectName(u"groupBox_11")
        self.verticalLayout_21 = QVBoxLayout(self.groupBox_11)
        self.verticalLayout_21.setObjectName(u"verticalLayout_21")
        self.horizontalLayout_19 = QHBoxLayout()
        self.horizontalLayout_19.setObjectName(u"horizontalLayout_19")
        self.label_32 = QLabel(self.groupBox_11)
        self.label_32.setObjectName(u"label_32")
        self.label_32.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_19.addWidget(self.label_32)

        self.btn_model_browse = QPushButton(self.groupBox_11)
        self.btn_model_browse.setObjectName(u"btn_model_browse")

        self.horizontalLayout_19.addWidget(self.btn_model_browse)

        self.label_34 = QLabel(self.groupBox_11)
        self.label_34.setObjectName(u"label_34")

        self.horizontalLayout_19.addWidget(self.label_34)

        self.label_model_path = QLabel(self.groupBox_11)
        self.label_model_path.setObjectName(u"label_model_path")
        self.label_model_path.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_19.addWidget(self.label_model_path)


        self.verticalLayout_21.addLayout(self.horizontalLayout_19)

        self.horizontalLayout_18 = QHBoxLayout()
        self.horizontalLayout_18.setObjectName(u"horizontalLayout_18")
        self.label_33 = QLabel(self.groupBox_11)
        self.label_33.setObjectName(u"label_33")
        self.label_33.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_18.addWidget(self.label_33)

        self.btn_label_browse = QPushButton(self.groupBox_11)
        self.btn_label_browse.setObjectName(u"btn_label_browse")

        self.horizontalLayout_18.addWidget(self.btn_label_browse)

        self.label_35 = QLabel(self.groupBox_11)
        self.label_35.setObjectName(u"label_35")

        self.horizontalLayout_18.addWidget(self.label_35)

        self.label_label_path = QLabel(self.groupBox_11)
        self.label_label_path.setObjectName(u"label_label_path")
        self.label_label_path.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_18.addWidget(self.label_label_path)


        self.verticalLayout_21.addLayout(self.horizontalLayout_18)

        self.horizontalLayout_17 = QHBoxLayout()
        self.horizontalLayout_17.setObjectName(u"horizontalLayout_17")
        self.label_36 = QLabel(self.groupBox_11)
        self.label_36.setObjectName(u"label_36")
        self.label_36.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_17.addWidget(self.label_36)

        self.combo_hardware_accel = QComboBox(self.groupBox_11)
        self.combo_hardware_accel.addItem("")
        self.combo_hardware_accel.addItem("")
        self.combo_hardware_accel.addItem("")
        self.combo_hardware_accel.setObjectName(u"combo_hardware_accel")
        self.combo_hardware_accel.setMinimumSize(QSize(0, 50))

        self.horizontalLayout_17.addWidget(self.combo_hardware_accel)


        self.verticalLayout_21.addLayout(self.horizontalLayout_17)


        self.verticalLayout_25.addWidget(self.groupBox_11)

        self.groupBox_12 = QGroupBox(self.scrollAreaWidgetContents)
        self.groupBox_12.setObjectName(u"groupBox_12")
        self.verticalLayout_22 = QVBoxLayout(self.groupBox_12)
        self.verticalLayout_22.setObjectName(u"verticalLayout_22")
        self.horizontalLayout_30 = QHBoxLayout()
        self.horizontalLayout_30.setObjectName(u"horizontalLayout_30")
        self.label_37 = QLabel(self.groupBox_12)
        self.label_37.setObjectName(u"label_37")
        self.label_37.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_30.addWidget(self.label_37)

        self.combo_target_select_rule = QComboBox(self.groupBox_12)
        self.combo_target_select_rule.addItem("")
        self.combo_target_select_rule.addItem("")
        self.combo_target_select_rule.addItem("")
        self.combo_target_select_rule.addItem("")
        self.combo_target_select_rule.setObjectName(u"combo_target_select_rule")
        self.combo_target_select_rule.setMinimumSize(QSize(0, 50))

        self.horizontalLayout_30.addWidget(self.combo_target_select_rule)


        self.verticalLayout_22.addLayout(self.horizontalLayout_30)

        self.horizontalLayout_28 = QHBoxLayout()
        self.horizontalLayout_28.setObjectName(u"horizontalLayout_28")
        self.label_38 = QLabel(self.groupBox_12)
        self.label_38.setObjectName(u"label_38")
        self.label_38.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_28.addWidget(self.label_38)

        self.combo_specific_class = QComboBox(self.groupBox_12)
        self.combo_specific_class.setObjectName(u"combo_specific_class")
        self.combo_specific_class.setMinimumSize(QSize(0, 50))

        self.horizontalLayout_28.addWidget(self.combo_specific_class)


        self.verticalLayout_22.addLayout(self.horizontalLayout_28)

        self.horizontalLayout_24 = QHBoxLayout()
        self.horizontalLayout_24.setObjectName(u"horizontalLayout_24")
        self.label_29 = QLabel(self.groupBox_12)
        self.label_29.setObjectName(u"label_29")
        self.label_29.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_24.addWidget(self.label_29)

        self.slider_base_width = QSlider(self.groupBox_12)
        self.slider_base_width.setObjectName(u"slider_base_width")
        self.slider_base_width.setMinimum(1)
        self.slider_base_width.setMaximum(640)
        self.slider_base_width.setPageStep(1)
        self.slider_base_width.setValue(100)
        self.slider_base_width.setOrientation(Qt.Orientation.Horizontal)

        self.horizontalLayout_24.addWidget(self.slider_base_width)

        self.label_base_width = QLabel(self.groupBox_12)
        self.label_base_width.setObjectName(u"label_base_width")

        self.horizontalLayout_24.addWidget(self.label_base_width)


        self.verticalLayout_22.addLayout(self.horizontalLayout_24)


        self.verticalLayout_25.addWidget(self.groupBox_12)

        self.groupBox_14 = QGroupBox(self.scrollAreaWidgetContents)
        self.groupBox_14.setObjectName(u"groupBox_14")
        self.verticalLayout_7 = QVBoxLayout(self.groupBox_14)
        self.verticalLayout_7.setObjectName(u"verticalLayout_7")
        self.horizontalLayout_12 = QHBoxLayout()
        self.horizontalLayout_12.setObjectName(u"horizontalLayout_12")
        self.label_28 = QLabel(self.groupBox_14)
        self.label_28.setObjectName(u"label_28")
        self.label_28.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_12.addWidget(self.label_28)

        self.slider_sample_freq = QSlider(self.groupBox_14)
        self.slider_sample_freq.setObjectName(u"slider_sample_freq")
        self.slider_sample_freq.setMinimum(10)
        self.slider_sample_freq.setMaximum(100)
        self.slider_sample_freq.setPageStep(1)
        self.slider_sample_freq.setValue(30)
        self.slider_sample_freq.setOrientation(Qt.Orientation.Horizontal)

        self.horizontalLayout_12.addWidget(self.slider_sample_freq)

        self.label_sample_freq = QLabel(self.groupBox_14)
        self.label_sample_freq.setObjectName(u"label_sample_freq")

        self.horizontalLayout_12.addWidget(self.label_sample_freq)


        self.verticalLayout_7.addLayout(self.horizontalLayout_12)

        self.checkBox = QCheckBox(self.groupBox_14)
        self.checkBox.setObjectName(u"checkBox")
        self.checkBox.setMinimumSize(QSize(0, 50))

        self.verticalLayout_7.addWidget(self.checkBox)

        self.horizontalLayout_11 = QHBoxLayout()
        self.horizontalLayout_11.setObjectName(u"horizontalLayout_11")
        self.QPuahButton_calibrate_status = QPushButton(self.groupBox_14)
        self.QPuahButton_calibrate_status.setObjectName(u"QPuahButton_calibrate_status")
        self.QPuahButton_calibrate_status.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_11.addWidget(self.QPuahButton_calibrate_status)

        self.label_30 = QLabel(self.groupBox_14)
        self.label_30.setObjectName(u"label_30")

        self.horizontalLayout_11.addWidget(self.label_30)

        self.label__calibrate_status = QLabel(self.groupBox_14)
        self.label__calibrate_status.setObjectName(u"label__calibrate_status")

        self.horizontalLayout_11.addWidget(self.label__calibrate_status)


        self.verticalLayout_7.addLayout(self.horizontalLayout_11)


        self.verticalLayout_25.addWidget(self.groupBox_14)

        self.groupBox_calib = QGroupBox(self.scrollAreaWidgetContents)
        self.groupBox_calib.setObjectName(u"groupBox_calib")
        self.verticalLayout_calib = QVBoxLayout(self.groupBox_calib)
        self.verticalLayout_calib.setObjectName(u"verticalLayout_calib")
        self.horizontalLayout_31 = QHBoxLayout()
        self.horizontalLayout_31.setObjectName(u"horizontalLayout_31")
        self.label_31 = QLabel(self.groupBox_calib)
        self.label_31.setObjectName(u"label_31")
        self.label_31.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_31.addWidget(self.label_31)

        self.spin_pattern_cols = QSpinBox(self.groupBox_calib)
        self.spin_pattern_cols.setObjectName(u"spin_pattern_cols")
        self.spin_pattern_cols.setMinimum(3)
        self.spin_pattern_cols.setMaximum(20)
        self.spin_pattern_cols.setValue(9)

        self.horizontalLayout_31.addWidget(self.spin_pattern_cols)

        self.label_39 = QLabel(self.groupBox_calib)
        self.label_39.setObjectName(u"label_39")
        self.label_39.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_31.addWidget(self.label_39)

        self.spin_pattern_rows = QSpinBox(self.groupBox_calib)
        self.spin_pattern_rows.setObjectName(u"spin_pattern_rows")
        self.spin_pattern_rows.setMinimum(3)
        self.spin_pattern_rows.setMaximum(20)
        self.spin_pattern_rows.setValue(6)

        self.horizontalLayout_31.addWidget(self.spin_pattern_rows)


        self.verticalLayout_calib.addLayout(self.horizontalLayout_31)

        self.horizontalLayout_32 = QHBoxLayout()
        self.horizontalLayout_32.setObjectName(u"horizontalLayout_32")
        self.label_40 = QLabel(self.groupBox_calib)
        self.label_40.setObjectName(u"label_40")
        self.label_40.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_32.addWidget(self.label_40)

        self.spin_square_mm = QDoubleSpinBox(self.groupBox_calib)
        self.spin_square_mm.setObjectName(u"spin_square_mm")
        self.spin_square_mm.setDecimals(1)
        self.spin_square_mm.setMinimum(1.000000000000000)
        self.spin_square_mm.setMaximum(500.000000000000000)
        self.spin_square_mm.setValue(18.000000000000000)

        self.horizontalLayout_32.addWidget(self.spin_square_mm)


        self.verticalLayout_calib.addLayout(self.horizontalLayout_32)

        self.horizontalLayout_33 = QHBoxLayout()
        self.horizontalLayout_33.setObjectName(u"horizontalLayout_33")
        self.label_41 = QLabel(self.groupBox_calib)
        self.label_41.setObjectName(u"label_41")
        self.label_41.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_33.addWidget(self.label_41)

        self.spin_pitch_deg = QDoubleSpinBox(self.groupBox_calib)
        self.spin_pitch_deg.setObjectName(u"spin_pitch_deg")
        self.spin_pitch_deg.setDecimals(1)
        self.spin_pitch_deg.setMinimum(0.000000000000000)
        self.spin_pitch_deg.setMaximum(60.000000000000000)
        self.spin_pitch_deg.setValue(0.000000000000000)

        self.horizontalLayout_33.addWidget(self.spin_pitch_deg)


        self.verticalLayout_calib.addLayout(self.horizontalLayout_33)

        self.horizontalLayout_34 = QHBoxLayout()
        self.horizontalLayout_34.setObjectName(u"horizontalLayout_34")
        self.btn_calib_capture = QPushButton(self.groupBox_calib)
        self.btn_calib_capture.setObjectName(u"btn_calib_capture")
        self.btn_calib_capture.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_34.addWidget(self.btn_calib_capture)

        self.btn_calib_solve = QPushButton(self.groupBox_calib)
        self.btn_calib_solve.setObjectName(u"btn_calib_solve")
        self.btn_calib_solve.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_34.addWidget(self.btn_calib_solve)


        self.verticalLayout_calib.addLayout(self.horizontalLayout_34)

        self.label_calib_info = QLabel(self.groupBox_calib)
        self.label_calib_info.setObjectName(u"label_calib_info")
        self.label_calib_info.setWordWrap(True)

        self.verticalLayout_calib.addWidget(self.label_calib_info)


        self.verticalLayout_25.addWidget(self.groupBox_calib)

        self.scrollArea.setWidget(self.scrollAreaWidgetContents)

        self.verticalLayout_20.addWidget(self.scrollArea)

        self.tabWidget.addTab(self.tab_setting, "")
        self.tab_record = QWidget()
        self.tab_record.setObjectName(u"tab_record")
        self.verticalLayout_rec = QVBoxLayout(self.tab_record)
        self.verticalLayout_rec.setObjectName(u"verticalLayout_rec")
        self.groupBox_rec = QGroupBox(self.tab_record)
        self.groupBox_rec.setObjectName(u"groupBox_rec")
        self.verticalLayout_rec1 = QVBoxLayout(self.groupBox_rec)
        self.verticalLayout_rec1.setObjectName(u"verticalLayout_rec1")
        self.horizontalLayout_rec1 = QHBoxLayout()
        self.horizontalLayout_rec1.setObjectName(u"horizontalLayout_rec1")
        self.btn_rec_toggle = QPushButton(self.groupBox_rec)
        self.btn_rec_toggle.setObjectName(u"btn_rec_toggle")
        self.btn_rec_toggle.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_rec1.addWidget(self.btn_rec_toggle)

        self.label_rec_status = QLabel(self.groupBox_rec)
        self.label_rec_status.setObjectName(u"label_rec_status")

        self.horizontalLayout_rec1.addWidget(self.label_rec_status)


        self.verticalLayout_rec1.addLayout(self.horizontalLayout_rec1)

        self.label_rec_info = QLabel(self.groupBox_rec)
        self.label_rec_info.setObjectName(u"label_rec_info")
        self.label_rec_info.setWordWrap(True)

        self.verticalLayout_rec1.addWidget(self.label_rec_info)


        self.verticalLayout_rec.addWidget(self.groupBox_rec)

        self.groupBox_play = QGroupBox(self.tab_record)
        self.groupBox_play.setObjectName(u"groupBox_play")
        self.verticalLayout_play = QVBoxLayout(self.groupBox_play)
        self.verticalLayout_play.setObjectName(u"verticalLayout_play")
        self.horizontalLayout_play1 = QHBoxLayout()
        self.horizontalLayout_play1.setObjectName(u"horizontalLayout_play1")
        self.btn_play_pick = QPushButton(self.groupBox_play)
        self.btn_play_pick.setObjectName(u"btn_play_pick")
        self.btn_play_pick.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_play1.addWidget(self.btn_play_pick)

        self.btn_play_toggle = QPushButton(self.groupBox_play)
        self.btn_play_toggle.setObjectName(u"btn_play_toggle")
        self.btn_play_toggle.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_play1.addWidget(self.btn_play_toggle)

        self.btn_play_stop = QPushButton(self.groupBox_play)
        self.btn_play_stop.setObjectName(u"btn_play_stop")
        self.btn_play_stop.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_play1.addWidget(self.btn_play_stop)

        self.slider_play_pos = QSlider(self.groupBox_play)
        self.slider_play_pos.setObjectName(u"slider_play_pos")
        self.slider_play_pos.setMinimum(0)
        self.slider_play_pos.setMaximum(1000)
        self.slider_play_pos.setValue(0)
        self.slider_play_pos.setOrientation(Qt.Orientation.Horizontal)

        self.horizontalLayout_play1.addWidget(self.slider_play_pos)

        self.label_play_pos = QLabel(self.groupBox_play)
        self.label_play_pos.setObjectName(u"label_play_pos")

        self.horizontalLayout_play1.addWidget(self.label_play_pos)


        self.verticalLayout_play.addLayout(self.horizontalLayout_play1)

        self.label_play_info = QLabel(self.groupBox_play)
        self.label_play_info.setObjectName(u"label_play_info")
        self.label_play_info.setWordWrap(True)

        self.verticalLayout_play.addWidget(self.label_play_info)


        self.verticalLayout_rec.addWidget(self.groupBox_play)

        self.groupBox_play_plot = QGroupBox(self.tab_record)
        self.groupBox_play_plot.setObjectName(u"groupBox_play_plot")
        self.verticalLayout_playplot = QVBoxLayout(self.groupBox_play_plot)
        self.verticalLayout_playplot.setObjectName(u"verticalLayout_playplot")
        self.plot_replay_distance = PlotWidget(self.groupBox_play_plot)
        self.plot_replay_distance.setObjectName(u"plot_replay_distance")

        self.verticalLayout_playplot.addWidget(self.plot_replay_distance)


        self.verticalLayout_rec.addWidget(self.groupBox_play_plot)

        self.label_replay_summary = QLabel(self.tab_record)
        self.label_replay_summary.setObjectName(u"label_replay_summary")
        self.label_replay_summary.setWordWrap(True)

        self.verticalLayout_rec.addWidget(self.label_replay_summary)

        self.tabWidget.addTab(self.tab_record, "")

        self.verticalLayout_10.addWidget(self.tabWidget)


        self.retranslateUi(Form)

        self.tabWidget.setCurrentIndex(2)


        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.groupBox_5.setTitle(QCoreApplication.translate("Form", u"\u539f\u59cb\u56fe\u50cf", None))
        self.lbl_original.setText(QCoreApplication.translate("Form", u"TextLabel", None))
        self.groupBox_6.setTitle(QCoreApplication.translate("Form", u"\u5904\u7406\u540e\u7684\u56fe\u50cf", None))
        self.lbl_process.setText(QCoreApplication.translate("Form", u"TextLabel", None))
        self.groupBox_targetpos.setTitle(QCoreApplication.translate("Form", u"\u76ee\u6807\u4f4d\u7f6e", None))
        self.label.setText(QCoreApplication.translate("Form", u"\u6846\u4e2d\u5fc3 X\uff1a", None))
        self.label_2.setText(QCoreApplication.translate("Form", u"\u6846\u4e2d\u5fc3 Y\uff1a", None))
        self.label_17.setText(QCoreApplication.translate("Form", u"\u68c0\u6d4b\u7f6e\u53ef\u4fe1\u5ea6\uff1a", None))
        self.label_19.setText(QCoreApplication.translate("Form", u"\u76ee\u6807\u7c7b\u522b\uff1a", None))
        self.label_target_category.setText(QCoreApplication.translate("Form", u"--", None))
        self.label_distance_title.setText(QCoreApplication.translate("Form", u"\u76ee\u6807\u8ddd\u79bb\uff1a", None))
        self.label_distance_value.setText(QCoreApplication.translate("Form", u"\u4e0d\u53ef\u6d4b", None))
        self.groupBox_10.setTitle(QCoreApplication.translate("Form", u"\u6a21\u578b\u53c2\u6570\u5b9e\u65f6\u5fae\u8c03", None))
        self.label_23.setText(QCoreApplication.translate("Form", u" \u7f6e\u4fe1\u5ea6\u9608\u503c\uff1a", None))
        self.label_confidence_thres.setText(QCoreApplication.translate("Form", u"0.50", None))
        self.label_25.setText(QCoreApplication.translate("Form", u" NMS\u9608\u503c\uff1a", None))
        self.label_nms_thres.setText(QCoreApplication.translate("Form", u"0.45", None))
        self.groupBox_4.setTitle(QCoreApplication.translate("Form", u"\u7cfb\u7edf\u6027\u80fd", None))
        self.label_21.setText(QCoreApplication.translate("Form", u"\u63a8\u7406FPS\uff1a", None))
        self.label_9.setText(QCoreApplication.translate("Form", u"\u753b\u9762FPS\uff1a", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_monitor), QCoreApplication.translate("Form", u"\u76d1\u89c6", None))
        self.groupBox_7.setTitle(QCoreApplication.translate("Form", u"\u76ee\u6807\u4f4d\u7f6e\u5206\u6790", None))
        self.label_5.setText(QCoreApplication.translate("Form", u"\u63d0\u793a\uff1a", None))
        self.label_prompt.setText(QCoreApplication.translate("Form", u"TextLabel", None))
        self.groupBox_8.setTitle(QCoreApplication.translate("Form", u"\u76ee\u6807\u5c3a\u5bf8\u4e0e\u8ddd\u79bb\u5206\u6790", None))
        self.groupBox_9.setTitle(QCoreApplication.translate("Form", u"\u7f6e\u4fe1\u5ea6\u5206\u6790", None))
        self.label_6.setText(QCoreApplication.translate("Form", u"\u63d0\u793a\uff1a", None))
        self.label_conf.setText(QCoreApplication.translate("Form", u"TextLabel", None))
        self.groupBox_13.setTitle(QCoreApplication.translate("Form", u"\u7cfb\u7edf\u6027\u80fd\u5206\u6790", None))
        self.label_3.setText(QCoreApplication.translate("Form", u"CPU\u5360\u7528\uff1a", None))
        self.label_4.setText(QCoreApplication.translate("Form", u"\u5185\u5b58\u5360\u7528\uff1a", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_analysis), QCoreApplication.translate("Form", u"\u6df1\u5ea6\u5206\u6790", None))
        self.groupBox_11.setTitle(QCoreApplication.translate("Form", u"\u6a21\u578b\u914d\u7f6e", None))
        self.label_32.setText(QCoreApplication.translate("Form", u"\u6a21\u578b\u6587\u4ef6\uff1a", None))
        self.btn_model_browse.setText(QCoreApplication.translate("Form", u"\u6d4f\u89c8", None))
        self.label_34.setText(QCoreApplication.translate("Form", u"\u5f53\u524d\u6a21\u578b\uff1a", None))
        self.label_model_path.setText(QCoreApplication.translate("Form", u"\u5f53\u524d\u6a21\u578b", None))
        self.label_33.setText(QCoreApplication.translate("Form", u"\u6807\u7b7e\u6587\u4ef6\u6587\u4ef6\uff1a", None))
        self.btn_label_browse.setText(QCoreApplication.translate("Form", u"\u6d4f\u89c8", None))
        self.label_35.setText(QCoreApplication.translate("Form", u"\u5f53\u524d\u6807\u7b7e\uff1a", None))
        self.label_label_path.setText(QCoreApplication.translate("Form", u"\u5f53\u524d\u6a21\u578b", None))
        self.label_36.setText(QCoreApplication.translate("Form", u"\u786c\u4ef6\u52a0\u901f\u5668\uff1a", None))
        self.combo_hardware_accel.setItemText(0, QCoreApplication.translate("Form", u"CPU", None))
        self.combo_hardware_accel.setItemText(1, QCoreApplication.translate("Form", u"GPU", None))
        self.combo_hardware_accel.setItemText(2, QCoreApplication.translate("Form", u"NPU", None))

        self.groupBox_12.setTitle(QCoreApplication.translate("Form", u"\u68c0\u6d4b\u914d\u7f6e", None))
        self.label_37.setText(QCoreApplication.translate("Form", u"\u76ee\u6807\u9009\u62e9\u89c4\u5219\uff1a", None))
        self.combo_target_select_rule.setItemText(0, QCoreApplication.translate("Form", u"\u6700\u9ad8\u7f6e\u4fe1\u5ea6", None))
        self.combo_target_select_rule.setItemText(1, QCoreApplication.translate("Form", u"\u6700\u5927\u9762\u79ef", None))
        self.combo_target_select_rule.setItemText(2, QCoreApplication.translate("Form", u"\u6700\u63a5\u8fd1\u4e2d\u5fc3", None))
        self.combo_target_select_rule.setItemText(3, QCoreApplication.translate("Form", u"\u6307\u5b9a\u7c7b\u522b", None))

        self.label_38.setText(QCoreApplication.translate("Form", u"\u6307\u5b9a\u7c7b\u522b\uff1a", None))
        self.label_29.setText(QCoreApplication.translate("Form", u"\u57fa\u51c6\u5bbd\u5ea6\uff1a", None))
        self.label_base_width.setText(QCoreApplication.translate("Form", u"30", None))
        self.groupBox_14.setTitle(QCoreApplication.translate("Form", u"\u6807\u5b9a\u4e0e\u7cfb\u7edf", None))
        self.label_28.setText(QCoreApplication.translate("Form", u"\u91c7\u6837\u9891\u7387\uff08Hz\uff09\uff1a", None))
        self.label_sample_freq.setText(QCoreApplication.translate("Form", u"30Hz", None))
        self.checkBox.setText(QCoreApplication.translate("Form", u"\u662f\u5426\u542f\u7528\u6df1\u5ea6\u5206\u6790", None))
        self.QPuahButton_calibrate_status.setText(QCoreApplication.translate("Form", u"\u5e94\u7528\u53c2\u6570", None))
        self.label_30.setText(QCoreApplication.translate("Form", u"\u6807\u5b9a\u72b6\u6001\uff1a", None))
        self.label__calibrate_status.setText(QCoreApplication.translate("Form", u"\u672a\u6807\u5b9a", None))
        self.groupBox_calib.setTitle(QCoreApplication.translate("Form", u"\u76f8\u673a\u6807\u5b9a", None))
        self.label_31.setText(QCoreApplication.translate("Form", u"\u68cb\u76d8\u683c\u5185\u89d2\u70b9\uff1a", None))
        self.label_39.setText(QCoreApplication.translate("Form", u"\u00d7", None))
        self.label_40.setText(QCoreApplication.translate("Form", u"\u65b9\u683c\u8fb9\u957f\uff08mm\uff09\uff1a", None))
        self.label_41.setText(QCoreApplication.translate("Form", u"\u76f8\u673a\u4fef\u4ef0\u89d2\uff08\u00b0\uff09\uff1a", None))
        self.btn_calib_capture.setText(QCoreApplication.translate("Form", u"\u5f00\u59cb\u91c7\u96c6", None))
        self.btn_calib_solve.setText(QCoreApplication.translate("Form", u"\u6c42\u89e3\u5e76\u4fdd\u5b58", None))
        self.label_calib_info.setText(QCoreApplication.translate("Form", u"\u672a\u91c7\u96c6\u3002\u70b9\u300c\u5f00\u59cb\u91c7\u96c6\u300d\uff0c\u8ba9\u68cb\u76d8\u683c\u5728\u753b\u9762\u4e2d\u53d8\u6362\u4f4d\u7f6e\u4e0e\u503e\u659c\u89d2\uff1b\u91c7\u591f 10 \u5e27\u540e\u70b9\u300c\u6c42\u89e3\u5e76\u4fdd\u5b58\u300d\u3002", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_setting), QCoreApplication.translate("Form", u"\u8bbe\u7f6e", None))
        self.groupBox_rec.setTitle(QCoreApplication.translate("Form", u"\u5f55\u5236", None))
        self.btn_rec_toggle.setText(QCoreApplication.translate("Form", u"\u5f00\u59cb\u5f55\u5236", None))
        self.label_rec_status.setText(QCoreApplication.translate("Form", u"\u7a7a\u95f2", None))
        self.label_rec_info.setText(QCoreApplication.translate("Form", u"\u672a\u5f55\u5236\u3002\u5f00\u59cb\u540e\u4f1a\u628a\u753b\u9762\u4e0e\u68c0\u6d4b/\u6d4b\u8ddd\u7ed3\u679c\u5206\u522b\u843d\u76d8\uff0c\u5f55\u5236\u671f\u95f4\u4e0d\u963b\u585e\u4e3b\u94fe\u8def\u3002", None))
        self.groupBox_play.setTitle(QCoreApplication.translate("Form", u"\u56de\u653e\u5206\u6790", None))
        self.btn_play_pick.setText(QCoreApplication.translate("Form", u"\u9009\u62e9\u5f55\u5236", None))
        self.btn_play_toggle.setText(QCoreApplication.translate("Form", u"\u64ad\u653e", None))
        self.btn_play_stop.setText(QCoreApplication.translate("Form", u"\u505c\u6b62", None))
        self.label_play_pos.setText(QCoreApplication.translate("Form", u"0/0", None))
        self.label_play_info.setText(QCoreApplication.translate("Form", u"\u672a\u9009\u62e9\u5f55\u5236\u3002\u56de\u653e\u89c6\u9891\u8f68\u4e0e\u6570\u636e\u8f68\u540c\u6b65\uff0c\u53ef\u5728\u4e0b\u65b9\u67e5\u770b\u6d4b\u8ddd\u66f2\u7ebf\u3002", None))
        self.groupBox_play_plot.setTitle(QCoreApplication.translate("Form", u"\u6d4b\u8ddd\u66f2\u7ebf\uff08\u56de\u653e\uff09", None))
        self.label_replay_summary.setText(QCoreApplication.translate("Form", u"\u5c1a\u65e0\u56de\u653e\u6570\u636e\u3002", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_record), QCoreApplication.translate("Form", u"\u5f55\u5236\u56de\u653e", None))
    # retranslateUi

