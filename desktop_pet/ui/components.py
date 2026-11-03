"""通用小控件：导航、图标按钮、状态胶囊与首页行。"""
from datetime import datetime, timedelta

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette, QPen
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from ..core import parse_due
from ..recurrence import REPEAT_LABELS
from . import icons
from . import tokens as T
from .theme import mono_font, tokens


class NavButton(QPushButton):
    """自绘侧栏导航项，支持 232px 展开与 68px 图标栏。"""

    def __init__(self, label, icon_name, parent=None):
        super().__init__(parent)
        self.label = label
        self.icon_name = icon_name
        self._count = 0
        self._collapsed = False
        self._hover = False
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(T.NAV_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFlat(True)

    def set_collapsed(self, collapsed):
        self._collapsed = bool(collapsed)
        self.setToolTip(self.label if self._collapsed else '')
        self.update()

    def set_count(self, count):
        count = max(0, int(count or 0))
        if count != self._count:
            self._count = count
            self.update()

    def refresh_theme(self):
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def sizeHint(self):
        return QSize(T.RAIL_W - T.SIDEBAR_PAD * 2, T.NAV_H)

    def paintEvent(self, event):
        t = tokens()
        active = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        if active:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.brand_wash))
            painter.drawRoundedRect(rect, T.RADIUS_CTL, T.RADIUS_CTL)
            painter.setBrush(QColor(t.brand))
            painter.drawRoundedRect(QRectF(0, (rect.height() - 18) / 2, 3, 18), 1.5, 1.5)
        elif self._hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.surface_2))
            painter.drawRoundedRect(rect, T.RADIUS_CTL, T.RADIUS_CTL)

        icon_color = t.brand if active else (t.ink_2 if self._hover else t.ink_3)
        icon_size = 18
        icon_x = (rect.width() - icon_size) / 2 if self._collapsed else 12
        painter.drawPixmap(QPointF(icon_x, (rect.height() - icon_size) / 2),
                           icons.pixmap(self.icon_name, icon_color, icon_size))

        if self._collapsed:
            if self._count:
                painter.setPen(QPen(QColor(t.surface), 2))
                painter.setBrush(QColor(t.brand))
                painter.drawEllipse(QPointF(icon_x + icon_size - 1, rect.height() / 2 - 8), 3, 3)
            return

        font = QFont(T.FONT_UI)
        font.setPixelSize(14)
        font.setWeight(QFont.DemiBold if active else QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor(t.brand_press if active else (t.ink if self._hover else t.ink_2)))
        painter.drawText(QRectF(40, 0, rect.width() - 78, rect.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, self.label)

        if self._count:
            count_font = QFont(T.FONT_MONO)
            count_font.setPixelSize(10)
            painter.setFont(count_font)
            badge_w = max(18, painter.fontMetrics().horizontalAdvance(str(self._count)) + 10)
            badge = QRectF(rect.width() - badge_w - 8, (rect.height() - 18) / 2, badge_w, 18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.brand if active else t.surface_3))
            painter.drawRoundedRect(badge, 9, 9)
            painter.setPen(QColor(t.brand_on if active else t.ink_2))
            painter.drawText(badge, Qt.AlignCenter, str(self._count))


class IconButton(QPushButton):
    """无边框图标按钮，用于主题切换等外壳操作。"""

    def __init__(self, icon_name, tooltip='', parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self._hover = False
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setFlat(True)

    def set_icon_name(self, icon_name):
        self.icon_name = icon_name
        self.update()

    def refresh_theme(self):
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
        active = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._hover or active:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.brand_wash if active else t.surface_2))
            painter.drawRoundedRect(QRectF(self.rect()), 8, 8)
        color = t.brand if active else (t.ink if self._hover else t.ink_3)
        if not self.isEnabled():
            color = t.ink_4
        painter.drawPixmap(QPointF((self.width() - 16) / 2, (self.height() - 16) / 2),
                           icons.pixmap(self.icon_name, color, 16))


