import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, QLockFile, Signal, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QMessageBox, QSystemTrayIcon

from .assistant import ask, plain_text, RequestCancelled
from .bridge import BridgeHost
from .core import (HORIZON_LABELS, REMIND_LIMIT, TaskStore, decode_response, in_quiet_hours,
                   local_day_bounds, parse_due, utc_now)
from .platforms import data_directory, notify
from . import dingtalk, knowledge, update, websearch
from .shell import ShellMixin, local_time
from .ui.pet import Pet
from .ui.reminder_popup import ReminderPopup
from .recurrence import REPEAT_LABELS
from .version import __version__
from .ui.theme import apply_theme, application_icon


def task_title_key(value):
    return ' '.join(str(value).split()).casefold()


def due_text(value):
    return local_time(value) if value else '待安排'


def horizon_label(task):
    return HORIZON_LABELS.get(task['horizon'] if 'horizon' in task.keys() else 'timed', '')


SELECTION = re.compile(r'\s*(?:第\s*)?([0-9]{1,2}|[一二三四五六七八九十])\s*(?:个|条|项)?\s*[.。]?\s*')
CHINESE_DIGITS = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                  '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


class AssistantWorker(QThread):
    result = Signal(str)
    failed = Signal(str)
    chunk = Signal(str)
    stopped = Signal()
    search_started = Signal()
    searched = Signal(object)
    search_failed = Signal(str)
    knowledge_started = Signal()
    knowledge_searched = Signal(object)

    def __init__(self, settings, messages, tasks, parent, web_query='', knowledge=None,
                 knowledge_query=''):
        super().__init__(parent)
        self.settings, self.messages = dict(settings), messages
        self.tasks = tasks
        self.web_query = web_query
        self.knowledge = knowledge
        self.knowledge_query = knowledge_query
        self.searching = False
        self.reading = False
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            knowledge_context = ''
            if self.knowledge_query and self.knowledge is not None:
                self.reading = True
                self.knowledge_started.emit()
                try:
                    hits = self.knowledge.search(self.knowledge_query)
                    if self.cancel_event.is_set():
                        raise RequestCancelled()
                    if hits:
                        knowledge_context = knowledge.format_context(hits)
                        self.knowledge_searched.emit(hits)
                except RequestCancelled:
                    raise
                except (ValueError, OSError):
                    pass
                finally:
                    self.reading = False
            context = ''
            if self.web_query and self.settings.get('tavily_key'):
                self.searching = True
                self.search_started.emit()
                try:
                    found = websearch.tavily_search(self.settings['tavily_key'], self.web_query,
                                                    self.cancel_event.is_set)
                    if self.cancel_event.is_set():
                        raise RequestCancelled()
                    context = websearch.format_context(found)
                    self.searched.emit(found['results'])
                except RequestCancelled:
                    raise
                except ValueError as exc:
                    self.search_failed.emit(str(exc))
                finally:
                    self.searching = False
            context = '\n\n'.join(part for part in (knowledge_context, context) if part)
            if context:
                result = ask(self.settings, self.messages, self.chunk.emit,
                             self.cancel_event.is_set, self.tasks, search_context=context)
            else:
                result = ask(self.settings, self.messages, self.chunk.emit,
                             self.cancel_event.is_set, self.tasks)
            if self.cancel_event.is_set():
                self.stopped.emit()
            else:
                self.result.emit(result)
        except RequestCancelled:
            self.stopped.emit()
        except Exception as exc:
            if self.cancel_event.is_set():
                self.stopped.emit()
                return
            # Only deliberate user-facing errors are exposed, never arbitrary exceptions.
            self.failed.emit(str(exc) if isinstance(exc, ValueError) else '请求失败，请检查模型设置后重试。')


INSTANCE_MUTEX_NAME = 'DesktopPetSingleInstance'
_INSTANCE_MUTEX = None


def hold_instance_mutex():
    """Keep a named mutex alive so the Inno Setup installer can detect a running app."""
    global _INSTANCE_MUTEX
    if sys.platform != 'win32' or _INSTANCE_MUTEX:
        return
    try:
        import ctypes
        _INSTANCE_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, INSTANCE_MUTEX_NAME)
    except (AttributeError, OSError):
        _INSTANCE_MUTEX = None


