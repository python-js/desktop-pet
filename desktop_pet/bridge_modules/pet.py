"""pet.*: pet appearance gallery plus the shell-side native image flow.

File validation, copying and background removal stay in the Qt shell; the page only
receives small base64 thumbnails for preview and calls back to trigger native dialogs.
"""
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage

from ..bridge import BridgeError
from ..ui.pet import default_pet_image

THUMB = 96
PREVIEW = 240


def _data_url(image, size):
    if image.isNull():
        return ''
    scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    scaled.save(buffer, 'PNG')
    buffer.close()
    return 'data:image/png;base64,' + bytes(data.toBase64()).decode('ascii')


def _thumb(path):
    return _data_url(QImage(path), THUMB) if path else ''


def _records(window):
    records = window.settings.get('pet_images')
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _gallery(window):
    active = str(window.settings.get('pet_image') or '')
    items = []
    for record in _records(window):
        image = str(record.get('image') or '')
        if not image:
            continue
        items.append({
            'image': image,
            'original': str(record.get('original') or ''),
            'thumb': _thumb(image),
            'active': image == active,
        })
    current = next((item for item in items if item['active']), None)
    return {
        'active': active,
        'items': items,
        'defaultThumb': _data_url(default_pet_image(), THUMB),
        'preview': _data_url(QImage(active), PREVIEW) if active else '',
        'hasOriginal': bool(current and current['original']),
        'position': list(window.settings.get('pet_position') or []),
    }


def _emit_changed(host, window, before):
    active = str(window.settings.get('pet_image') or '')
    host.emit_event('pet.changed', {'active': active, 'changed': active != before})


def handle(action, args, host):
    window = host.context['window']
    if action == 'gallery':
        return _gallery(window)
    if action == 'select':
        image = str(args.get('image') or '')
        known = {str(record.get('image') or '') for record in _records(window)}
        if image and image not in known:
            raise BridgeError('图片不在宠物形象历史中', code='NOT_FOUND')
        active = str(window.settings.get('pet_image') or '')
        if image == active:
            return {'applied': True}
        notice = '已切换宠物图片。' if image else '已切换到默认形象。'
        applied = bool(window.apply_pet_image(image or None, None, notice))
        if applied:
            host.emit_event('pet.changed', {'active': image, 'changed': True})
        return {'applied': applied}
    before = str(window.settings.get('pet_image') or '')
    if action == 'chooseImage':
        window.choose_image()
    elif action == 'removeImage':
        window.remove_pet_image()
    elif action == 'removeBackground':
        window.remove_image_background()
    elif action == 'restoreOriginal':
        window.restore_original_image()
    elif action == 'resetPosition':
        window.reset_pet_position()
        return {}
    else:
        raise BridgeError(f'未知方法: pet.{action}', code='NOT_FOUND')
    _emit_changed(host, window, before)
    return {'changed': str(window.settings.get('pet_image') or '') != before}
