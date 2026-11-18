import json
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject, Signal

from desktop_pet.bridge import BridgeHost, BridgeError
from desktop_pet import bridge_modules
from desktop_pet.core import TaskStore, utc_now
from desktop_pet.secure_storage import SecretStore


class FakeStartup:
    def __init__(self, broken=False):
        self.broken = broken
        self.calls = []

    def enabled(self):
        if self.broken:
            raise ValueError('registry unavailable')
        return True

    def set_enabled(self, enabled):
        self.calls.append(enabled)


class FakeKnowledge:
    def __init__(self):
        self.removed = []
        self.cleared = False
        self.progress_seen = []

    def documents(self):
        return [{'doc_id': 'd1', 'name': 'a.pdf', 'source_path': str(Path('nope.pdf'))}]

    def stats(self):
        return {'docs': 1}

    def search(self, query, preview=False):
        return [{'title': query, 'preview': preview}]

    def remove(self, doc_id):
        self.removed.append(doc_id)

    def clear(self):
        self.cleared = True

    def add_file(self, path, settings, progress, cancelled, force=False):
        progress(f'working on {Path(path).name}')
        if path.endswith('bad.pdf'):
            raise ValueError('boom')
        return {'status': 'added' if not force else 'updated', 'name': Path(path).name}

    def add_folder(self, folder, settings, progress, cancelled, force=False):
        return [self.add_file(str(Path(folder) / 'x.pdf'), settings, progress, cancelled, force)]


class FakePet:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


class FakeWindow:
    def __init__(self, root):
        self.root = root
        self.settings = {'theme': 'light', 'stream': True, 'api_key': 'secret-value',
                         'tavily_key': 'tvly-secret', 'pet_images': [{'image': 'a.png'}],
                         'active_session': 'default'}
        self.persisted = []
        self.secret_store = SecretStore(root)
        self.secret_endpoint = None
        self.startup_manager = FakeStartup()
        self.knowledge = FakeKnowledge()
        self._bridge_kb_busy = False
        self.store = TaskStore(root / 'tasks.db')
        self.pet_calls = []
        self.web_reminders = set()
        self.active_session = 'default'
        self.retry_by_session = {}
        self.task_choice = {}
        self.web_chat_worker = None
        self.exit_pending = False
        self.quit_calls = 0
        self.pet = FakePet()

    def dismiss_reminder(self, task_id):
        self.web_reminders.discard(task_id)

    def close_web_reminder(self, task_id, postpone=True):
        if task_id not in self.web_reminders:
            return False
        self.web_reminders.discard(task_id)
        return bool(postpone)

    def persist_settings(self):
        self.persisted.append(dict(self.settings))

    def quit_app(self):
        self.quit_calls += 1

    # -- assistant pipeline (real window lives in app.py) --------------------------------------
    def web_search_ready(self):
        return bool(self.settings.get('tavily_key'))

    def knowledge_ready(self):
        return True

    def selection_index(self, text):
        text = text.strip()
        return int(text) if text.isdigit() else None

    def execute_task_op(self, op, confirmed=False):
        action = op.get('action', 'create')
        if action == 'create':
            self.store.add(op['title'], op['due_at'], repeat=op.get('repeat', 'none'),
                           dingtalk=bool(op.get('dingtalk')), source='chat')
            return f"已保存：{op['title']}。", None
        row = next((item for item in self.store.pending() if item['id'] == op.get('id')), None)
        if row is None:
            raise ValueError('待办已不存在或已完成')
        if action == 'complete':
            self.store.complete(row['id'])
            return f"已完成：{row['title']}。", None
        if action == 'delete':
            self.store.delete(row['id'])
            return f"已删除：{row['title']}。", None
        raise ValueError('不支持的任务操作')

    def run_task_ops(self, ops, session_id):
        receipts, errors = [], []
        for op in ops:
            try:
                receipt, _ = self.execute_task_op(op)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            receipts.append(receipt)
        return receipts, errors, None

    # -- pet appearance flow (native dialogs stay shell-side) ---------------------------------
    def apply_pet_image(self, path, records=None, notice=''):
        self.pet_calls.append(('apply', path))
        if records is not None:
            self.settings['pet_images'] = [dict(item) for item in records]
        if path:
            self.settings['pet_image'] = path
        else:
            self.settings.pop('pet_image', None)
        return True

    def choose_image(self):
        self.pet_calls.append(('choose',))
        self.settings['pet_image'] = 'chosen.png'
        self.settings['pet_images'].append({'image': 'chosen.png'})

    def remove_pet_image(self):
        self.pet_calls.append(('remove',))
        self.settings.pop('pet_image', None)

    def remove_image_background(self):
        self.pet_calls.append(('cutout',))

    def restore_original_image(self):
        self.pet_calls.append(('restore',))

    def reset_pet_position(self):
        self.pet_calls.append(('reset',))


