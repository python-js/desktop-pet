"""Preview a local color cutout without changing the active pet until accepted."""
from PyQt5.QtCore import QRectF, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QSlider, QColorDialog)
from ..cutout import corner_color, remove_background, CutoutCancelled
from .common import button, dialog_heading
from .theme import mono_font, tokens


class ImagePreview(QWidget):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.image = image
        self.setMinimumSize(180, 200)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor(t.surface))
        dark = QColor(t.surface_2)
        for y in range(0, self.height(), 16):
            for x in range(0, self.width(), 16):
                if (x // 16 + y // 16) % 2:
                    painter.fillRect(x, y, 16, 16, dark)
        if not self.image.isNull():
            image = self.image.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawImage((self.width() - image.width()) // 2, (self.height() - image.height()) // 2, image)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(t.border), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 12, 12)


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
        layout.setSpacing(12)
        dialog_heading(layout, '图像处理 · CUTOUT', '纯色背景移除',
                       '适合纯色底图，仅移除与图片边缘连通的近似背景色；主体与背景同色时可能误删。'
                       '处理结果最长边为 1024 像素，原图保留。')
        images = QHBoxLayout()
        images.setSpacing(12)
        for title, image_value in [('原图', self.image), ('处理预览（棋盘表示透明）', self.image)]:
            column = QVBoxLayout()
            column.setSpacing(6)
            caption = QLabel(title)
            caption.setObjectName('fieldLabel')
            column.addWidget(caption)
            preview = ImagePreview(image_value)
            column.addWidget(preview, 1)
            images.addLayout(column)
        self.preview = preview
        layout.addLayout(images, 1)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.color_button = button('选择背景颜色', self.choose_color, controls)
        self.tolerance_label = QLabel('容差：30')
        self.tolerance_label.setObjectName('dialogHintText')
        self.tolerance_label.setFont(mono_font(11))
        controls.addWidget(self.tolerance_label)
        self.tolerance = QSlider(Qt.Horizontal)
        self.tolerance.setRange(0, 120)
        self.tolerance.setValue(30)
        self.tolerance.valueChanged.connect(self.invalidate)
        controls.addWidget(self.tolerance, 1)
        layout.addLayout(controls)
        self.status = QLabel('调整颜色或容差后，点击“预览去背景”。')
        self.status.setObjectName('dialogHintText')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        button('取消', self.reject, row)
        self.preview_button = button('预览去背景', self.process, row)
        self.apply_button = button('应用到宠物', self.accept, row, primary=True)
        self.apply_button.setEnabled(False)
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
