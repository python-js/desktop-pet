import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, QTimer, QLockFile, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QDialog,
                             QHBoxLayout, QLabel,
                             QMainWindow, QMenu,
                             QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                             QSystemTrayIcon, QTabWidget, QTextEdit,
                             QVBoxLayout, QWidget, QStyle, QShortcut, QComboBox,
                             QInputDialog)
from PyQt5.QtGui import QFont, QKeySequence

from .assistant import ask, local_reply, plain_text, reply_preview, RequestCancelled
from .core import (REMIND_LIMIT, TaskStore, decode_response, in_quiet_hours,
                   local_day_bounds, parse_due, utc_now)
from .platforms import data_directory, notify
from . import dingtalk
from .ui.common import PlanDialog, button, frozen_updates, local_time
from .ui.draft_card import DraftCard
from .ui.home import HomePageMixin, Line
from .ui.tasks import TasksPageMixin
from .ui.settings import SettingsPageMixin
from .ui.chat_rail import ChatRail
from .ui.pet import Pet
from .ui.reminder import ReminderDialog
from .recurrence import REPEAT_LABELS
from .planning import daily_snapshot, planning_prompt, local_plan
from .version import __version__
from .ui import icons, tokens as T
from .ui.components import IconButton, LiveBadge, NavButton
from .ui.pet_tag import PetTag
from .ui.theme import apply_theme, application_icon, tokens
from .ui.chat_widgets import ComposerCard, MessageHistory, ModelChip
from qfluentwidgets import PrimaryPushButton, TransparentPushButton, FluentIcon
from .ui.controls import ComboBox as QComboBox, TextEdit as QTextEdit


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
    settings_test = pyqtSignal(bool, str)

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
        self.error_row = None
        self.request_model = ''
        self.request_started = None
        self.exit_pending = False
        self.last_deleted = None
        self.reminders = {}
        self.settings = {}
        self.shutting_down = False
        self.load_configuration(secret_store, startup_manager)
        self.theme = self.settings.get('theme', 'light')
        self.sidebar_collapsed = bool(self.settings.get('sidebar_collapsed', False))
        if QApplication.instance() is not None:
            apply_theme(QApplication.instance(), self.theme)
        self.dingtalk_result.connect(self.show_dingtalk_result)
        self.settings_test.connect(self.on_settings_test)
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
        self.build_shell()
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
        self.apply_layout(self.width(), force=True)
        self.refresh_pet_tag()
        self.refresh_tasks()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_due)
        self.timer.start(2000)
        self.task_refresh_timer = QTimer(self)
        self.task_refresh_timer.timeout.connect(self.refresh_tasks)
        self.task_refresh_timer.start(30000)

    def build_shell(self):
        self.tabs = QTabWidget()
        self.tabs.setObjectName('mainTabs')
        self.tabs.tabBar().hide()
        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.sidebar = QWidget()
        self.sidebar.setObjectName('sidebar')
        self.sidebar.setAttribute(Qt.WA_StyledBackground, True)
        self.side_layout = QVBoxLayout(self.sidebar)
        self.side_layout.setContentsMargins(T.SIDEBAR_PAD, 16, T.SIDEBAR_PAD, 12)
        self.side_layout.setSpacing(4)

        self.logo = QLabel()
        self.logo.setPixmap(application_icon().pixmap(30, 30))
        self.logo.setFixedSize(30, 30)
        logo = self.logo
        self.brand_full = QWidget()
        brand_row = QHBoxLayout(self.brand_full)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(10)
        brand_row.addWidget(logo, 0, Qt.AlignVCenter)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        brand = QLabel('Pet Studio')
        brand.setObjectName('brand')
        brand_text.addWidget(brand)
        tagline = QLabel('你的桌面事务伙伴')
        tagline.setObjectName('subtitle')
        brand_text.addWidget(tagline)
        brand_row.addLayout(brand_text, 1)
        self.brand_compact = QWidget()
        compact_row = QHBoxLayout(self.brand_compact)
        compact_row.setContentsMargins(0, 0, 0, 0)
        compact_row.addStretch()
        self.compact_logo = QLabel()
        self.compact_logo.setPixmap(application_icon().pixmap(30, 30))
        self.compact_logo.setFixedSize(30, 30)
        compact_row.addWidget(self.compact_logo)
        compact_row.addStretch()
        self.side_layout.addWidget(self.brand_full)
        self.side_layout.addWidget(self.brand_compact)
        self.brand_compact.hide()
        self.side_layout.addSpacing(20)

        nav_host = QWidget()
        nav_box = QVBoxLayout(nav_host)
        nav_box.setContentsMargins(0, 0, 0, 0)
        nav_box.setSpacing(2)
        self.nav_buttons = []
        self.nav_todo = None
        for index, (title, icon_name) in enumerate((
                ('首页', 'home'), ('对话助手', 'chat'),
                ('待办事项', 'todo'), ('偏好设置', 'gear'))):
            nav = NavButton(title, icon_name)
            nav.clicked.connect(lambda checked=False, i=index: self.tabs.setCurrentIndex(i))
            nav_box.addWidget(nav)
            self.nav_buttons.append(nav)
            if title == '待办事项':
                self.nav_todo = nav
        self.nav_buttons[0].setChecked(True)
        self.side_layout.addWidget(nav_host)
        self.side_layout.addStretch()

        self.pet_tag = PetTag()
        self.pet_tag.set_paused(bool(self.settings.get('pet_paused')))
        self.pet_tag.chat_requested.connect(self.open_chat_input)
        self.pet_tag.pause_toggled.connect(self.toggle_pet_pause)
        self.side_layout.addWidget(self.pet_tag)
        self.side_layout.addSpacing(8)

        footer = QHBoxLayout()
        footer.setSpacing(4)
        self.version_label = QLabel(f'v{__version__}')
        self.version_label.setObjectName('versionLabel')
        footer.addWidget(self.version_label)
        footer.addStretch()
        self.theme_button = IconButton('sun' if self.theme == 'dark' else 'moon',
                                       '切换纸白 / 夜幕')
        self.theme_button.clicked.connect(self.toggle_theme)
        footer.addWidget(self.theme_button)
        self.side_layout.addLayout(footer)
        shell_layout.addWidget(self.sidebar)

        main_column = QWidget()
        main_box = QVBoxLayout(main_column)
        main_box.setContentsMargins(0, 0, 0, 0)
        main_box.setSpacing(0)
        winbar = QWidget()
        winbar.setObjectName('winbar')
        winbar.setAttribute(Qt.WA_StyledBackground, True)
        winbar.setFixedHeight(T.WINBAR_H)
        win_box = QHBoxLayout(winbar)
        win_box.setContentsMargins(16, 0, 12, 0)
        win_box.setSpacing(8)
        self.sidebar_toggle = IconButton('side', '展开侧边栏' if self.sidebar_collapsed else '收起侧边栏')
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        win_box.addWidget(self.sidebar_toggle)
        self.win_mark = QLabel()
        self.win_mark.setPixmap(icons.pixmap('paw', tokens().brand, 14))
        self.win_mark.setFixedSize(14, 14)
        win_box.addWidget(self.win_mark)
        win_title = QLabel('Pet Studio')
        win_title.setObjectName('winbarTitle')
        win_box.addWidget(win_title)
        win_context = QLabel('· 控制台')
        win_context.setObjectName('winbarContext')
        win_box.addWidget(win_context)
        win_box.addStretch()
        paused = bool(self.settings.get('pet_paused'))
        self.live_badge = LiveBadge('小满 正在歇会儿' if paused else '小满 正在桌面值守',
                                    'muted' if paused else 'calm')
        win_box.addWidget(self.live_badge)
        main_box.addWidget(winbar)
        main_box.addWidget(self.tabs, 1)
        shell_layout.addWidget(main_column, 1)
        self.setCentralWidget(shell)
        self.tabs.currentChanged.connect(self._sync_nav)

    def _sync_nav(self, index):
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)

    def toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        self.settings['sidebar_collapsed'] = self.sidebar_collapsed
        try:
            self.persist_settings()
        except OSError:
            self.statusBar().showMessage('侧边栏状态暂时无法保存，本次运行仍然有效。', 6000)
        # 宽度与文案一起切换，冻结到下一轮事件循环，避免中间态露出。
        with frozen_updates(self):
            self.apply_layout(self.width(), force=True)

    def apply_layout(self, width, force=False):
        expanded = not self.sidebar_collapsed
        if not force and getattr(self, '_layout_expanded', None) == expanded:
            return
        self._layout_expanded = expanded
        self.sidebar_toggle.setToolTip('收起侧边栏' if expanded else '展开侧边栏')
        if expanded:
            self.sidebar.setFixedWidth(T.RAIL_W)
            self.side_layout.setContentsMargins(T.SIDEBAR_PAD, 16, T.SIDEBAR_PAD, 12)
            self.brand_full.show()
            self.brand_compact.hide()
            self.version_label.show()
        else:
            self.sidebar.setFixedWidth(T.RAIL_W_COLLAPSED)
            self.side_layout.setContentsMargins(8, 16, 8, 12)
            self.brand_full.hide()
            self.brand_compact.show()
            self.version_label.hide()
        for button in self.nav_buttons:
            button.set_collapsed(not expanded)
        self.pet_tag.set_collapsed(not expanded)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'sidebar'):
            self.apply_layout(event.size().width())
        if hasattr(self, 'home_top'):
            self.apply_home_layout(event.size().width())
        if hasattr(self, 'task_segments'):
            self.apply_tasks_layout(event.size().width())
        if hasattr(self, 'chat_bar'):
            self.apply_chat_layout(event.size().width())
        if hasattr(self, 'settings_canvas_layout'):
            self.apply_settings_layout(event.size().width())

    def toggle_theme(self):
        self.set_theme('dark' if self.theme == 'light' else 'light')

    def set_theme(self, theme, persist=True, notify=True):
        theme = 'dark' if theme == 'dark' else 'light'
        self.theme = theme
        self.settings['theme'] = theme
        if persist:
            try:
                self.persist_settings()
            except OSError:
                self.statusBar().showMessage('主题设置暂时无法保存，本次运行仍然有效。', 6000)
        # 整套令牌重建会让所有子控件重新 polish；冻结绘制到下一轮事件循环，合并为一帧。
        with frozen_updates(self):
            apply_theme(QApplication.instance(), self.theme)
            self.theme_button.set_icon_name('sun' if self.theme == 'dark' else 'moon')
            self.win_mark.setPixmap(icons.pixmap('paw', tokens().brand, 14))
            self.logo.setPixmap(application_icon().pixmap(30, 30))
            self.compact_logo.setPixmap(application_icon().pixmap(30, 30))
            for button in self.nav_buttons:
                button.refresh_theme()
            self.sidebar_toggle.refresh_theme()
            self.pet_tag.refresh_theme()
            self.live_badge.refresh_theme()
            if hasattr(self, 'settings_theme_segment'):
                self.settings_theme_segment.set_current(self.theme)
            if hasattr(self, 'home_hero'):
                self.refresh_home_theme()
            if hasattr(self, 'task_segments'):
                self.refresh_tasks_theme()
            if hasattr(self, 'chat_bar'):
                self.refresh_chat_theme()
            if hasattr(self, 'refresh_settings_theme'):
                self.refresh_settings_theme()
        if notify:
            self.statusBar().showMessage(
                '已切换到夜幕主题' if self.theme == 'dark' else '已切换到纸白主题', 4000)

    def refresh_pet_tag(self):
        if not hasattr(self, 'pet_tag'):
            return
        now = datetime.now().astimezone()
        pending = [dict(row) for row in self.store.pending()]
        today = [row for row in pending
                 if parse_due(row['due_at']).astimezone().date() == now.date()]
        upcoming = sorted((row for row in pending if parse_due(row['due_at']).astimezone() > now),
                          key=lambda row: parse_due(row['due_at']))
        self.pet_tag.set_stats(len(today), upcoming[0]['due_at'] if upcoming else None, len(pending))
        if self.nav_todo is not None:
            self.nav_todo.set_count(len(pending))
        paused = bool(self.settings.get('pet_paused'))
        if hasattr(self, 'pet'):
            paused = self.pet.paused
            self.pet_tag.set_mode('3D · 哈士奇' if self.pet.mode == '3d' else '2D · 内置')
        self.pet_tag.set_paused(paused)
        if hasattr(self, 'live_badge'):
            self.live_badge.set_text('小满 正在歇会儿' if paused else '小满 正在桌面值守')
            self.live_badge.set_tone('muted' if paused else 'calm')

    def open_chat_input(self):
        self.tabs.setCurrentIndex(1)
        self.input.setFocus(Qt.OtherFocusReason)

    def toggle_pet_pause(self):
        if not hasattr(self, 'pet'):
            return
        self.pet.toggle_animation()
        self.refresh_pet_tag()

    def build_chat(self):
        self.chat_page = QWidget()
        self.chat_page.setObjectName('chatPage')
        self.chat_page.setAttribute(Qt.WA_StyledBackground, True)
        shell = QHBoxLayout(self.chat_page)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.chat_col = QWidget()
        self.chat_col.setObjectName('chatCol')
        self.chat_col.setAttribute(Qt.WA_StyledBackground, True)
        column = QVBoxLayout(self.chat_col)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self.chat_bar = QWidget()
        self.chat_bar.setObjectName('chatBar')
        self.chat_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.chat_bar_layout = QHBoxLayout(self.chat_bar)
        self.chat_bar_layout.setContentsMargins(32, 10, 32, 10)
        self.chat_bar_layout.setSpacing(8)
        self.chat_eyebrow = QLabel('当前对话')
        self.chat_bar_layout.addWidget(self.chat_eyebrow)
        self.session_combo = QComboBox()
        self.session_combo.setMinimumContentsLength(12)
        self.session_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.session_combo.setMinimumWidth(180)
        self.session_combo.setMaximumWidth(320)
        self.chat_bar_layout.addWidget(self.session_combo)
        self.rename_button = IconButton('edit', '重命名对话')
        self.rename_button.clicked.connect(self.rename_session)
        self.chat_bar_layout.addWidget(self.rename_button)
        self.chat_rail_toggle = IconButton('side', '显示 / 收起右栏')
        self.chat_rail_toggle.clicked.connect(self.toggle_chat_rail)
        self.chat_bar_layout.addWidget(self.chat_rail_toggle)
        self.chat_bar_layout.addStretch(1)
        self.plan_button = TransparentPushButton(FluentIcon.CALENDAR, '今日规划', self.chat_bar)
        self.plan_button.setMinimumHeight(30)
        self.plan_button.setToolTip('预览逾期和今天到期待办；确认后生成规划，保留未发送输入')
        self.plan_button.clicked.connect(self.plan_today)
        self.chat_bar_layout.addWidget(self.plan_button)
        self.new_chat_button = PrimaryPushButton(FluentIcon.ADD, '新对话', self.chat_bar)
        self.new_chat_button.setMinimumHeight(30)
        self.new_chat_button.clicked.connect(self.new_session)
        self.chat_bar_layout.addWidget(self.new_chat_button)
        column.addWidget(self.chat_bar)
        self.refresh_sessions()
        self.session_combo.currentIndexChanged.connect(self.switch_session)

        self.history = MessageHistory()
        column.addWidget(self.history, 1)

        self.draft_holder = QWidget()
        self.draft_holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        draft_row = QHBoxLayout(self.draft_holder)
        draft_row.setContentsMargins(32, 0, 32, 8)
        draft_row.setSpacing(0)
        self.draft_area = QScrollArea()
        self.draft_area.setWidgetResizable(True)
        self.draft_area.setFrameShape(QScrollArea.NoFrame)
        self.draft_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.draft_area.setMaximumHeight(300)
        self.draft_widget = QWidget()
        self.drafts = QVBoxLayout(self.draft_widget)
        self.drafts.setContentsMargins(0, 0, 0, 0)
        self.drafts.setSpacing(8)
        self.draft_area.setWidget(self.draft_widget)
        draft_row.addWidget(self.draft_area)
        self.draft_holder.hide()
        column.addWidget(self.draft_holder)

        self.composer_holder = QWidget()
        composer_row = QHBoxLayout(self.composer_holder)
        composer_row.setContentsMargins(32, 8, 32, 20)
        composer_row.setSpacing(0)
        self.composer = ComposerCard()
        composer_row.addWidget(self.composer)

        inside = QVBoxLayout(self.composer)
        inside.setContentsMargins(14, 10, 14, 10)
        inside.setSpacing(6)
        self.input = QTextEdit()
        self.input.setObjectName('composer')
        self.input.setPlaceholderText('说出事项和时间，小满替你记成待办')
        self.input.setMinimumHeight(52)
        self.input.setMaximumHeight(64)
        self.input.installEventFilter(self.composer)
        self.input.viewport().installEventFilter(self.composer)
        self.input.textChanged.connect(self.save_input)
        inside.addWidget(self.input)
        inside.addWidget(Line())
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.model_chip = ModelChip()
        bar.addWidget(self.model_chip)
        self.chat_status = QLabel('')
        self.chat_status.setWordWrap(False)
        bar.addWidget(self.chat_status, 1)
        self.chat_hint = QLabel('Ctrl+Enter 发送')
        bar.addWidget(self.chat_hint)
        self.regenerate_button = IconButton(
            'sync', '在新对话中重新回答最后一个已回复问题，保留原对话与任务；需要配置模型', self.composer)
        self.regenerate_button.setFixedSize(30, 30)
        self.regenerate_button.clicked.connect(self.regenerate_reply)
        bar.addWidget(self.regenerate_button)
        self.stop_button = QPushButton('停止')
        self.stop_button.setFixedHeight(28)
        self.stop_button.clicked.connect(self.stop_request)
        self.stop_button.hide()
        bar.addWidget(self.stop_button)
        self.retry_button = QPushButton('重试')
        self.retry_button.setFixedHeight(28)
        self.retry_button.clicked.connect(self.retry_request)
        self.retry_button.hide()
        bar.addWidget(self.retry_button)
        self.send = PrimaryPushButton(FluentIcon.SEND, '发送', self.composer)
        self.send.setMinimumHeight(30)
        self.send.clicked.connect(self.send_message)
        bar.addWidget(self.send)
        inside.addLayout(bar)
        column.addWidget(self.composer_holder)

        self.shortcut = QShortcut(QKeySequence('Ctrl+Return'), self.input)
        self.shortcut.activated.connect(self.send_message)

        self.chat_rail = ChatRail(self.store)
        self.chat_rail.open_task.connect(self.open_chat_task)
        self.chat_rail.mute_task.connect(self.chat_mute_task)
        self.chat_rail.plan_requested.connect(self.plan_today)
        self.chat_rail.open_tasks.connect(lambda: self.tabs.setCurrentIndex(2))
        self.chat_rail.open_settings.connect(lambda: self.tabs.setCurrentIndex(3))
        shell.addWidget(self.chat_col, 1)
        shell.addWidget(self.chat_rail)

        self._chat_rail_open = False
        self.refresh_chat_theme()
        self.apply_chat_layout(self.width(), force=True)
        self.refresh_chat_rail()
        self.tabs.addTab(self.chat_page, '聊天')

    def apply_chat_layout(self, width, force=False):
        if not hasattr(self, 'chat_bar'):
            return
        pad = 32 if width > 1280 else 20
        compact = width <= 1080
        wide = width > 1280
        state = (pad, compact, wide, self._chat_rail_open)
        if not force and state == getattr(self, '_chat_layout_state', None):
            return
        self._chat_layout_state = state
        self.chat_bar_layout.setContentsMargins(pad, 10, pad, 10)
        self.composer_holder.layout().setContentsMargins(pad, 8, pad, 20)
        self.draft_holder.layout().setContentsMargins(pad, 0, pad, 8)
        if hasattr(self, 'history'):
            self.history.set_gutter(pad)
        self.chat_eyebrow.setVisible(not compact)
        self.plan_button.setVisible(not compact)
        self.chat_hint.setVisible(not compact)
        self.session_combo.setMaximumWidth(320 if wide else 220)
        self.chat_rail_toggle.setVisible(not wide)
        self.chat_rail.setVisible(wide or self._chat_rail_open)

    def toggle_chat_rail(self):
        if self.width() > 1280:
            return
        self._chat_rail_open = not self._chat_rail_open
        self.apply_chat_layout(self.width(), force=True)

    def refresh_chat_theme(self):
        if not hasattr(self, 'chat_bar'):
            return
        t = tokens()
        self.chat_page.setStyleSheet(f'QWidget#chatPage{{background:{t.bg};}}')
        self.chat_col.setStyleSheet(f'QWidget#chatCol{{background:{t.bg};}}')
        self.chat_bar.setStyleSheet(f'QWidget#chatBar{{background:{t.surface};'
                                    f'border-bottom:1px solid {t.border};}}')
        self.chat_eyebrow.setStyleSheet(f'background:transparent;color:{t.ink_3};'
                                        f'font-family:"{T.FONT_MONO}","Consolas",monospace;font-size:10px;')
        self.chat_hint.setStyleSheet(f'background:transparent;color:{t.ink_4};'
                                     f'font-family:"{T.FONT_UI}";font-size:10px;')
        self.chat_status.setStyleSheet(f'background:transparent;color:{t.ink_3};'
                                       f'font-family:"{T.FONT_UI}";font-size:10px;')
        self.input.setStyleSheet(
            f'QTextEdit#composer{{background:transparent;border:0;border-radius:0;padding:2px;'
            f'color:{t.ink};font-family:"{T.FONT_UI}";font-size:13px;}}')
        for control in (self.stop_button, self.retry_button):
            control.setStyleSheet(
                f'QPushButton{{background:transparent;color:{t.ink_2};border:1px solid {t.border};'
                f'border-radius:8px;padding:0 10px;font-family:"{T.FONT_UI}";font-size:11px;}}'
                f'QPushButton:hover{{border-color:{t.brand};color:{t.ink};}}'
                f'QPushButton:disabled{{color:{t.ink_4};}}')
        self.draft_holder.setStyleSheet('background:transparent;')
        self.draft_area.setStyleSheet('QScrollArea{background:transparent;border:0;}')
        self.draft_widget.setStyleSheet('background:transparent;')
        self.composer.refresh_theme()
        self.regenerate_button.refresh_theme()
        self.history.refresh_theme()
        for index in range(self.drafts.count()):
            card = self.drafts.itemAt(index).widget()
            if hasattr(card, 'refresh_theme'):
                card.refresh_theme()
        self.update_model_chip()
        if hasattr(self, 'chat_rail'):
            self.chat_rail.refresh_theme()

    def update_model_chip(self):
        if not hasattr(self, 'model_chip'):
            return
        configured = bool(self.settings.get('model') and self.settings.get('base_url'))
        self.model_chip.set_text(self.settings.get('model') if configured else '本地规则', configured)

    def refresh_chat_rail(self):
        if not hasattr(self, 'chat_rail'):
            return
        self.chat_rail.set_session(self.store.session(self.active_session)['title'],
                                   self.store.message_count(self.active_session),
                                   self.settings.get('model') if (
                                       self.settings.get('model') and self.settings.get('base_url')
                                   ) else '本地规则')

    def open_chat_task(self, task_id):
        self.show_main()
        self.tabs.setCurrentIndex(2)
        self.focus_task(task_id)

    def chat_mute_task(self, task_id):
        task = next((dict(row) for row in self.store.pending() if row['id'] == task_id), None)
        if task is None:
            self.statusBar().showMessage('这条待办已完成或删除，无需静音。', 5000)
            return
        self.store.mute_today(task_id)
        message = f'已设置：{task["title"]} 今天不再提醒。'
        self.store.add_message('assistant', message, self.active_session)
        self.append_message('system', message)
        self.refresh_tasks()
        self.refresh_chat_rail()
        self.statusBar().showMessage(message, 6000)

    def retry_local(self):
        messages = self.retry_messages or self.store.messages(20, self.active_session)
        text = messages[-1]['content'] if messages else ''
        self.retry_messages = None
        self.retry_button.hide()
        self.request_model = ''
        self.on_reply(local_reply(text))
        self.update_request_status()

    def refresh_sessions(self):
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        for session in self.store.sessions():
            self.session_combo.addItem(session['title'], session['id'])
        self.session_combo.setCurrentIndex(self.session_combo.findData(self.active_session))
        self.session_combo.blockSignals(False)
        self.refresh_chat_rail()

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
        self.error_row = None
        for message in self.store.messages(session_id=self.active_session):
            self.append_message(message['role'], message['content'])
        while self.drafts.count():
            item = self.drafts.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.draft_holder.hide()
        for draft in self.store.drafts(self.active_session):
            self.add_draft(dict(draft))
        self.input.blockSignals(True)
        self.input.setPlainText(self.store.session(self.active_session)['input_text'])
        self.input.blockSignals(False)
        self.retry_messages = self.retry_by_session.get(self.active_session)
        self.retry_button.setVisible(bool(self.retry_messages))
        self.update_request_status()
        self.render_stream()
        self.refresh_chat_rail()

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
        self.update_model_chip()
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
        dialog = PlanDialog(self, prompt, uses_model)
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
        self.error_row = None
        configured = bool(self.settings.get('model') and self.settings.get('base_url'))
        self.request_model = self.settings.get('model') if configured else ''
        self.request_started = time.monotonic()
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
        self.request_model = ''
        self.request_started = None
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
                self.store.add(op['title'], op['due_at'], repeat=repeat, dingtalk=dingtalk_flag, source='chat')
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
        self.register_deleted([row['id']])
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

    def _reply_meta(self):
        if self.worker is None or not self.request_model:
            return '小满 · 本地规则'
        elapsed = time.monotonic() - self.request_started if self.request_started else 0
        return f'小满 · {self.request_model} · 用时 {elapsed:.1f} 秒'

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
            row = self.error_row
            if row is not None:
                row.clear_error()
                self.history.update_row(row, reply, markdown=True)
                row.set_meta(self._reply_meta())
                self.error_row = None
            elif self.stream_row is not None:
                row = self.stream_row
                self.history.update_row(row, reply, markdown=True)
                row.set_meta(self._reply_meta())
                self.stream_row = None
            else:
                row = self.history.append_message('assistant', reply)
                row.set_meta(self._reply_meta())
        if errors:
            note = '部分建议未采用：' + '；'.join(errors)
            self.store.add_message('assistant', note, session_id)
            if visible:
                self.append_message('system', note)
        self.refresh_chat_rail()
        self.pet.say(plain_text(reply) or reply)

    def on_error(self, message):
        if self.worker is not None and self.worker.cancel_event.is_set():
            return
        session_id = self.request_session
        self.retry_by_session[session_id] = list(self.worker.messages)
        if session_id == self.active_session:
            self.retry_messages = self.retry_by_session[session_id]
            self.retry_button.show()
            row = self.stream_row or self.history.append_message('assistant', '发送失败')
            self.history.show_error(row, '发送失败', message,
                                    on_retry=self.retry_request, on_local=self.retry_local)
            self.stream_row = None
            self.error_row = row
        else:
            self.statusBar().showMessage('其他对话请求失败，切回该对话可重试。', 8000)

    def add_draft(self, task):
        session_id = self.active_session
        card = DraftCard(self.store, task, session_id, self.draft_widget)

        def remove_card():
            self.drafts.removeWidget(card)
            card.hide()
            card.deleteLater()
            self.draft_holder.setVisible(self.drafts.count() > 0)

        def saved(message):
            self.store.add_message('assistant', message, session_id)
            if session_id == self.active_session:
                self.append_message('system', message)
            self.refresh_tasks()

        card.saved.connect(saved)
        card.removed.connect(remove_card)
        self.drafts.addWidget(card)
        self.draft_holder.show()

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
        for task in self.store.due(current):
            task = dict(task)
            task_id = task['id']
            if task_id in self.reminders:
                continue
            if quiet:
                if not self.store.quiet_logged(task_id, local_day_bounds(now)[0]):
                    self.store.record_quiet(task_id, current, quiet)
                continue
            final = task.get('remind_count', 0) + 1 >= REMIND_LIMIT
            dialog = ReminderDialog(
                self, task,
                on_complete=lambda checked=False, tid=task_id: self.resolve(tid, False),
                on_snooze=lambda checked=False, tid=task_id: self.resolve(tid, True),
                on_open=lambda checked=False, tid=task_id: self.open_reminder_task(tid),
                final=final)

            def finished(_=0, tid=task_id, d=dialog, title=task['title']):
                acted = d.resolved
                self.forget_reminder(tid, d)
                if not acted and self.settings.get('auto_postpone'):
                    self.store.snooze(tid, datetime.now(timezone.utc), minutes=10, auto=True)
                    self.statusBar().showMessage(f'“{title}”没有回应，已自动顺延 10 分钟。', 8000)
                    self.refresh_tasks()

            dialog.finished.connect(finished)
            self.reminders[task_id] = dialog
            anchor = self.pet.frameGeometry() if self.pet.isVisible() else None
            dialog.present(anchor, len(self.reminders) - 1)
            self.store.mark_shown(task_id, current)
            if final:
                self.statusBar().showMessage(f'“{task["title"]}”已提醒 {REMIND_LIMIT} 次，标记为延期，不再提醒。', 10000)
            self.pet.say('到时间了：' + task['title'])
            self.pet.play_action('reminder')
            notify(self.tray, '待办提醒', task['title'])
            if self.settings.get('sound_enabled', True):
                QApplication.beep()
            if task.get('dingtalk'):
                self.push_dingtalk(task)
        self.check_early(now, current, quiet)

    def check_early(self, now, current, quiet):
        if quiet or not self.settings.get('early_nudge', True):
            return
        for task in self.store.early_due(current):
            task = dict(task)
            minutes = max(1, int((parse_due(task['due_at']) - current).total_seconds() // 60))
            if self.store.mark_early_shown(task['id'], current):
                self.pet.say(f'还有 {minutes} 分钟：{task["title"]}')
                self.statusBar().showMessage(f'提前提醒：{task["title"]} 还有 {minutes} 分钟。', 6000)

    # 0.30 旧实现保留备查（无免打扰、提前提点与自动顺延）：
    # def check_due(self):
    #     for task in self.store.due():
    #         task = dict(task)
    #         task_id = task['id']
    #         if task_id in self.reminders:
    #             continue
    #         final = task.get('remind_count', 0) + 1 >= REMIND_LIMIT
    #         dialog = ReminderDialog(
    #             self, task,
    #             on_complete=lambda checked=False, tid=task_id: self.resolve(tid, False),
    #             on_snooze=lambda checked=False, tid=task_id: self.resolve(tid, True),
    #             on_open=lambda checked=False, tid=task_id: self.open_reminder_task(tid),
    #             final=final)
    #         dialog.finished.connect(lambda _=0, tid=task_id, d=dialog: self.forget_reminder(tid, d))
    #         self.reminders[task_id] = dialog
    #         anchor = self.pet.frameGeometry() if self.pet.isVisible() else None
    #         dialog.present(anchor, len(self.reminders) - 1)
    #         self.store.mark_shown(task_id)
    #         if final:
    #             self.statusBar().showMessage(f'“{task["title"]}”已提醒 {REMIND_LIMIT} 次，标记为延期，不再提醒。', 10000)
    #         self.pet.say('到时间了：' + task['title'])
    #         self.pet.play_action('reminder')
    #         notify(self.tray, '待办提醒', task['title'])
    #         if task.get('dingtalk'):
    #             self.push_dingtalk(task)

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
