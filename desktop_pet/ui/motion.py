"""Preview generated motion before replacing any active sequences."""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSlider
from ..animations import ACTION_LABELS
from ..motion import generate_motion
from .common import button
from .cutout import ImagePreview
from .controls import ComboBox as QComboBox


class MotionDialog(QDialog):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setWindowTitle('单图基础动作 · 预览')
        self.resize(570, 530)
        self.image = image
        self.frames = generate_motion(image)
        self.index = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        note = QLabel('使用当前静态宠物图片，本地生成呼吸、弹跳和摇摆。整张图片一起变形，不会生成关节动作或新表情。\n建议先去背景。应用将替换待机、点击、提醒三类动作，可撤销最近一次生成。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.action = QComboBox()
        for key, label in ACTION_LABELS.items():
            self.action.addItem(label, key)
        self.action.currentIndexChanged.connect(self.reset_preview)
        layout.addWidget(self.action)
        self.preview = ImagePreview(self.frames['idle'][0])
        layout.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.strength_label = QLabel('动作幅度：40')
        row.addWidget(self.strength_label)
        self.strength = QSlider(Qt.Horizontal)
        self.strength.setRange(0, 100)
        self.strength.setValue(40)
        self.strength.valueChanged.connect(lambda v: self.strength_label.setText(f'动作幅度：{v}'))
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.setInterval(120)
        self.update_timer.timeout.connect(self.regenerate)
        self.strength.valueChanged.connect(lambda: self.update_timer.start())
        row.addWidget(self.strength, 1)
        layout.addLayout(row)
        buttons = QHBoxLayout()
        button('应用三类动作', self.accept, buttons, primary=True)
        button('取消', self.reject, buttons)
        layout.addLayout(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(100)

    def reset_preview(self):
        self.index = 0
        if hasattr(self, 'preview'):
            self.preview.image = self.frames[self.action.currentData()][0]
            self.preview.update()

    def regenerate(self):
        self.update_timer.stop()
        self.frames = generate_motion(self.image, self.strength.value())
        self.reset_preview()

    def advance(self):
        self.index = (self.index + 1) % 16
        self.preview.image = self.frames[self.action.currentData()][self.index]
        self.preview.update()

    def accept(self):
        # Keyboard changes to the slider may not emit sliderReleased.
        self.regenerate()
        super().accept()

    def done(self, result):
        self.timer.stop()
        self.update_timer.stop()
        super().done(result)
