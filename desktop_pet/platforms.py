"""Platform-specific behavior stays behind this small boundary."""
import os
import sys
from pathlib import Path


def data_directory():
    override = os.environ.get('DESKTOP_PET_DATA_DIR')
    if override:
        path = Path(override)
    elif sys.platform == 'win32':
        path = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'DesktopPet'
    elif sys.platform == 'darwin':
        path = Path.home() / 'Library/Application Support/DesktopPet'
    else:
        path = Path.home() / '.local/share/desktop-pet'
    path.mkdir(parents=True, exist_ok=True)
    return path


def notify(tray, title, message):
    if tray and tray.isVisible() and tray.supportsMessages():
        tray.showMessage(title, message, tray.Information, 10000)
