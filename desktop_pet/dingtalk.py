"""DingTalk custom robot delivery: webhook validation, signing and one-shot push."""
import base64
import hashlib
import hmac
import json
import time
from urllib import parse, request


class DingTalkError(ValueError):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_webhook(value):
    value = (value or '').strip()
    parts = parse.urlsplit(value)
    if (parts.scheme != 'https' or parts.hostname != 'oapi.dingtalk.com'
            or parts.path.rstrip('/') != '/robot/send' or parts.username or parts.password):
        raise DingTalkError('请填写钉钉自定义机器人的 Webhook 地址')
    token = parse.parse_qs(parts.query).get('access_token', [''])[0].strip()
    if not token or len(token) > 512:
        raise DingTalkError('Webhook 缺少有效的 access_token')
    return value


def signed_url(webhook, secret, timestamp=None):
    if not secret:
        return webhook
    timestamp = str(int(time.time() * 1000) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode('utf-8'), f'{timestamp}\n{secret}'.encode('utf-8'),
                      hashlib.sha256).digest()
    sign = parse.quote_plus(base64.b64encode(digest).decode('ascii'))
    separator = '&' if '?' in webhook else '?'
    return f'{webhook}{separator}timestamp={timestamp}&sign={sign}'


def build_payload(title, due_label, repeat_label):
    content = f'【待办提醒】{title}\n时间：{due_label}\n重复：{repeat_label}'
    return {'msgtype': 'text', 'text': {'content': content[:20000]}}


def send(webhook, secret, title, due_label, repeat_label, opener=None):
    webhook = validate_webhook(webhook)
    secret = (secret or '').strip()
    if not secret:
        raise DingTalkError('请填写机器人加签密钥')
    data = json.dumps(build_payload(title, due_label, repeat_label), ensure_ascii=False).encode('utf-8')
    req = request.Request(signed_url(webhook, secret), data=data,
                          headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        with (opener or request.build_opener(NoRedirect())).open(req, timeout=8) as response:
            body = json.loads(response.read(65536).decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise DingTalkError(f'无法连接钉钉（{exc}）') from None
    if not isinstance(body, dict) or body.get('errcode') != 0:
        reason = body.get('errmsg') if isinstance(body, dict) else ''
        raise DingTalkError('钉钉拒绝发送：' + str(reason or '返回格式异常')[:200])
    return str(body.get('errmsg') or 'ok')
