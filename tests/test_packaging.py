import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from desktop_pet.startup import StartupManager, StartupError

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_frozen_startup_uses_exe_without_python_launcher(self):
        with tempfile.TemporaryDirectory(prefix='desktop pet ') as folder:
            exe = Path(folder) / 'DesktopPet.exe'
            exe.touch()
            manager = StartupManager(folder, exe, supported=True, frozen=True)
            command = manager.command()
            self.assertIn('DesktopPet.exe" --background', command)
            self.assertNotIn('launch.py', command)
            exe.unlink()
            with self.assertRaises(StartupError):
                manager.command()

    def test_source_version_and_smoke_test_do_not_create_user_data(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'report.json'
            data = Path(folder) / 'should-not-be-created'
            env = dict(os.environ, DESKTOP_PET_DATA_DIR=str(data))
            version = subprocess.run([sys.executable, str(ROOT / 'launch.py'), '--version'],
                                     capture_output=True, text=True, check=True, env=env)
            from desktop_pet.version import __version__
            self.assertEqual(version.stdout.strip(), __version__)
            subprocess.run([sys.executable, str(ROOT / 'launch.py'), '--smoke-test', str(report)],
                           check=True, env=env, capture_output=True, timeout=30)
            result = json.loads(report.read_text(encoding='utf-8'))
            self.assertTrue(result['ok'])
            self.assertEqual(result['checks'], ['qt-offscreen', 'sqlite', 'pet-image', 'pet3d-assets'])
            self.assertFalse(data.exists())

    def test_build_command_has_explicit_entry_output_and_no_source_data(self):
        spec = importlib.util.spec_from_file_location('build_windows', ROOT / 'tools' / 'build_windows.py')
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'dist'
            command = build.build_command(output, Path(folder) / 'work')
            self.assertIn('--windowed', command)
            self.assertIn('--onedir', command)
            self.assertEqual(command[-1], str(ROOT / 'launch.py'))
            data_index = command.index('--add-data')
            self.assertTrue(command[data_index + 1].endswith(';desktop_pet/assets'))
            self.assertNotIn('--noconfirm', command)
            with patch.object(build.metadata, 'version', side_effect=build.metadata.PackageNotFoundError):
                with self.assertRaises(SystemExit):
                    build.main()
            self.assertFalse(output.exists())
