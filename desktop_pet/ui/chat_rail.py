"""对话右栏：本段对话产物、今天安排、快捷动作与提醒方式。"""
from datetime import datetime

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QSizePolicy, QVBoxLayout, QWidget)

from ..core import parse_due
from ..recurrence import REPEAT_LABELS
from . import icons
from . import tokens as T
from .components import ElidedLabel, Panel, StatePill
from .home import Line
from .theme import mono_font, tokens

RAIL_W = 296
_WEIGHTS = {QFont.DemiBold: 600, QFont.Bold: 700}


def _label(size, token_name, weight=QFont.Normal, wrap=False, mono=False, spacing=0.0):
    label = QLabel()
    font = mono_font(size) if mono else QFont(T.FONT_UI)
    font.setPixelSize(size)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    label.setFont(font)
    label.setWordWrap(wrap)
    label._token_name = token_name
    label._size = size
    label._weight = weight
    label._mono = mono
    label._spacing = spacing
    label.setStyleSheet(_label_style(label))
    return label


def _label_style(label):
    family = f'"{T.FONT_MONO}","Consolas",monospace' if label._mono else f'"{T.FONT_UI}"'
    weight = _WEIGHTS.get(label._weight)
    return (f'font-family:{family};font-size:{label._size}px;'
            f'{f"font-weight:{weight};" if weight else ""}'
            f'color:{getattr(tokens(), label._token_name)};background:transparent;')


def _mono(size, token_name, weight=QFont.Normal, spacing=0.0):
    return _label(size, token_name, weight, False, True, spacing)


def _local(value):
    return parse_due(value).astimezone()


class _TodayItem(QWidget):
    """今日安排的一行：整行可点，逾期标签在右侧。"""

    activated = pyqtSignal(str)

    def __init__(self, task, done=False, parent=None):
        super().__init__(parent)
        self.task_id = task['id']
        self.done = done
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 5, 0, 5)
        row.setSpacing(6)
        self.tick = QLabel()
        self.tick.setFixedSize(14, 14)
        row.addWidget(self.tick)
        title = _label(12, 'ink_3' if done else 'ink_2')
        title.setText(task['title'])
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(title, 1)
        when = _mono(10, 'ink_3')
        due = _local(task['due_at'])
        when.setText(due.strftime('%H:%M'))
        row.addWidget(when)
        self.pill = None
        if not done and due < datetime.now().astimezone():
            self.pill = StatePill('逾期', 'over')
            row.addWidget(self.pill)
        self.refresh_theme()

    def refresh_theme(self):
        t = tokens()
        self.tick.setPixmap(icons.pixmap('check' if self.done else 'clock',
                                         t.calm if self.done else t.ink_3, 12))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.activated.emit(self.task_id)


