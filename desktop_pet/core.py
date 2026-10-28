import json
import re
import sqlite3
import uuid
from pathlib import Path
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from .recurrence import validate_repeat, next_occurrence


def utc_now():
    return datetime.now(timezone.utc)


def parse_due(value):
    if not isinstance(value, str):
        raise ValueError('提醒时间必须为带时区的 ISO 日期时间')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('提醒时间格式不正确') from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('提醒时间缺少时区')
    return result.astimezone(timezone.utc)


def validate_task(title, due, now=None):
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise ValueError('任务标题需要 1–200 个字符')
    value = parse_due(due)
    if value <= (now or utc_now()):
        raise ValueError('请选择未来的提醒时间')
    return title.strip(), value.isoformat()


def validate_endpoint(value):
    parts = urlsplit(value.strip())
    if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
            or parts.scheme not in ('https', 'http')):
        raise ValueError('请输入有效的 API 根地址，不包含密钥或查询参数')
    if parts.scheme == 'http' and parts.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('远程服务必须使用 HTTPS；本机服务可使用 HTTP')
    return value.strip().rstrip('/')


TASK_BLOCK = re.compile(r'```tasks[ \t]*\r?\n(.*?)```', re.S)
TASK_ACTIONS = ('update', 'complete', 'delete')
REMIND_LIMIT = 3


