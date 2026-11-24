from qt_support import QT_APP
import base64
import importlib.util
import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from desktop_pet.secure_storage import SecretStore, SecretStorageError
from desktop_pet.startup import StartupManager, StartupError


def synthetic_protector(data, decrypt=False):
    """Test double only. Production exclusively uses Windows DPAPI."""
    return base64.b64decode(data) if decrypt else base64.b64encode(data)


class FakeRegistry:
    HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_SZ = 'user', 1, 2, 1

    def __init__(self):
        self.values = {'OtherApplication': 'keep'}

    def OpenKey(self, *args):
        return nullcontext('key')

    CreateKeyEx = OpenKey

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError()
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError()
        del self.values[name]


class WindowsAdapterTests(unittest.TestCase):
    def test_secret_roundtrip_endpoint_scope_and_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecretStore(folder, synthetic_protector, supported=True)
            self.assertEqual(store.load('https://a.example/v1'), '')
            store.save('https://a.example/v1', 'synthetic-key')
            self.assertNotIn(b'synthetic-key', store.path.read_bytes())
            self.assertEqual(store.load('https://b.example/v1'), '')
            self.assertEqual(store.load('https://a.example/v1'), 'synthetic-key')
            store.remove()
            store.remove()
            self.assertFalse(store.path.exists())

    def test_dingtalk_secret_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecretStore(folder, synthetic_protector, supported=True)
            self.assertEqual(store.load_dingtalk(), ('', ''))
            webhook = 'https://oapi.dingtalk.com/robot/send?access_token=abc'
            store.save_dingtalk(webhook, 'SEC-test')
            self.assertNotIn(b'SEC-test', (Path(folder) / 'dingtalk.dpapi').read_bytes())
            self.assertEqual(store.load_dingtalk(), (webhook, 'SEC-test'))
            with self.assertRaises(SecretStorageError):
                store.save_dingtalk(webhook, '')
            store.remove_dingtalk()
            self.assertEqual(store.load_dingtalk(), ('', ''))

    def test_tavily_secret_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecretStore(folder, synthetic_protector, supported=True)
            self.assertEqual(store.load_tavily(), '')
            store.save_tavily('tvly-synthetic')
            self.assertNotIn(b'tvly-synthetic', (Path(folder) / 'tavily-key.dpapi').read_bytes())
            self.assertEqual(store.load_tavily(), 'tvly-synthetic')
            with self.assertRaises(SecretStorageError):
                store.save_tavily('')
            store.remove_tavily()
            self.assertEqual(store.load_tavily(), '')

    def test_secret_failure_preserves_previous_file_without_plaintext_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecretStore(folder, synthetic_protector, supported=True)
            store.save('https://a.example', 'old')
            before = store.path.read_bytes()
            with patch.object(store, 'protector', side_effect=SecretStorageError('unavailable')):
                with self.assertRaises(SecretStorageError):
                    store.save('https://a.example', 'new')
            self.assertEqual(store.path.read_bytes(), before)
            store.path.write_bytes(b'corrupt')
            with self.assertRaises(SecretStorageError):
                store.load('https://a.example')
            self.assertTrue(store.path.exists())

    def test_unsupported_platform_never_saves_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SecretStore(folder, supported=False)
            with self.assertRaises(SecretStorageError):
                store.save('https://a.example', 'synthetic')
            self.assertFalse(store.path.exists())

    def test_startup_command_quotes_paths_and_only_changes_owned_value(self):
        with tempfile.TemporaryDirectory(prefix='desktop pet ') as folder:
            root = Path(folder)
            (root / 'launch.py').write_text('# test', encoding='utf-8')
            (root / 'python.exe').touch()
            (root / 'pythonw.exe').touch()
            registry = FakeRegistry()
            manager = StartupManager(root, root / 'python.exe', registry, supported=True)
            self.assertFalse(manager.enabled())
            manager.set_enabled(True)
            self.assertTrue(manager.enabled())
            command = registry.values['DesktopPet']
            self.assertIn('pythonw.exe"', command)
            self.assertIn('launch.py" --background', command)
            manager.set_enabled(False)
            manager.set_enabled(False)
            self.assertEqual(registry.values, {'OtherApplication': 'keep'})

    def test_missing_launcher_does_not_change_registry(self):
        registry = FakeRegistry()
        with tempfile.TemporaryDirectory() as folder:
            manager = StartupManager(folder, Path(folder) / 'missing.exe', registry, supported=True)
            with self.assertRaises(StartupError):
                manager.set_enabled(True)
        self.assertEqual(registry.values, {'OtherApplication': 'keep'})


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 未安装')
class ShellConfigTests(unittest.TestCase):
    def test_secret_restore_and_settings_never_store_plaintext(self):
        from desktop_pet.app import MainWindow
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            secret = SecretStore(folder, synthetic_protector, supported=True)
            secret.save('https://a.example/v1', 'synthetic-key')
            secret.save_tavily('tvly-synthetic')
            (Path(folder) / 'settings.json').write_text(json.dumps({
                'base_url': 'https://a.example/v1', 'model': 'test',
                'remember_key': True, 'theme': 'dark',
                'pet_animations': {'idle': {}},
            }), encoding='utf-8')
            startup = StartupManager(folder, Path(folder) / 'missing.exe', FakeRegistry(), supported=True)
            window = MainWindow(secret_store=secret, startup_manager=startup)
            try:
                window.timer.stop()
                self.assertEqual(window.settings['api_key'], 'synthetic-key')
                self.assertEqual(window.settings['tavily_key'], 'tvly-synthetic')
                self.assertEqual(window.secret_endpoint, 'https://a.example/v1')
                self.assertEqual(window.theme, 'dark')
                self.assertNotIn('pet_animations', window.settings)
                window.set_theme('light')
                config = json.loads((Path(folder) / 'settings.json').read_text(encoding='utf-8'))
                self.assertEqual(config['theme'], 'light')
                self.assertNotIn('api_key', config)
                self.assertNotIn('ui_shell', config)
                self.assertNotIn('sidebar_collapsed', config)
                self.assertNotIn('synthetic-key', json.dumps(config))
                self.assertNotIn('tvly-synthetic', json.dumps(config))
            finally:
                window.timer.stop()
                window.shutting_down = True
                window.pet.close()
                window.tray.hide()
                window.close()
                window.store.close()
                window.deleteLater()
                QT_APP.processEvents()

    def test_missing_secret_warns_without_plaintext_fallback(self):
        from desktop_pet.app import MainWindow
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            (Path(folder) / 'settings.json').write_text(json.dumps({
                'base_url': 'https://a.example/v1', 'model': 'test', 'remember_key': True,
            }), encoding='utf-8')
            secret = SecretStore(folder, synthetic_protector, supported=True)
            window = MainWindow(secret_store=secret, startup_manager=StartupManager(
                folder, Path(folder) / 'missing.exe', FakeRegistry(), supported=True))
            try:
                window.timer.stop()
                self.assertNotIn('api_key', window.settings)
                self.assertIn('安全密钥', window.settings_warning)
                self.assertFalse(secret.path.exists())
            finally:
                window.timer.stop()
                window.shutting_down = True
                window.pet.close()
                window.tray.hide()
                window.close()
                window.store.close()
                window.deleteLater()
                QT_APP.processEvents()


