"""Explicit, optional QFluentWidgets adapters; enable only with installed extras."""
from PyQt5.QtWidgets import QComboBox as NativeComboBox, QSizePolicy
from PyQt5.QtCore import Qt
from qfluentwidgets import (PushButton, PrimaryPushButton, ComboBox as FluentComboBox,
                            SpinBox as FluentSpinBox, CheckBox, LineEdit as FluentLineEdit, TextEdit,
                            setTheme, Theme, setThemeColor, setCustomStyleSheet)


def configure_fluent():
    setTheme(Theme.LIGHT)
    setThemeColor('#C9563F')


class LineEdit(FluentLineEdit):
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setMinimumHeight(36)
        setCustomStyleSheet(self, 'LineEdit {border-radius:8px;}', 'LineEdit {border-radius:8px;}')


class SpinBox(FluentSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(36)
        setCustomStyleSheet(self, 'SpinBox {border-radius:8px;}', 'SpinBox {border-radius:8px;}')


class Button(PushButton):
    def __init__(self, text='', parent=None):
        super().__init__(parent=parent)
        self.setText(text)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        setCustomStyleSheet(self, 'PushButton {border-radius:8px;padding:7px 14px;}', 'PushButton {border-radius:8px;padding:7px 14px;}')


class PrimaryButton(PrimaryPushButton):
    def __init__(self, text='', parent=None):
        super().__init__(parent=parent)
        self.setText(text)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        setCustomStyleSheet(self, 'PrimaryPushButton {border-radius:8px;padding:7px 14px;}', 'PrimaryPushButton {border-radius:8px;padding:7px 14px;}')


class ComboBox(FluentComboBox):
    """Bridge the project's QComboBox userData and sizing calls to Fluent."""
    AdjustToMinimumContentsLengthWithIcon = NativeComboBox.AdjustToMinimumContentsLengthWithIcon

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_data = []
        self.setMinimumHeight(36)
        setCustomStyleSheet(self, 'ComboBox {border-radius:8px;}', 'ComboBox {border-radius:8px;}')

    def addItem(self, text, userData=None):
        # Fluent's second positional argument is icon, unlike the project's usage.
        self._project_data.append(userData)
        super().addItem(text, userData=userData)

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)

    def clear(self):
        self._project_data.clear()
        super().clear()

    def currentData(self):
        index = self.currentIndex()
        return self._project_data[index] if 0 <= index < len(self._project_data) else None

    def findData(self, data):
        return next((i for i, value in enumerate(self._project_data) if value == data), -1)

    def setMinimumContentsLength(self, length):
        self.setMinimumWidth(self.fontMetrics().horizontalAdvance('宽' * length) + 40)

    def setSizeAdjustPolicy(self, policy):
        # Fluent lays out text inside a button rather than a native combo box.
        pass

    def _showComboMenu(self):
        super()._showComboMenu()
        if self.dropMenu is not None:
            # 全局列表样式可能给菜单项叠加垂直内边距，显式压回固定行高。
            self.dropMenu.view.setStyleSheet(
                'MenuActionListWidget::item { padding:0 10px; margin:1px 6px; border-radius:5px; border:none; }')

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Down, Qt.Key_Up):
            step = 1 if event.key() == Qt.Key_Down else -1
            index = self.currentIndex() + step
            while 0 <= index < self.count():
                if self.items[index].isEnabled:
                    self.setCurrentIndex(index)
                    break
                index += step
            event.accept()
            return
        super().keyPressEvent(event)
