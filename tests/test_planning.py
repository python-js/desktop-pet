"""Daily planning boundaries and prompt budget."""
import json
import unittest
from datetime import datetime

from desktop_pet.planning import daily_snapshot, planning_prompt, local_plan


class PlanningTests(unittest.TestCase):
    def task(self, title, due, status='pending'):
        return dict(title=title, due_at=due, status=status, repeat_rule='none')

    def test_local_day_timezone_and_pending_only(self):
        now = datetime.fromisoformat('2026-10-26T10:00:00+08:00')
        rows = [self.task('overdue', '2026-10-26T01:59:00Z'),
                self.task('today', '2026-10-26T15:59:00Z'),
                self.task('tomorrow', '2026-10-26T16:00:00Z'),
                self.task('done', '2026-10-26T02:00:00Z', 'done')]
        snapshot = daily_snapshot(rows, now)
        self.assertEqual((snapshot['overdue_count'], snapshot['today_count'], snapshot['future_count']), (1, 1, 1))
        self.assertEqual(snapshot['today'][0]['title'], 'today')
        self.assertNotIn('tomorrow', planning_prompt(snapshot))
        reply = json.loads(local_plan(snapshot))
        self.assertEqual(reply['tasks'], [])
        self.assertIn('未调用模型', reply['reply'])

    def test_large_backlog_keeps_today_and_reports_truncation(self):
        now = datetime.fromisoformat('2026-10-26T10:00:00+08:00')
        rows = [self.task('x' * 200, '2026-10-25T10:00:00+08:00') for _ in range(100)]
        rows.append(self.task('today', '2026-10-26T11:00:00+08:00'))
        snapshot = daily_snapshot(rows, now)
        self.assertEqual(snapshot['omitted'], 71)
        self.assertEqual(len(snapshot['overdue']), 29)
        self.assertEqual(snapshot['today'][0]['title'], 'today')
        self.assertLess(len(planning_prompt(snapshot)), 12000)
        self.assertIn('71', json.loads(local_plan(snapshot))['reply'])

    def test_empty_and_naive_time(self):
        self.assertIn('今天没有', json.loads(local_plan(daily_snapshot([])))['reply'])
        with self.assertRaises(ValueError):
            daily_snapshot([], datetime(2026, 10, 26))
