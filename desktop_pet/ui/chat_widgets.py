"""对话线程：token 气泡、事件行、流式占位与输入卡。"""
import html
import math

from PyQt5.QtCore import QRectF, QSize, Qt, QTimer
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPalette, QPen, QTextBlockFormat,
                         QTextCursor, QTextDocument, QTextOption)
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QSizePolicy, QTextBrowser, QVBoxLayout, QWidget)
from qfluentwidgets import SmoothScrollArea

from . import icons
from . import tokens as T
from .theme import mono_font, tokens

BUBBLE_MAX = 560


class Rule(QFrame):
    """事件行两侧的发丝线。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tokens().border))


class Avatar(QWidget):
    def __init__(self, user=False, parent=None):
        super().__init__(parent)
        self.user = user
        self.setFixedSize(28, 28)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(t.surface_3 if self.user else t.brand))
        painter.drawRoundedRect(self.rect(), 9, 9)
        color = t.ink_2 if self.user else t.brand_on
        painter.drawPixmap(6, 6, icons.pixmap('user' if self.user else 'paw', color, 16))


class Bubble(QFrame):
    def __init__(self, user=False, parent=None):
        super().__init__(parent)
        self.user = user
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.refresh_theme()

    def refresh_theme(self):
        t = tokens()
        fill = t.brand_wash if self.user else t.surface
        edge = t.brand_line if self.user else t.border
        radius = ('border-top-left-radius:14px;border-top-right-radius:14px;'
                  'border-bottom-left-radius:5px;border-bottom-right-radius:14px;' if self.user else
                  'border-top-left-radius:14px;border-top-right-radius:14px;'
                  'border-bottom-left-radius:14px;border-bottom-right-radius:5px;')
        self.setObjectName('msgBubble')
        self.setStyleSheet(f'QFrame#msgBubble{{background:{fill};border:1px solid {edge};{radius}}}')


class EventPill(QWidget):
    """系统回执：中性胶囊 + 勾选图标，长文按可用宽度省略。"""

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.text = text
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def _font(self):
        font = QFont(T.FONT_UI)
        font.setPixelSize(11)
        font.setWeight(QFont.DemiBold)
        return font

    def display_text(self):
        # 回执可能带换行；QRect 版 drawText 会把换行画成多行，先压平成单行再省略。
        flat = ' '.join(self.text.split())
        return QFontMetrics(self._font()).elidedText(flat, Qt.ElideRight, max(0, self.width() - 32))

    def sizeHint(self):
        width = QFontMetrics(self._font()).horizontalAdvance(' '.join(self.text.split())) + 38
        return QSize(min(540, width), 22)

    def minimumSizeHint(self):
        return QSize(40, 22)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor(t.border), 1))
        painter.setBrush(QColor(t.surface_2))
        painter.drawRoundedRect(rect, 11, 11)
        painter.drawPixmap(9, 5, icons.pixmap('check', t.ink_3, 11))
        painter.setFont(self._font())
        painter.setPen(QColor(t.ink_2))
        painter.drawText(rect.adjusted(24, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, self.display_text())


class MessageText(QTextBrowser):
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._height_timer = QTimer(self)
        self._height_timer.setSingleShot(True)
        self._height_timer.timeout.connect(self._apply_height)
        self.document().setDocumentMargin(0)
        option = self.document().defaultTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(option)
        self.document().documentLayout().documentSizeChanged.connect(self.fit_height)
        self.setPlainText(text)

    def refresh_theme(self, user=False):
        t = tokens()
        color = t.brand_press if user else t.ink
        # 与气泡同色不透明底：流式重排只重绘正文，不再向气泡和祖先逐层要底色。
        fill = t.brand_wash if user else t.surface
        self.setStyleSheet(f'QTextBrowser{{background:{fill};border:0;padding:0;color:{color};'
                           f'font-family:"{T.FONT_UI}";font-size:13px;}}')
        palette = self.palette()
        palette.setColor(QPalette.Link, QColor(t.brand_hover))
        palette.setColor(QPalette.LinkVisited, QColor(t.brand_hover))
        self.setPalette(palette)
        self.document().setDefaultStyleSheet(f'a{{color:{t.brand_hover};}}')

    def setPlainText(self, text):
        super().setPlainText(text)
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.Document)
        block = QTextBlockFormat()
        block.setLineHeight(165, QTextBlockFormat.ProportionalHeight)
        cursor.mergeBlockFormat(block)
        self.fit_height()

    def append_plain(self, text):
        """增量追加流式正文：只排新增段落，避免整篇重置造成的闪动。"""
        if not text:
            return
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.fit_height()

    def setMarkdown(self, text):
        document = self.document()
        font = QFont(T.FONT_UI)
        font.setPixelSize(13)
        document.setDefaultFont(font)
        document.setMarkdown(text, QTextDocument.MarkdownDialectGitHub)
        # Markdown 解析会把链接写死成 #0000ff，需按当前主题重新着色。
        self._recolor_links()
        # Markdown 解析会丢弃裸露的 HTML 块，整段变成空文档时退回纯文本，避免内容消失。
        if text.strip() and not document.toPlainText().strip():
            self.setPlainText(text)
            return
        self.fit_height()

    def _recolor_links(self):
        color = QColor(tokens().brand_hover)
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.Start)
        while cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor):
            fmt = cursor.charFormat()
            if fmt.isAnchor() and fmt.anchorHref():
                fmt.setForeground(color)
                cursor.mergeCharFormat(fmt)
            cursor.clearSelection()

    def natural_width(self):
        font = QFont(T.FONT_UI)
        font.setPixelSize(13)
        metrics = QFontMetrics(font)
        lines = (self.toPlainText() or '').splitlines() or ['']
        return max(24, max(metrics.horizontalAdvance(line) for line in lines) + 5)

    def fit_height(self, *args):
        # QTextDocument emits during resize; defer geometry changes to avoid reentry.
        self._height_timer.start(0)

    def _apply_height(self):
        height = max(24, math.ceil(self.document().size().height()) + 3)
        if height != self.height():
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(max(1, self.viewport().width()))
        self.fit_height()


class MessageRow(QWidget):
    def __init__(self, role, content, parent=None):
        super().__init__(parent)
        self.role = role
        self.system = role == 'system'
        self.user = role == 'user'
        self._content = content or ''
        self._markdown = False
        self._error_box = None
        self.meta = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 0)
        layout.setSpacing(10)
        if self.system:
            self.pill = EventPill(self._content)
            layout.addWidget(Rule(), 1)
            layout.addWidget(self.pill, 0)
            layout.addWidget(Rule(), 1)
            return
        self.avatar = Avatar(self.user)
        self.bubble = Bubble(self.user)
        body = QVBoxLayout(self.bubble)
        body.setContentsMargins(14, 11, 14, 12)
        body.setSpacing(4)
        self.text = MessageText('', self.bubble)
        self.text.refresh_theme(self.user)
        body.addWidget(self.text)
        self.materials = QLabel('')
        self.materials.setTextFormat(Qt.PlainText)
        self.materials.setWordWrap(True)
        self.materials.hide()
        body.addWidget(self.materials)
        self._materials = []
        self.sources = QLabel('')
        self.sources.setTextFormat(Qt.RichText)
        self.sources.setOpenExternalLinks(True)
        self.sources.setWordWrap(True)
        self.sources.hide()
        body.addWidget(self.sources)
        self._sources = []
        self.meta = QLabel('')
        self.meta.setWordWrap(True)
        self.meta.hide()
        body.addWidget(self.meta)
        if self.user:
            layout.addStretch(1)
            layout.addWidget(self.bubble, 0)
            layout.addWidget(self.avatar, 0, Qt.AlignTop)
        else:
            layout.addWidget(self.avatar, 0, Qt.AlignTop)
            layout.addWidget(self.bubble, 1)
        self.set_content(self._content, self.role == 'assistant')

    def set_content(self, content, markdown=False):
        content = content or ''
        if (not markdown and not self.user and not self._markdown and self._content
                and content.startswith(self._content)):
            self.text.append_plain(content[len(self._content):])
            self._content = content
            return
        self._content = content
        self._markdown = bool(markdown)
        if self.system:
            self.pill.text = self._content
            self.pill.updateGeometry()
            self.pill.update()
            return
        if self._markdown:
            self.text.setMarkdown(self._content)
        else:
            self.text.setPlainText(self._content)
        self._sync_width()

    def _sync_width(self):
        if not self.user:
            return
        available = max(180, self.width() - 54)
        text_limit = max(60, min(BUBBLE_MAX, available) - 30)
        width = min(self.text.natural_width(), text_limit)
        if self.text.width() != width:
            self.text.setFixedWidth(width)

    def set_materials(self, hits):
        self._materials = []
        for item in hits or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get('doc_name') or item.get('title') or '').strip()
            if name and name not in self._materials:
                self._materials.append(name)
            if len(self._materials) == 4:
                break
        self._render_materials()

    def _render_materials(self):
        if not self._materials:
            self.materials.hide()
            self.materials.clear()
            return
        self.materials.setText('资料：' + '　·　'.join(f'《{name}》' for name in self._materials))
        self.materials.show()

    def set_sources(self, sources):
        self._sources = [(str(item.get('title') or item.get('url') or ''),
                          str(item.get('url') or '')) for item in (sources or [])
                         if isinstance(item, dict)
                         and str(item.get('url') or '').lower().startswith(('http://', 'https://'))][:5]
        self._render_sources()

    def _render_sources(self):
        if not self._sources:
            self.sources.hide()
            self.sources.clear()
            return
        t = tokens()
        links = []
        for title, url in self._sources:
            links.append(f'<a href="{html.escape(url, quote=True)}" style="color:{t.brand_hover};'
                         f'text-decoration:none;">{html.escape(title or url)}</a>')
        self.sources.setText('来源：' + '　·　'.join(links))
        self.sources.show()

    def set_meta(self, text):
        if self.meta is None:
            return
        self.meta.setText(text or '')
        self.meta.setVisible(bool(text))

    def show_error(self, content, reason, on_retry=None, on_local=None):
        self.set_content(content or '发送失败', False)
        if self._error_box is not None:
            self._error_box.hide()
            self._error_box.deleteLater()
        box = QFrame()
        box.setObjectName('chatError')
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(6)
        self.error_reason = QLabel((reason or '请求失败').strip())
        self.error_reason.setWordWrap(True)
        self.error_hint = QLabel('可检查模型设置后重试；也可以先用本地规则记下。')
        self.error_hint.setWordWrap(True)
        layout.addWidget(self.error_reason)
        layout.addWidget(self.error_hint)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        if on_retry is not None:
            self.error_retry = self._small_button('重试', on_retry, True)
            buttons.addWidget(self.error_retry)
        if on_local is not None:
            self.error_local = self._small_button('用本地规则记下', on_local)
            buttons.addWidget(self.error_local)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        body = self.bubble.layout()
        body.insertWidget(body.indexOf(self.meta), box)
        self._error_box = box
        self.refresh_theme()

    def clear_error(self):
        if self._error_box is not None:
            self._error_box.hide()
            self._error_box.deleteLater()
            self._error_box = None

    @staticmethod
    def _small_button(text, callback, primary=False):
        control = QPushButton(text)
        control.setCursor(Qt.PointingHandCursor)
        control.setFixedHeight(26)
        control.clicked.connect(callback)
        control.setProperty('primary', primary)
        return control

    def refresh_theme(self):
        t = tokens()
        if self.system:
            self.pill.update()
            return
        self.bubble.refresh_theme()
        self.avatar.update()
        self.text.refresh_theme(self.user)
        self.set_content(self._content, self._markdown)
        if self.meta is not None:
            self.meta.setStyleSheet(f'background:transparent;color:{t.ink_4};'
                                    f'font-family:"{T.FONT_UI}";font-size:10px;')
        self.materials.setStyleSheet(f'background:transparent;color:{t.ink_3};'
                                     f'font-family:"{T.FONT_UI}";font-size:10px;')
        self.sources.setStyleSheet(f'background:transparent;color:{t.ink_3};'
                                   f'font-family:"{T.FONT_UI}";font-size:10px;')
        self._render_materials()
        self._render_sources()
        if self._error_box is not None:
            self._error_box.setStyleSheet(f'QFrame#chatError{{background:{t.alert_wash};'
                                          'border:1px solid transparent;border-radius:9px;}')
            self.error_reason.setStyleSheet(f'background:transparent;color:{t.alert};'
                                            f'font-family:"{T.FONT_UI}";font-size:11px;font-weight:600;')
            self.error_hint.setStyleSheet(f'background:transparent;color:{t.ink_3};'
                                          f'font-family:"{T.FONT_UI}";font-size:10px;')
            for name in ('error_retry', 'error_local'):
                control = getattr(self, name, None)
                if control is None:
                    continue
                primary = control.property('primary')
                fill = t.brand if primary else 'transparent'
                color = t.brand_on if primary else t.ink_2
                edge = t.brand if primary else t.border
                control.setStyleSheet(
                    f'QPushButton{{background:{fill};color:{color};border:1px solid {edge};'
                    'border-radius:8px;padding:0 10px;font-size:11px;}'
                    f'QPushButton:hover{{border-color:{t.brand};}}')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.system:
            self.pill.setMaximumWidth(max(140, self.width() - 72))
            return
        self._sync_width()


class MessageHistory(SmoothScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet('QScrollArea { background:transparent; border:0; }')
        self.content = QWidget()
        self.content.setStyleSheet('background:transparent;')
        self.rows = QVBoxLayout(self.content)
        self.gutter = 32
        self.rows.setContentsMargins(self.gutter, 8, self.gutter, 12)
        self.rows.setSpacing(0)
        self.rows.addStretch()
        self.setWidget(self.content)
        self.messages = []
        self._rows = []
        self._follow_timer = QTimer(self)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.timeout.connect(self._scroll_to_end)
        self.placeholder = self._build_placeholder()
        self.rows.insertWidget(0, self.placeholder)

    def _build_placeholder(self):
        holder = QWidget(self.content)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(8)
        self.placeholder_mark = QLabel()
        self.placeholder_mark.setFixedSize(40, 40)
        self.placeholder_mark.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.placeholder_mark, 0, Qt.AlignHCenter)
        self.placeholder_title = QLabel('从一句话开始')
        self.placeholder_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.placeholder_title)
        self.placeholder_hint = QLabel('说出事项和时间，小满替你记成待办。')
        self.placeholder_hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.placeholder_hint)
        layout.addStretch(1)
        self.refresh_theme()
        return holder

    def clear(self):
        self._follow_timer.stop()
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget == self.placeholder:
                self.placeholder.setParent(self.content)
                self.placeholder.hide()
            elif widget is not None:
                widget.hide()
                widget.deleteLater()
        self.messages.clear()
        self._rows.clear()
        self.rows.insertWidget(0, self.placeholder)
        self.placeholder.show()

    def append_message(self, role, content):
        bar = self.verticalScrollBar()
        follow = bar.maximum() - bar.value() < 60
        self.placeholder.hide()
        previous = self.messages[-1][0] if self.messages else None
        self.messages.append((role, content))
        row = MessageRow(role, content, self.content)
        if previous is None:
            gap = 8
        elif role == 'system' or previous == 'system':
            gap = 16
        elif previous == 'user' and role == 'assistant':
            gap = 6
        else:
            gap = 22
        row.layout().setContentsMargins(8, gap, 8, 0)
        self.rows.insertWidget(self.rows.count() - 1, row)
        self._rows.append(row)
        if follow:
            self._follow_timer.start(100)
        return row

    def scroll_to_end(self):
        self._follow_timer.start(100)

    def update_row(self, row, content, markdown=False):
        bar = self.verticalScrollBar()
        follow = bar.maximum() - bar.value() < 60
        row.set_content(content, markdown)
        if self.messages:
            self.messages[-1] = (row.role, content)
        if follow:
            self._follow_timer.start(100)

    def show_error(self, row, content, reason, on_retry=None, on_local=None):
        bar = self.verticalScrollBar()
        follow = bar.maximum() - bar.value() < 60
        row.show_error(content, reason, on_retry, on_local)
        if self.messages:
            self.messages[-1] = (row.role, content)
        if follow:
            self._follow_timer.start(100)

    def set_sources(self, row, sources):
        bar = self.verticalScrollBar()
        follow = bar.maximum() - bar.value() < 60
        row.set_sources(sources)
        if follow:
            self._follow_timer.start(100)

    def set_materials(self, row, hits):
        bar = self.verticalScrollBar()
        follow = bar.maximum() - bar.value() < 60
        row.set_materials(hits)
        if follow:
            self._follow_timer.start(100)

    def refresh_theme(self):
        if not hasattr(self, 'placeholder_mark'):
            return
        t = tokens()
        # 与聊天列同色不透明：正文重排的重绘止步于视口，不再逐层上报整窗。
        self.setStyleSheet(f'QScrollArea{{background:{t.bg};border:0;}}')
        self.viewport().setStyleSheet(f'background:{t.bg};')
        self.content.setStyleSheet(f'background:{t.bg};')
        self.placeholder_mark.setStyleSheet(f'background:{t.calm_wash};border-radius:20px;')
        self.placeholder_mark.setPixmap(icons.pixmap('paw', t.calm, 19))
        self.placeholder_title.setStyleSheet(f'background:transparent;color:{t.ink};'
                                             f'font-family:"{T.FONT_UI}";font-size:15px;font-weight:600;')
        self.placeholder_hint.setStyleSheet(f'background:transparent;color:{t.ink_3};'
                                            f'font-family:"{T.FONT_UI}";font-size:12px;')
        for row in self._rows:
            row.refresh_theme()
        for rule in self.content.findChildren(Rule):
            rule.update()

    def set_gutter(self, gutter):
        gutter = max(8, int(gutter))
        if gutter != self.gutter:
            self.gutter = gutter
            self.rows.setContentsMargins(self.gutter, 8, self.gutter, 12)

    def _scroll_to_end(self):
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def toPlainText(self):
        return '\n\n'.join(content for role, content in self.messages)

    def setPlainText(self, content):
        if len(self.messages) == 1 and self.messages[0][0] == 'assistant' and self._rows:
            row = self._rows[-1]
            row.set_content(content or '正在思考…', False)
            self.messages[0] = ('assistant', content)
        else:
            self.clear()
            self.append_message('assistant', content or '正在思考…')


class ComposerCard(QFrame):
    """输入卡：描边承担分隔，聚焦时描边转为品牌色。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.focused = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_StyledBackground, False)

    def set_focused(self, focused):
        focused = bool(focused)
        if focused != self.focused:
            self.focused = focused
            self.update()

    def _sync_focus(self):
        self.set_focused(self.isAncestorOf(QApplication.focusWidget()))

    def eventFilter(self, obj, event):
        if event.type() in (event.FocusIn, event.FocusOut):
            QTimer.singleShot(0, self._sync_focus)
        return super().eventFilter(obj, event)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(t.brand if self.focused else t.border_strong), 1.5 if self.focused else 1))
        painter.setBrush(QColor(t.surface))
        painter.drawRoundedRect(rect, T.RADIUS_CARD, T.RADIUS_CARD)

    def refresh_theme(self):
        self.update()


