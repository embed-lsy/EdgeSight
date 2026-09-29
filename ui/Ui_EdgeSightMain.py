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
    QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget)

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

        self.label_distance_reason = QLabel(self.groupBox_targetpos)
        self.label_distance_reason.setObjectName(u"label_distance_reason")
        self.label_distance_reason.setWordWrap(True)
        self.label_distance_reason.setStyleSheet(u"font-size: 9pt;")

        self.verticalLayout_5.addWidget(self.label_distance_reason)

        self.horizontalLayout_ttc = QHBoxLayout()
        self.horizontalLayout_ttc.setObjectName(u"horizontalLayout_ttc")
        self.label_ttc_title = QLabel(self.groupBox_targetpos)
        self.label_ttc_title.setObjectName(u"label_ttc_title")
        self.label_ttc_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_ttc.addWidget(self.label_ttc_title)

        self.label_ttc_value = QLabel(self.groupBox_targetpos)
        self.label_ttc_value.setObjectName(u"label_ttc_value")
        self.label_ttc_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_ttc_value.setStyleSheet(u"font-weight: bold; font-size: 12pt;")

        self.horizontalLayout_ttc.addWidget(self.label_ttc_value)


        self.verticalLayout_5.addLayout(self.horizontalLayout_ttc)

        self.label_ttc_reason = QLabel(self.groupBox_targetpos)
        self.label_ttc_reason.setObjectName(u"label_ttc_reason")
        self.label_ttc_reason.setWordWrap(True)
        self.label_ttc_reason.setStyleSheet(u"font-size: 9pt;")

        self.verticalLayout_5.addWidget(self.label_ttc_reason)


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
        self.slider_confidence_thres.setValue(40)
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
        self.verticalLayout_26 = QVBoxLayout(self.groupBox_8)
        self.verticalLayout_26.setObjectName(u"verticalLayout_26")
        self.plot_target_distance = PlotWidget(self.groupBox_8)
        self.plot_target_distance.setObjectName(u"plot_target_distance")

        self.verticalLayout_26.addWidget(self.plot_target_distance)

        self.horizontalLayout_35 = QHBoxLayout()
        self.horizontalLayout_35.setObjectName(u"horizontalLayout_35")
        self.label_42 = QLabel(self.groupBox_8)
        self.label_42.setObjectName(u"label_42")
        self.label_42.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_35.addWidget(self.label_42)

        self.label_method_prompt = QLabel(self.groupBox_8)
        self.label_method_prompt.setObjectName(u"label_method_prompt")
        self.label_method_prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_35.addWidget(self.label_method_prompt)

        self.horizontalLayout_35.setStretch(0, 2)
        self.horizontalLayout_35.setStretch(1, 8)

        self.verticalLayout_26.addLayout(self.horizontalLayout_35)


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

        self.combo_track_target = QComboBox(self.groupBox_12)
        self.combo_track_target.addItem("")
        self.combo_track_target.setObjectName(u"combo_track_target")
        self.combo_track_target.setMinimumSize(QSize(0, 50))

        self.horizontalLayout_30.addWidget(self.combo_track_target)

        self.btn_rename_track_target = QPushButton(self.groupBox_12)
        self.btn_rename_track_target.setObjectName(u"btn_rename_track_target")
        self.btn_rename_track_target.setMinimumSize(QSize(0, 50))

        self.horizontalLayout_30.addWidget(self.btn_rename_track_target)


        self.verticalLayout_22.addLayout(self.horizontalLayout_30)

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

        self.groupBox_profiles = QGroupBox(self.scrollAreaWidgetContents)
        self.groupBox_profiles.setObjectName(u"groupBox_profiles")
        self.verticalLayout_profiles = QVBoxLayout(self.groupBox_profiles)
        self.verticalLayout_profiles.setObjectName(u"verticalLayout_profiles")
        self.label_profiles_hint = QLabel(self.groupBox_profiles)
        self.label_profiles_hint.setObjectName(u"label_profiles_hint")
        self.label_profiles_hint.setWordWrap(True)

        self.verticalLayout_profiles.addWidget(self.label_profiles_hint)

        self.list_profiles = QListWidget(self.groupBox_profiles)
        self.list_profiles.setObjectName(u"list_profiles")
        self.list_profiles.setMinimumSize(QSize(0, 150))

        self.verticalLayout_profiles.addWidget(self.list_profiles)

        self.horizontalLayout_profiles = QHBoxLayout()
        self.horizontalLayout_profiles.setObjectName(u"horizontalLayout_profiles")
        self.btn_profile_rename = QPushButton(self.groupBox_profiles)
        self.btn_profile_rename.setObjectName(u"btn_profile_rename")
        self.btn_profile_rename.setMinimumSize(QSize(0, 36))

        self.horizontalLayout_profiles.addWidget(self.btn_profile_rename)

        self.btn_profile_delete = QPushButton(self.groupBox_profiles)
        self.btn_profile_delete.setObjectName(u"btn_profile_delete")
        self.btn_profile_delete.setMinimumSize(QSize(0, 36))

        self.horizontalLayout_profiles.addWidget(self.btn_profile_delete)

        self.btn_profile_refresh = QPushButton(self.groupBox_profiles)
        self.btn_profile_refresh.setObjectName(u"btn_profile_refresh")
        self.btn_profile_refresh.setMinimumSize(QSize(0, 36))

        self.horizontalLayout_profiles.addWidget(self.btn_profile_refresh)


        self.verticalLayout_profiles.addLayout(self.horizontalLayout_profiles)

        self.label_profile_detail = QLabel(self.groupBox_profiles)
        self.label_profile_detail.setObjectName(u"label_profile_detail")
        self.label_profile_detail.setWordWrap(True)

        self.verticalLayout_profiles.addWidget(self.label_profile_detail)


        self.verticalLayout_25.addWidget(self.groupBox_profiles)

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
        self.tab_calib = QWidget()
        self.tab_calib.setObjectName(u"tab_calib")
        self.verticalLayout_calibtab = QVBoxLayout(self.tab_calib)
        self.verticalLayout_calibtab.setObjectName(u"verticalLayout_calibtab")
        self.label_calibtab_hint = QLabel(self.tab_calib)
        self.label_calibtab_hint.setObjectName(u"label_calibtab_hint")
        self.label_calibtab_hint.setWordWrap(True)

        self.verticalLayout_calibtab.addWidget(self.label_calibtab_hint)

        self.groupBox_calib_preview = QGroupBox(self.tab_calib)
        self.groupBox_calib_preview.setObjectName(u"groupBox_calib_preview")
        self.verticalLayout_calibprev = QVBoxLayout(self.groupBox_calib_preview)
        self.verticalLayout_calibprev.setObjectName(u"verticalLayout_calibprev")
        self.lbl_calib_view = QLabel(self.groupBox_calib_preview)
        self.lbl_calib_view.setObjectName(u"lbl_calib_view")
        self.lbl_calib_view.setMinimumSize(QSize(320, 240))
        self.lbl_calib_view.setMaximumSize(QSize(16777215, 300))
        self.lbl_calib_view.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout_calibprev.addWidget(self.lbl_calib_view)


        self.verticalLayout_calibtab.addWidget(self.groupBox_calib_preview)

        self.scrollArea_calib = QScrollArea(self.tab_calib)
        self.scrollArea_calib.setObjectName(u"scrollArea_calib")
        self.scrollArea_calib.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scrollArea_calib.setWidgetResizable(True)
        self.scrollAreaWidgetContents_calib = QWidget()
        self.scrollAreaWidgetContents_calib.setObjectName(u"scrollAreaWidgetContents_calib")
        self.scrollAreaWidgetContents_calib.setGeometry(QRect(0, 0, 986, 623))
        self.verticalLayout_calibinner = QVBoxLayout(self.scrollAreaWidgetContents_calib)
        self.verticalLayout_calibinner.setObjectName(u"verticalLayout_calibinner")
        self.groupBox_calib = QGroupBox(self.scrollAreaWidgetContents_calib)
        self.groupBox_calib.setObjectName(u"groupBox_calib")
        self.verticalLayout_calib = QVBoxLayout(self.groupBox_calib)
        self.verticalLayout_calib.setObjectName(u"verticalLayout_calib")
        self.horizontalLayout_camdev = QHBoxLayout()
        self.horizontalLayout_camdev.setObjectName(u"horizontalLayout_camdev")
        self.label_camera_device = QLabel(self.groupBox_calib)
        self.label_camera_device.setObjectName(u"label_camera_device")
        self.label_camera_device.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_camdev.addWidget(self.label_camera_device)

        self.combo_camera_device = QComboBox(self.groupBox_calib)
        self.combo_camera_device.setObjectName(u"combo_camera_device")

        self.horizontalLayout_camdev.addWidget(self.combo_camera_device)


        self.verticalLayout_calib.addLayout(self.horizontalLayout_camdev)

        self.label_camera_status = QLabel(self.groupBox_calib)
        self.label_camera_status.setObjectName(u"label_camera_status")
        self.label_camera_status.setWordWrap(True)

        self.verticalLayout_calib.addWidget(self.label_camera_status)

        self.horizontalLayout_cambind = QHBoxLayout()
        self.horizontalLayout_cambind.setObjectName(u"horizontalLayout_cambind")
        self.btn_camera_bind = QPushButton(self.groupBox_calib)
        self.btn_camera_bind.setObjectName(u"btn_camera_bind")
        self.btn_camera_bind.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_cambind.addWidget(self.btn_camera_bind)

        self.btn_camera_scan = QPushButton(self.groupBox_calib)
        self.btn_camera_scan.setObjectName(u"btn_camera_scan")
        self.btn_camera_scan.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_cambind.addWidget(self.btn_camera_scan)


        self.verticalLayout_calib.addLayout(self.horizontalLayout_cambind)

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
        self.spin_square_mm.setValue(17.100000000000001)

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
        self.spin_pitch_deg.setMinimum(-20.000000000000000)
        self.spin_pitch_deg.setMaximum(75.000000000000000)
        self.spin_pitch_deg.setValue(0.000000000000000)

        self.horizontalLayout_33.addWidget(self.spin_pitch_deg)


        self.verticalLayout_calib.addLayout(self.horizontalLayout_33)

        self.horizontalLayout_ch = QHBoxLayout()
        self.horizontalLayout_ch.setObjectName(u"horizontalLayout_ch")
        self.label_camera_height = QLabel(self.groupBox_calib)
        self.label_camera_height.setObjectName(u"label_camera_height")
        self.label_camera_height.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_ch.addWidget(self.label_camera_height)

        self.spin_camera_height = QDoubleSpinBox(self.groupBox_calib)
        self.spin_camera_height.setObjectName(u"spin_camera_height")
        self.spin_camera_height.setDecimals(2)
        self.spin_camera_height.setMinimum(0.000000000000000)
        self.spin_camera_height.setMaximum(5.000000000000000)
        self.spin_camera_height.setSingleStep(0.050000000000000)
        self.spin_camera_height.setValue(0.000000000000000)

        self.horizontalLayout_ch.addWidget(self.spin_camera_height)


        self.verticalLayout_calib.addLayout(self.horizontalLayout_ch)

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


        self.verticalLayout_calibinner.addWidget(self.groupBox_calib)

        self.groupBox_mount = QGroupBox(self.scrollAreaWidgetContents_calib)
        self.groupBox_mount.setObjectName(u"groupBox_mount")
        self.verticalLayout_mount = QVBoxLayout(self.groupBox_mount)
        self.verticalLayout_mount.setObjectName(u"verticalLayout_mount")
        self.label_mount_hint = QLabel(self.groupBox_mount)
        self.label_mount_hint.setObjectName(u"label_mount_hint")
        self.label_mount_hint.setWordWrap(True)

        self.verticalLayout_mount.addWidget(self.label_mount_hint)

        self.horizontalLayout_mount = QHBoxLayout()
        self.horizontalLayout_mount.setObjectName(u"horizontalLayout_mount")
        self.label_known_dist = QLabel(self.groupBox_mount)
        self.label_known_dist.setObjectName(u"label_known_dist")
        self.label_known_dist.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_mount.addWidget(self.label_known_dist)

        self.spin_known_dist = QDoubleSpinBox(self.groupBox_mount)
        self.spin_known_dist.setObjectName(u"spin_known_dist")
        self.spin_known_dist.setDecimals(2)
        self.spin_known_dist.setMinimum(0.200000000000000)
        self.spin_known_dist.setMaximum(50.000000000000000)
        self.spin_known_dist.setSingleStep(0.500000000000000)
        self.spin_known_dist.setValue(2.000000000000000)

        self.horizontalLayout_mount.addWidget(self.spin_known_dist)

        self.btn_mark_known = QPushButton(self.groupBox_mount)
        self.btn_mark_known.setObjectName(u"btn_mark_known")

        self.horizontalLayout_mount.addWidget(self.btn_mark_known)

        self.btn_solve_mount = QPushButton(self.groupBox_mount)
        self.btn_solve_mount.setObjectName(u"btn_solve_mount")
        self.btn_solve_mount.setEnabled(False)

        self.horizontalLayout_mount.addWidget(self.btn_solve_mount)


        self.verticalLayout_mount.addLayout(self.horizontalLayout_mount)

        self.label_mount_status = QLabel(self.groupBox_mount)
        self.label_mount_status.setObjectName(u"label_mount_status")
        self.label_mount_status.setWordWrap(True)

        self.verticalLayout_mount.addWidget(self.label_mount_status)


        self.verticalLayout_calibinner.addWidget(self.groupBox_mount)

        self.groupBox_enroll = QGroupBox(self.scrollAreaWidgetContents_calib)
        self.groupBox_enroll.setObjectName(u"groupBox_enroll")
        self.verticalLayout_enroll = QVBoxLayout(self.groupBox_enroll)
        self.verticalLayout_enroll.setObjectName(u"verticalLayout_enroll")
        self.label_enroll_hint = QLabel(self.groupBox_enroll)
        self.label_enroll_hint.setObjectName(u"label_enroll_hint")
        self.label_enroll_hint.setWordWrap(True)

        self.verticalLayout_enroll.addWidget(self.label_enroll_hint)

        self.horizontalLayout_enroll1 = QHBoxLayout()
        self.horizontalLayout_enroll1.setObjectName(u"horizontalLayout_enroll1")
        self.label_enroll_dist = QLabel(self.groupBox_enroll)
        self.label_enroll_dist.setObjectName(u"label_enroll_dist")

        self.horizontalLayout_enroll1.addWidget(self.label_enroll_dist)

        self.spin_enroll_distance = QDoubleSpinBox(self.groupBox_enroll)
        self.spin_enroll_distance.setObjectName(u"spin_enroll_distance")
        self.spin_enroll_distance.setDecimals(2)
        self.spin_enroll_distance.setMaximum(50.000000000000000)
        self.spin_enroll_distance.setSingleStep(0.100000000000000)
        self.spin_enroll_distance.setValue(0.000000000000000)

        self.horizontalLayout_enroll1.addWidget(self.spin_enroll_distance)

        self.btn_enroll_toggle = QPushButton(self.groupBox_enroll)
        self.btn_enroll_toggle.setObjectName(u"btn_enroll_toggle")
        self.btn_enroll_toggle.setMinimumSize(QSize(0, 40))

        self.horizontalLayout_enroll1.addWidget(self.btn_enroll_toggle)


        self.verticalLayout_enroll.addLayout(self.horizontalLayout_enroll1)

        self.label_enroll_status = QLabel(self.groupBox_enroll)
        self.label_enroll_status.setObjectName(u"label_enroll_status")
        font1 = QFont()
        font1.setPointSize(20)
        font1.setBold(True)
        self.label_enroll_status.setFont(font1)
        self.label_enroll_status.setWordWrap(True)

        self.verticalLayout_enroll.addWidget(self.label_enroll_status)

        self.label_enroll_match = QLabel(self.groupBox_enroll)
        self.label_enroll_match.setObjectName(u"label_enroll_match")
        self.label_enroll_match.setWordWrap(True)

        self.verticalLayout_enroll.addWidget(self.label_enroll_match)


        self.verticalLayout_calibinner.addWidget(self.groupBox_enroll)

        self.scrollArea_calib.setWidget(self.scrollAreaWidgetContents_calib)

        self.verticalLayout_calibtab.addWidget(self.scrollArea_calib)

        self.tabWidget.addTab(self.tab_calib, "")

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
        self.label_distance_reason.setText("")
        self.label_ttc_title.setText(QCoreApplication.translate("Form", u"\u78b0\u649e\u9884\u8b66\uff1a", None))
        self.label_ttc_value.setText(QCoreApplication.translate("Form", u"--", None))
        self.label_ttc_reason.setText("")
        self.groupBox_10.setTitle(QCoreApplication.translate("Form", u"\u6a21\u578b\u53c2\u6570\u5b9e\u65f6\u5fae\u8c03", None))
        self.label_23.setText(QCoreApplication.translate("Form", u" \u7f6e\u4fe1\u5ea6\u9608\u503c\uff1a", None))
        self.label_confidence_thres.setText(QCoreApplication.translate("Form", u"0.40", None))
        self.label_25.setText(QCoreApplication.translate("Form", u" NMS\u9608\u503c\uff1a", None))
        self.label_nms_thres.setText(QCoreApplication.translate("Form", u"0.45", None))
        self.groupBox_4.setTitle(QCoreApplication.translate("Form", u"\u7cfb\u7edf\u6027\u80fd", None))
        self.label_21.setText(QCoreApplication.translate("Form", u"\u63a8\u7406FPS\uff1a", None))
        self.label_9.setText(QCoreApplication.translate("Form", u"\u753b\u9762FPS\uff1a", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_monitor), QCoreApplication.translate("Form", u"\u76d1\u89c6", None))
        self.groupBox_7.setTitle(QCoreApplication.translate("Form", u"TTC\u5206\u6790", None))
        self.label_5.setText(QCoreApplication.translate("Form", u"\u63d0\u793a\uff1a", None))
        self.label_prompt.setText(QCoreApplication.translate("Form", u"TextLabel", None))
        self.groupBox_8.setTitle(QCoreApplication.translate("Form", u"\u76ee\u6807\u8ddd\u79bb\u5206\u6790", None))
        self.label_42.setText(QCoreApplication.translate("Form", u"\u63d0\u793a\uff1a", None))
        self.label_method_prompt.setText(QCoreApplication.translate("Form", u"TextLabel", None))
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
        self.label_33.setText(QCoreApplication.translate("Form", u"\u6807\u7b7e\u6587\u4ef6\uff1a", None))
        self.btn_label_browse.setText(QCoreApplication.translate("Form", u"\u6d4f\u89c8", None))
        self.label_35.setText(QCoreApplication.translate("Form", u"\u5f53\u524d\u6807\u7b7e\uff1a", None))
        self.label_label_path.setText(QCoreApplication.translate("Form", u"\u5f53\u524d\u6807\u7b7e", None))
        self.label_36.setText(QCoreApplication.translate("Form", u"\u786c\u4ef6\u52a0\u901f\u5668\uff1a", None))
        self.combo_hardware_accel.setItemText(0, QCoreApplication.translate("Form", u"CPU", None))
        self.combo_hardware_accel.setItemText(1, QCoreApplication.translate("Form", u"GPU", None))
        self.combo_hardware_accel.setItemText(2, QCoreApplication.translate("Form", u"NPU", None))

        self.groupBox_12.setTitle(QCoreApplication.translate("Form", u"\u68c0\u6d4b\u914d\u7f6e", None))
        self.label_37.setText(QCoreApplication.translate("Form", u"\u8ffd\u8e2a\u76ee\u6807\u9009\u62e9\uff1a", None))
        self.combo_track_target.setItemText(0, QCoreApplication.translate("Form", u"\uff08\u5c1a\u65e0\u6307\u7eb9\u6863\u6848\uff09", None))

