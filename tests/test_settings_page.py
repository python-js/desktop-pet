from qt_support import QT_APP
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_QT = importlib.util.find_spec('PyQt5') is not None


@unittest.skipUnless(HAS_QT, 'PyQt5 未安装')
class SettingsPageTests(unittest.TestCase):
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
        self.window.stream_timer.stop()

    def tearDown(self):
        self.window.shutting_down = True
        self.window.pet.close()
        self.window.tray.hide()
        self.window.close()
        self.window.store.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def saved(self):
        return json.loads((Path(self.temp.name) / 'settings.json').read_text(encoding='utf-8'))

    def wait_for(self, predicate):
        from PyQt5.QtTest import QTest
        for _ in range(300):
            QTest.qWait(10)
            self.app.processEvents()
            if predicate():
                return
        self.fail('等待超时')

    def test_cards_follow_layout_breakpoints_without_horizontal_scroll(self):
        from desktop_pet.ui.settings import PrefCard
        window = self.window
        window.show()
        window.tabs.setCurrentIndex(3)
        window.resize(1440, 820)
        self.app.processEvents()

        cards = window.settings_page.findChildren(PrefCard)
        self.assertEqual([card.title_label.text() for card in cards],
                         ['模型与对话', '联网搜索', '提醒与免打扰', '外观与密度', '数据与隐私', '宠物形象', '钉钉群通知'])
        self.assertTrue(all(card.conclusion.text().strip() for card in cards))
        self.assertEqual(window.settings_content.width(), 760)
        self.assertEqual(window.settings_scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(window.settings_canvas_layout.contentsMargins().left(), 32)
        self.assertTrue(all(not row._stacked for row in window._pref_rows))

        window.resize(1180, 820)
        self.app.processEvents()
        self.assertEqual(window.settings_content.width(), 760)
        self.assertEqual(window.settings_scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(window.settings_canvas_layout.contentsMargins().left(), 20)
        self.assertTrue(all(not row._stacked for row in window._pref_rows))

        window.resize(900, 820)
        self.app.processEvents()
        self.assertLessEqual(window.settings_content.width(), 820)
        self.assertEqual(window.settings_scroll.horizontalScrollBar().maximum(), 0)
        self.assertTrue(all(row._stacked for row in window._pref_rows))

    def test_changes_persist_immediately(self):
        from PyQt5.QtCore import QTime
        from desktop_pet.ui.theme import tokens
        window = self.window

        window.settings_theme_segment.set_current('dark', emit=True)
        self.assertEqual(tokens().name, 'dark')
        self.assertEqual(self.saved()['theme'], 'dark')

        window.settings_density_segment.set_current('compact', emit=True)
        self.assertEqual(window.task_density.key(), 'compact')
        self.assertEqual(self.saved()['density'], 'compact')

        window.early_nudge_check.toggle()
        window.sound_check.toggle()
        window.auto_postpone_check.toggle()
        window.dnd_switch.setChecked(False)
        window.dnd_start_edit.setTime(QTime(23, 0))
        self.app.processEvents()
        saved = self.saved()
        self.assertIs(saved['early_nudge'], False)
        self.assertIs(saved['sound_enabled'], False)
        self.assertIs(saved['auto_postpone'], True)
        self.assertIs(saved['dnd_enabled'], False)
        self.assertEqual(saved['dnd_start'], '23:00')
        self.assertEqual(window.dnd_state.text, '已关闭')

    def test_restore_defaults_keeps_secrets_and_pets(self):
        from PyQt5.QtCore import QTime
        from PyQt5.QtWidgets import QMessageBox
        window = self.window
        window.settings['api_key'] = 'keep-key'
        window.settings['remember_key'] = False
        window.key.setText('keep-key')
        window.dingtalk_webhook_input.setText('https://example.invalid/hook')
        window.set_theme('dark')
        window.set_task_density('compact')
        window.early_nudge_check.setChecked(False)
        window.sound_check.setChecked(False)
        window.auto_postpone_check.setChecked(True)
        window.dnd_switch.setChecked(False)
        window.dnd_start_edit.setTime(QTime(23, 0))

        with patch('desktop_pet.ui.settings.QMessageBox.question', return_value=QMessageBox.Yes):
            window.restore_default_settings()
        self.app.processEvents()

        self.assertEqual(window.theme, 'light')
        self.assertEqual(window.settings['density'], 'comfortable')
        self.assertEqual(window.task_density.key(), 'comfortable')
        self.assertIs(window.settings['early_nudge'], True)
        self.assertIs(window.settings['sound_enabled'], True)
        self.assertIs(window.settings['auto_postpone'], False)
        self.assertIs(window.settings['dnd_enabled'], True)
        self.assertEqual((window.settings['dnd_start'], window.settings['dnd_end']), ('22:30', '07:30'))
        self.assertEqual(window.dnd_state.text, '已开启')
        self.assertEqual(window.settings_theme_segment.key(), 'light')
        self.assertEqual(window.settings_density_segment.key(), 'comfortable')
        self.assertEqual(window.key.text(), 'keep-key')
        self.assertEqual(window.settings['api_key'], 'keep-key')
        self.assertEqual(window.dingtalk_webhook_input.text(), 'https://example.invalid/hook')
        saved = self.saved()
        self.assertEqual(saved['theme'], 'light')
        self.assertEqual(saved['density'], 'comfortable')
        self.assertNotIn('api_key', saved)

    def test_connection_test_reports_result_and_never_echoes_key(self):
        window = self.window
        window.base_url.setText('https://a.example/v1')
        window.model.setText('demo-model')
        window.key.setText('secret-key')

        with patch('desktop_pet.ui.settings.test_connection', return_value=321) as probe:
            window.test_model_connection()
            self.assertFalse(window.test_button.isEnabled())
            self.wait_for(lambda: window.test_button.isEnabled())
            sent = probe.call_args.args[0]
            self.assertEqual(sent['api_key'], 'secret-key')
        self.assertIn('连接成功', window.settings_test_status.text())
        self.assertIn('321', window.settings_test_status.text())
        self.assertNotIn('secret-key', window.settings_test_status.text())

        with patch('desktop_pet.ui.settings.test_connection', side_effect=ValueError('鉴权失败')):
            window.test_model_connection()
            self.wait_for(lambda: window.test_button.isEnabled())
        self.assertIn('鉴权失败', window.settings_test_status.text())
        self.assertNotIn('secret-key', window.settings_test_status.text())

        window.base_url.clear()
        window.model.clear()
        with patch('desktop_pet.ui.settings.test_connection') as probe:
            window.test_model_connection()
            probe.assert_not_called()
        self.assertIn('请先填写服务地址和模型', window.settings_test_status.text())

    def test_export_open_folder_and_clear_with_backup(self):
        from PyQt5.QtWidgets import QMessageBox
        window = self.window
        window.set_theme('dark')
        window.base_url.setText('https://a.example/v1')
        window.model.setText('demo-model')
        window.save_settings()
        window.store.add('要清理的事项', '2099-01-01T12:00:00+08:00')

        export = Path(self.temp.name) / 'export.json'
        with patch('desktop_pet.ui.settings.QFileDialog.getSaveFileName', return_value=(str(export), '')):
            window.export_settings_data()
        text = export.read_text(encoding='utf-8')
        payload = json.loads(text)
        self.assertEqual(payload['format'], 'desktop-pet-export')
        self.assertNotIn('api_key', text)
        self.assertNotIn('secret', text)
        self.assertEqual(len(payload['tasks']), 1)
        self.assertIn('已导出', window.data_status.text())

        with patch('desktop_pet.ui.settings.QDesktopServices.openUrl') as opener:
            window.open_data_folder()
        url = opener.call_args.args[0]
        self.assertEqual(Path(url.toLocalFile()), Path(self.temp.name))

        with patch('desktop_pet.ui.settings.QMessageBox.warning', return_value=QMessageBox.Yes) as warning:
            window.clear_settings_data()
        self.assertEqual(warning.call_count, 2)
        self.assertEqual(window.store.pending(), [])
        self.assertEqual(len(list(Path(self.temp.name).glob('*.backup-*.bak'))), 1)
        self.assertIn('备份', window.data_status.text())
        saved = self.saved()
        self.assertEqual(saved['theme'], 'dark')
        self.assertEqual(saved['base_url'], 'https://a.example/v1')

    def test_secret_fields_are_masked_and_not_written(self):
        from PyQt5.QtWidgets import QLineEdit
        window = self.window
        for field in (window.key, window.tavily_key, window.dingtalk_webhook_input,
                      window.dingtalk_secret_input):
            self.assertEqual(field.echoMode(), QLineEdit.Password)
        window.key.setText('plain-key')
        window.remember_key.setChecked(False)
        window.save_settings()
        self.assertNotIn('plain-key', (Path(self.temp.name) / 'settings.json').read_text(encoding='utf-8'))
        self.assertEqual(window.settings['api_key'], 'plain-key')

    def test_tavily_key_is_encrypted_and_toggle_persisted(self):
        window = self.window
        window.tavily_key.setText('tvly-synthetic')
        window.web_search_enabled.setChecked(True)
        window.save_web_search_settings()
        settings_text = (Path(self.temp.name) / 'settings.json').read_text(encoding='utf-8')
        self.assertNotIn('tvly-synthetic', settings_text)
        self.assertNotIn('tavily_key', settings_text)
        self.assertTrue(self.saved()['web_search_enabled'])
        self.assertNotIn(b'tvly-synthetic',
                         (Path(self.temp.name) / 'tavily-key.dpapi').read_bytes())
        self.assertEqual(window.settings['tavily_key'], 'tvly-synthetic')
        self.assertTrue(window.web_toggle.isChecked())
        window.web_search_enabled.setChecked(False)
        window.save_web_search_settings()
        self.assertFalse(self.saved()['web_search_enabled'])
        self.assertFalse(window.web_toggle.isChecked())


if __name__ == '__main__':
    unittest.main()
