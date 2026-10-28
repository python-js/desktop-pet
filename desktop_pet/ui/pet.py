"""Local desktop pet interaction and screen placement."""
import time
from PyQt5.QtCore import Qt, QTimer, QSize, QRect
from PyQt5.QtGui import QColor, QFontMetrics, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QMenu
from ..animations import load_sequences
from ..motion import CANVAS_SIZE, SUBJECT_SIZE, SUBJECT_BOTTOM

# 气泡可用区域：窗口 220×260，宠物头顶在 y≈100，底边停在 84，最多 3 行。
BUBBLE_WIDTH = 210
BUBBLE_BOTTOM = 84
BUBBLE_TEXT_HEIGHT = 58  # 气泡最大高度 82 减去上下 padding 11×2 与边框 1×2
BUBBLE_PAD_WIDTH = 28  # 样式 padding 13×2 + 边框 1×2
BUBBLE_PAD_HEIGHT = 24  # 样式 padding 11×2 + 边框 1×2


def paint_default_pet(painter):
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#ddac80'))
    painter.drawEllipse(35, 75, 38, 45)
    painter.drawEllipse(117, 75, 38, 45)
    painter.setBrush(QColor('#f1d1aa'))
    painter.drawEllipse(35, 90, 120, 108)
    painter.setBrush(QColor('#443b39'))
    painter.drawEllipse(66, 128, 10, 13)
    painter.drawEllipse(114, 128, 10, 13)
    painter.drawEllipse(89, 148, 12, 9)
    painter.setBrush(QColor('#e8a49c'))
    painter.drawEllipse(49, 147, 19, 10)
    painter.drawEllipse(122, 147, 19, 10)


