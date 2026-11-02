"""对话里的结构化待办草稿：确认才入库，丢弃只删草稿。"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QFormLayout, QFrame, QHBoxLayout, QLabel, QMessageBox,
                             QPushButton, QVBoxLayout, QWidget)

from .common import local_time, time_input, iso_input, repeat_input
from ..recurrence import REPEAT_LABELS
from . import tokens as T
from .components import StatePill
from .controls import LineEdit as QLineEdit
from .home import Line
from .theme import mono_font, tokens


def _label(size, token_name, weight=QFont.Normal, wrap=False, mono=False):
    label = QLabel()
    font = mono_font(size) if mono else QFont(T.FONT_UI)
    font.setPixelSize(size)
    font.setWeight(weight)
    label.setFont(font)
    label.setWordWrap(wrap)
    label._token_name = token_name
    label._size = size
    label._weight = weight
    label._mono = mono
    return label


def _style_label(label):
    weights = {QFont.DemiBold: 600, QFont.Bold: 700}
    family = f'"{T.FONT_MONO}","Consolas",monospace' if label._mono else f'"{T.FONT_UI}"'
    weight = weights.get(label._weight)
    label.setStyleSheet(f'font-family:{family};font-size:{label._size}px;'
                        f'{f"font-weight:{weight};" if weight else ""}'
                        f'color:{getattr(tokens(), label._token_name)};background:transparent;')


class DraftCard(QFrame):
    saved = pyqtSignal(str)
    removed = pyqtSignal()

    def __init__(self, store, task, session_id, parent=None):
        super().__init__(parent)
        self.setObjectName('draftCard')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.store = store
        self.session_id = session_id
        self.note = str(task.get('note') or '')
        self.repeat_rule = task.get('repeat_rule', task.get('repeat', 'none'))
        self.draft_id = task.get('id') or store.save_draft(
            task['title'], task['due_at'], session_id=session_id,
            repeat=self.repeat_rule, note=self.note)
        self._editing = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QFrame()
        self.header.setAttribute(Qt.WA_StyledBackground, True)
        head = QHBoxLayout(self.header)
        head.setContentsMargins(12, 7, 12, 7)
        head.setSpacing(8)
        self.head_label = _label(10, 'brand_press', QFont.DemiBold, mono=True)
        self.head_label.setText('待办草稿')
        head.addWidget(self.head_label)
        head.addStretch(1)
        head.addWidget(StatePill('待你确认', 'soon'))
        outer.addWidget(self.header)

        self.rows = QWidget()
        rows = QVBoxLayout(self.rows)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        self.title_value = _label(12, 'ink', QFont.DemiBold, wrap=True)
        self.note_value = _label(12, 'ink_3', QFont.Normal, wrap=True)
        self.time_value = _label(12, 'ink', QFont.DemiBold, mono=True)
        self.repeat_value = _label(12, 'ink', QFont.DemiBold)
        self.channel_value = _label(12, 'ink', QFont.DemiBold)
        self.title_value.setText(task['title'])
        self.note_value.setText(self.note or '未补充')
        self.time_value.setText(local_time(task['due_at']))
        self.repeat_value.setText(REPEAT_LABELS.get(self.repeat_rule, '不重复'))
        self.channel_value.setText('桌面气泡')
        rows.addWidget(self._field('标题', self.title_value))
        rows.addWidget(Line())
        rows.addWidget(self._field('背景', self.note_value))
        rows.addWidget(Line())
        rows.addWidget(self._field('时间', self.time_value))
        rows.addWidget(Line())
        rows.addWidget(self._field('重复', self.repeat_value))
        rows.addWidget(Line())
        rows.addWidget(self._field('提醒', self.channel_value))
        outer.addWidget(self.rows)

        self.editor = QWidget()
        form = QFormLayout(self.editor)
        form.setContentsMargins(12, 10, 12, 10)
        form.setSpacing(8)
        self.title = QLineEdit(task['title'])
        self.title.setMaxLength(200)
        self.date = time_input(task['due_at'])
        self.repeat = repeat_input(self.repeat_rule)
        form.addRow('标题', self.title)
        form.addRow('提醒时间', self.date)
        form.addRow('重复', self.repeat)
        self.editor.hide()
        outer.addWidget(self.editor)

        self.footer = QFrame()
        self.footer.setAttribute(Qt.WA_StyledBackground, True)
        actions = QHBoxLayout(self.footer)
        actions.setContentsMargins(12, 9, 12, 9)
        actions.setSpacing(6)
        self.save_button = self._action('直接创建', self.confirm, primary=True)
        self.edit_button = self._action('我要改时间', self.toggle_editor)
        self.discard_button = self._action('先放着', self.discard)
        actions.addWidget(self.save_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.discard_button)
        actions.addStretch(1)
        outer.addWidget(self.footer)

        self.title.textChanged.connect(self.persist)
        self.date.dateTimeChanged.connect(self.persist)
        self.repeat.currentIndexChanged.connect(self.persist)
        self.refresh_theme()

    def _field(self, key, value):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(12, 7, 12, 7)
        row.setSpacing(12)
        name = _label(10, 'ink_3')
        name.setText(key)
        name.setFixedWidth(40)
        row.addWidget(name, 0, Qt.AlignTop)
        row.addWidget(value, 1)
        return holder

    def _action(self, text, callback, primary=False):
        control = QPushButton(text)
        control.setCursor(Qt.PointingHandCursor)
        control.setFixedHeight(28)
        control.clicked.connect(callback)
        control._primary = primary
        return control

    def _time_text(self):
        return self.date.text()

    def _due_display(self):
        self.time_value.setText(self._time_text())

    def toggle_editor(self):
        self._editing = not self._editing
        self.editor.setVisible(self._editing)
        self.edit_button.setText('收起修改' if self._editing else '我要改时间')

    def persist(self):
        self.repeat_rule = self.repeat.currentData()
        self._due_display()
        self.title_value.setText(self.title.text())
        self.repeat_value.setText(REPEAT_LABELS.get(self.repeat_rule, '不重复'))
        self.store.save_draft(self.title.text(), iso_input(self.date), self.draft_id,
                              self.session_id, self.repeat_rule, self.note)

    def confirm(self):
        try:
            self.persist()
            self.store.confirm_draft(self.draft_id)
            self.save_button.setEnabled(False)
            self.saved.emit(f'已保存：{self.title.text()}，提醒时间 {self.date.text()}，'
                            f'{REPEAT_LABELS[self.repeat.currentData()]}。')
            self.removed.emit()
        except ValueError as exc:
            QMessageBox.warning(self, '无法保存', str(exc))

    def discard(self):
        self.store.discard_draft(self.draft_id)
        self.removed.emit()

    def refresh_theme(self):
        t = tokens()
        self.setStyleSheet(f'QFrame#draftCard{{background:{t.surface};'
                           f'border:1px solid {t.brand_line};border-radius:{T.RADIUS_CARD}px;}}')
        self.header.setStyleSheet(
            f'QFrame{{background:{t.brand_wash};border-top-left-radius:{T.RADIUS_CARD - 1}px;'
            f'border-top-right-radius:{T.RADIUS_CARD - 1}px;}}')
        self.footer.setStyleSheet(
            f'QFrame{{background:{t.surface_2};border-top:1px solid {t.border};'
            f'border-bottom-left-radius:{T.RADIUS_CARD - 1}px;'
            f'border-bottom-right-radius:{T.RADIUS_CARD - 1}px;}}')
        for label in self.findChildren(QLabel):
            if hasattr(label, '_token_name'):
                _style_label(label)
        self.title.setStyleSheet(
            f'QLineEdit{{background:{t.surface};border:1px solid {t.border};border-radius:8px;'
            f'padding:0 8px;color:{t.ink};font-family:"{T.FONT_UI}";font-size:12px;}}')
        for control in (self.save_button, self.edit_button, self.discard_button):
            primary = control._primary
            fill = t.brand if primary else 'transparent'
            color = t.brand_on if primary else t.ink_2
            edge = t.brand if primary else t.border
            control.setStyleSheet(
                f'QPushButton{{background:{fill};color:{color};border:1px solid {edge};'
                f'border-radius:8px;padding:0 11px;font-family:"{T.FONT_UI}";font-size:11px;}}'
                f'QPushButton:hover{{border-color:{t.brand};}}'
                f'QPushButton:disabled{{color:{t.ink_4};border-color:{t.border};}}')
        for line in self.findChildren(Line):
            line.update()


# 0.30 旧草稿卡实现保留备查（P4 结构化草稿前版本，需回退时可整体替换上方实现）：
_LEGACY_DRAFT_CARD_030 = r'''
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QFormLayout, QLineEdit, QHBoxLayout, QMessageBox

from .common import button, time_input, iso_input, repeat_input
from ..recurrence import REPEAT_LABELS
from .controls import LineEdit as QLineEdit


class DraftCard(QWidget):
    saved = pyqtSignal(str)
    removed = pyqtSignal()

    def __init__(self, store, task, session_id, parent=None):
        super().__init__(parent)
        self.setObjectName('draftCard')
        from .theme import add_soft_shadow
        add_soft_shadow(self)
        self.store = store
        self.session_id = session_id
        self.draft_id = task.get('id') or store.save_draft(task['title'], task['due_at'], session_id=session_id, repeat=task.get('repeat', 'none'))
        form = QFormLayout(self)
        form.setContentsMargins(16, 14, 16, 14)
        self.title = QLineEdit(task['title'])
        self.title.setMaxLength(200)
        self.date = time_input(task['due_at'])
        form.addRow('待确认', self.title)
        form.addRow('提醒时间', self.date)
        self.repeat = repeat_input(task.get('repeat_rule', task.get('repeat', 'none')))
        form.addRow('重复', self.repeat)
        actions = QHBoxLayout()
        self.save_button = button('确认保存', self.confirm, actions, primary=True)
        button('丢弃', self.discard, actions)
        form.addRow(actions)
        self.title.textChanged.connect(self.persist)
        self.date.dateTimeChanged.connect(self.persist)
        self.repeat.currentIndexChanged.connect(self.persist)

    def persist(self):
        self.store.save_draft(self.title.text(), iso_input(self.date), self.draft_id, self.session_id, self.repeat.currentData())

    def confirm(self):
        try:
            self.persist()
            self.store.confirm_draft(self.draft_id)
            self.save_button.setEnabled(False)
            self.saved.emit(f'已保存：{self.title.text()}，提醒时间 {self.date.text()}，{REPEAT_LABELS[self.repeat.currentData()]}。')
            self.removed.emit()
        except ValueError as exc:
            QMessageBox.warning(self, '无法保存', str(exc))

    def discard(self):
        self.store.discard_draft(self.draft_id)
        self.removed.emit()
'''
