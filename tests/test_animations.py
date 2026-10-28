from qt_support import QT_APP
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage, QColor
from desktop_pet.animations import import_sequence, load_sequences


class AnimationTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = []
        for name, color in [('10.png', 'blue'), ('2.png', 'green'), ('1.png', 'red')]:
            image = QImage(30, 30, QImage.Format_ARGB32)
            image.fill(QColor(color))
            path = self.root / name
            image.save(str(path))
            self.paths.append(str(path))

    def tearDown(self):
        self.temp.cleanup()

    def test_natural_order_bounds_and_damaged_frame_fallback(self):
        folder = self.root / 'animations' / 'one'
        entry = import_sequence(self.paths, folder, 10)
        first = QImage(entry['frames'][0])
        self.assertEqual(first.pixelColor(0, 0), QColor('red'))
        self.assertEqual(len(load_sequences({'idle': entry}, self.root)['idle']['frames']), 3)
        Path(entry['frames'][1]).write_bytes(b'bad')
        self.assertEqual(load_sequences({'idle': entry}, self.root), {})
        for paths, fps in [(self.paths[:1], 10), (self.paths, 21), (self.paths * 9, 10)]:
            with self.assertRaises(ValueError):
                import_sequence(paths, self.root / 'bad', fps)
        self.assertFalse((self.root / 'bad').exists())

    def test_external_paths_and_failed_import_cleanup(self):
        self.assertEqual(load_sequences({'idle': {'frames': self.paths, 'fps': 10}}, self.root), {})
        bad = self.root / 'bad.png'
        bad.write_bytes(b'not an image')
        folder = self.root / 'animations' / 'failed'
        with self.assertRaises(ValueError):
            import_sequence([self.paths[0], str(bad)], folder, 10)
        self.assertFalse(folder.exists())

    def test_sequence_playback_advance_pause_and_restart(self):
        from desktop_pet.app import MainWindow
        entry = import_sequence(self.paths, self.root / 'animations' / 'idle', 10)
        with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': str(self.root)}):
            window = MainWindow()
            windows = [window]
            try:
                window.settings['pet_animations'] = {'idle': entry}
                window.persist_settings()
                window.pet.load_animations()
                initial = window.pet.action_started
                window.pet.advance_action(initial + 0.11)
                self.assertEqual(window.pet.frame_index, 1)
                window.pet.advance_action(initial + 0.41)
                self.assertEqual(window.pet.frame_index, 1)
                window.pet.toggle_animation()
                window.pet.play_action('touch')
                self.assertEqual(window.pet.action, 'idle')
                window.pet.toggle_animation()
                second = MainWindow()
                windows.append(second)
                # 0.20 起启动时不再加载动作配置，序列保持为空。
                self.assertEqual(second.pet.sequences, {})
                self.assertNotIn('pet_animations', second.settings)
            finally:
                for item in windows:
                    item.shutting_down = True
                    item.timer.stop()
                    item.task_refresh_timer.stop()
                    item.pet.close()
                    item.tray.hide()
                    item.close()
                    item.store.close()
                    item.deleteLater()
                self.app.processEvents()

    def test_reminder_action_has_priority_and_falls_back_to_static(self):
        from desktop_pet.app import MainWindow
        with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': str(self.root)}):
            window = MainWindow()
            try:
                entry = import_sequence(self.paths, self.root / 'animations' / 'events', 10)
                window.settings['pet_animations'] = {'touch': entry, 'reminder': entry}
                window.pet.load_animations()
                window.pet.play_action('reminder')
                window.pet.play_action('touch')
                self.assertEqual(window.pet.action, 'reminder')
                window.pet.advance_action(window.pet.action_started + 1)
                self.assertEqual(window.pet.action, 'idle')
                self.assertNotIn('idle', window.pet.sequences)
            finally:
                window.shutting_down = True
                window.timer.stop()
                window.task_refresh_timer.stop()
                window.pet.close()
                window.tray.hide()
                window.close()
                window.store.close()
                window.deleteLater()
                self.app.processEvents()
