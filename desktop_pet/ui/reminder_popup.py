"""待办提醒卡：贴在宠物头顶，不进入主界面。"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from .pet import BUBBLE_BOTTOM
from .theme import add_soft_shadow

CARD_WIDTH = 304
SHADOW_MARGIN = 14
STACK_GAP = 6


class ReminderPopup(QWidget):
    """A single due-task card anchored above the pet's head."""

    action = Signal(str, str)  # task_id, action

    def __init__(self, task, when, repeat, pet):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.task = dict(task)
        self.task_id = self.task['id']
        self.pet = pet
        self.slot = 0
        self._done = False
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(CARD_WIDTH + SHADOW_MARGIN * 2)
        self.setWindowTitle('待办提醒')

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN)
        card = QFrame()
        card.setObjectName('reminderCard')
        card.setFixedWidth(CARD_WIDTH)
        add_soft_shadow(card)
        outer.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(16, 13, 16, 13)
        body.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(8)
        count = int(self.task.get('remind_count') or 1)
        kicker = QLabel('最后一次提醒' if self.task.get('deferred') else
                        (f'第 {count} 次提醒' if count > 1 else '待办提醒'))
        kicker.setObjectName('reminderKicker')
        head.addWidget(kicker)
        when_label = QLabel(when)
        when_label.setObjectName('reminderHint')
        head.addWidget(when_label)
        head.addStretch(1)
        close = QToolButton()
        close.setObjectName('reminderClose')
        close.setText('×')
        close.setFixedSize(22, 22)
        close.setFocusPolicy(Qt.NoFocus)
        close.setToolTip('关闭并顺延 10 分钟')
        close.clicked.connect(lambda: self.finish('close'))
        head.addWidget(close)
        body.addLayout(head)

        title = QLabel(self.task.get('title') or '待办提醒')
        title.setObjectName('reminderTitle')
        title.setWordWrap(True)
        body.addWidget(title)

        hint_parts = [part for part in (repeat, self.task.get('note') or '') if part]
        if hint_parts:
            hint = QLabel(' · '.join(hint_parts))
            hint.setObjectName('reminderHint')
            hint.setWordWrap(True)
            body.addWidget(hint)

        actions = QHBoxLayout()
        actions.setSpacing(7)
        complete = QPushButton('完成')
        complete.setProperty('variant', 'primary')
        complete.clicked.connect(lambda: self.finish('complete'))
        snooze = QPushButton('10 分钟后')
        snooze.clicked.connect(lambda: self.finish('snooze'))
        if self.task.get('deferred'):
            snooze.setEnabled(False)
            snooze.setToolTip('已达提醒上限，不再重复提醒')
        mute = QPushButton('今天别再说')
        mute.clicked.connect(lambda: self.finish('mute'))
        for button in (complete, snooze, mute):
            button.setCursor(Qt.PointingHandCursor)
            actions.addWidget(button)
        actions.addStretch(1)
        body.addLayout(actions)

        foot = QHBoxLayout()
        foot.addStretch(1)
        open_tasks = QToolButton()
        open_tasks.setObjectName('reminderLink')
        open_tasks.setText('打开待办 →')
        open_tasks.setCursor(Qt.PointingHandCursor)
        open_tasks.clicked.connect(lambda: self.finish('open'))
        foot.addWidget(open_tasks)
        body.addLayout(foot)

        self.follow = QTimer(self)
        self.follow.setInterval(120)
        self.follow.timeout.connect(self.refresh_position)

    def set_slot(self, slot):
        self.slot = slot
        self.refresh_position()

    def show_at_pet(self):
        self.adjustSize()
        self.show()
        self.refresh_position()
        self.follow.start()

    def refresh_position(self):
        if self._done or not self.pet.isVisible():
            return
        bounds = QGuiApplication.screenAt(self.pet.frameGeometry().center())
        if bounds is None:
            bounds = QGuiApplication.primaryScreen()
        area = bounds.availableGeometry()
        rect = self.pet.frameGeometry()
        x = rect.center().x() - self.width() // 2
        head_top = rect.top() + BUBBLE_BOTTOM
        y = head_top - self.height() - self.slot * (self.height() + STACK_GAP)
        if y < area.top() + 4:
            y = rect.bottom() + STACK_GAP + self.slot * (self.height() + STACK_GAP)
        y = min(y, area.bottom() - self.height() - 4)
        x = max(area.left() + 4, min(x, area.right() - self.width() - 3))
        self.move(x, y)

    def finish(self, action):
        if self._done:
            return
        self._done = True
        self.follow.stop()
        self.hide()
        self.action.emit(self.task_id, action)

    def dispose(self):
        self._done = True
        self.follow.stop()
        self.hide()
        self.deleteLater()
