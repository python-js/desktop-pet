"""QWebChannel bridge host: JSON-envelope dispatch between the HTML UI and Python backend.

Protocol (see docs/BRIDGE_API.md): a single QObject exposes
  invoke(method, payload) -> response envelope JSON string
  cancel(jobId)
  event(name, payload) signal broadcast to every attached view.

Handlers are registered per module ('tasks.add' -> module 'tasks', action 'add')
and must never contain business logic; they adapt arguments and forward to the
existing backend objects carried in the context dict.
"""
import json
import logging
import os
import sys
import threading
import uuid

from PySide6.QtCore import QObject, Signal, Slot

from .version import __version__

log = logging.getLogger(__name__)

BRIDGE_PROTOCOL_VERSION = 1


class BridgeError(Exception):
    def __init__(self, message, code='VALIDATION_ERROR'):
        super().__init__(message)
        self.code = code

    def to_dict(self):
        return {'code': self.code, 'message': str(self)}


def _envelope(ok, body):
    return json.dumps(body, ensure_ascii=False)


class BridgeHost(QObject):
    event = Signal(str, str)

    def __init__(self, context=None, parent=None):
        super().__init__(parent)
        self.context = context or {}
        self._modules = {}
        self._jobs = {}
        self._job_lock = threading.Lock()
        self._pending_events = []
        self._handshaken = False
        self.register_module('system', handle_system)

    # -- invocation ---------------------------------------------------------

    @Slot(str, str, result=str)
    def invoke(self, method, payload):
        try:
            data = self._dispatch(method, payload)
            return _envelope(True, {'ok': True, 'data': data})
        except BridgeError as exc:
            return _envelope(False, {'ok': False, 'error': exc.to_dict()})
        except Exception:
            log.exception('bridge invoke failed: %s', method)
            return _envelope(False, {'ok': False, 'error': {'code': 'INTERNAL', 'message': '内部错误，请查看日志。'}})

    def _dispatch(self, method, payload):
        if not isinstance(method, str) or method.count('.') != 1:
            raise BridgeError(f'非法方法名: {method!r}')
        module_name, _, action = method.partition('.')
        handler = self._modules.get(module_name)
        if handler is None:
            raise BridgeError(f'未知模块: {module_name}', code='NOT_FOUND')
        args = json.loads(payload) if payload else {}
        if not isinstance(args, dict):
            raise BridgeError('参数必须是 JSON 对象')
        return handler(action, args, self)

    # -- module registration --------------------------------------------------

    def register_module(self, name, handler):
        self._modules[name] = handler

    # -- jobs (async operations) ---------------------------------------------

    def create_job(self):
        job_id = uuid.uuid4().hex[:16]
        cancel_event = threading.Event()
        with self._job_lock:
            self._jobs[job_id] = cancel_event
        return job_id, cancel_event

    def finish_job(self, job_id):
        with self._job_lock:
            self._jobs.pop(job_id, None)

    @Slot(str)
    def cancel(self, job_id):
        with self._job_lock:
            cancel_event = self._jobs.get(job_id)
        if cancel_event is not None:
            cancel_event.set()
            log.info('bridge job cancelled: %s', job_id)

    # -- events ----------------------------------------------------------------

    def emit_event(self, name, payload):
        text = json.dumps(payload, ensure_ascii=False)
        if self._handshaken:
            self.event.emit(name, text)
        else:
            self._pending_events.append((name, text))

    def _mark_handshake(self):
        """First `system.info` call marks the page ready; buffered events replay before it returns."""
        self._handshaken = True
        pending, self._pending_events = self._pending_events, []
        for name, text in pending:
            self.event.emit(name, text)

    def emit_result(self, job_id, ok, message='', **extra):
        self.emit_event('job.result', {'jobId': job_id, 'ok': ok, 'message': message, **extra})
        self.finish_job(job_id)


def handle_system(action, args, host):
    ctx = host.context
    if action == 'info':
        host._mark_handshake()
        return {
            'appVersion': __version__,
            'bridgeVersion': BRIDGE_PROTOCOL_VERSION,
            'platform': sys.platform,
            'devMode': bool(ctx.get('dev_mode') or os.environ.get('DESKTOP_PET_DEV')),
            'dataDir': str(ctx.get('data_dir', '')),
        }
    raise BridgeError(f'未知方法: system.{action}', code='NOT_FOUND')