class MainWindow(ShellMixin, QMainWindow):
    dingtalk_result = Signal(bool, str)
    update_announce = Signal(object)

    def __init__(self, secret_store=None, startup_manager=None):
        super().__init__()
        self.root = data_directory()
        self.updates = update.UpdateManager(self.root, __version__)
        self.store = TaskStore(self.root / 'desktop-pet.sqlite3')
        self.knowledge = knowledge.KnowledgeBase(self.root / 'knowledge')
        self.store.reset_notifications()
        self.worker = None
        self.web_chat_worker = None
        self.retry_by_session = {}
        self.task_choice = {}
        self.exit_pending = False
        self.web_reminders = set()
        self.reminder_popups = {}
        self.settings = {}
        self.shutting_down = False
        self.update_notice_pending = False
        self._hidden_at = None
        self.load_configuration(secret_store, startup_manager)
        self.theme = self.settings.get('theme', 'light')
        if QApplication.instance() is not None:
            apply_theme(QApplication.instance(), self.theme)
        self.dingtalk_result.connect(self.show_dingtalk_result)
        self.update_announce.connect(self.announce_update)
        session_ids = {s['id'] for s in self.store.sessions()}
        self.active_session = self.settings.get('active_session', 'default')
        if self.active_session not in session_ids:
            self.active_session = 'default'
        self.setWindowTitle(f'Desktop Pet {__version__} · 你的待办伙伴')
        self.setMinimumSize(900, 640)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1180, available.width() - 60), min(820, available.height() - 80))
        icon = application_icon()
        self.setWindowIcon(icon)
        self.bridge = BridgeHost(context={'data_dir': str(self.root), 'window': self})
        from . import bridge_modules
        bridge_modules.install(self.bridge)
        from .ui.webshell import WebShell
        self.web_shell = WebShell(self.bridge, self)
        self.setCentralWidget(self.web_shell)
        self.devtools_shortcut = QShortcut(QKeySequence('F12'), self)
        self.devtools_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.devtools_shortcut.activated.connect(self.open_web_devtools)
        self.statusBar().hide()
        self.bridge.emit_event('app.launched', {'version': __version__, 'theme': self.theme,
                                                'shell': 'web'})
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip('小满桌面助手')
        menu = QMenu(self)
        menu.addSection('小满桌面助手')
        menu.addAction('打开主界面', self.show_main)
        menu.addAction('网页调试工具', self.open_web_devtools)
        self.tray_toggle_action = menu.addAction('隐藏桌宠', self.toggle_pet)
        menu.addAction('找回桌宠位置', self.reset_pet_position)
        menu.addSeparator()
        menu.addAction('退出小满', self.quit_app)
        menu.aboutToShow.connect(self.update_tray_menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_main() if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.messageClicked.connect(self.on_tray_message_clicked)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        if self.settings_warning:
            self.tray.showMessage('设置提示', self.settings_warning.strip(),
                                  QSystemTrayIcon.Warning, 8000)
        self.pet = Pet(self)
        image_path = self.settings.get('pet_image', '')
        self.pet.load_image(image_path if image_path and Path(image_path).is_file() else '')
        self.pet.show()
        QApplication.instance().screenRemoved.connect(self.pet.ensure_visible)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_due)
        self.timer.start(2000)
        QTimer.singleShot(10000, self.auto_check_updates)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.auto_check_updates)
        # 长驻进程不会重启，周期触发配合按日护栏即可每天补检一次。
        self.update_timer.start(6 * 60 * 60 * 1000)

    def update_tray_menu(self):
        """Refresh stateful tray labels when the native menu opens."""
        pet_visible = bool(getattr(self, 'pet', None) and self.pet.isVisible())
        self.tray_toggle_action.setText('隐藏桌宠' if pet_visible else '显示桌宠')

    def open_web_devtools(self):
        self.show_main()
        self.web_shell.show_devtools()

    def selection_index(self, text):
        match = SELECTION.fullmatch(text)
        if not match:
            return None
        value = match.group(1)
        return int(value) if value.isdigit() else CHINESE_DIGITS[value]

    def build_choice(self, op, rows):
        verbs = {'update': '修改', 'complete': '完成', 'delete': '删除'}
        lines = [f'找到 {len(rows)} 条「{rows[0]["title"]}」，请选择要{verbs[op["action"]]}的那条：', '']
        for index, row in enumerate(rows, 1):
            overdue = '已逾期 · ' if row['due_at'] and parse_due(row['due_at']) <= utc_now() else ''
            repeat = horizon_label(row) or REPEAT_LABELS.get(row['repeat_rule'], '不重复')
            lines.append(f'{index}. {overdue}{due_text(row["due_at"])} · {repeat}')
        lines.extend(['', '回复序号即可，回复其他内容将取消本次操作。'])
        return {'op': {key: value for key, value in op.items() if key != 'id'},
                'ids': [row['id'] for row in rows], 'prompt': '\n'.join(lines)}

    def execute_task_op(self, op, confirmed=False):
        """Return (receipt, choice); ambiguous operations write nothing."""
        action = op.get('action', 'create')
        pending = self.store.pending()
        if action == 'create':
            horizon = op.get('horizon', 'timed')
            repeat = op.get('repeat', 'none') if horizon == 'timed' else 'none'
            dingtalk_flag = bool(op.get('dingtalk'))
            existing = next((row for row in pending
                             if row['title'] == op['title'].strip()
                             and row['horizon'] == horizon
                             and (horizon != 'timed'
                                  or (row['due_at'] and op.get('due_at')
                                      and parse_due(row['due_at']) == parse_due(op['due_at'])
                                      and row['repeat_rule'] == repeat))), None)
            if existing is None:
                self.store.add(op['title'], op.get('due_at'), repeat=repeat, dingtalk=dingtalk_flag,
                               source='chat', horizon=horizon)
            elif dingtalk_flag and not existing['dingtalk']:
                self.store.set_dingtalk(existing['id'], True)
            prefix = '已有待办：' if existing else '已保存：'
            if horizon != 'timed':
                return f"{prefix}{op['title']}，{HORIZON_LABELS[horizon]}。", None
            channel = ''
            if dingtalk_flag:
                channel = ('，到期后推送到钉钉群' if self.dingtalk_webhook
                           else '，尚未配置钉钉机器人，到期仅本地提醒')
            return (f"{prefix}{op['title']}，提醒时间 {local_time(op['due_at'])}，"
                    f"{REPEAT_LABELS[repeat]}{channel}。"), None
        if action not in ('update', 'complete', 'delete'):
            raise ValueError('不支持的任务操作')
        row = next((item for item in pending if item['id'] == op['id']), None)
        if row is None:
            raise ValueError('待办已不存在或已完成')
        if not confirmed:
            same = [item for item in pending
                    if task_title_key(item['title']) == task_title_key(row['title'])]
            if len(same) > 1:
                return None, self.build_choice(op, same)
        return self.apply_existing_op(op, row), None

    def apply_existing_op(self, op, row):
        action = op['action']
        if action == 'update':
            title = op.get('title', row['title'])
            horizon = op.get('horizon', row['horizon'])
            due = op.get('due_at', row['due_at'])
            repeat = op.get('repeat', row['repeat_rule']) if horizon == 'timed' else 'none'
            dingtalk = op.get('dingtalk', bool(row['dingtalk']))
            if (horizon == 'timed' and 'due_at' not in op and row['due_at']
                    and parse_due(row['due_at']) <= utc_now()):
                raise ValueError('该待办已逾期，请同时给出新的提醒时间')
            self.store.edit(row['id'], title, due, repeat=repeat, dingtalk=dingtalk, horizon=horizon)
            self.dismiss_reminder(row['id'])
            after = dict(self.store.db.execute('SELECT * FROM tasks WHERE id=?', (row['id'],)).fetchone())
            changes = []
            if title != row['title']:
                changes.append(f'标题「{row["title"]}」→「{title}」')
            if (after['due_at'], after['horizon']) != (row['due_at'], row['horizon']):
                changes.append(f'时间 {due_text(row["due_at"])} → {due_text(after["due_at"])}')
            if after['repeat_rule'] != row['repeat_rule']:
                changes.append(f'重复 {REPEAT_LABELS[row["repeat_rule"]]} → {REPEAT_LABELS[after["repeat_rule"]]}')
            if bool(dingtalk) != bool(row['dingtalk']):
                changes.append('钉钉通知已开启' if dingtalk else '钉钉通知已关闭')
            return '已修改：' + ('；'.join(changes) + '。' if changes
                                else f'「{title}」没有需要变更的内容。')
        if action == 'complete':
            next_id = self.store.complete(row['id'])
            self.dismiss_reminder(row['id'])
            if next_id:
                following = next((item for item in self.store.pending() if item['id'] == next_id), None)
                when = f'，已生成下一次：{local_time(following["due_at"])}' if following else ''
                return f'已完成：{row["title"]}{when}。'
            return f'已完成：{row["title"]}。'
        self.store.delete(row['id'])
        self.dismiss_reminder(row['id'])
        return f'已删除：{row["title"]}（可在待办页撤销删除）。'

    def run_task_ops(self, ops, session_id):
        receipts, errors, choice = [], [], None
        for op in ops:
            try:
                receipt, ambiguous = self.execute_task_op(op)
            except ValueError as exc:
                label = op.get('title') or '待办'
                errors.append(f'{label}：{exc}')
                continue
            if ambiguous is not None:
                if choice is None:
                    choice = ambiguous
                else:
                    errors.append('一次只能确认一条待办，请先回复上一条的序号。')
                continue
            receipts.append(receipt)
        if choice is not None:
            self.task_choice[session_id] = choice
        return receipts, errors, choice

    def dismiss_reminder(self, task_id):
        self.web_reminders.discard(task_id)
        popup = self.reminder_popups.pop(task_id, None)
        if popup is not None:
            popup.dispose()
            self.restack_reminders()

    def close_web_reminder(self, task_id, postpone=True):
        """Drop the reminder card and auto-postpone when unanswered."""
        if task_id not in self.web_reminders and task_id not in self.reminder_popups:
            return False
        self.dismiss_reminder(task_id)
        if postpone and self.settings.get('auto_postpone'):
            self.store.snooze(task_id, datetime.now(timezone.utc), minutes=10, auto=True)
            return True
        return False

    def show_reminder(self, task):
        """Pin a due-task card just above the pet's head."""
        if not self.pet.isVisible():
            return
        label = horizon_label(task) or REPEAT_LABELS.get(task['repeat_rule'], '不重复')
        popup = ReminderPopup(task, due_text(task['due_at']), label, self.pet)
        popup.action.connect(self.resolve_reminder)
        self.reminder_popups[task['id']] = popup
        self.restack_reminders()
        popup.show_at_pet()

    def restack_reminders(self):
        for index, popup in enumerate(self.reminder_popups.values()):
            popup.set_slot(index)

    def resolve_reminder(self, task_id, action):
        popup = self.reminder_popups.pop(task_id, None)
        if popup is not None:
            popup.dispose()
        self.web_reminders.discard(task_id)
        self.restack_reminders()
        title = popup.task.get('title') if popup is not None else '待办'
        try:
            if action == 'complete':
                next_id = self.store.complete(task_id)
                following = next((row for row in self.store.pending() if row['id'] == next_id), None)
                self.pet.say(f'已完成：{title}'
                             + (f'，下次 {local_time(following["due_at"])}' if following else ''))
            elif action == 'snooze':
                self.store.snooze(task_id, minutes=10)
                self.pet.say('好的，10 分钟后再提醒你。')
            elif action == 'mute':
                self.store.mute_today(task_id)
                self.pet.say('今天不再提醒这件。')
            elif action == 'close' and self.settings.get('auto_postpone'):
                self.store.snooze(task_id, minutes=10, auto=True)
        except ValueError:
            pass
        if action == 'open':
            self.show_main()
            self.bridge.emit_event('ui.navigate', {'page': 'tasks'})
        self.bridge.emit_event('tasks.changed', {'reason': 'reminder'})

    def quiet_reason(self, now):
        if self.settings.get('pet_paused'):
            return 'paused'
        if self.settings.get('dnd_enabled', True):
            try:
                if in_quiet_hours(now, self.settings.get('dnd_start'), self.settings.get('dnd_end')):
                    return 'dnd'
            except ValueError:
                pass
        return ''

    def check_due(self):
        now = datetime.now().astimezone()
        current = now.astimezone(timezone.utc)
        quiet = self.quiet_reason(now)
        self.check_due_web(current, quiet, now)
        self.check_early(now, current, quiet)
        self.check_inbox_review(now, quiet)

    def check_inbox_review(self, now, quiet=''):
        """周五 17:00 后提醒一次回顾待安排收集箱。"""
        if quiet or now.weekday() != 4 or now.hour < 17:
            return
        today = now.date().isoformat()
        if self.settings.get('last_inbox_review') == today:
            return
        count = self.store.inbox_count()
        if not count:
            return
        self.settings['last_inbox_review'] = today
        try:
            self.persist_settings()
        except OSError:
            pass
        self.pet.say(f'待安排里还有 {count} 项，要不要整理一下？')
        self.bridge.emit_event('inbox.review', {'count': count})

    def announce_due(self, task, final):
        self.pet.play_action('reminder')
        if not self.pet.isVisible():
            self.update_notice_pending = False
            notify(self.tray, '待办提醒', task['title'])
        if self.settings.get('sound_enabled', True):
            QApplication.beep()
        if task.get('dingtalk'):
            self.push_dingtalk(task)

    def check_due_web(self, current, quiet, now):
        """Hand due tasks to reminder cards above the pet; popups stay shell-side."""
        batch, quiet_logged = [], False
        day_start = local_day_bounds(now)[0]
        for task in self.store.due(current):
            task = dict(task)
            task_id = task['id']
            if task_id in self.web_reminders:
                continue
            if quiet:
                if not self.store.quiet_logged(task_id, day_start):
                    self.store.record_quiet(task_id, current, quiet)
                    quiet_logged = True
                continue
            count, deferred = self.store.mark_shown(task_id, current)
            task.update(remind_count=count, deferred=int(deferred), final=bool(deferred))
            self.web_reminders.add(task_id)
            batch.append(task)
            self.announce_due(task, final=bool(deferred))
            self.show_reminder(task)
        if quiet_logged:
            self.bridge.emit_event('tasks.changed', {'reason': 'quiet'})
        if batch:
            self.bridge.emit_event('reminder.due', {'tasks': batch})
            self.bridge.emit_event('tasks.changed', {'reason': 'reminder'})

    def check_early(self, now, current, quiet):
        if quiet or not self.settings.get('early_nudge', True):
            return
        batch = []
        for task in self.store.early_due(current):
            task = dict(task)
            minutes = max(1, int((parse_due(task['due_at']) - current).total_seconds() // 60))
            if self.store.mark_early_shown(task['id'], current):
                task['minutesLeft'] = minutes
                batch.append(task)
                self.pet.say(f'还有 {minutes} 分钟：{task["title"]}')
        if batch:
            self.bridge.emit_event('reminder.early', {'tasks': batch})
            self.bridge.emit_event('tasks.changed', {'reason': 'early'})

    def push_dingtalk(self, task):
        if not self.dingtalk_webhook:
            return
        title = task['title']
        due_label = local_time(task['due_at'])
        repeat_label = REPEAT_LABELS.get(task['repeat_rule'], '不重复')
        webhook, secret = self.dingtalk_webhook, self.dingtalk_secret

        def work():
            try:
                dingtalk.send(webhook, secret, title, due_label, repeat_label)
                ok, message = True, f'已发送到钉钉群：{title}'
            except (OSError, ValueError) as exc:
                ok, message = False, f'钉钉通知失败：{exc}'
            try:
                self.dingtalk_result.emit(ok, message)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def show_dingtalk_result(self, ok, message):
        if not ok:
            self.update_notice_pending = False
            notify(self.tray, '钉钉通知失败', message)

    def toggle_pet(self):
        visible = not self.pet.isVisible()
        if not visible:
            for popup in self.reminder_popups.values():
                popup.dispose()
            self.reminder_popups.clear()
        self.pet.setVisible(visible)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._hidden_at = time.time()

    def _hidden_seconds(self):
        if self._hidden_at is None:
            return 0.0
        elapsed = time.time() - self._hidden_at
        self._hidden_at = None
        return max(0.0, elapsed)

    def showEvent(self, event):
        super().showEvent(event)
        hidden = self._hidden_seconds()
        QTimer.singleShot(0, lambda: self._wake_shell(hidden))

    def _wake_shell(self, hidden_seconds=0.0):
        shell = getattr(self, 'web_shell', None)
        if shell is not None:
            shell.ensure_alive(hidden_seconds)

    def show_main(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.shutting_down:
            self.knowledge.close()
            event.accept()
        elif self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.ignore()
            self.quit_app()

    def update_status(self):
        return self.updates.status(self.settings.get('skipped_version', ''))

    def auto_check_updates(self):
        if not getattr(sys, 'frozen', False):
            return
        if self.update_status()['state'] in ('downloading', 'installing', 'ready'):
            return
        today = datetime.now().astimezone().date().isoformat()
        if self.settings.get('last_update_check') == today:
            return
        self.settings['last_update_check'] = today
        try:
            self.persist_settings()
        except OSError:
            pass
        self.check_updates_async(notify=True)

    def check_updates_async(self, notify=False):
        if not self.updates.begin_check():
            return False
        self.bridge.emit_event('update.state', self.update_status())

        def work():
            try:
                self.updates.check()
            except update.UpdateError as exc:
                self.updates.fail(str(exc))
            status = self.update_status()
            self.bridge.emit_event('update.state', status)
            if notify:
                self.update_announce.emit(status)

        threading.Thread(target=work, daemon=True).start()
        return True

    def announce_update(self, status):
        if not update.should_announce(status, self.settings.get('skipped_version', ''),
                                      self.settings.get('update_notified_version', '')):
            return
        if not (self.tray.isVisible() and self.tray.supportsMessages()):
            return
        version = status['manifest']['version']
        self.update_notice_pending = True
        self.tray.showMessage('发现新版本', f'v{version} 已发布，点击打开设置页下载安装。',
                              QSystemTrayIcon.MessageIcon.Information, 10000)
        self.settings['update_notified_version'] = version
        try:
            self.persist_settings()
        except OSError:
            pass

    def on_tray_message_clicked(self):
        if not self.update_notice_pending:
            return
        self.update_notice_pending = False
        self.show_main()
        self.bridge.emit_event('ui.navigate', {'page': 'settings'})

    def download_update(self, job_id='', cancel_event=None):
        if not self.updates.begin_download():
            return False
        self.bridge.emit_event('update.state', self.update_status())

        def progress(received, total):
            self.updates.progress(received, total)
            self.bridge.emit_event('update.progress', {
                'jobId': job_id, 'received': received, 'total': total,
            })

        def work():
            try:
                self.updates.download(progress, cancel_event.is_set if cancel_event else None)
            except update.UpdateCancelled:
                self.updates.cancelled()
            except (update.UpdateError, OSError) as exc:
                self.updates.fail(str(exc))
            finally:
                self.bridge.emit_event('update.state', self.update_status())
                if job_id:
                    self.bridge.finish_job(job_id)

        threading.Thread(target=work, daemon=True).start()
        return True

    def install_update(self):
        if not getattr(sys, 'frozen', False):
            raise update.UpdateError('当前为开发版，无法自动安装更新')
        if not self.updates.ready_installer():
            raise update.UpdateError('安装包尚未下载或校验失败')
        if not self.updates.begin_install():
            raise update.UpdateError('更新正在安装，请稍候')
        log_path = self.root / 'updates' / 'install.log'
        try:
            update.spawn_installer(self.updates.setup_path, Path(sys.executable), log_path)
        except (OSError, update.UpdateError) as exc:
            self.updates.fail(f'无法启动安装程序：{exc}')
            raise update.UpdateError('无法启动安装程序，请稍后重试') from None
        self.bridge.emit_event('update.state', self.update_status())
        QTimer.singleShot(600, self.quit_app)

    def quit_app(self):
        web_worker = getattr(self, 'web_chat_worker', None)
        if self.worker is not None or web_worker is not None:
            self.exit_pending = True
            if self.worker is not None:
                self.worker.cancel()
            if web_worker is not None:
                web_worker.cancel()
            return
        self.shutting_down = True
        self.timer.stop()
        self.pet.close()
        self.tray.hide()
        self.knowledge.close()
        self.store.close()
        QApplication.instance().quit()


def main():
    if os.environ.get('DESKTOP_PET_DEV'):
        # 前端 dev 模式的调试通道;必须在 WebEngine 初始化前设置。
        os.environ.setdefault('QTWEBENGINE_REMOTE_DEBUGGING', '127.0.0.1:9223')
    app = QApplication(sys.argv)
    app.setApplicationName('DesktopPet')
    hold_instance_mutex()
    try:
        # WebShell 依赖 QtWebEngine;缺失时明确提示，而不是静默回退。
        from PySide6 import QtWebEngineWidgets  # noqa: F401
    except ImportError:
        QMessageBox.critical(None, '缺少网页组件',
                             '当前环境缺少 QtWebEngine，无法打开界面。\n请重新安装完整的 PySide6 后重试。')
        sys.exit(1)
    lock = QLockFile(str(data_directory() / 'application.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, 'Desktop Pet 已在运行', '请通过系统托盘打开已有窗口，避免重复提醒。')
        return
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    if '--background' not in sys.argv or not window.tray.isVisible():
        window.show()
    result = app.exec()
    lock.unlock()
    sys.exit(result)
