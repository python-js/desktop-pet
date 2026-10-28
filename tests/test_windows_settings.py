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


@unittest.skipUnless(importlib.util.find_spec('PyQt5'), 'PyQt5 未安装')
class SettingsUiTests(unittest.TestCase):
    def test_secure_restore_disable_and_startup_are_explicit(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            secret = SecretStore(folder, synthetic_protector, supported=True)
            startup = StartupManager(folder, Path(folder) / 'missing.exe', FakeRegistry(), supported=True)
            windows = []
            try:
                window = MainWindow(secret_store=secret, startup_manager=startup)
                windows.append(window)
                window.timer.stop()
                window.base_url.setText('https://a.example/v1')
                window.model.setText('test')
                window.key.setText('synthetic-key')
                window.remember_key.setChecked(True)
                window.save_settings()
                self.assertNotIn('synthetic-key', (Path(folder) / 'settings.json').read_text(encoding='utf-8'))
                self.assertEqual(startup.registry.values, {'OtherApplication': 'keep'})
                restored = MainWindow(secret_store=secret, startup_manager=startup)
                windows.append(restored)
                restored.timer.stop()
                self.assertEqual(restored.key.text(), 'synthetic-key')
                self.assertTrue(restored.remember_key.isChecked())
                restored.base_url.setText('https://b.example/v1')
                with patch('desktop_pet.ui.settings.QMessageBox.warning') as warning:
                    restored.save_settings()
                    warning.assert_called_once()
                self.assertEqual(restored.settings['base_url'], 'https://a.example/v1')
                restored.endpoint_edited()
                self.assertEqual(restored.key.text(), '')
                restored.key.setText('new-synthetic-key')
                restored.remember_key.setChecked(False)
                restored.save_settings()
                self.assertFalse(secret.path.exists())
                self.assertEqual(restored.settings['api_key'], 'new-synthetic-key')
                config = json.loads((Path(folder) / 'settings.json').read_text(encoding='utf-8'))
                self.assertNotIn('api_key', config)
                self.assertFalse(config['remember_key'])
                with patch.object(startup, 'set_enabled') as setter:
                    restored.login_startup.setChecked(True)
                    setter.assert_not_called()
                    restored.save_startup()
                    setter.assert_called_once_with(True)
            finally:
                for window in windows:
                    window.timer.stop()
                    window.stream_timer.stop()
                    window.task_refresh_timer.stop()
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
