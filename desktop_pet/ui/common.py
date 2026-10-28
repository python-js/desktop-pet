from datetime import datetime, timedelta

from PyQt5.QtCore import QDateTime
from PyQt5.QtWidgets import (QDateTimeEdit, QDialog, QDialogButtonBox, QFormLayout,
                             QLineEdit, QPushButton, QComboBox, QLabel, QHBoxLayout)

from ..core import parse_due
from ..recurrence import REPEAT_LABELS
from .controls import Button as QPushButton, ComboBox as QComboBox
from .controls import CheckBox as QCheckBox
from .controls import PrimaryButton
from .controls import LineEdit as QLineEdit
from .controls import DateTimeEdit as QDateTimeEdit


def repeat_input(rule='none'):
    widget = QComboBox()
    for value, label in REPEAT_LABELS.items():
        widget.addItem(label, value)
    widget.setCurrentIndex(widget.findData(rule))
    return widget


def local_time(value):
    return parse_due(value).astimezone().strftime('%Y-%m-%d %H:%M')


def button(text, action, layout, primary=False):
    layout.setSpacing(8)
    widget = PrimaryButton(text) if primary else QPushButton(text)
    widget.clicked.connect(action)
    layout.addWidget(widget)
    return widget


def time_input(value=None):
    widget = QDateTimeEdit()
    widget.setCalendarPopup(True)
    widget.setDisplayFormat('yyyy-MM-dd HH:mm')
    value = parse_due(value).astimezone() if value else datetime.now().astimezone() + timedelta(hours=1)
    widget.setDateTime(QDateTime(value))
    return widget


def iso_input(widget):
    return widget.dateTime().toPyDateTime().astimezone().isoformat()


class TaskDialog(QDialog):
    def __init__(self, parent, task=None):
        super().__init__(parent)
        self.setWindowTitle('编辑待办' if task else '新增待办')
        self.resize(520, 410)
        form = QFormLayout(self)
        form.setContentsMargins(24, 24, 24, 24)
        form.setSpacing(16)
        heading = QLabel(self.windowTitle())
        heading.setObjectName("sectionTitle")
        form.addRow(heading)
        self.title = QLineEdit(task['title'] if task else '')
        self.title.setMaxLength(200)
        self.date = time_input(task['due_at'] if task else None)
        form.addRow('要做什么', self.title)
        form.addRow('提醒时间', self.date)
        self.repeat = repeat_input(task['repeat_rule'] if task else 'none')
        form.addRow('重复', self.repeat)
        self.dingtalk = QCheckBox('到期时同时发送到钉钉群（仅此待办）')
        self.dingtalk.setChecked(bool(task.get('dingtalk')) if task else False)
        self.dingtalk.setToolTip('需先在设置页配置钉钉机器人；未配置时仍只做本地提醒。')
        form.addRow(self.dingtalk)
        hint = QLabel('完成本次后生成下一次；延期十分钟不改变重复时刻。\n周一至五不区分法定节假日，跨夏令时请重新检查时间。')
        hint.setWordWrap(True)
        form.addRow(hint)
        controls = QHBoxLayout()
        controls.addStretch()
        button('取消', self.reject, controls)
        button('保存待办', self.accept, controls, primary=True)
        form.addRow(controls)
