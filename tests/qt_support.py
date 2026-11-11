"""Shared offscreen QApplication for tests.

QtWebEngine cannot tear down cleanly under the offscreen platform, so the shell
mounts a lightweight placeholder instead of a real QWebEngineView. The real view
is exercised by tools/webshell_*_check.py on a desktop session.
"""
import os
import sys
import types

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget

QT_APP = QApplication.instance() or QApplication([])


class HeadlessWebShell(QWidget):
    def __init__(self, bridge_host, parent=None):
        super().__init__(parent)
        self.bridge = bridge_host
        self.view = None

    def reload(self):
        return None

    def ensure_alive(self, hidden_seconds=0.0):
        return None


def install_headless_shell():
    if 'desktop_pet.ui.webshell' in sys.modules:
        return
    import desktop_pet.ui
    module = types.ModuleType('desktop_pet.ui.webshell')
    module.WebShell = HeadlessWebShell
    module.web_dist = lambda: None
    sys.modules['desktop_pet.ui.webshell'] = module
    desktop_pet.ui.webshell = module


install_headless_shell()

from desktop_pet.ui.theme import apply_theme

apply_theme(QT_APP)