class LiveBadge(QWidget):
    """winbar 右侧的值守状态胶囊。"""

    TONES = {
        'calm': ('calm_wash', 'calm', 'calm'),
        'caution': ('caution_wash', 'caution', 'caution'),
        'muted': ('surface_2', 'surface_3', 'ink_3'),
    }

    def __init__(self, text='', tone='calm', parent=None):
        super().__init__(parent)
        self.text = text
        self.tone = tone
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_text(self, text):
        if text != self.text:
            self.text = text
            self.updateGeometry()
            self.update()

    def set_tone(self, tone):
        if tone != self.tone:
            self.tone = tone
            self.update()

    def refresh_theme(self):
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        font = self._font()
        return QSize(font.pixelSize() * len(self.text) + 28, 22)

    def _font(self):
        font = QFont(T.FONT_UI)
        font.setPixelSize(10)
        font.setWeight(QFont.DemiBold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 0.4)
        return font

    def paintEvent(self, event):
        t = tokens()
        wash, border, ink = self.TONES.get(self.tone, self.TONES['calm'])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        edge = QColor(getattr(t, border))
        edge.setAlpha(90)
        painter.setPen(QPen(edge, 1))
        painter.setBrush(QColor(getattr(t, wash)))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(getattr(t, ink)))
        painter.drawEllipse(QPointF(10, rect.center().y()), 3, 3)
        painter.setFont(self._font())
        painter.setPen(QColor(getattr(t, ink)))
        painter.drawText(rect.adjusted(18, 0, -9, 0), Qt.AlignLeft | Qt.AlignVCenter, self.text)


class Panel(QFrame):
    """按 token 绘制的卡片底，替代页面内联暖色样式。"""

    def __init__(self, parent=None, radius=T.RADIUS_CARD):
        super().__init__(parent)
        self._radius = radius
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(t.border), 1))
        painter.setBrush(QColor(t.surface))
        painter.drawRoundedRect(rect, self._radius, self._radius)


class ElidedLabel(QLabel):
    """单行标签，按可用宽度省略，避免窄窗口撑出横向滚动。"""

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self._full = text
        self._color = None
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        super().setText(text)

    def setText(self, text):
        self._full = text or ''
        super().setText(self._full)
        self.setToolTip(self._full)
        self.updateGeometry()
        self.update()

    def set_color(self, color):
        self._color = QColor(color) if color else None
        self.update()

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self._color or self.palette().color(QPalette.WindowText))
        text = QFontMetrics(self.font()).elidedText(self._full, Qt.ElideRight, max(0, self.width()))
        painter.drawText(self.rect(), int(self.alignment()) or int(Qt.AlignLeft | Qt.AlignVCenter), text)


class Track(QWidget):
    """5px 进度轨，用于主卡与今日节奏。"""

    def __init__(self, value=0.0, tone='calm', parent=None):
        super().__init__(parent)
        self._value = value
        self._tone = tone
        self.setFixedHeight(5)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value, tone=None):
        self._value = max(0.0, min(1.0, value))
        if tone:
            self._tone = tone
        self.update()

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(t.surface_3))
        painter.drawRoundedRect(rect, 2.5, 2.5)
        if self._value <= 0:
            return
        color = {'alert': t.alert, 'brand': t.brand}.get(self._tone, t.calm)
        fill = QRectF(rect.left(), rect.top(), rect.width() * self._value, rect.height())
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(fill, 2.5, 2.5)


