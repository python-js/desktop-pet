import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_pet import update


def manifest_for(payload, url='https://example.com/DesktopPet-setup.exe'):
    return {
        'version': '9.9.9',
        'min_version': None,
        'notes': '',
        'published_at': '',
        'installer': {
            'url': url,
            'sha256': hashlib.sha256(payload).hexdigest(),
            'size': len(payload),
        },
    }


class VersionTests(unittest.TestCase):
    def test_numeric_version_comparison(self):
        self.assertTrue(update.is_newer('0.33.0', '0.32.0'))
        self.assertTrue(update.is_newer('0.32.10', '0.32.9'))
        self.assertFalse(update.is_newer('0.32.0', '0.32.0'))
        self.assertFalse(update.is_newer('0.9.0', '0.10.0'))
        with self.assertRaises(update.UpdateError):
            update.version_tuple('v0.32.0')


class ManifestTests(unittest.TestCase):
    def test_parse_manifest_requires_https_and_valid_hash(self):
        payload = {
            'version': '0.33.0',
            'installer': {'url': 'https://example.com/a.exe',
                          'sha256': 'a' * 64, 'size': 1024},
            'notes': 'hello',
        }
        parsed = update.parse_manifest(payload)
        self.assertEqual(parsed['version'], '0.33.0')
        self.assertEqual(parsed['installer']['size'], 1024)
        with self.assertRaises(update.UpdateError):
            update.parse_manifest({**payload, 'installer': {**payload['installer'],
                                                            'url': 'http://example.com/a.exe'}})
        with self.assertRaises(update.UpdateError):
            update.parse_manifest({**payload, 'installer': {**payload['installer'],
                                                            'sha256': 'nope'}})
        with self.assertRaises(update.UpdateError):
            update.parse_manifest({**payload, 'version': '0.33.0-beta'})


class DownloadTests(unittest.TestCase):
    def test_download_verifies_hash_and_reuses_verified_file(self):
        payload = b'installer-bytes' * 1000
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.exe'
            source.write_bytes(payload)
            manifest = manifest_for(payload, source.as_uri())
            calls = []
            target = update.download_installer(manifest, Path(folder) / 'updates',
                                               lambda done, total: calls.append((done, total)))
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(calls[-1], (len(payload), len(payload)))
            self.assertTrue(update.installer_ready(manifest, target))
            again = update.download_installer(manifest, Path(folder) / 'updates')
            self.assertEqual(again, target)

    def test_bad_hash_discards_download(self):
        payload = b'real-bytes'
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.exe'
            source.write_bytes(payload)
            manifest = manifest_for(payload, source.as_uri())
            manifest['installer']['sha256'] = 'b' * 64
            with self.assertRaises(update.UpdateError):
                update.download_installer(manifest, Path(folder) / 'updates')
            target = update.installer_path(manifest, Path(folder) / 'updates')
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.part').exists())

    def test_cancel_removes_partial_file(self):
        payload = b'x' * 4096
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.exe'
            source.write_bytes(payload)
            manifest = manifest_for(payload, source.as_uri())
            with self.assertRaises(update.UpdateCancelled):
                update.download_installer(manifest, Path(folder) / 'updates',
                                          cancel=lambda: True)
            target = update.installer_path(manifest, Path(folder) / 'updates')
            self.assertFalse(target.with_suffix('.part').exists())


class SpawnTests(unittest.TestCase):
    def test_helper_avoids_detached_process(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(update.subprocess, 'Popen') as popen:
            update.spawn_installer(Path(folder) / 'setup.exe', Path(folder) / 'app.exe',
                                   Path(folder) / 'install.log')
            flags = popen.call_args.kwargs['creationflags']
            self.assertFalse(flags & getattr(update.subprocess, 'DETACHED_PROCESS', 0))
            self.assertTrue(flags & getattr(update.subprocess, 'CREATE_NO_WINDOW', 0))


class ManagerTests(unittest.TestCase):
    def test_check_marks_available_and_busy_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = update.UpdateManager(folder, current='0.32.0')
            remote = manifest_for(b'setup')
            self.assertTrue(manager.begin_check())
            self.assertFalse(manager.begin_check())
            with patch.object(update, 'fetch_manifest', return_value=remote):
                status = manager.check()
            self.assertEqual(status['state'], 'available')
            self.assertEqual(status['manifest']['version'], '9.9.9')
            self.assertFalse(status['canInstall'])
            self.assertTrue(manager.begin_download())
            self.assertFalse(manager.begin_download())
            manager.fail('network down')
            self.assertEqual(manager.status()['state'], 'error')
            self.assertEqual(manager.status()['error'], 'network down')

    def test_check_reports_latest_without_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = update.UpdateManager(folder, current='0.32.0')
            manager.begin_check()
            with patch.object(update, 'fetch_manifest', return_value=manifest_for(b'setup') | {'version': '0.31.0'}):
                status = manager.check()
            self.assertEqual(status['state'], 'latest')
            self.assertIsNone(status['manifest'])


if __name__ == '__main__':
    unittest.main()
