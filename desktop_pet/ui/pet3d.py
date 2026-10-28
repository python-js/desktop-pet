"""Local three.js pet canvas; WebEngine stays optional and is imported on first use."""
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt, QUrl
from PyQt5.QtWidgets import QWidget

SCENE = Path(__file__).resolve().parent.parent / 'assets' / 'pet3d' / 'index.html'


def create_view(parent=None, event_filter=None):
    from PyQt5.QtWebEngineWidgets import QWebEngineView

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
