"""Publish a built installer and latest.json as a GitHub Release (requires GITHUB_TOKEN)."""
import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_pet.version import __version__

REPO = 'python-js/desktop-pet'
API = f'https://api.github.com/repos/{REPO}'


def request_json(method, url, token, payload=None, raw=None, content_type='application/octet-stream', timeout=60):
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'DesktopPet-release',
    }
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    else:
        body = raw
        headers['Content-Type'] = content_type
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read()
    return json.loads(text) if text else {}


def find_installer(version):
    candidates = sorted((ROOT / 'dist').glob(f'windows-{version}-*/DesktopPet-{version}-setup.exe'),
                        key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise SystemExit(f'No installer found for {version}; run tools/build_windows.py first.')
    return candidates[-1]


def build_manifest(installer, notes):
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    manifest = {
        'version': __version__,
        'installer': {
            'url': f'https://github.com/{REPO}/releases/download/v{__version__}/{installer.name}',
            'sha256': digest,
            'size': installer.stat().st_size,
        },
        'notes': notes,
        'published_at': datetime.now(timezone.utc).isoformat(),
    }
    path = installer.parent / 'latest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return path, manifest


def upload_asset(release, path, token):
    upload_url = release['upload_url'].split('{')[0]
    query = urllib.parse.urlencode({'name': path.name})
    return request_json('POST', f'{upload_url}?{query}', token,
                        raw=path.read_bytes(), timeout=600)


def main():
    parser = argparse.ArgumentParser(description='Publish the DesktopPet installer to GitHub Releases.')
    parser.add_argument('--notes', default='', help='release notes')
    parser.add_argument('--notes-file', type=Path, help='read release notes from a UTF-8 file')
    parser.add_argument('--branch', default='revision', help='commitish used when creating the tag')
    parser.add_argument('--dry-run', action='store_true', help='only write latest.json next to the installer')
    args = parser.parse_args()

    notes = args.notes
    if args.notes_file:
        notes = args.notes_file.read_text(encoding='utf-8')
    notes = notes.strip() or f'DesktopPet {__version__}'
    installer = find_installer(__version__)
    manifest_path, manifest = build_manifest(installer, notes)
    print(f'Installer: {installer}\nManifest: {manifest_path}')
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise SystemExit('GITHUB_TOKEN is required to publish a release.')
    release = request_json('POST', f'{API}/releases', token, {
        'tag_name': f'v{__version__}',
        'name': f'v{__version__}',
        'body': notes,
        'draft': True,
        'prerelease': False,
        'target_commitish': args.branch,
    })
    print(f'Draft release: {release["html_url"]}')
    try:
        upload_asset(release, installer, token)
        upload_asset(release, manifest_path, token)
        published = request_json('PATCH', f'{API}/releases/{release["id"]}', token, {'draft': False})
    except Exception:
        print(f'Draft release kept for inspection: {release["html_url"]}', file=sys.stderr)
        raise
    print(f'Published: {published["html_url"]}\nManifest URL: '
          f'https://github.com/{REPO}/releases/latest/download/latest.json')


if __name__ == '__main__':
    main()
