"""Home overview: today's schedule, quick numbers and shortcuts."""
from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea,
                             QSizePolicy, QVBoxLayout, QWidget)
from qfluentwidgets import FluentIcon, PrimaryPushButton, TransparentPushButton

from ..core import parse_due
from ..recurrence import REPEAT_LABELS
from .common import button
from .tasks import short_due
from .theme import ACCENT_DARK, INK, MUTED


def _local(value):
    return parse_due(value).astimezone()


def today_overview(store, now=None):
    now = now or datetime.now().astimezone()
    today = now.date()
    pending = [dict(row) for row in store.pending()]
    done = [dict(row) for row in store.history('done')]
    today_pending = [task for task in pending if _local(task['due_at']).date() == today]
    today_done = [task for task in done if _local(task['due_at']).date() == today]
    overdue = [task for task in pending if _local(task['due_at']) < now]
    earlier_overdue = [task for task in overdue if _local(task['due_at']).date() < today]
    upcoming = sorted((task for task in pending if _local(task['due_at']) > now),
                      key=lambda task: _local(task['due_at']))
    return {
        'today_pending': today_pending,
        'today_done': today_done,
        'overdue': overdue,
        'earlier_overdue': earlier_overdue,
        'next': upcoming[0] if upcoming else None,
        'schedule': sorted(today_pending + today_done, key=lambda task: _local(task['due_at'])),
    }


def greeting(now):
    hour = now.hour
    word = '早上好' if hour < 9 else '上午好' if hour < 12 else '下午好' if hour < 18 else '晚上好'
    weekday = '一二三四五六日'[now.weekday()]
    return f'{word}，今天 {now.month}月{now.day}日 周{weekday}'


