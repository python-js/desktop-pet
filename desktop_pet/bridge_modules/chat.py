"""chat.*: sessions, messages, assistant streaming and daily planning.

Session/message/draft rows come straight from TaskStore; the model pipeline stays
in AssistantWorker; task operations reuse the window's execute/apply methods.
The only shell-side request state (worker, stream buffer, sources) lives in
host.context['chat_state'] so the bridge survives page reloads.
"""
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Slot

from .. import websearch
from ..assistant import local_reply, plain_text, reply_preview
from ..bridge import BridgeError
from ..core import decode_response
from ..planning import daily_snapshot, local_plan, planning_prompt


def _window(host):
    window = host.context.get('window')
    if window is None:
        raise BridgeError('窗口不可用', code='NOT_AVAILABLE')
    return window


def _store(host):
    store = getattr(_window(host), 'store', None)
    if store is None:
        raise BridgeError('数据存储不可用', code='NOT_AVAILABLE')
    return store


def _configured(window):
    return bool(window.settings.get('model') and window.settings.get('base_url'))


def _ready(window, name):
    check = getattr(window, name, None)
    return bool(check()) if callable(check) else False


def _state(host):
    state = host.context.get('chat_state')
    if state is None:
        state = {'worker': None, 'job_id': None, 'session_id': None, 'model': '',
                 'started': None, 'raw': '', 'sent': '', 'timer': None,
                 'sources': [], 'knowledge': [], 'notices': [],
                 'plan': None, 'plan_session': None}
        host.context['chat_state'] = state
    return state


def _busy(host):
    return (_state(host)['worker'] is not None
            or getattr(_window(host), 'worker', None) is not None)


def _timer(host):
    state = _state(host)
    timer = state.get('timer')
    if timer is None:
        window = _window(host)
        timer = QTimer(window if isinstance(window, QObject) else None)
        timer.setInterval(100)
        timer.timeout.connect(lambda: _flush(host))
        state['timer'] = timer
    return timer


def _flush(host):
    """Push the visible part of the buffered reply as a delta (100ms cadence)."""
    state = _state(host)
    preview = reply_preview(state['raw'])
    if preview == state['sent']:
        return
    delta = preview[len(state['sent']):] if preview.startswith(state['sent']) else preview
    state['sent'] = preview
    if delta:
        host.emit_event('assistant.chunk', {'jobId': state['job_id'],
                                            'sessionId': state['session_id'],
                                            'text': delta})


def _meta(window, state):
    if not state['model'] or state['started'] is None:
        return '小满 · 本地规则'
    return f"小满 · {state['model']} · 用时 {time.monotonic() - state['started']:.1f} 秒"


def _visible(messages):
    out = []
    for message in messages:
        role, content = message['role'], message['content']
        system = role == 'system' or (role == 'assistant' and content.startswith('已保存：'))
        if role == 'assistant' and not system and content.lstrip()[:1] in ('{', '`'):
            content = decode_response(content)[0]
        elif role == 'user' and content.startswith('请根据下面的只读待办快照'):
            content = '帮我规划今天'
        out.append({'role': 'system' if system else role, 'content': content,
                    'created_at': message.get('created_at')})
    return out


def _refresh(host, reason):
    host.emit_event('tasks.changed', {'reason': reason})


def _activate(window, session_id):
    if window.active_session != session_id:
        window.active_session = session_id
    if window.settings.get('active_session') != session_id:
        window.settings['active_session'] = session_id
        persist = getattr(window, 'persist_settings', None)
        if callable(persist):
            persist()


def _session_id(host, args):
    session_id = args.get('sessionId') or _window(host).active_session
    if not isinstance(session_id, str) or not session_id:
        raise BridgeError('会话 ID 不合法')
    try:
        _store(host).session(session_id)
    except ValueError as exc:
        raise BridgeError(str(exc), code='NOT_FOUND') from None
    return session_id


def _session_event(host, session_id, reason):
    store = _store(host)
    session = store.session(session_id)
    host.emit_event('chat.changed', {'reason': reason, 'sessionId': session_id,
                                     'title': session['title'],
                                     'messageCount': store.message_count(session_id)})


