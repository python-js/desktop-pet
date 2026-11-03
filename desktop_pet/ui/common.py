from contextlib import contextmanager
from datetime import datetime, timedelta

from PyQt5 import sip
from PyQt5.QtCore import QDateTime, QTimer
from PyQt5.QtWidgets import (QDateTimeEdit, QDialog, QFrame, QLineEdit, QPushButton,
                             QComboBox, QLabel, QHBoxLayout, QTextBrowser, QVBoxLayout)

from ..core import parse_due
from ..recurrence import REPEAT_LABELS
from .controls import Button as QPushButton, ComboBox as QComboBox
from .controls import CheckBox as QCheckBox
from .controls import PrimaryButton
from .controls import LineEdit as QLineEdit
from .controls import DateTimeEdit as QDateTimeEdit

_freeze_depth = {}


def _thaw(widget):
    try:
        if sip.isdeleted(widget):
            return
        # 父控件冻结时子控件读到的 updatesEnabled() 也是 False，必须显式恢复，
        # 否则子控件会一直留在“显式禁用更新”的状态。
        widget.setUpdatesEnabled(True)
        parent = widget.parentWidget()
        if parent is not None and not parent.updatesEnabled():
            # 祖先仍在冻结中：由祖先的 thaw 一并重绘，避免同一改动分两帧闪现。
            return
        widget.update()
    except RuntimeError:
        pass


@contextmanager
def frozen_updates(widget):
    """冻结绘制到下一轮事件循环再恢复，把布局/滚动条的二次重绘合并为一帧。"""
    depth = _freeze_depth.get(widget, 0)
    if depth == 0:
        widget.setUpdatesEnabled(False)
    _freeze_depth[widget] = depth + 1
    try:
        yield
    finally:
        depth = _freeze_depth.get(widget, 1) - 1
        if depth:
            _freeze_depth[widget] = depth
        else:
            _freeze_depth.pop(widget, None)
            QTimer.singleShot(0, lambda w=widget: _thaw(w))


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


def dialog_heading(layout, eyebrow, title, subtitle):
    head = QVBoxLayout()
    head.setSpacing(4)
    for text, name in ((eyebrow, 'dialogEyebrow'), (title, 'dialogTitle'), (subtitle, 'dialogSubtitle')):
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(name == 'dialogSubtitle')
        head.addWidget(label)
    layout.addLayout(head)


def field_group(layout, text, widget):
    label = QLabel(text)
    label.setObjectName('fieldLabel')
    layout.addWidget(label)
    layout.addWidget(widget)
    return widget


def hint_box(layout, text):
    frame = QFrame()
    frame.setObjectName('dialogHint')
    box = QVBoxLayout(frame)
    box.setContentsMargins(12, 10, 12, 10)
    label = QLabel(text)
    label.setObjectName('dialogHintText')
    label.setWordWrap(True)
    box.addWidget(label)
    layout.addWidget(frame)
    return frame


class TaskDialog(QDialog):
    def __init__(self, parent, task=None):
        super().__init__(parent)
        self.setWindowTitle('编辑待办' if task else '新增待办')
        self.resize(520, 470)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
        dialog_heading(layout, '待办事项 · TASK', self.windowTitle(),
                       '写清要做什么和时间，到点会提醒；完成后可在待办页回看。')
        layout.addSpacing(6)

        self.title = QLineEdit(task['title'] if task else '')
        self.title.setMaxLength(200)
        self.title.setPlaceholderText('例如：整理本周周报并发给组长')
        field_group(layout, '要做什么', self.title)

        pair = QHBoxLayout()
        pair.setSpacing(12)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(8)
        right.setSpacing(8)
        self.date = field_group(left, '提醒时间', time_input(task['due_at'] if task else None))
        self.repeat = field_group(right, '重复', repeat_input(task['repeat_rule'] if task else 'none'))
        pair.addLayout(left, 1)
        pair.addLayout(right, 1)
        layout.addLayout(pair)

        self.dingtalk = QCheckBox('到期时同时发送到钉钉群（仅此待办）')
        self.dingtalk.setChecked(bool(task.get('dingtalk')) if task else False)
        self.dingtalk.setToolTip('需先在设置页配置钉钉机器人；未配置时仍只做本地提醒。')
        layout.addWidget(self.dingtalk)

        hint_box(layout, '完成本次后生成下一次；延期十分钟不改变重复时刻。\n'
                         '周一至五不区分法定节假日，跨夏令时请重新检查时间。')
        layout.addStretch(1)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addStretch(1)
        button('取消', self.reject, controls)
        self.save_button = button('保存待办', self.accept, controls, primary=True)
        self.save_button.setDefault(True)
        layout.addLayout(controls)
        self.resize(520, self.sizeHint().height())
        self.title.setFocus()


class PlanDialog(QDialog):
    def __init__(self, parent, prompt, uses_model):
        super().__init__(parent)
        self.setWindowTitle('今日规划 · 确认待办快照')
        self.resize(650, 540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        dialog_heading(layout, '今日规划 · TODAY',
                       '确认今日待办快照',
                       '确认后会将以下待办标题、时间及本对话最近消息发送给已配置的模型服务。'
                       if uses_model else '当前未配置模型，确认后仅在本地整理清单。')
        self.preview = QTextBrowser()
        self.preview.setObjectName('planPreview')
        self.preview.setOpenExternalLinks(False)
        self.preview.setPlainText(prompt)
        layout.addWidget(self.preview, 1)
        hint_box(layout, '发送内容仅包含待办标题、时间和最近对话，不含 API Key；'
                         '确认后可在历史中重试。' if uses_model else
                         '不会连接模型，也不会改动待办；清单只写入当前对话。')
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addStretch(1)
        button('取消', self.reject, controls)
        self.accept_button = button('发送给模型' if uses_model else '生成本地清单',
                                    self.accept, controls, primary=True)
        self.accept_button.setDefault(True)
        layout.addLayout(controls)
