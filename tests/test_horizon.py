from qt_support import QT_APP
import json
import sqlite3
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from desktop_pet.app import MainWindow
from desktop_pet.assistant import local_reply
from desktop_pet.core import TaskStore, _decode_tasks, horizon_deadline, parse_due


def local_at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute).astimezone()


class HorizonDeadlineTests(unittest.TestCase):
    def test_week_ends_sunday_and_reminds_friday(self):
        now = local_at(2026, 11, 18, 10)  # 周三
        due, remind = horizon_deadline('week', now)
        due, remind = due.astimezone(), remind.astimezone()
        self.assertEqual(due.date().isoformat(), '2026-11-22')
        self.assertEqual((due.hour, due.minute, due.second), (23, 59, 59))
        self.assertEqual(remind.date().isoformat(), '2026-11-20')
        self.assertEqual((remind.hour, remind.minute), (17, 0))

    def test_week_created_after_friday_reminder_stays_silent(self):
        now = local_at(2026, 11, 21, 9)  # 周六
        due, remind = horizon_deadline('week', now)
        self.assertEqual(due.astimezone().date().isoformat(), '2026-11-22')
        self.assertIsNone(remind)

    def test_month_reminder_moves_back_to_workday(self):
        now = local_at(2026, 10, 15, 10)
        due, remind = horizon_deadline('month', now)
        self.assertEqual(due.astimezone().date().isoformat(), '2026-10-31')
        self.assertEqual(remind.astimezone().date().isoformat(), '2026-10-30')

    def test_plain_horizons_have_no_deadline(self):
        now = local_at(2026, 11, 18, 10)
        self.assertEqual(horizon_deadline('timed', now), (None, None))
        self.assertEqual(horizon_deadline('someday', now), (None, None))
        with self.assertRaises(ValueError):
            horizon_deadline('year', now)


class HorizonStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp.name) / 'tasks.db')
        self.now = local_at(2026, 11, 18, 10)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def row(self, task_id):
        return self.store.db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()

    def test_add_fills_each_horizon(self):
        week = self.store.add('周报', horizon='week', repeat='daily', now=self.now)
        row = self.row(week)
        self.assertEqual(row['horizon'], 'week')
        self.assertEqual(row['repeat_rule'], 'none')
        self.assertEqual(parse_due(row['due_at']).astimezone().strftime('%Y-%m-%d %H:%M:%S'), '2026-11-22 23:59:59')
        self.assertEqual(parse_due(row['remind_at']).astimezone().strftime('%Y-%m-%d %H:%M'), '2026-11-20 17:00')
        self.assertEqual(row['scheduled_at'], row['due_at'])

        month = self.store.add('月报', horizon='month', now=self.now)
        row = self.row(month)
        self.assertEqual(parse_due(row['due_at']).astimezone().date().isoformat(), '2026-11-30')
        self.assertEqual(parse_due(row['remind_at']).astimezone().strftime('%Y-%m-%d %H:%M'), '2026-11-30 17:00')

        someday = self.store.add('整理书架', horizon='someday', repeat='daily', now=self.now)
        row = self.row(someday)
        self.assertEqual((row['due_at'], row['remind_at'], row['scheduled_at']), (None, None, None))
        self.assertEqual(row['repeat_rule'], 'none')

        timed = self.store.add('喝水', (self.now + timedelta(hours=1)).isoformat(), now=self.now)
        row = self.row(timed)
        self.assertEqual(row['horizon'], 'timed')
        self.assertEqual(row['remind_at'], row['due_at'])

        with self.assertRaises(ValueError):
            self.store.add('无效', horizon='year', now=self.now)

    def test_due_and_early_nudge_use_reminder_moment(self):
        bucket = self.store.add('周报', horizon='week', now=self.now)
        self.assertEqual(self.store.due(self.now), [])
        friday = local_at(2026, 11, 20, 17, 1)
        self.assertEqual([task['id'] for task in self.store.due(friday)], [bucket])

        early = local_at(2026, 11, 20, 16, 55)
        timed = self.store.add('临时', (early + timedelta(minutes=5)).isoformat(), now=early)
        self.assertEqual([task['id'] for task in self.store.early_due(early)], [timed])

    def test_snooze_bucket_moves_only_the_reminder(self):
        bucket = self.store.add('周报', horizon='week', now=self.now)
        before = self.row(bucket)
        friday = local_at(2026, 11, 20, 17, 1)
        self.store.snooze(bucket, now=friday, minutes=15)
        after = self.row(bucket)
        self.assertEqual(after['due_at'], before['due_at'])
        self.assertEqual(parse_due(after['remind_at']), (friday + timedelta(minutes=15)).astimezone(timezone.utc))
        self.assertIsNone(after['notified_at'])

        someday = self.store.add('整理书架', horizon='someday', now=self.now)
        self.store.snooze(someday, now=friday)
        row = self.row(someday)
        self.assertEqual((row['due_at'], row['remind_at'], row['notified_at']), (None, None, None))

    def test_edit_switches_between_horizons(self):
        task_id = self.store.add('任务', (self.now + timedelta(hours=2)).isoformat(), now=self.now)
        self.store.edit(task_id, '任务', now=self.now, horizon='someday')
        row = self.row(task_id)
        self.assertEqual((row['horizon'], row['due_at'], row['remind_at']), ('someday', None, None))

        self.store.edit(task_id, '任务', now=self.now, horizon='week')
        row = self.row(task_id)
        self.assertEqual(row['horizon'], 'week')
        self.assertEqual(parse_due(row['due_at']).astimezone().date().isoformat(), '2026-11-22')
        self.assertEqual(row['repeat_rule'], 'none')

        due = (self.now + timedelta(hours=5)).isoformat()
        self.store.edit(task_id, '任务', due=due, now=self.now, horizon='timed')
        row = self.row(task_id)
        self.assertEqual(row['horizon'], 'timed')
        self.assertEqual(row['remind_at'], parse_due(due).isoformat())

    def test_inbox_count_and_someday_completion(self):
        first = self.store.add('整理书架', horizon='someday', now=self.now)
        second = self.store.add('看牙医', horizon='someday', now=self.now)
        timed = self.store.add('喝水', (self.now + timedelta(hours=1)).isoformat(), now=self.now)
        self.assertEqual(self.store.inbox_count(), 2)
        self.assertEqual([row['id'] for row in self.store.pending()], [timed, first, second])
        self.store.complete(first, now=self.now + timedelta(hours=1))
        self.assertEqual(self.store.inbox_count(), 1)
        detail = self.store.db.execute("SELECT detail FROM task_events WHERE task_id=? AND kind='completed'",
                                       (first,)).fetchone()[0]
        self.assertEqual(detail, 'on_time')

    def test_v7_upgrade_allows_someday_and_backs_up(self):
        old_path = Path(self.temp.name) / 'old-v7.db'
        with sqlite3.connect(old_path) as old:
            old.executescript('''
                CREATE TABLE tasks (id TEXT PRIMARY KEY,title TEXT NOT NULL,due_at TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'pending',notified_at TEXT,created_at TEXT NOT NULL,
                  dingtalk INTEGER NOT NULL DEFAULT 0,remind_count INTEGER NOT NULL DEFAULT 0,
                  deferred INTEGER NOT NULL DEFAULT 0,repeat_rule TEXT NOT NULL DEFAULT 'none',
                  scheduled_at TEXT,next_id TEXT,completed_at TEXT,
                  source TEXT NOT NULL DEFAULT 'manual',note TEXT NOT NULL DEFAULT '',
                  muted_until TEXT,early_notified_at TEXT);
                CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,role TEXT NOT NULL,
                  content TEXT NOT NULL,created_at TEXT NOT NULL,session_id TEXT NOT NULL DEFAULT 'default');
                CREATE TABLE drafts(id TEXT PRIMARY KEY,title TEXT NOT NULL,due_at TEXT NOT NULL,
                  created_at TEXT NOT NULL,session_id TEXT NOT NULL DEFAULT 'default',
                  repeat_rule TEXT NOT NULL DEFAULT 'none',note TEXT NOT NULL DEFAULT '');
                CREATE TABLE sessions(id TEXT PRIMARY KEY,title TEXT NOT NULL,
                  input_text TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL);
                INSERT INTO tasks(id,title,due_at,created_at,scheduled_at)
                  VALUES('legacy','旧任务','2099-01-01T09:00:00+00:00','2030-01-01','2099-01-01T09:00:00+00:00');
                PRAGMA user_version=7;
            ''')
        old.close()
        upgraded = TaskStore(old_path)
        try:
            self.assertEqual(upgraded.db.execute('PRAGMA user_version').fetchone()[0], 8)
            notnull = {row['name']: row['notnull'] for row in upgraded.db.execute('PRAGMA table_info(tasks)')}
            self.assertEqual(notnull['due_at'], 0)
            row = upgraded.pending()[0]
            self.assertEqual(row['horizon'], 'timed')
            self.assertEqual(row['remind_at'], row['due_at'])
            self.assertEqual(row['scheduled_at'], row['due_at'])
            self.assertEqual(len(list(Path(self.temp.name).glob('old-v7.db.v7-*.bak'))), 1)
            inbox = upgraded.add('整理书架', horizon='someday')
            self.assertEqual(upgraded.inbox_count(), 1)
            self.assertIsNone(upgraded.db.execute('SELECT due_at FROM tasks WHERE id=?', (inbox,)).fetchone()[0])
        finally:
            upgraded.close()


