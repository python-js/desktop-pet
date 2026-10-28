import re
import sys
import threading
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, QTimer, QLockFile, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QDialog,
                             QHBoxLayout, QLabel,
                             QMainWindow, QMenu,
                             QMessageBox, QScrollArea, QSystemTrayIcon,
                             QTabWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
                             QStyle, QShortcut, QComboBox, QInputDialog, QPushButton, QButtonGroup)
from PyQt5.QtGui import QKeySequence

from .assistant import ask, plain_text, reply_preview, RequestCancelled
from .core import REMIND_LIMIT, TaskStore, decode_response, parse_due, utc_now
from .platforms import data_directory, notify
from . import dingtalk
from .ui.common import button, local_time
from .ui.draft_card import DraftCard
from .ui.home import HomePageMixin
from .ui.tasks import TasksPageMixin
from .ui.settings import SettingsPageMixin
from .ui.pet import Pet
from .ui.reminder import ReminderDialog
from .recurrence import REPEAT_LABELS
from .planning import daily_snapshot, planning_prompt, local_plan
from .version import __version__
from .ui.theme import apply_theme, application_icon, ACCENT, INK
from .ui.chat_widgets import MessageHistory, Surface
from qfluentwidgets import PrimaryPushButton, TransparentPushButton, FluentIcon
from .ui.controls import ComboBox as QComboBox, TextEdit as QTextEdit, FLUENT_MODE
from qfluentwidgets import ScrollArea as QScrollArea


def task_title_key(value):
    return ' '.join(str(value).split()).casefold()


SELECTION = re.compile(r'\s*(?:第\s*)?([0-9]{1,2}|[一二三四五六七八九十])\s*(?:个|条|项)?\s*[.。]?\s*')
CHINESE_DIGITS = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                  '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


class AssistantWorker(QThread):
    result = pyqtSignal(str)
    failed = pyqtSignal(str)
    chunk = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, settings, messages, tasks, parent):
        super().__init__(parent)
        self.settings, self.messages = dict(settings), messages
        self.tasks = tasks
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
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


