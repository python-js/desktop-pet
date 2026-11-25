"""Explicit packaging probe: temporary/in-memory data only, no network or secrets."""
import json
import os
from pathlib import Path
from .version import __version__


def packaged_smoke_test(report_path):
    # Run in a separate process; exercise bundled platform plugins without a window.
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    from .core import TaskStore
    from .ui.pet import default_pet_image
    from .ui.pet3d import SCENE
    from .ui.theme import apply_theme
    from .ui.webshell import web_dist
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    store = TaskStore(':memory:')
    try:
        store.add_message('user', 'packaging probe')
        assert store.messages()[0]['content'] == 'packaging probe'
        image = default_pet_image()
        assert not image.isNull() and image.width() > 0
        assert SCENE.is_file()
        for name in ('three.min.js', 'GLTFLoader.js', 'husky.glb.js'):
            assert (SCENE.parent / name).is_file(), name
        assert (web_dist() / 'index.html').is_file()
        app.processEvents()
        Path(report_path).write_text(json.dumps({'ok': True, 'version': __version__,
                                               'ui_backend': 'web',
                                               'checks': ['qt-offscreen', 'sqlite', 'pet-image',
                                                          'pet3d-assets', 'web-bundle']}, indent=2),
                                     encoding='utf-8')
    finally:
        store.close()