#if QT_CONFIG(tooltip)
        self.combo_track_target.setToolTip(QCoreApplication.translate("Form", u"\u5355\u9009\u4e00\u6761\u6307\u7eb9\u6863\u6848\u4f5c\u4e3a\u552f\u4e00\u8ffd\u8e2a\u76ee\u6807\uff08\u5217\u8868\u6765\u81ea models/person_profile.json\uff09\u3002\u6d4b\u8ddd\u53ea\u5bf9\u88ab\u8ffd\u8e2a\u7684\u8fd9\u4e00\u4e2a\u51fa\u6570\uff1b\u540d\u5b57\u53ef\u7528\u53f3\u4fa7\u6309\u94ae\u6539\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.btn_rename_track_target.setText(QCoreApplication.translate("Form", u"\u91cd\u547d\u540d\u2026", None))
        self.label_29.setText(QCoreApplication.translate("Form", u"\u57fa\u51c6\u5bbd\u5ea6\uff1a", None))
        self.label_base_width.setText(QCoreApplication.translate("Form", u"30", None))
        self.groupBox_14.setTitle(QCoreApplication.translate("Form", u"\u6807\u5b9a\u4e0e\u7cfb\u7edf", None))
        self.label_28.setText(QCoreApplication.translate("Form", u"\u91c7\u6837\u9891\u7387\uff08Hz\uff09\uff1a", None))
        self.label_sample_freq.setText(QCoreApplication.translate("Form", u"30Hz", None))
        self.checkBox.setText(QCoreApplication.translate("Form", u"\u662f\u5426\u542f\u7528\u6df1\u5ea6\u5206\u6790", None))
        self.QPuahButton_calibrate_status.setText(QCoreApplication.translate("Form", u"\u5e94\u7528\u53c2\u6570", None))
        self.label_30.setText(QCoreApplication.translate("Form", u"\u6807\u5b9a\u72b6\u6001\uff1a", None))
        self.label__calibrate_status.setText(QCoreApplication.translate("Form", u"\u672a\u6807\u5b9a", None))
        self.groupBox_profiles.setTitle(QCoreApplication.translate("Form", u"\u6307\u7eb9\u6863\u6848\u7ba1\u7406\uff08\u67e5 / \u6539 / \u5220\uff09", None))
        self.label_profiles_hint.setText(QCoreApplication.translate("Form", u"\u5efa\u6863\u5728\u300c\u6807\u5b9a\u300d\u9875\u7b2c\u4e09\u6b65\u3002\u8fd9\u91cc\u7ba1\u5df2\u5efa\u7684\u6863\uff1a\u9009\u4e2d\u4e00\u6761\u53ef\u4ee5\u6539\u540d\u6216\u5220\u9664\u3002\u5220\u9664\u4f1a\u7acb\u523b\u5199\u76d8\u3001\u4e0d\u53ef\u64a4\u9500\uff1b\u82e5\u5220\u7684\u6b63\u662f\u8ffd\u8e2a\u76ee\u6807\uff0c\u8ffd\u8e2a\u76ee\u6807\u4f1a\u540c\u65f6\u88ab\u53d6\u6d88\u3002", None))
        self.btn_profile_rename.setText(QCoreApplication.translate("Form", u"\u6539\u540d\u2026", None))
        self.btn_profile_delete.setText(QCoreApplication.translate("Form", u"\u5220\u9664", None))
        self.btn_profile_refresh.setText(QCoreApplication.translate("Form", u"\u5237\u65b0\u5217\u8868", None))
        self.label_profile_detail.setText(QCoreApplication.translate("Form", u"\uff08\u9009\u4e2d\u4e00\u6761\u6863\u6848\uff0c\u8fd9\u91cc\u663e\u793a\u5b83\u7684\u6765\u6e90\u3001\u6837\u672c\u91cf\u4e0e\u5d4c\u5165\u72b6\u6001\uff09", None))
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
        self.groupBox_play_plot.setTitle(QCoreApplication.translate("Form", u"\u6d4b\u8ddd\u66f2\u7ebf\uff08\u5f55\u5236/\u56de\u653e\uff09", None))
        self.label_replay_summary.setText(QCoreApplication.translate("Form", u"\u5c1a\u65e0\u56de\u653e\u6570\u636e\u3002", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_record), QCoreApplication.translate("Form", u"\u5f55\u5236\u56de\u653e", None))
        self.label_calibtab_hint.setText(QCoreApplication.translate("Form", u"\u6807\u5b9a\u4e0e\u767b\u8bb0\u5171\u4e09\u4ef6\uff0c\u4e92\u4e0d\u4f9d\u8d56\u3001\u6309\u9700\u505a\uff1a\u2460 \u68cb\u76d8\u6807\u5b9a\uff08\u5185\u53c2\u4e0e\u672c\u673a\u8bbe\u5907\u7ed1\u5b9a\uff09\u2192 \u2461 \u91c7\u6837\u70b9\u6807\u5b9a\uff08\u5b89\u88c5\u9ad8\u5ea6/\u4fef\u89d2\uff09\u2192 \u2462 \u6307\u7eb9\u5efa\u6863\uff08\u8bb0\u4f4f\u8fd9\u4e2a\u4eba\uff09\u3002\u524d\u4e24\u4ef6\u968f\u8bbe\u5907\u505a\u4e00\u6b21\uff0c\u7b2c\u4e09\u4ef6\u6bcf\u6362\u4e00\u4e2a\u4eba\u505a\u4e00\u6b21\u3002\u4e09\u4ef6\u90fd\u8981\u770b\u7740\u4e0b\u9762\u7684\u753b\u9762\u64cd\u4f5c\u3002", None))
        self.groupBox_calib_preview.setTitle(QCoreApplication.translate("Form", u"\u753b\u9762\uff08\u5e26\u68c0\u6d4b\u6846\u4e0e\u6d4b\u8ddd\uff09", None))
        self.lbl_calib_view.setText(QCoreApplication.translate("Form", u"\u6444\u50cf\u5934\u672a\u8fde\u63a5", None))
        self.groupBox_calib.setTitle(QCoreApplication.translate("Form", u"\u2460 \u68cb\u76d8\u6807\u5b9a\uff08\u5185\u53c2\uff09", None))
        self.label_camera_device.setText(QCoreApplication.translate("Form", u"\u672c\u673a\u6444\u50cf\u5934\uff1a", None))
#if QT_CONFIG(tooltip)
        self.combo_camera_device.setToolTip(QCoreApplication.translate("Form", u"\u7a0b\u5e8f\u56fa\u5b9a\u6253\u5f00\u7d22\u5f15 0 \u7684\u6444\u50cf\u5934\u3002\u672c\u673a\u53ea\u6709\u4e00\u53f0\u65f6\u4f1a\u81ea\u52a8\u786e\u8ba4\uff1b\u6709\u591a\u53f0\u65f6\u8bf7\u5728\u8fd9\u91cc\u6307\u660e\u7a0b\u5e8f\u6b63\u5728\u7528\u7684\u662f\u54ea\u4e00\u53f0\u2014\u2014\u6807\u5b9a\u7ed3\u679c\u6309\u8bbe\u5907\u5206\u522b\u4fdd\u5b58\uff0c\u6362\u76f8\u673a\u4e0d\u4f1a\u6df7\u7528\u522b\u4eba\u7684\u5185\u53c2\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_camera_status.setText(QCoreApplication.translate("Form", u"\u6b63\u5728\u8bc6\u522b\u6444\u50cf\u5934\u2026\u2026", None))
#if QT_CONFIG(tooltip)
        self.btn_camera_bind.setToolTip(QCoreApplication.translate("Form", u"\u628a\u5f53\u524d\u5df2\u7ecf\u52a0\u8f7d\u7684\u6807\u5b9a\u8ba4\u5230\u8fd9\u53f0\u8bbe\u5907\u540d\u4e0b\u3002\u9002\u7528\u4e8e\u300c\u5347\u7ea7\u540e\u6cbf\u7528\u7740\u65e7\u6807\u5b9a\u6587\u4ef6\u3001\u4e14\u786e\u5b9a\u5c31\u662f\u8fd9\u53f0\u76f8\u673a\u62cd\u7684\u300d\u2014\u2014\u4e0d\u60f3\u518d\u6807\u4e00\u6b21\u5c31\u70b9\u5b83\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.btn_camera_bind.setText(QCoreApplication.translate("Form", u"\u628a\u5f53\u524d\u6807\u5b9a\u7ed1\u5b9a\u5230\u672c\u8bbe\u5907", None))
#if QT_CONFIG(tooltip)
        self.btn_camera_scan.setToolTip(QCoreApplication.translate("Form", u"\u91cd\u65b0\u679a\u4e3e\u4e00\u6b21\u672c\u673a\u6444\u50cf\u5934\uff08\u63d2\u62d4\u8bbe\u5907\u540e\u7528\uff09\u3002\u6b63\u5e38\u8bc6\u522b\u662f\u6beb\u79d2\u7ea7\u7684\uff0c\u70b9\u5b83\u4e0d\u4f1a\u6709\u660e\u663e\u7b49\u5f85\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.btn_camera_scan.setText(QCoreApplication.translate("Form", u"\u91cd\u65b0\u68c0\u6d4b\u8bbe\u5907", None))
        self.label_31.setText(QCoreApplication.translate("Form", u"\u68cb\u76d8\u683c\u5185\u89d2\u70b9\uff1a", None))
        self.label_39.setText(QCoreApplication.translate("Form", u"\u00d7", None))
        self.label_40.setText(QCoreApplication.translate("Form", u"\u65b9\u683c\u8fb9\u957f\uff08mm\uff09\uff1a", None))
#if QT_CONFIG(tooltip)
        self.spin_square_mm.setToolTip(QCoreApplication.translate("Form", u"\u4ee5\u6253\u5370\u540e\u5b9e\u6d4b\u4e3a\u51c6\uff1a\u91cf\u56fe\u4e0a\u90a3\u6761 100mm \u6821\u9a8c\u5c3a\u2014\u2014\u6b63\u597d 100mm \u586b 18.0\uff0c\u5426\u5219\u586b\u300c18 \u00d7 \u5b9e\u6d4b\u91cf \u00f7 100\u300d\u3002\u672c\u673a\u6253\u5370\u673a\u5b9e\u6d4b 17.1mm\uff08\u7a0b\u5e8f\u9ed8\u8ba4\u503c\uff09\u3002\u586b\u9519\u8fd9\u4e00\u683c\uff0c\u5168\u90e8\u8ddd\u79bb\u7b49\u6bd4\u9519\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.label_41.setText(QCoreApplication.translate("Form", u"\u76f8\u673a\u4fef\u4ef0\u89d2\uff08\u00b0\uff09\uff1a", None))
        self.label_camera_height.setText(QCoreApplication.translate("Form", u"\u76f8\u673a\u5b89\u88c5\u9ad8\u5ea6\uff08m\uff09\uff1a", None))
#if QT_CONFIG(tooltip)
        self.spin_camera_height.setToolTip(QCoreApplication.translate("Form", u"\u955c\u5934\u4e2d\u5fc3\u5230\u5730\u9762\u7684\u9ad8\u5ea6\uff08\u7c73\uff09\u3002\u53ef\u4ee5\u5377\u5c3a\u91cf\uff0c\u4e5f\u53ef\u4ee5\u5728\u300c\u76d1\u89c6\u300d\u9875\u7528\u300c\u5b89\u88c5\u53c2\u6570\u81ea\u6807\u5b9a\u300d\u89e3\u51fa\u6765\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.btn_calib_capture.setText(QCoreApplication.translate("Form", u"\u5f00\u59cb\u91c7\u96c6", None))
        self.btn_calib_solve.setText(QCoreApplication.translate("Form", u"\u6c42\u89e3\u5e76\u4fdd\u5b58", None))
        self.label_calib_info.setText(QCoreApplication.translate("Form", u"\u672a\u91c7\u96c6\u3002\u70b9\u300c\u5f00\u59cb\u91c7\u96c6\u300d\uff0c\u8ba9\u68cb\u76d8\u683c\u5728\u753b\u9762\u4e2d\u53d8\u6362\u4f4d\u7f6e\u4e0e\u503e\u659c\u89d2\uff1b\u91c7\u591f 10 \u5e27\u540e\u70b9\u300c\u6c42\u89e3\u5e76\u4fdd\u5b58\u300d\u3002", None))
        self.groupBox_mount.setTitle(QCoreApplication.translate("Form", u"\u2461 \u91c7\u6837\u70b9\u6807\u5b9a\uff08\u5b89\u88c5\u53c2\u6570\uff09", None))
        self.label_mount_hint.setText(QCoreApplication.translate("Form", u"\u8ba9\u76ee\u6807\u7ad9\u5230\u5377\u5c3a\u91cf\u597d\u7684\u5df2\u77e5\u8ddd\u79bb\u5904\u3001\u9759\u6b62\uff0c\u70b9\u300c\u8bb0\u4e3a\u91c7\u6837\u70b9\u300d\u3002\u63a8\u8350 2 m / 5 m / 10 m \u4e09\u70b9\uff08\u4e24\u70b9\u65e0\u6cd5\u81ea\u67e5\u9519\u8bef\u6807\u8bb0\uff09\uff0c\u7136\u540e\u70b9\u300c\u6c42\u89e3\u5b89\u88c5\u53c2\u6570\u300d\u3002", None))
        self.label_known_dist.setText(QCoreApplication.translate("Form", u"\u5df2\u77e5\u8ddd\u79bb\uff08m\uff09\uff1a", None))
        self.btn_mark_known.setText(QCoreApplication.translate("Form", u"\u8bb0\u4e3a\u91c7\u6837\u70b9", None))
        self.btn_solve_mount.setText(QCoreApplication.translate("Form", u"\u6c42\u89e3\u5b89\u88c5\u53c2\u6570", None))
        self.label_mount_status.setText(QCoreApplication.translate("Form", u"\u5c1a\u672a\u91c7\u6837 \u2014\u2014 \u70b9\u300c\u8bb0\u4e3a\u91c7\u6837\u70b9\u300d\u540e\uff0c\u8fd9\u91cc\u4f1a\u5217\u51fa\u6bcf\u4e2a\u5df2\u8bb0\u5f55\u7684\u8ddd\u79bb\u4e0e\u5e95\u8fb9\u50cf\u7d20\u3002", None))
        self.groupBox_enroll.setTitle(QCoreApplication.translate("Form", u"\u2462 \u6307\u7eb9\u5efa\u6863\uff08\u8ba9\u7a0b\u5e8f\u8bb0\u4f4f\u8fd9\u4e2a\u4eba\uff09", None))
        self.label_enroll_hint.setText(QCoreApplication.translate("Form", u"\u8ba9\u88ab\u767b\u8bb0\u8005\u8d70\u5230\u753b\u9762\u4e2d\u95f4\uff083-10 m\uff09\uff0c\u70b9\u300c\u5f00\u59cb\u5efa\u6863\u300d\u540e\u7ad9\u5b9a\u7ea6 3 \u79d2\uff0c\u6512\u591f\u7a33\u5b9a\u7a97\u53e3\u5373\u81ea\u52a8\u8bb0\u5165\u6863\u6848\u3002\u53ef\u8fde\u7eed\u7ed9\u591a\u4eba\u5efa\u6863\uff1a\u8ba9\u4ed6\u8d70\u51fa\u753b\u9762\uff0c\u6362\u4e0b\u4e00\u4e2a\u4eba\u518d\u8d70\u8fdb\u6765\u3002\u4e0b\u9762\u300c\u753b\u9762\u300d\u7ec4\u4f1a\u5b9e\u65f6\u663e\u793a\u53cd\u89e3\u51fa\u7684\u8eab\u9ad8/\u80a9\u5bbd\uff1b\u6570\u503c\u8d8a\u8fc7\u5408\u7406\u533a\u95f4\u4f1a\u76f4\u63a5\u5224\u5931\u8d25\u5e76\u8bf4\u660e\u539f\u56e0\uff0c\u4e0d\u4f1a\u628a\u53ef\u7591\u503c\u9759\u9ed8\u5199\u8fdb\u6863\u6848\u3002", None))
        self.label_enroll_dist.setText(QCoreApplication.translate("Form", u"\u91c7\u6837\u70b9\u8ddd\u79bb\uff08m\uff09\uff1a", None))
#if QT_CONFIG(tooltip)
        self.spin_enroll_distance.setToolTip(QCoreApplication.translate("Form", u"\u7559 0 = \u7528\u6d4b\u8ddd\u503c\u53cd\u89e3\u8eab\u9ad8/\u80a9\u5bbd\uff08\u9700\u5148\u5b8c\u6210\u5185\u53c2 + \u5b89\u88c5\u53c2\u6570\u6807\u5b9a\uff09\uff1b\u586b\u5927\u4e8e 0 = \u7528\u8fd9\u4e2a\u624b\u586b\u8ddd\u79bb\uff0c\u7ed5\u8fc7\u6807\u5b9a\u3002\u8ddd\u79bb\u662f\u955c\u5934\u5230\u4eba\u7684\u6c34\u5e73\u8ddd\u79bb\uff0c\u5377\u5c3a\u91cf\u3002", None))
#endif // QT_CONFIG(tooltip)
        self.btn_enroll_toggle.setText(QCoreApplication.translate("Form", u"\u5f00\u59cb\u5efa\u6863", None))
        self.label_enroll_status.setText(QCoreApplication.translate("Form", u"\u672a\u5f00\u59cb", None))
        self.label_enroll_match.setText(QCoreApplication.translate("Form", u"\u5339\u914d\uff1a\u672c\u5e27\u672a\u8ba1\u7b97", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_calib), QCoreApplication.translate("Form", u"\u6807\u5b9a", None))
    # retranslateUi

