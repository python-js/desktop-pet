"""Explicit packaging probe: temporary/in-memory data only, no network or secrets."""
import json
import os
import tempfile
from pathlib import Path
from .version import __version__


def packaged_smoke_test(report_path):
    # Run in a separate process; exercise bundled platform plugins without a window.
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PyQt5.QtWidgets import QApplication
    from .core import TaskStore
    from .ui.pet import default_pet_image
    from .ui.theme import apply_theme
    from .ui.controls import FLUENT_MODE
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    store = TaskStore(':memory:')
    try:
        store.add_message('user', 'packaging probe')
        assert store.messages()[0]['content'] == 'packaging probe'
        image = default_pet_image()
        assert not image.isNull() and image.width() == 256
        if FLUENT_MODE:
            from .app import MainWindow
            from .startup import StartupManager
            from .secure_storage import SecretStore
            previous = os.environ.get('DESKTOP_PET_DATA_DIR')
            try:
                with tempfile.TemporaryDirectory() as folder:
                    os.environ['DESKTOP_PET_DATA_DIR'] = folder
                    window = MainWindow(secret_store=SecretStore(folder, supported=False),
                                        startup_manager=StartupManager(supported=False))
                    try:
                        assert window.tabs.count() == 4
                        assert window.pet_gallery_layout.count() == 1
                        app.processEvents()
                    finally:
                        window.shutting_down = True
                        window.timer.stop()
                        window.task_refresh_timer.stop()
                        window.pet.close()
                        window.tray.hide()
                        window.close()
                        window.store.close()
                        window.deleteLater()
            finally:
                if previous is None:
                    os.environ.pop('DESKTOP_PET_DATA_DIR', None)
                else:
                    os.environ['DESKTOP_PET_DATA_DIR'] = previous
        app.processEvents()
        Path(report_path).write_text(json.dumps({'ok': True, 'version': __version__,
                                               'ui_backend': 'fluent' if FLUENT_MODE else 'native',
                                               'checks': ['qt-offscreen', 'sqlite', 'pet-image']}, indent=2), encoding='utf-8')
    finally:
        store.close()
