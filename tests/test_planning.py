from qt_support import QT_APP
"""Daily planning boundaries and read-only UI integration."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

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

    def test_ui_preview_cancel_local_and_model_snapshot(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication, QDialog
        from PyQt5.QtTest import QTest
        from desktop_pet.app import MainWindow
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
            window = MainWindow()
            window.timer.stop()
            try:
                now = datetime.now(timezone.utc)
                window.store.add('plan me', (now + timedelta(minutes=1)).isoformat())
                window.input.setPlainText('keep my draft')
                before = [dict(t) for t in window.store.pending()]
                with patch('desktop_pet.app.QDialog.exec_', return_value=QDialog.Rejected):
                    window.plan_today()
                self.assertEqual(window.store.messages(), [])
                with patch('desktop_pet.app.QDialog.exec_', return_value=QDialog.Accepted):
                    window.plan_today()
                self.assertIsNone(window.worker)
                self.assertIn('plan me', window.history.toPlainText())
                self.assertEqual(window.input.toPlainText(), 'keep my draft')
                self.assertEqual(window.store.drafts(), [])
                self.assertEqual([dict(t) for t in window.store.pending()], before)
                window.settings.update(model='test', base_url='https://example.com/v1')
                with patch('desktop_pet.app.ask', return_value='{"reply":"model plan","tasks":[]}') as ask:
                    with patch('desktop_pet.app.QDialog.exec_', return_value=QDialog.Accepted):
                        window.plan_today()
                    self.assertFalse(window.plan_button.isEnabled())
                    for _ in range(100):
                        QTest.qWait(10)
                        if window.worker is None:
                            break
                    self.assertIsNone(window.worker)
                    self.assertIn('plan me', ask.call_args.args[1][-1]['content'])
                    self.assertIn('model plan', window.history.toPlainText())
                self.assertTrue(window.plan_button.isEnabled())
                self.assertEqual(window.input.toPlainText(), 'keep my draft')
                self.assertEqual([dict(t) for t in window.store.pending()], before)
            finally:
                if window.worker:
                    window.worker.cancel()
                    window.worker.wait(3000)
                    app.processEvents()
                window.shutting_down = True
                window.timer.stop()
                window.task_refresh_timer.stop()
                window.pet.close()
                window.tray.hide()
                window.close()
                window.store.close()
                window.deleteLater()
                app.processEvents()
