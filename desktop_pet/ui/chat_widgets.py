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
        # Markdown 解析会丢弃裸露的 HTML 块，整段变成空文档时退回纯文本，避免内容消失。
        if text.strip() and not document.toPlainText().strip():
            self.setPlainText(text)
            return
        self.fit_height()

    def fit_height(self, *args):
        # QTextDocument emits during resize; defer geometry changes to avoid reentry.
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
