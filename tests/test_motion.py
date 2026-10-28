from qt_support import QT_APP
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage, QColor, QPainter
from PyQt5.QtCore import Qt
from desktop_pet.motion import generate_motion, save_motion
from desktop_pet.animations import load_sequences


def source_image():
    image = QImage(100, 120, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.fillRect(15, 15, 70, 100, QColor('#c18c73'))
    painter.end()
    return image


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_generation_alpha_variation_strength_and_source_preservation(self):
        image = source_image()
        before = image.copy()
        frames = generate_motion(image, 100)
        self.assertEqual(image, before)
        self.assertEqual(set(frames), {'idle', 'hover', 'touch', 'reminder'})
        for action, sequence in frames.items():
            self.assertEqual(len(sequence), 12 if action == 'hover' else 16)
            self.assertNotEqual(sequence[0], sequence[4])
            for frame in sequence:
                self.assertEqual((frame.width(), frame.height()), (256, 256))
                self.assertEqual(frame.pixelColor(0, 0).alpha(), 0)
                self.assertEqual(frame.pixelColor(255, 255).alpha(), 0)
        for sequence in generate_motion(image, 0).values():
            self.assertTrue(all(frame == sequence[0] for frame in sequence))
        with self.assertRaises(ValueError):
            generate_motion(QImage())
        with self.assertRaises(ValueError):
            generate_motion(image, 101)

    def test_saved_frames_reload_and_failed_save_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frames = generate_motion(source_image())
            config = save_motion(frames, root / 'animations' / 'one')
            loaded = load_sequences(config, root)
            self.assertEqual(set(loaded), {'idle', 'hover', 'touch', 'reminder'})
            self.assertEqual(len(loaded['idle']['frames']), 16)
            self.assertEqual(len(loaded['hover']['frames']), 12)
            self.assertEqual(loaded['hover']['fps'], 12)
            with patch('desktop_pet.motion.QImage.save', return_value=False):
                with self.assertRaises(OSError):
                    save_motion(frames, root / 'animations' / 'failed')
            self.assertFalse((root / 'animations' / 'failed').exists())

    def test_preview_strength_action_and_cancel_timer(self):
        from PyQt5.QtTest import QTest
        from desktop_pet.ui.motion import MotionDialog
        dialog = MotionDialog(source_image())
        try:
            before = dialog.frames['touch'][4].copy()
            dialog.strength.setValue(100)
            QTest.qWait(200)
            self.assertNotEqual(dialog.frames['touch'][4], before)
            dialog.action.setCurrentIndex(dialog.action.findData('touch'))
            self.assertEqual(dialog.index, 0)
            dialog.advance()
            self.assertEqual(dialog.preview.image, dialog.frames['touch'][1])
            dialog.reject()
            self.assertFalse(dialog.timer.isActive())
            self.assertFalse(dialog.update_timer.isActive())
        finally:
            dialog.deleteLater()
            self.app.processEvents()

    def test_apply_image_switches_static_image_and_survives_restart(self):
        from desktop_pet.app import MainWindow
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            image_path = str(Path(folder) / 'source.png')
            source_image().save(image_path)
            window = MainWindow()
            windows = [window]
            try:
                self.assertTrue(window.apply_pet_image(image_path, [{'image': image_path}], 'ok'))
                self.assertEqual(window.pet.sequences, {})
                self.assertNotIn('pet_animations', window.settings)
                self.assertEqual(window.settings['pet_images'], [{'image': image_path}])
                second = MainWindow()
                windows.append(second)
                self.assertFalse(second.pet.pixmap.isNull())
                second.select_default_image()
                self.assertNotIn('pet_image', second.settings)
                self.assertTrue(second.pet.pixmap.isNull())
                second.select_pet_image(second.settings['pet_images'][0])
                self.assertEqual(second.settings['pet_image'], image_path)
                self.assertFalse(second.pet.pixmap.isNull())
            finally:
                self.close_windows(windows)

    def test_write_failure_keeps_state_without_creating_frames(self):
        from desktop_pet.app import MainWindow
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            root = Path(folder)
            image_path = str(root / 'source.png')
            source_image().save(image_path)
            window = MainWindow()
            try:
                before = dict(window.settings)
                with patch.object(window, 'persist_settings', side_effect=OSError), patch('desktop_pet.ui.settings.QMessageBox.warning'):
                    self.assertFalse(window.apply_pet_image(image_path, [{'image': image_path}], 'x'))
                self.assertEqual(window.settings, before)
                self.assertEqual(window.pet.sequences, {})
                self.assertFalse((root / 'animations').exists())
            finally:
                self.close_windows([window])

    def test_remove_active_image_switches_to_default_and_deletes_files(self):
        from PyQt5.QtWidgets import QMessageBox
        from desktop_pet.app import MainWindow
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            image_path = str(Path(folder) / 'source.png')
            source_image().save(image_path)
            window = MainWindow()
            try:
                self.assertTrue(window.apply_pet_image(image_path, [{'image': image_path}], 'ok'))
                with patch('desktop_pet.ui.settings.QMessageBox.question', return_value=QMessageBox.Yes):
                    window.remove_pet_image()
                self.assertNotIn('pet_image', window.settings)
                self.assertEqual(window.settings['pet_images'], [])
                self.assertFalse(Path(image_path).exists())
                self.assertTrue(window.pet.pixmap.isNull())
            finally:
                self.close_windows([window])

    def close_windows(self, windows):
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
