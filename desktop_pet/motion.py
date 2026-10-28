"""Generate basic whole-image motion locally; no semantic or skeletal synthesis."""
import math
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPainter
from .animations import ACTION_LABELS

# Hover is a single short hop; static actions keep 16 frames at 10 fps.
HOVER_FRAMES = 12
HOVER_FPS = 12
# 帧画布与源图内容边长；显示端按两者比例补偿透明留白，避免动作开启后宠物变小。
CANVAS_SIZE = 256
SUBJECT_SIZE = 172
SUBJECT_BOTTOM = 218


def generate_motion(image, strength=40):
    if image.isNull() or type(strength) is not int or not 0 <= strength <= 100:
        raise ValueError('请选择有效图片，动作幅度须在0～100之间')
    source = image.scaled(SUBJECT_SIZE, SUBJECT_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    amount = strength / 100
    result = {}
    for action in ACTION_LABELS:
        count = HOVER_FRAMES if action == 'hover' else 16
        frames = []
        for index in range(count):
            # Both ends of event motion rest at the original pose.
            phase = index / (count if action == 'idle' else count - 1)
            wave = math.sin(phase * math.tau)
            stretch, jump, angle = 1.0, 0.0, 0.0
            if action == 'idle':
                stretch = 1 + wave * 0.035 * amount
            elif action == 'hover':
                jump = math.sin(phase * math.pi) * 10 * amount
                stretch = 1 - math.sin(phase * math.tau) * 0.04 * amount
            elif action == 'touch':
                jump = math.sin(phase * math.pi) * 24 * amount
                stretch = 1 - math.sin(phase * math.tau) * 0.1 * amount
            else:
                angle = wave * 12 * amount
            frame = QImage(CANVAS_SIZE, CANVAS_SIZE, QImage.Format_ARGB32_Premultiplied)
            frame.fill(Qt.transparent)
            painter = QPainter(frame)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.translate(CANVAS_SIZE / 2, SUBJECT_BOTTOM - jump)
            painter.rotate(angle)
            painter.scale(1 / stretch, stretch)
            painter.drawImage(-source.width() // 2, -source.height(), source)
            painter.end()
            frames.append(frame)
        result[action] = frames
    return result


def cleanup_generated(folder):
    """Nonrecursive cleanup of only PNGs in a dedicated generated asset folder."""
    folder = Path(folder)
    if not folder.is_dir():
        return
    for path in folder.glob('*.png'):
        try:
            path.unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass


def save_motion(frames, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    result = {}
    try:
        for action in ACTION_LABELS:
            paths = []
            for index, image in enumerate(frames[action]):
                target = folder / f'{action}-{index:03d}.png'
                if image.isNull() or not image.save(str(target), 'PNG'):
                    raise OSError('动作保存失败')
                paths.append(str(target))
            result[action] = {'frames': paths, 'fps': HOVER_FPS if action == 'hover' else 10}
        return result
    except Exception:
        cleanup_generated(folder)
        raise
