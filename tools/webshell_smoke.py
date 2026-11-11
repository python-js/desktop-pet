"""Phase 0 smoke test: load the built web UI in a real WebEngine view.

The script emits a buffered event before the page loads; the React handshake
(system.info) must flush it. A local listener on the bridge signal proves the
JS side actually performed the handshake. A screenshot is saved for inspection.

Usage: .venv/Scripts/python.exe tools/webshell_smoke.py [out.png]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6 import QtWebEngineWidgets  # noqa: F401  must be imported before QApplication
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from desktop_pet.bridge import BridgeHost
from desktop_pet.ui.webshell import WebShell

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('build') / 'webshell-smoke.png'
TIMEOUT_MS = 30000


def main():
    app = QApplication(sys.argv)
    host = BridgeHost(context={'data_dir': 'smoke', 'dev_mode': True})
    shell = WebShell(host)
    shell.resize(1000, 700)
    shell.show()

    state = {'handshake': False, 'events': [], 'saved': False}

    def finish():
        if not state['saved']:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            state['saved'] = shell.grab().save(str(OUT))
        app.quit()

    def on_event(name, _payload):
        if not state['handshake']:
            state['handshake'] = True
        state['events'].append(name)
        QTimer.singleShot(400, finish)

    host.event.connect(on_event)
    host.emit_event('smoke.ping', {'v': 1})  # buffered; only the JS handshake can flush it
    QTimer.singleShot(TIMEOUT_MS, finish)
    app.exec()

    print(json.dumps({
        'handshake': state['handshake'],
        'events': state['events'],
        'screenshot': str(OUT) if state['saved'] else None,
    }, ensure_ascii=False))
    return 0 if state['handshake'] and state['saved'] else 1


if __name__ == '__main__':
    sys.exit(main())