class UpdateNoticeTests(unittest.TestCase):
    def test_announce_once_and_click_navigates_to_settings(self):
        class FakeTray:
            def __init__(self):
                self.messages = []

            def isVisible(self):
                return True

            def supportsMessages(self):
                return True

            def showMessage(self, *args):
                self.messages.append(args)

        from desktop_pet.app import MainWindow
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            window = MainWindow()
            window.timer.stop()
            window.update_timer.stop()
            real_tray, window.tray = window.tray, FakeTray()
            try:
                self.assertEqual(window.update_timer.interval(), 6 * 60 * 60 * 1000)
                status = {'state': 'available', 'manifest': {'version': '9.9.9'}}
                window.announce_update(status)
                window.announce_update(status)
                self.assertEqual(len(window.tray.messages), 1)
                self.assertEqual(window.settings['update_notified_version'], '9.9.9')
                with patch.object(window, 'show_main') as show, patch.object(window.bridge, 'emit_event') as emit:
                    window.on_tray_message_clicked()
                show.assert_called_once()
                emit.assert_called_once_with('ui.navigate', {'page': 'settings'})
                with patch.object(window, 'show_main') as show_again:
                    window.on_tray_message_clicked()
                show_again.assert_not_called()
                window.settings['update_notified_version'] = ''
                window.settings['skipped_version'] = '9.9.9'
                window.announce_update(status)
                self.assertEqual(len(window.tray.messages), 1)
            finally:
                window.tray = real_tray
                window.timer.stop()
                window.update_timer.stop()
                window.shutting_down = True
                window.pet.close()
                window.tray.hide()
                window.close()
                window.store.close()
                window.deleteLater()
                QT_APP.processEvents()


if __name__ == '__main__':
    unittest.main()
