from qt_support import QT_APP
"""Offscreen integration smoke test. No real API calls or notifications."""
import importlib.util
import os
import tempfile
import unittest
from datetime import timedelta

HAS_QT = importlib.util.find_spec('PyQt5') is not None


@unittest.skipUnless(HAS_QT, 'PyQt5 未安装，跳过界面测试')
class UiSmokeTests(unittest.TestCase):
    def test_drafts_tasks_and_reminder(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow
        from desktop_pet.core import utc_now
        from unittest.mock import patch

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                try:
                    window.timer.stop()
                    window.settings.update({'dnd_enabled': False, 'early_nudge': False})
                    self.assertEqual(window.tabs.count(), 4)
                    window.add_draft({'title': 'test', 'due_at': '2099-01-01T12:00:00+08:00'})
                    self.assertEqual(window.drafts.count(), 1)
                    self.assertEqual(len(window.store.pending()), 0)
                    now = utc_now()
                    tid = window.store.add('reminder', (now - timedelta(minutes=1)).isoformat(), now - timedelta(minutes=2))
                    window.check_due()
                    self.assertIn(tid, window.reminders)
                    window.resolve(tid, True)
                    self.assertNotIn(tid, window.reminders)
                    self.assertEqual(len(window.store.due()), 0)
                    tid2 = window.store.add('close me', (now - timedelta(minutes=1)).isoformat(), now - timedelta(minutes=2))
                    window.check_due()
                    self.assertIn(tid2, window.reminders)
                    window.reminders[tid2].close()
                    app.processEvents()
                    self.assertNotIn(tid2, window.reminders)
                    window.store.delete(tid2)
                    window.resolve(tid, False)
                    self.assertEqual(len(window.store.pending()), 0)
                    window.task_segments.set_current('done', emit=True)
                    self.assertEqual(len(window.task_rows), 1)
                    first = window.task_rows[0]
                    first.set_picked(True)
                    window.on_task_pick(first.task['id'], True)
                    window.delete_selected()
                    self.assertEqual(len(window.task_rows), 0)
                    window.undo_delete()
                    self.assertEqual(len(window.task_rows), 1)
                    first = window.task_rows[0]
                    first.set_picked(True)
                    window.on_task_pick(first.task['id'], True)
                    window.complete_selected()
                    window.task_segments.set_current('pending', emit=True)
                    self.assertEqual(len(window.task_rows), 1)
                    window.task_search.setText('absent')
                    self.assertEqual(len(window.task_rows), 0)
                    self.assertEqual(len(window.store.drafts()), 1)
                    window.task_search.clear()
                    window.task_period.setCurrentIndex(window.task_period.findData('future'))
                    self.assertEqual(len(window.task_rows), 0)
                    window.store.add('overdue', (now - timedelta(minutes=1)).isoformat(), now - timedelta(minutes=2))
                    window.task_period.setCurrentIndex(window.task_period.findData('overdue'))
                    self.assertEqual(len(window.task_rows), 1)
                    card = window.drafts.itemAt(0).widget()
                    card.repeat.setCurrentIndex(card.repeat.findData('daily'))
                    card.save_button.click()
                    self.assertEqual(window.drafts.count(), 0)
                    window.task_period.setCurrentIndex(window.task_period.findData('future'))
                    self.assertEqual(len(window.task_rows), 1)
                    self.assertIn('每天', window.task_rows[0].meta.text())
                    first = window.task_rows[0]
                    first.set_picked(True)
                    window.on_task_pick(first.task['id'], True)
                    window.complete_selected()
                    self.assertEqual(len(window.task_rows), 1)
                    self.assertEqual(window.task_rows[0].task['repeat_rule'], 'daily')
                finally:
                    window.shutting_down = True
                    window.timer.stop()
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_only_dingtalk_flagged_tasks_push(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from datetime import timedelta
        from unittest.mock import patch
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow
        from desktop_pet.core import utc_now

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.settings.update({'dnd_enabled': False, 'early_nudge': False})
                try:
                    now = utc_now()
                    due = (now - timedelta(minutes=1)).isoformat()
                    window.store.add('钉钉任务', due, now - timedelta(minutes=2), dingtalk=True)
                    window.store.add('普通任务', due, now - timedelta(minutes=2))
                    with patch.object(window, 'push_dingtalk') as push:
                        window.check_due()
                    push.assert_called_once()
                    self.assertEqual(push.call_args.args[0]['title'], '钉钉任务')
                    for dialog in list(window.reminders.values()):
                        dialog.close()
                    app.processEvents()
                finally:
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_third_reminder_is_final_and_defers_task(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from unittest.mock import patch
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow
        from desktop_pet.core import utc_now

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.task_refresh_timer.stop()
                window.settings.update({'dnd_enabled': False, 'early_nudge': False})
                try:
                    now = utc_now()
                    tid = window.store.add('报告', (now - timedelta(minutes=1)).isoformat(),
                                           now - timedelta(minutes=2))
                    for shown in (1, 2, 3):
                        window.store.reset_notifications()
                        window.check_due()
                        dialog = window.reminders[tid]
                        if shown < 3:
                            self.assertTrue(dialog.snooze_button.isEnabled())
                        else:
                            self.assertFalse(dialog.snooze_button.isEnabled())
                            self.assertIn('不再重复提醒', dialog.snooze_button.toolTip())
                        window.dismiss_reminder(tid)
                        app.processEvents()
                    self.assertEqual(window.store.pending()[0]['deferred'], 1)
                    self.assertEqual(window.store.pending()[0]['remind_count'], 3)
                    window.check_due()
                    self.assertNotIn(tid, window.reminders)
                finally:
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_quiet_hours_suppress_then_auto_postpone(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from datetime import datetime, timedelta
        from unittest.mock import patch
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow
        from desktop_pet.core import parse_due, utc_now

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.task_refresh_timer.stop()
                try:
                    now = datetime.now().astimezone()
                    window.settings.update({
                        'dnd_enabled': True,
                        'dnd_start': (now - timedelta(hours=1)).strftime('%H:%M'),
                        'dnd_end': (now + timedelta(hours=1)).strftime('%H:%M'),
                        'early_nudge': False,
                    })
                    current = utc_now()
                    tid = window.store.add('静默任务', (current - timedelta(minutes=1)).isoformat(),
                                           current - timedelta(minutes=2))
                    window.check_due()
                    window.check_due()
                    self.assertEqual(window.reminders, {})
                    quiet = window.store.db.execute(
                        "SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='quiet'", (tid,)).fetchone()[0]
                    self.assertEqual(quiet, 1)

                    window.settings['dnd_enabled'] = False
                    window.settings['auto_postpone'] = True
                    window.check_due()
                    self.assertIn(tid, window.reminders)
                    before = parse_due(window.store.pending()[0]['due_at'])
                    window.reminders[tid].close()
                    app.processEvents()
                    row = window.store.pending()[0]
                    self.assertGreater(parse_due(row['due_at']), before)
                    self.assertEqual(row['notified_at'], None)
                    postponed = window.store.db.execute(
                        "SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='auto_postponed'",
                        (tid,)).fetchone()[0]
                    self.assertEqual(postponed, 1)
                finally:
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_early_nudge_and_mute_today(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from datetime import timedelta
        from unittest.mock import patch
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow
        from desktop_pet.core import utc_now

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.task_refresh_timer.stop()
                try:
                    window.settings.update({'dnd_enabled': False, 'early_nudge': True})
                    now = utc_now()
                    nudged = window.store.add('五分钟', (now + timedelta(minutes=5)).isoformat(), now)
                    muted = window.store.add('六分钟', (now + timedelta(minutes=6)).isoformat(), now)
                    window.store.mute_today(muted, now)
                    window.check_due()
                    self.assertEqual(window.reminders, {})
                    early = {row[0] for row in window.store.db.execute(
                        "SELECT task_id FROM task_events WHERE kind='early'")}
                    self.assertEqual(early, {nudged})
                    window.store.db.execute('UPDATE tasks SET due_at=? WHERE id=?',
                                            ((now - timedelta(minutes=1)).isoformat(), muted))
                    window.store.db.commit()
                    window.check_due()
                    self.assertNotIn(muted, window.reminders)
                finally:
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_chat_ops_and_duplicate_choice(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from unittest.mock import patch
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtTest import QTest
        from desktop_pet.app import MainWindow
        from desktop_pet.core import parse_due, utc_now

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.task_refresh_timer.stop()
                try:
                    now = utc_now()
                    soon = (now + timedelta(days=1)).isoformat()
                    later = (now + timedelta(days=2)).isoformat()
                    latest = (now + timedelta(days=3)).isoformat()
                    tid = window.store.add('交报告', soon)
                    window.on_reply(f'处理完毕。\n\n```tasks\n'
                                    f'[{{"action":"update","id":"{tid}","title":"交周报"}}]\n```')
                    self.assertEqual(window.store.pending()[0]['title'], '交周报')
                    self.assertIn('已修改', window.history.toPlainText())

                    window.on_reply(f'```tasks\n[{{"action":"complete","id":"{tid}"}}]\n```')
                    self.assertEqual(window.store.pending(), [])
                    self.assertIn('已完成', window.history.toPlainText())

                    removed = window.store.add('临时事项', later)
                    window.on_reply(f'```tasks\n[{{"action":"delete","id":"{removed}"}}]\n```')
                    self.assertEqual(window.store.pending(), [])
                    self.assertEqual(window.last_deleted, removed)
                    self.assertTrue(window.undo_button.isEnabled())

                    before = [dict(row) for row in window.store.pending()]
                    window.on_reply(f'```tasks\n'
                                    f'[{{"action":"update","id":"{"f" * 32}","title":"x"}}]\n```')
                    self.assertEqual([dict(row) for row in window.store.pending()], before)
                    self.assertIn('部分建议未采用', window.history.toPlainText())

                    first = window.store.add('写周报', soon)
                    second = window.store.add('写周报', later)
                    window.on_reply(f'```tasks\n[{{"action":"update","id":"{first}",'
                                    f'"due_at":"{latest}"}}]\n```')
                    rows = {row['id']: dict(row) for row in window.store.pending()}
                    self.assertEqual(rows[first]['due_at'], soon)
                    self.assertEqual(rows[second]['due_at'], later)
                    self.assertIn('找到 2 条', window.history.toPlainText())
                    self.assertIn('回复序号', window.history.toPlainText())

                    with patch('desktop_pet.app.ask') as ask:
                        window.input.setPlainText('2')
                        window.send_message()
                        ask.assert_not_called()
                    rows = {row['id']: dict(row) for row in window.store.pending()}
                    self.assertEqual(parse_due(rows[second]['due_at']), parse_due(latest))
                    self.assertEqual(rows[first]['due_at'], soon)
                    self.assertNotIn(window.active_session, window.task_choice)

                    window.on_reply(f'```tasks\n[{{"action":"update","id":"{first}",'
                                    f'"due_at":"{latest}"}}]\n```')
                    self.assertIn(window.active_session, window.task_choice)
                    with patch('desktop_pet.app.ask', return_value='{"reply":"普通回复","tasks":[]}') as ask:
                        window.input.setPlainText('先不选了')
                        window.send_message()
                        for _ in range(200):
                            QTest.qWait(10)
                            if window.worker is None:
                                break
                        ask.assert_called_once()
                    self.assertNotIn(window.active_session, window.task_choice)
                finally:
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_combo_menu_items_stay_compact(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from unittest.mock import patch
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.task_refresh_timer.stop()
                try:
                    window.store.create_session('另一版·默认对话')
                    window.refresh_sessions()
                    combo = window.session_combo
                    if hasattr(combo, '_showComboMenu'):
                        combo._showComboMenu()
                        menu = combo.dropMenu
                        try:
                            heights = [menu.view.item(i).sizeHint().height()
                                       for i in range(menu.view.count())]
                        finally:
                            menu.close()
                    else:
                        combo.showPopup()
                        app.processEvents()
                        heights = [combo.view().sizeHintForRow(i) for i in range(combo.count())]
                        combo.hidePopup()
                    self.assertTrue(heights)
                    for height in heights:
                        self.assertGreaterEqual(height, 28)
                        self.assertLessEqual(height, 40)
                finally:
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_home_overview_and_navigation(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from datetime import datetime, timedelta as span, timezone
        from unittest.mock import patch
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        from PyQt5.QtWidgets import QApplication
        from qfluentwidgets import PrimaryPushButton
        from desktop_pet.app import MainWindow
        from desktop_pet.ui.components import due_when, overdue_text
        from desktop_pet.ui.theme import tokens

        fixed = datetime(2030, 1, 2, 9, 0, tzinfo=timezone(span(hours=8)))
        self.assertEqual(due_when(fixed, fixed), '今天 09:00')
        self.assertEqual(due_when(fixed + span(days=1), fixed), '明天 09:00')
        self.assertEqual(due_when(fixed + span(days=3), fixed), '3 天后')
        self.assertEqual(overdue_text(fixed - span(minutes=95), fixed), '逾期 1小时35分')

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.task_refresh_timer.stop()
                try:
                    window.refresh_home()
                    self.assertEqual(window.tabs.currentIndex(), 0)
                    self.assertEqual(window.home_hero.kind, 'empty')
                    self.assertEqual((window.home_rhythm.ring.done, window.home_rhythm.ring.total), (0, 0))
                    self.assertEqual(window.home_row_widgets, [])
                    self.assertFalse(window.home_empty_panel.isHidden())
                    self.assertFalse(window.home_log_empty.isHidden())
                    self.assertEqual(len(window.home_page.findChildren(PrimaryPushButton)), 1)
                    self.assertEqual(window.home_page.findChildren(PrimaryPushButton)[0],
                                     window.home_add_button)

                    now = datetime.now().astimezone()
                    tid = window.store.add('今日演示', now.isoformat(), now - span(minutes=5))
                    earlier = window.store.add('更早遗留', (now - span(days=2)).isoformat(),
                                               now - span(days=3))
                    window.refresh_home()
                    self.assertEqual(window.home_hero.kind, 'overdue')
                    self.assertEqual(window.home_hero.task['id'], earlier)
                    self.assertIn('另有 1 件逾期', window.home_hero.body.text())
                    self.assertTrue(window.home_empty_panel.isHidden())
                    self.assertEqual(len(window.home_row_widgets), 1)
                    row = window.home_row_widgets[0]
                    self.assertEqual(row.height(), 58)
                    self.assertIn('逾期', row.pill.text)
                    self.assertEqual((window.home_rhythm.ring.done, window.home_rhythm.ring.total), (0, 1))

                    window.settings['density'] = 'compact'
                    old_row = window.home_row_widgets[0]
                    window.refresh_home()
                    # 旧控件先隐藏再延迟销毁，切页刷新时不会和新行同屏闪烁。
                    self.assertTrue(old_row.isHidden())
                    self.assertEqual(window.home_row_widgets[0].height(), 44)
                    row = window.home_row_widgets[0]
                    row.setFocus()
                    QTest.keyClick(row, Qt.Key_Return)
                    app.processEvents()
                    self.assertEqual(window.tabs.currentIndex(), 2)
                    self.assertEqual(window.task_segments.key(), 'pending')
                    self.assertTrue(any(row.task['id'] == tid for row in window.task_rows))

                    window.tabs.setCurrentIndex(0)
                    chat_id = window.store.add('对话记录', (now + span(hours=1)).isoformat(),
                                               now, source='chat')
                    window.home_complete(tid)
                    app.processEvents()
                    self.assertEqual(window.home_log_data['created'], 1)
                    self.assertEqual(window.home_log_data['completed'], 1)
                    self.assertGreaterEqual(len(window.home_log_cards), 1)
                    self.assertTrue(window.home_log_empty.isHidden())
                    self.assertEqual(window.home_rhythm.ring.done, 1)
                    self.assertEqual(window.home_rhythm.ring.total, len(window.home_row_widgets))

                    window.store.delete(earlier)
                    window.refresh_home()
                    self.assertEqual(window.home_hero.kind, 'next')
                    self.assertEqual(window.home_hero.task['id'], chat_id)

                    window.show()
                    window.resize(1440, 820)
                    app.processEvents()
                    self.assertEqual(window.home_top.getItemPosition(
                        window.home_top.indexOf(window.home_rhythm))[:2], (0, 1))
                    window.resize(900, 820)
                    app.processEvents()
                    self.assertEqual(window.home_top.getItemPosition(
                        window.home_top.indexOf(window.home_rhythm))[:2], (1, 0))
                    self.assertEqual(window.home_scroll.horizontalScrollBar().maximum(), 0)

                    window.toggle_theme()
                    app.processEvents()
                    self.assertEqual(tokens().name, 'dark')
                    self.assertIn(tokens().ink_3, window.home_date.styleSheet())
                finally:
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_failed_request_retry_does_not_duplicate_user_message(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtTest import QTest
        from desktop_pet.app import MainWindow
        from unittest.mock import patch

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                try:
                    with patch('desktop_pet.app.ask', side_effect=ValueError('test failure')):
                        window.input.setPlainText('hello')
                        window.send_message()
                        for _ in range(100):
                            QTest.qWait(10)
                            if window.worker is None:
                                break
                        self.assertIsNone(window.worker)
                        self.assertIsNotNone(window.retry_messages)
                    origin = window.active_session
                    window.new_session()
                    self.assertIsNone(window.retry_messages)
                    self.assertTrue(window.retry_button.isHidden())
                    window.session_combo.setCurrentIndex(window.session_combo.findData(origin))
                    self.assertIsNotNone(window.retry_messages)
                    with patch('desktop_pet.app.ask', return_value='{"reply":"success","tasks":[]}'):
                        window.retry_request()
                        for _ in range(100):
                            QTest.qWait(10)
                            if window.worker is None:
                                break
                        self.assertIsNone(window.worker)
                        self.assertIsNone(window.retry_messages)
                    self.assertEqual([m['role'] for m in window.store.messages()], ['user', 'assistant'])
                    window.on_reply('{"reply":"draft","tasks":[{"title":"persist me","due_at":"2099-01-01T12:00:00Z"}]}')
                    second = MainWindow()
                    second.timer.stop()
                    try:
                        self.assertEqual(second.drafts.count(), 0)
                        self.assertEqual(second.store.pending()[0]['title'], 'persist me')
                    finally:
                        second.shutting_down = True
                        second.pet.close()
                        second.tray.hide()
                        second.close()
                        second.store.close()
                        second.deleteLater()
                finally:
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_switch_during_generation_keeps_original_session(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        import threading
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtTest import QTest
        from desktop_pet.app import MainWindow
        from unittest.mock import patch

        app = QApplication.instance() or QApplication([])
        gate = threading.Event()

        def delayed_reply(settings, messages, *args):
            gate.wait(2)
            return '{"reply":"original reply","tasks":[{"title":"original task","due_at":"2099-01-01T12:00:00Z"}]}'

        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                try:
                    origin = window.active_session
                    with patch('desktop_pet.app.ask', side_effect=delayed_reply):
                        window.input.setPlainText('original request')
                        window.send_message()
                        window.new_session()
                        target = window.active_session
                        window.input.setPlainText('unsent second topic')
                        self.assertFalse(window.send.isEnabled())
                        gate.set()
                        for _ in range(100):
                            QTest.qWait(10)
                            if window.worker is None:
                                break
                        self.assertIsNone(window.worker)
                    self.assertEqual(window.store.messages(session_id=target), [])
                    self.assertEqual(window.drafts.count(), 0)
                    self.assertNotIn('original reply', window.history.toPlainText())
                    self.assertIn('已保存：original task', window.store.messages(session_id=origin)[-1]['content'])
                    self.assertEqual(len(window.store.drafts(origin)), 0)
                    self.assertEqual(window.store.pending()[0]['title'], 'original task')
                    window.session_combo.setCurrentIndex(window.session_combo.findData(origin))
                    self.assertEqual(window.drafts.count(), 0)
                    self.assertIn('已保存：original task', window.history.toPlainText())
                    window.input.setPlainText('unsent original')
                    window.session_combo.setCurrentIndex(window.session_combo.findData(target))
                    self.assertEqual(window.input.toPlainText(), 'unsent second topic')
                    self.assertTrue(window.send.isEnabled())
                    self.assertEqual(window.store.session(origin)['input_text'], 'unsent original')
                    window.session_combo.setCurrentIndex(window.session_combo.findData(origin))
                    self.assertEqual(window.drafts.count(), 0)
                    self.assertEqual(window.store.pending()[0]['title'], 'original task')
                    self.assertEqual(window.store.messages(session_id=target), [])
                finally:
                    gate.set()
                    if window.worker:
                        window.worker.wait(3000)
                        app.processEvents()
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()


    def test_shell_theme_and_responsive_layout(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        import json
        from pathlib import Path
        from unittest.mock import patch
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.task_refresh_timer.stop()
                try:
                    window.show()
                    window.resize(1440, 820)
                    app.processEvents()
                    self.assertEqual(window.sidebar.width(), 232)
                    self.assertFalse(window.pet_tag.collapsed)

                    window.resize(900, 820)
                    app.processEvents()
                    self.assertEqual(window.sidebar.width(), 68)
                    self.assertTrue(window.pet_tag.collapsed)
                    self.assertTrue(window.pet_tag.content.isHidden())
                    self.assertTrue(window.nav_buttons[0].isChecked())

                    window.store.add('导航计数', '2099-01-01T12:00:00+08:00')
                    window.refresh_pet_tag()
                    self.assertEqual(window.nav_todo._count, 1)
                    self.assertEqual(window.pet_tag.today_value.text(), '0 件')

                    self.assertEqual(window.theme, 'light')
                    window.settings['density'] = 'compact'
                    window.toggle_theme()
                    self.assertEqual(window.theme, 'dark')
                    saved = json.loads((Path(folder) / 'settings.json').read_text(encoding='utf-8'))
                    self.assertEqual(saved['theme'], 'dark')
                    self.assertEqual(saved['density'], 'compact')
                    self.assertTrue(saved['early_nudge'])
                    self.assertFalse(saved['auto_postpone'])
                    self.assertTrue(saved['dnd_enabled'])
                    self.assertEqual((saved['dnd_start'], saved['dnd_end']), ('22:30', '07:30'))

                    second = MainWindow()
                    second.timer.stop()
                    second.task_refresh_timer.stop()
                    try:
                        self.assertEqual(second.theme, 'dark')
                        self.assertEqual(second.settings['density'], 'compact')
                    finally:
                        second.shutting_down = True
                        second.pet.close()
                        second.tray.hide()
                        second.close()
                        second.store.close()
                        second.deleteLater()
                        app.processEvents()
                finally:
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_3d_mode_falls_back_offscreen_and_persists(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        import json
        from pathlib import Path
        from unittest.mock import patch
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.task_refresh_timer.stop()
                try:
                    self.assertEqual(window.pet.mode, '2d')
                    self.assertFalse(window.pet.enable_3d(persist=False))
                    self.assertEqual(window.pet.mode, '2d')
                    window.settings['pet_mode'] = '3d'
                    window.settings['pet_walking'] = False
                    window.persist_settings()
                    saved = json.loads((Path(folder) / 'settings.json').read_text(encoding='utf-8'))
                    self.assertEqual(saved['pet_mode'], '3d')
                    self.assertIs(saved['pet_walking'], False)
                finally:
                    window.shutting_down = True
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()

    def test_tasks_page_groups_bulk_density_and_theme(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        import json
        from datetime import datetime, timedelta as span
        from pathlib import Path
        from unittest.mock import Mock, patch
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow
        from desktop_pet.ui.components import overdue_text
        from desktop_pet.ui.theme import tokens

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.task_refresh_timer.stop()
                try:
                    now = datetime.now().astimezone()
                    overdue = window.store.add('逾期事项', (now - span(minutes=95)).isoformat(),
                                               now - span(hours=3), source='chat')
                    today = window.store.add('今天事项', (now + span(minutes=30)).isoformat(),
                                             now, dingtalk=True)
                    window.store.add('以后事项', (now + span(days=3)).isoformat(), now)
                    done = window.store.add('完成事项', (now - span(hours=4)).isoformat(),
                                            now - span(hours=5))
                    window.store.complete(done, now - span(hours=3, minutes=50))
                    window.refresh_tasks()

                    rows = {row.task['id']: row for row in window.task_rows}
                    self.assertEqual(window.task_segments.key(), 'pending')
                    self.assertEqual(len(rows), 3)
                    self.assertLess(list(rows).index(overdue), list(rows).index(today))
                    self.assertEqual(window.task_count_num.text(), '3')
                    self.assertEqual(window.task_count_cap.text(), '项未完成')
                    self.assertEqual(rows[overdue].pill.text, overdue_text(
                        now - span(minutes=95), rows[overdue].now))
                    self.assertEqual(rows[overdue].rail.tone, 'over')
                    self.assertIn('今天', window.task_rows[1].pill.text)

                    window.task_segments.set_current('done', emit=True)
                    self.assertEqual(len(window.task_rows), 1)
                    done_row = window.task_rows[0]
                    self.assertTrue(done_row.done)
                    self.assertTrue(done_row.title.font().strikeOut())
                    self.assertEqual(done_row.pill.text, '已完成')
                    self.assertFalse(window.task_period.isEnabled())
                    window.task_segments.set_current('pending', emit=True)

                    window.set_task_density('compact')
                    self.assertEqual(window.settings['density'], 'compact')
                    self.assertEqual(window.task_rows[0].height(), 44)
                    window.set_task_density('comfortable')
                    self.assertEqual(window.task_rows[0].height(), 58)
                    window.set_task_density('compact')
                    saved = json.loads((Path(folder) / 'settings.json').read_text(encoding='utf-8'))
                    self.assertEqual(saved['density'], 'compact')
                    window.set_task_density('comfortable')

                    window.task_search.setText('以后')
                    self.assertEqual(len(window.task_rows), 1)
                    window.task_search.clear()
                    window.task_period.setCurrentIndex(window.task_period.findData('overdue'))
                    self.assertEqual(len(window.task_rows), 1)
                    window.task_period.setCurrentIndex(window.task_period.findData('future'))
                    self.assertEqual(len(window.task_rows), 1)
                    window.task_period.setCurrentIndex(0)

                    dialog = Mock()
                    with patch.object(window, 'task_dialog', dialog):
                        row = next(item for item in window.task_rows
                                   if item.task['id'] == overdue)
                        QTest.mouseDClick(row, Qt.LeftButton)
                        app.processEvents()
                        dialog.assert_called_once()
                        row.ring.clicked.emit()
                        app.processEvents()
                        self.assertEqual(dialog.call_count, 1)
                    self.assertEqual(len(window.store.history('done')), 2)
                    self.assertFalse(window.task_bulk.isVisible())

                    window.resize(1440, 820)
                    window.tabs.setCurrentIndex(2)
                    window.show()
                    app.processEvents()
                    window.clear_task_selection()
                    picks = window.task_rows[:2]
                    for row in picks:
                        row.set_picked(True)
                        window.on_task_pick(row.task['id'], True)
                    app.processEvents()
                    bulk = window.task_bulk
                    page = window.task_page
                    self.assertTrue(bulk.isVisible())
                    self.assertEqual((bulk.width(), bulk.height()), (604, 42))
                    self.assertEqual(bulk.x(), (page.width() - 604) // 2)
                    self.assertEqual(bulk.y(), page.height() - 62)
                    bulk.cancel.click()
                    app.processEvents()
                    self.assertFalse(bulk.isVisible())
                    self.assertEqual(window.task_selected, set())

                    for row in window.task_rows[:2]:
                        row.set_picked(True)
                        window.on_task_pick(row.task['id'], True)
                    window.complete_selected()
                    app.processEvents()
                    self.assertFalse(bulk.isVisible())
                    self.assertEqual(len(window.store.pending()), 0)
                    self.assertEqual(len(window.store.history('done')), 4)

                    window.task_segments.set_current('done', emit=True)
                    for row in window.task_rows:
                        row.set_picked(True)
                        window.on_task_pick(row.task['id'], True)
                    window.delete_selected()
                    app.processEvents()
                    self.assertEqual(len(window.store.history('done')), 0)
                    self.assertTrue(window.undo_button.isVisible())
                    self.assertEqual(len(window.deleted_batch), 4)
                    window.undo_delete()
                    app.processEvents()
                    self.assertEqual(len(window.store.history('done')), 4)
                    self.assertTrue(all(row['status'] == 'done'
                                        for row in window.store.history('done')))
                    self.assertFalse(window.undo_button.isVisible())

                    window.resize(1180, 820)
                    app.processEvents()
                    self.assertEqual(window.task_scroll.horizontalScrollBar().maximum(), 0)
                    window.resize(900, 820)
                    app.processEvents()
                    self.assertEqual(window.task_scroll.horizontalScrollBar().maximum(), 0)
                    self.assertFalse(window.task_bulk.isVisible())

                    window.toggle_theme()
                    app.processEvents()
                    self.assertEqual(tokens().name, 'dark')
                    self.assertTrue(window.task_rows)
                    top = window.task_rows[0]
                    self.assertEqual(top.title._color.name().upper(),
                                     tokens().ink_3 if top.done else tokens().ink)
                finally:
                    window.shutting_down = True
                    window.timer.stop()
                    window.pet.close()
                    window.tray.hide()
                    window.close()
                    window.store.close()
                    window.deleteLater()
                    app.processEvents()


if __name__ == '__main__':
    unittest.main()
