from qt_support import QT_APP
"""P6 dialog tokens, final reminder state and screen clamping."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from PyQt5.QtCore import QRect
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel

from desktop_pet.ui import tokens as T
from desktop_pet.ui.theme import apply_theme


class DialogTests(unittest.TestCase):
    def tearDown(self):
        apply_theme(QT_APP, 'light')
        QT_APP.processEvents()

    def task(self):
        return {'title': '整理本周周报', 'due_at': '2026-11-03T18:30:00+08:00',
                'repeat_rule': 'weekdays', 'dingtalk': True}

    def test_task_dialog_fields_and_heading_tokens(self):
        from desktop_pet.ui.common import TaskDialog
        from desktop_pet.ui.controls import PrimaryButton
        apply_theme(QT_APP, 'dark')
        dialog = TaskDialog(None, self.task())
        try:
            self.assertEqual(dialog.title.text(), '整理本周周报')
            self.assertEqual(dialog.repeat.currentData(), 'weekdays')
            self.assertTrue(dialog.dingtalk.isChecked())
            self.assertIsInstance(dialog.save_button, PrimaryButton)
            self.assertIsNotNone(dialog.findChild(QLabel, 'dialogTitle'))
            self.assertIsNotNone(dialog.findChild(QLabel, 'dialogSubtitle'))
            self.assertLessEqual(dialog.minimumSizeHint().width(), dialog.width())
            self.assertLessEqual(dialog.minimumSizeHint().height(), dialog.height())
        finally:
            dialog.deleteLater()
            QT_APP.processEvents()

    def test_plan_dialog_preview_and_action_text(self):
        from desktop_pet.ui.common import PlanDialog
        prompt = '{"today": [{"title": "整理周报"}]}'
        dialog = PlanDialog(None, prompt, True)
        local = PlanDialog(None, prompt, False)
        try:
            self.assertEqual(dialog.preview.toPlainText(), prompt)
            self.assertEqual(dialog.accept_button.text(), '发送给模型')
            self.assertEqual(local.accept_button.text(), '生成本地清单')
            self.assertIsNotNone(dialog.findChild(QLabel, 'dialogTitle'))
        finally:
            for item in (dialog, local):
                item.deleteLater()
            QT_APP.processEvents()

    def test_final_reminder_disables_snooze_and_clamps_to_screen(self):
        from desktop_pet.ui.reminder import ReminderDialog
        due = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        calls = []
        dialog = ReminderDialog(None, {'title': '预算复核', 'due_at': due, 'repeat_rule': 'none'},
                                lambda: calls.append('complete'), lambda: calls.append('snooze'),
                                lambda: calls.append('open'), final=True)
        try:
            self.assertTrue(dialog.final)
            self.assertFalse(dialog.snooze_button.isEnabled())
            self.assertIn('不再重复提醒', dialog.snooze_button.toolTip())
            self.assertIn('延期', dialog.hint.text())
            bounds = QT_APP.primaryScreen().availableGeometry()
            dialog.present(QRect(bounds.right() - 20, bounds.bottom() - 20, 60, 60), 2)
            QT_APP.processEvents()
            self.assertTrue(bounds.contains(dialog.frameGeometry()))
            dialog.complete_button.click()
            self.assertTrue(dialog.resolved)
            self.assertEqual(calls, ['complete'])
        finally:
            dialog.close()
            dialog.deleteLater()
            QT_APP.processEvents()

    def test_reminder_uses_secondary_screen_bounds(self):
        from desktop_pet.ui.reminder import ReminderDialog

        class Secondary:
            def availableGeometry(self):
                return QRect(1920, 0, 1280, 720)

        dialog = ReminderDialog(None, {'title': '双屏检查', 'due_at': '2099-01-01T12:00:00+08:00',
                                       'repeat_rule': 'none'}, lambda: None, lambda: None, lambda: None)
        try:
            with patch('desktop_pet.ui.reminder.QApplication.screenAt', return_value=Secondary()):
                dialog.present(QRect(3140, 700, 60, 60), 1)
                QT_APP.processEvents()
                self.assertTrue(Secondary().availableGeometry().contains(dialog.frameGeometry()))
        finally:
            dialog.close()
            dialog.deleteLater()
            QT_APP.processEvents()

    def test_regular_reminder_allows_snooze(self):
        from desktop_pet.ui.reminder import ReminderDialog
        due = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        dialog = ReminderDialog(None, {'title': '休息', 'due_at': due, 'repeat_rule': 'daily'},
                                lambda: None, lambda: None, lambda: None)
        try:
            self.assertTrue(dialog.snooze_button.isEnabled())
            self.assertNotIn('延期', dialog.hint.text())
        finally:
            dialog.deleteLater()
            QT_APP.processEvents()

    def test_cutout_preview_follows_theme_tokens(self):
        from desktop_pet.ui.cutout import CutoutDialog, ImagePreview
        preview = ImagePreview(QImage())
        preview.resize(64, 64)
        try:
            colors = {}
            for theme in ('light', 'dark'):
                apply_theme(QT_APP, theme)
                preview.update()
                canvas = QPixmap(preview.size())
                preview.render(canvas)
                colors[theme] = canvas.toImage().pixelColor(24, 24).name().lower()
            self.assertEqual(colors['light'], T.get('light').surface.lower())
            self.assertEqual(colors['dark'], T.get('dark').surface.lower())
        finally:
            preview.deleteLater()

        dialog = CutoutDialog(self.image())
        try:
            self.assertFalse(dialog.apply_button.isEnabled())
            self.assertEqual(dialog.status.objectName(), 'dialogHintText')
            self.assertLessEqual(dialog.minimumSizeHint().width(), dialog.width())
            self.assertLessEqual(dialog.minimumSizeHint().height(), dialog.height())
        finally:
            dialog.deleteLater()
            QT_APP.processEvents()

    def image(self):
        image = QImage(20, 20, QImage.Format_RGBA8888)
        image.fill(0xFFFFFFFF)
        return image.copy()
