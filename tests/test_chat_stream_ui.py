from qt_support import QT_APP
import importlib.util
import os
import tempfile
import threading
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('PyQt5'), 'PyQt5 未安装')
class StreamingUiTests(unittest.TestCase):
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
        self.gate = threading.Event()

    def tearDown(self):
        self.gate.set()
        if self.window.worker:
            self.window.worker.wait(3000)
            self.app.processEvents()
        self.window.stream_timer.stop()
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

    def delayed(self, settings, messages, chunk, cancelled, tasks=None):
        chunk('{"reply":"partial reply')
        self.gate.wait(2)
        # Simulate a response already arriving while the user presses stop.
        return '{"reply":"complete reply","tasks":[{"title":"must not save on stop","due_at":"2099-01-01T12:00:00Z"}]}'

    def wait_finished(self):
        from PyQt5.QtTest import QTest
        for _ in range(200):
            QTest.qWait(10)
            if self.window.worker is None:
                break
        self.assertIsNone(self.window.worker)

    def test_stop_discards_partial_reply_and_task_proposals(self):
        from PyQt5.QtTest import QTest
        with patch('desktop_pet.app.ask', side_effect=self.delayed):
            self.window.input.setPlainText('test')
            self.window.send_message()
            QTest.qWait(120)
            self.assertIn('partial reply', self.window.history.toPlainText())
            self.window.stop_request()
            self.assertNotIn('partial reply', self.window.history.toPlainText())
            self.assertIn('已停止', self.window.history.toPlainText())
            self.gate.set()
            self.wait_finished()
        self.assertEqual([m['role'] for m in self.window.store.messages()], ['user'])
        self.assertEqual(self.window.store.drafts(), [])
        self.assertEqual(self.window.store.pending(), [])
        self.assertIsNotNone(self.window.retry_messages)
        self.assertTrue(self.window.send.isEnabled())

    def test_stream_placeholder_follows_original_session(self):
        from PyQt5.QtTest import QTest
        with patch('desktop_pet.app.ask', side_effect=self.delayed):
            original = self.window.active_session
            self.window.input.setPlainText('test')
            self.window.send_message()
            QTest.qWait(120)
            self.assertIn('partial reply', self.window.history.toPlainText())
            self.window.new_session()
            self.assertNotIn('partial reply', self.window.history.toPlainText())
            self.window.session_combo.setCurrentIndex(self.window.session_combo.findData(original))
            self.gate.set()
            self.wait_finished()
        self.assertTrue(self.window.store.messages()[-1]['content'].startswith('已保存：'))
        self.assertEqual(len(self.window.store.drafts()), 0)
        self.assertEqual(len(self.window.store.pending()), 1)
        self.assertIn('已保存：', self.window.history.toPlainText())

    def test_exit_waits_for_thread_before_closing_database(self):
        from PyQt5.QtTest import QTest
        with patch('desktop_pet.app.ask', side_effect=self.delayed), patch.object(self.app, 'quit') as quit_app:
            self.window.input.setPlainText('test')
            self.window.send_message()
            QTest.qWait(20)
            self.window.quit_app()
            self.assertTrue(self.window.exit_pending)
            quit_app.assert_not_called()
            self.assertEqual(len(self.window.store.messages()), 1)
            self.gate.set()
            self.wait_finished()
            quit_app.assert_called_once()


if __name__ == '__main__':
    unittest.main()
