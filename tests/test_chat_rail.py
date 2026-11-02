from qt_support import QT_APP
import importlib.util
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('PyQt5'), 'PyQt5 未安装')
class ChatRailTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow
        self.app = QApplication.instance() or QApplication([])
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': self.temp.name})
        self.environment.start()
        self.window = MainWindow()
        self.window.timer.stop()
        self.window.task_refresh_timer.stop()

    def tearDown(self):
        self.window.timer.stop()
        self.window.shutting_down = True
        self.window.pet.close()
        self.window.tray.hide()
        self.window.close()
        self.window.store.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def test_rail_breakpoint_and_toggle(self):
        window = self.window
        window.apply_chat_layout(1440, force=True)
        self.assertFalse(window.chat_rail.isHidden())
        self.assertEqual(window.chat_rail.width(), 296)
        self.assertTrue(window.chat_rail_toggle.isHidden())

        window.apply_chat_layout(1180, force=True)
        self.assertTrue(window.chat_rail.isHidden())
        self.assertFalse(window.chat_rail_toggle.isHidden())
        window.toggle_chat_rail()
        self.assertFalse(window.chat_rail.isHidden())
        window.toggle_chat_rail()
        self.assertTrue(window.chat_rail.isHidden())

        window.apply_chat_layout(1440, force=True)
        self.assertFalse(window.chat_rail.isHidden())

    def test_draft_card_confirm_writes_task_and_discard_does_not(self):
        from PyQt5.QtTest import QTest
        window = self.window
        due = (datetime.now().astimezone() + timedelta(days=1)).replace(microsecond=0).isoformat()

        window.add_draft({'title': '确认后入库', 'due_at': due, 'note': '补充一句背景'})
        card = window.drafts.itemAt(0).widget()
        self.assertEqual(window.store.pending(), [])
        self.assertEqual(len(window.store.drafts()), 1)
        card.save_button.click()
        QTest.qWait(20)
        self.assertEqual([row['title'] for row in window.store.pending()], ['确认后入库'])
        self.assertEqual(window.store.drafts(), [])
        self.assertEqual(window.drafts.count(), 0)
        self.assertTrue(window.draft_holder.isHidden())

        window.add_draft({'title': '丢弃就不要写库', 'due_at': due})
        card = window.drafts.itemAt(0).widget()
        card.discard_button.click()
        QTest.qWait(20)
        self.assertEqual([row['title'] for row in window.store.pending()], ['确认后入库'])
        self.assertEqual(window.store.drafts(), [])
        self.assertTrue(window.draft_holder.isHidden())

    def test_mute_from_rail_marks_task_and_reports(self):
        window = self.window
        now = datetime.now().astimezone()
        task_id = window.store.add('会被静音的待办', (now + timedelta(hours=1)).isoformat(),
                                   now, source='chat')
        window.refresh_tasks()
        self.assertEqual(window.chat_rail.latest_task['id'], task_id)

        window.chat_mute_task(task_id)
        row = next(item for item in window.store.pending() if item['id'] == task_id)
        self.assertEqual(row['muted_until'], now.date().isoformat())
        self.assertIn('今天不再提醒', window.history.toPlainText())

    def test_unexpected_failure_does_not_expose_raw_response(self):
        from desktop_pet.app import AssistantWorker
        worker = AssistantWorker({}, [], [], None)
        messages = []
        worker.failed.connect(messages.append)
        with patch('desktop_pet.app.ask', side_effect=RuntimeError('SECRET raw provider body')):
            worker.run()
        self.assertEqual(messages, ['请求失败，请检查模型设置后重试。'])


if __name__ == '__main__':
    unittest.main()