class BridgeModuleTestsBase(unittest.TestCase):
    def setUp(self):
        self._app = QCoreApplication.instance() or QCoreApplication([])
        self.temp = tempfile.TemporaryDirectory()
        self.window = FakeWindow(Path(self.temp.name))
        self.host = BridgeHost(context={'window': self.window})
        bridge_modules.install(self.host)
        self.events = []
        self.host.event.connect(lambda name, payload: self.events.append((name, json.loads(payload))))
        # Handshake so emit_event flows directly (matching runtime behaviour).
        self.invoke('system.info')

    def tearDown(self):
        if self.window.store:
            self.window.store.close()
        self.temp.cleanup()

    def invoke(self, method, payload=None):
        return json.loads(self.host.invoke(method, json.dumps(payload or {})))

    def wait_for_event(self, name, timeout=5):
        got = threading.Event()

        def watch(n, _p):
            if n == name:
                got.set()

        self.host.event.connect(watch)
        try:
            # Worker threads deliver signals as queued events; pump the loop to receive
            # them. Fast jobs may finish before the watcher connects, so also scan
            # events captured by the recorder in setUp.
            deadline = time.time() + timeout
            while not got.wait(0.02):
                QCoreApplication.processEvents()
                if any(e[0] == name for e in self.events):
                    got.set()
                    break
                if time.time() >= deadline:
                    raise AssertionError(f'等待事件 {name} 超时')
            QCoreApplication.processEvents()
            return [e for e in self.events if e[0] == name][-1]
        finally:
            self.host.event.disconnect(watch)


class SettingsModuleTests(BridgeModuleTestsBase):
    def test_getall_hides_secrets(self):
        resp = self.invoke('settings.getAll')
        self.assertTrue(resp['ok'])
        data = resp['data']
        self.assertNotIn('api_key', data)
        self.assertNotIn('tavily_key', data)
        self.assertEqual(data['theme'], 'light')

    def test_set_persists_and_broadcasts(self):
        resp = self.invoke('settings.set', {'patch': {'theme': 'dark', 'early_nudge': False}})
        self.assertTrue(resp['ok'])
        self.assertEqual(self.window.settings['theme'], 'dark')
        self.assertEqual(self.window.settings['early_nudge'], False)
        self.assertTrue(self.window.persisted)
        self.assertIn(('settings.changed', {'patch': {'theme': 'dark', 'early_nudge': False}}), self.events)

    def test_set_rejects_unknown_and_readonly(self):
        resp = self.invoke('settings.set', {'patch': {'nope': 1}})
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')
        resp = self.invoke('settings.set', {'patch': {'pet_images': []}})
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')
        for removed in ({'ui_shell': 'web'}, {'sidebar_collapsed': True}):
            resp = self.invoke('settings.set', {'patch': removed})
            self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR', removed)
        self.assertNotIn('ui_shell', self.invoke('settings.getAll')['data'])
        self.assertNotIn('sidebar_collapsed', self.invoke('settings.getAll')['data'])

    def test_set_validates_values(self):
        for patch in ({'theme': 'blue'}, {'early_nudge': 'yes'}, {'dnd_start': '25:00'},
                      {'base_url': 123}, {'pet_mode': '4d'}):
            resp = self.invoke('settings.set', {'patch': patch})
            self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR', patch)

    def test_set_normalizes_clock(self):
        resp = self.invoke('settings.set', {'patch': {'dnd_start': '09:05'}})
        self.assertTrue(resp['ok'])
        self.assertEqual(self.window.settings['dnd_start'], '09:05')

    def test_unknown_action(self):
        resp = self.invoke('settings.nope')
        self.assertEqual(resp['error']['code'], 'NOT_FOUND')

    def test_export_data(self):
        self.window.store.add('示例', (utc_now() + timedelta(hours=1)).isoformat())
        target = Path(self.temp.name) / 'export.json'
        resp = self.invoke('settings.exportData', {'path': str(target)})
        self.assertTrue(resp['ok'])
        self.assertEqual(resp['data'], {'file': 'export.json', 'tasks': 1, 'sessions': 1})
        payload = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(payload['format'], 'desktop-pet-export')
        self.assertTrue(payload['tasks'])
        resp = self.invoke('settings.exportData', {'path': ''})
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')

    def test_clear_data(self):
        self.window.store.add('示例', (utc_now() + timedelta(hours=1)).isoformat())
        resp = self.invoke('settings.clearData', {})
        self.assertTrue(resp['ok'])
        self.assertIn('tasks.db', resp['data']['backup'])
        self.assertEqual(self.window.settings['active_session'], 'default')
        self.assertIn(('tasks.changed', {'reason': 'cleared'}), self.events)
        self.assertEqual(self.invoke('knowledge.documents')['ok'], True)  # host still usable

    def test_data_methods_without_store(self):
        self.window.store.close()
        self.window.store = None
        self.assertEqual(self.invoke('settings.exportData', {'path': 'x'})['error']['code'],
                         'NOT_AVAILABLE')
        self.assertEqual(self.invoke('settings.clearData', {})['error']['code'], 'NOT_AVAILABLE')