def default_pet_image():
    """Render the built-in pet to fill the canvas so motion and thumbnails keep its size."""
    image = QImage(256, 256, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    # paint_default_pet 的内容范围是 (35,75)-(155,198)，等比放大后水平居中。
    scale = 256 / 123
    painter.translate((256 - 120 * scale) / 2, 0)
    painter.scale(scale, scale)
    painter.translate(-35, -75)
    paint_default_pet(painter)
    painter.end()
    return image


class Pet(QWidget):
    def __init__(self, owner):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(220, 260)
        self.setToolTip('拖动移动 · 双击聊天 · 右键菜单')
        self.offset = None
        self.press_position = None
        self.dragged = False
        self.paused = owner.settings.get('pet_paused', False)
        self.pixmap = QPixmap()
        self.sequences = {}
        self.action = 'idle'
        self.frame_index = 0
        self.action_started = time.monotonic()
        self.phase = 0
        self.bubble = QLabel('双击我，开始聊天', self)
        self.bubble.setTextFormat(Qt.PlainText)
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignCenter)
        self.bubble.setStyleSheet('background:#ffffff;color:#4A4039;border:1px solid #F1E3D7;border-radius:18px;padding:11px 13px;font-size:13px;')
        from .theme import add_soft_shadow
        add_soft_shadow(self.bubble)
        self.bubble.ensurePolished()
        self.fit_bubble(self.bubble.text())
        self.bubble_timer = QTimer(self)
        self.bubble_timer.setSingleShot(True)
        self.bubble_timer.timeout.connect(self.bubble.hide)
        timer = QTimer(self)
        timer.timeout.connect(self.animate)
        if not self.paused:
            timer.start(40)
        self.timer = timer
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - 220, screen.bottom() - 240)
        position = owner.settings.get('pet_position')
        if isinstance(position, list) and len(position) == 2 and all(type(v) is int for v in position):
            self.move(*position)
        self.ensure_visible()

    def animate(self):
        self.phase = (time.monotonic() * 12.5) % 40
        self.advance_action()
        self.update()

    def load_animations(self):
        self.sequences = load_sequences(self.owner.settings.get('pet_animations'), self.owner.root)
        self.action = 'idle'
        self.frame_index = 0
        self.action_started = time.monotonic()
        self.update()

    def play_action(self, action):
        if self.paused or action not in self.sequences:
            return
        if self.action == 'reminder' and action == 'touch':
            return
        self.action = action
        self.frame_index = 0
        self.action_started = time.monotonic()
        self.update()

    def advance_action(self, now=None):
        sequence = self.sequences.get(self.action)
        if not sequence:
            return
        index = int(max(0, (time.monotonic() if now is None else now) - self.action_started) * sequence['fps'])
        if self.action != 'idle' and index >= len(sequence['frames']):
            self.action = 'idle'
            self.frame_index = 0
            self.action_started = time.monotonic() if now is None else now
        else:
            self.frame_index = index % len(sequence['frames'])

    def load_image(self, path):
        self.pixmap = QPixmap(path) if path else QPixmap()
        self.update()

    def fit_bubble(self, text):
        """气泡宽高随文字收缩，超过 3 行时用省略号截断。"""
        metrics = QFontMetrics(self.bubble.font())
        area = QRect(0, 0, BUBBLE_WIDTH - BUBBLE_PAD_WIDTH, 1000)
        bounds = metrics.boundingRect(area, Qt.TextWordWrap, text)
        width = min(BUBBLE_WIDTH, bounds.width() + BUBBLE_PAD_WIDTH + 2)
        inner = QRect(0, 0, width - BUBBLE_PAD_WIDTH, 1000)
        bounds = metrics.boundingRect(inner, Qt.TextWordWrap, text)
        while bounds.height() > BUBBLE_TEXT_HEIGHT and len(text) > 1:
            text = text[:-2] + '…'
            bounds = metrics.boundingRect(inner, Qt.TextWordWrap, text)
        self.bubble.setText(text)
        height = bounds.height() + BUBBLE_PAD_HEIGHT
        self.bubble.setFixedSize(width, height)
        self.bubble.move((self.width() - width) // 2, BUBBLE_BOTTOM - height)

    def say(self, text):
        self.fit_bubble(text)
        self.bubble.setToolTip(text)
        self.bubble.show()
        self.bubble_timer.start(12000)

    def static_size(self):
        if self.pixmap.isNull():
            # paint_default_pet 的内容范围，无上传图时作为尺寸基准。
            return QSize(120, 123)
        return self.pixmap.size().scaled(165, 140, Qt.KeepAspectRatio)

    def paintEvent(self, event):
        import math
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(15, 35)
        painter.translate(0, int(math.sin(self.phase * math.pi / 20) * 4))
        sequence = self.sequences.get(self.action)
        frame = sequence['frames'][self.frame_index] if sequence else self.pixmap
        if not frame.isNull():
            if sequence:
                # 动作帧含跳跃留白，按内容占比放大绘制框，使待机尺寸与静态图一致。
                size = self.static_size()
                side = round(max(size.width(), size.height()) * CANVAS_SIZE / SUBJECT_SIZE)
                image = frame.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                bottom = 65 + (140 + size.height()) / 2
                top = round(bottom - image.height() * SUBJECT_BOTTOM / CANVAS_SIZE)
            else:
                image = frame.scaled(165, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                top = 65 + (140 - image.height()) // 2
            painter.drawPixmap((190 - image.width()) // 2, top, image)
        else:
            paint_default_pet(painter)

    def enterEvent(self, event):
        if not self.paused and not self.dragged and self.action == 'idle':
            self.play_action('hover')
        super().enterEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.offset = event.globalPos() - self.pos()
            self.press_position = event.globalPos()
            self.dragged = False

    def mouseMoveEvent(self, event):
        if self.offset is not None and event.buttons() & Qt.LeftButton:
            if (event.globalPos() - self.press_position).manhattanLength() >= QApplication.startDragDistance():
                self.dragged = True
            if self.dragged:
                self.move(event.globalPos() - self.offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.offset is not None:
            if self.dragged:
                self.ensure_visible()
                self.save_preferences()
            else:
                self.play_action('touch')
                self.say('摸摸收到！双击我可以聊天，也可以一起整理待办。')
        self.offset = None

    def ensure_visible(self, *args):
        screens = QApplication.screens()
        if not screens:
            return
        area = self.frameGeometry()
        screen = max(screens, key=lambda s: (s.availableGeometry().intersected(area).width()
                                             * s.availableGeometry().intersected(area).height()))
        if not any(s.availableGeometry().intersects(area) for s in screens):
            screen = QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        self.move(max(bounds.left(), min(self.x(), bounds.right() - self.width() + 1)),
                  max(bounds.top(), min(self.y(), bounds.bottom() - self.height() + 1)))

    def save_preferences(self):
        self.owner.settings['pet_position'] = [self.x(), self.y()]
        self.owner.settings['pet_paused'] = self.paused
        try:
            self.owner.persist_settings()
        except OSError:
            self.owner.statusBar().showMessage('宠物设置暂时无法保存，本次运行仍然有效。', 6000)

    def toggle_animation(self):
        self.paused = not self.paused
        if self.paused:
            self.timer.stop()
        else:
            self.action_started = time.monotonic() - self.frame_index / self.sequences.get(self.action, {'fps': 10})['fps']
            self.timer.start(40)
        self.save_preferences()

    def reset_position(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - 220, screen.bottom() - 240)
        self.ensure_visible()
        self.show()
        self.save_preferences()


    def mouseDoubleClickEvent(self, event):
        self.owner.show_main()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('打开聊天与待办', self.owner.show_main)
        menu.addAction('更换宠物图片', self.owner.choose_image)
        menu.addAction('恢复动画' if self.paused else '暂停动画', self.toggle_animation)
        menu.addAction('重置宠物位置', self.reset_position)
        menu.addAction('退出', self.owner.quit_app)
        menu.exec_(event.globalPos())


