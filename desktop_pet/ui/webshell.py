"""Embedded WebView host for the React UI; bridges one view onto the shared BridgeHost."""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QTimer, QUrl, Qt
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView

# 只做存活探测：渲染进程被回收后 DOM 不会响应，脚本回调也不会到达。
HEALTH_JS = ("(() => { const root = document.getElementById('root');"
             " return document.readyState + ':' + (root ? root.childElementCount : -1) })()")

# 隐藏期间 Chromium 会冻结合成器，恢复时可能只剩白底；超过此时长直接重载。
HIDDEN_RELOAD_SECONDS = 120
DEV_URL = 'http://127.0.0.1:5173/'


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
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.devtools_window = None
        self.devtools_view = None
        self.devtools_page = QWebEnginePage(self.view)
        self.devtools_view = QWebEngineView()
        self.devtools_view.setPage(self.devtools_page)
        self.view.page().setDevToolsPage(self.devtools_page)
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
        dev_mode = bool(os.environ.get('DESKTOP_PET_DEV')) and not getattr(sys, '_MEIPASS', None)
        if dev_mode:
            # A qrc:/// script URL is cross-origin from Vite's HTTP page; inline the
            # Qt-provided client at document creation so the bridge is ready before React.
            channel_script = QFile(':/qtwebchannel/qwebchannel.js')
            if not channel_script.open(QFile.OpenModeFlag.ReadOnly):
                raise RuntimeError('无法读取 Qt WebChannel 客户端脚本')
            try:
                source = bytes(channel_script.readAll()).decode('utf-8')
            finally:
                channel_script.close()
            bridge_client = QWebEngineScript()
            bridge_client.setName('desktop-pet-qwebchannel-client')
            bridge_client.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            bridge_client.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            bridge_client.setRunsOnSubFrames(False)
            bridge_client.setSourceCode(source)
            self.view.page().scripts().insert(bridge_client)
            dev_url = os.environ.get('DESKTOP_PET_DEV_URL', DEV_URL)
            self.view.load(QUrl(dev_url))
        else:
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
            self._nudge_repaint()
        else:
            self.reload()

    def _nudge_repaint(self):
        """最小化恢复后合成器可能停在空帧；轻抖 1px 强制重新出帧。"""
        window = self.window()
        if window is None or not window.isVisible() or window.isMinimized():
            return
        if window.isMaximized():
            size = self.view.size()
            self.view.resize(size.width(), max(1, size.height() - 1))
            QTimer.singleShot(50, lambda: self.view.resize(size))
            return
        geometry = window.geometry()
        window.resize(geometry.width(), geometry.height() + 1)
        QTimer.singleShot(50, lambda: window.resize(geometry.size()))

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

    def show_devtools(self):
        """Open the inspector attached to the embedded application page."""
        if self.devtools_window is None:
            window = QMainWindow(self.window())
            window.setWindowTitle('网页调试工具 · 小满')
            window.resize(980, 680)
            window.setCentralWidget(self.devtools_view)
            window.destroyed.connect(self._devtools_closed)
            self.devtools_window = window
        self.devtools_window.show()
        self.devtools_window.raise_()
        self.devtools_window.activateWindow()

    def _devtools_closed(self, *_):
        self.devtools_window = None
