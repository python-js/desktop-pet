"""待办事项页：分组列表、行内完成与批量选择。"""
from datetime import datetime, timedelta

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (QAction, QDialog, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                             QVBoxLayout, QWidget)
from qfluentwidgets import FluentIcon, PrimaryPushButton, TransparentPushButton

from ..core import parse_due
from ..recurrence import REPEAT_LABELS, in_period
from . import icons
from . import tokens as T
from .common import iso_input, TaskDialog
from .components import (ElidedLabel, Segmented, StatePill, due_when, overdue_text)
from .controls import ComboBox as QComboBox
from .controls import LineEdit as QLineEdit
from .home import Line
from .theme import mono_font, tokens


_WEIGHTS = {QFont.DemiBold: 600, QFont.Bold: 700}


def _text(size, token_name, weight=QFont.Normal, wrap=False):
    label = QLabel()
    font = QFont(T.FONT_UI)
    font.setPixelSize(size)
    font.setWeight(weight)
    label.setFont(font)
    label.setWordWrap(wrap)
    style = f'font-family:"{T.FONT_UI}";font-size:{size}px;'
    if weight in _WEIGHTS:
        style += f'font-weight:{_WEIGHTS[weight]};'
    label._token_name = token_name
    label._style_base = style
    label.setStyleSheet(f'{style}color:{getattr(tokens(), token_name)};background:transparent;')
    return label


def _mono(size, token_name, weight=QFont.Normal):
    label = QLabel()
    font = mono_font(size)
    font.setWeight(weight)
    label.setFont(font)
    style = f'font-family:"{T.FONT_MONO}","Consolas",monospace;font-size:{size}px;'
    if weight in _WEIGHTS:
        style += f'font-weight:{_WEIGHTS[weight]};'
    label._token_name = token_name
    label._style_base = style
    label.setStyleSheet(f'{style}color:{getattr(tokens(), token_name)};background:transparent;')
    return label


def _set_color(label, color):
    label.setStyleSheet(f'{getattr(label, "_style_base", "")}color:{color};background:transparent;')


def _rgba(color, alpha):
    value = QColor(color)
    return f'rgba({value.red()},{value.green()},{value.blue()},{alpha})'


def _is_chat(task):
    return task.get('source') in ('chat', 'draft')


def _meta_text(task, due, now):
    parts = []
    repeat = REPEAT_LABELS.get(task.get('repeat_rule', 'none'), '不重复')
    if repeat != '不重复':
        parts.append(repeat)
    done = task.get('status') == 'done'
    if done:
        completed = task.get('completed_at')
        if completed:
            done_at = parse_due(completed).astimezone()
            minutes = int((due - done_at).total_seconds() // 60)
            tail = f'提前 {minutes} 分钟' if minutes > 0 else (
                f'晚 {abs(minutes)} 分钟' if minutes < 0 else '准点')
            parts.append(f'{done_at:%H:%M} 完成，{tail}')
    else:
        if task.get('early_notified_at'):
            parts.append('提前 10 分钟提醒')
        if task.get('deferred'):
            parts.append('提醒已达上限')
        elif due < now and task.get('remind_count'):
            parts.append(f'已提醒 {task["remind_count"]} 次')
    if _is_chat(task):
        created = parse_due(task.get('created_at') or task['due_at']).astimezone()
        parts.append(f'由对话创建 {created:%H:%M}')
    note = str(task.get('note') or '').strip()
    if note:
        parts.append('备注：' + note)
    return ' · '.join(parts)


class _Rail(QWidget):
    TONES = {'over': 'alert', 'soon': 'caution', 'today': 'brand',
             'done': 'calm', 'next': 'border_strong'}

    def __init__(self, tone='next', parent=None):
        super().__init__(parent)
        self.tone = tone
        self.setFixedWidth(3)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(getattr(tokens(), self.TONES.get(self.tone, 'border_strong'))))
        rect = QRectF(self.rect())
        painter.drawRoundedRect(QRectF(rect.left(), 9, 3, max(0, rect.height() - 18)), 1.5, 1.5)


class _Pick(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.picked = False
        self.hover = False
        self.setFixedSize(18, 18)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('选择这条待办')

    def set_state(self, picked, hover):
        self.picked = bool(picked)
        self.hover = bool(hover)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.picked:
            painter.setPen(QPen(QColor(t.brand), 1.5))
            painter.setBrush(QColor(t.brand))
            painter.drawRoundedRect(rect, 6, 6)
            painter.drawPixmap(QPointF(3.5, 3.5), icons.pixmap('check', t.brand_on, 11))
        elif self.hover:
            painter.setPen(QPen(QColor(t.border_strong), 1.5))
            painter.setBrush(QColor(t.surface))
            painter.drawRoundedRect(rect, 6, 6)


class _Ring(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.done = False
        self.tone = 'next'
        self.hover = False
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('标记完成')

    def set_state(self, tone, done):
        self.tone = tone
        self.done = bool(done)
        self.update()

    def enterEvent(self, event):
        self.hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
        color = {'over': t.alert, 'soon': t.caution, 'done': t.calm}.get(self.tone, t.border_strong)
        if self.done:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.calm))
        else:
            painter.setPen(QPen(QColor(t.brand if self.hover else color), 1.6))
            painter.setBrush(QColor(t.surface))
        painter.drawEllipse(rect)
        if self.done:
            painter.setPen(QPen(QColor(t.brand_on), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            center = rect.center()
            painter.drawLine(QPointF(center.x() - 4, center.y()),
                             QPointF(center.x() - 1, center.y() + 3))
            painter.drawLine(QPointF(center.x() - 1, center.y() + 3),
                             QPointF(center.x() + 5, center.y() - 3))


class _Quick(QWidget):
    clicked = pyqtSignal()

    def __init__(self, icon_name, tooltip, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.active = False
        self.hover = False
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)

    def set_active(self, active):
        if self.active != bool(active):
            self.active = bool(active)
            self.update()

    def enterEvent(self, event):
        self.hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        if not self.active:
            return
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.surface_3))
            painter.drawRoundedRect(QRectF(self.rect()), 7, 7)
        painter.drawPixmap(QPointF(5, 5), icons.pixmap(self.icon_name, t.ink_2 if self.hover else t.ink_3, 16))


