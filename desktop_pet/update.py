"""Update feed checks, verified downloads, and a detached Inno Setup updater."""
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

from .version import __version__

MANIFEST_URL = 'https://github.com/python-js/desktop-pet/releases/latest/download/latest.json'
DEFAULT_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 30
MAX_PACKAGE_BYTES = 1_500_000_000
VERSION_RE = re.compile(r'^[0-9]+(?:\.[0-9]+){0,2}$')
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
BUSY_STATES = ('checking', 'downloading', 'installing')

HELPER_SCRIPT = r'''param(
  [Parameter(Mandatory=$true)][int]$WaitForPid,
  [Parameter(Mandatory=$true)][string]$Setup,
  [Parameter(Mandatory=$true)][string]$AppExe,
  [Parameter(Mandatory=$true)][string]$LogPath
)
$ErrorActionPreference = 'Stop'
if (Get-Process -Id $WaitForPid -ErrorAction SilentlyContinue) {
  Wait-Process -Id $WaitForPid -Timeout 60 -ErrorAction SilentlyContinue
}
if (Get-Process -Id $WaitForPid -ErrorAction SilentlyContinue) { exit 2 }
try {
  $arguments = @('/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS', ('/LOG="' + $LogPath + '"'))
  $process = Start-Process -FilePath $Setup -ArgumentList $arguments -Wait -PassThru
  if ($process.ExitCode -ne 0) {
    Add-Content -Path $LogPath -Value ('installer exit code: ' + $process.ExitCode) -Encoding UTF8
  }
} catch {
  Add-Content -Path $LogPath -Value ('installer failed: ' + $_.Exception.Message) -Encoding UTF8
}
$installed = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Programs\DesktopPet\DesktopPet.exe' }
if ($installed -and (Test-Path -LiteralPath $installed)) {
  Start-Process -FilePath $installed
} else {
  Start-Process -FilePath $AppExe
}
'''


class UpdateError(ValueError):
    pass


class UpdateCancelled(Exception):
    pass


def manifest_url():
    return os.environ.get('DESKTOP_PET_UPDATE_URL') or MANIFEST_URL


def version_tuple(value):
    text = str(value or '').strip()
    if not VERSION_RE.fullmatch(text):
        raise UpdateError('版本号格式无效')
    parts = [int(part) for part in text.split('.')]
    return tuple(parts + [0] * (3 - len(parts)))


def is_newer(remote, current):
    return version_tuple(remote) > version_tuple(current)


def parse_manifest(payload):
    if not isinstance(payload, dict):
        raise UpdateError('更新清单格式无效')
    version = str(payload.get('version') or '').strip()
    version_tuple(version)
    installer = payload.get('installer')
    if not isinstance(installer, dict):
        raise UpdateError('更新清单缺少安装包信息')
    url = installer.get('url')
    if not isinstance(url, str) or not url.startswith('https://'):
        raise UpdateError('安装包地址必须是 HTTPS')
    sha256 = str(installer.get('sha256') or '').lower()
    if not SHA256_RE.fullmatch(sha256):
        raise UpdateError('安装包校验值无效')
    size = installer.get('size')
    if type(size) is not int or size <= 0 or size > MAX_PACKAGE_BYTES:
        raise UpdateError('安装包大小无效')
    min_version = payload.get('min_version')
    if min_version is not None:
        version_tuple(min_version)
    notes = payload.get('notes')
    return {
        'version': version,
        'min_version': min_version if isinstance(min_version, str) else None,
        'notes': notes[:4000] if isinstance(notes, str) else '',
        'installer': {'url': url, 'sha256': sha256, 'size': size},
        'published_at': str(payload.get('published_at') or '')[:64],
    }


