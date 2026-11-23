"""system.*: shell-only capabilities (native file pickers, opening data dir, startup toggle)."""
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from ..bridge import BridgeError, handle_system as base_system

IMAGE_FILTER = '图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*.*)'


def handle(action, args, host):
    window = host.context['window']
    if action == 'pickFile':
        path, _ = QFileDialog.getOpenFileName(
            None, str(args.get('title') or '选择文件'), str(Path.home()),
            str(args.get('filter') or '所有文件 (*.*)'))
        return {'path': path or None}
    if action == 'pickFiles':
        paths, _ = QFileDialog.getOpenFileNames(
            None, str(args.get('title') or '选择文件'), str(Path.home()),
            str(args.get('filter') or '所有文件 (*.*)'))
        return {'paths': list(paths)}
    if action == 'pickImage':
        path, _ = QFileDialog.getOpenFileName(None, '选择宠物形象图片', str(Path.home()), IMAGE_FILTER)
        return {'path': path or None}
    if action == 'pickFolder':
        path = QFileDialog.getExistingDirectory(None, str(args.get('title') or '选择文件夹'), str(Path.home()))
        return {'path': path or None}
    if action == 'pickSavePath':
        name = str(args.get('name') or '')
        path, _ = QFileDialog.getSaveFileName(
            None, str(args.get('title') or '保存文件'),
            str(Path.home() / name) if name else str(Path.home()),
            str(args.get('filter') or '所有文件 (*.*)'))
        extension = str(args.get('extension') or '').strip().lower()
        if path and extension and not path.lower().endswith(extension):
            path += extension
        return {'path': path or None}
    if action == 'writeTextFile':
        text = args.get('text')
        if not isinstance(text, str) or len(text) > 5_000_000:
            raise BridgeError('导出内容无效')
        name = str(args.get('name') or '导出文件')[:200]
        path, _ = QFileDialog.getSaveFileName(
            None, str(args.get('title') or '导出文件'), str(Path.home() / name),
            str(args.get('filter') or '所有文件 (*.*)'))
        extension = str(args.get('extension') or '').strip().lower()
        if path and extension and not path.lower().endswith(extension):
            path += extension
        if not path:
            return {'file': None, 'cancelled': True}
        try:
            Path(path).write_text(text, encoding='utf-8')
        except OSError:
            raise BridgeError('无法写入导出文件，请选择可写入的位置') from None
        return {'file': path.name}
    if action == 'openPath':
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(window.root)))
        return {}
    return base_system(action, args, host)


def handle_startup(action, args, host):
    window = host.context['window']
    if action == 'get':
        try:
            return {'enabled': window.startup_manager.enabled()}
        except (ValueError, OSError):
            return {'enabled': False}
    if action == 'set':
        enabled = args.get('enabled')
        if not isinstance(enabled, bool):
            raise BridgeError('enabled 必须是布尔值')
        window.startup_manager.set_enabled(enabled)
        return {}
    raise BridgeError(f'未知方法: startup.{action}', code='NOT_FOUND')