class TaskRow(QWidget):
    """待办行：3px 状态轨、选择、行内完成、快捷动作与双击编辑。"""

    complete_requested = pyqtSignal(str)
    pick_toggled = pyqtSignal(str, bool)
    edit_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    snooze_requested = pyqtSignal(str)

    def __init__(self, task, now, density='comfortable', picked=False, parent=None):
        super().__init__(parent)
        self.task = dict(task)
        self.now = now
        self.compact = density == 'compact'
        self.picked = bool(picked)
        self.hover = False
        self.done = self.task.get('status') == 'done'
        self.deferred = not self.done and bool(self.task.get('deferred'))
        self.due = parse_due(self.task['due_at']).astimezone()
        self.overdue = not self.done and self.due < now
        self.soon = not self.done and not self.overdue and self.due - now <= timedelta(minutes=30)
        self.tone = 'done' if self.done else (
            'over' if self.overdue else ('soon' if (self.deferred or self.soon) else 'today'))
        self.setObjectName('taskRow')
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFixedHeight(T.ROW_H_SM if self.compact else T.ROW_H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(f'{self.task.get("title", "")}，'
                               f'{"已完成" if self.done else ("逾期" if self.overdue else "待提醒")}')
        self._build()
        self._apply_style()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 10, 0)
        layout.setSpacing(10)
        self.pick = _Pick()
        self.pick.clicked.connect(self._toggle_pick)
        layout.addWidget(self.pick, 0, Qt.AlignVCenter)
        self.rail = _Rail(self.tone)
        layout.addWidget(self.rail)
        self.ring = _Ring()
        self.ring.setToolTip('恢复待办' if self.done else '标记完成')
        self.ring.clicked.connect(lambda: self.complete_requested.emit(self.task['id']))
        layout.addWidget(self.ring, 0, Qt.AlignVCenter)

        when = QWidget()
        when.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        when_box = QVBoxLayout(when)
        when_box.setContentsMargins(0, 0, 0, 0)
        when_box.setSpacing(0)
        when.setFixedWidth(64)
        self.when_date = _mono(11, 'ink_3')
        self.when_time = _mono(12, 'ink_2', QFont.DemiBold)
        self.when_date.setText(f'{self.due:%m月%d日}')
        self.when_time.setText(f'{self.due:%H:%M}')
        when_box.addWidget(self.when_date)
        when_box.addWidget(self.when_time)
        layout.addWidget(when, 0, Qt.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        self.title = ElidedLabel(self.task.get('title', ''))
        title_font = QFont(T.FONT_UI)
        title_font.setPixelSize(15)
        title_font.setWeight(QFont.DemiBold)
        title_font.setStrikeOut(self.done)
        self.title.setFont(title_font)
        self.title.setStyleSheet(
            f'font-family:"{T.FONT_UI}";font-size:15px;font-weight:600;background:transparent;')
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        text_box.addWidget(self.title)
        self.meta = ElidedLabel()
        meta_font = QFont(T.FONT_UI)
        meta_font.setPixelSize(11)
        self.meta.setFont(meta_font)
        self.meta.setStyleSheet(f'font-family:"{T.FONT_UI}";font-size:11px;background:transparent;')
        self.meta.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.meta.setVisible(not self.compact)
        if not self.compact:
            text_box.addWidget(self.meta)
        layout.addLayout(text_box, 1)

        self.chips = []
        if self.task.get('dingtalk'):
            chip = StatePill('钉钉', 'info', 'ding')
            chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.chips.append(chip)
            layout.addWidget(chip, 0, Qt.AlignVCenter)
        if _is_chat(self.task):
            chip = StatePill('来自对话', 'today', 'chat')
            chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.chips.append(chip)
            layout.addWidget(chip, 0, Qt.AlignVCenter)

        self.pill = StatePill()
        self.pill.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.pill, 0, Qt.AlignVCenter)

        self.quick = []
        quick_box = QHBoxLayout()
        quick_box.setContentsMargins(0, 0, 0, 0)
        quick_box.setSpacing(0)
        if not self.done:
            for icon_name, tip, signal in (('clock', '十分钟后提醒', self.snooze_requested),
                                           ('edit', '编辑', self.edit_requested),
                                           ('trash', '删除', self.delete_requested)):
                action = _Quick(icon_name, tip)
                action.clicked.connect(
                    lambda _=False, task_id=self.task['id'], target=signal: target.emit(task_id))
                self.quick.append(action)
                quick_box.addWidget(action)
        layout.addLayout(quick_box)
        self._sync_hover()

    def _toggle_pick(self):
        self.set_picked(not self.picked)
        self.pick_toggled.emit(self.task['id'], self.picked)

    def set_picked(self, picked):
        self.picked = bool(picked)
        self.pick.set_state(self.picked, self.hover or self.hasFocus())
        self.update()

    def set_actions_visible(self, visible):
        for action in self.quick:
            action.setVisible(visible)

    def refresh_theme(self):
        self._apply_style()

    def _apply_style(self):
        t = tokens()
        self.rail.tone = self.tone
        self.rail.update()
        self.ring.set_state(self.tone, self.done)
        if self.done:
            state, tone, state_icon = '已完成', 'done', 'check'
        elif self.deferred:
            state, tone, state_icon = '已延期', 'soon', 'clock'
        elif self.overdue:
            state, tone, state_icon = overdue_text(self.due, self.now), 'over', 'alert'
        elif self.soon:
            state, tone, state_icon = due_when(self.due, self.now), 'soon', 'clock'
        else:
            state, tone, state_icon = due_when(self.due, self.now), 'next', ''
        self.pill.set_state(state, tone, state_icon)
        self.title.set_color(t.ink_3 if self.done else t.ink)
        self.meta.set_color(t.ink_3)
        _set_color(self.when_date, t.ink_3 if self.done else t.ink_2)
        _set_color(self.when_time, t.ink_3 if self.done else (
            t.alert if (self.overdue and not self.deferred) else t.ink_2))
        meta = _meta_text(self.task, self.due, self.now)
        self.meta.setText(meta)
        self.meta.setVisible(bool(meta) and not self.compact)
        self.setToolTip(f'{self.task.get("title", "")}\n{state}'
                        + (f'\n{meta}' if meta else ''))
        self.update()

    def _sync_hover(self):
        active = self.hover or self.hasFocus()
        self.pick.set_state(self.picked, active)
        for action in self.quick:
            action.set_active(active)

    def enterEvent(self, event):
        self.hover = True
        self._sync_hover()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover = False
        self._sync_hover()
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self._sync_hover()
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._sync_hover()
        self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._toggle_pick()
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not self.done:
                self.edit_requested.emit(self.task['id'])
            event.accept()
            return
        if event.key() == Qt.Key_Delete:
            self.delete_requested.emit(self.task['id'])
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and not self.done:
            self.edit_requested.emit(self.task['id'])
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.picked:
            fill, border, style = QColor(t.brand_wash), QColor(t.brand_line), Qt.SolidLine
        elif self.done:
            fill, border, style = QColor(0, 0, 0, 0), QColor(t.border), Qt.DashLine
        elif self.hover:
            fill, border, style = QColor(t.surface_2), QColor(t.border_strong), Qt.SolidLine
        else:
            fill, border, style = QColor(t.surface), QColor(t.border), Qt.SolidLine
        if self.hasFocus():
            border = QColor(t.brand)
        painter.setPen(QPen(border, 2 if self.hasFocus() else 1, style))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, T.RADIUS_CARD, T.RADIUS_CARD)