def fetch_manifest(url=None, timeout=DEFAULT_TIMEOUT):
    request = urllib.request.Request(url or manifest_url(), headers={
        'User-Agent': f'DesktopPet/{__version__}',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(512 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError('尚未发布可用的更新版本') from None
        raise UpdateError(f'更新服务返回 HTTP {exc.code}') from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f'无法连接更新服务：{exc}') from None
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise UpdateError('更新清单不是有效的 JSON') from None
    return parse_manifest(payload)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def installer_path(manifest, directory):
    return Path(directory) / manifest['version'] / f"DesktopPet-{manifest['version']}-setup.exe"


def installer_ready(manifest, path):
    return bool(
        manifest and path and Path(path).is_file()
        and Path(path).stat().st_size == manifest['installer']['size']
        and sha256_file(path) == manifest['installer']['sha256']
    )


def download_installer(manifest, directory, progress=None, cancel=None):
    target = installer_path(manifest, directory)
    if installer_ready(manifest, target):
        if progress:
            progress(manifest['installer']['size'], manifest['installer']['size'])
        return target
    if cancel and cancel():
        raise UpdateCancelled()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix('.part')
    expected = manifest['installer']['size']
    request = urllib.request.Request(manifest['installer']['url'], headers={
        'User-Agent': f'DesktopPet/{__version__}',
        'Accept': 'application/octet-stream',
    })
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response, open(partial, 'wb') as handle:
            while True:
                if cancel and cancel():
                    raise UpdateCancelled()
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > expected or received > MAX_PACKAGE_BYTES:
                    raise UpdateError('安装包大小超出清单声明')
                handle.write(chunk)
                if progress:
                    progress(received, expected)
        if received != expected:
            raise UpdateError('安装包下载不完整，请重试')
        if sha256_file(partial) != manifest['installer']['sha256']:
            raise UpdateError('安装包校验失败，已丢弃下载文件')
    except UpdateCancelled:
        partial.unlink(missing_ok=True)
        raise
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f'下载失败：HTTP {exc.code}') from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f'下载失败：{exc}') from None
    partial.replace(target)
    return target


def spawn_installer(setup, app_exe, log_path):
    """Start a hidden helper that waits for this process to exit, then installs silently."""
    if sys.platform != 'win32':
        raise UpdateError('自动安装仅支持 Windows')
    setup = Path(setup)
    app_exe = Path(app_exe)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    script = log_path.parent / 'install-update.ps1'
    script.write_text(HELPER_SCRIPT, encoding='utf-8')
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    subprocess.Popen(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
         '-File', str(script), '-WaitForPid', str(os.getpid()),
         '-Setup', str(setup), '-AppExe', str(app_exe), '-LogPath', str(log_path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    return script


class UpdateManager:
    """Thread-safe state shared by the startup check, bridge jobs, and the settings page."""

    def __init__(self, root, current=None, url=None):
        self.root = Path(root)
        self.current = current or __version__
        self.url = url or manifest_url()
        self.manifest = None
        self.setup_path = None
        self.state = 'idle'
        self.error = ''
        self.received = 0
        self._lock = threading.Lock()

    def busy(self):
        with self._lock:
            return self.state in BUSY_STATES

    def status(self, skipped_version=''):
        with self._lock:
            manifest = None
            if self.manifest is not None:
                manifest = {
                    'version': self.manifest['version'],
                    'min_version': self.manifest['min_version'],
                    'notes': self.manifest['notes'],
                    'published_at': self.manifest['published_at'],
                    'installer': dict(self.manifest['installer']),
                }
            return {
                'currentVersion': self.current,
                'state': self.state,
                'manifest': manifest,
                'received': self.received,
                'total': manifest['installer']['size'] if manifest else 0,
                'error': self.error,
                'canInstall': bool(getattr(sys, 'frozen', False)),
                'skippedVersion': skipped_version or '',
            }

    def begin_check(self):
        with self._lock:
            if self.state in BUSY_STATES:
                return False
            self.state = 'checking'
            self.error = ''
            self.received = 0
            self.setup_path = None
            return True

    def check(self):
        remote = fetch_manifest(self.url)
        with self._lock:
            if is_newer(remote['version'], self.current):
                self.manifest = remote
                self.state = 'available'
            else:
                self.manifest = None
                self.state = 'latest'
            self.error = ''
            self.received = 0
            self.setup_path = None
        return self.status()

    def begin_download(self):
        with self._lock:
            if self.state in BUSY_STATES or not self.manifest:
                return False
            self.state = 'downloading'
            self.error = ''
            self.received = 0
            return True

    def download(self, progress=None, cancel=None):
        with self._lock:
            manifest = self.manifest
        if not manifest:
            raise UpdateError('没有可下载的更新')
        path = download_installer(manifest, self.root / 'updates', progress, cancel)
        with self._lock:
            self.setup_path = path
            self.state = 'ready'
            self.received = manifest['installer']['size']
            self.error = ''
        return path

    def progress(self, received, total):
        with self._lock:
            self.received = received
            self.state = 'downloading'

    def cancelled(self):
        with self._lock:
            self.state = 'available' if self.manifest else 'idle'
            self.received = 0
            self.error = ''

    def fail(self, message):
        with self._lock:
            self.state = 'error'
            self.error = str(message)

    def begin_install(self):
        with self._lock:
            if self.state != 'ready' or not self.manifest:
                return False
            self.state = 'installing'
            self.error = ''
            return True

    def ready_installer(self):
        with self._lock:
            manifest, path = self.manifest, self.setup_path
        return installer_ready(manifest, path)
