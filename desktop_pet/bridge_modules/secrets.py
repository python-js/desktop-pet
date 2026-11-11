"""secrets.*: DPAPI secret store adapter plus connection-test jobs (model / Tavily / DingTalk)."""
import threading
from datetime import datetime, timedelta

from ..assistant import RequestCancelled, test_connection as test_model
from ..bridge import BridgeError
from ..core import validate_endpoint
from ..dingtalk import DingTalkError, send as dingtalk_send, validate_webhook
from ..websearch import test_connection as test_tavily


def handle(action, args, host):
    window = host.context['window']
    store = window.secret_store
    if action == 'status':
        return {
            'hasApiKey': bool(window.settings.get('api_key')),
            'hasTavily': bool(window.settings.get('tavily_key')),
            'hasDingtalk': _has_dingtalk(store),
            'rememberKey': bool(window.settings.get('remember_key')),
        }
    if action == 'saveApiKey':
        value = str(args.get('value') or '').strip()
        try:
            endpoint = validate_endpoint(str(args.get('endpoint') or '').strip())
        except ValueError as exc:
            raise BridgeError(str(exc)) from None
        if not endpoint:
            raise BridgeError('请先填写服务地址')
        if value:
            store.save(endpoint, value)
        else:
            store.remove()
        window.settings['api_key'] = value
        window.secret_endpoint = endpoint
        return {}
    if action == 'saveTavily':
        value = str(args.get('value') or '').strip()
        if value:
            store.save_tavily(value)
        else:
            store.remove_tavily()
        window.settings['tavily_key'] = value
        return {}
    if action == 'saveDingtalk':
        webhook = str(args.get('webhook') or '').strip()
        secret = str(args.get('secret') or '').strip()
        if webhook:
            try:
                store.save_dingtalk(validate_webhook(webhook), secret)
            except DingTalkError as exc:
                raise BridgeError(str(exc)) from None
        else:
            store.remove_dingtalk()
        return {}
    if action == 'rememberKey':
        enabled = args.get('enabled')
        if not isinstance(enabled, bool):
            raise BridgeError('enabled 必须是布尔值')
        window.settings['remember_key'] = enabled
        if enabled:
            # Qt 侧密钥输入框预填当前值;web 侧密钥不下发,启用记住时直接
            # 把本次运行内存里的密钥落盘,与 Qt 行为一致。
            endpoint = str(window.settings.get('base_url') or '')
            key = str(window.settings.get('api_key') or '')
            if not (endpoint and key):
                window.settings['remember_key'] = False
                raise BridgeError('请先填写服务地址并保存 API Key，再记住密钥。')
            store.save(validate_endpoint(endpoint), key)
            window.secret_endpoint = endpoint
        else:
            store.remove()
        window.persist_settings()
        return {}
    if action == 'testConnection':
        kind = args.get('kind')
        if kind not in ('model', 'tavily', 'dingtalk'):
            raise BridgeError('kind 必须是 model / tavily / dingtalk')
        return _spawn_test(host, window, kind, args)
    raise BridgeError(f'未知方法: secrets.{action}', code='NOT_FOUND')


def _has_dingtalk(store):
    try:
        webhook, _secret = store.load_dingtalk()
        return bool(webhook)
    except (OSError, ValueError):
        return False


def _spawn_test(host, window, kind, args):
    job_id, _cancel_event = host.create_job()

    def work():
        ok, message = False, ''
        try:
            if kind == 'model':
                message = f'连接成功，{test_model(window.settings)}ms'
                ok = True
            elif kind == 'tavily':
                key = str(args.get('value') or window.settings.get('tavily_key') or '').strip()
                if not key:
                    raise ValueError('请先填写 Tavily 密钥')
                message = f'连接成功，{test_tavily(key)}ms'
                ok = True
            elif kind == 'dingtalk':
                webhook = str(args.get('webhook') or '').strip()
                secret = str(args.get('secret') or '').strip()
                if not webhook:
                    webhook, secret = window.secret_store.load_dingtalk()
                webhook = validate_webhook(webhook)
                if not secret:
                    raise DingTalkError('请填写加签密钥')
                due_label = (datetime.now().astimezone() + timedelta(hours=1)).strftime('%m月%d日 %H:%M')
                dingtalk_send(webhook, secret, '钉钉通知测试', due_label, '不重复')
                message, ok = '测试消息已发送，请查看钉钉群。', True
        except (ValueError, DingTalkError) as exc:
            message = str(exc)
        except (OSError, RequestCancelled):
            message = '请求失败，请稍后重试。'
        except Exception:
            message = '测试失败，发生未预期的错误。'
        host.emit_event('connection.testResult', {'jobId': job_id, 'kind': kind, 'ok': ok, 'message': message})
        host.finish_job(job_id)

    threading.Thread(target=work, daemon=True).start()
    return {'jobId': job_id}