class ChatRail(QScrollArea):
    open_task = pyqtSignal(str)
    mute_task = pyqtSignal(str)
    plan_requested = pyqtSignal()
    open_tasks = pyqtSignal()
    open_settings = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.latest_task = None
        self.session_title = '默认对话'
        self.message_count = 0
        self.model_text = '本地规则'
        self.setFixedWidth(RAIL_W)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.body = QWidget()
        self.body.setObjectName('chatRailBody')
        self.box = QVBoxLayout(self.body)
        self.box.setContentsMargins(16, 20, 16, 20)
        self.box.setSpacing(18)
        self.setWidget(self.body)
        self.refresh()

    def set_session(self, title, message_count, model_text):
        self.session_title = title or '默认对话'
        self.message_count = int(message_count or 0)
        self.model_text = model_text or '本地规则'
        self.refresh()

    def refresh_theme(self):
        self.refresh()

    def _clear(self):
        while self.box.count():
            item = self.box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def _eyebrow(self, text):
        return _mono(10, 'ink_3', QFont.DemiBold, 0.5)

    def _set_eyebrow(self, label, text):
        label.setText(text)
        return label

    def _kv(self, key, value, mono=False, elide=False):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        name = _mono(10, 'ink_3')
        name.setText(key)
        name.setFixedWidth(34)
        row.addWidget(name)
        if elide:
            text = ElidedLabel(value)
            font = mono_font(12) if mono else QFont(T.FONT_UI)
            font.setPixelSize(12)
            text.setFont(font)
            text.set_color(tokens().ink_2)
        else:
            text = _label(12, 'ink_2', mono=mono, wrap=True)
            text.setText(value)
        row.addWidget(text, 1)
        return holder

    def _action(self, text, icon_name, callback):
        control = QPushButton(text)
        control.setCursor(Qt.PointingHandCursor)
        control.setFixedHeight(30)
        control.setIcon(icons.icon(icon_name, tokens().ink_2, 14))
        control.setIconSize(QSize(14, 14))
        control.clicked.connect(callback)
        control._icon_name = icon_name
        return control

    def _chip_row(self, task):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(4)
        repeat = REPEAT_LABELS.get(task.get('repeat_rule', 'none'), '不重复')
        if repeat != '不重复':
            row.addWidget(StatePill(repeat, 'today', 'cal'))
        if task.get('dingtalk'):
            row.addWidget(StatePill('钉钉', 'info', 'ding'))
        row.addStretch(1)
        return holder

    def refresh(self):
        self._clear()
        now = datetime.now().astimezone()
        pending = [dict(row) for row in self.store.pending()]
        chat_tasks = [row for row in pending if row.get('source') in ('chat', 'draft')]
        chat_tasks.sort(key=lambda row: str(row.get('created_at') or ''), reverse=True)
        self.latest_task = chat_tasks[0] if chat_tasks else None

        self.box.addWidget(self._eyebrow('这段对话落到了什么'))
        heading = QWidget()
        heading_row = QHBoxLayout(heading)
        heading_row.setContentsMargins(0, 0, 0, 0)
        heading_row.setSpacing(6)
        mark = QLabel()
        mark.setPixmap(icons.pixmap('todo', tokens().brand, 14))
        mark.setFixedSize(14, 14)
        heading_row.addWidget(mark)
        count = len(chat_tasks)
        title = _label(12, 'ink_2', QFont.DemiBold)
        title.setText(f'{count} 条待办已创建' if count else '还没有落到待办')
        heading_row.addWidget(title, 1)
        self.box.addWidget(heading)

        if self.latest_task is None:
            empty = _label(12, 'ink_3', wrap=True)
            empty.setText('说清事项和时间，小满会先给出草稿；确认后才写入待办。')
            self.box.addWidget(empty)
        else:
            panel = Panel()
            inner = QVBoxLayout(panel)
            inner.setContentsMargins(12, 11, 12, 11)
            inner.setSpacing(5)
            task_title = _label(12, 'ink', QFont.DemiBold, wrap=True)
            task_title.setText(self.latest_task['title'])
            inner.addWidget(task_title)
            due = _local(self.latest_task['due_at'])
            meta = _mono(10, 'ink_3')
            repeat = REPEAT_LABELS.get(self.latest_task.get('repeat_rule', 'none'), '不重复')
            meta.setText(f'{due.strftime("%m月%d日 %H:%M")} · {repeat}')
            inner.addWidget(meta)
            inner.addWidget(self._chip_row(self.latest_task))
            task_id = self.latest_task['id']
            open_button = self._action('打开这条待办', 'arrow',
                                       lambda: self.open_task.emit(task_id))
            inner.addWidget(open_button)
            muted = str(self.latest_task.get('muted_until') or '') == now.date().isoformat()
            mute_text = '今天已静音' if muted else '今天别再说'
            mute_button = self._action(mute_text, 'bell',
                                       lambda: self.mute_task.emit(task_id))
            mute_button.setEnabled(not muted)
            inner.addWidget(mute_button)
            self.box.addWidget(panel)

        self.box.addWidget(Line())
        self.box.addWidget(self._eyebrow('会话信息'))
        self.box.addWidget(self._kv('对话', self.session_title, elide=True))
        self.box.addWidget(self._kv('消息', f'{self.message_count} 条'))
        self.box.addWidget(self._kv('模型', self.model_text, mono=True, elide=True))

        today_items = []
        today = now.date()
        yesterday = [row for row in self.store.history('done')
                     if _local(row['due_at']).date() == today]
        for row in pending:
            if _local(row['due_at']).date() == today:
                today_items.append((dict(row), False))
        for row in yesterday:
            today_items.append((dict(row), True))
        today_items.sort(key=lambda pair: _local(pair[0]['due_at']))
        self.box.addWidget(Line())
        self.box.addWidget(self._set_eyebrow(
            self._eyebrow(''), f'今天安排 · {len(today_items)} 项'))
        if today_items:
            for task, done in today_items[:4]:
                item = _TodayItem(task, done)
                item.activated.connect(self.open_task.emit)
                self.box.addWidget(item)
        else:
            empty = _label(12, 'ink_3')
            empty.setText('今天没有安排。')
            self.box.addWidget(empty)

        self.box.addWidget(Line())
        self.box.addWidget(self._eyebrow('快捷动作'))
        self.box.addWidget(self._action('今日规划', 'cal', self.plan_requested.emit))
        self.box.addWidget(self._action('打开待办', 'todo', self.open_tasks.emit))
        self.box.addWidget(self._action('改提醒设置', 'gear', self.open_settings.emit))

        self.box.addStretch(1)
        self.box.addWidget(Line())
        self.box.addWidget(self._eyebrow('提醒方式'))
        hint = _label(12, 'ink_3', wrap=True)
        hint.setText('桌面气泡加声音；只有标记「钉钉通知」的事才会推群。')
        self.box.addWidget(hint)
        self._style()

    def _style(self):
        t = tokens()
        self.setStyleSheet(f'QScrollArea{{background:{t.surface};border:0;'
                           f'border-left:1px solid {t.border};}}')
        self.body.setStyleSheet(f'QWidget#chatRailBody{{background:{t.surface};}}')
        for label in self.body.findChildren(QLabel):
            if hasattr(label, '_token_name'):
                label.setStyleSheet(_label_style(label))
        for label in self.body.findChildren(ElidedLabel):
            label.set_color(t.ink_2)
        for control in self.body.findChildren(QPushButton):
            if not hasattr(control, '_icon_name'):
                continue
            control.setIcon(icons.icon(control._icon_name, t.ink_2, 14))
            control.setStyleSheet(
                f'QPushButton{{text-align:left;padding:0 8px;border:0;border-radius:8px;'
                f'background:transparent;color:{t.ink_2};font-family:"{T.FONT_UI}";font-size:12px;}}'
                f'QPushButton:hover{{background:{t.surface_2};}}'
                f'QPushButton:disabled{{color:{t.ink_4};}}')
        for item in self.body.findChildren(_TodayItem):
            item.refresh_theme()
