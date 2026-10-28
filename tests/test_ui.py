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
                    window.task_filter.setCurrentIndex(1)
                    self.assertEqual(window.tasks.count(), 1)
                    window.tasks.setCurrentRow(0)
                    window.delete_selected()
                    self.assertEqual(window.tasks.count(), 0)
                    window.undo_delete()
                    self.assertEqual(window.tasks.count(), 1)
                    window.tasks.setCurrentRow(0)
                    window.complete_selected()
                    window.task_filter.setCurrentIndex(0)
                    self.assertEqual(window.tasks.count(), 1)
                    window.task_search.setText('absent')
                    self.assertEqual(window.tasks.count(), 0)
                    self.assertEqual(len(window.store.drafts()), 1)
                    window.task_search.clear()
                    window.task_period.setCurrentIndex(window.task_period.findData('future'))
                    self.assertEqual(window.tasks.count(), 0)
                    window.store.add('overdue', (now - timedelta(minutes=1)).isoformat(), now - timedelta(minutes=2))
                    window.task_period.setCurrentIndex(window.task_period.findData('overdue'))
                    self.assertEqual(window.tasks.count(), 1)
                    card = window.drafts.itemAt(0).widget()
                    card.repeat.setCurrentIndex(card.repeat.findData('daily'))
                    card.save_button.click()
                    self.assertEqual(window.drafts.count(), 0)
                    window.task_period.setCurrentIndex(window.task_period.findData('future'))
                    self.assertEqual(window.tasks.count(), 1)
                    self.assertIn('每天', window.tasks.item(0).text())
                    window.tasks.setCurrentRow(0)
                    window.complete_selected()
                    self.assertEqual(window.tasks.count(), 1)
                    self.assertEqual(window.tasks.item(0).data(256)['repeat_rule'], 'daily')
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
        from datetime import datetime
        from unittest.mock import patch
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        from PyQt5.QtWidgets import QApplication
        from desktop_pet.app import MainWindow

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'DESKTOP_PET_DATA_DIR': folder}):
                window = MainWindow()
                window.timer.stop()
                window.task_refresh_timer.stop()
                try:
                    window.refresh_home()
                    self.assertEqual(window.tabs.currentIndex(), 0)
                    self.assertEqual(window.home_stats['today'].text(), '0 件')
                    now = datetime.now().astimezone()
                    # 相对当前时刻取今天内的过去时间，避免中午前后逾期数量随之波动。
                    due = now - timedelta(minutes=2)
                    tid = window.store.add('今日演示', due.isoformat(), due - timedelta(days=1))
                    window.store.add('更早遗留', (now - timedelta(days=2)).isoformat(),
                                     now - timedelta(days=3))
                    window.refresh_home()
                    self.assertEqual(window.home_stats['today'].text(), '1 件')
                    self.assertEqual(window.home_stats['overdue'].text(), '2 件')
                    self.assertFalse(window.home_banner.isHidden())
                    self.assertIn('1 件更早', window.home_banner_text.text())
                    self.assertEqual(len(window.home_row_widgets), 1)
                    QTest.mouseClick(window.home_row_widgets[0], Qt.LeftButton)
                    app.processEvents()
                    self.assertEqual(window.tabs.currentIndex(), 2)
                    self.assertIsNotNone(window.tasks.currentItem())
                    self.assertEqual(window.tasks.currentItem().data(Qt.UserRole)['id'], tid)
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


if __name__ == '__main__':
    unittest.main()
