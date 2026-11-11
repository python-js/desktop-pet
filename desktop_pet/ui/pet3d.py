"""Local three.js pet canvas; WebEngine stays optional and is imported on first use."""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtWidgets import QWidget


def scene_path():
    # 页面随 web 工程构建，打包后在 _internal/web/pet3d；源码运行时直接用 web/public 下的原件。
    override = os.environ.get('DESKTOP_PET_WEB_DIST')
    if override:
        return Path(override) / 'pet3d' / 'index.html'
    frozen = getattr(sys, '_MEIPASS', None)
    if frozen:
        return Path(frozen) / 'web' / 'pet3d' / 'index.html'
    return Path(__file__).resolve().parents[2] / 'web' / 'public' / 'pet3d' / 'index.html'


SCENE = scene_path()


def create_view(parent=None, event_filter=None):
    from PySide6.QtWebEngineWidgets import QWebEngineView

    class Pet3DView(QWebEngineView):
        def __init__(self):
            super().__init__(parent)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setStyleSheet('background: transparent; border: none;')
            self.setContextMenuPolicy(Qt.NoContextMenu)
            self.page().setBackgroundColor(Qt.transparent)
            self.setUrl(QUrl.fromLocalFile(str(SCENE)))
            self._attach_filter()

        def _attach_filter(self):
            # WebEngine 的内部渲染控件直接接收鼠标，必须逐个安装过滤器。
            if event_filter is None:
                return
            for widget in [self, self.focusProxy()] + self.findChildren(QWidget):
                if widget is not None:
                    widget.installEventFilter(event_filter)

        def childEvent(self, event):
            super().childEvent(event)
            if event.type() == QEvent.ChildAdded and event_filter is not None:
                child = event.child()
                if isinstance(child, QWidget):
                    child.installEventFilter(event_filter)
                    for widget in child.findChildren(QWidget):
                        widget.installEventFilter(event_filter)

    return Pet3DView()
