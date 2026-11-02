"""首页：先回答“接下来发生什么”，再用节奏环与工作日志补充上下文。"""
from datetime import datetime, timedelta, timezone

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                             QSizePolicy, QVBoxLayout, QWidget)
from qfluentwidgets import (FluentIcon, PrimaryPushButton, PushButton,
                            TransparentPushButton)

from ..core import parse_due
from ..recurrence import REPEAT_LABELS
from . import icons
from . import tokens as T
from .components import (ElidedLabel, Panel, RhythmRing, StatePill, StatusRow,
                         Track, due_when, overdue_text)
from .pet_tag import countdown
from .theme import mono_font, tokens


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
    return word


def date_line(now):
    return (f'{now.year} 年 {now.month} 月 {now.day} 日 · '
            f'周{"一二三四五六日"[now.weekday()]}')


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


def _mono(size, token_name, weight=QFont.DemiBold):
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


class Line(QWidget):
    """1px 发丝线，颜色随主题。"""

    def __init__(self, vertical=False, parent=None):
        super().__init__(parent)
        self.vertical = vertical
        self.setFixedSize(1, 20) if vertical else self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Expanding if not vertical else QSizePolicy.Fixed,
                           QSizePolicy.Fixed)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tokens().border))


class StreakBar(QWidget):
    """本周按时打卡条：文字 + 7 个日期格。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.count = 0
        self.dates = set()
        self.now = datetime.now().astimezone()
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, count, dates, now):
        self.count = int(count or 0)
        self.dates = set(dates or [])
        self.now = now
        self.setAccessibleName(f'本周按时完成 {self.count} 天')
        self.update()

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(t.calm_wash))
        painter.drawRoundedRect(rect, T.RADIUS_CTL, T.RADIUS_CTL)
        painter.drawPixmap(QPointF(10, 9), icons.pixmap('paw', t.calm, 14))

        prefix = '本周按时打卡 '
        suffix = ' 天'
        font = QFont(T.FONT_UI)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor(t.ink_2))
        x = 31
        painter.drawText(QPointF(x, rect.center().y() + 4), prefix)
        x += QFontMetrics(font).horizontalAdvance(prefix)
        count_font = mono_font(11)
        painter.setFont(count_font)
        painter.setPen(QColor(t.ink))
        painter.drawText(QPointF(x, rect.center().y() + 4), str(self.count))
        x += QFontMetrics(count_font).horizontalAdvance(str(self.count))
        painter.setFont(font)
        painter.setPen(QColor(t.ink_2))
        painter.drawText(QPointF(x, rect.center().y() + 4), suffix)

        day = self.now.date()
        monday = day - timedelta(days=day.weekday())
        left = rect.right() - 10 - (7 * 7 + 6 * 4)
        painter.setPen(QPen(QColor(t.border_strong), 1))
        for index in range(7):
            date = monday + timedelta(days=index)
            box = QRectF(left + index * 11, rect.center().y() - 3.5, 7, 7)
            if date.isoformat() in self.dates:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(t.calm))
            elif date > day:
                painter.setPen(QPen(QColor(t.border_strong), 1))
                painter.setBrush(Qt.NoBrush)
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(t.surface_3))
            painter.drawRoundedRect(box, 2, 2)


class HeroCard(Panel):
    """主卡只呈现一个焦点：逾期 > 下一次 > 空。"""

    snooze_requested = pyqtSignal(str)
    complete_requested = pyqtSignal(str)
    mute_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = 'empty'
        self.task = None
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.mark = QLabel()
        self.mark.setFixedSize(34, 34)
        self.mark.setAlignment(Qt.AlignCenter)
        top.addWidget(self.mark, 0, Qt.AlignTop)
        labels = QVBoxLayout()
        labels.setSpacing(3)
        self.headline = _text(15, 'ink', QFont.DemiBold)
        self.body = _text(12, 'ink_3', wrap=True)
        labels.addWidget(self.headline)
        labels.addWidget(self.body)
        top.addLayout(labels, 1)
        self.pill = StatePill()
        top.addWidget(self.pill, 0, Qt.AlignTop)
        layout.addLayout(top)

        self.count_widget = QWidget()
        count_row = QHBoxLayout(self.count_widget)
        count_row.setContentsMargins(0, 0, 0, 0)
        count_row.setSpacing(16)
        main = QVBoxLayout()
        main.setSpacing(2)
        self.title = ElidedLabel()
        title_font = QFont(T.FONT_DISPLAY)
        title_font.setPixelSize(28)
        title_font.setWeight(QFont.DemiBold)
        self.title.setFont(title_font)
        self.title.setStyleSheet(f'font-family:"{T.FONT_DISPLAY}";font-size:28px;font-weight:600;')
        self.cap = _text(11, 'ink_3')
        main.addWidget(self.title)
        main.addWidget(self.cap)
        count_row.addLayout(main, 1)
        when = QVBoxLayout()
        when.setSpacing(4)
        self.when_eyebrow = _text(10, 'ink_3')
        self.when_value = ElidedLabel()
        self.when_value.setFont(mono_font(15))
        self.when_value.setStyleSheet(
            f'font-family:"{T.FONT_MONO}","Consolas",monospace;font-size:15px;font-weight:600;')
        self.when_value.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.when_note = _text(10, 'ink_3')
        when.addWidget(self.when_eyebrow)
        when.addWidget(self.when_value)
        when.addWidget(self.when_note)
        count_row.addLayout(when, 0)
        layout.addWidget(self.count_widget)

        self.track = Track()
        layout.addWidget(self.track)

        self.actions_widget = QWidget()
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.snooze_button = PushButton(FluentIcon.STOP_WATCH, '十分钟后')
        self.complete_button = PushButton(FluentIcon.COMPLETED, '标记完成')
        self.mute_button = TransparentPushButton(FluentIcon.QUIET_HOURS, '今天别再说')
        for control in (self.snooze_button, self.complete_button, self.mute_button):
            control.setFixedHeight(32)
            actions.addWidget(control)
        actions.addSpacing(4)
        self.tip = _text(11, 'ink_3')
        actions.addWidget(self.tip, 1)
        layout.addWidget(self.actions_widget)
        layout.addStretch(1)

        self.snooze_button.clicked.connect(
            lambda: self.task and self.snooze_requested.emit(self.task['id']))
        self.complete_button.clicked.connect(
            lambda: self.task and self.complete_requested.emit(self.task['id']))
        self.mute_button.clicked.connect(
            lambda: self.task and self.mute_requested.emit(self.task['id']))
        self.render(None, 'empty')

    def _mark(self, icon_name, wash, ink, border):
        t = tokens()
        edge = QColor(border)
        edge.setAlpha(80)
        self.mark.setStyleSheet(
            f'background:{wash};border:1px solid rgba({edge.red()},{edge.green()},{edge.blue()},{edge.alpha()});'
            'border-radius:11px;')
        self.mark.setPixmap(icons.pixmap(icon_name, ink, 17))

    def render(self, task, kind, now=None, extra=0, early_nudge=True):
        t = tokens()
        now = now or datetime.now().astimezone()
        self.kind = kind
        self.task = dict(task) if task else None
        self.tip.setText('处理结果会记入今天的工作日志。')
        if kind == 'empty':
            self._mark('paw', t.calm_wash, t.calm, t.calm)
            _set_color(self.headline, t.ink)
            self.headline.setText('今天没有要盯的事了')
            self.body.setText('新增一件待办，或让对话助手替你记下。')
            self.pill.hide()
            self.count_widget.hide()
            self.track.hide()
            self.actions_widget.hide()
            self.setToolTip('')
            return

        due = _local(task['due_at'])
        deferred = bool(task.get('deferred'))
        if kind == 'overdue':
            self._mark('bell', t.alert_wash, t.alert, t.alert)
            if task.get('remind_count'):
                self.headline.setText(f'{due_when(due, now)} 的提醒，你没有回应')
                text = f'小满在桌面弹过 {task["remind_count"]} 次气泡'
                if task.get('dingtalk'):
                    text += '，也推了钉钉'
                text += '，还没有收到你的确认。'
            else:
                self.headline.setText(f'{due_when(due, now)} 的提醒还没有处理')
                text = '这件事已过了原定时间，还在等你处理。'
            if extra:
                text += f' 另有 {extra} 件逾期排在后面。'
            self.body.setText(text)
            self.pill.set_state('已延期' if deferred else overdue_text(due, now),
                                'soon' if deferred else 'over', 'clock' if deferred else 'alert')
            self.pill.show()
            self.title.set_color(t.ink_2 if deferred else t.alert)
            state = '已延期' if deferred else (
                f'已提醒 {task["remind_count"]} 次' if task.get('remind_count') else '待处理')
            self.cap.setText(self._caption(task, state))
            self.when_eyebrow.setText('原定时间')
            self.when_value.set_color(t.ink)
            self.when_value.setText(due_when(due, now))
            self.when_note.setText('提醒已达上限' if deferred else '等待你的回应')
            self.count_widget.show()
            minutes = max(0, int((now - due).total_seconds()) // 60)
            self.track.set_value(min(1.0, minutes / 120), 'alert')
            self.track.show()
            self.snooze_button.setVisible(not deferred)
            self.actions_widget.show()
        else:
            self._mark('clock', t.brand_wash, t.brand, t.brand_line)
            self.headline.setText(f'下一次提醒在 {due_when(due, now)}')
            self.body.setText('小满会提前 10 分钟提醒你。' if early_nudge else '小满会到点提醒你。')
            self.pill.set_state(due_when(due, now),
                                'today' if due.date() == now.date() else 'next', 'clock')
            self.pill.show()
            self.title.set_color(t.ink)
            self.cap.setText(self._caption(task, '待提醒'))
            self.when_eyebrow.setText('下一次提醒')
            self.when_value.set_color(t.ink)
            self.when_value.setText(due_when(due, now))
            self.when_note.setText(f'还有 {countdown(task["due_at"], now)}')
            self.count_widget.show()
            self.track.hide()
            self.snooze_button.hide()
            self.actions_widget.show()
        self.title.setText(task.get('title', ''))
        self.setToolTip(task.get('title', ''))

    @staticmethod
    def _caption(task, state):
        parts = [state]
        repeat = REPEAT_LABELS.get(task.get('repeat_rule', 'none'), '不重复')
        if repeat != '不重复':
            parts.append(repeat)
        if task.get('dingtalk'):
            parts.append('钉钉同步')
        return ' · '.join(parts)


class RhythmCard(Panel):
    """今日完成度、本周按时记录与下一次提醒。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(16)
        self.ring = RhythmRing()
        head.addWidget(self.ring, 0, Qt.AlignVCenter)
        labels = QVBoxLayout()
        labels.setSpacing(1)
        self.today_title = _text(15, 'ink', QFont.DemiBold)
        self.today_summary = _text(12, 'ink_3', wrap=True)
        labels.addWidget(self.today_title)
        labels.addWidget(self.today_summary)
        head.addLayout(labels, 1)
        layout.addLayout(head)

        self.streak = StreakBar()
        layout.addWidget(self.streak)
        self.track = Track()
        layout.addWidget(self.track)

        next_box = QVBoxLayout()
        next_box.setSpacing(4)
        next_box.addWidget(_text(10, 'ink_3'))
        self.next_box = next_box
        self._next_eyebrow = next_box.itemAt(0).widget()
        self._next_eyebrow.setText('下一次提醒')
        when_row = QHBoxLayout()
        when_row.setSpacing(6)
        self.next_when = ElidedLabel()
        self.next_when.setFont(mono_font(15))
        self.next_when.setStyleSheet(
            f'font-family:"{T.FONT_MONO}","Consolas",monospace;font-size:15px;font-weight:600;')
        when_row.addWidget(self.next_when, 1)
        self.next_repeat = StatePill()
        self.next_dingtalk = StatePill()
        when_row.addWidget(self.next_repeat, 0)
        when_row.addWidget(self.next_dingtalk, 0)
        next_box.addLayout(when_row)
        self.next_title = ElidedLabel()
        next_font = QFont(T.FONT_UI)
        next_font.setPixelSize(12)
        self.next_title.setFont(next_font)
        self.next_title.setStyleSheet(f'font-family:"{T.FONT_UI}";font-size:12px;')
        next_box.addWidget(self.next_title)
        layout.addLayout(next_box)
        layout.addStretch(1)

    def render(self, data, stats, now, early_nudge=True):
        total = len(data['today_pending']) + len(data['today_done'])
        done = len(data['today_done'])
        self.ring.set_value(done, total)
        self.today_title.setText(f'今天 {total} 件事' if total else '今天还没有安排')
        if not total:
            summary = '新增待办后，节奏会从这里开始。'
        elif done >= total:
            summary = '全部完成，今天收工。'
        else:
            summary = f'已完成 {done} 件，还剩 {total - done} 件待处理。'
        self.today_summary.setText(summary)
        self.streak.set_data(stats['week_on_time_days'], stats.get('week_on_time_dates', []), now)
        self.track.set_value(done / total if total else 0.0, 'calm')

        task = data['next']
        if task is None:
            self.next_when.set_color(tokens().ink)
            self.next_when.setText('暂无下一次提醒')
            self.next_title.set_color(tokens().ink_3)
            self.next_title.setText('新增待办后，小满会替你盯着。')
            self.next_repeat.hide()
            self.next_dingtalk.hide()
            return
        due = _local(task['due_at'])
        self.next_when.set_color(tokens().ink)
        self.next_when.setText(due_when(due, now))
        self.next_title.set_color(tokens().ink_3)
        self.next_title.setText(task.get('title', ''))
        repeat = REPEAT_LABELS.get(task.get('repeat_rule', 'none'), '不重复')
        self.next_repeat.set_state(repeat, 'today', 'cal')
        self.next_repeat.setVisible(repeat != '不重复')
        self.next_dingtalk.set_state('钉钉', 'info', 'bell')
        self.next_dingtalk.setVisible(bool(task.get('dingtalk')))