class HomeTaskRow(QFrame):
    clicked = pyqtSignal()

    def __init__(self, task, now, parent=None):
        super().__init__(parent)
        self.setObjectName('homeTaskRow')
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(56)
        self.setToolTip(task.get('title', ''))
        due = _local(task['due_at'])
        done = task.get('status') == 'done'
        deferred = not done and bool(task.get('deferred'))
        overdue = not done and due < now

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)

        dot = QLabel()
        dot.setFixedSize(10, 10)
        if done:
            dot.setStyleSheet(f'background:{ACCENT_DARK};border-radius:5px;')
        else:
            color = '#C25A43' if overdue and not deferred else '#D9CDC0'
            dot.setStyleSheet(f'background:transparent;border:1.5px solid {color};border-radius:5px;')
        layout.addWidget(dot)

        time = QLabel(f'{due:%H:%M}')
        time.setFixedWidth(42)
        time.setStyleSheet(f'color:#B4432F;font-size:12px;' if overdue and not deferred else f'color:{MUTED};font-size:12px;')
        layout.addWidget(time)

        title = QLabel(task.get('title', ''))
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        font = QFont(title.font())
        font.setPixelSize(14)
        font.setStrikeOut(done)
        title.setFont(font)
        title.setStyleSheet(f'color:{MUTED if done else INK};')
        layout.addWidget(title, 1)

        meta = []
        if done:
            meta.append('已完成')
        repeat = REPEAT_LABELS.get(task.get('repeat_rule', 'none'), '不重复')
        if repeat != '不重复':
            meta.append(repeat)
        if deferred:
            meta.insert(0, '已延期')
        elif overdue:
            meta.insert(0, '已逾期')
        if meta:
            label = QLabel(' · '.join(meta))
            label.setStyleSheet(f'color:{MUTED};font-size:12px;')
            layout.addWidget(label)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class HomePageMixin:
    def build_home(self):
        page = QWidget()
        page.setObjectName('homePage')
        page.setStyleSheet(
            'QFrame#homeStat{background:#FFFFFF;border:1px solid #F3EADF;border-radius:14px;}'
            'QFrame#homeBanner{background:#FFF0EA;border:1px solid #F6DCD2;border-radius:12px;}'
            'QFrame#homeTaskRow{background:#FFFFFF;border:1px solid #F3EADF;border-radius:12px;}'
            'QFrame#homeTaskRow:hover{background:#FFFBF7;border-color:#F3C9BA;}')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 28, 30, 20)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)
        self.home_title = QLabel()
        self.home_title.setObjectName('pageTitle')
        self.home_subtitle = QLabel()
        self.home_subtitle.setObjectName('subtitle')
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(self.home_title)
        titles.addWidget(self.home_subtitle)
        header.addLayout(titles, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        chat_button = TransparentPushButton(FluentIcon.CHAT, '继续对话', self)
        chat_button.setMinimumHeight(36)
        chat_button.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        plan_button = TransparentPushButton(FluentIcon.CALENDAR, '今日规划', self)
        plan_button.setMinimumHeight(36)
        plan_button.clicked.connect(self.home_plan)
        add_button = PrimaryPushButton(FluentIcon.ADD, '新增待办', self)
        add_button.setMinimumHeight(36)
        add_button.clicked.connect(self.new_task)
        actions.addWidget(chat_button)
        actions.addWidget(plan_button)
        actions.addWidget(add_button)
        header.addLayout(actions)
        layout.addLayout(header)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.home_stats = {}
        for key, caption in (('today', '今日待办'), ('done', '已完成'),
                             ('overdue', '已逾期'), ('next', '下一次提醒')):
            card = QFrame()
            card.setObjectName('homeStat')
            card.setFixedHeight(78)
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 11, 16, 11)
            box.setSpacing(3)
            label = QLabel(caption)
            label.setObjectName('eyebrow')
            value = QLabel('—')
            value.setStyleSheet(f'color:{INK};font-size:22px;font-weight:700;')
            box.addWidget(label)
            box.addWidget(value)
            self.home_stats[key] = value
            stats.addWidget(card, 1)
        layout.addLayout(stats)

        self.home_banner = QFrame()
        self.home_banner.setObjectName('homeBanner')
        banner_row = QHBoxLayout(self.home_banner)
        banner_row.setContentsMargins(14, 8, 10, 8)
        self.home_banner_text = QLabel()
        self.home_banner_text.setStyleSheet('color:#B4432F;font-size:13px;')
        banner_row.addWidget(self.home_banner_text, 1)
        button('去处理', self.open_overdue, banner_row)
        self.home_banner.hide()
        layout.addWidget(self.home_banner)

        section = QHBoxLayout()
        section.setSpacing(8)
        title = QLabel('今天安排')
        title.setStyleSheet('color:#3A322C;font-size:16px;font-weight:600;')
        self.home_count = QLabel()
        self.home_count.setObjectName('subtitle')
        section.addWidget(title)
        section.addStretch()
        section.addWidget(self.home_count)
        layout.addLayout(section)

        self.home_scroll = QScrollArea()
        self.home_scroll.setWidgetResizable(True)
        self.home_list = QWidget()
        self.home_rows = QVBoxLayout(self.home_list)
        self.home_rows.setContentsMargins(0, 0, 4, 0)
        self.home_rows.setSpacing(8)
        self.home_scroll.setWidget(self.home_list)
        layout.addWidget(self.home_scroll, 1)
        self.home_row_widgets = []
        self.tabs.addTab(page, '首页')

    def refresh_home(self):
        if not hasattr(self, 'home_stats'):
            return
        now = datetime.now().astimezone()
        data = today_overview(self.store, now)
        self.home_title.setText(greeting(now))
        total = len(data['schedule'])
        done = len(data['today_done'])
        summary = f'今天 {total} 件事，已完成 {done} 件。'
        if data['overdue']:
            summary += f' 还有 {len(data["overdue"])} 件已逾期。'
        self.home_subtitle.setText(summary)
        self.home_stats['today'].setText(f'{len(data["today_pending"])} 件')
        self.home_stats['done'].setText(f'{done} 件')
        overdue = len(data['overdue'])
        self.home_stats['overdue'].setText(f'{overdue} 件')
        self.home_stats['overdue'].setStyleSheet(
            f'color:{"#B4432F" if overdue else INK};font-size:22px;font-weight:700;')
        self.home_stats['next'].setText(short_due(data['next']['due_at'], now) if data['next'] else '暂无')
        earlier = len(data['earlier_overdue'])
        self.home_banner_text.setText(f'另有 {earlier} 件更早的逾期未处理。')
        self.home_banner.setVisible(bool(earlier))
        self.home_count.setText(f'{total} 项' if total else '')

        while self.home_rows.count():
            widget = self.home_rows.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self.home_row_widgets = []
        if not data['schedule']:
            empty = QLabel('今天还没有安排\n\n新增一件待办，或让对话助手帮你记下。')
            empty.setObjectName('subtitle')
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet('padding:40px 0;')
            self.home_rows.addWidget(empty)
            self.home_rows.addStretch()
            return
        for task in data['schedule']:
            row = HomeTaskRow(task, now)
            row.clicked.connect(lambda task=task: self.open_home_task(task))
            self.home_rows.addWidget(row)
            self.home_row_widgets.append(row)
        self.home_rows.addStretch()

    def open_home_task(self, task):
        self.tabs.setCurrentIndex(2)
        self.focus_task(task['id'], task.get('status') == 'done')

    def open_overdue(self):
        self.tabs.setCurrentIndex(2)
        self.task_filter.setCurrentIndex(0)
        self.task_period.setCurrentIndex(self.task_period.findData('overdue'))
        self.task_search.clear()

    def home_plan(self):
        self.tabs.setCurrentIndex(1)
        self.plan_today()
