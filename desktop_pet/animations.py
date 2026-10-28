"""Bounded local image-sequence import and configuration validation."""
import re
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImageReader, QPixmap

ACTION_LABELS = {'idle': '待机', 'hover': '移入', 'touch': '点击', 'reminder': '提醒'}


def natural_key(path):
    return [int(v) if v.isdigit() else v.lower() for v in re.split(r'(\d+)', Path(path).name)]


def import_sequence(paths, folder, fps):
    if not 2 <= len(paths) <= 24 or type(fps) is not int or not 5 <= fps <= 20:
        raise ValueError('请选择2～24帧图片，帧率为5～20帧/秒')
    paths = sorted((Path(p) for p in paths), key=natural_key)
    if sum(p.stat().st_size for p in paths) > 16 * 1024 * 1024:
        raise ValueError('一组动作图片合计不能超过16 MB')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    frames = []
    try:
        for index, path in enumerate(paths):
            reader = QImageReader(str(path))
            size = reader.size()
            if not reader.canRead() or size.width() <= 0 or size.height() <= 0 or size.width() * size.height() > 1000000:
                raise ValueError('每帧必须是可读取且不超过100万像素的图片')
            image = reader.read()
            if image.isNull():
                raise ValueError('有图片无法解码，动作未导入')
            image = image.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            target = folder / f'{index:03d}.png'
            if not image.save(str(target), 'PNG'):
                raise OSError('无法保存动作图片')
            frames.append(str(target))
        return {'frames': frames, 'fps': fps}
    except Exception:
        # Only files created in this new, dedicated import folder are removed.
        for target in folder.glob('*.png'):
            target.unlink(missing_ok=True)
        folder.rmdir()
        raise


def load_sequences(config, root):
    """Never load frame paths outside the managed assets or unbounded images."""
    result = {}
    if not isinstance(config, dict):
        return result
    for action in ACTION_LABELS:
        entry = config.get(action)
        if not isinstance(entry, dict) or type(entry.get('fps')) is not int or not 5 <= entry['fps'] <= 20:
            continue
        paths = entry.get('frames')
        if not isinstance(paths, list) or not 2 <= len(paths) <= 24:
            continue
        frames = []
        try:
            for path in paths:
                if not isinstance(path, str):
                    raise ValueError()
                target = Path(path).resolve()
                if not target.is_relative_to((Path(root) / 'animations').resolve()) or target.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError()
                reader = QImageReader(str(target))
                size = reader.size()
                if not (0 < size.width() <= 256 and 0 < size.height() <= 256):
                    raise ValueError()
                image = reader.read()
                if image.isNull():
                    raise ValueError()
                frames.append(QPixmap.fromImage(image).scaled(165, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except (ValueError, OSError, RuntimeError):
            continue
        result[action] = {'frames': frames, 'fps': entry['fps']}
    return result
