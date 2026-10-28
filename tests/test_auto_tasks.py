from qt_support import QT_APP
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from desktop_pet.app import MainWindow


class AutoTaskTests(unittest.TestCase):
    def test_auto_save_repeat_dedup_and_invalid_time(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            window = MainWindow()
            window.timer.stop()
            try:
                task = {'title': '喝水', 'due_at': '2099-01-01T12:00:00+08:00'}
                content = json.dumps({'reply': '请确认保存', 'tasks': [task]}, ensure_ascii=False)
                window.on_reply(content)
                self.assertEqual(window.drafts.count(), 0)
                self.assertEqual(window.store.drafts(), [])
                self.assertEqual(len(window.store.pending()), 1)
                self.assertEqual(window.store.pending()[0]['repeat_rule'], 'none')
                self.assertIn('已保存：喝水', window.history.toPlainText())
                self.assertNotIn('请确认保存', window.history.toPlainText())
                window.on_reply(content)
                self.assertEqual(len(window.store.pending()), 1)
                self.assertIn('已有待办：喝水', window.history.toPlainText())
                task.update(title='每日喝水', repeat='daily')
                window.on_reply(json.dumps({'reply': '正在处理', 'tasks': [task]}))
                self.assertEqual(len(window.store.pending()), 2)
                self.assertEqual(window.store.pending()[1]['repeat_rule'], 'daily')
                task['due_at'] = '2000-01-01T12:00:00+08:00'
                window.on_reply(json.dumps({'reply': '时间无效', 'tasks': [task]}))
                self.assertEqual(len(window.store.pending()), 2)
                window.on_reply('{"reply":"请提供提醒时间","tasks":[]}')
                self.assertEqual(len(window.store.pending()), 2)
            finally:
                window.shutting_down = True
                window.timer.stop()
                window.task_refresh_timer.stop()
                window.pet.close()
                window.tray.hide()
                window.close()
                window.store.close()
                window.deleteLater()
                QT_APP.processEvents()