def _prepare_daily_session(host, window, store):
    """Start a fresh chat on the first chat-page visit of each local day."""
    today = datetime.now().astimezone().date().isoformat()
    if window.settings.get('chat_session_day') == today:
        return

    current_id = window.active_session
    try:
        message_count = store.message_count(current_id)
    except (ValueError, KeyError):
        message_count = 0
    if message_count:
        session_id = store.create_session('新对话')
        _activate(window, session_id)
        _session_event(host, session_id, 'daily-create')
    window.settings['chat_session_day'] = today
    persist = getattr(window, 'persist_settings', None)
    if callable(persist):
        persist()


def _session_payload(host, session_id, limit):
    window = _window(host)
    store = _store(host)
    row = store.session(session_id)
    state = _state(host)
    retries = getattr(window, 'retry_by_session', {}) or {}
    choices = getattr(window, 'task_choice', {}) or {}
    return {
        'activeSession': window.active_session,
        'session': {'id': row['id'], 'title': row['title'],
                    'inputText': row['input_text'] or ''},
        'messages': _visible(store.messages(limit, session_id)),
        'drafts': [dict(draft) for draft in store.drafts(session_id)],
        'canRegenerate': _configured(window) and bool(store.regeneration_context(session_id)),
        'retryable': session_id in retries,
        'busy': state['worker'] is not None,
        'busySessionId': state['session_id'],
        'hasModel': _configured(window),
        'choicePending': session_id in choices,
    }


class _Relay(QObject):
    """Receives AssistantWorker signals on the main thread (worker runs in QThread)."""

    def __init__(self, host, worker):
        # Parented to the host (always a QObject) so the relay outlives the
        # terminal signal that arrives just before QThread.finished.
        super().__init__(host)
        self.host = host
        self.worker = worker

    def _current(self):
        return _state(self.host)['worker'] is self.worker

    @Slot(str)
    def on_chunk(self, text):
        if self._current():
            _state(self.host)['raw'] += text

    @Slot()
    def on_search_started(self):
        if self._current():
            _emit_state(self.host, 'searching')

    @Slot(object)
    def on_searched(self, sources):
        if self._current():
            state = _state(self.host)
            state['sources'] = list(sources or [])
            _emit_state(self.host, 'searching')

    @Slot(str)
    def on_search_failed(self, message):
        if self._current():
            _state(self.host)['notices'].append(message)
            _emit_state(self.host, 'responding')

    @Slot()
    def on_knowledge_started(self):
        if self._current():
            _emit_state(self.host, 'knowledge')

    @Slot(object)
    def on_knowledge_searched(self, hits):
        if self._current():
            state = _state(self.host)
            state['knowledge'] = list(hits or [])
            _emit_state(self.host, 'knowledge')

    @Slot(str)
    def on_result(self, content):
        if self._current():
            _result(self.host, self.worker, content)

    @Slot(str)
    def on_failed(self, message):
        if self._current():
            _failed(self.host, self.worker, message)

    @Slot()
    def on_stopped(self):
        if self._current():
            _stopped(self.host, self.worker)

    @Slot()
    def on_finished(self):
        _finished(self.host, self.worker)
        self.deleteLater()


def _emit_state(host, name):
    state = _state(host)
    payload = {'state': name, 'jobId': state['job_id'], 'sessionId': state['session_id']}
    if name == 'searching' and state['sources']:
        payload['sources'] = state['sources']
    if name == 'knowledge' and state['knowledge']:
        payload['knowledge'] = state['knowledge']
    host.emit_event('assistant.state', payload)


def _reset(host, worker):
    state = _state(host)
    timer = state.get('timer')
    if timer is not None:
        timer.stop()
    job_id = state['job_id']
    if job_id:
        host.finish_job(job_id)
    state.update({'worker': None, 'job_id': None, 'session_id': None, 'model': '',
                  'started': None, 'raw': '', 'sent': '', 'sources': [],
                  'knowledge': [], 'notices': [], 'plan': None, 'plan_session': None})
    state.pop('relay', None)
    window = host.context.get('window')
    if window is not None and getattr(window, 'web_chat_worker', None) is worker:
        window.web_chat_worker = None


