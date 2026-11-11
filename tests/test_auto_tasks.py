from qt_support import QT_APP
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from desktop_pet.app import MainWindow
from desktop_pet.core import decode_response


class AutoTaskTests(unittest.TestCase):
    def apply_reply(self, window, content):
        reply, tasks, errors = decode_response(content)
        receipts, op_errors, choice = (window.run_task_ops(tasks, 'default') if tasks
                                       else ([], errors, None))
        return reply, receipts, op_errors, choice

    def test_auto_save_repeat_dedup_and_invalid_time(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            window = MainWindow()
            window.timer.stop()
            try:
                task = {'title': '喝水', 'due_at': '2099-01-01T12:00:00+08:00'}
                content = json.dumps({'reply': '请确认保存', 'tasks': [task]}, ensure_ascii=False)
                reply, receipts, errors, choice = self.apply_reply(window, content)
                self.assertEqual(reply, '请确认保存')
                self.assertEqual(len(receipts), 1)
                self.assertTrue(receipts[0].startswith('已保存：喝水'))
                self.assertEqual(errors, [])
                self.assertIsNone(choice)
                self.assertEqual(window.store.drafts(), [])
                self.assertEqual(len(window.store.pending()), 1)
                self.assertEqual(window.store.pending()[0]['repeat_rule'], 'none')

                _, receipts, errors, choice = self.apply_reply(window, content)
                self.assertTrue(receipts[0].startswith('已有待办：喝水'))
                self.assertEqual(errors, [])
                self.assertIsNone(choice)
                self.assertEqual(len(window.store.pending()), 1)

                task.update(title='每日喝水', repeat='daily')
                _, receipts, errors, _ = self.apply_reply(
                    window, json.dumps({'reply': '正在处理', 'tasks': [task]}))
                self.assertTrue(receipts[0].startswith('已保存：每日喝水'))
                self.assertEqual(errors, [])
                self.assertEqual(len(window.store.pending()), 2)
                self.assertEqual(window.store.pending()[1]['repeat_rule'], 'daily')

                task['due_at'] = '2000-01-01T12:00:00+08:00'
                _, receipts, errors, _ = self.apply_reply(
                    window, json.dumps({'reply': '时间无效', 'tasks': [task]}))
                self.assertEqual(receipts, [])
                self.assertEqual(errors, ['请选择未来的提醒时间'])
                self.assertEqual(len(window.store.pending()), 2)

                reply, receipts, errors, choice = self.apply_reply(
                    window, '{"reply":"请提供提醒时间","tasks":[]}')
                self.assertEqual(reply, '请提供提醒时间')
                self.assertEqual((receipts, errors, choice), ([], [], None))
                self.assertEqual(len(window.store.pending()), 2)
            finally:
                window.shutting_down = True
                window.timer.stop()
                window.pet.close()
                window.tray.hide()
                window.close()
                window.store.close()
                window.deleteLater()
                QT_APP.processEvents()
