"""Preview a local color cutout without changing the active pet until accepted."""
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QColor, QPainter
from PyQt5.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QSlider, QColorDialog)
from ..cutout import corner_color, remove_background, CutoutCancelled
from .common import button


class ImagePreview(QWidget):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.image = image
        self.setMinimumSize(180, 200)

    def paintEvent(self, event):
        painter = QPainter(self)
        for y in range(0, self.height(), 16):
            for x in range(0, self.width(), 16):
                painter.fillRect(x, y, 16, 16, QColor('#dddddd' if (x // 16 + y // 16) % 2 else '#ffffff'))
        if not self.image.isNull():
            image = self.image.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawImage((self.width() - image.width()) // 2, (self.height() - image.height()) // 2, image)


class CutoutWorker(QThread):
    ready = pyqtSignal(bytes)
    failed = pyqtSignal(str)

    def __init__(self, image, pixels, color, tolerance, parent):
        super().__init__(parent)
        self.image, self.pixels, self.color, self.tolerance = image, pixels, color, tolerance

    def run(self):
        try:
            result = remove_background(self.image.width(), self.image.height(), self.pixels,
                                       self.color, self.tolerance, self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.ready.emit(result)
        except CutoutCancelled:
            pass
        except Exception:
            self.failed.emit('处理失败，请尝试其他图片或降低尺寸。')


class CutoutDialog(QDialog):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setWindowTitle('纯色背景移除 · 本地预览')
        self.resize(700, 510)
        self.image = image.scaled(1024, 1024, Qt.KeepAspectRatio, Qt.SmoothTransformation) if max(image.width(), image.height()) > 1024 else image
        self.image = self.image.convertToFormat(QImage.Format_RGBA8888)
        bits = self.image.constBits()
        bits.setsize(self.image.byteCount())
        self.pixels = bytes(bits)
        self.color = corner_color(self.image.width(), self.image.height(), self.pixels)
        self.result_image = QImage()
        self.worker = None
        self.close_pending = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        note = QLabel('适合纯色底图，仅移除与图片边缘连通的近似背景色。\n主体与背景同色时可能误删；复杂照片请使用专用抠图工具。处理结果最长边为1024像素，原图保留。')
        note.setWordWrap(True)
        layout.addWidget(note)
        images = QHBoxLayout()
        for title, image_value in [('原图', self.image), ('处理预览（棋盘表示透明）', self.image)]:
            column = QVBoxLayout()
            column.addWidget(QLabel(title))
            preview = ImagePreview(image_value)
            column.addWidget(preview, 1)
            images.addLayout(column)
        self.preview = preview
        layout.addLayout(images, 1)
        controls = QHBoxLayout()
        self.color_button = button('选择背景颜色', self.choose_color, controls)
        self.tolerance_label = QLabel('容差：30')
        controls.addWidget(self.tolerance_label)
        self.tolerance = QSlider(Qt.Horizontal)
        self.tolerance.setRange(0, 120)
        self.tolerance.setValue(30)
        self.tolerance.valueChanged.connect(self.invalidate)
        controls.addWidget(self.tolerance, 1)
        layout.addLayout(controls)
        self.status = QLabel('调整颜色或容差后，点击“预览去背景”。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.preview_button = button('预览去背景', self.process, row)
        self.apply_button = button('应用到宠物', self.accept, row, primary=True)
        self.apply_button.setEnabled(False)
        button('取消', self.reject, row)
        layout.addLayout(row)
        self.update_color()

    def update_color(self):
        self.color_button.setText('背景颜色 ' + QColor(*self.color).name())

    def choose_color(self):
        color = QColorDialog.getColor(QColor(*self.color), self, '选择要移除的背景颜色')
        if color.isValid():
            self.color = color.red(), color.green(), color.blue()
            self.update_color()
            self.invalidate()

    def invalidate(self):
        self.result_image = QImage()
        self.apply_button.setEnabled(False)
        self.tolerance_label.setText(f'容差：{self.tolerance.value()}')
        self.preview.image = self.image
        self.preview.update()
        self.status.setText('参数已调整，请重新预览。')

    def process(self):
        if self.worker is not None:
            return
        self.invalidate()
        self.worker = CutoutWorker(self.image, self.pixels, self.color, self.tolerance.value(), self)
        self.color_button.setEnabled(False)
        self.tolerance.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.status.setText('正在本地处理，可以取消…')
        self.worker.ready.connect(self.on_ready)
        self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self.finished_processing)
        self.worker.start()

    def on_ready(self, pixels):
        if self.close_pending:
            return
        result = QImage(pixels, self.image.width(), self.image.height(), self.image.width() * 4, QImage.Format_RGBA8888).copy()
        if not any(pixels[3::4]):
            self.status.setText('结果完全透明，不能应用；请降低容差或更换背景颜色。')
            return
        self.result_image = result
        self.preview.image = result
        self.preview.update()
        self.status.setText('预览完成；请检查主体是否被误删，再应用。')

    def finished_processing(self):
        self.worker.deleteLater()
        self.worker = None
        self.color_button.setEnabled(True)
        self.tolerance.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.apply_button.setEnabled(not self.result_image.isNull())
        if self.close_pending:
            super().reject()

    def accept(self):
        if self.worker is None and not self.result_image.isNull():
            super().accept()

    def reject(self):
        if self.worker is not None:
            self.close_pending = True
            self.worker.requestInterruption()
            self.status.setText('正在取消处理…')
        else:
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