def _deliver(host, session_id, content, job_id, meta, sources, knowledge, notices, plan):
    window = _window(host)
    store = _store(host)
    reply, tasks, errors = decode_response(content)
    receipts, errors, choice = (window.run_task_ops(tasks, session_id) if tasks
                                else ([], errors, None))
    if tasks:
        # Only application-confirmed writes may be described as successful.
        parts = list(receipts)
        if choice is not None:
            parts.append(choice['prompt'])
        reply = '\n\n'.join(parts) or '待办操作未能执行，请补充有效信息后重试。'
        _refresh(host, 'chat')
    store.add_message('assistant', reply, session_id)
    note = ''
    if errors:
        note = '部分建议未采用：' + '；'.join(errors)
        store.add_message('assistant', note, session_id)
    pet = getattr(window, 'pet', None)
    if pet is not None:
        pet.say(plain_text(reply) or reply)
    host.emit_event('assistant.result', {
        'jobId': job_id, 'sessionId': session_id, 'reply': reply,
        'tasks': receipts, 'errors': list(errors),
        'choice': choice['prompt'] if choice else None, 'note': note,
        'sources': sources, 'knowledge': knowledge, 'notices': notices, 'meta': meta,
    })
    host.emit_event('assistant.state', {'state': 'idle', 'jobId': job_id,
                                        'sessionId': session_id})
    _session_event(host, session_id, 'result')
    if plan is not None:
        host.emit_event('plan.result', {'snapshot': plan, 'reply': reply,
                                        'jobId': job_id, 'sessionId': session_id})


def _result(host, worker, content):
    state = _state(host)
    _flush(host)
    job_id, session_id = state['job_id'], state['session_id']
    meta = _meta(_window(host), state)
    sources, knowledge = list(state['sources']), list(state['knowledge'])
    notices, plan = list(state['notices']), state['plan']
    _reset(host, worker)
    _deliver(host, session_id, content, job_id, meta, sources, knowledge, notices, plan)


def _failed(host, worker, message):
    state = _state(host)
    session_id, job_id = state['session_id'], state['job_id']
    window = _window(host)
    retries = getattr(window, 'retry_by_session', None)
    if isinstance(retries, dict) and session_id is not None:
        retries[session_id] = list(worker.messages)
    _reset(host, worker)
    host.emit_event('assistant.failed', {'jobId': job_id, 'sessionId': session_id,
                                         'message': message, 'retryable': True})
    host.emit_event('assistant.state', {'state': 'failed', 'jobId': job_id,
                                        'sessionId': session_id})


def _stopped(host, worker):
    state = _state(host)
    session_id, job_id = state['session_id'], state['job_id']
    window = _window(host)
    retries = getattr(window, 'retry_by_session', None)
    if isinstance(retries, dict) and session_id is not None:
        retries[session_id] = list(worker.messages)
    _reset(host, worker)
    host.emit_event('assistant.state', {'state': 'stopped', 'jobId': job_id,
                                        'sessionId': session_id})


def _finished(host, worker):
    state = _state(host)
    if state['worker'] is worker:
        # Defensive: the thread ended without a terminal signal.
        _reset(host, worker)
        host.emit_event('assistant.state', {'state': 'stopped'})
    try:
        worker.deleteLater()
    except RuntimeError:
        pass
    window = host.context.get('window')
    if window is None:
        return
    if getattr(window, 'web_chat_worker', None) is worker:
        window.web_chat_worker = None
    if (getattr(window, 'exit_pending', False)
            and getattr(window, 'web_chat_worker', None) is None
            and getattr(window, 'worker', None) is None):
        quit_app = getattr(window, 'quit_app', None)
        if callable(quit_app):
            quit_app()


