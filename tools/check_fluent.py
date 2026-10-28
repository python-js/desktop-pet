"""Run after installing requirements-fluent.txt; never use real user data."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DESKTOP_PET_UI'] = 'fluent'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'


def main():
    import importlib.metadata as metadata
    try:
        print('PyQt-Fluent-Widgets:', metadata.version('PyQt-Fluent-Widgets'))
    except metadata.PackageNotFoundError:
        raise SystemExit('Install requirements-fluent.txt first; Fluent verification has not run.')
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtTest import QTest
    from qfluentwidgets import PrimaryPushButton
    from desktop_pet.ui.theme import apply_theme
    from desktop_pet.ui.settings import PetImageTile
    from desktop_pet.app import MainWindow
    app = QApplication([])
    apply_theme(app)
    with tempfile.TemporaryDirectory() as folder:
        os.environ['DESKTOP_PET_DATA_DIR'] = folder
        window = MainWindow()
        try:
            window.timer.stop()
            assert isinstance(window.send, PrimaryPushButton)
            assert isinstance(window.pet_gallery_layout.itemAt(0).widget(), PetImageTile)
            window.new_session()
            window.new_session()
            window.input.setPlainText('unsent')
            window.load_conversation()
            assert window.input.toPlainText() == 'unsent'
            window.add_draft({'title': 'Fluent probe', 'due_at': '2099-01-01T12:00:00Z'})
            assert window.drafts.count() == 1
            window.tabs.setCurrentIndex(2)
            window.resize(1180, 820)
            window.show()
            QTest.qWait(200)
            folder_path = ROOT / '.artifacts'
            folder_path.mkdir(exist_ok=True)
            window.grab().save(str(folder_path / 'fluent-settings.png'))
            print('Fluent components, data mapping, input restore and draft creation: passed')
        finally:
            window.shutting_down = True
            window.timer.stop()
            window.task_refresh_timer.stop()
            window.pet.close()
            window.tray.hide()
            window.close()
            window.store.close()


if __name__ == '__main__':
    main()