class ModelChip(QWidget):
    """等宽模型名胶囊，圆点表示已配置模型。"""

    def __init__(self, text='本地规则', online=False, parent=None):
        super().__init__(parent)
        self.text = text
        self.online = online
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_text(self, text, online):
        if (text, online) != (self.text, self.online):
            self.text, self.online = text, online
            self.updateGeometry()
            self.update()

    def _font(self):
        font = QFont(T.FONT_MONO)
        font.setPixelSize(10)
        return font

    def sizeHint(self):
        width = QFontMetrics(self._font()).horizontalAdvance(self.text) + 26
        return QSize(width, 26)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(t.surface_2))
        painter.drawRoundedRect(rect, 13, 13)
        painter.setBrush(QColor(t.calm if self.online else t.ink_3))
        painter.drawEllipse(9, 10, 6, 6)
        painter.setFont(self._font())
        painter.setPen(QColor(t.ink_2))
        painter.drawText(rect.adjusted(20, 0, -9, 0), Qt.AlignLeft | Qt.AlignVCenter, self.text)


# 0.30 旧对话组件实现保留备查（P4 重构前版本，需回退时可整体替换上方实现）：
_LEGACY_CHAT_WIDGETS_030 = r'''
"""Selectable plain-text messages, avatars and shared focus surfaces."""
import math
from PyQt5.QtCore import Qt, QTimer, QEvent, QPropertyAnimation
from PyQt5.QtGui import QColor, QTextBlockFormat, QTextCursor, QTextDocument, QTextOption, QPixmap, QPainter
from PyQt5.QtWidgets import (QFrame, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QTextBrowser, QGraphicsDropShadowEffect, QSizePolicy)
from qfluentwidgets import SmoothScrollArea, AvatarWidget, FluentIcon
from .theme import ACCENT, ACCENT_SOFT, INK, MUTED, application_icon


class Surface(QFrame):
    def __init__(self, parent=None, color='#FFFFFF', shadow=True):
        super().__init__(parent)
        self.setObjectName('surface')
        self.setStyleSheet(f'QFrame#surface {{ background:{color}; border:1px solid transparent; border-radius:16px; }}'
                          f'QFrame#surface[focused="true"] {{ border-color:{ACCENT}; }}')
        if shadow:
            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(30)
            effect.setOffset(0, 6)
            effect.setColor(QColor(120, 82, 60, 20))
            self.setGraphicsEffect(effect)
            self.hover_animation = QPropertyAnimation(effect, b'color', self)
            self.hover_animation.setDuration(160)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.setProperty('focused', event.type() == QEvent.FocusIn)
            self.style().unpolish(self)
            self.style().polish(self)
        return super().eventFilter(obj, event)

    def enterEvent(self, event):
        if hasattr(self, 'hover_animation'):
            self.hover_animation.stop()
            self.hover_animation.setStartValue(self.graphicsEffect().color())
            self.hover_animation.setEndValue(QColor(120, 82, 60, 32))
            self.hover_animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if hasattr(self, 'hover_animation'):
            self.hover_animation.stop()
            self.hover_animation.setStartValue(self.graphicsEffect().color())
            self.hover_animation.setEndValue(QColor(120, 82, 60, 20))
            self.hover_animation.start()
        super().leaveEvent(event)


class MessageText(QTextBrowser):
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(f'QTextBrowser {{ background:transparent; border:0; padding:0; color:{INK}; font-size:14px; }}')
        self._height_timer = QTimer(self)
        self._height_timer.setSingleShot(True)
        self._height_timer.timeout.connect(self._apply_height)
        self.document().setDocumentMargin(0)
        option = self.document().defaultTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(option)
        self.document().documentLayout().documentSizeChanged.connect(self.fit_height)
        self.setPlainText(text)

    def setPlainText(self, text):
        super().setPlainText(text)
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.Document)
        block = QTextBlockFormat()
        block.setLineHeight(150, QTextBlockFormat.ProportionalHeight)
        cursor.mergeBlockFormat(block)
        self.fit_height()

    def setMarkdown(self, text):
        document = self.document()
        document.setDefaultFont(self.font())
        document.setMarkdown(text, QTextDocument.MarkdownDialectGitHub)
        if text.strip() and not document.toPlainText().strip():
            self.setPlainText(text)
            return
        self.fit_height()

    def fit_height(self, *args):
        self._height_timer.start(0)

    def _apply_height(self):
        height = max(25, math.ceil(self.document().size().height()) + 3)
        if height != self.height():
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(max(1, self.viewport().width()))
        self.fit_height()


class MessageRow(QWidget):
    def __init__(self, role, content, parent=None):
        super().__init__(parent)
        self.role = role
        self.system = role == 'system'
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 8)
        layout.setSpacing(12)
        if self.system:
            label = QLabel(content)
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            label.setAlignment(Qt.AlignCenter)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setStyleSheet(f'background:#F4EEE7;color:{MUTED};border-radius:9px;padding:8px 14px;font-size:12px;')
            layout.addStretch()
            layout.addWidget(label)
            layout.addStretch()
            self.bubble = label
            return
        user = role == 'user'
        avatar = AvatarWidget(self)
        avatar.setRadius(17)
        if user:
            image = QPixmap(40, 40)
            image.fill(QColor('#FBE3DA'))
            painter = QPainter(image)
            FluentIcon.PEOPLE.render(painter, image.rect().adjusted(10, 10, -10, -10))
            painter.end()
            avatar.setImage(image)
        else:
            avatar.setImage(application_icon().pixmap(40, 40))
        self.bubble = Surface(self, ACCENT_SOFT if user else '#FFFFFF', shadow=not user)
        body = QVBoxLayout(self.bubble)
        body.setContentsMargins(18, 13, 18, 15)
        body.setSpacing(6)
        name = QLabel('你' if user else '桌面伙伴')
        name.setStyleSheet(f'background:transparent;color:{MUTED};font-size:12px;')
        body.addWidget(name)
        self.text = MessageText(content, self.bubble)
        if role == 'assistant':
            self.text.setMarkdown(content)
        body.addWidget(self.text)
        if user:
            layout.addStretch(1)
            layout.addWidget(self.bubble, 4)
            layout.addWidget(avatar, 0, Qt.AlignTop)
        else:
            layout.addWidget(avatar, 0, Qt.AlignTop)
            layout.addWidget(self.bubble, 4)
            layout.addStretch(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.system:
            self.bubble.setFixedWidth(min(max(100, self.width() - 32), 540,
                                          self.bubble.fontMetrics().horizontalAdvance(self.bubble.text()) + 32))
            return
        self.bubble.setMaximumWidth(max(160, int(self.width() * .79) - 46))

    def set_content(self, content, markdown=False):
        if markdown:
            self.text.setMarkdown(content)
        else:
            self.text.setPlainText(content)


class MessageHistory(SmoothScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet('QScrollArea { background:transparent; border:0; }')
        self.content = QWidget()
        self.content.setStyleSheet('background:transparent;')
        self.rows = QVBoxLayout(self.content)
        self.rows.setContentsMargins(0, 8, 12, 12)
        self.rows.setSpacing(0)
        self.rows.addStretch()
        self.setWidget(self.content)
        self.messages = []
        self._follow_timer = QTimer(self)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.timeout.connect(self._scroll_to_end)
        self.placeholder = QLabel('从一句话开始\n\n聊聊想法，或试试“明天15:00提醒我交报告”。', self.content)
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet('color:#A3998D;font-size:14px;padding:28px;')
        self.rows.insertWidget(0, self.placeholder)

    def clear(self):
        self._follow_timer.stop()
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            if item.widget() == self.placeholder:
                self.placeholder.setParent(self.content)
                self.placeholder.hide()
            else:
                item.widget().deleteLater()
        self.messages.clear()
        self.rows.insertWidget(0, self.placeholder)
        self.placeholder.show()

    def append_message(self, role, content):
        bar = self.verticalScrollBar()
        follow = bar.maximum() - bar.value() < 60
        self.placeholder.hide()
        previous = self.messages[-1][0] if self.messages else None
        self.messages.append((role, content))
        row = MessageRow(role, content, self.content)
        gap = 4 if previous is None else (12 if previous == 'user' and role == 'assistant' else 24)
        row.layout().setContentsMargins(8, gap, 8, 8)
        self.rows.insertWidget(self.rows.count() - 1, row)
        if follow:
            self._follow_timer.start(100)
        return row

    def scroll_to_end(self):
        self._follow_timer.start(100)

    def update_row(self, row, content, markdown=False):
        bar = self.verticalScrollBar()
        follow = bar.maximum() - bar.value() < 60
        row.set_content(content, markdown)
        if self.messages:
            self.messages[-1] = (row.role, content)
        if follow:
            self._follow_timer.start(100)

    def _scroll_to_end(self):
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def toPlainText(self):
        return '\n\n'.join(content for role, content in self.messages)

    def setPlainText(self, content):
        if len(self.messages) == 1 and self.messages[0][0] == 'assistant':
            row = self.rows.itemAt(self.rows.count() - 2).widget()
            row.text.setPlainText(content or '正在思考…')
            self.messages[0] = ('assistant', content)
        else:
            self.clear()
            self.append_message('assistant', content or '正在思考…')
'''
