"""update.*: check the GitHub release feed, download the installer, and install it."""
from .. import update as updater
from ..bridge import BridgeError


def handle(action, args, host):
    window = host.context['window']
    manager = window.updates
    if action == 'get':
        return manager.status(window.settings.get('skipped_version', ''))
    if action == 'check':
        if not window.check_updates_async():
            raise BridgeError('正在检查或下载更新，请稍候。', code='CONFLICT')
        return {}
    if action == 'download':
        if not manager.manifest:
            raise BridgeError('没有可下载的更新', code='NOT_FOUND')
        job_id, cancel_event = host.create_job()
        if not window.download_update(job_id, cancel_event):
            host.finish_job(job_id)
            raise BridgeError('当前无法开始下载，请稍候。', code='CONFLICT')
        return {'jobId': job_id}
    if action == 'install':
        try:
            window.install_update()
        except updater.UpdateError as exc:
            raise BridgeError(str(exc), code='CONFLICT') from None
        return {}
    if action == 'skip':
        version = str(args.get('version') or '')
        if not version and manager.manifest:
            version = manager.manifest['version']
        try:
            updater.version_tuple(version)
        except updater.UpdateError:
            raise BridgeError('版本号格式无效') from None
        window.settings['skipped_version'] = version
        try:
            window.persist_settings()
        except OSError:
            raise BridgeError('跳过版本设置未能保存') from None
        host.emit_event('update.state', manager.status(version))
        return {'skippedVersion': version}
    raise BridgeError(f'未知方法: update.{action}', code='NOT_FOUND')