class SecretsModuleTests(BridgeModuleTestsBase):
    def test_status_empty(self):
        self.window.settings['api_key'] = ''
        self.window.settings['tavily_key'] = ''
        resp = self.invoke('secrets.status')
        self.assertTrue(resp['ok'])
        self.assertFalse(resp['data']['hasApiKey'])
        self.assertFalse(resp['data']['hasTavily'])
        self.assertFalse(resp['data']['hasDingtalk'])

    def test_status_reflects_settings_key(self):
        resp = self.invoke('secrets.status')
        self.assertTrue(resp['data']['hasApiKey'])  # FakeWindow carries a session key

    def test_save_and_clear_roundtrip(self):
        self.assertTrue(self.invoke('secrets.saveApiKey',
                                    {'endpoint': 'https://api.example.com/v1', 'value': 'k1'})['ok'])
        self.assertEqual(self.window.secret_store.load('https://api.example.com/v1'), 'k1')
        self.assertTrue(self.invoke('secrets.saveTavily', {'value': 'tvly-1'})['ok'])
        self.assertEqual(self.window.secret_store.load_tavily(), 'tvly-1')
        self.assertTrue(self.invoke('secrets.saveDingtalk',
                                    {'webhook': 'https://oapi.dingtalk.com/robot/send?access_token=abc',
                                     'secret': 'SEC'})['ok'])
        webhook, secret = self.window.secret_store.load_dingtalk()
        self.assertEqual(webhook, 'https://oapi.dingtalk.com/robot/send?access_token=abc')
        self.assertEqual(secret, 'SEC')
        self.invoke('secrets.rememberKey', {'enabled': False})
        self.assertEqual(self.window.settings['remember_key'], False)
        self.assertEqual(self.window.secret_store.load('https://api.example.com/v1'), '')

    def test_save_tavily_and_dingtalk_clear_on_empty(self):
        self.invoke('secrets.saveTavily', {'value': 'tvly-1'})
        self.invoke('secrets.saveTavily', {'value': ''})
        self.assertEqual(self.window.secret_store.load_tavily(), '')
        self.invoke('secrets.saveDingtalk',
                    {'webhook': 'https://oapi.dingtalk.com/robot/send?access_token=abc', 'secret': 'S'})
        self.invoke('secrets.saveDingtalk', {'webhook': '', 'secret': ''})
        self.assertFalse(self.invoke('secrets.status')['data']['hasDingtalk'])

    def test_save_rejects_bad_endpoint(self):
        resp = self.invoke('secrets.saveApiKey', {'endpoint': 'not-a-url', 'value': 'k'})
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')

    def test_kind_validation(self):
        resp = self.invoke('secrets.testConnection', {'kind': 'nope'})
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')

    def test_model_test_job_emits_result(self):
        with patch('desktop_pet.bridge_modules.secrets.test_model', return_value=42) as fake:
            resp = self.invoke('secrets.testConnection', {'kind': 'model'})
            self.assertTrue(resp['ok'])
            name, payload = self.wait_for_event('connection.testResult')
            self.assertEqual(name, 'connection.testResult')
            self.assertTrue(payload['ok'])
            self.assertIn('42ms', payload['message'])
            self.assertEqual(fake.call_count, 1)
        self.assertEqual(self.host._jobs, {})


class KnowledgeModuleTests(BridgeModuleTestsBase):
    def test_reads(self):
        self.assertEqual(self.invoke('knowledge.documents')['data']['documents'][0]['doc_id'], 'd1')
        self.assertEqual(self.invoke('knowledge.stats')['data'], {'docs': 1})
        self.assertEqual(self.invoke('knowledge.search', {'query': 'hi'})['data']['hits'],
                         [{'title': 'hi', 'preview': True}])
        resp = self.invoke('knowledge.search', {'query': ''})
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')

    def test_remove_and_clear(self):
        self.assertTrue(self.invoke('knowledge.remove', {'docId': 'd1'})['ok'])
        self.assertEqual(self.window.knowledge.removed, ['d1'])
        self.assertTrue(self.invoke('knowledge.clear')['ok'])
        self.assertTrue(self.window.knowledge.cleared)

    def test_rebuild_without_sources(self):
        resp = self.invoke('knowledge.rebuild')
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')
        self.assertIn('没有可重建', resp['error']['message'])

    def test_import_job_counts_and_progress(self):
        resp = self.invoke('knowledge.importPaths',
                           {'paths': [str(self.window.root / 'a.pdf'), str(self.window.root / 'bad.pdf')]})
        self.assertTrue(resp['ok'])
        name, payload = self.wait_for_event('knowledge.jobDone')
        self.assertEqual(payload['added'], 1)
        self.assertEqual(payload['failed'], 1)
        self.assertIn('boom', payload['message'])
        progress = [e for e in self.events if e[0] == 'knowledge.jobProgress']
        self.assertTrue(progress)
        self.assertFalse(self.window._bridge_kb_busy)
        self.assertEqual(self.host._jobs, {})

    def test_import_conflict_while_busy(self):
        self.window._bridge_kb_busy = True
        resp = self.invoke('knowledge.importPaths', {'paths': ['a.pdf']})
        self.assertEqual(resp['error']['code'], 'CONFLICT')


