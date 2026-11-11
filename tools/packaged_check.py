"""Phase 0.6: launch the packaged exe against an isolated data dir.

Measures time-to-main-window and captures the web view to verify the bridge
handshake renders. Usage:

    .venv/Scripts/python.exe tools/packaged_check.py <path-to-packaged-DesktopPet.exe>
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

OUT_DIR = Path(__file__).resolve().parents[1] / 'build' / 'packaged-check'
SETTLE_SECONDS = 9.0
STARTUP_TIMEOUT = 45.0


def visible_windows(pid):
    results = []
    pid_buf = ctypes.c_ulong()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)
    def on_window(hwnd):
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
        if pid_buf.value != pid or not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value:
            results.append((int(hwnd), buf.value))
        return True

    ctypes.windll.user32.EnumWindows(on_window, 0)
    return results


def run_mode(exe, data_dir, capture_name=None):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / 'settings.json').write_text(json.dumps({'theme': 'light'}), encoding='utf-8')
    env = dict(os.environ, DESKTOP_PET_DATA_DIR=str(data_dir))
    start = time.perf_counter()
    proc = subprocess.Popen([str(exe)], env=env, cwd=exe.parent,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    hwnd = None
    startup_ms = None
    try:
        deadline = time.perf_counter() + STARTUP_TIMEOUT
        while time.perf_counter() < deadline:
            for handle, title in visible_windows(proc.pid):
                if title.startswith('Desktop Pet'):
                    hwnd, startup_ms = handle, (time.perf_counter() - start) * 1000
                    break
            if hwnd or proc.poll() is not None:
                break
            time.sleep(0.1)
        if hwnd is None:
            raise SystemExit(f'main window never appeared (exit={proc.poll()})')
        time.sleep(SETTLE_SECONDS)
        captured = False
        if capture_name:
            QGuiApplication.primaryScreen().grabWindow(hwnd).save(str(OUT_DIR / capture_name))
            captured = (OUT_DIR / capture_name).is_file()
        return {'startup_ms': round(startup_ms), 'captured': captured}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    exe = Path(sys.argv[1])
    if not exe.is_file():
        raise SystemExit(f'exe not found: {exe}')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _app = QApplication([])  # QPixmap.grabWindow needs a live QGuiApplication.
    results = [
        run_mode(exe, OUT_DIR / 'data-web', 'web-mode.png'),
    ]
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
