"""侧栏签名元素：宠物领口铭牌，控制台与桌面本体的连接点。"""
from datetime import datetime

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..core import parse_due
from . import icons
from . import tokens as T
from .theme import tokens

CUT = 32
EYELET = QPointF(23, 23)


def countdown(value, now=None):
    if not value:
        return '暂无'
    now = now or datetime.now().astimezone()
    seconds = int((parse_due(value).astimezone() - now).total_seconds())
    if seconds <= 0:
        return '现在'
    minutes = seconds // 60
    if minutes < 60:
        return f'{max(1, minutes)}分钟'
    hours = minutes // 60
    if hours < 24:
        return f'{hours}小时'
    days = hours // 24
    return f'{days}天{hours % 24}时' if hours % 24 else f'{days}天'


class TagActionButton(QPushButton):
    def __init__(self, text, icon_name, parent=None):
        super().__init__(text, parent)
        self.icon_name = icon_name
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_action(self, text, icon_name, tooltip):
        self.setText(text)
        self.icon_name = icon_name
        self.setToolTip(tooltip)
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._hover:
            fill, border = QColor(t.brand_wash), QColor(t.brand_line)
        else:
            fill, border = QColor(t.surface), QColor(t.border)
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 9, 9)
        color = t.brand if self._hover else t.ink_2
        painter.drawPixmap(QPointF(9, (rect.height() - 14) / 2), icons.pixmap(self.icon_name, color, 14))
        font = QFont(T.FONT_UI)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(rect.adjusted(28, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter, self.text())


class PetTag(QWidget):
    chat_requested = pyqtSignal()
    pause_toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.name = '小满'
        self.mode_label = '2D · 内置'
        self.paused = False
        self.collapsed = False
        self.today_count = 0
        self.next_due = None
        self._set_expanded_size()
        self.content = QWidget(self)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(6)
        head.addSpacing(34)
        self.name_label = QLabel(self.name)
        head.addWidget(self.name_label)
        head.addStretch()
        self.mode_chip = QLabel(self.mode_label)
        self.mode_chip.setAlignment(Qt.AlignCenter)
        head.addWidget(self.mode_chip)
        layout.addLayout(head)

        self.state_label = QLabel()
        layout.addWidget(self.state_label)
        layout.addSpacing(6)

        self.today_value = self._meta_row(layout, '今天替你盯着')
        self.next_value = self._meta_row(layout, '下一次提醒')
        layout.addSpacing(8)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.chat_button = TagActionButton('说句话', 'chat', self)
        self.chat_button.setToolTip('切到对话助手并聚焦输入框')
        self.chat_button.clicked.connect(lambda checked=False: self.chat_requested.emit())
        self.pause_button = TagActionButton('歇会儿', 'pause', self)
        self.pause_button.setToolTip('暂停桌宠动作与走动，不影响待办提醒')
        self.pause_button.clicked.connect(lambda checked=False: self.pause_toggled.emit())
        actions.addWidget(self.chat_button)
        actions.addWidget(self.pause_button)
        layout.addLayout(actions)

        self.refresh_theme()
        self.set_stats(0, None)

    def _set_expanded_size(self):
        self.setFixedSize(T.RAIL_W - T.SIDEBAR_PAD * 2, 196)

    def _meta_row(self, layout, caption):
        line = QFrame()
        line.setFixedHeight(1)
        layout.addSpacing(5)
        layout.addWidget(line)
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 6, 0, 6)
        box.setSpacing(6)
        key = QLabel(caption)
        box.addWidget(key)
        box.addStretch()
        value = QLabel('—')
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        box.addWidget(value)
        layout.addWidget(row)
        line.setProperty('role', 'separator')
        if not hasattr(self, '_separators'):
            self._separators = []
        self._separators.append(line)
        if not hasattr(self, '_captions'):
            self._captions = []
        self._captions.append(key)
        return value

    def set_stats(self, today_count, next_due, pending_count=None):
        self.today_count = int(today_count or 0)
        self.next_due = next_due
        self.today_value.setText(f'{self.today_count} 件')
        self.next_value.setText(countdown(next_due))
        if pending_count is not None:
            self.setToolTip(f'未完成 {int(pending_count)} 件；点击“说句话”打开对话助手')
        self.update()

    def set_paused(self, paused):
        self.paused = bool(paused)
        self._sync_state()
        self.update()

    def set_mode(self, mode_label):
        self.mode_label = mode_label
        self.mode_chip.setText(mode_label)
        self.update()

    def set_collapsed(self, collapsed):
        collapsed = bool(collapsed)
        if collapsed == self.collapsed:
            return
        self.collapsed = collapsed
        self.content.setVisible(not collapsed)
        if collapsed:
            self.setFixedSize(52, 112)
        else:
            self._set_expanded_size()
        self.update()

    def refresh_theme(self):
        t = tokens()
        self.name_label.setStyleSheet(f'color:{t.ink};font-size:15px;font-weight:700;background:transparent;')
        self.mode_chip.setStyleSheet(
            f'background:{t.surface_3};color:{t.ink_2};border-radius:9px;'
            'padding:2px 7px;font-size:10px;font-weight:600;')
        for line in self._separators:
            line.setStyleSheet(f'border-top:1px dashed {t.border_strong};')
        for key in self._captions:
            key.setStyleSheet(f'color:{t.ink_3};font-size:10px;background:transparent;')
        for value in (self.today_value, self.next_value):
            value.setStyleSheet(f'color:{t.ink};font-size:12px;font-weight:600;background:transparent;')
        self._sync_state()
        self.chat_button.update()
        self.pause_button.update()
        self.update()

    def _sync_state(self):
        t = tokens()
        if self.paused:
            self.state_label.setText('●  歇会儿中')
            self.state_label.setStyleSheet(
                f'color:{t.ink_3};font-size:10px;font-weight:600;background:transparent;')
            self.pause_button.set_action('继续值守', 'play', '恢复桌宠动作与走动')
        else:
            self.state_label.setText('●  值守中 · 屏幕右上角')
            self.state_label.setStyleSheet(
                f'color:{t.calm};font-size:10px;font-weight:600;background:transparent;')
            self.pause_button.set_action('歇会儿', 'pause', '暂停桌宠动作与走动，不影响待办提醒')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.content.setGeometry(1, 1, self.width() - 2, self.height() - 2)

    def _shape(self, rect, cut=CUT):
        path = QPainterPath()
        path.moveTo(rect.left() + cut, rect.top())
        path.lineTo(rect.right(), rect.top())
        path.lineTo(rect.right(), rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + cut)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.collapsed:
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.setPen(QPen(QColor(t.border), 1))
            painter.setBrush(QColor(t.surface_2))
            painter.drawRoundedRect(rect, 12, 12)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.calm if not self.paused else t.ink_4))
            painter.drawEllipse(QPointF(rect.center().x(), 16), 3, 3)
            name_font = QFont(T.FONT_UI)
            name_font.setPixelSize(13)
            name_font.setWeight(QFont.DemiBold)
            painter.setFont(name_font)
            painter.setPen(QColor(t.ink))
            for index, char in enumerate(self.name):
                painter.drawText(QRectF(0, 30 + index * 18, rect.width(), 18), Qt.AlignCenter, char)
            state_font = QFont(T.FONT_UI)
            state_font.setPixelSize(9)
            painter.setFont(state_font)
            painter.setPen(QColor(t.calm if not self.paused else t.ink_4))
            for index, char in enumerate('歇会儿中' if self.paused else '值守中'):
                painter.drawText(QRectF(0, 68 + index * 13, rect.width(), 13), Qt.AlignCenter, char)
            return

        outer = QRectF(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(t.border_strong))
        painter.drawPath(self._shape(outer))
        inner = outer.adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(t.surface_2))
        painter.drawPath(self._shape(inner, CUT - 1))
        painter.setPen(QPen(QColor(t.border_strong), 1.5))
        painter.setBrush(QColor(t.surface))
        painter.drawEllipse(EYELET, 5, 5)