class PetModuleTests(BridgeModuleTestsBase):
    def test_gallery_marks_active_and_renders_default_thumb(self):
        self.window.settings['pet_image'] = 'a.png'
        resp = self.invoke('pet.gallery')
        self.assertTrue(resp['ok'])
        data = resp['data']
        self.assertEqual(data['active'], 'a.png')
        self.assertEqual([item['image'] for item in data['items']], ['a.png'])
        self.assertTrue(data['items'][0]['active'])
        self.assertTrue(data['defaultThumb'].startswith('data:image/png;base64,'))
        # Missing file gives an empty thumbnail rather than an exception.
        self.assertEqual(data['items'][0]['thumb'], '')

    def test_select_switches_and_rejects_unknown(self):
        resp = self.invoke('pet.select', {'image': 'a.png'})
        self.assertTrue(resp['ok'])
        self.assertTrue(resp['data']['applied'])
        self.assertEqual(self.window.settings['pet_image'], 'a.png')
        self.assertIn(('pet.changed', {'active': 'a.png', 'changed': True}), self.events)
        self.assertEqual(self.invoke('pet.select', {'image': 'nope.png'})['error']['code'], 'NOT_FOUND')
        resp = self.invoke('pet.select', {'image': ''})
        self.assertTrue(resp['data']['applied'])
        self.assertNotIn('pet_image', self.window.settings)

    def test_shell_actions_forward_and_broadcast(self):
        resp = self.invoke('pet.chooseImage')
        self.assertTrue(resp['ok'])
        self.assertTrue(resp['data']['changed'])
        self.assertIn(('choose',), self.window.pet_calls)
        self.assertIn(('pet.changed', {'active': 'chosen.png', 'changed': True}), self.events)
        for action in ('removeImage', 'removeBackground', 'restoreOriginal'):
            self.assertTrue(self.invoke(f'pet.{action}')['ok'], action)
        self.assertEqual([call[0] for call in self.window.pet_calls],
                         ['choose', 'remove', 'cutout', 'restore'])
        self.assertTrue(self.invoke('pet.resetPosition')['ok'])
        self.assertIn(('reset',), self.window.pet_calls)
        self.assertEqual(self.invoke('pet.nope')['error']['code'], 'NOT_FOUND')