def _start(host, session_id, messages, web_query=None, knowledge_query=None,
           plan_snapshot=None):
    window = _window(host)
    settings = window.settings
    if _busy(host):
        raise BridgeError('上一条回复还在进行中，请稍候', code='CONFLICT')
    if web_query is None or knowledge_query is None:
        last = next((m.get('content', '') for m in reversed(messages)
                     if m.get('role') == 'user'), '')
        if web_query is None:
            web_query = (last if (_ready(window, 'web_search_ready')
                                  and settings.get('web_search_enabled', True)
                                  and websearch.wants_web_search(last)) else '')
        if knowledge_query is None:
            knowledge_query = (last if (_ready(window, 'knowledge_ready')
                                        and settings.get('knowledge_enabled', True)) else '')
    tasks = [dict(row) for row in _store(host).pending()]
    factory = host.context.get('worker_factory')
    if factory is None:
        from ..app import AssistantWorker
        factory = AssistantWorker
    parent = window if isinstance(window, QObject) else None
    worker = factory(settings, messages, tasks, parent, web_query,
                     getattr(window, 'knowledge', None), knowledge_query)
    job_id, _ = host.create_job()
    state = _state(host)
    state.update({'worker': worker, 'job_id': job_id, 'session_id': session_id,
                  'model': settings.get('model') if _configured(window) else '',
                  'started': time.monotonic(), 'raw': '', 'sent': '',
                  'sources': [], 'knowledge': [], 'notices': [],
                  'plan': plan_snapshot,
                  'plan_session': session_id if plan_snapshot is not None else None})
    choices = getattr(window, 'task_choice', None)
    if isinstance(choices, dict):
        choices.pop(session_id, None)
    relay = _Relay(host, worker)
    state['relay'] = relay
    worker.chunk.connect(relay.on_chunk)
    worker.search_started.connect(relay.on_search_started)
    worker.searched.connect(relay.on_searched)
    worker.search_failed.connect(relay.on_search_failed)
    worker.knowledge_started.connect(relay.on_knowledge_started)
    worker.knowledge_searched.connect(relay.on_knowledge_searched)
    worker.result.connect(relay.on_result)
    worker.failed.connect(relay.on_failed)
    worker.stopped.connect(relay.on_stopped)
    worker.finished.connect(relay.on_finished)
    window.web_chat_worker = worker
    _timer(host).start()
    host.emit_event('assistant.state', {'state': 'responding', 'jobId': job_id,
                                        'sessionId': session_id})
    worker.start()
    return job_id


def _local_exchange(host, session_id, content, plan_snapshot=None):
    window = _window(host)
    job_id, _ = host.create_job()
    state = _state(host)
    state.update({'job_id': job_id, 'session_id': session_id, 'model': '',
                  'started': None})
    host.emit_event('assistant.state', {'state': 'responding', 'jobId': job_id,
                                        'sessionId': session_id})
    retries = getattr(window, 'retry_by_session', None)
    if isinstance(retries, dict):
        retries.pop(session_id, None)
    _deliver(host, session_id, content, job_id, '小满 · 本地规则', [], [], [],
             plan_snapshot)
    state.update({'job_id': None, 'session_id': None})
    host.finish_job(job_id)
    return job_id


def _selection_index(window, text):
    method = getattr(window, 'selection_index', None)
    return method(text) if callable(method) else None


def _pending_choice(host, session_id):
    choices = getattr(_window(host), 'task_choice', None)
    return choices.get(session_id) if isinstance(choices, dict) else None


