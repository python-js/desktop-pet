"""Reusable controls with vector indicators and native Qt interaction semantics."""
import os
from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor
from PyQt5.QtWidgets import (QPushButton, QComboBox, QSpinBox, QCheckBox, QListView,
                             QSizePolicy, QStyle, QStyleOptionButton, QDateTimeEdit)


def chevron(painter, x, y, up=False, enabled=True):
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor('#8A8178' if enabled else '#C9BBAE'), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    direction = -1 if up else 1
    painter.drawLine(QPointF(x - 3.5, y - direction * 1.7), QPointF(x, y + direction * 1.7))
    painter.drawLine(QPointF(x, y + direction * 1.7), QPointF(x + 3.5, y - direction * 1.7))


class DateTimeEdit(QDateTimeEdit):
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.calendarPopup():
            painter = QPainter(self)
            chevron(painter, self.width() - 15, self.height() / 2, enabled=self.isEnabled())


class Button(QPushButton):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setMinimumHeight(38)


class ComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('nativeCombo')
        self.setView(QListView())
        self.view().setSpacing(3)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setMaxVisibleItems(9)
        self.setStyleSheet('QComboBox::down-arrow { image:none; width:0; height:0; }')

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        chevron(painter, self.width() - 17, self.height() / 2, enabled=self.isEnabled())


class SpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40)
        self.setStyleSheet('QSpinBox { padding-right:32px; } '
                          'QSpinBox::up-button { subcontrol-origin:border; subcontrol-position:top right; width:28px; border:0; background:transparent; } '
                          'QSpinBox::down-button { subcontrol-origin:border; subcontrol-position:bottom right; width:28px; border:0; background:transparent; } '
                          'QSpinBox::up-arrow,QSpinBox::down-arrow { image:none; width:0; height:0; }')

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        chevron(painter, self.width() - 15, self.height() * .28, up=True,
                enabled=self.isEnabled() and self.value() < self.maximum())
        chevron(painter, self.width() - 15, self.height() * .73,
                enabled=self.isEnabled() and self.value() > self.minimum())


class CheckBox(QCheckBox):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('QCheckBox::indicator { width:18px; height:18px; image:none; background:transparent; border:0; }')

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        selected = self.isChecked()
        painter.setPen(QPen(QColor('#C9563F' if selected else '#D9CDC0'), 1))
        painter.setBrush(QColor('#C9563F' if selected and self.isEnabled() else '#ffffff'))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
        if selected:
            painter.setPen(QPen(QColor('#ffffff' if self.isEnabled() else '#B9AEA2'), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            x, y = rect.center().x(), rect.center().y()
            painter.drawLine(QPointF(x - 4, y), QPointF(x - 1, y + 3))
            painter.drawLine(QPointF(x - 1, y + 3), QPointF(x + 5, y - 3))


class PrimaryButton(Button):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setProperty('variant', 'primary')


from PyQt5.QtWidgets import QLineEdit as LineEdit, QTextEdit as TextEdit

FLUENT_MODE = os.environ.get('DESKTOP_PET_UI', 'fluent').lower() != 'native'
if FLUENT_MODE:
    try:
        from .fluent import Button, PrimaryButton, ComboBox, SpinBox, CheckBox, LineEdit, TextEdit
    except ImportError as exc:
        raise ImportError('Fluent组件不可用，请先安装 requirements-fluent.txt；普通启动仍可使用现有界面。') from exc