class TasksModuleTests(BridgeModuleTestsBase):
    def add(self, title='报告', **extra):
        payload = {'title': title,
                   'dueAt': (utc_now() + timedelta(hours=1)).isoformat(), **extra}
        resp = self.invoke('tasks.add', payload)
        self.assertTrue(resp['ok'], resp)
        return resp['data']

    def test_add_list_history_stats_and_events(self):
        task = self.add(repeat='daily', dingtalk=True)
        self.assertEqual(task['title'], '报告')
        self.assertEqual(task['repeat_rule'], 'daily')
        self.assertEqual(task['dingtalk'], 1)
        self.assertEqual([row['id'] for row in self.invoke('tasks.list')['data']], [task['id']])
        self.assertEqual(self.invoke('tasks.history', {'status': 'done'})['data'], [])
        self.assertTrue(self.invoke('tasks.complete', {'id': task['id']})['data']['nextId'])
        self.assertEqual(len(self.invoke('tasks.history', {'status': 'done'})['data']), 1)
        stats = self.invoke('tasks.stats')['data']
        self.assertGreaterEqual(stats['completed_today'], 1)
        kinds = {event['kind'] for event in self.invoke('tasks.todayEvents')['data']}
        self.assertTrue({'created', 'completed'} <= kinds)
        self.assertIn(('tasks.changed', {'reason': 'add'}), self.events)

    def test_add_and_edit_validation(self):
        past = (utc_now() - timedelta(minutes=1)).isoformat()
        self.assertEqual(self.invoke('tasks.add', {'title': 'x', 'dueAt': past})['error']['code'],
                         'VALIDATION_ERROR')
        self.assertEqual(self.invoke('tasks.add', {'title': '', 'dueAt': past})['error']['code'],
                         'VALIDATION_ERROR')
        task = self.add()
        resp = self.invoke('tasks.edit', {'id': task['id'], 'title': '新标题'})
        self.assertTrue(resp['ok'])
        self.assertEqual(resp['data']['title'], '新标题')
        resp = self.invoke('tasks.edit', {'id': task['id'], 'repeat': 'yearly'})
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')

    def test_add_and_edit_bucket_tasks(self):
        week = self.invoke('tasks.add', {'title': '周报', 'horizon': 'week'})['data']
        self.assertEqual((week['horizon'], week['repeat_rule']), ('week', 'none'))
        self.assertIsNotNone(week['remind_at'])
        someday = self.invoke('tasks.add', {'title': '整理书架', 'horizon': 'someday'})['data']
        self.assertEqual((someday['due_at'], someday['remind_at']), (None, None))
        resp = self.invoke('tasks.edit', {'id': week['id'], 'title': '周报', 'horizon': 'someday'})
        self.assertTrue(resp['ok'], resp)
        self.assertEqual(resp['data']['horizon'], 'someday')
        self.assertIsNone(resp['data']['due_at'])
        self.assertEqual(self.invoke('tasks.add', {'title': 'x', 'horizon': 'year'})['error']['code'],
                         'VALIDATION_ERROR')

    def test_edit_on_overdue_requires_new_time(self):
        now = utc_now()
        tid = self.window.store.add('旧任务', (now - timedelta(minutes=1)).isoformat(),
                                    now - timedelta(minutes=2))
        resp = self.invoke('tasks.edit', {'id': tid, 'title': '改名'})
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')
        self.assertIn('逾期', resp['error']['message'])
        resp = self.invoke('tasks.edit', {'id': tid, 'title': '改名',
                                          'dueAt': (now + timedelta(hours=1)).isoformat()})
        self.assertTrue(resp['ok'])
        self.assertEqual(resp['data']['title'], '改名')

    def test_snooze_dingtalk_and_mute(self):
        task = self.add()
        before = self.window.store.pending()[0]['due_at']
        self.assertTrue(self.invoke('tasks.snooze', {'id': task['id'], 'minutes': 15})['ok'])
        self.assertNotEqual(self.window.store.pending()[0]['due_at'], before)
        self.assertEqual(self.invoke('tasks.snooze', {'id': task['id'], 'minutes': 0})['error']['code'],
                         'VALIDATION_ERROR')
        self.assertTrue(self.invoke('tasks.setDingtalk', {'id': task['id'], 'enabled': True})['ok'])
        self.assertEqual(self.window.store.pending()[0]['dingtalk'], 1)
        muted = self.invoke('tasks.muteToday', {'id': task['id']})['data']['mutedUntil']
        self.assertEqual(self.window.store.pending()[0]['muted_until'], muted)

    def test_delete_undo_and_reopen_conflict(self):
        task = self.add(repeat='daily')
        next_id = self.invoke('tasks.complete', {'id': task['id']})['data']['nextId']
        self.assertEqual(self.invoke('tasks.reopen', {'id': task['id']})['error']['code'],
                         'CONFLICT')
        self.assertTrue(self.invoke('tasks.delete', {'id': next_id})['ok'])
        self.assertEqual(self.invoke('tasks.list')['data'], [])
        self.assertTrue(self.invoke('tasks.undoDelete', {'id': next_id})['ok'])
        self.assertEqual(len(self.invoke('tasks.list')['data']), 1)

    def test_parse_due_text(self):
        parsed = self.invoke('tasks.parseDue', {'text': '明天 9:30'})['data']
        self.assertEqual(parsed['repeat'], 'none')
        self.assertFalse(parsed['past'])
        self.assertEqual(self.invoke('tasks.parseDue', {'text': '每天 8:00'})['data']['repeat'],
                         'daily')
        self.assertEqual(self.invoke('tasks.parseDue', {'text': '工作日 18:00'})['data']['repeat'],
                         'weekdays')
        self.assertEqual(self.invoke('tasks.parseDue', {'text': '随便'})['error']['code'],
                         'VALIDATION_ERROR')

    def test_dismiss_reminder_postpones_once(self):
        task = self.add()
        self.window.web_reminders.add(task['id'])
        resp = self.invoke('tasks.dismissReminder', {'id': task['id']})
        self.assertEqual(resp['data'], {'postponed': True})
        self.assertNotIn(task['id'], self.window.web_reminders)
        self.assertIn(('tasks.changed', {'reason': 'autoPostpone'}), self.events)
        self.assertEqual(self.invoke('tasks.dismissReminder', {'id': task['id']})['data'],
                         {'postponed': False})

    def test_unknown_action(self):
        self.assertEqual(self.invoke('tasks.nope')['error']['code'], 'NOT_FOUND')


