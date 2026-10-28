from qt_support import QT_APP
"""Pet settings and uploaded image restart regression."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage
from PyQt5.QtCore import Qt, QPoint, QRect
from PyQt5.QtTest import QTest
from desktop_pet.app import MainWindow
from desktop_pet.ui.pet import BUBBLE_BOTTOM, BUBBLE_WIDTH


class PetTests(unittest.TestCase):
    def test_image_position_animation_and_touch(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            image = QImage(20, 20, QImage.Format_ARGB32)
            image.fill(Qt.red)
            image_path = str(Path(folder) / 'pet.png')
            image.save(image_path)
            window = MainWindow()
            windows = [window]
            try:
                window.settings['pet_image'] = image_path
                window.pet.move(120, 130)
                window.pet.toggle_animation()
                self.assertFalse(window.pet.timer.isActive())
                second = MainWindow()
                windows.append(second)
                self.assertFalse(second.pet.pixmap.isNull())
                self.assertTrue(second.pet.paused)
                self.assertEqual(second.settings['pet_position'], [120, 130])
                QTest.mouseClick(second.pet, Qt.LeftButton, pos=QPoint(95, 150))
                self.assertIn('摸摸', second.pet.bubble.text())
                second.pet.move(-90000, -90000)
                second.pet.ensure_visible()
                self.assertTrue(any(s.availableGeometry().contains(second.pet.geometry()) for s in app.screens()))
                second.pet.toggle_animation()
                self.assertTrue(second.pet.timer.isActive())
                second.pet.hide()
                second.pet.reset_position()
                self.assertTrue(second.pet.isVisible())
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
                app.processEvents()

    def test_bubble_size_follows_text_and_truncates_long_text(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            window = MainWindow()
            try:
                pet = window.pet
                pet.say('好的！')
                short = pet.bubble.size()
                long_text = ('已记下：明天下午三点开产品评审会，需要提前准备三页材料，'
                             '并且在会前把方案同步给设计同学，另外记得带上上次的会议纪要。')
                pet.say(long_text)
                long_size = pet.bubble.size()
                self.assertLess(short.width(), long_size.width())
                self.assertLess(short.height(), long_size.height())
                self.assertLessEqual(long_size.width(), BUBBLE_WIDTH)
                self.assertEqual(pet.bubble.y() + pet.bubble.height(), BUBBLE_BOTTOM)
                self.assertEqual(pet.bubble.x(), (pet.width() - pet.bubble.width()) // 2)
                self.assertTrue(pet.bubble.text().endswith('…'))
                self.assertEqual(pet.bubble.toolTip(), long_text)
                needed = pet.bubble.fontMetrics().boundingRect(
                    QRect(0, 0, pet.bubble.contentsRect().width(), 1000),
                    Qt.TextWordWrap, pet.bubble.text())
                self.assertLessEqual(needed.height(), pet.bubble.contentsRect().height())
            finally:
                window.shutting_down = True
                window.timer.stop()
                window.task_refresh_timer.stop()
                window.pet.close()
                window.tray.hide()
                window.close()
                window.store.close()
                window.deleteLater()
                app.processEvents()

    def test_image_apply_is_static_and_removes_old_actions(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            root = Path(folder)
            image = QImage(20, 20, QImage.Format_ARGB32)
            image.fill(Qt.red)
            image_path = str(root / 'pet.png')
            image.save(image_path)
            stale = root / 'animations' / 'auto-old'
            stale.mkdir(parents=True)
            image.save(str(stale / 'idle-000.png'))
            (root / 'settings.json').write_text(json.dumps({
                'pet_image': image_path,
                'pet_images': [{'image': image_path}],
                'pet_animations': {'idle': {'frames': [str(stale / 'idle-000.png')], 'fps': 10}},
            }), encoding='utf-8')
            window = MainWindow()
            try:
                self.assertNotIn('pet_animations', window.settings)
                self.assertFalse(stale.exists())
                persisted = json.loads((root / 'settings.json').read_text(encoding='utf-8'))
                self.assertNotIn('pet_animations', persisted)
                window.apply_pet_image(image_path, [{'image': image_path}], '')
                self.assertEqual(window.pet.sequences, {})
                self.assertFalse(window.pet.pixmap.isNull())
                self.assertFalse(list((root / 'animations').glob('auto-*')))
            finally:
                window.shutting_down = True
                window.timer.stop()
                window.task_refresh_timer.stop()
                window.pet.close()
                window.tray.hide()
                window.close()
                window.store.close()
                window.deleteLater()
                app.processEvents()
