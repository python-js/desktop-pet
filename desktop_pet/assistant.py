"""Provider-neutral compatible chat protocol; never executes model actions."""
import json
import re
from datetime import datetime, timedelta
from urllib import request, error

from .core import decode_response, parse_due, validate_endpoint
from .recurrence import REPEAT_LABELS


class RequestCancelled(Exception):
    """Cooperative stop; incomplete output must never create tasks."""


def reply_preview(raw):
    """Extract only the visible reply while a tasks block or JSON envelope is incomplete."""
    raw = re.sub(r'```tasks[^\n]*\n.*?(?:```|$)', '', raw, flags=re.S)
    match = re.match(r'^\s*(?:```(?:json)?\s*)?\{\s*"reply"\s*:\s*"', raw)
    if not match:
        return raw if raw.strip() and raw.lstrip()[0] not in '{[`' else ''
    position, parts = match.end(), []
    escapes = {'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'f': '\f', '"': '"', '\\': '\\', '/': '/'}
    while position < len(raw):
        char = raw[position]
        if char == '"':
            break
        if char != '\\':
            parts.append(char)
            position += 1
            continue
        if position + 1 >= len(raw):
            break
        code = raw[position + 1]
        if code in escapes:
            parts.append(escapes[code])
            position += 2
        elif code == 'u':
            length = 6
            if len(raw) < position + length:
                break
            try:
                number = int(raw[position + 2:position + 6], 16)
                if 0xD800 <= number <= 0xDBFF:
                    length = 12
                    if len(raw) < position + length:
                        break
                text = json.loads('"' + raw[position:position + length] + '"')
                if any(0xD800 <= ord(c) <= 0xDFFF for c in text):
                    break
                parts.append(text)
                position += length
            except (ValueError, TypeError):
                break
        else:
            break
    return ''.join(parts)


def plain_text(text):
    """Flatten a Markdown reply for the pet bubble."""
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'(?m)^\s*(?:[-+*]|\d+\.)\s+', '', text)
    text = re.sub(r'[`*_#>]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def read_stream(response, on_chunk, cancelled):
    content, total, finished = [], 0, False
    event = []

    def process(lines):
        nonlocal finished
        data = '\n'.join(line[5:].lstrip() for line in lines if line.startswith('data:'))
        if not data:
            return
        if data.strip() == '[DONE]':
            finished = True
            return
        payload = json.loads(data)
        if not isinstance(payload, dict) or payload.get('error'):
            raise ValueError('流式服务返回错误，请检查模型配置后重试。')
        choices = payload.get('choices', [])
        if not choices:
            return  # Some services send usage-only events.
        choice = choices[0]
        if choice.get('finish_reason') in ('length', 'content_filter'):
            raise ValueError('回复被截断或过滤，未创建任务建议，请调整请求后重试。')
        delta = choice.get('delta', {}).get('content')
        if delta is not None:
            if not isinstance(delta, str):
                raise ValueError('流式消息格式不兼容')
            content.append(delta)
            on_chunk(delta)

    while True:
        if cancelled():
            raise RequestCancelled()
        line = response.readline(262145)
        if cancelled():
            raise RequestCancelled()
        if not line:
            if event:
                process(event)
            break
        total += len(line)
        if len(line) > 262144 or total > 2 * 1024 * 1024:
            raise ValueError('流式回复过大，请缩小请求范围')
        decoded = line.decode('utf-8').rstrip('\r\n')
        if decoded:
            event.append(decoded)
        else:
            process(event)
            event = []
            if finished:
                break
    if cancelled():
        raise RequestCancelled()
    if not finished:
        raise ValueError('流式连接提前结束，未创建任务建议，请重试。')
    if not content:
        raise ValueError('模型没有返回可显示的内容')
    return ''.join(content)


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


DINGTALK_REQUEST = re.compile(r'钉钉群?(?:通知|提醒|推送)|(?:发到|发送到|推送到|同步到|发至|发送至)钉钉群?')
MANAGE_REQUEST = re.compile(
    r'(?:把|将).{1,40}(?:改|修改|调整|推迟|提前|延期|完成|删除|取消)'
    r'|(?:改|修改|调整|推迟|提前|延期|完成|删除|取消|标记).{0,12}(?:待办|提醒|任务)'
    r'|(?:待办|提醒|任务).{0,12}(?:改|修改|完成|删除|取消)')


def task_snapshot(tasks):
    """Render the pending list the model may reference; ids stay opaque to the user."""
    if not tasks:
        return '当前没有未完成待办；不要输出 update、complete 或 delete 操作。'
    now = datetime.now().astimezone()
    lines = ['当前未完成待办（修改、完成、删除时只能使用下列 id，逐字复制）：',
             'id | 标题 | 到期（本地时间） | 重复 | 状态']
    for task in tasks[:50]:
        due = parse_due(task['due_at']).astimezone()
        title = ' '.join(str(task['title']).split()).replace('|', '/')
        state = '已延期' if task.get('deferred') else ('已逾期' if due <= now else '未逾期')
        label = REPEAT_LABELS.get(task.get('repeat_rule', 'none'), '不重复')
        if task.get('dingtalk'):
            state += ' | 钉钉'
        lines.append(f"{task['id']} | {title} | {due:%Y-%m-%d %H:%M} | {label} | {state}")
    if len(tasks) > 50:
        lines.append(f'另有 {len(tasks) - 50} 条未列出，未列出的待办不能操作。')
    return '\n'.join(lines)


def local_reply(text, now=None):
    now = now or datetime.now().astimezone()
    dingtalk = bool(DINGTALK_REQUEST.search(text))
    if dingtalk:
        # 把“钉钉群通知”这类渠道词从待办标题里移除。
        text = DINGTALK_REQUEST.sub('', text)
    match = re.search(r'(今天|明天|后天|每天|每个工作日|每周一至五|每周[一二三四五六日天])?\s*(\d{1,2})[:：](\d{2})\s*提醒我\s*(.+)', text)
    if match:
        day, hour, minute, title = match.groups()
        try:
            repeat = 'daily' if day == '每天' else ('weekdays' if day in ('每个工作日', '每周一至五') else ('weekly' if day and day.startswith('每周') else 'none'))
            if re.search(r'不(?:要|用|需(?:要)?)?重复|只(?:提醒)?一次|仅一次', text):
                repeat = 'none'
            elif repeat == 'none' and re.search(r'重复提醒|循环提醒|(?:^|[，,。\s])重复(?:$|[。！!\s])', text):
                # A bare request to repeat uses the same local time every day.
                repeat = 'daily'
            title = re.sub(r'[，,]\s*(?:请)?(?:不要重复|不重复|重复提醒|重复|循环提醒)[。！!\s]*$', '', title).strip()
            title = title.strip('，,。！!；; ')
            due = (now + timedelta(days={'今天': 0, '明天': 1, '后天': 2}.get(day, 0))).replace(
                hour=int(hour), minute=int(minute), second=0, microsecond=0)
            if repeat == 'weekly':
                weekday = '一二三四五六日'.index(day[-1].replace('天', '日'))
                due += timedelta(days=(weekday - due.weekday()) % 7)
            if repeat != 'none':
                while due <= now or (repeat == 'weekdays' and due.weekday() >= 5):
                    due += timedelta(days=7 if repeat == 'weekly' else 1)
            if due <= now:
                return json.dumps({'reply': '这个时间已经过去了，请指定未来日期和时间。', 'tasks': []}, ensure_ascii=False)
            return json.dumps({'reply': '已识别待办，正在创建提醒。',
                               'tasks': [{'title': title, 'due_at': due.isoformat(), 'repeat': repeat,
                                          'dingtalk': dingtalk}]}, ensure_ascii=False)
        except ValueError:
            pass
    if MANAGE_REQUEST.search(text):
        return json.dumps({'reply': '当前是本地规则模式，暂不支持在对话中修改、完成或删除待办。'
                                    '请到待办页双击编辑，或配置模型后再在对话中操作。', 'tasks': []},
                          ensure_ascii=False)
    return json.dumps({'reply': '当前是本地规则模式。你可以说“明天15:00提醒我交报告”，或在待办页手动创建任务。配置模型后可进行自由聊天和任务规划。', 'tasks': []}, ensure_ascii=False)


def ask(settings, messages, on_chunk=None, cancelled=None, tasks=None):
    cancelled = cancelled or (lambda: False)
    if cancelled():
        raise RequestCancelled()
    if not settings.get('model') or not settings.get('base_url'):
        return local_reply(messages[-1]['content'])
    endpoint = validate_endpoint(settings['base_url']) + '/chat/completions'
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    system = ('你是一个中文桌面宠物待办助手。当前本地时间：' + now + '。'
              '帮助用户聊天和规划任务。用中文回答，正文使用 Markdown：按需使用标题、列表、粗体和代码块，不要输出 HTML。'
              '需要创建待办时，在正文最后另起一个代码块，语言标记为 tasks，块内只放 JSON 数组：'
              '```tasks\n[{"title":"任务标题","due_at":"带时区偏移的ISO8601时间","repeat":"none","dingtalk":false}]\n```\n'
              'tasks 块必须是回复的最后一部分，正文不要复述块内内容；普通聊天不要输出 tasks 块。'
              'tasks 块也用于管理已有待办：{"action":"update","id":"…","title":"新标题","due_at":"…"} 修改，只写要改的字段；'
              '{"action":"complete","id":"…"} 完成；{"action":"delete","id":"…"} 删除。'
              '修改、完成、删除只能使用“当前未完成待办”清单中逐字复制的 id，不得编造；清单里没有对应待办时不要输出这些操作。'
              '同一标题有多条且无法确定用户指代时，先列出候选（标题和时间）让用户选择，不要自行挑一条。'
              '修改时间必须是带时区偏移的未来时间；待办已逾期且用户没给新时间时先追问。'
              '所有创建、修改、完成、删除均由程序执行并反馈，正文不要声称已经执行成功。'
              '只有当用户明确要求把某个待办通知到钉钉群（如“钉钉群通知”“发到钉钉群”）时，才在该任务对象中设置"dingtalk":true；'
              '其他情况不要输出该字段或设为false，不要主动建议、追问或添加钉钉通知。'
              'repeat只能为none不重复、daily每天、weekdays周一至五、weekly每周。'
              '用户未明确要求重复时，直接使用none，不要询问是否重复、是否每天提醒，也不要为了重复选项让用户再次确认。'
              '用户明确要求每天、工作日或每周时直接填对应规则；只说“重复提醒”或“重复”而没有频率时，默认daily每天同一时间，并在回复中简要说明，不再追问频率。'
              '用户明确说不重复或只提醒一次时使用none。用户要求每月、自定义间隔等不支持的规则时说明限制，不要擅自改成每天。'
              'due_at为下一次未来时间，普通聊天不要凭空创建任务。'
              '时间不明确时追问，不自行猜测。最多10个任务，不给过去时间。'
              '用户明确要求创建待办或提醒且事项与时间完整时，直接输出 tasks，由程序自动保存并设置提醒，不要要求用户确认或点击保存。'
              '仅讨论、举例或规划建议不要输出 tasks；用户要求直接安排具体待办时才创建。'
              '不要受历史回复中“待确认”“需要保存”等旧流程影响。保存结果由程序反馈，正文不要声称已经执行成功。'
              + '\n\n' + task_snapshot(tasks or []))
    history = []
    for m in messages[-20:]:
        content = m['content']
        if m['role'] == 'assistant':
            # 旧版本回复存成 JSON 信封，发送给模型前还原为正文。
            content = decode_response(content)[0]
        history.append({'role': m['role'], 'content': content[:12000]})
    streaming = on_chunk is not None and settings.get('stream', True)
    body = json.dumps({'model': settings['model'], 'stream': streaming,
                       'messages': [{'role': 'system', 'content': system}] + history}).encode('utf-8')
    headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream' if streaming else 'application/json'}
    if settings.get('api_key'):
        headers['Authorization'] = 'Bearer ' + settings['api_key']
    req = request.Request(endpoint, data=body, headers=headers, method='POST')
    try:
        with request.build_opener(NoRedirect()).open(req, timeout=45) as response:
            if cancelled():
                raise RequestCancelled()
            headers = getattr(response, 'headers', {})
            if streaming and 'text/event-stream' in headers.get('Content-Type', '').lower():
                return read_stream(response, on_chunk, cancelled)
            data = response.read(2 * 1024 * 1024 + 1)
            if cancelled():
                raise RequestCancelled()
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('回复过大，请缩小请求范围')
            payload = json.loads(data)
            if payload['choices'][0].get('finish_reason') in ('length', 'content_filter'):
                raise ValueError('回复被截断或过滤，未创建任务建议，请调整请求后重试。')
            content = payload['choices'][0]['message']['content']
            if not isinstance(content, str):
                raise ValueError('服务返回了不支持的消息格式')
            return content
    except error.HTTPError as exc:
        raise ValueError(f'模型服务返回 HTTP {exc.code}，请检查地址、模型、鉴权或额度。') from None
    except (error.URLError, TimeoutError, OSError):
        raise ValueError('无法连接模型服务或请求超时，请检查网络和服务地址。') from None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        raise ValueError('服务返回格式不兼容，请确认支持 Chat Completions 接口。') from None
