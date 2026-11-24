"""One-click release: preflight, key tests, build, publish and verify."""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_windows import find_iscc
from desktop_pet.version import __version__
from publish_release import find_installer

REPO = 'python-js/desktop-pet'
BRANCH = 'revision'
API = f'https://api.github.com/repos/{REPO}'
MANIFEST_URL = f'https://github.com/{REPO}/releases/latest/download/latest.json'
RELEASE_URL = f'https://github.com/{REPO}/releases/tag/v{__version__}'
USER_AGENT = 'DesktopPet-release'

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass


def say(text=''):
    print(text, flush=True)


def fail(message):
    say(f'发版中止：{message}')
    return 1


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, text=True, encoding='utf-8',
                            errors='replace', capture_output=True)
    if result.returncode:
        raise RuntimeError(f'git {" ".join(args)} 失败：{(result.stderr or result.stdout).strip()}')
    return result.stdout


def read_token():
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    if token:
        return token
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            token, _ = winreg.QueryValueEx(key, 'GITHUB_TOKEN')
    except OSError:
        return ''
    return str(token).strip()


def http_json(url, timeout=30):
    request = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT, 'Accept': 'application/vnd.github+json',
        'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read() or b'{}')


def fetch_release(version):
    try:
        return http_json(f'{API}/releases/tags/v{version}')
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(f'查询 v{version} 发布状态失败（HTTP {exc.code}），请检查网络后重试。')


def preflight():
    if sys.platform != 'win32' or struct.calcsize('P') != 8:
        return '请在 64 位 Windows 上运行。'
    venv_python = (ROOT / '.venv' / 'Scripts' / 'python.exe').resolve()
    if Path(sys.executable).resolve() != venv_python:
        return '请双击 release.cmd（使用项目虚拟环境）运行。'
    try:
        find_iscc()
    except SystemExit as exc:
        return str(exc)
    if shutil.which('npm') is None:
        return '未找到 npm，请安装 Node.js 18+。'
    try:
        git('fetch', 'origin', '--tags', '--force')
        branch = git('rev-parse', '--abbrev-ref', 'HEAD').strip()
        if branch != BRANCH:
            return f'当前分支是 {branch}，发版要求 {BRANCH}。'
        if git('rev-parse', 'HEAD').strip() != git('rev-parse', f'origin/{BRANCH}').strip():
            return f'本地提交未推送，先 push 到 origin/{BRANCH} 再发版。'
        dirty = git('status', '--porcelain').strip()
        if dirty:
            return '工作区不干净，先提交或还原改动：\n' + dirty
        if fetch_release(__version__):
            return f'v{__version__} 已发布。先修改 desktop_pet/version.py 并提交推送后再发版。'
    except (RuntimeError, urllib.error.URLError) as exc:
        return str(exc)
    if not read_token():
        return ('未找到 GITHUB_TOKEN。在 PowerShell 里执行一次：\n'
                "  [Environment]::SetEnvironmentVariable('GITHUB_TOKEN','ghp_...','User')\n"
                '然后重新双击 release.cmd。')
    return ''


def build_notes():
    notes_file = ROOT / 'docs' / 'release-notes.md'
    if notes_file.is_file():
        text = notes_file.read_text(encoding='utf-8').strip()
        if text:
            return text
    tag = ''
    try:
        tag = git('describe', '--tags', '--abbrev=0').strip()
    except RuntimeError:
        pass
    try:
        body = git('log', '--pretty=format:- %s', f'{tag}..HEAD' if tag else '-20').strip()
    except RuntimeError:
        body = ''
    return f'DesktopPet {__version__}\n\n{body or f"- DesktopPet {__version__}"}'


def run_step(title, command, **kwargs):
    say(f'== {title} ==')
    return subprocess.run(command, cwd=ROOT, **kwargs).returncode


def run_publish(notes, token):
    handle, path = tempfile.mkstemp(prefix='desktop-pet-notes-', suffix='.md')
    os.close(handle)
    try:
        Path(path).write_text(notes, encoding='utf-8')
        env = dict(os.environ, GITHUB_TOKEN=token)
        return run_step('上传并发布 Release', [sys.executable,
                                              str(ROOT / 'tools' / 'publish_release.py'),
                                              '--notes-file', path, '--branch', BRANCH], env=env)
    finally:
        Path(path).unlink(missing_ok=True)


def verify(installer):
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    size = installer.stat().st_size
    release = None
    for _ in range(12):
        release = fetch_release(__version__)
        if release and not release.get('draft'):
            break
        time.sleep(5)
    if not release or release.get('draft'):
        return '线上 Release 未就绪，请到 Releases 页面检查。'
    asset = next((item for item in release.get('assets', []) if item.get('name') == installer.name), None)
    if asset is None:
        return '线上 Release 缺少安装包资产。'
    if asset.get('size') != size:
        return f'线上安装包大小不符：{asset.get("size")} != {size}'
    if asset.get('digest') and asset['digest'] != f'sha256:{digest}':
        return '线上安装包 SHA256 不符。'
    try:
        manifest = http_json(f'https://github.com/{REPO}/releases/download/v{__version__}/latest.json',
                             timeout=60)
    except Exception as exc:
        return f'无法下载线上 latest.json：{exc}'
    installer_info = manifest.get('installer') or {}
    if (manifest.get('version') != __version__ or installer_info.get('sha256') != digest
            or installer_info.get('size') != size):
        return '线上 latest.json 与本地安装包不一致。'
    say('== 校验客户端更新地址 ==')
    fresh = False
    for _ in range(12):
        try:
            live = http_json(MANIFEST_URL, timeout=60)
            fresh = (live.get('version') == __version__
                     and (live.get('installer') or {}).get('sha256') == digest)
            if fresh:
                break
        except Exception:
            pass
        time.sleep(5)
    if not fresh:
        say('提示：latest/download/latest.json 仍是旧内容（CDN 缓存），稍后会自动刷新。')
    try:
        request = urllib.request.Request(
            f'https://github.com/{REPO}/releases/download/v{__version__}/{installer.name}',
            method='HEAD', headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            length = int(response.headers.get('Content-Length') or 0)
            if response.status != 200 or length != size:
                say(f'提示：安装包下载检查异常（HTTP {response.status}，{length} 字节）。')
    except Exception as exc:
        say(f'提示：安装包下载检查失败：{exc}')
    return ''


def main():
    say(f'DesktopPet {__version__} 发版')
    start = time.time()
    problem = preflight()
    if problem:
        return fail(problem)
    token = read_token()
    notes = build_notes()
    say('== 发布说明 ==')
    say(notes)
    if run_step('运行关键测试 tests.test_update',
                [sys.executable, '-m', 'unittest', 'tests.test_update']) != 0:
        return fail('关键测试未通过，未构建、未发布。')
    if run_step('构建安装包与自检（需要几分钟）',
                [sys.executable, str(ROOT / 'tools' / 'build_windows.py')]) != 0:
        return fail('构建或自检失败，未发布。')
    installer = find_installer(__version__)
    say(f'安装包：{installer}')
    if run_publish(notes, token) != 0:
        return fail('发布失败。若已生成 draft，请到 Releases 页面确认并删除后重试。')
    problem = verify(installer)
    if problem:
        return fail(problem)
    say()
    say(f'发版完成，用时 {time.time() - start:.1f} 秒。')
    say(f'Release: {RELEASE_URL}')
    say(f'更新清单: {MANIFEST_URL}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