class MainWindow(HomePageMixin, SettingsPageMixin, TasksPageMixin, QMainWindow):
    dingtalk_result = pyqtSignal(bool, str)
    dingtalk_test = pyqtSignal(bool, str)

    def __init__(self, secret_store=None, startup_manager=None):
        super().__init__()
        self.root = data_directory()
        self.store = TaskStore(self.root / 'desktop-pet.sqlite3')
        self.store.reset_notifications()
        self.worker = None
        self.retry_messages = None
        self.retry_by_session = {}
        self.task_choice = {}
        self.request_session = None
        self.stream_content = ''
        self.stream_row = None
        self.exit_pending = False
        self.last_deleted = None
        self.reminders = {}
        self.settings = {}
        self.shutting_down = False
        self.load_configuration(secret_store, startup_manager)
        self.dingtalk_result.connect(self.show_dingtalk_result)
        session_ids = {s['id'] for s in self.store.sessions()}
        self.active_session = self.settings.get('active_session', 'default')
        if self.active_session not in session_ids:
            self.active_session = 'default'
        self.setWindowTitle(f'Desktop Pet {__version__} · 你的待办伙伴')
        self.setMinimumSize(1000, 640)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1180, available.width() - 60), min(820, available.height() - 80))
        icon = application_icon()
        self.setWindowIcon(icon)
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.tabs.setStyleSheet('QTabWidget::pane { border:0; background:transparent; }')
        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(200)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 28, 18, 22)
        side.setSpacing(10)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(application_icon().pixmap(30, 30))
        logo.setFixedSize(30, 30)
        brand_row.addWidget(logo, 0, Qt.AlignTop)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        brand = QLabel('Pet Studio')
        brand.setObjectName('brand')
        brand_text.addWidget(brand)
        tagline = QLabel('你的桌面事务伙伴')
        tagline.setObjectName('subtitle')
        brand_text.addWidget(tagline)
        brand_row.addLayout(brand_text, 1)
        side.addLayout(brand_row)
        side.addSpacing(28)
        if FLUENT_MODE:
            from qfluentwidgets import NavigationInterface, FluentIcon
            self.navigation = NavigationInterface(sidebar, showMenuButton=False, collapsible=False)
            self.navigation.setExpandWidth(164)
            for index, (title, icon_value) in enumerate(zip(
                    ('首页', '对话助手', '待办事项', '偏好设置'),
                    (FluentIcon.HOME, FluentIcon.CHAT, FluentIcon.CHECKBOX, FluentIcon.SETTING))):
                self.navigation.addItem(str(index), icon_value, title,
                                        onClick=lambda checked=False, i=index: self.tabs.setCurrentIndex(i))
            self.navigation.panel.expand(useAni=False)
            self.navigation.panel.topLayout.setSpacing(8)
            for index in range(4):
                item = self.navigation.widget(str(index))
                item.setFixedHeight(40)
                item.itemWidget.setFixedHeight(40)
                font = item.itemWidget.font()
                font.setPixelSize(15)
                item.itemWidget.setFont(font)
            self.navigation.setCurrentItem('0')
            self.tabs.currentChanged.connect(lambda i: self.navigation.setCurrentItem(str(i)))
            side.addWidget(self.navigation, 1)
        else:
            self.navigation = QButtonGroup(self)
            self.nav_buttons = []
            for index, title in enumerate(('首页', '对话助手', '待办事项', '偏好设置')):
                nav = QPushButton(title)
                nav.setProperty('variant', 'nav')
                nav.setCheckable(True)
                nav.clicked.connect(lambda checked=False, i=index: self.tabs.setCurrentIndex(i))
                self.navigation.addButton(nav, index)
                side.addWidget(nav)
                self.nav_buttons.append(nav)
            self.nav_buttons[0].setChecked(True)
            self.tabs.currentChanged.connect(lambda i: self.nav_buttons[i].setChecked(True))
            side.addStretch()
        footer = QLabel(f'DESKTOP PET\nv{__version__}  ·  Windows')
        footer.setObjectName('versionLabel')
        side.addWidget(footer)
        shell_layout.addWidget(sidebar)
        shell_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(shell)
        self.build_home()
        self.build_chat()
        self.build_tasks()
        self.build_settings()
        self.tabs.currentChanged.connect(lambda index: self.refresh_home() if index == 0 else None)
        self.stream_timer = QTimer(self)
        self.stream_timer.setInterval(60)
        self.stream_timer.timeout.connect(self.render_stream)
        self.load_conversation()
        self.statusBar().showMessage('关闭主窗口后可在托盘继续提醒；完全退出后不提醒。')
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu(self)
        menu.addAction('打开聊天与待办', self.show_main)
        menu.addAction('显示 / 隐藏宠物', self.toggle_pet)
        menu.addAction('找回宠物', lambda: self.pet.reset_position())
        menu.addSeparator()
        menu.addAction('退出', self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_main() if reason == QSystemTrayIcon.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.pet = Pet(self)
        image_path = self.settings.get('pet_image', '')
        if image_path and Path(image_path).is_file():
            self.pet.load_image(image_path)
        self.pet.show()
        QApplication.instance().screenRemoved.connect(self.pet.ensure_visible)
        self.refresh_tasks()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_due)
        self.timer.start(2000)
        self.task_refresh_timer = QTimer(self)
        self.task_refresh_timer.timeout.connect(self.refresh_tasks)
        self.task_refresh_timer.start(30000)

    def build_chat(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 28, 30, 20)
        layout.setSpacing(16)
        heading = QLabel('对话助手')
        heading.setObjectName('pageTitle')
        subtitle = QLabel('聊聊想法，梳理计划。说清事项和时间，我来替你记下。')
        subtitle.setObjectName('subtitle')
        header = QHBoxLayout()
        header.setSpacing(12)
        heading_block = QVBoxLayout()
        heading_block.setSpacing(4)
        heading_block.addWidget(heading)
        heading_block.addWidget(subtitle)
        header.addLayout(heading_block, 1)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        def ghost(text, icon, callback):
            control = TransparentPushButton(icon, text, self)
            control.setMinimumHeight(36)
            control.clicked.connect(callback)
            actions.addWidget(control)
            return control
        new_chat = PrimaryPushButton(FluentIcon.ADD, '新对话', self)
        new_chat.setMinimumHeight(36)
        new_chat.clicked.connect(self.new_session)
        actions.addWidget(new_chat)
        ghost('重命名', FluentIcon.EDIT, self.rename_session)
        self.plan_button = ghost('今日规划', FluentIcon.CALENDAR, self.plan_today)
        self.plan_button.setToolTip('预览逾期和今天到期待办；确认后生成规划，保留未发送输入')
        header.addLayout(actions)
        layout.addLayout(header)
        session_row = QHBoxLayout()
        session_row.setSpacing(10)
        session_label = QLabel('当前对话')
        session_label.setObjectName('eyebrow')
        session_row.addWidget(session_label)
        self.session_combo = QComboBox()
        self.session_combo.setMinimumContentsLength(12)
        self.session_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.session_combo.setMinimumWidth(280)
        self.session_combo.setMaximumWidth(360)
        session_row.addWidget(self.session_combo)
        session_row.addStretch()
        layout.addLayout(session_row)
        self.refresh_sessions()
        self.session_combo.currentIndexChanged.connect(self.switch_session)
        self.history = MessageHistory()
        layout.addWidget(self.history, 3)
        # 0.21 起流式内容直接更新历史里的占位消息，独立预览面板保留备查、不再显示：
        # self.stream_preview = MessageHistory()
        # self.stream_preview.setMaximumHeight(160)
        # self.stream_preview.hide()
        # layout.addWidget(self.stream_preview)
        self.draft_area = QScrollArea()
        self.draft_area.setWidgetResizable(True)
        self.draft_area.setMaximumHeight(220)
        self.draft_widget = QWidget()
        self.drafts = QVBoxLayout(self.draft_widget)
        self.draft_area.setWidget(self.draft_widget)
        self.draft_area.hide()
        layout.addWidget(self.draft_area)
        composer = Surface(self)
        composer.setObjectName('composerCard')
        composer.setStyleSheet(f'QFrame#composerCard {{background:#FFFFFF;border:1px solid #F2E8DC;border-radius:16px;}} QFrame#composerCard[focused="true"] {{border-color:{ACCENT};}}')
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(16, 12, 16, 12)
        composer_layout.setSpacing(10)
        self.input = QTextEdit()
        self.input.setObjectName('composer')
        self.input.setStyleSheet(f'QTextEdit#composer {{background:transparent;border:0;border-radius:0;padding:6px;color:{INK};}}')
        self.input.installEventFilter(composer)
        self.input.viewport().installEventFilter(composer)
        self.input.setPlaceholderText('输入消息，Ctrl+Enter 发送；说出事项和时间即可自动创建待办')
        self.input.setMinimumHeight(72)
        self.input.setMaximumHeight(96)
        composer_layout.addWidget(self.input)
        self.input.textChanged.connect(self.save_input)
        row = QHBoxLayout()
        self.chat_status = QLabel('')
        self.chat_status.setObjectName('subtitle')
        self.chat_status.setWordWrap(True)
        row.addWidget(self.chat_status, 1)
        self.send = button('发送', self.send_message, row, primary=True)
        self.stop_button = button('停止当前请求', self.stop_request, row)
        self.stop_button.hide()
        self.retry_button = button('重试上次请求', self.retry_request, row)
        self.retry_button.hide()
        self.regenerate_button = button('生成另一版', self.regenerate_reply, row)
        self.regenerate_button.setToolTip('在新对话中重新回答最后一个已回复问题，保留原对话与任务；需要配置模型')
        row.removeWidget(self.send)
        row.addWidget(self.send)
        composer_layout.addLayout(row)
        layout.addWidget(composer)
        self.shortcut = QShortcut(QKeySequence('Ctrl+Return'), self.input)
        self.shortcut.activated.connect(self.send_message)
        self.tabs.addTab(page, '聊天')

    def refresh_sessions(self):
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        for session in self.store.sessions():
            self.session_combo.addItem(session['title'], session['id'])
        self.session_combo.setCurrentIndex(self.session_combo.findData(self.active_session))
        self.session_combo.blockSignals(False)

    def new_session(self):
        self.active_session = self.store.create_session()
        self.refresh_sessions()
        self.load_conversation()

    def rename_session(self):
        title, accepted = QInputDialog.getText(self, '重命名对话', '名称（最多60字）',
                                               text=self.store.session(self.active_session)['title'])
        if accepted:
            try:
                self.store.rename_session(self.active_session, title)
                self.refresh_sessions()
            except ValueError as exc:
                QMessageBox.warning(self, '名称无效', str(exc))

    def switch_session(self):
        session_id = self.session_combo.currentData()
        if session_id and session_id != self.active_session:
            self.active_session = session_id
            self.load_conversation()

    def save_input(self):
        self.store.save_input(self.active_session, self.input.toPlainText())

    def load_conversation(self):
        self.settings['active_session'] = self.active_session
        self.persist_settings()
        self.history.clear()
        self.stream_row = None
        for message in self.store.messages(session_id=self.active_session):
            self.append_message(message['role'], message['content'])
        while self.drafts.count():
            item = self.drafts.takeAt(0)
            item.widget().deleteLater()
        self.draft_area.hide()
        for draft in self.store.drafts(self.active_session):
            self.add_draft(dict(draft))
        self.input.blockSignals(True)
        self.input.setPlainText(self.store.session(self.active_session)['input_text'])
        self.input.blockSignals(False)
        self.retry_messages = self.retry_by_session.get(self.active_session)
        self.retry_button.setVisible(bool(self.retry_messages))
        self.update_request_status()
        self.render_stream()

    def update_request_status(self):
        busy = self.worker is not None
        self.send.setEnabled(not busy)
        self.plan_button.setEnabled(not busy)
        self.retry_button.setEnabled(not busy)
        self.regenerate_button.setEnabled(
            not busy and bool(self.settings.get('model') and self.settings.get('base_url'))
            and bool(self.store.regeneration_context(self.active_session)))
        self.stop_button.setVisible(busy)
        self.stop_button.setEnabled(busy and not self.worker.cancel_event.is_set())
        if busy:
            if self.worker.cancel_event.is_set():
                self.chat_status.setText('正在停止，等待连接释放（最长约45秒）')
            else:
                self.chat_status.setText('正在回复…' if self.request_session == self.active_session else '其他对话正在回复，可继续浏览和编辑')
        else:
            self.chat_status.setText('可修改设置后重试上次请求' if self.retry_messages else
                                     ('模型聊天' if self.settings.get('model') else '本地规则模式'))

    def append_message(self, role, content):
        # Legacy history stored save notices as assistant text; render these quietly.
        system = role == 'system' or (role == 'assistant' and content.startswith('已保存：'))
        if role == 'assistant' and not system and content.lstrip()[:1] in ('{', '`'):
            # 旧版本把回复存成 JSON 信封，显示时还原成正文。
            content = decode_response(content)[0]
        self.history.append_message('system' if system else role, content)

    def send_message(self):
        text = self.input.toPlainText().strip()
        if not text or self.worker is not None:
            return
        if len(text) > 12000:
            QMessageBox.information(self, '消息过长', '请将消息控制在 12000 字以内。')
            return
        self.store.add_message('user', text, self.active_session)
        self.refresh_sessions()
        self.append_message('user', text)
        self.input.clear()
        self.retry_messages = None
        self.retry_by_session.pop(self.active_session, None)
        self.retry_button.hide()
        if self.apply_task_choice(text):
            return
        self.start_request(self.store.messages(20, self.active_session))

    def plan_today(self):
        if self.worker is not None:
            return
        snapshot = daily_snapshot(self.store.pending())
        prompt = planning_prompt(snapshot)
        uses_model = bool(self.settings.get('model') and self.settings.get('base_url'))
        dialog = QDialog(self)
        dialog.setWindowTitle('今日规划 · 确认待办快照')
        dialog.resize(650, 510)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        notice = QLabel('确认后会将以下待办标题、时间及本对话最近消息发送给已配置的模型服务。'
                        if uses_model else '当前未配置模型，确认后仅在本地整理清单。')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        preview = QTextBrowser()
        preview.setPlainText(prompt)
        layout.addWidget(preview)
        row = QHBoxLayout()
        button('发送给模型' if uses_model else '生成本地清单', dialog.accept, row)
        button('取消', dialog.reject, row)
        layout.addLayout(row)
        if dialog.exec_() == QDialog.Accepted:
            self.submit_daily_plan(snapshot)
        dialog.deleteLater()

    def submit_daily_plan(self, snapshot):
        if self.worker is not None:
            return
        # Keep the exact previewed snapshot in history for retries and follow-up questions.
        self.store.add_message('user', planning_prompt(snapshot), self.active_session)
        self.refresh_sessions()
        self.append_message('user', planning_prompt(snapshot))
        self.retry_messages = None
        self.retry_by_session.pop(self.active_session, None)
        self.retry_button.hide()
        if self.settings.get('model') and self.settings.get('base_url'):
            self.start_request(self.store.messages(20, self.active_session))
        else:
            self.on_reply(local_plan(snapshot))
            self.update_request_status()

    def start_request(self, messages):
        self.request_session = self.active_session
        self.task_choice.pop(self.request_session, None)
        self.stream_content = ''
        self.stream_row = None
        tasks = [dict(row) for row in self.store.pending()]
        self.worker = AssistantWorker(self.settings, messages, tasks, self)
        self.stream_timer.start()
        self.update_request_status()
        if self.request_session == self.active_session:
            self.stream_row = self.history.append_message('assistant', '正在思考…')
        self.render_stream()
        # 用户主动发送时始终跳到最新消息；之后流式更新只在已接近底部时跟随。
        self.history.scroll_to_end()
        self.worker.result.connect(self.on_reply)
        self.worker.failed.connect(self.on_error)
        self.worker.chunk.connect(self.on_chunk)
        self.worker.stopped.connect(self.on_stopped)
        self.worker.finished.connect(self.request_finished)
        self.worker.start()

    def on_chunk(self, content):
        if self.worker is not None and not self.worker.cancel_event.is_set():
            self.stream_content += content

    def render_stream(self):
        if (self.stream_row is None or self.worker is None
                or self.request_session != self.active_session or self.worker.cancel_event.is_set()):
            return
        self.history.update_row(self.stream_row, reply_preview(self.stream_content) or '正在思考…')

    def stop_request(self):
        if self.worker is None:
            return
        self.worker.cancel()
        self.retry_by_session[self.request_session] = list(self.worker.messages)
        if self.active_session == self.request_session:
            self.retry_messages = self.retry_by_session[self.request_session]
            self.retry_button.show()
            if self.stream_row is not None:
                self.history.update_row(self.stream_row, '已停止，未保存这条回复。')
                self.stream_row = None
        self.update_request_status()

    def on_stopped(self):
        self.statusBar().showMessage('已停止，未保存不完整回复，也未创建任务建议。', 8000)

    def retry_request(self):
        if self.retry_messages and self.worker is None:
            self.start_request(self.retry_messages)

    def regenerate_reply(self):
        if self.worker is not None or not (self.settings.get('model') and self.settings.get('base_url')):
            return
        try:
            session_id = self.store.branch_for_regeneration(self.active_session)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 6000)
            return
        self.active_session = session_id
        self.refresh_sessions()
        self.load_conversation()
        self.statusBar().showMessage('已在新对话生成另一版，原对话和任务均保留；相同待办不会重复创建。', 10000)
        self.start_request(self.store.messages(20, session_id))

    def request_finished(self):
        self.stream_timer.stop()
        self.send.setEnabled(True)
        self.worker.deleteLater()
        self.worker = None
        self.request_session = None
        self.stream_content = ''
        self.stream_row = None
        self.update_request_status()
        if self.exit_pending:
            self.quit_app()

    def selection_index(self, text):
        match = SELECTION.fullmatch(text)
        if not match:
            return None
        value = match.group(1)
        return int(value) if value.isdigit() else CHINESE_DIGITS[value]

    def apply_task_choice(self, text):
        """Resolve an ambiguous batch before any model request is made."""
        choice = self.task_choice.get(self.active_session)
        if choice is None:
            return False
        index = self.selection_index(text)
        if index is None:
            self.task_choice.pop(self.active_session, None)
            return False
        ids = choice['ids']
        if not 1 <= index <= len(ids):
            notice = f'请回复 1–{len(ids)} 之间的序号，或输入其他内容取消。'
            self.store.add_message('assistant', notice, self.active_session)
            self.append_message('system', notice)
            return True
        self.task_choice.pop(self.active_session, None)
        try:
            receipt, _ = self.execute_task_op(dict(choice['op'], id=ids[index - 1]), confirmed=True)
        except ValueError as exc:
            receipt = f'操作未执行：{exc}'
        self.store.add_message('assistant', receipt, self.active_session)
        self.append_message('assistant', receipt)
        self.refresh_tasks()
        self.pet.say(plain_text(receipt) or receipt)
        return True

    def build_choice(self, op, rows):
        verbs = {'update': '修改', 'complete': '完成', 'delete': '删除'}
        lines = [f'找到 {len(rows)} 条「{rows[0]["title"]}」，请选择要{verbs[op["action"]]}的那条：', '']
        for index, row in enumerate(rows, 1):
            overdue = '已逾期 · ' if parse_due(row['due_at']) <= utc_now() else ''
            repeat = REPEAT_LABELS.get(row['repeat_rule'], '不重复')
            lines.append(f'{index}. {overdue}{local_time(row["due_at"])} · {repeat}')
        lines.extend(['', '回复序号即可，回复其他内容将取消本次操作。'])
        return {'op': {key: value for key, value in op.items() if key != 'id'},
                'ids': [row['id'] for row in rows], 'prompt': '\n'.join(lines)}

    def execute_task_op(self, op, confirmed=False):
        """Return (receipt, choice); ambiguous operations write nothing."""
        action = op.get('action', 'create')
        pending = self.store.pending()
        if action == 'create':
            repeat = op.get('repeat', 'none')
            dingtalk_flag = bool(op.get('dingtalk'))
            existing = next((row for row in pending
                             if row['title'] == op['title'].strip()
                             and parse_due(row['due_at']) == parse_due(op['due_at'])
                             and row['repeat_rule'] == repeat), None)
            if existing is None:
                self.store.add(op['title'], op['due_at'], repeat=repeat, dingtalk=dingtalk_flag)
            elif dingtalk_flag and not existing['dingtalk']:
                self.store.set_dingtalk(existing['id'], True)
            prefix = '已有待办：' if existing else '已保存：'
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
            due = op.get('due_at', row['due_at'])
            repeat = op.get('repeat', row['repeat_rule'])
            dingtalk = op.get('dingtalk', bool(row['dingtalk']))
            if 'due_at' not in op and parse_due(row['due_at']) <= utc_now():
                raise ValueError('该待办已逾期，请同时给出新的提醒时间')
            self.store.edit(row['id'], title, due, repeat=repeat, dingtalk=dingtalk)
            self.dismiss_reminder(row['id'])
            changes = []
            if title != row['title']:
                changes.append(f'标题「{row["title"]}」→「{title}」')
            if parse_due(due) != parse_due(row['due_at']):
                changes.append(f'时间 {local_time(row["due_at"])} → {local_time(due)}')
            if repeat != row['repeat_rule']:
                changes.append(f'重复 {REPEAT_LABELS[row["repeat_rule"]]} → {REPEAT_LABELS[repeat]}')
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
        self.last_deleted = row['id']
        self.undo_button.setEnabled(True)
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

    def on_reply(self, content):
        if self.worker is not None and self.worker.cancel_event.is_set():
            return
        session_id = self.request_session if self.worker is not None else self.active_session
        self.retry_by_session.pop(session_id, None)
        visible = session_id == self.active_session
        if visible:
            self.retry_messages = None
            self.retry_button.hide()
        reply, tasks, errors = decode_response(content)
        receipts, errors, choice = self.run_task_ops(tasks, session_id) if tasks else ([], errors, None)
        if tasks:
            # Only application-confirmed writes may be described as successful.
            parts = list(receipts)
            if choice:
                parts.append(choice['prompt'])
            reply = '\n\n'.join(parts) or '待办操作未能执行，请补充有效信息后重试。'
            self.refresh_tasks()
        self.store.add_message('assistant', reply, session_id)
        self.refresh_sessions()
        if visible:
            if self.stream_row is not None:
                self.history.update_row(self.stream_row, reply, markdown=True)
                self.stream_row = None
            else:
                self.history.append_message('assistant', reply)
        if errors:
            note = '部分建议未采用：' + '；'.join(errors)
            self.store.add_message('assistant', note, session_id)
            if visible:
                self.append_message('system', note)
        self.pet.say(plain_text(reply) or reply)

    def on_error(self, message):
        if self.worker.cancel_event.is_set():
            return
        session_id = self.request_session
        self.retry_by_session[session_id] = list(self.worker.messages)
        if session_id == self.active_session:
            self.retry_messages = self.retry_by_session[session_id]
            self.retry_button.show()
            text = '发送失败：' + message + '\n可修改设置后点击“重试上次请求”，不会重复添加原消息。'
            if self.stream_row is not None:
                self.history.update_row(self.stream_row, text)
                self.stream_row = None
            else:
                self.append_message('assistant', text)
        else:
            self.statusBar().showMessage('其他对话请求失败，切回该对话可重试。', 8000)

    def add_draft(self, task):
        session_id = self.active_session
        card = DraftCard(self.store, task, session_id, self.draft_widget)

        def remove_card():
            self.drafts.removeWidget(card)
            card.deleteLater()
            self.draft_area.setVisible(self.drafts.count() > 0)

        def saved(message):
            self.store.add_message('assistant', message, session_id)
            if session_id == self.active_session:
                self.append_message('system', message)
            self.refresh_tasks()

        card.saved.connect(saved)
        card.removed.connect(remove_card)
        self.drafts.addWidget(card)
        self.draft_area.show()

    def dismiss_reminder(self, task_id):
        dialog = self.reminders.pop(task_id, None)
        if dialog:
            dialog.close()

    def forget_reminder(self, task_id, dialog):
        self.reminders.pop(task_id, None)
        dialog.deleteLater()

    def open_reminder_task(self, task_id):
        self.dismiss_reminder(task_id)
        self.show_main()
        self.tabs.setCurrentIndex(2)
        self.focus_task(task_id)

    def check_due(self):
        for task in self.store.due():
            task = dict(task)
            task_id = task['id']
            if task_id in self.reminders:
                continue
            final = task.get('remind_count', 0) + 1 >= REMIND_LIMIT
            dialog = ReminderDialog(
                self, task,
                on_complete=lambda checked=False, tid=task_id: self.resolve(tid, False),
                on_snooze=lambda checked=False, tid=task_id: self.resolve(tid, True),
                on_open=lambda checked=False, tid=task_id: self.open_reminder_task(tid),
                final=final)
            dialog.finished.connect(lambda _=0, tid=task_id, d=dialog: self.forget_reminder(tid, d))
            self.reminders[task_id] = dialog
            anchor = self.pet.frameGeometry() if self.pet.isVisible() else None
            dialog.present(anchor, len(self.reminders) - 1)
            self.store.mark_shown(task_id)
            if final:
                self.statusBar().showMessage(f'“{task["title"]}”已提醒 {REMIND_LIMIT} 次，标记为延期，不再提醒。', 10000)
            self.pet.say('到时间了：' + task['title'])
            self.pet.play_action('reminder')
            notify(self.tray, '待办提醒', task['title'])
            if task.get('dingtalk'):
                self.push_dingtalk(task)

    def push_dingtalk(self, task):
        if not self.dingtalk_webhook:
            self.statusBar().showMessage(f'“{task["title"]}”标记了钉钉通知，但尚未配置钉钉机器人。', 10000)
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
        self.statusBar().showMessage(message, 8000)
        if not ok:
            notify(self.tray, '钉钉通知失败', message)

    def toggle_pet(self):
        self.pet.setVisible(not self.pet.isVisible())

    def show_main(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.shutting_down:
            event.accept()
        elif self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.ignore()
            self.quit_app()

    def quit_app(self):
        if self.worker is not None:
            self.exit_pending = True
            self.stop_request()
            self.statusBar().showMessage('正在停止请求，连接释放后自动退出。')
            return
        self.shutting_down = True
        self.timer.stop()
        self.task_refresh_timer.stop()
        self.pet.close()
        self.tray.hide()
        self.store.close()
        QApplication.instance().quit()


def main():
    try:
        # 3D 视图使用的 QtWebEngine 需要在 QApplication 之前初始化。
        from PyQt5 import QtWebEngineWidgets  # noqa: F401
    except ImportError:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName('DesktopPet')
    lock = QLockFile(str(data_directory() / 'application.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, 'Desktop Pet 已在运行', '请通过系统托盘打开已有窗口，避免重复提醒。')
        return
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    window = MainWindow()
    if '--background' not in sys.argv or not window.tray.isVisible():
        window.show()
    result = app.exec_()
    lock.unlock()
    sys.exit(result)