def _choice_reply(host, session_id, index):
    window = _window(host)
    choice = _pending_choice(host, session_id)
    if choice is None:
        raise BridgeError('没有等待选择的待办', code='CONFLICT')
    if not isinstance(index, int) or not 1 <= index <= len(choice['ids']):
        raise BridgeError(f'请回复 1–{len(choice["ids"])} 之间的序号',
                          code='VALIDATION_ERROR')
    window.task_choice.pop(session_id, None)
    try:
        receipt, _ = window.execute_task_op(
            dict(choice['op'], id=choice['ids'][index - 1]), confirmed=True)
    except ValueError as exc:
        receipt = f'操作未执行：{exc}'
    _store(host).add_message('assistant', receipt, session_id)
    _refresh(host, 'chat')
    pet = getattr(window, 'pet', None)
    if pet is not None:
        pet.say(plain_text(receipt) or receipt)
    job_id, _ = host.create_job()
    host.emit_event('assistant.result', {
        'jobId': job_id, 'sessionId': session_id, 'reply': receipt,
        'tasks': [receipt], 'errors': [], 'choice': None, 'note': '',
        'sources': [], 'knowledge': [], 'notices': [], 'meta': '小满 · 本地规则',
    })
    host.emit_event('assistant.state', {'state': 'idle', 'jobId': job_id,
                                        'sessionId': session_id})
    host.finish_job(job_id)
    _session_event(host, session_id, 'choice')
    return receipt


