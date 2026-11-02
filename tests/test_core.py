import json
import tempfile
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from desktop_pet.assistant import ask, local_reply, test_connection
from desktop_pet.core import (TaskStore, decode_response, in_quiet_hours, parse_clock,
                              parse_due, validate_endpoint, validate_task)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'tasks.db'
        self.store = TaskStore(self.path)
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_timezone_normalization(self):
        self.assertEqual(parse_due('2030-01-01T08:00:00+08:00'), self.now)
        for value in ('2030-01-01T08:00:00', 'nonsense', None):
            with self.assertRaises(ValueError):
                parse_due(value)

    def test_no_empty_or_past_task(self):
        for title, due in [('', '2031-01-01T00:00:00Z'), ('report', '2029-01-01T00:00:00Z')]:
            with self.assertRaises(ValueError):
                validate_task(title, due, self.now)

    def test_reminder_lifecycle_and_restart(self):
        tid = self.store.add('报告', '2030-01-01T00:01:00Z', self.now)
        self.assertEqual(len(self.store.due(self.now)), 0)
        later = self.now + timedelta(minutes=2)
        self.assertEqual(len(self.store.due(later)), 1)
        self.store.mark_shown(tid)
        self.assertEqual(len(self.store.due(later)), 0)
        self.store.close()
        self.store = TaskStore(self.path)
        self.store.reset_notifications()
        self.assertEqual(len(self.store.due(later)), 1)
        self.store.snooze(tid, later)
        self.assertEqual(len(self.store.due(later)), 0)
        self.assertEqual(len(self.store.due(later + timedelta(minutes=10))), 1)
        self.store.complete(tid)
        self.assertEqual(len(self.store.pending()), 0)
        self.store.reset_notifications()
        self.assertEqual(len(self.store.due(later + timedelta(days=1))), 0)

    def test_reminders_stop_after_three_and_edit_resets(self):
        tid = self.store.add('报告', '2030-01-01T00:05:00Z', self.now)
        due = self.now + timedelta(minutes=6)
        self.assertEqual(self.store.mark_shown(tid), (1, False))
        self.store.reset_notifications()
        self.assertEqual(len(self.store.due(due)), 1)
        self.assertEqual(self.store.mark_shown(tid), (2, False))
        self.store.reset_notifications()
        self.assertEqual(self.store.mark_shown(tid), (3, True))
        self.assertEqual(self.store.due(due), [])
        self.store.reset_notifications()
        self.assertEqual(self.store.due(due), [])
        self.store.snooze(tid)
        self.assertEqual(self.store.due(due + timedelta(days=1)), [])
        row = self.store.pending()[0]
        self.assertEqual((row['remind_count'], row['deferred']), (3, 1))
        self.store.edit(tid, '报告', '2030-01-02T00:05:00Z', self.now)
        row = self.store.pending()[0]
        self.assertEqual((row['remind_count'], row['deferred']), (0, 0))

    def test_reopen_clears_deferred_state(self):
        tid = self.store.add('报告', '2030-01-01T00:05:00Z', self.now)
        for _ in range(3):
            self.store.mark_shown(tid)
        self.assertEqual(self.store.pending()[0]['deferred'], 1)
        self.store.complete(tid)
        self.store.reopen(tid)
        row = self.store.pending()[0]
        self.assertEqual((row['remind_count'], row['deferred']), (0, 0))
        self.assertIsNone(row['notified_at'])

    def test_edit_clears_notification_and_saves(self):
        tid = self.store.add('old', '2030-01-01T01:00:00Z', self.now)
        self.store.mark_shown(tid)
        self.store.edit(tid, 'new', '2030-01-02T01:00:00Z', self.now)
        row = self.store.pending()[0]
        self.assertEqual(row['title'], 'new')
        self.assertIsNone(row['notified_at'])

    def test_messages_order_and_limit(self):
        self.store.add_message('user', 'one')
        self.store.add_message('assistant', 'two')
        self.assertEqual(self.store.messages(1), [{'role': 'assistant', 'content': 'two'}])

    def test_ai_output_is_validated_without_saving(self):
        payload = {'reply': '建议如下', 'tasks': [
            {'title': 'valid', 'due_at': '2099-01-01T12:00:00+08:00'},
            {'title': 'bad', 'due_at': '2099-01-01T12:00:00'}, None]}
        reply, tasks, errors = decode_response(json.dumps(payload))
        self.assertEqual(reply, '建议如下')
        self.assertEqual(len(tasks), 1)
        self.assertEqual(len(errors), 2)
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(decode_response('plain text'), ('plain text', [], []))
        self.assertEqual(decode_response('[]'), ('[]', [], []))

    def test_markdown_reply_with_tasks_block(self):
        content = ('先用 **FTS5** 建索引：\n\n- 收集文档\n- 建表\n\n'
                   '```tasks\n[{"title":"整理文档","due_at":"2099-01-01T12:00:00+08:00","repeat":"daily"}]\n```')
        reply, tasks, errors = decode_response(content)
        self.assertEqual(reply, '先用 **FTS5** 建索引：\n\n- 收集文档\n- 建表')
        self.assertEqual(tasks, [{'title': '整理文档', 'due_at': '2099-01-01T12:00:00+08:00',
                                  'repeat': 'daily', 'dingtalk': False}])
        self.assertEqual(errors, [])
        self.assertEqual(decode_response('# 标题\n\n正文'), ('# 标题\n\n正文', [], []))
        reply, tasks, errors = decode_response('正文\n\n```tasks\n[oops]\n```')
        self.assertEqual(reply, '正文')
        self.assertEqual(tasks, [])
        self.assertEqual(errors, ['任务建议格式错误'])

    def test_decode_task_operations(self):
        tid = 'a' * 32
        content = ('好的。\n\n```tasks\n'
                   f'[{{"action":"update","id":"{tid}","title":"新标题"}},'
                   f'{{"action":"complete","id":"{tid}"}},'
                   f'{{"action":"delete","id":"{tid}"}}]\n```')
        reply, ops, errors = decode_response(content)
        self.assertEqual(reply, '好的。')
        self.assertEqual(ops, [{'action': 'update', 'id': tid, 'title': '新标题'},
                               {'action': 'complete', 'id': tid},
                               {'action': 'delete', 'id': tid}])
        self.assertEqual(errors, [])
        _, ops, errors = decode_response('```tasks\n[{"action":"update","id":"bad","title":"x"}]'
                                         '\n```')
        self.assertEqual(ops, [])
        self.assertEqual(len(errors), 1)
        _, ops, errors = decode_response('```tasks\n[{"action":"update","id":"' + tid + '"}]'
                                         '\n```')
        self.assertEqual(ops, [])
        self.assertEqual(errors, ['修改操作未指定任何内容'])
        _, ops, errors = decode_response('```tasks\n[{"action":"archive","id":"' + tid + '"}]'
                                         '\n```')
        self.assertEqual(ops, [])
        self.assertEqual(errors, ['不支持的任务操作'])

    def test_manage_request_requires_model(self):
        result = json.loads(local_reply('把交报告改成明天10点', self.now))
        self.assertEqual(result['tasks'], [])
        self.assertIn('待办页', result['reply'])
        result = json.loads(local_reply('明天15:00提醒我交报告', self.now))
        self.assertEqual(result['tasks'][0]['title'], '交报告')

    def test_model_payload_contains_pending_snapshot(self):
        tid = self.store.add('交报告', '2099-01-01T12:00:00+08:00', self.now)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, limit):
                return json.dumps({'choices': [{'message': {'content': 'hello'}}]}).encode()

        with patch('desktop_pet.assistant.request.build_opener') as mocked:
            mocked.return_value.open.return_value = Response()
            tasks = [dict(row) for row in self.store.pending()]
            ask({'base_url': 'https://example.com/v1', 'model': 'test'},
                [{'role': 'user', 'content': 'hi'}], tasks=tasks)
            system = json.loads(mocked.return_value.open.call_args.args[0].data)['messages'][0]
            self.assertEqual(system['role'], 'system')
            self.assertIn('当前未完成待办', system['content'])
            self.assertIn(tid, system['content'])
            self.assertIn('交报告', system['content'])

    def test_broken_legacy_envelope_is_recovered(self):
        broken = '{"reply":"别破坏 {"reply","tasks"} 的结构。\\n\\n工程建议：先做最小版","tasks":[]}'
        reply, tasks, errors = decode_response(broken)
        self.assertIn('工程建议：先做最小版', reply)
        self.assertIn('\n\n', reply)
        self.assertEqual(tasks, [])
        self.assertEqual(errors, [])

    def test_endpoint_security(self):
        self.assertEqual(validate_endpoint('https://example.com/v1/'), 'https://example.com/v1')
        self.assertEqual(validate_endpoint('http://localhost:1234/v1'), 'http://localhost:1234/v1')
        for url in ('http://example.com/v1', 'file:///tmp/key', 'https://user:secret@example.com', 'https://example.com?key=secret'):
            with self.assertRaises(ValueError):
                validate_endpoint(url)

    def test_dingtalk_flag_roundtrip_and_repeat_inheritance(self):
        tid = self.store.add('交报告', '2099-01-01T12:00:00+08:00', self.now, repeat='daily', dingtalk=True)
        self.assertEqual(self.store.pending()[0]['dingtalk'], 1)
        next_id = self.store.complete(tid)
        self.assertEqual(self.store.pending()[0]['id'], next_id)
        self.assertEqual(self.store.pending()[0]['dingtalk'], 1)
        self.store.edit(next_id, '交报告', '2099-01-02T12:00:00+08:00', repeat='daily', dingtalk=False)
        self.assertEqual(self.store.pending()[0]['dingtalk'], 0)
        self.store.edit(next_id, '交报告', '2099-01-02T12:00:00+08:00', repeat='daily')
        self.assertEqual(self.store.pending()[0]['dingtalk'], 0)
        self.store.set_dingtalk(next_id)
        self.assertEqual(self.store.pending()[0]['dingtalk'], 1)

    def test_local_rule_and_invalid_time(self):
        result = json.loads(local_reply('明天15:00提醒我交报告', self.now))
        self.assertEqual(result['tasks'][0]['title'], '交报告')
        self.assertEqual(parse_due(result['tasks'][0]['due_at']).day, 2)
        self.assertFalse(result['tasks'][0]['dingtalk'])
        result = json.loads(local_reply('明天15:00提醒我交报告，钉钉群通知', self.now))
        self.assertEqual(result['tasks'][0]['title'], '交报告')
        self.assertTrue(result['tasks'][0]['dingtalk'])
        self.assertEqual(json.loads(local_reply('今天00:00提醒我交报告', self.now))['tasks'], [])
        self.assertEqual(json.loads(local_reply('明天25:90提醒我交报告', self.now))['tasks'], [])

    def test_network_payload_and_no_redirect(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, limit):
                return json.dumps({'choices': [{'message': {'content': 'hello'}}]}).encode()

        with patch('desktop_pet.assistant.request.build_opener') as mocked:
            mocked.return_value.open.return_value = Response()
            result = ask({'base_url': 'https://example.com/v1', 'model': 'test', 'api_key': 'fake'},
                         [{'role': 'user', 'content': 'hi'}])
            self.assertEqual(result, 'hello')
            req = mocked.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url, 'https://example.com/v1/chat/completions')
            self.assertEqual(json.loads(req.data)['messages'][-1]['content'], 'hi')
            self.assertNotIn('fake', req.full_url)

    def test_draft_confirmation_is_atomic_and_not_repeatable(self):
        draft_id = self.store.save_draft('draft', '2099-01-01T12:00:00Z')
        self.store.save_draft('edited', '2099-01-02T12:00:00Z', draft_id)
        self.store.close()
        self.store = TaskStore(self.path)
        self.assertEqual(self.store.drafts()[0]['title'], 'edited')
        self.store.confirm_draft(draft_id)
        self.assertEqual(self.store.drafts(), [])
        self.assertEqual(self.store.pending()[0]['title'], 'edited')
        with self.assertRaises(ValueError):
            self.store.confirm_draft(draft_id)
        self.assertEqual(len(self.store.pending()), 1)

    def test_expired_draft_stays_editable_and_is_not_saved(self):
        draft_id = self.store.save_draft('', '2000-01-01T12:00:00Z')
        with self.assertRaises(ValueError):
            self.store.confirm_draft(draft_id)
        self.assertEqual(len(self.store.drafts()), 1)
        self.assertEqual(self.store.pending(), [])
        self.store.discard_draft(draft_id)
        self.assertEqual(self.store.drafts(), [])

    def test_history_search_delete_undo_and_reopen(self):
        tid = self.store.add('报告100%', '2030-01-01T01:00:00Z', self.now)
        self.store.complete(tid)
        self.assertEqual(len(self.store.history('done', '%')), 1)
        self.store.delete(tid)
        self.assertEqual(self.store.history('done'), [])
        self.store.undo_delete(tid)
        self.assertEqual(len(self.store.history('done')), 1)
        self.assertEqual(self.store.pending(), [])
        self.store.reopen(tid)
        self.store.delete(tid)
        self.assertEqual(self.store.due(self.now + timedelta(days=1)), [])
        self.store.undo_delete(tid)
        self.assertEqual(len(self.store.due(self.now + timedelta(days=1))), 1)
        self.assertEqual(self.store.history('pending', 'missing'), [])

    def test_v1_upgrade_backups_and_preserves_user_data(self):
        tid = self.store.add('existing', '2030-01-01T01:00:00Z', self.now)
        self.store.add_message('user', 'keep me')
        self.store.db.execute('DROP TABLE drafts')
        self.store.db.execute('PRAGMA user_version=1')
        self.store.db.commit()
        self.store.close()
        self.store = TaskStore(self.path)
        self.assertEqual(self.store.db.execute('PRAGMA user_version').fetchone()[0], 7)
        self.assertEqual(self.store.pending()[0]['id'], tid)
        self.assertEqual(self.store.pending()[0]['dingtalk'], 0)
        self.assertEqual(self.store.pending()[0]['remind_count'], 0)
        self.assertEqual(self.store.pending()[0]['deferred'], 0)
        self.assertEqual(self.store.messages()[0]['content'], 'keep me')
        self.assertEqual(len(list(Path(self.temp.name).glob('*.bak'))), 1)
        self.assertEqual(self.store.drafts(), [])

    def test_session_context_and_drafts_are_isolated(self):
        first = self.store.create_session()
        second = self.store.create_session('学习')
        self.store.add_message('user', '工作安排', first)
        self.store.add_message('assistant', 'work reply', first)
        self.store.add_message('user', 'study', second)
        self.assertEqual(self.store.session(first)['title'], '工作安排')
        self.assertEqual([m['content'] for m in self.store.messages(session_id=second)], ['study'])
        self.assertEqual(self.store.messages(), [])
        self.store.save_draft('work task', '2099-01-01T12:00:00Z', session_id=first)
        self.assertEqual(len(self.store.drafts(first)), 1)
        self.assertEqual(self.store.drafts(second), [])
        self.store.save_input(first, 'unsent work')
        self.store.save_input(second, 'unsent study')
        self.store.rename_session(first, '项目')
        self.store.close()
        self.store = TaskStore(self.path)
        self.assertEqual(self.store.session(first)['input_text'], 'unsent work')
        self.assertEqual(self.store.session(first)['title'], '项目')
        self.assertEqual(self.store.session(second)['input_text'], 'unsent study')
        for title in ('', 'x' * 61):
            with self.assertRaises(ValueError):
                self.store.rename_session(first, title)

    def test_actual_v2_schema_upgrade_and_backup(self):
        old_path = Path(self.temp.name) / 'old-v2.db'
        with sqlite3.connect(old_path) as old:
            old.executescript('''
                CREATE TABLE tasks (id TEXT PRIMARY KEY,title TEXT NOT NULL,due_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',notified_at TEXT,created_at TEXT NOT NULL);
                CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE drafts(id TEXT PRIMARY KEY,title TEXT NOT NULL,due_at TEXT NOT NULL,created_at TEXT NOT NULL);
                INSERT INTO messages(role,content,created_at) VALUES('user','legacy message','2030-01-01');
                INSERT INTO drafts VALUES('legacy-draft','legacy title','2099-01-01T12:00:00Z','2030-01-01');
                PRAGMA user_version=2;
            ''')
        old.close()
        upgraded = TaskStore(old_path)
        try:
            self.assertEqual(upgraded.messages()[0]['content'], 'legacy message')
            self.assertEqual(upgraded.drafts('default')[0]['id'], 'legacy-draft')
            self.assertEqual(len(upgraded.sessions()), 1)
            self.assertEqual(len(list(Path(self.temp.name).glob('old-v2.db.v2-*.bak'))), 1)
        finally:
            upgraded.close()


    def test_v6_upgrade_backs_up_and_adds_v7_columns(self):
        old_path = Path(self.temp.name) / 'old-v6.db'
        with sqlite3.connect(old_path) as old:
            old.executescript('''
                CREATE TABLE tasks (id TEXT PRIMARY KEY,title TEXT NOT NULL,due_at TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'pending',notified_at TEXT,created_at TEXT NOT NULL,
                  dingtalk INTEGER NOT NULL DEFAULT 0,remind_count INTEGER NOT NULL DEFAULT 0,
                  deferred INTEGER NOT NULL DEFAULT 0,repeat_rule TEXT NOT NULL DEFAULT 'none',
                  scheduled_at TEXT,next_id TEXT);
                CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE drafts(id TEXT PRIMARY KEY,title TEXT NOT NULL,due_at TEXT NOT NULL,created_at TEXT NOT NULL,
                  session_id TEXT NOT NULL DEFAULT 'default',repeat_rule TEXT NOT NULL DEFAULT 'none');
                INSERT INTO tasks(id,title,due_at,created_at)
                  VALUES('legacy','旧任务','2099-01-01T00:00:00+00:00','2030-01-01T00:00:00+00:00');
                INSERT INTO drafts VALUES('legacy-draft','旧草稿','2099-01-02T00:00:00+00:00','2030-01-01','default','none');
                PRAGMA user_version=6;
            ''')
        old.close()
        upgraded = TaskStore(old_path)
        try:
            self.assertEqual(upgraded.db.execute('PRAGMA user_version').fetchone()[0], 7)
            row = upgraded.pending()[0]
            self.assertEqual(row['id'], 'legacy')
            self.assertIsNone(row['completed_at'])
            self.assertIsNone(row['muted_until'])
            self.assertIsNone(row['early_notified_at'])
            self.assertEqual((row['source'], row['note']), ('manual', ''))
            self.assertEqual(upgraded.drafts('default')[0]['note'], '')
            self.assertIsNotNone(upgraded.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_events'").fetchone())
            self.assertEqual(len(list(Path(self.temp.name).glob('old-v6.db.v6-*.bak'))), 1)
        finally:
            upgraded.close()

    def test_stats_completion_and_cross_midnight(self):
        tz = timezone(timedelta(hours=8))
        day1 = datetime(2030, 1, 2, 23, 40, tzinfo=tz)
        first = self.store.add('按时', datetime(2030, 1, 2, 23, 55, tzinfo=tz).isoformat(), day1)
        second = self.store.add('跨夜', datetime(2030, 1, 2, 23, 58, tzinfo=tz).isoformat(), day1)
        self.store.mark_shown(first, day1)
        self.store.complete(first, datetime(2030, 1, 2, 23, 50, tzinfo=tz))
        self.store.complete(second, datetime(2030, 1, 3, 0, 5, tzinfo=tz))
        completed = self.store.db.execute('SELECT completed_at FROM tasks WHERE id=?', (first,)).fetchone()[0]
        self.assertEqual(parse_due(completed), datetime(2030, 1, 2, 15, 50, tzinfo=timezone.utc))

        today = self.store.today_stats(datetime(2030, 1, 2, 23, 59, tzinfo=tz))
        self.assertEqual((today['completed_today'], today['reminders_today'], today['on_time_rate']), (1, 1, 1.0))
        self.assertEqual(today['week_on_time_dates'], ['2030-01-02'])
        tomorrow = self.store.today_stats(datetime(2030, 1, 3, 0, 10, tzinfo=tz))
        self.assertEqual((tomorrow['completed_today'], tomorrow['reminders_today'], tomorrow['on_time_rate']), (1, 0, 0.0))
        self.assertEqual(tomorrow['week_on_time_days'], 1)
        self.assertEqual(tomorrow['week_on_time_dates'], ['2030-01-02'])

        events = self.store.today_events(datetime(2030, 1, 2, 23, 59, tzinfo=tz))
        self.assertEqual([event['kind'] for event in events], ['created', 'created', 'reminded', 'completed'])
        self.assertEqual([event['title'] for event in events], ['按时', '跨夜', '按时', '按时'])
        self.assertEqual([event['kind'] for event in self.store.today_events(
            datetime(2030, 1, 3, 0, 10, tzinfo=tz))], ['completed'])

        self.store.reopen(first)
        reopened = self.store.db.execute('SELECT completed_at FROM tasks WHERE id=?', (first,)).fetchone()[0]
        self.assertIsNone(reopened)

    def test_quiet_hours_wrap_midnight_and_validation(self):
        def at(hour, minute):
            return datetime(2030, 1, 1, hour, minute, tzinfo=timezone.utc)

        self.assertTrue(in_quiet_hours(at(23, 0)))
        self.assertTrue(in_quiet_hours(at(0, 0)))
        self.assertTrue(in_quiet_hours(at(7, 29)))
        self.assertFalse(in_quiet_hours(at(7, 30)))
        self.assertFalse(in_quiet_hours(at(12, 0)))
        self.assertTrue(in_quiet_hours(at(13, 0), '12:00', '14:00'))
        self.assertFalse(in_quiet_hours(at(13, 0), '13:00', '13:00'))
        self.assertEqual(parse_clock('7:05'), '07:05')
        for value in ('24:00', '7:5', '', None):
            with self.assertRaises(ValueError):
                parse_clock(value)

    def test_early_nudge_mute_and_next_day(self):
        tz = timezone(timedelta(hours=8))
        now = datetime(2030, 1, 2, 10, 0, tzinfo=tz)
        soon = self.store.add('十点零五', datetime(2030, 1, 2, 10, 5, tzinfo=tz).isoformat(), now)
        later = self.store.add('十点零八', datetime(2030, 1, 2, 10, 8, tzinfo=tz).isoformat(), now)
        self.assertEqual([row['id'] for row in self.store.early_due(now)], [soon, later])
        self.store.mute_today(later, now)
        self.assertEqual([row['id'] for row in self.store.early_due(now)], [soon])
        self.assertTrue(self.store.mark_early_shown(soon, now))
        self.assertFalse(self.store.mark_early_shown(soon, now))
        self.assertEqual(self.store.early_due(now), [])
        muted = self.store.db.execute('SELECT muted_until FROM tasks WHERE id=?', (later,)).fetchone()[0]
        self.assertEqual(muted, '2030-01-02')
        self.store.mute_today(soon, now)
        self.assertEqual(self.store.due(datetime(2030, 1, 2, 10, 30, tzinfo=tz)), [])
        next_day = [row['id'] for row in self.store.due(datetime(2030, 1, 3, 10, 30, tzinfo=tz))]
        self.assertIn(later, next_day)
        kinds = [row[0] for row in self.store.db.execute(
            "SELECT kind FROM task_events WHERE task_id=? ORDER BY id", (later,))]
        self.assertEqual(kinds, ['created', 'muted'])

    def test_export_redacts_and_clear_keeps_restorable_backup(self):
        tid = self.store.add('保留', '2099-01-01T00:00:00Z', self.now)
        self.store.add_message('user', 'hello')
        self.store.save_draft('draft', '2099-01-02T00:00:00Z', note='备注')
        self.store.mark_shown(tid, self.now)
        export = Path(self.temp.name) / 'export.json'
        self.store.export_data(export)
        text = export.read_text(encoding='utf-8')
        payload = json.loads(text)
        for key in ('api_key', 'secret', 'webhook', 'authorization', 'dpapi'):
            self.assertNotIn(key, text.lower())
        self.assertEqual(len(payload['tasks']), 1)
        self.assertEqual(payload['drafts'][0]['note'], '备注')
        self.assertGreaterEqual(len(payload['task_events']), 2)

        backup = self.store.clear_data()
        self.assertTrue(backup and Path(backup).is_file())
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.messages(), [])
        self.assertEqual(self.store.drafts(), [])
        self.assertEqual([row['id'] for row in self.store.sessions()], ['default'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM task_events').fetchone()[0], 0)
        old = sqlite3.connect(backup)
        try:
            self.assertEqual(old.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 1)
            self.assertEqual(old.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 1)
        finally:
            old.close()

    def test_connection_test_reports_status_without_secrets(self):
        from urllib import error as urlerror

        settings = {'base_url': 'https://example.com/v1', 'model': 'm', 'api_key': 'sk-should-not-leak'}
        with patch('desktop_pet.assistant.request.build_opener') as build:
            build.return_value.open.side_effect = urlerror.HTTPError(
                'https://example.com', 401, 'Unauthorized', {}, None)
            with self.assertRaises(ValueError) as caught:
                test_connection(settings)
        message = str(caught.exception)
        self.assertIn('HTTP 401', message)
        self.assertNotIn('sk-should-not-leak', message)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size):
                return b'{}'

        with patch('desktop_pet.assistant.request.build_opener') as build:
            build.return_value.open.return_value = Response()
            self.assertIsInstance(test_connection(settings, timeout=3), int)
        with self.assertRaises(ValueError):
            test_connection({'base_url': '', 'model': ''})


if __name__ == '__main__':
    unittest.main()
