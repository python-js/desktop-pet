"""Floating reminder card shown when a task becomes due."""
from datetime import datetime, timedelta

from PyQt5.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QParallelAnimationGroup, Qt
from PyQt5.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
                             QToolButton, QVBoxLayout)

from ..core import REMIND_LIMIT, parse_due
from ..recurrence import REPEAT_LABELS
from .common import button
from .components import StatePill
from .theme import add_soft_shadow, application_icon


def friendly_time(value, now=None):
    due = parse_due(value).astimezone()
    now = now or datetime.now().astimezone()
    if due <= now:
        minutes = max(1, int((now - due).total_seconds() // 60))
        if minutes < 60:
            return f'已逾期 {minutes} 分钟', True
        if minutes < 1440:
            return f'已逾期 {minutes // 60} 小时', True
        return f'已逾期 {minutes // 1440} 天', True
    if due.date() == now.date():
        return f'今天 {due:%H:%M}', False
    if due.date() == (now + timedelta(days=1)).date():
        return f'明天 {due:%H:%M}', False
    return f'{due:%m月%d日 %H:%M}', False


class ReminderDialog(QDialog):
    def __init__(self, parent, task, on_complete, on_snooze, on_open, final=False):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle('待办提醒')
        self.setFixedWidth(420)
        self.final = final
        self._animated = False
        self._motion = None
        self.resolved = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        card = QFrame()
        card.setObjectName('reminderCard')
        add_soft_shadow(card)
        outer.addWidget(card)
        body = QVBoxLayout(card)
        body.setContentsMargins(20, 18, 20, 18)
        body.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(application_icon().pixmap(34, 34))
        icon.setFixedSize(34, 34)
        header.addWidget(icon)
        kicker = QLabel('待办提醒')
        kicker.setObjectName('reminderKicker')
        header.addWidget(kicker)
        if final:
            header.addWidget(StatePill('最终提醒', 'over', 'alert'))
        header.addStretch()
        close = QToolButton()
        close.setObjectName('reminderClose')
        close.setText('×')
        close.setCursor(Qt.PointingHandCursor)
        close.setFixedSize(28, 28)
        close.setToolTip('关闭提醒')
        close.clicked.connect(self.reject)
        header.addWidget(close)
        body.addLayout(header)

        title = QLabel(task['title'])
        title.setObjectName('reminderTitle')
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        body.addWidget(title)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        time_text, overdue = friendly_time(task['due_at'])
        chips.addWidget(StatePill(time_text, 'over' if overdue else 'today', 'clock'))
        repeat = task.get('repeat_rule', 'none')
        if repeat != 'none':
            chips.addWidget(StatePill(REPEAT_LABELS.get(repeat, '不重复'), 'next', 'sync'))
        chips.addStretch()
        body.addLayout(chips)

        self.hint = QLabel(f'已提醒 {REMIND_LIMIT} 次，这是最后一次；关闭后转为延期，不再提醒。' if final
                           else '关闭后仍可在待办页继续处理。')
        self.hint.setObjectName('reminderHint')
        self.hint.setWordWrap(True)
        body.addWidget(self.hint)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.complete_button = button('完成', lambda checked=False: self._resolve(on_complete), actions, primary=True)
        self.complete_button.setDefault(True)
        self.snooze_button = button('10 分钟后', lambda checked=False: self._resolve(on_snooze), actions)
        if final:
            self.snooze_button.setEnabled(False)
            self.snooze_button.setToolTip(f'已提醒 {REMIND_LIMIT} 次，不再重复提醒')
        open_button = QToolButton()
        open_button.setObjectName('reminderLink')
        open_button.setText('打开待办')
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.clicked.connect(lambda checked=False: self._resolve(on_open))
        actions.addWidget(open_button)
        actions.addStretch()
        body.addLayout(actions)

    def _resolve(self, callback):
        self.resolved = True
        callback()

    def present(self, anchor=None, index=0):
        self.adjustSize()
        screen = QApplication.screenAt(anchor.center()) if anchor else QApplication.primaryScreen()
        if screen is None:
            screen = QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        width, height = self.width(), self.height()
        if anchor:
            x = anchor.center().x() - width // 2
            y = anchor.top() - height - 14 - index * (height + 12)
            if y < bounds.top() + 12:
                y = anchor.bottom() + 14 + index * (height + 12)
        else:
            x = bounds.right() - width - 24
            y = bounds.bottom() - height - 24 - index * (height + 12)
        x = max(bounds.left() + 12, min(x, bounds.right() - width - 12))
        y = max(bounds.top() + 12, min(y, bounds.bottom() - height - 12))
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event):
        super().showEvent(event)
        if self._animated or QApplication.platformName() == 'offscreen':
            return
        self._animated = True
        self.setWindowOpacity(0.0)
        target = self.pos()
        fade = QPropertyAnimation(self, b'windowOpacity', self)
        fade.setDuration(180)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        move = QPropertyAnimation(self, b'pos', self)
        move.setDuration(180)
        move.setStartValue(target + QPoint(0, 8))
        move.setEndValue(target)
        move.setEasingCurve(QEasingCurve.OutCubic)
        self._motion = QParallelAnimationGroup(self)
        self._motion.addAnimation(fade)
        self._motion.addAnimation(move)
        self._motion.start()
