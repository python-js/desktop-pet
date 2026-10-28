import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from desktop_pet.assistant import local_reply
from desktop_pet.core import TaskStore, parse_due, decode_response
from desktop_pet.recurrence import next_occurrence, in_period


class RecurrenceTests(unittest.TestCase):
    def test_calendar_offsets_leap_day_and_skipped_days(self):
        now = parse_due('2032-02-28T09:30:00+08:00')
        self.assertEqual(next_occurrence('2032-02-28T09:00:00+08:00', 'daily', now).isoformat(), '2032-02-29T09:00:00+08:00')
        now = parse_due('2032-03-05T10:00:00+08:00')
        self.assertEqual(next_occurrence('2032-02-28T09:00:00+08:00', 'daily', now).isoformat(), '2032-03-06T09:00:00+08:00')
        now = parse_due('2030-01-04T10:00:00+08:00')  # Friday
        self.assertEqual(next_occurrence('2030-01-04T09:00:00+08:00', 'weekdays', now).isoformat(), '2030-01-07T09:00:00+08:00')
        self.assertEqual(next_occurrence('2030-01-04T09:00:00+08:00', 'weekly', now).isoformat(), '2030-01-11T09:00:00+08:00')

    def test_local_rules_generate_first_future_occurrence(self):
        now = datetime.fromisoformat('2030-01-04T16:00:00+08:00')
        for command, repeat, day in [('每天15:00提醒我喝水', 'daily', 5),
                                     ('每个工作日15:00提醒我报告', 'weekdays', 7),
                                     ('每周五15:00提醒我周报', 'weekly', 11)]:
            task = json.loads(local_reply(command, now))['tasks'][0]
            self.assertEqual(task['repeat'], repeat)
            self.assertEqual(datetime.fromisoformat(task['due_at']).day, day)

    def test_bad_model_repeat_does_not_crash_or_create_suggestion(self):
        for repeat in ([], {}, 'monthly', 3):
            _, tasks, errors = decode_response(json.dumps({'reply': 'hi', 'tasks': [
                {'title': 'bad', 'due_at': '2099-01-01T09:00:00Z', 'repeat': repeat}]}))
            self.assertEqual(tasks, [])
            self.assertEqual(len(errors), 1)

    def test_periods_respect_local_midnight(self):
        now = datetime.fromisoformat('2030-01-02T00:05:00+08:00')
        yesterday = parse_due('2030-01-01T23:59:00+08:00')
        today = parse_due('2030-01-02T09:00:00+08:00')
        tomorrow = parse_due('2030-01-03T00:00:00+08:00')
        self.assertTrue(in_period(yesterday, 'overdue', now))
        self.assertFalse(in_period(yesterday, 'today', now))
        self.assertTrue(in_period(today, 'today', now))
        self.assertFalse(in_period(today, 'future', now))
        self.assertTrue(in_period(tomorrow, 'future', now))

    def test_complete_snooze_and_duplicate_clicks(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TaskStore(Path(folder) / 'db')
            try:
                creation = parse_due('2030-01-01T00:00:00Z')
                tid = store.add('daily', '2030-01-02T09:00:00+08:00', creation, repeat='daily')
                snoozed_at = parse_due('2030-01-02T10:00:00+08:00')
                store.snooze(tid, snoozed_at)
                row = store.pending()[0]
                store.edit(tid, 'renamed', row['due_at'], creation)
                next_id = store.complete(tid, snoozed_at + timedelta(minutes=11))
                self.assertIsNotNone(next_id)
                self.assertIsNone(store.complete(tid, snoozed_at))
                row = store.pending()[0]
                self.assertEqual(row['title'], 'renamed')
                self.assertEqual(row['due_at'], parse_due('2030-01-03T09:00:00+08:00').isoformat())
                self.assertEqual(row['repeat_rule'], 'daily')
                self.assertEqual(len(store.history('done')), 1)
                with self.assertRaises(ValueError):
                    store.reopen(tid)
                store.delete(next_id)
                self.assertEqual(store.pending(), [])
                store.undo_delete(next_id)
                self.assertEqual(len(store.pending()), 1)
                store.edit(next_id, 'one-off now', row['due_at'], creation, repeat='none')
                self.assertIsNone(store.complete(next_id, creation))
                self.assertEqual(store.pending(), [])
            finally:
                store.close()

    def test_repeated_draft_keeps_rule_on_confirmation(self):
        store = TaskStore(':memory:')
        try:
            draft_id = store.save_draft('daily', '2099-01-01T09:00:00+08:00', repeat='daily')
            store.confirm_draft(draft_id)
            row = store.pending()[0]
            self.assertEqual(row['repeat_rule'], 'daily')
            self.assertEqual(row['scheduled_at'], '2099-01-01T09:00:00+08:00')
        finally:
            store.close()

    def test_v3_migration_keeps_one_off_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'old.db'
            old = sqlite3.connect(path)
            old.executescript('''
                CREATE TABLE tasks (id TEXT PRIMARY KEY,title TEXT NOT NULL,due_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',notified_at TEXT,created_at TEXT NOT NULL);
                CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL,session_id TEXT NOT NULL DEFAULT 'default');
                CREATE TABLE drafts(id TEXT PRIMARY KEY,title TEXT NOT NULL,due_at TEXT NOT NULL,created_at TEXT NOT NULL,session_id TEXT NOT NULL DEFAULT 'default');
                INSERT INTO tasks(id,title,due_at,created_at) VALUES('old','old task','2099-01-01T09:00:00+00:00','2030-01-01');
                PRAGMA user_version=3;
            ''')
            old.close()
            store = TaskStore(path)
            try:
                self.assertEqual(store.pending()[0]['repeat_rule'], 'none')
                self.assertEqual(store.pending()[0]['scheduled_at'], '2099-01-01T09:00:00+00:00')
                self.assertEqual(len(list(Path(folder).glob('*.bak'))), 1)
                self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 6)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