class StatePill(QWidget):
    """21px 状态胶囊；颜色、圆角与字号全站统一。"""

    TONES = {
        'over': ('alert_wash', 'alert'),
        'done': ('calm_wash', 'calm'),
        'today': ('brand_wash', 'brand'),
        'soon': ('caution_wash', 'caution'),
        'info': ('info_wash', 'info'),
        'next': ('surface_2', 'ink_2'),
    }

    def __init__(self, text='', tone='next', icon_name='', parent=None):
        super().__init__(parent)
        self.text = text
        self.tone = tone
        self.icon_name = icon_name
        self.setFixedHeight(21)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_state(self, text, tone='next', icon_name=''):
        self.text = text
        self.tone = tone
        self.icon_name = icon_name
        self.updateGeometry()
        self.update()

    def _font(self):
        font = QFont(T.FONT_UI)
        font.setPixelSize(10)
        font.setWeight(QFont.DemiBold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 0.2)
        return font

    def _text_width(self):
        return QFontMetrics(self._font()).horizontalAdvance(self.text)

    def sizeHint(self):
        icon = 16 if self.icon_name else 0
        return QSize(16 + icon + self._text_width(), 21)

    def paintEvent(self, event):
        t = tokens()
        wash, ink = self.TONES.get(self.tone, self.TONES['next'])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(getattr(t, wash)))
        painter.drawRoundedRect(rect, 10.5, 10.5)
        x = 8
        if self.icon_name:
            painter.drawPixmap(QPointF(x, 5), icons.pixmap(self.icon_name, getattr(t, ink), 11))
            x += 16
        painter.setFont(self._font())
        painter.setPen(QColor(getattr(t, ink)))
        painter.drawText(QRectF(x, 0, rect.width() - x - 6, rect.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, self.text)


class Segmented(QWidget):
    """分段控件：胶囊底 + 当前项抬起，可带等宽计数；用于筛选与密度。"""

    changed = pyqtSignal(str)

    def __init__(self, items, current=None, parent=None):
        super().__init__(parent)
        self._items = []
        for item in items:
            if isinstance(item, str):
                item = {'key': item, 'label': item}
            self._items.append({'key': item['key'], 'label': item.get('label', item['key']),
                                'count': item.get('count')})
        self._current = current or self._items[0]['key']
        self._hover = -1
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

    def key(self):
        return self._current

    def set_current(self, key, emit=False):
        if key == self._current:
            return
        self._current = key
        self.update()
        if emit:
            self.changed.emit(key)

    def set_counts(self, counts):
        changed = False
        for item in self._items:
            if item['key'] in counts and item['count'] != counts[item['key']]:
                item['count'] = counts[item['key']]
                changed = True
        if changed:
            self.updateGeometry()
            self.update()

    def _label_font(self):
        font = QFont(T.FONT_UI)
        font.setPixelSize(12)
        font.setWeight(QFont.DemiBold)
        return font

    def _count_font(self):
        font = QFont(T.FONT_MONO)
        font.setPixelSize(10)
        font.setWeight(QFont.DemiBold)
        return font

    def _widths(self):
        label_fm = QFontMetrics(self._label_font())
        count_fm = QFontMetrics(self._count_font())
        widths = []
        for item in self._items:
            width = 20 + label_fm.horizontalAdvance(item['label'])
            if item['count'] is not None:
                width += 6 + count_fm.horizontalAdvance(str(item['count']))
            widths.append(max(44, width))
        return widths

    def sizeHint(self):
        return QSize(sum(self._widths()) + 6 + 3 * (len(self._items) - 1), 30)

    def _segments(self):
        rects = []
        x = 3
        for width in self._widths():
            rects.append(QRectF(x, 3, width, 24))
            x += width + 3
        return rects

    def _hit(self, pos):
        for index, rect in enumerate(self._segments()):
            if rect.contains(QPointF(pos)):
                return index
        return -1

    def mouseMoveEvent(self, event):
        index = self._hit(event.pos())
        if index != self._hover:
            self._hover = index
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self._hit(event.pos())
            if index >= 0:
                self.set_current(self._items[index]['key'], emit=True)
                event.accept()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        keys = [item['key'] for item in self._items]
        index = keys.index(self._current)
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            step = -1 if event.key() == Qt.Key_Left else 1
            self.set_current(keys[max(0, min(len(keys) - 1, index + step))], emit=True)
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(t.surface_3))
        painter.drawRoundedRect(QRectF(self.rect()), 15, 15)
        label_fm = QFontMetrics(self._label_font())
        count_fm = QFontMetrics(self._count_font())
        for index, (item, rect) in enumerate(zip(self._items, self._segments())):
            active = item['key'] == self._current
            if active:
                painter.setPen(QPen(QColor(t.border), 1))
                painter.setBrush(QColor(t.surface))
                painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
            elif index == self._hover and self.isEnabled():
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(t.surface_2))
                painter.drawRoundedRect(rect, 12, 12)
            painter.setFont(self._label_font())
            painter.setPen(QColor(t.ink if active else (t.ink_3 if self.isEnabled() else t.ink_4)))
            label_width = label_fm.horizontalAdvance(item['label'])
            count_width = count_fm.horizontalAdvance(str(item['count'])) if item['count'] is not None else 0
            content = label_width + (6 + count_width if item['count'] is not None else 0)
            x = rect.left() + (rect.width() - content) / 2
            painter.drawText(QRectF(x, rect.top(), label_width, rect.height()),
                             Qt.AlignLeft | Qt.AlignVCenter, item['label'])
            if item['count'] is not None:
                painter.setFont(self._count_font())
                painter.setPen(QColor(t.ink_2 if active else t.ink_3))
                painter.drawText(QRectF(x + label_width + 6, rect.top(), count_width, rect.height()),
                                 Qt.AlignLeft | Qt.AlignVCenter, str(item['count']))


