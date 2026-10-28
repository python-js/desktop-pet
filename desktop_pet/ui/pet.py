"""Local desktop pet interaction and screen placement."""
import random
import time
from PyQt5.QtCore import QEvent, Qt, QTimer, QSize, QRect
from PyQt5.QtGui import QColor, QCursor, QFontMetrics, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QMenu
from ..animations import load_sequences
from ..motion import CANVAS_SIZE, SUBJECT_SIZE, SUBJECT_BOTTOM

# 气泡可用区域：窗口 220×260，宠物头顶在 y≈100，底边停在 84，最多 3 行。
BUBBLE_WIDTH = 210
BUBBLE_BOTTOM = 84
BUBBLE_TEXT_HEIGHT = 58  # 气泡最大高度 82 减去上下 padding 11×2 与边框 1×2
BUBBLE_PAD_WIDTH = 28  # 样式 padding 13×2 + 边框 1×2
BUBBLE_PAD_HEIGHT = 24  # 样式 padding 11×2 + 边框 1×2

WINDOW_2D = QSize(220, 260)
# 3D 模式在顶部预留气泡区，3D 画布从 y=88 开始，互不遮挡。
WINDOW_3D = QSize(220, 340)
VIEW3D_TOP = 88

# 偶尔巡逻：静止一段时间后沿当前屏幕水平走几步，到边缘掉头。
WALK_SPEED = 45
WALK_MIN_MS = 3000
WALK_MAX_MS = 6000
WALK_IDLE_MIN_MS = 20000
WALK_IDLE_MAX_MS = 40000


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
        self.setFixedSize(WINDOW_2D)
        self.setToolTip('拖动移动 · 双击聊天 · 右键菜单')
        self.offset = None
        self.press_position = None
        self.dragged = False
        self.mode = '2d'
        self.view3d = None
        self.view3d_failed = False
        self.gaze = (0.0, 0.0)
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
        # 3D 视线跟随：轮询全局鼠标，只在方向变化时通知页面。
        self.gaze_timer = QTimer(self)
        self.gaze_timer.setInterval(80)
        self.gaze_timer.timeout.connect(self.update_gaze_3d)
        self.walking_enabled = owner.settings.get('pet_walking', True)
        self.walking = False
        self.walk_direction = 1
        self.walk_until = 0.0
        self.walk_last = 0.0
        self.walk_timer = QTimer(self)
        self.walk_timer.setInterval(40)
        self.walk_timer.timeout.connect(self.walk_tick)
        self.walk_idle_timer = QTimer(self)
        self.walk_idle_timer.setSingleShot(True)
        self.walk_idle_timer.timeout.connect(self.start_walk)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - 220, screen.bottom() - 240)
        position = owner.settings.get('pet_position')
        if isinstance(position, list) and len(position) == 2 and all(type(v) is int for v in position):
            self.move(*position)
        self.ensure_visible()
        if owner.settings.get('pet_mode', '3d') == '3d':
            self.enable_3d(persist=False)

    def animate(self):
        if self.mode == '3d':
            return
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
        if self.paused or self.mode == '3d' or action not in self.sequences:
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

    def enable_3d(self, persist=True):
        """Show the local three.js scene; return False when WebEngine is unavailable."""
        if self.mode == '3d':
            return True
        if QApplication.platformName() == 'offscreen':
            return False
        if self.view3d is None and not self.view3d_failed:
            try:
                from .pet3d import create_view
                self.view3d = create_view(self, self)
                self.view3d.installEventFilter(self)
                self.view3d.loadFinished.connect(self.apply_3d_pause)
            except Exception:
                self.view3d_failed = True
        if self.view3d is None:
            return False
        delta = WINDOW_3D.height() - WINDOW_2D.height()
        self.move(self.x(), self.y() - delta)
        self.setFixedSize(WINDOW_3D)
        self.view3d.setGeometry(0, VIEW3D_TOP, WINDOW_3D.width(), WINDOW_3D.height() - VIEW3D_TOP)
        self.view3d.show()
        self.mode = '3d'
        self.timer.stop()
        self.apply_3d_pause()
        self.schedule_walk()
        self.update()
        self.ensure_visible()
        if persist:
            self.save_preferences()
        return True

    def apply_3d_pause(self, *args):
        if self.view3d is not None:
            flag = 'true' if self.paused else 'false'
            self.view3d.page().runJavaScript(f'window.pet3d && window.pet3d.setPaused({flag})')
            if self.paused or self.mode != '3d':
                self.gaze_timer.stop()
            else:
                self.gaze_timer.start()

    def update_gaze_3d(self):
        if self.view3d is None or self.mode != '3d':
            return
        cursor = QCursor.pos()
        center = self.view3d.mapToGlobal(self.view3d.rect().center())
        x = max(-1.0, min(1.0, (cursor.x() - center.x()) / max(1, self.view3d.width() / 2)))
        y = max(-1.0, min(1.0, (center.y() - cursor.y()) / max(1, self.view3d.height() / 2)))
        if abs(x - self.gaze[0]) < 0.02 and abs(y - self.gaze[1]) < 0.02:
            return
        self.gaze = (x, y)
        self.view3d.page().runJavaScript(f'window.pet3d && window.pet3d.lookAt({x:.2f}, {y:.2f})')

    def react_3d(self):
        if self.view3d is not None and not self.paused:
            self.view3d.page().runJavaScript('window.pet3d && window.pet3d.react()')

    def set_3d_dragging(self, value):
        if self.mode == '3d' and self.view3d is not None:
            flag = 'true' if value else 'false'
            self.view3d.page().runJavaScript(f'window.pet3d && window.pet3d.setDragging({flag})')

    def walk_bounds(self):
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        return screen.availableGeometry()

    def schedule_walk(self, delay=None):
        if not self.walking_enabled or self.paused or self.mode != '3d' or self.walking:
            return
        self.walk_idle_timer.start(delay or random.randint(WALK_IDLE_MIN_MS, WALK_IDLE_MAX_MS))

    def start_walk(self):
        if not self.walking_enabled or self.paused or self.mode != '3d' or self.walking:
            return
        if self.offset is not None or self.underMouse() or self.bubble.underMouse():
            self.schedule_walk(5000)
            return
        bounds = self.walk_bounds()
        if self.x() <= bounds.left() + 2:
            self.walk_direction = 1
        elif self.x() + self.width() >= bounds.right():
            self.walk_direction = -1
        self.walking = True
        self.walk_last = time.monotonic()
        self.walk_until = self.walk_last + random.randint(WALK_MIN_MS, WALK_MAX_MS) / 1000
        self.walk_timer.start()
        self.set_3d_walking(True, self.walk_direction)

    def walk_tick(self):
        now = time.monotonic()
        delta = min(now - self.walk_last, 0.1)
        self.walk_last = now
        if now >= self.walk_until:
            self.stop_walking()
            return
        bounds = self.walk_bounds()
        x = self.x() + WALK_SPEED * delta * self.walk_direction
        if x <= bounds.left():
            x = bounds.left()
            self.walk_direction = 1
            self.set_3d_walking(True, 1)
        elif x + self.width() >= bounds.right() + 1:
            x = bounds.right() - self.width() + 1
            self.walk_direction = -1
            self.set_3d_walking(True, -1)
        self.move(round(x), self.y())

    def stop_walking(self, save=True):
        was_walking = self.walking
        self.walking = False
        self.walk_timer.stop()
        if was_walking:
            self.set_3d_walking(False, 0)
            if save:
                self.save_preferences()
        self.schedule_walk()

    def set_3d_walking(self, value, direction):
        if self.mode == '3d' and self.view3d is not None:
            flag = 'true' if value else 'false'
            self.view3d.page().runJavaScript(f'window.pet3d && window.pet3d.setWalking({flag}, {direction})')

    def toggle_walking(self):
        self.walking_enabled = not self.walking_enabled
        self.walk_idle_timer.stop()
        if not self.walking_enabled:
            self.stop_walking(save=False)
        else:
            self.schedule_walk(1500)
        self.save_preferences()

    def disable_3d(self, persist=True):
        if self.mode != '3d':
            return
        self.walk_idle_timer.stop()
        if self.walking:
            self.walking = False
            self.walk_timer.stop()
            self.set_3d_walking(False, 0)
        delta = WINDOW_3D.height() - WINDOW_2D.height()
        self.gaze_timer.stop()
        self.gaze = (0.0, 0.0)
        if self.view3d is not None:
            self.view3d.page().runJavaScript('window.pet3d && window.pet3d.setDragging(false)')
            self.view3d.page().runJavaScript('window.pet3d && window.pet3d.setPaused(true)')
        self.view3d.hide()
        self.setFixedSize(WINDOW_2D)
        self.move(self.x(), self.y() + delta)
        self.mode = '2d'
        if not self.paused:
            self.timer.start(40)
        self.update()
        self.ensure_visible()
        if persist:
            self.save_preferences()

    def toggle_3d(self, checked=False):
        if self.mode == '3d':
            self.disable_3d()
            self.owner.statusBar().showMessage('已切回 2D 形象。', 5000)
        elif self.enable_3d():
            self.owner.statusBar().showMessage('已切换到 3D 形象：拖动、双击和右键菜单仍然可用。', 6000)
        else:
            self.owner.statusBar().showMessage('当前环境无法启用 3D 视图，请确认已安装 PyQtWebEngine。', 8000)

    def eventFilter(self, watched, event):
        # WebEngine 会吞掉鼠标事件，这里转发拖动、双击和右键菜单。
        if watched is self.view3d or (self.view3d is not None and self.view3d.isAncestorOf(watched)):
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self.press(event.globalPos())
                return True
            if event.type() == QEvent.MouseMove:
                self.drag(event.globalPos(), event.buttons())
                return True
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self.release(event.globalPos())
                return True
            if event.type() == QEvent.MouseButtonDblClick:
                self.owner.show_main()
                return True
            if event.type() == QEvent.ContextMenu:
                self.show_menu(event.globalPos())
                return True
        return super().eventFilter(watched, event)

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
        if self.mode == '3d':
            return
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
        if self.walking:
            self.stop_walking(save=False)
        if not self.paused and not self.dragged and self.action == 'idle':
            self.play_action('hover')
        super().enterEvent(event)

    def press(self, pos):
        self.stop_walking(save=False)
        self.offset = pos - self.pos()
        self.press_position = pos
        self.dragged = False

    def drag(self, pos, buttons):
        if self.offset is not None and buttons & Qt.LeftButton:
            if not self.dragged and (pos - self.press_position).manhattanLength() >= QApplication.startDragDistance():
                self.dragged = True
                self.set_3d_dragging(True)
            if self.dragged:
                self.move(pos - self.offset)

    def release(self, pos):
        if self.offset is None:
            return
        if self.dragged:
            self.set_3d_dragging(False)
            self.ensure_visible()
            self.save_preferences()
        else:
            if self.mode == '3d':
                self.react_3d()
            else:
                self.play_action('touch')
            self.say('摸摸收到！双击我可以聊天，也可以一起整理待办。')
        self.offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.press(event.globalPos())

    def mouseMoveEvent(self, event):
        self.drag(event.globalPos(), event.buttons())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.release(event.globalPos())

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
        self.owner.settings['pet_mode'] = self.mode
        self.owner.settings['pet_walking'] = self.walking_enabled
        try:
            self.owner.persist_settings()
        except OSError:
            self.owner.statusBar().showMessage('宠物设置暂时无法保存，本次运行仍然有效。', 6000)

    def toggle_animation(self):
        self.paused = not self.paused
        if self.paused:
            self.stop_walking(save=False)
        if self.mode == '3d':
            self.apply_3d_pause()
            self.schedule_walk()
        elif self.paused:
            self.timer.stop()
        else:
            self.action_started = time.monotonic() - self.frame_index / self.sequences.get(self.action, {'fps': 10})['fps']
            self.timer.start(40)
        self.save_preferences()

    def reset_position(self):
        self.stop_walking(save=False)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - 220, screen.bottom() - 240)
        self.ensure_visible()
        self.show()
        self.save_preferences()


    def mouseDoubleClickEvent(self, event):
        self.owner.show_main()

    def show_menu(self, pos):
        self.stop_walking(save=False)
        menu = QMenu(self)
        menu.addAction('打开聊天与待办', self.owner.show_main)
        menu.addAction('更换宠物图片', self.owner.choose_image)
        menu.addAction('切回 2D 形象' if self.mode == '3d' else '切换到 3D 形象', self.toggle_3d)
        menu.addAction('恢复动画' if self.paused else '暂停动画', self.toggle_animation)
        if self.mode == '3d':
            menu.addAction('恢复走动' if not self.walking_enabled else '暂停走动', self.toggle_walking)
        menu.addAction('重置宠物位置', self.reset_position)
        menu.addAction('退出', self.owner.quit_app)
        menu.exec_(pos)
        self.schedule_walk(5000)

    def contextMenuEvent(self, event):
        self.show_menu(event.globalPos())


