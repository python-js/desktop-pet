from qt_support import QT_APP
import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('PyQt5'), 'PyQt5 未安装')
class WebSearchUiTests(unittest.TestCase):
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
        self.window.settings.update({'model': 'test', 'base_url': 'https://example.invalid/v1',
                                     'tavily_key': 'tvly-test', 'web_search_enabled': True})
        self.window.update_web_search_ui()

    def tearDown(self):
        if self.window.worker:
            self.window.worker.cancel()
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

    def wait_finished(self):
        from PyQt5.QtTest import QTest
        for _ in range(300):
            QTest.qWait(10)
            if self.window.worker is None:
                break
        self.assertIsNone(self.window.worker)

    def test_search_runs_for_realtime_question_and_sources_are_shown(self):
        from PyQt5.QtTest import QTest
        calls = {}

        def fake_search(api_key, query, cancelled=None, **kwargs):
            calls['query'] = query
            return {'answer': '今日金价小幅上涨。',
                    'results': [{'title': '金价行情', 'url': 'https://example.com/gold',
                                 'content': '最新报价 100 元'}]}

        def fake_ask(settings, messages, on_chunk=None, cancelled=None, tasks=None, search_context=None):
            calls['context'] = search_context
            return '金价小幅上涨。'

        with patch('desktop_pet.app.websearch.tavily_search', side_effect=fake_search), \
                patch('desktop_pet.app.ask', side_effect=fake_ask):
            self.window.input.setPlainText('帮我查一下最新金价')
            self.window.send_message()
            self.wait_finished()
        QTest.qWait(150)
        self.assertEqual(calls['query'], '帮我查一下最新金价')
        self.assertIn('金价行情', calls['context'])
        self.assertIn('不得改变', calls['context'])
        row = self.window.history._rows[-1]
        self.assertFalse(row.sources.isHidden())
        self.assertIn('https://example.com/gold', row.sources.text())
        self.assertIn('金价小幅上涨', row.text.toPlainText())

    def test_task_wording_skips_search(self):
        calls = {}

        def fake_ask(settings, messages, on_chunk=None, cancelled=None, tasks=None, search_context=None):
            calls['context'] = search_context
            return '已记录。'

        with patch('desktop_pet.app.websearch.tavily_search') as search, \
                patch('desktop_pet.app.ask', side_effect=fake_ask):
            self.window.input.setPlainText('明天15:00提醒我交报告')
            self.window.send_message()
            self.wait_finished()
            search.assert_not_called()
        self.assertFalse(calls['context'])

    def test_toggle_disabled_without_key_and_persists_choice(self):
        self.assertTrue(self.window.web_toggle.isChecked())
        self.window.web_toggle.setChecked(False)
        self.assertFalse(self.window.settings['web_search_enabled'])
        self.window.settings['tavily_key'] = ''
        self.window.update_web_search_ui()
        self.assertFalse(self.window.web_toggle.isEnabled())
        self.assertFalse(self.window.web_toggle.isChecked())


if __name__ == '__main__':
    unittest.main()