class DraftsModuleTests(BridgeModuleTestsBase):
    def test_save_list_confirm_and_discard(self):
        due = (utc_now() + timedelta(hours=2)).isoformat()
        resp = self.invoke('drafts.save', {'title': '草稿', 'dueAt': due, 'repeat': 'weekly'})
        self.assertTrue(resp['ok'])
        drafts = self.invoke('drafts.list', {'sessionId': 'default'})['data']
        self.assertEqual([row['title'] for row in drafts], ['草稿'])
        task_id = self.invoke('drafts.confirm', {'id': drafts[0]['id']})['data']['taskId']
        self.assertEqual([row['id'] for row in self.invoke('tasks.list')['data']], [task_id])
        self.assertTrue(any(row['id'] == task_id for row in self.window.store.pending()))
        self.assertEqual(self.invoke('drafts.list')['data'], [])
        saved = self.invoke('drafts.save', {'title': '另一份', 'dueAt': due})['data']
        self.assertTrue(self.invoke('drafts.discard', {'id': saved['id']})['ok'])
        self.assertEqual(self.invoke('drafts.list')['data'], [])

    def test_save_validates(self):
        resp = self.invoke('drafts.save', {'title': 'x', 'dueAt': 'nonsense'})
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')


class FakeWorker(QObject):
    result = Signal(str)
    failed = Signal(str)
    chunk = Signal(str)
    stopped = Signal()
    search_started = Signal()
    searched = Signal(object)
    search_failed = Signal(str)
    knowledge_started = Signal()
    knowledge_searched = Signal(object)
    finished = Signal()

    def __init__(self, settings, messages, tasks, parent, web_query='', knowledge=None,
                 knowledge_query=''):
        super().__init__()
        self.settings = settings
        self.messages = [dict(message) for message in messages]
        self.tasks = tasks
        self.web_query = web_query
        self.knowledge_query = knowledge_query
        self.started = False
        self.cancelled = False
        self.deleted = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True
        self.stopped.emit()

    def deleteLater(self):
        self.deleted = True