def _task_title(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise ValueError('任务标题需要 1–200 个字符')
    return value.strip()


def _task_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', value.strip()):
        raise ValueError('待办标识无效')
    return value.strip().lower()


def _decode_tasks(suggestions):
    tasks, errors = [], []
    if not isinstance(suggestions, list):
        return tasks, ['任务建议格式错误']
    for item in suggestions[:10]:
        try:
            if not isinstance(item, dict):
                raise ValueError('任务建议必须为对象')
            action = item.get('action', 'create')
            if action == 'create':
                title, due = validate_task(item.get('title'), item.get('due_at'))
                repeat = validate_repeat(item.get('repeat', 'none'))
                # Preserve the proposed wall-clock UTC offset for future occurrences.
                tasks.append({'title': title, 'due_at': item['due_at'], 'repeat': repeat,
                              'dingtalk': item.get('dingtalk') is True})
            elif action in TASK_ACTIONS:
                task = {'action': action, 'id': _task_id(item.get('id'))}
                if action == 'update':
                    fields = 0
                    if 'title' in item:
                        task['title'] = _task_title(item['title'])
                        fields += 1
                    if 'due_at' in item:
                        parse_due(item['due_at'])
                        task['due_at'] = item['due_at']
                        fields += 1
                    if 'repeat' in item:
                        task['repeat'] = validate_repeat(item['repeat'])
                        fields += 1
                    if 'dingtalk' in item:
                        if not isinstance(item['dingtalk'], bool):
                            raise ValueError('钉钉标记必须为 true 或 false')
                        task['dingtalk'] = item['dingtalk']
                        fields += 1
                    if not fields:
                        raise ValueError('修改操作未指定任何内容')
                tasks.append(task)
            else:
                raise ValueError('不支持的任务操作')
        except ValueError as error:
            errors.append(str(error))
    if len(suggestions) > 10:
        errors.append('只显示前 10 条建议')
    return tasks, errors


def _unquote(text):
    try:
        return json.loads('"' + text + '"')
    except ValueError:
        # 模型把引号直接写进正文时整段 JSON 无法解析，按常见转义还原后照常显示。
        text = text.replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t')
        return text.replace('\\"', '"').replace('\\\\', '\\')


def _legacy_envelope(raw):
    """Recover a reply from an old {"reply":...,"tasks":[...]} envelope that is not valid JSON."""
    marker = '","tasks"'
    key = raw.find('"reply"')
    colon = raw.find(':', key + 7) if key >= 0 else -1
    quote = raw.find('"', colon + 1) if colon >= 0 else -1
    end = raw.rfind(marker)
    if quote < 0 or end <= quote:
        return None
    reply = _unquote(raw[quote + 1:end])
    tail = raw[end + len(marker) + 1:].strip()
    if tail.endswith('}'):
        tail = tail[:-1].strip()
    try:
        suggestions = json.loads(tail)
    except (ValueError, TypeError):
        return reply, [], ['任务建议格式错误']
    tasks, errors = _decode_tasks(suggestions)
    return reply, tasks, errors


def decode_response(content):
    """Markdown reply plus an optional trailing tasks block; old JSON envelopes stay readable."""
    if not isinstance(content, str):
        raise ValueError('服务返回了不支持的消息格式')
    block = TASK_BLOCK.search(content)
    if block:
        reply = (content[:block.start()] + content[block.end():]).strip()
        try:
            suggestions = json.loads(block.group(1))
        except (ValueError, TypeError):
            return reply, [], ['任务建议格式错误']
        tasks, errors = _decode_tasks(suggestions)
        return reply, tasks, errors
    raw = content.strip()
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        legacy = _legacy_envelope(raw)
        return legacy if legacy else (content, [], [])
    if not isinstance(payload, dict) or not isinstance(payload.get('reply'), str):
        return content, [], []
    tasks, errors = _decode_tasks(payload.get('tasks', []))
    return payload['reply'], tasks, errors


class TaskStore:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version > 6:
            self.db.close()
            raise ValueError('数据库来自较新版本，请升级应用')
        if version in (1, 2, 3, 4, 5) and str(path) != ':memory:':
            # SQLite backup includes committed WAL data and never overwrites a previous backup.
            backup_path = Path(str(path) + f'.v{version}-' + uuid.uuid4().hex + '.bak')
            with closing(sqlite3.connect(str(backup_path))) as backup:
                self.db.backup(backup)
        self.db.executescript('''
            BEGIN;
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, due_at TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending', notified_at TEXT,
              created_at TEXT NOT NULL, dingtalk INTEGER NOT NULL DEFAULT 0,
              remind_count INTEGER NOT NULL DEFAULT 0, deferred INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS tasks_due ON tasks(status, due_at);
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL,
              content TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drafts (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, due_at TEXT NOT NULL,
              created_at TEXT NOT NULL);
        ''')
        try:
            self.db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY,title TEXT NOT NULL,input_text TEXT NOT NULL DEFAULT \'\',updated_at TEXT NOT NULL)')
            for table in ('messages', 'drafts'):
                columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
                if 'session_id' not in columns:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN session_id TEXT NOT NULL DEFAULT 'default'")
                self.db.execute(f'CREATE INDEX IF NOT EXISTS {table}_session ON {table}(session_id)')
            self.db.execute("INSERT OR IGNORE INTO sessions(id,title,updated_at) VALUES('default','默认对话',?)", (utc_now().isoformat(),))
            task_columns = {row['name'] for row in self.db.execute('PRAGMA table_info(tasks)')}
            for name, declaration in (('repeat_rule', "TEXT NOT NULL DEFAULT 'none'"),
                                      ('scheduled_at', 'TEXT'), ('next_id', 'TEXT'),
                                      ('dingtalk', 'INTEGER NOT NULL DEFAULT 0'),
                                      ('remind_count', 'INTEGER NOT NULL DEFAULT 0'),
                                      ('deferred', 'INTEGER NOT NULL DEFAULT 0')):
                if name not in task_columns:
                    self.db.execute(f'ALTER TABLE tasks ADD COLUMN {name} {declaration}')
            draft_columns = {row['name'] for row in self.db.execute('PRAGMA table_info(drafts)')}
            if 'repeat_rule' not in draft_columns:
                self.db.execute("ALTER TABLE drafts ADD COLUMN repeat_rule TEXT NOT NULL DEFAULT 'none'")
            self.db.execute('UPDATE tasks SET scheduled_at=due_at WHERE scheduled_at IS NULL')
            self.db.execute('PRAGMA user_version=6')
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.db.close()
            raise

    def sessions(self):
        return self.db.execute('SELECT * FROM sessions ORDER BY updated_at DESC,id').fetchall()

    def session(self, session_id):
        row = self.db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise ValueError('会话不存在')
        return row

    def create_session(self, title='新对话'):
        session_id = uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO sessions(id,title,updated_at) VALUES(?,?,?)',
                            (session_id, self.session_title(title), utc_now().isoformat()))
        return session_id

    @staticmethod
    def session_title(title):
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 60:
            raise ValueError('会话名称需要1–60个字符')
        return title.strip()

    def rename_session(self, session_id, title):
        self.session(session_id)
        with self.db:
            self.db.execute('UPDATE sessions SET title=? WHERE id=?', (self.session_title(title), session_id))

    def save_input(self, session_id, text):
        with self.db:
            self.db.execute('UPDATE sessions SET input_text=? WHERE id=?', (text, session_id))

    def add(self, title, due, now=None, repeat='none', dingtalk=False):
        scheduled_at = due
        title, due = validate_task(title, due, now)
        validate_repeat(repeat)
        task_id = uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO tasks(id,title,due_at,created_at,repeat_rule,scheduled_at,dingtalk) VALUES(?,?,?,?,?,?,?)',
                            (task_id, title, due, (now or utc_now()).isoformat(), repeat, scheduled_at, int(bool(dingtalk))))
        return task_id

    def set_dingtalk(self, task_id, enabled=True):
        with self.db:
            self.db.execute("UPDATE tasks SET dingtalk=? WHERE id=? AND status='pending'",
                            (int(bool(enabled)), task_id))

    def pending(self):
        return self.db.execute("SELECT * FROM tasks WHERE status='pending' ORDER BY due_at").fetchall()

    def history(self, status='done', search=''):
        if status not in ('pending', 'done'):
            raise ValueError('不支持的任务状态')
        # instr treats user-entered % and _ as literal characters.
        return self.db.execute('SELECT * FROM tasks WHERE status=? AND instr(lower(title),lower(?))>0 ORDER BY due_at',
                               (status, search.strip())).fetchall()

    def reopen(self, task_id):
        row = self.db.execute('SELECT next_id FROM tasks WHERE id=?', (task_id,)).fetchone()
        if row and row['next_id']:
            raise ValueError('此重复任务已生成下一次，请编辑未完成列表中的下一次任务，避免重复提醒。')
        with self.db:
            self.db.execute("UPDATE tasks SET status='pending',notified_at=NULL,remind_count=0,deferred=0 WHERE id=? AND status='done'", (task_id,))

    def delete(self, task_id):
        with self.db:
            self.db.execute("UPDATE tasks SET status='deleted_' || status WHERE id=? AND status IN ('pending','done')", (task_id,))

    def undo_delete(self, task_id):
        with self.db:
            self.db.execute("UPDATE tasks SET status=substr(status,9),notified_at=NULL WHERE id=? AND status IN ('deleted_pending','deleted_done')", (task_id,))

    def save_draft(self, title, due, draft_id=None, session_id='default', repeat='none'):
        self.session(session_id)
        parse_due(due)
        validate_repeat(repeat)
        if not isinstance(title, str) or len(title) > 200:
            raise ValueError('草稿标题不能超过200个字符')
        draft_id = draft_id or uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO drafts(id,title,due_at,created_at,session_id,repeat_rule) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,due_at=excluded.due_at,repeat_rule=excluded.repeat_rule',
                            (draft_id, title, due, utc_now().isoformat(), session_id, repeat))
        return draft_id

    def drafts(self, session_id=None):
        if session_id is not None:
            return self.db.execute('SELECT * FROM drafts WHERE session_id=? ORDER BY created_at', (session_id,)).fetchall()
        return self.db.execute('SELECT * FROM drafts ORDER BY created_at').fetchall()

    def discard_draft(self, draft_id):
        with self.db:
            self.db.execute('DELETE FROM drafts WHERE id=?', (draft_id,))

    def confirm_draft(self, draft_id):
        with self.db:
            draft = self.db.execute('SELECT * FROM drafts WHERE id=?', (draft_id,)).fetchone()
            if draft is None:
                raise ValueError('草稿已处理，请勿重复保存')
            title, due = validate_task(draft['title'], draft['due_at'])
            task_id = uuid.uuid4().hex
            self.db.execute('INSERT INTO tasks(id,title,due_at,created_at,repeat_rule,scheduled_at) VALUES(?,?,?,?,?,?)',
                            (task_id, title, due, utc_now().isoformat(), draft['repeat_rule'], draft['due_at']))
            self.db.execute('DELETE FROM drafts WHERE id=?', (draft_id,))
        return task_id

    def due(self, now=None):
        return self.db.execute("SELECT * FROM tasks WHERE status='pending' AND deferred=0 AND notified_at IS NULL AND due_at<=? ORDER BY due_at LIMIT 20",
                               ((now or utc_now()).isoformat(),)).fetchall()

    def mark_shown(self, task_id):
        """Count one reminder popup; the REMIND_LIMIT-th popup marks the task deferred."""
        with self.db:
            self.db.execute('UPDATE tasks SET remind_count=MIN(remind_count+1,?),notified_at=? WHERE id=?',
                            (REMIND_LIMIT, utc_now().isoformat(), task_id))
            row = self.db.execute('SELECT remind_count,deferred FROM tasks WHERE id=?', (task_id,)).fetchone()
            if row and row['remind_count'] >= REMIND_LIMIT and not row['deferred']:
                self.db.execute('UPDATE tasks SET deferred=1 WHERE id=?', (task_id,))
                return REMIND_LIMIT, True
        return (row['remind_count'], bool(row['deferred'])) if row else (0, False)

    def reset_notifications(self):
        with self.db:
            self.db.execute("UPDATE tasks SET notified_at=NULL WHERE status='pending' AND deferred=0")

    def complete(self, task_id, now=None):
        now = now or utc_now()
        with self.db:
            row = self.db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if row is None or row['status'] != 'pending':
                return None
            changed = self.db.execute("UPDATE tasks SET status='done' WHERE id=? AND status='pending'", (task_id,)).rowcount
            if not changed:
                return None
            scheduled = next_occurrence(row['scheduled_at'], row['repeat_rule'], now)
            if scheduled is None:
                return None
            next_id = uuid.uuid4().hex
            self.db.execute('INSERT INTO tasks(id,title,due_at,created_at,repeat_rule,scheduled_at,dingtalk) VALUES(?,?,?,?,?,?,?)',
                            (next_id, row['title'], scheduled.astimezone(timezone.utc).isoformat(), now.isoformat(),
                             row['repeat_rule'], scheduled.isoformat(), row['dingtalk']))
            self.db.execute('UPDATE tasks SET next_id=? WHERE id=?', (next_id, task_id))
            return next_id

    def edit(self, task_id, title, due, now=None, repeat=None, dingtalk=None):
        scheduled_at = due
        title, due = validate_task(title, due, now)
        row = self.db.execute('SELECT repeat_rule,due_at,scheduled_at,dingtalk FROM tasks WHERE id=?', (task_id,)).fetchone()
        repeat = validate_repeat(repeat if repeat is not None else (row['repeat_rule'] if row else 'none'))
        dingtalk = int(bool(row['dingtalk'] if dingtalk is None and row else dingtalk))
        if row and due == row['due_at'] and repeat == row['repeat_rule']:
            scheduled_at = row['scheduled_at']
        with self.db:
            self.db.execute("UPDATE tasks SET title=?,due_at=?,scheduled_at=?,repeat_rule=?,dingtalk=?,notified_at=NULL,remind_count=0,deferred=0 WHERE id=? AND status='pending'",
                            (title, due, scheduled_at, repeat, dingtalk, task_id))

    def snooze(self, task_id, now=None):
        with self.db:
            self.db.execute("UPDATE tasks SET due_at=?,notified_at=NULL WHERE id=? AND status='pending' AND deferred=0",
                            (((now or utc_now()) + timedelta(minutes=10)).isoformat(), task_id))

    def add_message(self, role, content, session_id='default'):
        session = self.session(session_id)
        with self.db:
            now = utc_now().isoformat()
            self.db.execute('INSERT INTO messages(role,content,created_at,session_id) VALUES(?,?,?,?)',
                            (role, content, now, session_id))
            title = content.strip().replace('\n', ' ')[:24] if role == 'user' and session['title'] == '新对话' else session['title']
            self.db.execute('UPDATE sessions SET title=?,updated_at=? WHERE id=?', (title or '新对话', now, session_id))

    def messages(self, limit=100, session_id='default'):
        rows = self.db.execute('SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?', (session_id, limit)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def regeneration_context(self, session_id):
        """Return context through the latest answered user turn, without its reply."""
        self.session(session_id)
        last_user = self.db.execute("SELECT id FROM messages WHERE session_id=? AND role='user' ORDER BY id DESC LIMIT 1",
                                    (session_id,)).fetchone()
        if last_user is None or not self.db.execute(
                "SELECT 1 FROM messages WHERE session_id=? AND role='assistant' AND id>? LIMIT 1",
                (session_id, last_user['id'])).fetchone():
            return []
        rows = self.db.execute('SELECT role,content FROM messages WHERE session_id=? AND id<=? ORDER BY id DESC LIMIT 20',
                               (session_id, last_user['id'])).fetchall()
        return [dict(row) for row in reversed(rows)]

    def branch_for_regeneration(self, session_id):
        messages = self.regeneration_context(session_id)
        if not messages:
            raise ValueError('当前对话没有可以重新生成的已回复消息')
        source = self.session(session_id)
        target_id = uuid.uuid4().hex
        now = utc_now().isoformat()
        with self.db:
            self.db.execute('INSERT INTO sessions(id,title,updated_at) VALUES(?,?,?)',
                            (target_id, ('另一版 · ' + source['title'])[:60], now))
            self.db.executemany('INSERT INTO messages(role,content,created_at,session_id) VALUES(?,?,?,?)',
                                [(m['role'], m['content'], now, target_id) for m in messages])
        return target_id

    def close(self):
        self.db.close()
