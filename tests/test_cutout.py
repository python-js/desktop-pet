from qt_support import QT_APP
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_pet.cutout import corner_color, remove_background, CutoutCancelled


def sample():
    # White background, red enclosing ring, white detail inside the subject.
    pixels = bytearray(bytes((255, 255, 255, 255)) * 49)
    for y in range(1, 6):
        for x in range(1, 6):
            if x in (1, 5) or y in (1, 5):
                pixels[(y * 7 + x) * 4:(y * 7 + x) * 4 + 4] = bytes((255, 0, 0, 255))
    return bytes(pixels)


class CutoutTests(unittest.TestCase):
    def test_removes_only_edge_connected_color_and_keeps_source(self):
        original = sample()
        result = remove_background(7, 7, original, (255, 255, 255), 0)
        self.assertEqual(result[3], 0)
        self.assertEqual(result[(3 * 7 + 3) * 4 + 3], 255)
        self.assertEqual(result[(1 * 7 + 1) * 4 + 3], 255)
        self.assertEqual(original[3], 255)

    def test_tolerance_and_transparent_edge_traversal(self):
        pixels = bytes((0, 0, 0, 0, 245, 245, 245, 255, 255, 0, 0, 128))
        result = remove_background(3, 1, pixels, (255, 255, 255), 10)
        self.assertEqual(list(result[3::4]), [0, 0, 128])
        result = remove_background(3, 1, pixels, (255, 255, 255), 9)
        self.assertEqual(list(result[3::4]), [0, 255, 128])

    def test_color_guess_validation_and_cancel(self):
        white = bytes((250, 250, 250, 255)) * 100
        self.assertEqual(corner_color(10, 10, white), (250, 250, 250))
        self.assertEqual(corner_color(1, 1, bytes(4)), (255, 255, 255))
        with self.assertRaises(ValueError):
            remove_background(7, 7, b'', (255, 255, 255))
        with self.assertRaises(ValueError):
            remove_background(7, 7, sample(), (255, 255, 255), 121)
        with self.assertRaises(CutoutCancelled):
            remove_background(7, 7, sample(), (255, 255, 255), cancelled=lambda: True)


class CutoutUiTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def image(self):
        from PyQt5.QtGui import QImage
        return QImage(sample(), 7, 7, 28, QImage.Format_RGBA8888).copy()

    def wait_worker(self, dialog):
        from PyQt5.QtTest import QTest
        for _ in range(400):
            QTest.qWait(10)
            if dialog.worker is None:
                break
        self.assertIsNone(dialog.worker)

    def test_preview_parameter_change_and_fully_transparent_rejection(self):
        from desktop_pet.ui.cutout import CutoutDialog
        dialog = CutoutDialog(self.image())
        try:
            dialog.process()
            self.wait_worker(dialog)
            self.assertEqual(dialog.result_image.pixelColor(0, 0).alpha(), 0)
            self.assertEqual(dialog.result_image.pixelColor(3, 3).alpha(), 255)
            self.assertTrue(dialog.apply_button.isEnabled())
            dialog.tolerance.setValue(40)
            self.assertTrue(dialog.result_image.isNull())
            self.assertFalse(dialog.apply_button.isEnabled())
            dialog.on_ready(bytes(7 * 7 * 4))
            self.assertTrue(dialog.result_image.isNull())
        finally:
            dialog.deleteLater()
            self.app.processEvents()

    def test_cancel_waits_for_worker(self):
        from desktop_pet.ui.cutout import CutoutDialog
        gate = threading.Event()
        def delayed(*args):
            gate.wait(2)
            return sample()
        dialog = CutoutDialog(self.image())
        try:
            with patch('desktop_pet.ui.cutout.remove_background', side_effect=delayed):
                dialog.process()
                dialog.reject()
                self.assertTrue(dialog.close_pending)
                gate.set()
                self.wait_worker(dialog)
            self.assertTrue(dialog.result_image.isNull())
            self.assertEqual(dialog.result(), dialog.Rejected)
        finally:
            gate.set()
            dialog.deleteLater()
            self.app.processEvents()

    def test_apply_restart_restore_and_save_failure(self):
        from desktop_pet.app import MainWindow
        from desktop_pet.ui.cutout import CutoutDialog
        from PyQt5.QtWidgets import QDialog
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            original = str(Path(folder) / 'original.png')
            self.image().save(original)
            window = MainWindow()
            windows = [window]
            try:
                window.settings['pet_image'] = original
                window.settings['pet_images'] = [{'image': original}]
                window.persist_settings()
                before = dict(window.settings)
                with patch.object(CutoutDialog, 'exec_', return_value=QDialog.Rejected):
                    window.remove_image_background()
                self.assertEqual(window.settings, before)
                def accept_preview(dialog):
                    dialog.result_image = self.image()
                    return QDialog.Accepted
                with patch.object(CutoutDialog, 'exec_', accept_preview):
                    with patch.object(window, 'persist_settings', side_effect=OSError), patch('desktop_pet.ui.settings.QMessageBox.warning'):
                        window.remove_image_background()
                    self.assertEqual(window.settings, before)
                    self.assertEqual(list(Path(folder).glob('pet-cutout-*')), [])
                    window.remove_image_background()
                target = window.settings['pet_image']
                self.assertNotEqual(target, original)
                self.assertTrue(Path(target).is_file())
                self.assertEqual(window.active_pet_record()['original'], original)
                second = MainWindow()
                windows.append(second)
                self.assertEqual(second.active_pet_record()['original'], original)
                second.restore_original_image()
                self.assertEqual(second.settings['pet_image'], original)
                self.assertNotIn('original', second.active_pet_record())
                self.assertTrue(Path(original).is_file())
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
