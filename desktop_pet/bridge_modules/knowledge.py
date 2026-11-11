"""knowledge.*: knowledge-base reads, remove/clear, and import/rebuild jobs with progress events."""
import sqlite3
import threading
from pathlib import Path

from ..assistant import RequestCancelled
from ..bridge import BridgeError


def handle(action, args, host):
    window = host.context['window']
    knowledge = window.knowledge
    if action == 'documents':
        return {'documents': list(knowledge.documents())}
    if action == 'stats':
        return knowledge.stats()
    if action == 'search':
        query = str(args.get('query') or '').strip()
        if not query:
            raise BridgeError('query 不能为空')
        return {'hits': list(knowledge.search(query))}
    if action == 'remove':
        doc_id = args.get('docId')
        if not isinstance(doc_id, str) or not doc_id:
            raise BridgeError('docId 不能为空')
        try:
            knowledge.remove(doc_id)
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise BridgeError(f'移除失败：{exc}') from None
        return {}
    if action == 'clear':
        try:
            knowledge.clear()
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise BridgeError(f'清空失败：{exc}') from None
        return {}
    if action in ('importPaths', 'rebuild'):
        if action == 'rebuild':
            try:
                paths = [doc['source_path'] for doc in knowledge.documents()
                         if Path(doc['source_path']).is_file()]
            except (OSError, ValueError, sqlite3.Error):
                paths = []
            if not paths:
                raise BridgeError('没有可重建的资料：原始文件已被移动或删除。')
        else:
            paths = args.get('paths')
            if not isinstance(paths, list) or not paths:
                raise BridgeError('paths 必须是非空数组')
        return _spawn_import(host, window, [str(p) for p in paths], force=action == 'rebuild')
    raise BridgeError(f'未知方法: knowledge.{action}', code='NOT_FOUND')


def _spawn_import(host, window, paths, force):
    if getattr(window, '_bridge_kb_busy', False):
        raise BridgeError('已有导入任务在进行，请等待完成或取消。', code='CONFLICT')
    job_id, cancel_event = host.create_job()
    window._bridge_kb_busy = True
    settings = dict(window.settings)

    def progress(message):
        host.emit_event('knowledge.jobProgress', {'jobId': job_id, 'message': str(message)})

    def work():
        added = updated = skipped = failed = 0
        errors, cancelled = [], False
        try:
            for path in paths:
                if cancel_event.is_set():
                    cancelled = True
                    break
                try:
                    if Path(path).is_dir():
                        results = window.knowledge.add_folder(path, settings, progress,
                                                               cancel_event.is_set, force=force)
                    else:
                        results = [window.knowledge.add_file(path, settings, progress,
                                                              cancel_event.is_set, force=force)]
                except RequestCancelled:
                    cancelled = True
                    break
                except (OSError, ValueError) as exc:
                    failed += 1
                    if len(errors) < 3:
                        errors.append(f'{Path(path).name}：{exc}')
                    continue
                for item in results:
                    status = item.get('status')
                    if status == 'added':
                        added += 1
                    elif status == 'updated':
                        updated += 1
                    elif status == 'skipped':
                        skipped += 1
                    else:
                        failed += 1
                    if item.get('error') and len(errors) < 3:
                        errors.append(f'{item.get("name")}：{item["error"]}')
                    elif item.get('wiki_error') and len(errors) < 3:
                        errors.append(f'{item.get("name")}：Wiki 未生成（{item["wiki_error"]}）')
        finally:
            window._bridge_kb_busy = False
            host.finish_job(job_id)
        host.emit_event('knowledge.jobDone', {
            'jobId': job_id, 'cancelled': cancelled, 'added': added, 'updated': updated,
            'skipped': skipped, 'failed': failed,
            'message': ('导入已取消：' if cancelled else '导入完成：')
                       + f'新增 {added}，更新 {updated}，跳过 {skipped}，失败 {failed}。'
                       + (' ' + '；'.join(errors) if errors else ''),
        })

    threading.Thread(target=work, daemon=True).start()
    return {'jobId': job_id}