class LogCard(Panel):
    def __init__(self, title, description, icon_name, wash, ink, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(76)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        mark = QLabel()
        mark.setFixedSize(28, 28)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(f'background:{wash};border-radius:9px;')
        mark.setPixmap(icons.pixmap(icon_name, ink, 15))
        layout.addWidget(mark, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        title_label = _text(12, 'ink', QFont.DemiBold, wrap=True)
        title_label.setText(title)
        desc = _text(12, 'ink_3', wrap=True)
        desc.setText(description)
        text.addWidget(title_label)
        text.addWidget(desc)
        layout.addLayout(text, 1)


class HomePageMixin:
    def build_home(self):
        page = QWidget()
        page.setObjectName('homePage')
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.home_scroll = QScrollArea()
        self.home_scroll.setWidgetResizable(True)
        self.home_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.home_canvas = QWidget()
        self.home_canvas_layout = QVBoxLayout(self.home_canvas)
        self.home_content = QWidget()
        self.home_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.home_content_layout = QVBoxLayout(self.home_content)
        self.home_content_layout.setContentsMargins(0, 0, 0, 0)
        self.home_content_layout.setSpacing(22)

        self._build_header()
        self._build_top()
        self._build_schedule()
        self._build_log()

        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addStretch(1)
        center.addWidget(self.home_content, 100)
        center.addStretch(1)
        self.home_canvas_layout.addLayout(center)
        self.home_canvas_layout.addStretch(1)
        self.home_scroll.setWidget(self.home_canvas)
        outer.addWidget(self.home_scroll)
        self.home_page = page
        self.tabs.addTab(page, '首页')
        self.apply_home_layout(self.width(), force=True)

    def _build_header(self):
        t = tokens()
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)

        eyebrow = QHBoxLayout()
        eyebrow.setSpacing(6)
        self.home_date = _text(11, 'ink_3')
        self.home_clock = _mono(11, 'ink_3')
        eyebrow.addWidget(self.home_date)
        dot = _text(11, 'ink_4')
        dot.setText('·')
        eyebrow.addWidget(dot)
        eyebrow.addWidget(self.home_clock)
        eyebrow.addStretch(1)
        box.addLayout(eyebrow)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.home_title = QLabel()
        self.home_title.setObjectName('pageTitle')
        title_row.addWidget(self.home_title)
        title_row.addStretch(1)
        self.home_chat_button = TransparentPushButton(FluentIcon.CHAT, '继续对话')
        self.home_plan_button = TransparentPushButton(FluentIcon.CALENDAR, '今日规划')
        self.home_add_button = PrimaryPushButton(FluentIcon.ADD, '新增待办')
        for control in (self.home_chat_button, self.home_plan_button, self.home_add_button):
            control.setFixedHeight(32)
            control.setCursor(Qt.PointingHandCursor)
            title_row.addWidget(control)
        title_row.addSpacing(4)
        title_row.addWidget(Line(vertical=True))
        self.home_chat_button.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        self.home_plan_button.clicked.connect(self.home_plan)
        self.home_add_button.clicked.connect(self.new_task)
        box.addLayout(title_row)
        box.addWidget(Line())
        self.home_content_layout.addWidget(holder)

    def _build_top(self):
        self.home_hero = HeroCard()
        self.home_rhythm = RhythmCard()
        self.home_hero.snooze_requested.connect(self.home_snooze)
        self.home_hero.complete_requested.connect(self.home_complete)
        self.home_hero.mute_requested.connect(self.home_mute)
        self.home_top = QGridLayout()
        self.home_top.setContentsMargins(0, 0, 0, 0)
        self.home_top.setHorizontalSpacing(16)
        self.home_top.setVerticalSpacing(16)
        self.home_top.addWidget(self.home_hero, 0, 0)
        self.home_top.addWidget(self.home_rhythm, 0, 1)
        self.home_top.setColumnStretch(0, 16)
        self.home_top.setColumnStretch(1, 10)
        self.home_content_layout.addLayout(self.home_top)
        self._home_wide_top = True

    def _build_schedule(self):
        t = tokens()
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        head = QHBoxLayout()
        section = _text(15, 'ink', QFont.DemiBold)
        section.setText('今天安排')
        head.addWidget(section)
        head.addStretch(1)
        self.home_count = _mono(11, 'ink_3', QFont.Normal)
        head.addWidget(self.home_count)
        box.addLayout(head)

        self.home_rows = QVBoxLayout()
        self.home_rows.setContentsMargins(0, 0, 0, 0)
        self.home_rows.setSpacing(8)
        box.addLayout(self.home_rows)
        self.home_empty_panel = Panel()
        self.home_empty_panel.setMinimumHeight(132)
        empty = QVBoxLayout(self.home_empty_panel)
        empty.setContentsMargins(20, 20, 20, 20)
        empty.setSpacing(4)
        empty.addStretch(1)
        mark = QLabel()
        mark.setFixedSize(34, 34)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(f'background:{t.calm_wash};border-radius:11px;')
        mark.setPixmap(icons.pixmap('paw', t.calm, 17))
        empty.addWidget(mark, 0, Qt.AlignHCenter)
        empty_title = _text(14, 'ink', QFont.DemiBold)
        empty_title.setText('今天没有要盯的事了')
        empty_title.setAlignment(Qt.AlignCenter)
        empty.addWidget(empty_title)
        empty_hint = _text(12, 'ink_3', wrap=True)
        empty_hint.setText('新增一件待办，或让对话助手替你记下。')
        empty_hint.setAlignment(Qt.AlignCenter)
        empty.addWidget(empty_hint)
        empty.addStretch(1)
        self.home_empty_panel.hide()
        self.home_row_widgets = []
        self.home_content_layout.addWidget(holder)

    def _build_log(self):
        t = tokens()
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        section = _text(15, 'ink', QFont.DemiBold)
        section.setText('小满今天替你做了什么')
        box.addWidget(section)
        self.home_log_grid = QGridLayout()
        self.home_log_grid.setContentsMargins(0, 0, 0, 0)
        self.home_log_grid.setHorizontalSpacing(16)
        self.home_log_grid.setVerticalSpacing(12)
        box.addLayout(self.home_log_grid)
        self.home_log_cards = []
        self.home_log_data = {}
        self.home_log_empty = Panel()
        self.home_log_empty.setMinimumHeight(76)
        empty = QHBoxLayout(self.home_log_empty)
        empty.setContentsMargins(16, 14, 16, 14)
        empty.setSpacing(12)
        mark = QLabel()
        mark.setFixedSize(28, 28)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(f'background:{t.calm_wash};border-radius:9px;')
        mark.setPixmap(icons.pixmap('paw', t.calm, 15))
        empty.addWidget(mark, 0, Qt.AlignTop)
        empty_text = _text(12, 'ink_3', wrap=True)
        empty_text.setText('今天还没有需要记录的动静。新增待办或和对话助手聊聊，小满会把动作记在这里。')
        empty.addWidget(empty_text, 1)
        self.home_log_empty.hide()
        self.home_content_layout.addWidget(holder)

    def apply_home_layout(self, width, force=False):
        if not hasattr(self, 'home_top'):
            return
        wide_top = width > 1080
        stacked_log = width <= 1280
        pad = 32 if width > 1280 else 20
        max_width = 1120 if width > 1400 else (980 if width > 1280 else (820 if width <= 1080 else None))
        state = (wide_top, stacked_log, pad, max_width)
        if not force and state == getattr(self, '_home_layout_state', None):
            return
        first = not hasattr(self, '_home_layout_state')
        self._home_layout_state = state
        self._home_log_stacked = stacked_log
        self.home_canvas_layout.setContentsMargins(pad, 24, pad, 32)
        self.home_content.setMaximumWidth(max_width or 16777215)
        if first or wide_top != self._home_wide_top:
            self._home_wide_top = wide_top
            self.home_top.removeWidget(self.home_hero)
            self.home_top.removeWidget(self.home_rhythm)
            if wide_top:
                self.home_top.addWidget(self.home_hero, 0, 0)
                self.home_top.addWidget(self.home_rhythm, 0, 1)
                self.home_top.setColumnStretch(0, 16)
                self.home_top.setColumnStretch(1, 10)
            else:
                self.home_top.addWidget(self.home_hero, 0, 0)
                self.home_top.addWidget(self.home_rhythm, 1, 0)
                self.home_top.setColumnStretch(0, 1)
                self.home_top.setColumnStretch(1, 0)
        if not first:
            self.refresh_home()

    def _apply_home_theme(self):
        t = tokens()
        for label in self.home_content.findChildren(QLabel):
            name = getattr(label, '_token_name', None)
            if not name:
                continue
            if isinstance(label, ElidedLabel):
                label.set_color(getattr(t, name))
            else:
                _set_color(label, getattr(t, name))
        for widget in (self.home_hero, self.home_rhythm):
            widget.update()

    def refresh_home(self):
        if not hasattr(self, 'home_hero'):
            return
        if hasattr(self, 'refresh_pet_tag'):
            self.refresh_pet_tag()
        self._apply_home_theme()
        now = datetime.now().astimezone()
        data = today_overview(self.store, now)
        stats = self.store.today_stats(now)
        events = self.store.today_events(now)
        self.home_date.setText(date_line(now))
        self.home_clock.setText(f'{now:%H:%M}')
        self.home_title.setText(greeting(now))

        overdue = data['overdue']
        if overdue:
            self.home_hero.render(overdue[0], 'overdue', now,
                                  extra=max(0, len(overdue) - 1),
                                  early_nudge=bool(self.settings.get('early_nudge', True)))
        elif data['next']:
            self.home_hero.render(data['next'], 'next', now,
                                  early_nudge=bool(self.settings.get('early_nudge', True)))
        else:
            self.home_hero.render(None, 'empty', now)
        self.home_rhythm.render(data, stats, now,
                                early_nudge=bool(self.settings.get('early_nudge', True)))

        self.home_count.setText(f'{len(data["schedule"])} 项' if data['schedule'] else '')
        for row in self.home_row_widgets:
            self.home_rows.removeWidget(row)
            row.deleteLater()
        self.home_row_widgets = []
        self.home_rows.removeWidget(self.home_empty_panel)
        if not data['schedule']:
            self.home_empty_panel.show()
            self.home_rows.addWidget(self.home_empty_panel)
        else:
            self.home_empty_panel.hide()
            density = self.settings.get('density', 'comfortable')
            for task in data['schedule']:
                row = StatusRow(task, now, density)
                row.clicked.connect(lambda task=task: self.open_home_task(task))
                self.home_rows.addWidget(row)
                self.home_row_widgets.append(row)
        self._render_log(events, stats)

    def _render_log(self, events, stats):
        counts = {}
        for event in events:
            counts[event['kind']] = counts.get(event['kind'], 0) + 1
        created = sum(1 for event in events
                      if event['kind'] == 'created' and event['detail'] in ('chat', 'draft'))
        completed = counts.get('completed', 0)
        postponed = counts.get('snoozed', 0) + counts.get('auto_postponed', 0)
        reminded = counts.get('reminded', 0)
        quiet = counts.get('quiet', 0)
        early = counts.get('early', 0)
        self.home_log_data = {
            'created': created, 'completed': completed, 'postponed': postponed,
            'reminded': reminded, 'quiet': quiet, 'early': early,
        }

        for card in self.home_log_cards:
            self.home_log_grid.removeWidget(card)
            card.deleteLater()
        self.home_log_cards = []
        self.home_log_grid.removeWidget(self.home_log_empty)
        self.home_log_empty.hide()

        t = tokens()
        cards = []
        if created:
            cards.append(LogCard(f'听懂并记下 {created} 件事',
                                 '从对话里补上时间，才建的任务。',
                                 'chat', t.brand_wash, t.brand))
        if reminded or quiet:
            title = f'提醒 {reminded} 次'
            if quiet:
                title += f' · 免打扰 {quiet} 次'
            detail = '桌面气泡与提前提点按待办标记执行。'
            if early:
                detail += f' 其中 {early} 次是提前提点。'
            cards.append(LogCard(title, detail, 'bell', t.caution_wash, t.caution))
        if completed or postponed:
            cards.append(LogCard(f'结掉 {completed} 件、顺延 {postponed} 件',
                                 '完成时刻已记入今天的工作日志。',
                                 'todo', t.calm_wash, t.calm))
        if not cards:
            self.home_log_empty.show()
            self.home_log_grid.addWidget(
                self.home_log_empty, 0, 0, 1, 1 if self._home_log_stacked else 3)
            return
        for index, card in enumerate(cards):
            if self._home_log_stacked:
                self.home_log_grid.addWidget(card, index, 0)
            else:
                self.home_log_grid.addWidget(card, 0, index)
            card.show()
            self.home_log_cards.append(card)
        if self._home_log_stacked:
            self.home_log_grid.setColumnStretch(0, 1)
        else:
            for index in range(3):
                self.home_log_grid.setColumnStretch(index, 1 if index < len(cards) else 0)

    def home_snooze(self, task_id):
        self.store.snooze(task_id, datetime.now(timezone.utc), minutes=10)
        self.dismiss_reminder(task_id)
        self.statusBar().showMessage('已顺延 10 分钟，到点会再次提醒。', 6000)
        self.refresh_tasks()

    def home_complete(self, task_id):
        next_id = self.store.complete(task_id)
        self.dismiss_reminder(task_id)
        message = '已标记完成，记入今天的工作日志。'
        if next_id:
            message = '已完成本次，下一次重复待办已生成。'
        self.statusBar().showMessage(message, 6000)
        self.refresh_tasks()

    def home_mute(self, task_id):
        self.store.mute_today(task_id)
        self.dismiss_reminder(task_id)
        self.statusBar().showMessage('今天之内不再提醒这条待办，明天恢复。', 6000)
        self.refresh_tasks()

    def open_home_task(self, task):
        self.tabs.setCurrentIndex(2)
        self.focus_task(task['id'], task.get('status') == 'done')

    def open_overdue(self):
        self.tabs.setCurrentIndex(2)
        self.task_segments.set_current('pending')
        self.task_period.setCurrentIndex(self.task_period.findData('overdue'))
        self.task_search.clear()
        self.clear_task_selection()
        self.refresh_tasks()

    def home_plan(self):
        self.tabs.setCurrentIndex(1)
        self.plan_today()

# 0.30 旧首页实现保留备查（P2 重构前版本，需回退时可整体替换上方实现）：
_LEGACY_HOME_030 = r'''
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
        if hasattr(self, 'refresh_pet_tag'):
            self.refresh_pet_tag()
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
'''
