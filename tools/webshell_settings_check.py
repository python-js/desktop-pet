"""Phase 1 UI check: run the real MainWindow with the built React settings
page, verify the page mounted, capture console errors and a screenshot.

Usage: .venv/Scripts/python.exe tools/webshell_settings_check.py [out.png]
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6 import QtWebEngineWidgets  # noqa: F401  must be imported before QApplication
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('build') / 'webshell-settings.png'
CHECK_JS = """(function(){
  var headings = Array.from(document.querySelectorAll('h1, h2, h3')).map(function(e){ return e.textContent.trim() });
  var text = document.getElementById('root').textContent;
  return JSON.stringify({
    aside: !!document.querySelector('aside'),
    headingCount: headings.length,
    headings: headings,
    buttons: document.querySelectorAll('button').length,
    inputs: document.querySelectorAll('input').length,
    switches: document.querySelectorAll('[role="switch"]').length,
    images: document.querySelectorAll('img').length,
    petCard: text.indexOf('\u5ba0\u7269\u5f62\u8c61') !== -1,
    petTiles: document.querySelectorAll('[aria-pressed]').length,
    theme: document.documentElement.dataset.theme || null,
    rootText: text.slice(0, 300),
    rootLen: document.getElementById('root').innerHTML.length,
  });
})()"""


def main():
    temp = tempfile.TemporaryDirectory()
    os.environ['DESKTOP_PET_DATA_DIR'] = temp.name
    (Path(temp.name) / 'settings.json').write_text(
        json.dumps({'theme': 'light'}), encoding='utf-8')
    app = QApplication(sys.argv)
    from desktop_pet.app import MainWindow
    window = MainWindow()
    window.timer.stop()
    window.resize(1180, 840)
    window.show()
    console = []

    def on_console(level, message, line, source):
        console.append(f'[{level}] {message} ({source}:{line})')

    window.web_shell.view.page().javaScriptConsoleMessage = on_console

    state = {'done': False}

    def finish():
        if state['done']:
            return
        state['done'] = True
        # Settings is no longer the landing page; open it the same way a user would.
        window.web_shell.view.page().runJavaScript(
            "Array.from(document.querySelectorAll('aside button'))"
            ".find(function(b){ return b.textContent.indexOf('\\u8bbe\\u7f6e') !== -1; })"
            "?.click()")

        def probe():
            window.web_shell.view.page().runJavaScript(
                CHECK_JS, lambda result: state.__setitem__('probe', result))
            QTimer.singleShot(1500, wrap_up)

        def wrap_up():
            OUT.parent.mkdir(parents=True, exist_ok=True)
            state['shot'] = window.grab().save(str(OUT))
            # Write results before quitting so a later crash cannot lose them.
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            print('RESULT ' + json.dumps(
                {'probe': state.get('probe'), 'console': console, 'screenshot': str(OUT)},
                ensure_ascii=False, indent=2), flush=True)
            window.shutting_down = True
            window.pet.close()
            window.tray.hide()
            window.close()

        QTimer.singleShot(700, probe)

    QTimer.singleShot(9000, finish)
    app.exec()

    probe = json.loads(state.get('probe') or '{}')
    window.store.close()
    temp.cleanup()
    required = (probe.get('aside'), probe.get('petCard'), probe.get('petTiles', 0),
                probe.get('buttons', 0) > 0)
    return 0 if all(required) else 1


if __name__ == '__main__':
    sys.exit(main())