class BulkBar(QWidget):
    """居中悬浮批量条：604×42，距底 20；只在有选中时出现。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setAttribute(Qt.WA_StyledBackground, False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(6)
        self.label = _mono(12, 'bg', QFont.DemiBold)
        layout.addWidget(self.label)
        self.mark = QPushButton('标记完成')
        self.snooze = QPushButton('十分钟后提醒')
        self.delete = QPushButton('删除')
        self.undo = QPushButton('撤销删除')
        for control in (self.mark, self.snooze, self.delete, self.undo):
            control.setFixedHeight(28)
            control.setCursor(Qt.PointingHandCursor)
            layout.addWidget(control)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setFixedWidth(100)
        layout.addWidget(self.note)
        layout.addStretch(1)
        self.cancel = QPushButton('取消')
        self.cancel.setFixedHeight(28)
        self.cancel.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.cancel)
        self.set_state(0, 0)
        self.restyle()

    def set_state(self, count, dingtalk):
        self.label.setText(f'已选 {count} 项')
        self.note.setText(f'含 {dingtalk} 条钉钉同步事项' if dingtalk else '')
        self.note.setVisible(bool(dingtalk))

    def set_undo_enabled(self, enabled):
        self.undo.setEnabled(bool(enabled))

    def restyle(self):
        t = tokens()
        fg = t.bg
        base = (f'QPushButton{{background:transparent;color:{fg};'
                f'border:1px solid {_rgba(fg, 72)};border-radius:8px;'
                f'padding:0 9px;font-size:12px;font-weight:600;font-family:"{T.FONT_UI}";}}'
                f'QPushButton:hover{{background:{_rgba(fg, 28)};border-color:{_rgba(fg, 120)};}}'
                f'QPushButton:pressed{{background:{_rgba(fg, 40)};}}'
                f'QPushButton:disabled{{color:{_rgba(fg, 90)};border-color:{_rgba(fg, 36)};}}')
        for control in (self.mark, self.snooze, self.delete, self.undo):
            control.setStyleSheet(base)
        self.cancel.setStyleSheet(
            f'QPushButton{{background:transparent;color:{fg};border:0;padding:0 6px;'
            f'font-size:12px;font-weight:600;font-family:"{T.FONT_UI}";}}'
            f'QPushButton:hover{{color:{fg};}}')
        self.label.setStyleSheet(
            f'font-family:"{T.FONT_MONO}","Consolas",monospace;font-size:12px;'
            f'font-weight:600;color:{fg};background:transparent;')
        self.note.setStyleSheet(
            f'font-family:"{T.FONT_UI}";font-size:10px;'
            f'color:{_rgba(fg, 190)};background:transparent;')
        self.update()

    def reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(604, max(320, parent.width() - 40))
        self.setFixedWidth(width)
        self.move((parent.width() - width) // 2, parent.height() - 20 - 42)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(tokens().ink))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0, 0, -0.5, -0.5), 21, 21)


class TasksPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bulk = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.bulk is not None and self.bulk.isVisible():
            self.bulk.reposition()


class TasksPageMixin:
    def build_tasks(self):
        if not hasattr(self, 'deleted_batch'):
            self.deleted_batch = []
        self.task_selected = set()
        page = TasksPage()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.task_toolbar_holder = QWidget()
        holder_layout = QHBoxLayout(self.task_toolbar_holder)
        holder_layout.setContentsMargins(32, 24, 32, 12)
        holder_layout.setSpacing(0)
        self.task_toolbar = QWidget()
        self.task_toolbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar = QVBoxLayout(self.task_toolbar)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel('待办事项')
        title.setObjectName('pageTitle')
        header.addWidget(title)
        subtitle = QLabel('双击任意一条可改标题和提醒时间。')
        subtitle.setObjectName('subtitle')
        header.addWidget(subtitle)
        header.addStretch(1)
        self.task_density = Segmented(
            [{'key': 'comfortable', 'label': '宽松'}, {'key': 'compact', 'label': '紧凑'}],
            current=self.settings.get('density', 'comfortable'))
        self.task_density.changed.connect(self.set_task_density)
        header.addWidget(self.task_density)
        header.addSpacing(2)
        header.addWidget(Line(vertical=True))
        self.task_add_button = PrimaryPushButton(FluentIcon.ADD, '新增待办')
        self.task_add_button.setFixedHeight(32)
        self.task_add_button.setCursor(Qt.PointingHandCursor)
        self.task_add_button.clicked.connect(self.new_task)
        header.addWidget(self.task_add_button)
        toolbar.addLayout(header)
        toolbar.addWidget(Line())
        toolbar.addLayout(self._build_task_filters())
        holder_layout.addStretch(1)
        holder_layout.addWidget(self.task_toolbar, 100)
        holder_layout.addStretch(1)
        outer.addWidget(self.task_toolbar_holder)

        self.task_scroll = QScrollArea()
        self.task_scroll.setWidgetResizable(True)
        self.task_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.task_canvas = QWidget()
        self.task_canvas_layout = QVBoxLayout(self.task_canvas)
        self.task_canvas_layout.setContentsMargins(32, 0, 32, 72)
        self.task_canvas_layout.setSpacing(0)
        self.task_body = QWidget()
        self.task_body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.task_body_layout = QVBoxLayout(self.task_body)
        self.task_body_layout.setContentsMargins(0, 0, 0, 0)
        self.task_body_layout.setSpacing(18)
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addStretch(1)
        center.addWidget(self.task_body, 100)
        center.addStretch(1)
        self.task_canvas_layout.addLayout(center)
        self.task_canvas_layout.addStretch(1)
        self.task_scroll.setWidget(self.task_canvas)
        outer.addWidget(self.task_scroll, 1)

        self.task_groups = []
        self.task_rows = []
        self._empty_visible = False
        self.task_empty_holder = self._build_task_empty()
        self.task_bulk = BulkBar(page)
        page.bulk = self.task_bulk
        self.task_bulk.mark.clicked.connect(self.complete_selected)
        self.task_bulk.snooze.clicked.connect(self.snooze_selected)
        self.task_bulk.delete.clicked.connect(self.delete_selected)
        self.task_bulk.undo.clicked.connect(self.undo_delete)
        self.task_bulk.cancel.clicked.connect(self.clear_task_selection)
        self.task_bulk.hide()

        self.task_page = page
        self.tabs.addTab(page, '待办')
        self.apply_tasks_layout(self.width(), force=True)

    def _build_task_filters(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        self.task_segments = Segmented(
            [{'key': 'pending', 'label': '未完成', 'count': 0},
             {'key': 'done', 'label': '已完成', 'count': 0}])
        self.task_segments.changed.connect(self.on_task_status)
        row.addWidget(self.task_segments)

        self.task_period = QComboBox()
        for label, value in [('全部时间', 'all'), ('今天', 'today'),
                             ('未来日期', 'future'), ('已逾期', 'overdue')]:
            self.task_period.addItem(label, value)
        self.task_period.setFixedWidth(148)
        self.task_period.setFixedHeight(32)
        self.task_period.currentIndexChanged.connect(self.on_task_period)
        row.addWidget(self.task_period)

        self.task_search = QLineEdit()
        self.task_search.setPlaceholderText('搜索待办标题')
        self.task_search.setFixedHeight(32)
        self.task_search.setMinimumWidth(180)
        self.task_search.setClearButtonEnabled(True)
        self.task_search_action = QAction(icons.icon('search', tokens().ink_3, 15), '',
                                          self.task_search)
        self.task_search.addAction(self.task_search_action, QLineEdit.LeadingPosition)
        self._search_icon_theme = tokens().name
        self.task_search.textChanged.connect(self.on_task_search)
        row.addWidget(self.task_search, 1)

        self.task_undo = TransparentPushButton(FluentIcon.RETURN, '撤销删除')
        self.task_undo.setFixedHeight(32)
        self.task_undo.setCursor(Qt.PointingHandCursor)
        self.task_undo.clicked.connect(self.undo_delete)
        self.task_undo.setVisible(False)
        self.task_undo.setEnabled(False)
        self.undo_button = self.task_undo
        row.addWidget(self.task_undo)

        self.task_count_num = _mono(12, 'ink', QFont.DemiBold)
        self.task_count_cap = _mono(12, 'ink_3')
        row.addWidget(self.task_count_num)
        row.addWidget(self.task_count_cap)
        return row

    def _build_task_empty(self):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 24, 0, 24)
        row.addStretch(1)
        panel = QWidget()
        panel.setMaximumWidth(420)
        panel.setMinimumWidth(280)
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.task_empty_mark = QLabel()
        self.task_empty_mark.setFixedSize(40, 40)
        self.task_empty_mark.setAlignment(Qt.AlignCenter)
        box.addWidget(self.task_empty_mark, 0, Qt.AlignHCenter)
        self.task_empty_title = _text(15, 'ink', QFont.DemiBold)
        self.task_empty_title.setAlignment(Qt.AlignCenter)
        box.addWidget(self.task_empty_title)
        self.task_empty_hint = _text(12, 'ink_3', wrap=True)
        self.task_empty_hint.setAlignment(Qt.AlignCenter)
        box.addWidget(self.task_empty_hint)
        row.addWidget(panel, 0)
        row.addStretch(1)
        holder.hide()
        return holder

    def apply_tasks_layout(self, width, force=False):
        if not hasattr(self, 'task_toolbar_holder'):
            return
        pad = 32 if width > 1280 else 20
        max_width = 1120 if width > 1400 else (980 if width > 1280 else (820 if width <= 1080 else None))
        state = (pad, max_width, width > 880)
        if not force and state == getattr(self, '_task_layout_state', None):
            return
        self._task_layout_state = state
        self.task_toolbar_holder.layout().setContentsMargins(pad, 24, pad, 12)
        self.task_canvas_layout.setContentsMargins(pad, 0, pad, 72)
        self.task_toolbar.setMaximumWidth(max_width or 16777215)
        self.task_body.setMaximumWidth(max_width or 16777215)
        for row in getattr(self, 'task_rows', []):
            row.set_actions_visible(width > 880)
        if hasattr(self, 'task_bulk') and self.task_bulk.isVisible():
            self.task_bulk.reposition()

    def set_task_density(self, key):
        if key not in ('comfortable', 'compact') or self.settings.get('density') == key:
            return
        self.settings['density'] = key
        self.task_density.set_current(key)
        if hasattr(self, 'settings_density_segment'):
            self.settings_density_segment.set_current(key)
        try:
            self.persist_settings()
        except OSError:
            self.statusBar().showMessage('密度设置暂时无法保存，本次运行仍然有效。', 6000)
        self.refresh_tasks()

    def on_task_status(self, key):
        self.clear_task_selection()
        self.refresh_tasks()

    def on_task_period(self, index):
        self.clear_task_selection()
        self.refresh_tasks()

    def on_task_search(self, text):
        self.clear_task_selection()
        self.refresh_tasks()

    def _restyle_toolbar(self):
        t = tokens()
        for label in (self.task_count_num, self.task_count_cap):
            _set_color(label, getattr(t, getattr(label, '_token_name', 'ink_3')))
        if self._search_icon_theme != t.name:
            self._search_icon_theme = t.name
            self.task_search_action.setIcon(icons.icon('search', t.ink_3, 15))
        self.task_segments.update()
        self.task_density.update()
        t_empty = tokens()
        self.task_empty_mark.setStyleSheet(f'background:{t_empty.calm_wash};border-radius:20px;')
        self.task_empty_mark.setPixmap(icons.pixmap('paw', t_empty.calm, 19))
        _set_color(self.task_empty_title, t_empty.ink)
        _set_color(self.task_empty_hint, t_empty.ink_3)
        for group in self.task_groups:
            group.update()
        for row in self.task_rows:
            row.refresh_theme()

    def _task_groups(self, rows, done, now):
        if done:
            return [('已完成 · 需要回顾', rows)] if rows else []
        overdue = [row for row in rows if parse_due(row['due_at']) < now]
        upcoming = [row for row in rows if parse_due(row['due_at']) >= now]
        today = [row for row in upcoming if parse_due(row['due_at']).astimezone().date() == now.date()]
        future = [row for row in upcoming if parse_due(row['due_at']).astimezone().date() > now.date()]
        groups = []
        if overdue:
            groups.append(('逾期 · 需要你回应', overdue))
        if today:
            groups.append((f'今天 · {len(today)} 项', today))
        if future:
            groups.append((f'接下来 · {len(future)} 项', future))
        return groups

    def _group_header(self, text):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(4, 0, 0, 0)
        row.setSpacing(12)
        label = _mono(10, 'ink_3')
        label.setText(text)
        row.addWidget(label)
        row.addWidget(Line(), 1)
        return holder

    def refresh_tasks(self):
        if not hasattr(self, 'task_segments'):
            return
        now = datetime.now().astimezone()
        scroll = self.task_scroll.verticalScrollBar().value()
        done = self.task_segments.key() == 'done'
        search = self.task_search.text().strip().lower()
        pending = [dict(row) for row in self.store.pending()]
        completed = [dict(row) for row in self.store.history('done')]
        self.task_segments.set_counts({'pending': len(pending), 'done': len(completed)})
        source = completed if done else pending
        if search:
            source = [row for row in source if search in str(row.get('title', '')).lower()]
        if done:
            source.sort(key=lambda row: row.get('completed_at') or row['due_at'], reverse=True)
        else:
            period = self.task_period.currentData() or 'all'
            if period != 'all':
                source = [row for row in source
                          if in_period(parse_due(row['due_at']), period, now)]
        self.task_period.setEnabled(not done)
        if hasattr(self, 'task_count_num'):
            self.task_count_num.setText(str(len(source)))
            self.task_count_cap.setText('项已完成' if done else '项未完成')

        for holder in self.task_groups:
            self.task_body_layout.removeWidget(holder)
            holder.hide()
            holder.deleteLater()
        self.task_groups = []
        self.task_rows = []
        self.task_selected &= {row['id'] for row in source}

        groups = self._task_groups(source, done, now)
        for title, items in groups:
            holder = QWidget()
            box = QVBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(8)
            box.addWidget(self._group_header(title))
            for task in items:
                row = TaskRow(task, now, self.settings.get('density', 'comfortable'),
                              picked=task['id'] in self.task_selected)
                row.complete_requested.connect(self.toggle_done)
                row.pick_toggled.connect(self.on_task_pick)
                row.edit_requested.connect(self.edit_task_by_id)
                row.delete_requested.connect(lambda task_id: self.delete_tasks([task_id]))
                row.snooze_requested.connect(self.snooze_task)
                row.set_actions_visible(self.width() > 880)
                box.addWidget(row)
                self.task_rows.append(row)
            self.task_body_layout.addWidget(holder)
            self.task_groups.append(holder)

        empty = not groups
        if empty:
            if not self._empty_visible:
                self.task_body_layout.addWidget(self.task_empty_holder)
                self._empty_visible = True
            self.task_empty_holder.show()
            self._set_empty_text(done, bool(search))
        elif self._empty_visible:
            self.task_body_layout.removeWidget(self.task_empty_holder)
            self.task_empty_holder.hide()
            self._empty_visible = False

        self._restyle_toolbar()
        self.task_bulk.restyle()
        self.task_bulk.set_undo_enabled(bool(self.deleted_batch or self.last_deleted))
        self.refresh_task_bulk()
        self.task_scroll.verticalScrollBar().setValue(scroll)
        self.refresh_home()
        if hasattr(self, 'chat_rail'):
            self.refresh_chat_rail()

    def _set_empty_text(self, done, searching):
        if searching:
            self.task_empty_title.setText('没有匹配的待办')
            self.task_empty_hint.setText('换个关键词试试，或清空搜索框。')
        elif done:
            self.task_empty_title.setText('还没有完成的待办')
            self.task_empty_hint.setText('完成一件待办后，会在这里留下记录。')
        else:
            self.task_empty_title.setText('没有要盯的事了')
            self.task_empty_hint.setText('新增一件待办，或回到对话让小满替你记下。')

    def refresh_task_bulk(self):
        selected = [row for row in self.task_rows if row.picked]
        if selected:
            self.task_bulk.set_state(len(selected),
                                     sum(1 for row in selected if row.task.get('dingtalk')))
            self.task_bulk.mark.setText(
                '恢复待办' if all(row.done for row in selected) else '标记完成')
            self.task_bulk.reposition()
            self.task_bulk.show()
            self.task_bulk.raise_()
        else:
            self.task_bulk.hide()

    def clear_task_selection(self):
        self.task_selected.clear()
        for row in getattr(self, 'task_rows', []):
            row.set_picked(False)
        if hasattr(self, 'task_bulk'):
            self.task_bulk.hide()

    def on_task_pick(self, task_id, picked):
        if picked:
            self.task_selected.add(task_id)
        else:
            self.task_selected.discard(task_id)
        self.refresh_task_bulk()

    def focus_task(self, task_id, done=False):
        self.task_segments.set_current('done' if done else 'pending')
        self.task_period.setCurrentIndex(0)
        self.task_search.clear()
        self.clear_task_selection()
        self.refresh_tasks()
        for row in self.task_rows:
            if row.task['id'] == task_id:
                row.setFocus(Qt.OtherFocusReason)
                self.task_scroll.ensureWidgetVisible(row, 0, 24)
                break

    def new_task(self):
        self.task_dialog()

    def edit_task_by_id(self, task_id):
        row = next((row for row in self.task_rows if row.task['id'] == task_id), None)
        if row is not None and not row.done:
            self.task_dialog(row.task)

    def task_dialog(self, task=None):
        dialog = TaskDialog(self, task)
        while dialog.exec_() == QDialog.Accepted:
            try:
                if task:
                    self.store.edit(task['id'], dialog.title.text(), iso_input(dialog.date),
                                    repeat=dialog.repeat.currentData(),
                                    dingtalk=dialog.dingtalk.isChecked())
                    self.dismiss_reminder(task['id'])
                else:
                    self.store.add(dialog.title.text(), iso_input(dialog.date),
                                   repeat=dialog.repeat.currentData(),
                                   dingtalk=dialog.dingtalk.isChecked())
                self.refresh_tasks()
                break
            except ValueError as exc:
                QMessageBox.warning(self, '无法保存', str(exc))

    def toggle_done(self, task_id):
        row = next((row for row in self.task_rows if row.task['id'] == task_id), None)
        if row is None:
            return
        if row.done:
            try:
                self.store.reopen(task_id)
            except ValueError as exc:
                QMessageBox.information(self, '重复任务', str(exc))
                return
            self.statusBar().showMessage(
                '已恢复待办；已过期的任务会重新提醒，可在未完成页修改时间。', 8000)
        else:
            next_id = self.store.complete(task_id)
            self.dismiss_reminder(task_id)
            self.statusBar().showMessage(
                '本次已完成，已生成下一次重复待办。' if next_id else '已标记完成。', 6000)
        self.refresh_tasks()

    def snooze_task(self, task_id):
        row = next((row for row in self.task_rows if row.task['id'] == task_id), None)
        if row is None:
            return
        if row.deferred:
            self.statusBar().showMessage(
                '该待办已延期，不再提醒；双击修改提醒时间可重新开始。', 8000)
            return
        self.store.snooze(task_id, minutes=10)
        self.dismiss_reminder(task_id)
        self.statusBar().showMessage('已顺延 10 分钟，到点会再次提醒。', 6000)
        self.refresh_tasks()

    def complete_selected(self):
        selected = [row for row in self.task_rows if row.picked]
        if not selected:
            return
        completed = reopened = nexts = 0
        for row in selected:
            task_id = row.task['id']
            if row.done:
                try:
                    self.store.reopen(task_id)
                    reopened += 1
                except ValueError:
                    continue
            else:
                if self.store.complete(task_id):
                    nexts += 1
                completed += 1
                self.dismiss_reminder(task_id)
        self.clear_task_selection()
        self.refresh_tasks()
        parts = []
        if completed:
            parts.append(f'已完成 {completed} 项')
        if nexts:
            parts.append(f'生成 {nexts} 条下一次重复待办')
        if reopened:
            parts.append(f'恢复 {reopened} 项待办')
        self.statusBar().showMessage('，'.join(parts) + '。' if parts else '没有可更新的待办。', 8000)

    def snooze_selected(self):
        selected = [row for row in self.task_rows if row.picked and not row.done]
        if not selected:
            return
        snoozed = skipped = 0
        for row in selected:
            if row.deferred:
                skipped += 1
                continue
            self.store.snooze(row.task['id'], minutes=10)
            self.dismiss_reminder(row.task['id'])
            snoozed += 1
        self.clear_task_selection()
        self.refresh_tasks()
        message = f'已顺延 {snoozed} 项十分钟。'
        if skipped:
            message += f'另有 {skipped} 项已延期，未处理。'
        self.statusBar().showMessage(message, 8000)

    def delete_selected(self):
        ids = [row.task['id'] for row in self.task_rows if row.picked]
        if ids:
            self.delete_tasks(ids)

    def delete_tasks(self, task_ids):
        ids = [task_id for task_id in task_ids if task_id]
        if not ids:
            return
        for task_id in ids:
            self.store.delete(task_id)
            self.dismiss_reminder(task_id)
        self.register_deleted(ids)
        self.clear_task_selection()
        self.refresh_tasks()
        self.statusBar().showMessage(f'已删除 {len(ids)} 项，可撤销最近一次删除。', 6000)

    def register_deleted(self, task_ids):
        ids = [task_id for task_id in task_ids if task_id]
        self.last_deleted = ids[-1] if ids else None
        self.deleted_batch = list(ids)
        if hasattr(self, 'undo_button'):
            self.undo_button.setEnabled(bool(ids))
            self.undo_button.setVisible(bool(ids))

    def undo_delete(self):
        ids = list(getattr(self, 'deleted_batch', []) or
                   ([self.last_deleted] if self.last_deleted else []))
        if not ids:
            return
        for task_id in reversed(ids):
            self.store.undo_delete(task_id)
        self.last_deleted = None
        self.deleted_batch = []
        if hasattr(self, 'undo_button'):
            self.undo_button.setEnabled(False)
            self.undo_button.setVisible(False)
        if hasattr(self, 'task_bulk'):
            self.task_bulk.set_undo_enabled(False)
        self.refresh_tasks()
        self.statusBar().showMessage(f'已恢复 {len(ids)} 项待办（含原完成状态）。', 6000)

    def resolve(self, task_id, snooze):
        if snooze:
            self.store.snooze(task_id)
        else:
            next_id = self.store.complete(task_id)
            if next_id:
                self.statusBar().showMessage('本次已完成，已生成下一次重复待办。', 8000)
        self.dismiss_reminder(task_id)
        self.refresh_tasks()


# 0.30 旧待办页实现保留备查（P3 重构前版本，需回退时可整体替换上方实现）：
_LEGACY_TASKS_030 = r'''
"""Task page presentation, kept separate from chat and model requests."""
from datetime import datetime, timedelta
from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout, QComboBox,
                             QLineEdit, QListWidget, QListWidgetItem, QDialog, QMessageBox,
                             QFrame, QStyle, QStyledItemDelegate)
from ..core import parse_due
from ..recurrence import REPEAT_LABELS, in_period
from .common import button, local_time, iso_input, TaskDialog
from .controls import ComboBox as QComboBox
from .controls import LineEdit as QLineEdit
from .theme import ACCENT_DARK, INK, MUTED


def short_due(value, now):
    due = parse_due(value).astimezone()
    if due.date() == now.date():
        return f'今天 {due:%H:%M}'
    if due.date() == (now + timedelta(days=1)).date():
        return f'明天 {due:%H:%M}'
    return f'{due:%m月%d日 %H:%M}'


class TaskDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(0, 78)

    def paint(self, painter, option, index):
        task = index.data(Qt.UserRole)
        if not task:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect.adjusted(2, 3, -2, -3))
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        if selected:
            fill, border = QColor('#FFF4ED'), QColor('#F2CDBF')
        elif hover:
            fill, border = QColor('#FFFBF7'), QColor('#F3E5D8')
        else:
            fill, border = QColor('#FFFFFF'), QColor('#F3EADF')
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 14, 14)

        now = datetime.now().astimezone()
        due = parse_due(task['due_at']).astimezone()
        done = task.get('status') == 'done'
        deferred = not done and bool(task.get('deferred'))
        overdue = not done and due <= now
        circle = QRectF(rect.left() + 18, rect.center().y() - 9, 18, 18)
        if done:
            painter.setBrush(QColor(ACCENT_DARK))
            painter.setPen(QPen(QColor(ACCENT_DARK), 1.6))
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor('#C25A43') if overdue and not deferred else QColor('#D9CDC0'), 1.6))
        painter.drawEllipse(circle)
        if done:
            painter.setPen(QPen(QColor('#FFFFFF'), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            center = circle.center()
            painter.drawLine(QPointF(center.x() - 4, center.y()), QPointF(center.x() - 1, center.y() + 3))
            painter.drawLine(QPointF(center.x() - 1, center.y() + 3), QPointF(center.x() + 5, center.y() - 3))

        left = circle.right() + 14
        width = rect.right() - left - 18
        title_font = QFont(option.font)
        title_font.setPixelSize(15)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(INK))
        title = painter.fontMetrics().elidedText(task.get('title', ''), Qt.ElideRight, int(width))
        painter.drawText(QRectF(left, rect.top() + 15, width, 22), Qt.AlignLeft | Qt.AlignVCenter, title)

        meta_font = QFont(option.font)
        meta_font.setPixelSize(12)
        painter.setFont(meta_font)
        painter.setPen(QColor('#B4432F') if overdue and not deferred else QColor(MUTED))
        repeat = REPEAT_LABELS.get(task.get('repeat_rule', 'none'), '不重复')
        prefix = '已延期' if deferred else ('已逾期' if overdue else '')
        meta = f"{prefix + ' · ' if prefix else ''}{short_due(task['due_at'], now)} · {repeat}"
        if task.get('dingtalk'):
            meta += ' · 钉钉'
        meta = painter.fontMetrics().elidedText(meta, Qt.ElideRight, int(width))
        painter.drawText(QRectF(left, rect.top() + 40, width, 18), Qt.AlignLeft | Qt.AlignVCenter, meta)
        painter.restore()


class TasksPageMixin:
    def build_tasks(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 28, 30, 20)
        layout.setSpacing(16)
        heading = QLabel('待办事项')
        heading.setObjectName('pageTitle')
        layout.addWidget(heading)
        subtitle = QLabel('让每件事都有着落。双击任务可编辑标题和提醒时间。')
        subtitle.setObjectName('subtitle')
        layout.addWidget(subtitle)
        filters = QHBoxLayout()
        self.task_filter = QComboBox()
        self.task_filter.addItems(['未完成', '已完成'])
        self.task_filter.currentIndexChanged.connect(self.refresh_tasks)
        filters.addWidget(self.task_filter)
        self.task_period = QComboBox()
        for label, value in [('全部时间', 'all'), ('今天', 'today'), ('未来日期', 'future'), ('已逾期', 'overdue')]:
            self.task_period.addItem(label, value)
        self.task_period.currentIndexChanged.connect(self.refresh_tasks)
        filters.addWidget(self.task_period)
        self.task_search = QLineEdit()
        self.task_search.setPlaceholderText('搜索任务标题')
        self.task_search.textChanged.connect(self.refresh_tasks)
        filters.addWidget(self.task_search, 1)
        self.task_count = QLabel()
        filters.addWidget(self.task_count)
        layout.addLayout(filters)
        self.tasks = QListWidget()
        self.tasks.setObjectName('taskList')
        self.tasks.setFrameShape(QFrame.NoFrame)
        self.tasks.setMouseTracking(True)
        self.tasks.setUniformItemSizes(True)
        self.tasks.setItemDelegate(TaskDelegate(self.tasks))
        self.tasks.itemDoubleClicked.connect(self.edit_task)
        layout.addWidget(self.tasks)
        self.task_empty = QLabel('还没有待办事项\n\n从一件小事开始，或让对话助手帮你整理。', self.tasks.viewport())
        self.task_empty.setObjectName('subtitle')
        self.task_empty.setAlignment(Qt.AlignCenter)
        empty_layout = QVBoxLayout(self.tasks.viewport())
        empty_layout.addStretch()
        empty_layout.addWidget(self.task_empty)
        empty_layout.addStretch()
        row = QHBoxLayout()
        button('新增待办', self.new_task, row, primary=True)
        self.complete_button = button('标记完成', self.complete_selected, row)
        self.snooze_button = button('十分钟后提醒', self.snooze_selected, row)
        button('删除', self.delete_selected, row)
        self.undo_button = button('撤销删除', self.undo_delete, row)
        self.undo_button.setEnabled(False)
        row.addStretch()
        layout.addLayout(row)
        self.tabs.addTab(page, '待办')

    def refresh_tasks(self):
        selected = self.tasks.currentItem()
        selected_id = selected.data(Qt.UserRole)['id'] if selected else None
        scroll = self.tasks.verticalScrollBar().value()
        self.tasks.clear()
        done = self.task_filter.currentIndex() == 1
        self.complete_button.setText('恢复待办' if done else '标记完成')
        self.snooze_button.setEnabled(not done)
        self.task_period.setEnabled(not done)
        rows = self.store.history('done' if done else 'pending', self.task_search.text())
        now = datetime.now().astimezone()
        if not done:
            rows = [row for row in rows if in_period(parse_due(row['due_at']), self.task_period.currentData(), now)]
        self.task_count.setText(f'{len(rows)} 项')
        self.task_empty.setVisible(not rows)
        for task in rows:
            overdue = not done and parse_due(task['due_at']) <= now
            deferred = not done and bool(task['deferred'])
            prefix = '已完成' if done else ('已延期' if deferred else ('已逾期' if overdue else '待提醒'))
            repeat = REPEAT_LABELS[task['repeat_rule']]
            item = QListWidgetItem(f"{task['title']}\n{prefix} · {local_time(task['due_at'])} · {repeat}")
            item.setData(Qt.UserRole, dict(task))
            item.setToolTip(task['title'])
            self.tasks.addItem(item)
            if task['id'] == selected_id:
                self.tasks.setCurrentItem(item)
        self.tasks.verticalScrollBar().setValue(scroll)
        self.refresh_home()

    def focus_task(self, task_id, done=False):
        self.task_filter.setCurrentIndex(1 if done else 0)
        self.task_period.setCurrentIndex(0)
        self.task_search.clear()
        self.refresh_tasks()
        for row in range(self.tasks.count()):
            item = self.tasks.item(row)
            if item.data(Qt.UserRole)['id'] == task_id:
                self.tasks.setCurrentRow(row)
                self.tasks.scrollToItem(item)
                break

    def new_task(self):
        self.task_dialog()

    def edit_task(self, item):
        if item.data(Qt.UserRole)['status'] == 'pending':
            self.task_dialog(item.data(Qt.UserRole))

    def task_dialog(self, task=None):
        dialog = TaskDialog(self, task)
        while dialog.exec_() == QDialog.Accepted:
            try:
                if task:
                    self.store.edit(task['id'], dialog.title.text(), iso_input(dialog.date),
                                    repeat=dialog.repeat.currentData(), dingtalk=dialog.dingtalk.isChecked())
                    self.dismiss_reminder(task['id'])
                else:
                    self.store.add(dialog.title.text(), iso_input(dialog.date),
                                   repeat=dialog.repeat.currentData(), dingtalk=dialog.dingtalk.isChecked())
                self.refresh_tasks()
                break
            except ValueError as exc:
                QMessageBox.warning(self, '无法保存', str(exc))

    def complete_selected(self):
        item = self.tasks.currentItem()
        if item:
            task = item.data(Qt.UserRole)
            if task['status'] == 'done':
                try:
                    self.store.reopen(task['id'])
                except ValueError as exc:
                    QMessageBox.information(self, '重复任务', str(exc))
                    return
                self.refresh_tasks()
                self.statusBar().showMessage('已恢复待办；已过期的任务会重新提醒，可在未完成页修改时间。', 8000)
            else:
                self.resolve(task['id'], False)

    def delete_selected(self):
        item = self.tasks.currentItem()
        if item:
            self.last_deleted = item.data(Qt.UserRole)['id']
            self.store.delete(self.last_deleted)
            self.dismiss_reminder(self.last_deleted)
            self.undo_button.setEnabled(True)
            self.refresh_tasks()
            self.statusBar().showMessage('已删除，可撤销最近一次删除。', 6000)

    def undo_delete(self):
        if self.last_deleted:
            self.store.undo_delete(self.last_deleted)
            self.last_deleted = None
            self.undo_button.setEnabled(False)
            self.refresh_tasks()

    def snooze_selected(self):
        item = self.tasks.currentItem()
        if item:
            task = item.data(Qt.UserRole)
            if task.get('deferred'):
                self.statusBar().showMessage('该待办已延期，不再提醒；双击修改提醒时间可重新开始。', 8000)
                return
            self.resolve(task['id'], True)

    def resolve(self, task_id, snooze):
        if snooze:
            self.store.snooze(task_id)
        else:
            next_id = self.store.complete(task_id)
            if next_id:
                self.statusBar().showMessage('本次已完成，已生成下一次重复待办。', 8000)
        self.dismiss_reminder(task_id)
        self.refresh_tasks()

'''
