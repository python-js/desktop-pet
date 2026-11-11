"""tasks.* / drafts.*: JSON adapters over TaskStore; no business rules live here.

Every mutation broadcasts `tasks.changed` so the HTML pages can re-pull lists.
"""
from ..bridge import BridgeError
from ..core import parse_due, parse_due_text, utc_now


def _store(host):
    store = getattr(host.context.get('window'), 'store', None)
    if store is None:
        raise BridgeError('数据存储不可用', code='NOT_AVAILABLE')
    return store


def _task(store, task_id):
    row = store.db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    if row is None:
        raise BridgeError('待办不存在', code='NOT_FOUND')
    return dict(row)


def _refresh(host, reason):
    host.emit_event('tasks.changed', {'reason': reason})


def _after_action(host, window, task_id):
    window.dismiss_reminder(task_id)
    _refresh(host, 'action')


def handle(action, args, host):
    store = _store(host)
    window = host.context['window']
    if action == 'list':
        return [dict(row) for row in store.pending()]
    if action == 'history':
        status = str(args.get('status') or 'done')
        try:
            rows = store.history(status, str(args.get('search') or ''))
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        return [dict(row) for row in rows]
    if action == 'add':
        title = args.get('title')
        due_at = args.get('dueAt')
        repeat = str(args.get('repeat') or 'none')
        try:
            task_id = store.add(title, due_at, repeat=repeat,
                                dingtalk=bool(args.get('dingtalk')),
                                note=str(args.get('note') or ''))
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        _refresh(host, 'add')
        return _task(store, task_id)
    if action == 'edit':
        task_id = str(args.get('id') or '')
        row = _task(store, task_id)
        due_at = args.get('dueAt', row['due_at'])
        if 'dueAt' not in args and parse_due(row['due_at']) <= utc_now():
            raise BridgeError('该待办已逾期，请同时给出新的提醒时间')
        try:
            store.edit(task_id, args.get('title', row['title']), due_at,
                       repeat=args.get('repeat', row['repeat_rule']),
                       dingtalk=args.get('dingtalk', bool(row['dingtalk'])))
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        _after_action(host, window, task_id)
        return _task(store, task_id)
    if action == 'complete':
        task_id = str(args.get('id') or '')
        _task(store, task_id)
        next_id = store.complete(task_id)
        _after_action(host, window, task_id)
        return {'nextId': next_id}
    if action == 'reopen':
        task_id = str(args.get('id') or '')
        _task(store, task_id)
        try:
            store.reopen(task_id)
        except ValueError as exc:
            raise BridgeError(str(exc), code='CONFLICT') from None
        _refresh(host, 'reopen')
        return {}
    if action == 'delete':
        task_id = str(args.get('id') or '')
        _task(store, task_id)
        store.delete(task_id)
        _after_action(host, window, task_id)
        return {}
    if action == 'undoDelete':
        task_id = str(args.get('id') or '')
        store.undo_delete(task_id)
        _refresh(host, 'undoDelete')
        return {}
    if action == 'snooze':
        task_id = str(args.get('id') or '')
        minutes = args.get('minutes', 10)
        if not isinstance(minutes, int) or not 1 <= minutes <= 1440:
            raise BridgeError('顺延分钟数需要是 1–1440 的整数')
        _task(store, task_id)
        store.snooze(task_id, minutes=minutes)
        _after_action(host, window, task_id)
        return {}
    if action == 'setDingtalk':
        task_id = str(args.get('id') or '')
        _task(store, task_id)
        store.set_dingtalk(task_id, bool(args.get('enabled')))
        _refresh(host, 'setDingtalk')
        return {}
    if action == 'muteToday':
        task_id = str(args.get('id') or '')
        _task(store, task_id)
        muted = store.mute_today(task_id)
        _after_action(host, window, task_id)
        return {'mutedUntil': muted}
    if action == 'stats':
        return store.today_stats()
    if action == 'todayEvents':
        return store.today_events()
    if action == 'parseDue':
        try:
            parsed = parse_due_text(str(args.get('text') or ''))
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        parsed['past'] = parse_due(parsed['dueAt']) <= utc_now()
        return parsed
    if action == 'dismissReminder':
        task_id = str(args.get('id') or '')
        close = getattr(window, 'close_web_reminder', None)
        postponed = bool(close(task_id, bool(args.get('postpone', True)))) if close else False
        _refresh(host, 'autoPostpone' if postponed else 'reminderDismissed')
        return {'postponed': postponed}
    raise BridgeError(f'未知方法: tasks.{action}', code='NOT_FOUND')


def handle_drafts(action, args, host):
    store = _store(host)
    if action == 'list':
        session_id = args.get('sessionId')
        return [dict(row) for row in store.drafts(session_id)]
    if action == 'save':
        try:
            draft_id = store.save_draft(
                args.get('title'), args.get('dueAt'),
                draft_id=args.get('id'), session_id=str(args.get('sessionId') or 'default'),
                repeat=str(args.get('repeat') or 'none'), note=str(args.get('note') or ''))
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        _refresh(host, 'draftSave')
        return {'id': draft_id}
    if action == 'confirm':
        try:
            task_id = store.confirm_draft(str(args.get('id') or ''))
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        _refresh(host, 'draftConfirm')
        return {'taskId': task_id}
    if action == 'discard':
        store.discard_draft(str(args.get('id') or ''))
        _refresh(host, 'draftDiscard')
        return {}
    raise BridgeError(f'未知方法: drafts.{action}', code='NOT_FOUND')