class RhythmRing(QWidget):
    """今日完成度环，QPainter 绘制，中心数字使用等宽字体。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.done = 0
        self.total = 0
        self.setFixedSize(62, 62)

    def set_value(self, done, total):
        self.done = max(0, int(done))
        self.total = max(0, int(total))
        self.setAccessibleName(f'今天完成 {self.done} 件，共 {self.total} 件')
        self.update()

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(4.5, 4.5, -4.5, -4.5)
        painter.setPen(QPen(QColor(t.surface_3), 7, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)
        ratio = self.done / self.total if self.total else 0.0
        if ratio:
            painter.setPen(QPen(QColor(t.calm), 7, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(rect, 90 * 16, -int(360 * 16 * min(1.0, ratio)))
        painter.setFont(mono_font(12))
        painter.setPen(QColor(t.ink))
        painter.drawText(QRectF(self.rect()), Qt.AlignCenter, f'{self.done}/{self.total}')


def due_when(value, now):
    """状态语言：今天/明天/N 天后；更早的时间给出月日。"""
    due = (value if isinstance(value, datetime) else parse_due(value)).astimezone()
    now = now.astimezone()
    days = (due.date() - now.date()).days
    if days == 0:
        return f'今天 {due:%H:%M}'
    if days == 1:
        return f'明天 {due:%H:%M}'
    if days > 1:
        return f'{days} 天后'
    return f'{due:%m月%d日 %H:%M}'


def overdue_text(due, now):
    minutes = max(0, int((now - due).total_seconds()) // 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'逾期 {hours}小时{minutes}分'
    if minutes:
        return f'逾期 {minutes}分'
    return '逾期 刚刚'


class _Tick(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tone = 'next'
        self.done = False
        self.setFixedSize(20, 20)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_state(self, tone, done):
        self.tone = tone
        self.done = done
        self.update()

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
            painter.setPen(QPen(QColor(color), 1.6))
            painter.setBrush(QColor(t.surface))
        painter.drawEllipse(rect)
        if self.done:
            painter.setPen(QPen(QColor(t.brand_on), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            center = rect.center()
            painter.drawLine(QPointF(center.x() - 4, center.y()),
                             QPointF(center.x() - 1, center.y() + 3))
            painter.drawLine(QPointF(center.x() - 1, center.y() + 3),
                             QPointF(center.x() + 5, center.y() - 3))


class StatusRow(QFrame):
    """首页/待办通用行：3px 状态轨、状态语言、悬停、焦点与键盘触发。"""

    clicked = pyqtSignal()

    def __init__(self, task, now, density='comfortable', parent=None):
        super().__init__(parent)
        self.task = dict(task)
        self.now = now
        self.compact = density == 'compact'
        self.hover = False
        self.done = self.task.get('status') == 'done'
        self.deferred = not self.done and bool(self.task.get('deferred'))
        due = parse_due(self.task['due_at']).astimezone()
        self.overdue = not self.done and due <= now
        self.soon = not self.done and not self.overdue and due - now <= timedelta(minutes=30)
        self.setObjectName('homeTaskRow')
        self.setFixedHeight(T.ROW_H_SM if self.compact else T.ROW_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName(self.task.get('title', ''))
        self._build(due)

    def _build(self, due):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14 if self.compact else 16, 0, 12, 0)
        layout.setSpacing(10)
        self.tick = _Tick()
        layout.addWidget(self.tick, 0, Qt.AlignVCenter)

        self.time_label = QLabel(f'{due:%H:%M}')
        self.time_label.setFont(mono_font(12))
        self._time_style = f'font-family:"{T.FONT_MONO}","Consolas",monospace;font-size:12px;font-weight:600;'
        self.time_label.setStyleSheet(f'{self._time_style}background:transparent;')
        self.time_label.setFixedWidth(52)
        self.time_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.time_label, 0, Qt.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        self.title_label = ElidedLabel(self.task.get('title', ''))
        title_font = QFont(T.FONT_UI)
        title_font.setPixelSize(14 if self.compact else 15)
        title_font.setWeight(QFont.DemiBold)
        title_font.setStrikeOut(self.done)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(
            f'font-family:"{T.FONT_UI}";font-size:{14 if self.compact else 15}px;font-weight:600;')
        text_box.addWidget(self.title_label)
        self.meta_label = ElidedLabel()
        meta_font = QFont(T.FONT_UI)
        meta_font.setPixelSize(11)
        self.meta_label.setFont(meta_font)
        self.meta_label.setStyleSheet(f'font-family:"{T.FONT_UI}";font-size:11px;')
        self.meta_label.setVisible(not self.compact)
        if not self.compact:
            text_box.addWidget(self.meta_label)
        layout.addLayout(text_box, 1)

        self.pill = StatePill()
        layout.addWidget(self.pill, 0, Qt.AlignVCenter)
        self._apply_style(due)

    def _apply_style(self, due=None):
        t = tokens()
        due = due or parse_due(self.task['due_at']).astimezone()
        if self.done:
            tone, text, icon = 'done', '已完成', 'check'
        elif self.deferred:
            tone, text, icon = 'soon', '已延期', 'clock'
        elif self.overdue:
            tone, text, icon = 'over', overdue_text(due, self.now), 'alert'
        else:
            tone, text, icon = ('soon' if self.soon else 'today'), due_when(due, self.now), 'clock'
        self.tick.set_state(tone, self.done)
        self.pill.set_state(text, tone, icon)

        self.title_label.set_color(t.ink_3 if self.done else t.ink)
        self.time_label.setStyleSheet(
            f'{self._time_style}color:{t.alert if self.overdue else (t.ink_3 if self.done else t.ink_2)};'
            'background:transparent;')
        self.meta_label.set_color(t.ink_3)

        parts = []
        repeat = REPEAT_LABELS.get(self.task.get('repeat_rule', 'none'), '不重复')
        if repeat != '不重复':
            parts.append(repeat)
        if self.task.get('dingtalk'):
            parts.append('钉钉')
        if self.task.get('early_notified_at'):
            parts.append('提前 10 分钟提醒过')
        if self.deferred:
            parts.append('提醒已达上限')
        if self.done:
            completed = self.task.get('completed_at')
            if completed:
                done_at = parse_due(completed).astimezone()
                minutes = int((due - done_at).total_seconds() // 60)
                tail = f'提前 {minutes} 分钟' if minutes > 0 else (
                    f'晚 {abs(minutes)} 分钟' if minutes < 0 else '准点')
                parts.append(f'{done_at:%H:%M} 完成，{tail}')
            elif self.task.get('remind_count'):
                parts.append(f'已完成 · 提醒 {self.task["remind_count"]} 次')
        elif self.overdue and self.task.get('remind_count'):
            parts.append(f'已提醒 {self.task["remind_count"]} 次')
        meta = ' · '.join(parts)
        self.meta_label.setText(meta)
        self.meta_label.setVisible(bool(meta) and not self.compact)
        self.setToolTip(f'{self.task.get("title", "")}\n{meta}'.strip())
        self.update()

    def refresh_theme(self):
        self._apply_style()

    def enterEvent(self, event):
        self.hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover = False
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.done:
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
        rail = t.calm if self.done else (t.alert if self.overdue else (
            t.caution if (self.deferred or self.soon) else t.brand))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(rail))
        painter.drawRoundedRect(QRectF(1, 9, 3, rect.height() - 18), 1.5, 1.5)
