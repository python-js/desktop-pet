from qt_support import QT_APP
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('PyQt5'), 'PyQt5 未安装')
class KnowledgeUiTests(unittest.TestCase):
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
                                     'knowledge_enabled': True})
        doc = Path(self.temp.name) / '差旅制度.txt'
        doc.write_text('差旅制度：一线城市住宿标准为每晚 600 元。', encoding='utf-8')
        self.window.knowledge.add_file(doc)
        self.window.update_knowledge_ui()

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

    def run_question(self, text, fake_ask):
        from PyQt5.QtTest import QTest
        with patch('desktop_pet.app.ask', side_effect=fake_ask):
            self.window.input.setPlainText(text)
            self.window.send_message()
            for _ in range(300):
                QTest.qWait(10)
                if self.window.worker is None:
                    break
        self.assertIsNone(self.window.worker)
        QTest.qWait(150)
        return self.window.history._rows[-1]

    def test_local_documents_are_injected_and_listed(self):
        calls = {}

        def fake_ask(settings, messages, on_chunk=None, cancelled=None, tasks=None, search_context=None):
            calls['context'] = search_context
            return '按《差旅制度》，一线城市每晚 600 元。'

        row = self.run_question('一线城市住宿标准是多少', fake_ask)
        self.assertIn('差旅制度', calls['context'])
        self.assertIn('600 元', calls['context'])
        self.assertIn('不得改变', calls['context'])
        self.assertFalse(row.materials.isHidden())
        self.assertIn('差旅制度.txt', row.materials.text())
        self.assertIn('600 元', row.text.toPlainText())

    def test_disabled_knowledge_is_not_searched(self):
        calls = {}

        def fake_ask(settings, messages, on_chunk=None, cancelled=None, tasks=None, search_context=None):
            calls['context'] = search_context
            return '好。'

        self.window.settings['knowledge_enabled'] = False
        self.window.update_knowledge_ui()
        self.run_question('一线城市住宿标准是多少', fake_ask)
        self.assertFalse(calls['context'])


if __name__ == '__main__':
    unittest.main()