def handle(action, args, host):
    window = _window(host)
    store = _store(host)
    if action == 'sessions':
        _prepare_daily_session(host, window, store)
        rows = store.sessions()
        return {'activeSession': window.active_session,
                'sessions': [{'id': row['id'], 'title': row['title'],
                              'updatedAt': row['updated_at'],
                              'messageCount': store.message_count(row['id'])}
                             for row in rows]}
    if action == 'session':
        session_id = _session_id(host, args)
        _activate(window, session_id)
        limit = args.get('limit', 100)
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise BridgeError('消息条数需要是 1–200 的整数')
        return _session_payload(host, session_id, limit)
    if action == 'messages':
        session_id = _session_id(host, args)
        limit = args.get('limit', 100)
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise BridgeError('消息条数需要是 1–200 的整数')
        return _visible(store.messages(limit, session_id))
    if action == 'createSession':
        title = args.get('title', '新对话')
        try:
            session_id = store.create_session(title)
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        _activate(window, session_id)
        _session_event(host, session_id, 'create')
        return {'sessionId': session_id,
                **_session_payload(host, session_id, 100)}
    if action == 'deleteSession':
        session_id = _session_id(host, args)
        if _state(host).get('session_id') == session_id:
            raise BridgeError('该对话正在回复，暂时不能删除', code='CONFLICT')
        choices = getattr(window, 'task_choice', {}) or {}
        if session_id in choices:
            raise BridgeError('该对话有待确认的操作，暂时不能删除', code='CONFLICT')
        rows = store.sessions()
        fallback = next((row['id'] for row in rows if row['id'] != session_id), None)
        if fallback is None:
            raise BridgeError('至少需要保留一个对话', code='CONFLICT')
        try:
            store.delete_session(session_id)
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        retries = getattr(window, 'retry_by_session', None)
        if isinstance(retries, dict):
            retries.pop(session_id, None)
        if window.active_session == session_id:
            _activate(window, fallback)
        host.emit_event('chat.deleted', {'sessionId': session_id, 'activeSession': window.active_session})
        return {'activeSession': window.active_session}
    if action == 'renameSession':
        session_id = _session_id(host, args)
        try:
            store.rename_session(session_id, args.get('title'))
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        _session_event(host, session_id, 'rename')
        return {'session': {'id': session_id,
                            'title': store.session(session_id)['title']}}
    if action == 'saveInput':
        session_id = _session_id(host, args)
        text = args.get('text')
        if not isinstance(text, str):
            raise BridgeError('输入内容必须是文本')
        store.save_input(session_id, text)
        return {}
    if action == 'send':
        session_id = _session_id(host, args)
        text = args.get('text')
        if not isinstance(text, str) or not text.strip():
            raise BridgeError('消息不能为空')
        text = text.strip()
        if len(text) > 12000:
            raise BridgeError('请将消息控制在 12000 字以内')
        if _busy(host):
            raise BridgeError('上一条回复还在进行中，请稍候', code='CONFLICT')
        _activate(window, session_id)
        store.add_message('user', text, session_id)
        retries = getattr(window, 'retry_by_session', None)
        if isinstance(retries, dict):
            retries.pop(session_id, None)
        _session_event(host, session_id, 'user')
        choice = _pending_choice(host, session_id)
        if choice is not None:
            index = _selection_index(window, text)
            if index is not None and 1 <= index <= len(choice['ids']):
                _choice_reply(host, session_id, index)
                return {'accepted': True, 'mode': 'choice'}
            if index is not None:
                notice = (f'请回复 1–{len(choice["ids"])} 之间的序号，'
                          '或输入其他内容取消。')
                store.add_message('assistant', notice, session_id)
                job_id, _ = host.create_job()
                host.emit_event('assistant.result', {
                    'jobId': job_id, 'sessionId': session_id, 'reply': notice,
                    'tasks': [], 'errors': [], 'choice': None, 'note': '',
                    'sources': [], 'knowledge': [], 'notices': [],
                    'meta': '小满 · 本地规则',
                })
                host.finish_job(job_id)
                return {'accepted': True, 'mode': 'notice'}
            window.task_choice.pop(session_id, None)
        messages = store.messages(20, session_id)
        if not _configured(window):
            job_id = _local_exchange(host, session_id, local_reply(text))
            return {'accepted': True, 'local': True, 'jobId': job_id}
        job_id = _start(host, session_id, messages)
        return {'accepted': True, 'local': False, 'jobId': job_id}
    if action == 'retry':
        session_id = _session_id(host, args)
        if _busy(host):
            raise BridgeError('上一条回复还在进行中，请稍候', code='CONFLICT')
        retries = getattr(window, 'retry_by_session', {}) or {}
        messages = retries.get(session_id)
        if not messages:
            raise BridgeError('没有可重试的请求', code='CONFLICT')
        return {'accepted': True, 'jobId': _start(host, session_id, list(messages))}
    if action == 'regenerate':
        session_id = _session_id(host, args)
        if _busy(host):
            raise BridgeError('上一条回复还在进行中，请稍候', code='CONFLICT')
        if not _configured(window):
            raise BridgeError('请先在设置中配置模型', code='NOT_AVAILABLE')
        try:
            branch = store.branch_for_regeneration(session_id)
        except ValueError as exc:
            raise BridgeError(str(exc), code='CONFLICT') from None
        _activate(window, branch)
        _session_event(host, branch, 'regenerate')
        job_id = _start(host, branch, store.messages(20, branch))
        return {'jobId': job_id, 'sessionId': branch}
    if action == 'stop':
        state = _state(host)
        worker = state['worker']
        if worker is None:
            return {'stopped': False}
        session_id = state['session_id']
        retries = getattr(window, 'retry_by_session', None)
        if isinstance(retries, dict) and session_id is not None:
            retries[session_id] = list(worker.messages)
        worker.cancel()
        return {'stopped': True, 'jobId': state['job_id']}
    if action == 'chooseTask':
        session_id = _session_id(host, args)
        index = args.get('index')
        receipt = _choice_reply(host, session_id, index)
        return {'reply': receipt}
    if action == 'planToday':
        session_id = _session_id(host, args)
        snapshot = daily_snapshot(store.pending())
        if not args.get('confirmed'):
            return {'snapshot': snapshot, 'prompt': planning_prompt(snapshot),
                    'usesModel': _configured(window),
                    'activeSession': window.active_session}
        if _busy(host):
            raise BridgeError('上一条回复还在进行中，请稍候', code='CONFLICT')
        _activate(window, session_id)
        store.add_message('user', planning_prompt(snapshot), session_id)
        retries = getattr(window, 'retry_by_session', None)
        if isinstance(retries, dict):
            retries.pop(session_id, None)
        _session_event(host, session_id, 'user')
        if _configured(window):
            job_id = _start(host, session_id, store.messages(20, session_id),
                            web_query='', knowledge_query='',
                            plan_snapshot=snapshot)
            return {'accepted': True, 'jobId': job_id, 'snapshot': snapshot}
        job_id = _local_exchange(host, session_id, local_plan(snapshot),
                                 plan_snapshot=snapshot)
        return {'accepted': True, 'jobId': job_id, 'snapshot': snapshot,
                'local': True}
    raise BridgeError(f'未知方法: chat.{action}', code='NOT_FOUND')
