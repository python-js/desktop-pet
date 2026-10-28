from qt_support import QT_APP
"""Regeneration branches preserve source history, drafts, and task state."""
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from desktop_pet.core import TaskStore


class RegenerationStoreTests(unittest.TestCase):
    def test_branch_keeps_only_context_before_latest_answer(self):
        store = TaskStore(':memory:')
        try:
            store.add_message('user', 'first')
            store.add_message('assistant', 'first reply')
            store.add_message('user', 'second')
            store.add_message('assistant', 'old second reply')
            store.add_message('assistant', 'saved task notice')
            store.save_input('default', 'unsent')
            store.save_draft('draft', '2099-01-01T12:00:00Z')
            before = store.messages()
            branch = store.branch_for_regeneration('default')
            self.assertEqual(store.messages(session_id=branch), before[:3])
            self.assertEqual(store.messages(), before)
            self.assertEqual(store.session('default')['input_text'], 'unsent')
            self.assertEqual(store.session(branch)['input_text'], '')
            self.assertEqual(store.drafts(branch), [])
            self.assertEqual(len(store.drafts('default')), 1)
            self.assertEqual(store.pending(), [])
        finally:
            store.close()

    def test_unanswered_latest_question_is_not_regeneratable(self):
        store = TaskStore(':memory:')
        try:
            for role, text in [('user', 'old'), ('assistant', 'reply'), ('user', 'unanswered')]:
                store.add_message(role, text)
            self.assertEqual(store.regeneration_context('default'), [])
            with self.assertRaises(ValueError):
                store.branch_for_regeneration('default')
            self.assertEqual(len(store.sessions()), 1)
        finally:
            store.close()

    def test_branch_context_bounded_and_persistent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'test.db')
            store = TaskStore(path)
            for i in range(25):
                store.add_message('user', str(i))
                store.add_message('assistant', 'answer ' + str(i))
            branch = store.branch_for_regeneration('default')
            self.assertEqual(len(store.messages(session_id=branch)), 20)
            store.close()
            store = TaskStore(path)
            try:
                self.assertEqual(store.messages(session_id=branch)[-1]['content'], '24')
                self.assertEqual(store.messages()[-1]['content'], 'answer 24')
            finally:
                store.close()


class RegenerationUiTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow
        self.app = QApplication.instance() or QApplication([])
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': self.temp.name})
        self.env.start()
        self.window = MainWindow()
        self.window.timer.stop()
        self.gate = threading.Event()
        self.window.settings.update(model='test', base_url='https://example.com/v1')
        self.window.store.add_message('user', 'question')
        self.window.on_reply('{"reply":"original reply","tasks":[{"title":"original draft","due_at":"2099-01-01T12:00:00Z"}]}')
        self.window.input.setPlainText('unsent original')
        self.window.update_request_status()

    def tearDown(self):
        self.gate.set()
        if self.window.worker:
            self.window.worker.wait(3000)
            self.app.processEvents()
        self.window.shutting_down = True
        self.window.timer.stop()
        self.window.task_refresh_timer.stop()
        self.window.pet.close()
        self.window.tray.hide()
        self.window.close()
        self.window.store.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.env.stop()
        self.temp.cleanup()

    def wait_finished(self):
        from PyQt5.QtTest import QTest
        for _ in range(200):
            QTest.qWait(10)
            if self.window.worker is None:
                break
        self.assertIsNone(self.window.worker)

    def test_success_result_stays_in_branch_when_browsing_source(self):
        def delayed(settings, messages, *args):
            self.gate.wait(2)
            return '{"reply":"another reply","tasks":[]}'
        self.assertTrue(self.window.regenerate_button.isEnabled())
        with patch('desktop_pet.app.ask', side_effect=delayed) as ask:
            self.window.regenerate_reply()
            branch = self.window.active_session
            self.assertNotEqual(branch, 'default')
            self.assertFalse(self.window.regenerate_button.isEnabled())
            self.window.session_combo.setCurrentIndex(self.window.session_combo.findData('default'))
            self.gate.set()
            self.wait_finished()
            self.assertEqual(ask.call_args.args[1], [{'role': 'user', 'content': 'question'}])
        self.assertEqual(self.window.store.messages(session_id=branch)[-1]['content'], 'another reply')
        self.assertIn('已保存：original draft', self.window.store.messages()[-1]['content'])
        self.assertEqual(self.window.input.toPlainText(), 'unsent original')
        self.assertEqual(len(self.window.store.drafts('default')), 0)
        self.assertEqual(len(self.window.store.pending()), 1)
        self.assertNotIn('another reply', self.window.history.toPlainText())

    def test_failure_retry_no_duplicate_question_or_source_changes(self):
        with patch('desktop_pet.app.ask', side_effect=ValueError('test failure')):
            self.window.regenerate_reply()
            self.wait_finished()
        branch = self.window.active_session
        self.assertEqual(self.window.store.messages(session_id=branch), [{'role': 'user', 'content': 'question'}])
        self.assertIsNotNone(self.window.retry_messages)
        with patch('desktop_pet.app.ask', return_value='{"reply":"retry success","tasks":[]}'):
            self.window.retry_request()
            self.wait_finished()
        self.assertEqual(len(self.window.store.messages(session_id=branch)), 2)
        self.assertIn('已保存：original draft', self.window.store.messages()[-1]['content'])
        self.assertEqual(len(self.window.store.drafts('default')), 0)

    def test_stop_preserves_original_and_disables_local_mode(self):
        def delayed(*args):
            self.gate.wait(2)
            return '{"reply":"discard this","tasks":[]}'
        with patch('desktop_pet.app.ask', side_effect=delayed):
            self.window.regenerate_reply()
            branch = self.window.active_session
            self.window.stop_request()
            self.gate.set()
            self.wait_finished()
        self.assertEqual(len(self.window.store.messages(session_id=branch)), 1)
        self.assertIn('已保存：original draft', self.window.store.messages()[-1]['content'])
        self.window.settings['model'] = ''
        self.window.update_request_status()
        count = len(self.window.store.sessions())
        self.window.regenerate_reply()
        self.assertEqual(len(self.window.store.sessions()), count)
        self.assertFalse(self.window.regenerate_button.isEnabled())