class DecodeHorizonTests(unittest.TestCase):
    def test_create_and_update_horizon(self):
        tasks, errors = _decode_tasks([
            {'title': '周报', 'horizon': 'week'},
            {'title': '月报', 'horizon': 'month'},
            {'title': '整理书架', 'horizon': 'someday'},
            {'title': '喝水', 'due_at': '2099-01-01T12:00:00+08:00'},
        ])
        self.assertEqual(errors, [])
        self.assertEqual([task['horizon'] for task in tasks], ['week', 'month', 'someday', 'timed'])
        self.assertEqual([task['due_at'] for task in tasks], [None, None, None, '2099-01-01T12:00:00+08:00'])

        tasks, errors = _decode_tasks([{'title': '周报', 'horizon': 'week', 'repeat': 'daily'}])
        self.assertEqual((errors, tasks[0]['repeat']), ([], 'none'))

        tasks, errors = _decode_tasks([{'action': 'update', 'id': 'a' * 32, 'horizon': 'month'}])
        self.assertEqual((errors, tasks[0]['horizon']), ([], 'month'))

        tasks, errors = _decode_tasks([{'title': 'x', 'horizon': 'year'}])
        self.assertEqual(tasks, [])
        self.assertTrue(errors)


class LocalReplyHorizonTests(unittest.TestCase):
    now = local_at(2026, 11, 18, 10)

    def reply(self, text):
        payload = json.loads(local_reply(text, self.now))
        return payload['reply'], payload['tasks']

    def test_week_and_month_buckets(self):
        _, tasks = self.reply('这周提醒我写周报')
        self.assertEqual(tasks, [{'title': '写周报', 'horizon': 'week', 'repeat': 'none', 'dingtalk': False}])
        _, tasks = self.reply('提醒我这周内完成周报')
        self.assertEqual((tasks[0]['title'], tasks[0]['horizon']), ('周报', 'week'))
        _, tasks = self.reply('本月提醒我交水电费')
        self.assertEqual((tasks[0]['title'], tasks[0]['horizon']), ('交水电费', 'month'))

    def test_someday_only_without_time_hint(self):
        _, tasks = self.reply('提醒我整理书架')
        self.assertEqual(tasks, [{'title': '整理书架', 'horizon': 'someday', 'repeat': 'none', 'dingtalk': False}])
        _, tasks = self.reply('明天提醒我交报告')
        self.assertEqual(tasks, [])

    def test_timed_request_unchanged(self):
        _, tasks = self.reply('明天15:00提醒我交报告')
        due = parse_due(tasks[0]['due_at']).astimezone()
        self.assertEqual(due.strftime('%Y-%m-%d %H:%M'), '2026-11-19 15:00')
        self.assertEqual(tasks[0]['repeat'], 'none')


class FakePet:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


class FakeBridge:
    def __init__(self):
        self.events = []

    def emit_event(self, name, payload):
        self.events.append((name, payload))


class InboxReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp.name) / 'tasks.db')
        self.store.add('整理书架', horizon='someday', now=local_at(2026, 11, 18, 9))
        self.pet = FakePet()
        self.bridge = FakeBridge()
        self.saved = []
        self.window = types.SimpleNamespace(settings={}, store=self.store, pet=self.pet,
                                            bridge=self.bridge,
                                            persist_settings=lambda: self.saved.append(dict(self.window.settings)))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def review(self, now, quiet=''):
        MainWindow.check_inbox_review(self.window, now, quiet)

    def test_friday_evening_reviews_once_per_week(self):
        self.review(local_at(2026, 11, 20, 17, 1))
        self.assertEqual(len(self.pet.said), 1)
        self.assertIn('1 项', self.pet.said[0])
        self.assertEqual(self.bridge.events, [('inbox.review', {'count': 1})])
        self.assertEqual(self.window.settings['last_inbox_review'], '2026-11-20')
        self.assertTrue(self.saved)

        self.review(local_at(2026, 11, 20, 18))
        self.assertEqual(len(self.pet.said), 1)

        self.review(local_at(2026, 11, 27, 17, 1))
        self.assertEqual(len(self.pet.said), 2)

    def test_other_moments_are_silent(self):
        self.review(local_at(2026, 11, 20, 16, 59))
        self.review(local_at(2026, 11, 21, 17, 30))
        self.review(local_at(2026, 11, 20, 17, 30), quiet='dnd')
        self.assertEqual(self.pet.said, [])
        self.assertNotIn('last_inbox_review', self.window.settings)

    def test_empty_inbox_is_silent(self):
        for row in self.store.pending():
            self.store.complete(row['id'], now=local_at(2026, 11, 19, 9))
        self.review(local_at(2026, 11, 20, 17, 1))
        self.assertEqual(self.pet.said, [])


if __name__ == '__main__':
    unittest.main()
