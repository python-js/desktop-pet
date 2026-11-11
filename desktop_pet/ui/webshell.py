"""Embedded WebView host for the React UI; bridges one view onto the shared BridgeHost."""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView

# 只做存活探测：渲染进程被回收后 DOM 不会响应，脚本回调也不会到达。
HEALTH_JS = ("(() => { const root = document.getElementById('root');"
             " return document.readyState + ':' + (root ? root.childElementCount : -1) })()")

# 隐藏期间 Chromium 会冻结合成器，恢复时可能只剩白底；超过此时长直接重载。
HIDDEN_RELOAD_SECONDS = 120


def web_dist() -> Path:
    override = os.environ.get('DESKTOP_PET_WEB_DIST')
    if override:
        return Path(override)
    frozen = getattr(sys, '_MEIPASS', None)
    if frozen:
        return Path(frozen) / 'web'
    return Path(__file__).resolve().parents[2] / 'web' / 'dist'


class WebShell(QWidget):
    """Main-window central widget that loads the built web UI and attaches the bridge channel."""

    def __init__(self, bridge_host, parent=None):
        super().__init__(parent)
        self.view = QWebEngineView(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject('bridge', bridge_host)
        self.view.page().setWebChannel(self.channel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.render_lost = False
        self._loading = True
        self._loaded_once = False
        self._loaded_hidden = False
        self._probe_ok = False
        self._probe_id = 0
        self._recover_delay = 300
        self.view.loadFinished.connect(self._on_loaded)
        self.view.page().renderProcessTerminated.connect(self._on_render_gone)
        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.timeout.connect(self._on_probe_timeout)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self.reload)
        self.view.load(QUrl.fromLocalFile(str(web_dist() / 'index.html')))

    def _on_loaded(self, ok):
        self._loading = False
        if ok:
            self._loaded_once = True
            self.render_lost = False
            # 后台启动时页面在隐藏窗口里加载完成，首帧从未绘制过，直接显示会是白屏。
            self._loaded_hidden = not self.isVisible()
            self._recover_delay = 300

    def _on_render_gone(self, status, code):
        # 主窗长时间隐藏时 Chromium 会回收渲染进程，再次显示只剩下白底。
        self.render_lost = True
        if self.isVisible():
            self._reload_timer.start(self._recover_delay)
            self._recover_delay = min(5000, self._recover_delay * 2)

    def ensure_alive(self, hidden_seconds=0.0):
        """主窗显示前后调用：页面空白、隐藏加载或久置后强制重载，否则做存活探测。"""
        if self._loading or not self._loaded_once:
            return
        if (self.render_lost or self._loaded_hidden
                or hidden_seconds >= HIDDEN_RELOAD_SECONDS):
            self.reload()
            return
        self._probe_id += 1
        probe_id = self._probe_id
        self._probe_ok = False
        self.view.page().runJavaScript(HEALTH_JS, lambda value: self._on_probe(probe_id, value))
        self._probe_timer.start(1500)

    def _on_probe(self, probe_id, value):
        if probe_id != self._probe_id:
            return
        self._probe_timer.stop()
        ready, _, count = str(value).partition(':')
        if ready == 'complete' and count.isdigit() and int(count) > 0:
            self._probe_ok = True
        else:
            self.reload()

    def _on_probe_timeout(self):
        if not self._probe_ok:
            self.reload()

    def reload(self):
        app = QApplication.instance()
        if app is not None and app.closingDown():
            return
        self._reload_timer.stop()
        self._probe_timer.stop()
        self._loading = True
        self.render_lost = False
        self._loaded_hidden = False
        self.view.reload()
