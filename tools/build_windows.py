"""Build an isolated, unsigned Windows folder distribution and verify its runtime."""
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_pet.version import __version__

RUNTIME_PACKAGES = ('PyQt5', 'PyQt5-Qt5', 'PyQt5-sip', 'PyQt-Fluent-Widgets', 'PyQt5-Frameless-Window', 'darkdetect')


def build_command(output, work):
    return [sys.executable, '-m', 'PyInstaller', '--name', 'DesktopPet', '--windowed',
            '--onedir', '--clean', '--collect-all', 'qfluentwidgets', '--distpath', str(output), '--workpath', str(work / 'cache'),
            '--specpath', str(work), '--hidden-import', 'PyQt5.sip', str(ROOT / 'launch.py')]


def write_licenses(destination):
    destination.mkdir()
    shutil.copyfile(ROOT.parent / 'LICENSE', destination / 'PROJECT-LICENSE.txt')
    packages = []
    for name in RUNTIME_PACKAGES:
        dist = metadata.distribution(name)
        texts = []
        for entry in dist.files or []:
            if any(word in entry.name.lower() for word in ('license', 'copying', 'copyright')):
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    target_name = name + '-' + str(len(texts)) + '-' + entry.name
                    shutil.copyfile(source, destination / target_name)
                    texts.append(target_name)
        packages.append({'name': name, 'version': dist.version,
                         'license_metadata': dist.metadata.get('License', ''), 'license_files': texts})
    (destination / 'dependencies.json').write_text(json.dumps(packages, indent=2), encoding='utf-8')


def main():
    if sys.platform != 'win32' or struct.calcsize('P') != 8:
        raise SystemExit('Use 64-bit Windows Python to build this target.')
    try:
        if metadata.version('PyInstaller') != '6.16.0':
            raise SystemExit('Install the pinned build dependencies from requirements-build.txt.')
        for name in RUNTIME_PACKAGES:
            metadata.version(name)
    except metadata.PackageNotFoundError:
        raise SystemExit('Build dependencies missing. Run: .venv\\Scripts\\python.exe -m pip install -r requirements-build.txt')
    # Unique paths avoid overwriting a previous verified build. No recursive deletion.
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output = ROOT / 'dist' / f'windows-{__version__}-{stamp}'
    work = ROOT / 'build' / stamp
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    env = dict(os.environ)
    # A test environment's offscreen mode must not become the normal launch mode.
    env.pop('QT_QPA_PLATFORM', None)
    env['DESKTOP_PET_UI'] = 'fluent'
    subprocess.run(build_command(output, work), cwd=ROOT, env=env, check=True)
    application = output / 'DesktopPet'
    exe = application / 'DesktopPet.exe'
    if not exe.is_file():
        raise SystemExit('Build did not produce DesktopPet.exe; no verified release created.')
    report = output / 'smoke-test.json'
    subprocess.run([str(exe), '--smoke-test', str(report)], cwd=output, env=env,
                   check=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    result = json.loads(report.read_text(encoding='utf-8'))
    if result.get('ok') is not True or result.get('version') != __version__:
        raise SystemExit('Packaged runtime verification failed; do not distribute this build.')
    write_licenses(application / 'licenses')
    shutil.copyfile(ROOT / 'docs' / 'WINDOWS_BUILD.md', application / 'WINDOWS_BUILD.md')
    manifest = {'version': __version__, 'python': platform.python_version(),
                'architecture': platform.machine(), 'signed': False,
                'pyinstaller': metadata.version('PyInstaller'), 'smoke_test': result,
                'files': {str(path.relative_to(application)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(application.rglob('*')) if path.is_file()}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    archive = shutil.make_archive(str(output / f'DesktopPet-{__version__}-windows'), 'zip', output, 'DesktopPet')
    print(f'Verified unsigned folder build: {application}\nArchive: {archive}\nManifest: {output / "manifest.json"}')


if __name__ == '__main__':
    main()