class ChatModuleTests(BridgeModuleTestsBase):
    def setUp(self):
        super().setUp()
        self.workers = []

        def factory(*args, **kwargs):
            worker = FakeWorker(*args, **kwargs)
            self.workers.append(worker)
            return worker

        self.host.context['worker_factory'] = factory
        self.window.settings.update({'model': 'gpt-test',
                                     'base_url': 'https://api.example.com/v1'})

    def named(self, name):
        return [payload for event, payload in self.events if event == name]

    def start_send(self, text='你好'):
        resp = self.invoke('chat.send', {'text': text})
        self.assertTrue(resp['ok'], resp)
        self.assertTrue(resp['data']['accepted'])
        return self.workers[-1]

    def finish(self, worker, reply='你好'):
        worker.result.emit(json.dumps({'reply': reply, 'tasks': []}, ensure_ascii=False))
        worker.finished.emit()

    def test_sessions_create_rename_and_save_input(self):
        data = self.invoke('chat.sessions')['data']
        self.assertEqual(data['activeSession'], 'default')
        self.assertEqual([row['id'] for row in data['sessions']], ['default'])
        self.assertEqual(data['sessions'][0]['messageCount'], 0)

        resp = self.invoke('chat.createSession', {'title': '工作'})
        self.assertTrue(resp['ok'])
        session_id = resp['data']['sessionId']
        self.assertNotEqual(session_id, 'default')
        self.assertEqual(self.window.active_session, session_id)
        self.assertEqual(self.window.settings['active_session'], session_id)
        self.assertTrue(any(p['reason'] == 'create' for p in self.named('chat.changed')))

        self.assertTrue(self.invoke('chat.renameSession',
                                    {'sessionId': session_id, 'title': '新名字'})['ok'])
        self.assertEqual(self.window.store.session(session_id)['title'], '新名字')
        self.assertTrue(self.invoke('chat.saveInput',
                                    {'sessionId': session_id, 'text': '写到一半'})['ok'])
        payload = self.invoke('chat.session', {'sessionId': session_id})['data']
        self.assertEqual(payload['session']['inputText'], '写到一半')
        self.assertTrue(payload['hasModel'])
        self.assertEqual(payload['messages'], [])

    def test_stream_is_buffered_then_flushed_on_result(self):
        worker = self.start_send()
        self.assertTrue(worker.started)
        self.assertEqual(self.named('assistant.state')[-1]['state'], 'responding')
        worker.chunk.emit('{"reply": "你')
        worker.chunk.emit('好"}')
        self.assertEqual(self.named('assistant.chunk'), [])  # 100ms throttle holds it back
        worker.result.emit('{"reply": "你好"}')
        worker.finished.emit()
        chunks = self.named('assistant.chunk')
        self.assertEqual([chunk['text'] for chunk in chunks], ['你好'])
        result = self.named('assistant.result')[-1]
        self.assertEqual(result['reply'], '你好')
        self.assertEqual(result['sessionId'], 'default')
        self.assertEqual(result['meta'].split(' · ')[1], 'gpt-test')
        self.assertEqual(self.window.store.messages(10), [{'role': 'user', 'content': '你好'},
                                                          {'role': 'assistant', 'content': '你好'}])
        self.assertTrue(worker.deleted)
        self.assertIsNone(self.window.web_chat_worker)
        self.assertEqual(self.named('assistant.state')[-1]['state'], 'idle')

    def test_stop_stores_retry_context(self):
        worker = self.start_send()
        resp = self.invoke('chat.stop')
        self.assertEqual(resp['data']['stopped'], True)
        self.assertTrue(worker.cancelled)
        self.assertEqual(self.named('assistant.state')[-1]['state'], 'stopped')
        self.assertEqual(len(self.window.retry_by_session['default']), 1)
        payload = self.invoke('chat.session')['data']
        self.assertTrue(payload['retryable'])
        self.assertFalse(payload['busy'])

    def test_failure_and_retry(self):
        worker = self.start_send()
        worker.failed.emit('发送失败')
        worker.finished.emit()
        failed = self.named('assistant.failed')[-1]
        self.assertEqual(failed['message'], '发送失败')
        self.assertTrue(failed['retryable'])
        self.assertEqual(self.named('assistant.state')[-1]['state'], 'failed')
        resp = self.invoke('chat.retry')
        self.assertTrue(resp['ok'], resp)
        self.assertEqual(len(self.workers), 2)
        self.assertTrue(self.workers[-1].started)

    def test_busy_conflict_and_validation(self):
        self.start_send()
        self.assertEqual(self.invoke('chat.send', {'text': '再来'})['error']['code'], 'CONFLICT')
        self.workers[-1].finished.emit()
        empty = self.invoke('chat.send', {'text': '   '})
        self.assertEqual(empty['error']['code'], 'VALIDATION_ERROR')
        self.assertEqual(self.invoke('chat.send', {'text': 'hi', 'sessionId': 'missing'})
                         ['error']['code'], 'NOT_FOUND')
        self.assertEqual(self.invoke('chat.nope')['error']['code'], 'NOT_FOUND')

    def test_result_applies_task_commands(self):
        worker = self.start_send('明天 9 点提醒我开会')
        due = (utc_now() + timedelta(hours=1)).isoformat()
        content = ('好的，已安排。\n```tasks\n'
                   + json.dumps([{'title': '开会', 'due_at': due, 'repeat': 'none'}],
                                ensure_ascii=False)
                   + '\n```')
        worker.result.emit(content)
        worker.finished.emit()
        result = self.named('assistant.result')[-1]
        self.assertIn('已保存：开会', result['reply'])
        self.assertEqual(len(result['tasks']), 1)
        self.assertEqual(result['errors'], [])
        self.assertEqual([row['title'] for row in self.window.store.pending()], ['开会'])
        self.assertIn(('tasks.changed', {'reason': 'chat'}), self.events)
        self.assertTrue(any('开会' in text for text in self.window.pet.said))

    def test_ambiguous_task_choice(self):
        task_id = self.window.store.add('开会', (utc_now() + timedelta(hours=1)).isoformat())
        self.window.task_choice['default'] = {
            'op': {'action': 'complete'}, 'ids': [task_id],
            'prompt': '找到 1 条「开会」，请选择。'}
        payload = self.invoke('chat.session')['data']
        self.assertTrue(payload['choicePending'])
        self.assertEqual(self.invoke('chat.chooseTask', {'index': 0})['error']['code'],
                         'VALIDATION_ERROR')
        resp = self.invoke('chat.chooseTask', {'index': 1})
        self.assertTrue(resp['ok'], resp)
        self.assertIn('已完成：开会', resp['data']['reply'])
        self.assertEqual([row['title'] for row in self.window.store.history()], ['开会'])
        self.assertEqual(self.named('assistant.result')[-1]['tasks'], ['已完成：开会。'])

    def test_send_with_pending_choice_index(self):
        task_id = self.window.store.add('开会', (utc_now() + timedelta(hours=1)).isoformat())
        self.window.task_choice['default'] = {'op': {'action': 'complete'},
                                              'ids': [task_id], 'prompt': '选择'}
        resp = self.invoke('chat.send', {'text': '1'})
        self.assertEqual(resp['data']['mode'], 'choice')
        self.assertEqual(self.workers, [])
        self.assertEqual(len(self.window.store.history()), 1)

    def test_regenerate_branches_session(self):
        self.window.store.add_message('user', '聊聊', 'default')
        worker = self.start_send('聊聊')
        worker.result.emit('{"reply": "第一版"}')
        worker.finished.emit()
        resp = self.invoke('chat.regenerate')
        self.assertTrue(resp['ok'], resp)
        branch = resp['data']['sessionId']
        self.assertNotEqual(branch, 'default')
        self.assertEqual(self.window.active_session, branch)
        self.assertEqual(self.window.store.session(branch)['title'], '另一版 · 默认对话')
        self.assertTrue(any(p['reason'] == 'regenerate' for p in self.named('chat.changed')))
        self.assertTrue(self.workers[-1].started)

    def test_regenerate_result_routes_to_branch_while_browsing_source(self):
        due = (utc_now() + timedelta(hours=1)).isoformat()
        worker = self.start_send('question')
        worker.result.emit(json.dumps({'reply': 'original reply',
                                       'tasks': [{'title': 'original draft', 'due_at': due}]},
                                      ensure_ascii=False))
        worker.finished.emit()
        self.assertTrue(self.invoke('chat.saveInput',
                                    {'sessionId': 'default', 'text': 'unsent original'})['ok'])
        branch = self.invoke('chat.regenerate')['data']['sessionId']
        self.invoke('chat.session', {'sessionId': 'default'})  # browse the source session
        branch_worker = self.workers[-1]
        branch_worker.result.emit('{"reply":"another reply","tasks":[]}')
        branch_worker.finished.emit()
        self.assertEqual(self.window.store.messages(session_id=branch)[-1]['content'],
                         'another reply')
        self.assertIn('已保存：original draft', self.window.store.messages()[-1]['content'])
        self.assertEqual(self.window.store.session('default')['input_text'], 'unsent original')
        self.assertEqual(self.window.store.drafts('default'), [])
        self.assertEqual(len(self.window.store.pending()), 1)
        self.assertEqual(self.window.active_session, 'default')
        self.assertEqual(self.named('assistant.result')[-1]['sessionId'], branch)

    def test_retry_reuses_context_without_duplicate_question(self):
        worker = self.start_send('question')
        worker.failed.emit('boom')
        worker.finished.emit()
        resp = self.invoke('chat.retry')
        self.assertTrue(resp['ok'], resp)
        retry = self.workers[-1]
        self.assertEqual([message['content'] for message in retry.messages], ['question'])
        retry.result.emit('{"reply":"retry success","tasks":[]}')
        retry.finished.emit()
        self.assertEqual(self.window.store.messages(),
                         [{'role': 'user', 'content': 'question'},
                          {'role': 'assistant', 'content': 'retry success'}])

    def test_plan_preview_and_model_result(self):
        now = utc_now()
        # Backdated creation keeps the due time overdue regardless of wall clock,
        # so the snapshot lists the title deterministically.
        self.window.store.add('报告', (now - timedelta(minutes=30)).isoformat(),
                              now=now - timedelta(hours=1))
        preview = self.invoke('chat.planToday')['data']
        self.assertTrue(preview['usesModel'])
        self.assertEqual(preview['snapshot']['overdue_count'], 1)
        self.assertIn('报告', preview['prompt'])

        resp = self.invoke('chat.planToday', {'confirmed': True})
        self.assertTrue(resp['ok'], resp)
        worker = self.workers[-1]
        self.assertTrue(worker.started)
        worker.result.emit('{"reply": "先做报告", "tasks": []}')
        worker.finished.emit()
        plan = self.named('plan.result')[-1]
        self.assertEqual(plan['snapshot']['overdue_count'], 1)
        self.assertEqual(plan['reply'], '先做报告')

    def test_plan_local_mode(self):
        self.window.settings.pop('model', None)
        self.window.settings.pop('base_url', None)
        resp = self.invoke('chat.planToday', {'confirmed': True})
        self.assertTrue(resp['ok'], resp)
        self.assertTrue(resp['data']['local'])
        self.assertEqual(self.workers, [])
        plan = self.named('plan.result')[-1]
        self.assertIn('今日清单', plan['reply'])
        self.assertIn('快照时间', plan['reply'])


class SystemStartupTests(BridgeModuleTestsBase):
    def test_startup_get_and_set(self):
        self.assertEqual(self.invoke('startup.get')['data'], {'enabled': True})
        self.assertTrue(self.invoke('startup.set', {'enabled': False})['ok'])
        self.assertEqual(self.window.startup_manager.calls, [False])
        resp = self.invoke('startup.set', {'enabled': 'x'})
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')

    def test_startup_get_survives_broken_backend(self):
        self.window.startup_manager = FakeStartup(broken=True)
        self.assertEqual(self.invoke('startup.get')['data'], {'enabled': False})

    def test_unknown_system_action(self):
        resp = self.invoke('system.nope')
        self.assertEqual(resp['error']['code'], 'NOT_FOUND')


if __name__ == '__main__':
    unittest.main()
