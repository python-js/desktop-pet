"""Settings page and local configuration persistence."""
import json
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from PyQt5.QtCore import QPointF, QRectF, Qt, QTime, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QImage, QImageReader, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (QAbstractButton, QAbstractSpinBox, QDialog, QFileDialog, QFrame,
                             QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                             QScrollArea, QSizePolicy, QTimeEdit, QVBoxLayout, QWidget)
from ..assistant import test_connection
from ..core import (DEFAULT_DND_END, DEFAULT_DND_START, parse_clock, validate_endpoint)
from ..dingtalk import DingTalkError, send as dingtalk_send, validate_webhook
from ..secure_storage import SecretStore
from ..startup import StartupManager
from .. import websearch
from . import icons, tokens as T
from .common import button, local_time
from .components import ElidedLabel, Panel, Segmented, StatePill
from .cutout import CutoutDialog
from .home import Line
from ..motion import generate_motion, save_motion, cleanup_generated
from .pet import default_pet_image
from .controls import LineEdit as QLineEdit
from .theme import mono_font, tokens

_SETTINGS_DEFAULTS = {
    'theme': 'light',
    'density': 'comfortable',
    'early_nudge': True,
    'sound_enabled': True,
    'auto_postpone': False,
    'dnd_enabled': True,
    'dnd_start': DEFAULT_DND_START,
    'dnd_end': DEFAULT_DND_END,
}

_WEIGHTS = {QFont.DemiBold: 600, QFont.Bold: 700}


def _pref_text(size, token_name, weight=QFont.Normal, wrap=False, mono=False):
    label = QLabel()
    family = T.FONT_MONO if mono else T.FONT_UI
    font = QFont(family)
    font.setPixelSize(size)
    font.setWeight(weight)
    label.setFont(font)
    label.setWordWrap(wrap)
    style = f'font-family:"{family}",' + ('"Consolas",monospace;' if mono else 'sans-serif;')
    style += f'font-size:{size}px;'
    if weight in _WEIGHTS:
        style += f'font-weight:{_WEIGHTS[weight]};'
    label._token_name = token_name
    label._style_base = style
    label.setStyleSheet(f'{style}color:{getattr(tokens(), token_name)};background:transparent;')
    return label


def _pref_color(label, token_name):
    label._token_name = token_name
    label.setStyleSheet(f'{getattr(label, "_style_base", "")}color:{getattr(tokens(), token_name)};'
                        'background:transparent;')


def _pref_actions():
    holder = QWidget()
    holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 4, 0, 0)
    layout.setSpacing(8)
    holder._pref_action_row = True
    return holder, layout


class PrefIcon(QWidget):
    def __init__(self, icon_name, wash='brand_wash', ink='brand', parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.wash = wash
        self.ink = ink
        self.setFixedSize(30, 30)

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(getattr(t, self.wash)))
        painter.drawRoundedRect(QRectF(self.rect()), 9, 9)
        painter.drawPixmap(QPointF(7, 7), icons.pixmap(self.icon_name, getattr(t, self.ink), 16))


class PrefCheck(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(18, 18)
        self._key_focus = False

    def set_key_focus(self, focused):
        self._key_focus = bool(focused)
        self.update()

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        enabled = self.isEnabled()
        selected = self.isChecked()
        border = t.brand if selected else (t.border_strong if enabled else t.border)
        if self._key_focus:
            border = t.brand
        painter.setPen(QPen(QColor(border), 1.4))
        painter.setBrush(QColor(t.brand if selected else t.surface_2 if not enabled else t.surface))
        painter.drawRoundedRect(rect, 5, 5)
        if selected:
            painter.setPen(QPen(QColor(t.brand_on if enabled else t.ink_4), 1.8,
                                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            x, y = rect.center().x(), rect.center().y()
            painter.drawLine(QPointF(x - 4, y), QPointF(x - 1, y + 3))
            painter.drawLine(QPointF(x - 1, y + 3), QPointF(x + 5, y - 3))


class PrefSwitch(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def refresh_theme(self):
        self.update()

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        enabled = self.isEnabled()
        painter.setPen(QPen(QColor(t.brand if on else (t.border_strong if enabled else t.border)), 1))
        painter.setBrush(QColor(t.brand if on else t.surface_3))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        knob = QRectF(0, 0, 16, 16)
        knob.moveCenter(QPointF(rect.right() - 11 if on else rect.left() + 11, rect.center().y()))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(t.brand_on if on else t.surface))
        painter.drawEllipse(knob)
        if self.hasFocus():
            painter.setPen(QPen(QColor(t.brand), 1.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)


class CheckLine(QWidget):
    """整行可点的说明型复选：程序 setChecked 不发信号，只有用户操作才触发。"""

    toggled = pyqtSignal(bool)

    def __init__(self, title, subtitle='', checked=False, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(title)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.box = PrefCheck(self._checked)
        self.box.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.box.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.box, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        self.title_label = _pref_text(12, 'ink', QFont.DemiBold)
        self.title_label.setText(title)
        self.subtitle_label = _pref_text(10, 'ink_3', wrap=True)
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))
        text.addWidget(self.title_label)
        text.addWidget(self.subtitle_label)
        layout.addLayout(text, 1)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)
        self.box.setChecked(self._checked)
        self.setAccessibleDescription('已选中' if self._checked else '未选中')

    def toggle(self):
        self.setChecked(not self._checked)
        self.toggled.emit(self._checked)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()) and self.isEnabled():
            self.toggle()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.isEnabled():
            self.toggle()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        self.box.set_key_focus(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.box.set_key_focus(False)
        super().focusOutEvent(event)


class PrefRow(QWidget):
    """prow：宽屏左标题 + 右控件，窄屏折成单列。"""

    def __init__(self, title, description='', parent=None):
        super().__init__(parent)
        self._stacked = None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 14, 0, 14)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(8)
        self.key_box = QWidget()
        self.key_layout = QVBoxLayout(self.key_box)
        self.key_layout.setContentsMargins(0, 6, 0, 0)
        self.key_layout.setSpacing(2)
        self.key_layout.addWidget(_pref_text(13, 'ink', QFont.DemiBold))
        self.key_layout.itemAt(0).widget().setText(title)
        self.description_label = None
        if description:
            self.description_label = _pref_text(10, 'ink_3', wrap=True)
            self.description_label.setText(description)
            self.key_layout.addWidget(self.description_label)
        self.key_layout.addStretch(1)
        self.value_box = QWidget()
        self.value_box.setMinimumWidth(0)
        self.value_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.value_layout = QVBoxLayout(self.value_box)
        self.value_layout.setContentsMargins(0, 0, 0, 0)
        self.value_layout.setSpacing(8)
        self._place(False)

    def _place(self, stacked):
        if self._stacked == stacked:
            return
        self._stacked = stacked
        self.grid.addWidget(self.key_box, 0, 0)
        if stacked:
            self.grid.addWidget(self.value_box, 1, 0)
        else:
            self.grid.addWidget(self.value_box, 0, 1)
        self.grid.setColumnMinimumWidth(0, 0 if stacked else 158)
        self.grid.setColumnStretch(0, 1 if stacked else 0)
        self.grid.setColumnStretch(1, 0 if stacked else 1)
        self.key_layout.setContentsMargins(0, 0 if stacked else 6, 0, 0)

    def set_stacked(self, stacked):
        self._place(bool(stacked))

    def add(self, widget, stretch=0):
        self.value_layout.addWidget(widget, stretch)
        if getattr(widget, '_pref_action_row', False):
            widget.layout().addStretch(1)
        return widget


class PrefCard(Panel):
    def __init__(self, icon_name, title, conclusion, wash='brand_wash', ink='brand', parent=None):
        super().__init__(parent)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(20, 20, 20, 20)
        self.box.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        self.icon = PrefIcon(icon_name, wash, ink)
        header.addWidget(self.icon, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        self.title_label = _pref_text(15, 'ink', QFont.DemiBold)
        self.title_label.setText(title)
        self.conclusion = _pref_text(11, 'ink_3', wrap=True)
        self.conclusion.setText(conclusion)
        text.addWidget(self.title_label)
        text.addWidget(self.conclusion)
        header.addLayout(text, 1)
        self.box.addLayout(header)
        self.box.addSpacing(6)
        self.rows = []

    def add_row(self, row):
        if self.rows:
            self.box.addWidget(Line())
        self.rows.append(row)
        self.box.addWidget(row)
        return row


class PetImageTile(QFrame):
    clicked = pyqtSignal()

    def __init__(self, pixmap, selected=False, parent=None):
        super().__init__(parent)
        self.setObjectName('petTile')
        self._selected = bool(selected)
        self._hover = False
        self.setFixedSize(96, 96)
        self.setCursor(Qt.PointingHandCursor)
        label = QLabel(self)
        label.setGeometry(8, 8, 80, 80)
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        label.setAttribute(Qt.WA_TransparentForMouseEvents)

    def refresh_theme(self):
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._selected:
            fill, border, width = QColor(t.brand_wash), QColor(t.brand), 2
        elif self._hover:
            fill, border, width = QColor(t.surface_2), QColor(t.border_strong), 1
        else:
            fill, border, width = QColor(t.surface), QColor(t.border), 1
        painter.setPen(QPen(border, width))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, T.RADIUS_CARD, T.RADIUS_CARD)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()


class SettingsPageMixin:
    def load_configuration(self, secret_store=None, startup_manager=None):
        self.secret_store = secret_store or SecretStore(self.root)
        self.startup_manager = startup_manager or StartupManager()
        self.settings_warning = ''
        self.secret_endpoint = None
        loaded = None
        try:
            loaded = json.loads((self.root / 'settings.json').read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                self.settings = {k: loaded[k] for k in ('base_url', 'model', 'pet_image', 'pet_image_original',
                                                        'active_session', 'density', 'dnd_start', 'dnd_end')
                                 if isinstance(loaded.get(k), str)}
                for key in ('stream', 'remember_key', 'pet_paused', 'pet_walking', 'sidebar_collapsed'):
                    if isinstance(loaded.get(key), bool):
                        self.settings[key] = loaded[key]
                if loaded.get('pet_mode') in ('2d', '3d'):
                    self.settings['pet_mode'] = loaded['pet_mode']
                if loaded.get('theme') in ('light', 'dark'):
                    self.settings['theme'] = loaded['theme']
                position = loaded.get('pet_position')
                if isinstance(position, list) and len(position) == 2 and all(type(v) is int and abs(v) <= 100000 for v in position):
                    self.settings['pet_position'] = position
        except (OSError, ValueError):
            pass
        for key, default in (('early_nudge', True), ('sound_enabled', True),
                             ('auto_postpone', False), ('dnd_enabled', True),
                             ('web_search_enabled', True)):
            if not isinstance(self.settings.get(key), bool):
                self.settings[key] = default
        for key, default in (('dnd_start', DEFAULT_DND_START), ('dnd_end', DEFAULT_DND_END)):
            try:
                self.settings[key] = parse_clock(self.settings.get(key) or default)
            except ValueError:
                self.settings[key] = default
        if self.settings.get('density') not in ('comfortable', 'compact'):
            self.settings['density'] = 'comfortable'
        self.migrate_pet_images(loaded)
        # 0.20 起不再使用自动生成的动作：清理旧配置与 auto-* 目录，手动导入目录保留。
        stale = [loaded.get(key) for key in ('pet_animations', 'pet_animation_backup')
                 if isinstance(loaded, dict) and isinstance(loaded.get(key), dict)]
        if stale:
            for config in stale:
                self.cleanup_auto_animations(config)
            try:
                self.persist_settings()
            except OSError:
                self.settings_warning += ' 旧的自动动作配置未能从设置文件移除。'
        if self.settings.get('remember_key'):
            try:
                key = self.secret_store.load(self.settings.get('base_url', ''))
                if key:
                    self.settings['api_key'] = key
                    self.secret_endpoint = self.settings.get('base_url')
                else:
                    self.settings_warning = '没有找到此服务的安全密钥，请重新输入。'
            except (OSError, ValueError):
                self.settings_warning = '安全密钥未能恢复，请重新输入；原文件未自动删除。'
        self.settings['tavily_key'] = ''
        try:
            self.settings['tavily_key'] = self.secret_store.load_tavily()
        except (OSError, ValueError):
            self.settings_warning += ' Tavily 密钥未能恢复，请重新输入。'
        self.dingtalk_webhook = ''
        self.dingtalk_secret = ''
        try:
            self.dingtalk_webhook, self.dingtalk_secret = self.secret_store.load_dingtalk()
        except (OSError, ValueError):
            self.settings_warning += ' 钉钉机器人配置未能恢复，请重新填写。'

    def migrate_pet_images(self, loaded):
        """Build the image history from pet_images or the old single-image keys."""
        records = []
        raw = loaded.get('pet_images') if isinstance(loaded, dict) else None
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                image = item.get('image')
                original = item.get('original')
                if not isinstance(image, str) or not Path(image).is_file():
                    continue
                record = {'image': image}
                if isinstance(original, str) and Path(original).is_file():
                    record['original'] = original
                records.append(record)
        current = self.settings.get('pet_image')
        if isinstance(current, str) and not Path(current).is_file():
            current = ''
            self.settings.pop('pet_image', None)
        if current and not any(item['image'] == current for item in records):
            record = {'image': current}
            original = self.settings.get('pet_image_original')
            if isinstance(original, str) and Path(original).is_file():
                record['original'] = original
            records.insert(0, record)
        if records:
            self.settings['pet_images'] = records
        self.settings.pop('pet_image_original', None)

    def build_settings(self):
        self._pref_rows = []
        self._danger_buttons = []
        self._pet_columns = 5
        self._settings_layout_state = None
        self._startup_checked = False
        if self.startup_manager.supported:
            try:
                self._startup_checked = self.startup_manager.enabled()
            except ValueError:
                self.settings_warning += ' 无法读取开机启动状态，可手动应用设置。'

        page = QWidget()
        page.setObjectName('settingsPage')
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setFrameShape(QFrame.NoFrame)
        self.settings_canvas = QWidget()
        self.settings_canvas_layout = QVBoxLayout(self.settings_canvas)
        self.settings_canvas_layout.setContentsMargins(20, 24, 20, 32)
        self.settings_canvas_layout.setSpacing(0)
        self.settings_content = QWidget()
        self.settings_content.setMinimumWidth(0)
        self.settings_content.setMaximumWidth(760)
        self.settings_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)
        center.addStretch(1)
        center.addWidget(self.settings_content, 100)
        center.addStretch(1)
        self.settings_canvas_layout.addLayout(center)
        self.settings_canvas_layout.addStretch(1)
        self.settings_scroll.setWidget(self.settings_canvas)
        outer.addWidget(self.settings_scroll)
        self.settings_page = page
        content = QVBoxLayout(self.settings_content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(18)
        self.settings_content_layout = content

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 2)
        head.setSpacing(10)
        head.addWidget(_pref_text(19, 'ink', QFont.Bold))
        head.itemAt(0).widget().setText('偏好设置')
        head.addStretch(1)
        self.settings_live = StatePill('改动即时生效，无需重启', 'done', 'check')
        head.addWidget(self.settings_live, 0, Qt.AlignVCenter)
        self.restore_button = button('恢复默认', self.restore_default_settings, head)
        self.restore_button.setToolTip('只恢复主题、密度与提醒开关，不影响密钥、钉钉和宠物图片。')
        content.addLayout(head)

        card = PrefCard('chat', '模型与对话',
                        '接支持 Chat Completions 的服务。模型留空时走本地规则，一样能记事。')
        row = PrefRow('服务地址', 'OpenAI 兼容端点')
        self.base_url = QLineEdit(self.settings.get('base_url', ''))
        self.base_url.setPlaceholderText('供应商提供的 API 根地址，通常以 /v1 结尾')
        self.base_url.setMinimumWidth(0)
        self.base_url.textEdited.connect(self.endpoint_edited)
        row.add(self.base_url)
        card.add_row(row)

        row = PrefRow('模型', '决定回答速度与措辞')
        self.model = QLineEdit(self.settings.get('model', ''))
        self.model.setMinimumWidth(0)
        row.add(self.model)
        card.add_row(row)

        row = PrefRow('API Key', '默认只留在本次运行内存里')
        self.key = QLineEdit(self.settings.get('api_key', ''))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText('只用于当前服务地址的密钥')
        self.key.setMinimumWidth(0)
        self.key.textEdited.connect(self.key_edited)
        row.add(self.key)
        self.remember_key = CheckLine('用当前 Windows 账户加密记住',
                                      '写入系统凭据，不进设置文件。',
                                      self.settings.get('remember_key', False))
        self.remember_key.setEnabled(self.secret_store.supported)
        row.add(self.remember_key)
        self.stream_enabled = CheckLine('逐字显示回答',
                                        '服务不支持流式时会自动整段返回。',
                                        self.settings.get('stream', True))
        row.add(self.stream_enabled)
        actions, action_row = _pref_actions()
        self.save_model_button = button('保存', self.save_settings, action_row, primary=True)
        self.test_button = button('测试连接', self.test_model_connection, action_row)
        row.add(actions)
        self.settings_notice = _pref_text(10, 'alert' if self.settings_warning.strip() else 'ink_3',
                                          wrap=True)
        self.settings_notice.setText(self.settings_warning.strip() or
                                     '更改后点“保存”，下一条消息生效。')
        row.add(self.settings_notice)
        self.settings_test_status = _pref_text(10, 'ink_3', wrap=True)
        self.settings_test_status.setText('尚未测试连接。')
        row.add(self.settings_test_status)
        card.add_row(row)
        content.addWidget(card)

        card = PrefCard('search', '联网搜索',
                        '接入 Tavily 查实时资料；只发送当前问题，不发送对话历史和待办。')
        row = PrefRow('Tavily API Key', '在 tavily.com 创建，形如 tvly-…')
        self.tavily_key = QLineEdit(self.settings.get('tavily_key', ''))
        self.tavily_key.setEchoMode(QLineEdit.Password)
        self.tavily_key.setPlaceholderText('仅用于 Tavily 搜索')
        self.tavily_key.setMinimumWidth(0)
        row.add(self.tavily_key)
        self.web_search_enabled = CheckLine('自动联网查资料',
                                            '命中查资料类问题且已配置密钥时先搜索；每次消耗 1 credit。',
                                            self.settings.get('web_search_enabled', True))
        row.add(self.web_search_enabled)
        actions, action_row = _pref_actions()
        self.save_web_button = button('保存', self.save_web_search_settings, action_row, primary=True)
        self.test_web_button = button('测试连接', self.test_websearch, action_row)
        row.add(actions)
        self.websearch_status = _pref_text(10, 'ink_3', wrap=True)
        self.websearch_status.setText('尚未配置 Tavily 密钥；配置后默认自动联网。' if not
                                      self.settings.get('tavily_key') else 'Tavily 密钥已载入。')
        row.add(self.websearch_status)
        card.add_row(row)
        content.addWidget(card)

        card = PrefCard('bell', '提醒与免打扰',
                        '桌面气泡是主通道，钉钉只是备份。',
                        'caution_wash', 'caution')
        row = PrefRow('提醒方式', '到点后弹桌面气泡，不抢焦点。')
        self.early_nudge_check = CheckLine('提前 10 分钟轻轻提点',
                                           '只在小满身上显示，不弹气泡。',
                                           self.settings.get('early_nudge', True))
        self.early_nudge_check.toggled.connect(
            lambda checked: self.change_reminder_setting('early_nudge', checked))
        row.add(self.early_nudge_check)
        self.sound_check = CheckLine('桌面气泡 + 提示音',
                                     '到点播放一声系统提示音。',
                                     self.settings.get('sound_enabled', True))
        self.sound_check.toggled.connect(
            lambda checked: self.change_reminder_setting('sound_enabled', checked))
        row.add(self.sound_check)
        self.auto_postpone_check = CheckLine('错过后自动顺延 10 分钟',
                                             '关掉后，逾期未回应的事项保持逾期。',
                                             self.settings.get('auto_postpone', False))
        self.auto_postpone_check.toggled.connect(
            lambda checked: self.change_reminder_setting('auto_postpone', checked))
        row.add(self.auto_postpone_check)
        card.add_row(row)

        row = PrefRow('免打扰', '这段时间只静默记录，不弹窗也不推送。')
        inline = QWidget()
        inline.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        inline_layout = QHBoxLayout(inline)
        inline_layout.setContentsMargins(0, 0, 0, 0)
        inline_layout.setSpacing(8)
        self.dnd_start_edit = self._time_edit(self.settings.get('dnd_start', DEFAULT_DND_START))
        self.dnd_end_edit = self._time_edit(self.settings.get('dnd_end', DEFAULT_DND_END))
        self._time_edits = [self.dnd_start_edit, self.dnd_end_edit]
        inline_layout.addWidget(self.dnd_start_edit)
        dash = _pref_text(12, 'ink_3')
        dash.setText('—')
        inline_layout.addWidget(dash)
        inline_layout.addWidget(self.dnd_end_edit)
        inline_layout.addStretch(1)
        self.dnd_state = StatePill()
        inline_layout.addWidget(self.dnd_state, 0, Qt.AlignVCenter)
        self.dnd_switch = PrefSwitch(self.settings.get('dnd_enabled', True))
        self.dnd_switch.setAccessibleName('免打扰')
        self.dnd_switch.toggled.connect(self.on_dnd_toggled)
        inline_layout.addWidget(self.dnd_switch, 0, Qt.AlignVCenter)
        self._sync_dnd_state()
        self.dnd_start_edit.timeChanged.connect(self.dnd_time_changed)
        self.dnd_end_edit.timeChanged.connect(self.dnd_time_changed)
        row.add(inline)
        card.add_row(row)

        row = PrefRow('开机与后台',
                      '登录后启动；关机或睡眠期间的提醒，下次启动时补检。')
        self.login_startup = CheckLine('登录 Windows 后启动，主窗口收起到托盘',
                                       '小满直接出现在桌面上。',
                                       self._startup_checked)
        self.login_startup.setEnabled(self.startup_manager.supported)
        row.add(self.login_startup)
        actions, action_row = _pref_actions()
        self.startup_button = button('应用启动设置', self.save_startup, action_row)
        self.startup_button.setEnabled(self.startup_manager.supported)
        row.add(actions)
        card.add_row(row)
        content.addWidget(card)

        card = PrefCard('sun', '外观与密度',
                        '主题与列表密度即时生效，只影响这台电脑。',
                        'info_wash', 'info')
        row = PrefRow('主题', '纸白适合白天，夜幕降低夜间亮度。')
        self.settings_theme_segment = Segmented(
            [{'key': 'light', 'label': '纸白'}, {'key': 'dark', 'label': '夜幕'}],
            self.theme)
        self.settings_theme_segment.changed.connect(self.set_theme)
        row.add(self.settings_theme_segment)
        card.add_row(row)
        row = PrefRow('密度', '宽松更清晰，紧凑一屏看更多。')
        self.settings_density_segment = Segmented(
            [{'key': 'comfortable', 'label': '宽松'}, {'key': 'compact', 'label': '紧凑'}],
            self.settings.get('density', 'comfortable'))
        self.settings_density_segment.changed.connect(self.set_task_density)
        row.add(self.settings_density_segment)
        card.add_row(row)
        content.addWidget(card)

        card = PrefCard('todo', '数据与隐私',
                        '待办和对话都在本机，不上传；导出不含密钥。',
                        'surface_2', 'ink_2')
        row = PrefRow('存放位置', '所有数据都在这个目录；清空前会先自动备份。')
        self.data_path = ElidedLabel(str(self.root))
        self.data_path.setFont(mono_font(10))
        self.data_path.set_color(tokens().ink_3)
        self.data_path.setToolTip(str(self.root))
        row.add(self.data_path)
        actions, action_row = _pref_actions()
        button('打开文件夹', self.open_data_folder, action_row)
        self.export_button = button('导出数据', self.export_settings_data, action_row)
        self.clear_button = QPushButton('清空数据')
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.setMinimumHeight(36)
        self.clear_button.clicked.connect(self.clear_settings_data)
        self._danger_buttons.append(self.clear_button)
        action_row.addWidget(self.clear_button)
        row.add(actions)
        self.data_status = _pref_text(10, 'ink_3', wrap=True)
        self.data_status.setText('设置、密钥和宠物图片不在导出与清空范围内。')
        row.add(self.data_status)
        card.add_row(row)
        content.addWidget(card)

        card = PrefCard('paw', '宠物形象',
                        '2D 使用这张图片，3D 使用内置形象，可在桌面右键切换。')
        row = PrefRow('正在使用', '桌面上就是这一只。')
        self.pet_gallery_layout = QGridLayout()
        self.pet_gallery_layout.setContentsMargins(0, 0, 0, 0)
        self.pet_gallery_layout.setHorizontalSpacing(10)
        self.pet_gallery_layout.setVerticalSpacing(10)
        gallery = QWidget()
        gallery.setLayout(self.pet_gallery_layout)
        row.add(gallery)
        actions, action_row = _pref_actions()
        button('上传新图片', self.choose_image, action_row)
        self.remove_image_button = button('移除这张图片', self.remove_pet_image, action_row)
        row.add(actions)
        actions, action_row = _pref_actions()
        self.cutout_button = button('纯色背景移除', self.remove_image_background, action_row)
        self.restore_button = button('恢复原图', self.restore_original_image, action_row)
        row.add(actions)
        note = _pref_text(10, 'ink_3', wrap=True)
        note.setText('上传或切换后直接使用这张图片，不再生成动作。建议使用透明背景 PNG；'
                     '纯色底图可先做背景移除。上传新图片会保留在历史中。')
        row.add(note)
        card.add_row(row)

        row = PrefRow('桌面位置', '记住上次拖到的地方，不跟随显示器切换。')
        actions, action_row = _pref_actions()
        button('找回宠物', self.reset_pet_position, action_row)
        row.add(actions)
        card.add_row(row)
        content.addWidget(card)
        self.refresh_pet_gallery()

        card = PrefCard('ding', '钉钉群通知',
                        '只有明确标了「钉钉通知」的待办，到期才推群。',
                        'info_wash', 'info')
        row = PrefRow('群机器人', 'Webhook 与加签密钥由当前 Windows 用户加密保存，不写入设置文件。')
        self.dingtalk_webhook_input = QLineEdit(self.dingtalk_webhook)
        self.dingtalk_webhook_input.setEchoMode(QLineEdit.Password)
        self.dingtalk_webhook_input.setPlaceholderText(
            'https://oapi.dingtalk.com/robot/send?access_token=…')
        self.dingtalk_webhook_input.setMinimumWidth(0)
        self.dingtalk_secret_input = QLineEdit(self.dingtalk_secret)
        self.dingtalk_secret_input.setEchoMode(QLineEdit.Password)
        self.dingtalk_secret_input.setPlaceholderText('机器人“加签”密钥')
        self.dingtalk_secret_input.setMinimumWidth(0)
        row.add(self.dingtalk_webhook_input)
        row.add(self.dingtalk_secret_input)
        actions, action_row = _pref_actions()
        button('保存钉钉设置', self.save_dingtalk, action_row, primary=True)
        button('发送测试', self.test_dingtalk, action_row)
        row.add(actions)
        self.dingtalk_status = _pref_text(10, 'ink_3', wrap=True)
        self.dingtalk_status.setText('已配置，仅标记的任务会推送。'
                                     if self.dingtalk_webhook else '尚未配置钉钉机器人。')
        row.add(self.dingtalk_status)
        card.add_row(row)
        self.dingtalk_test.connect(self.on_dingtalk_test)
        content.addWidget(card)

        self.tabs.addTab(page, '设置')
        self._pref_rows = page.findChildren(PrefRow)
        self.apply_settings_layout(self.width(), force=True)
        self.refresh_settings_theme()

    def _time_edit(self, value):
        widget = QTimeEdit()
        hour, minute = parse_clock(value or DEFAULT_DND_START).split(':')
        widget.setTime(QTime(int(hour), int(minute)))
        widget.setDisplayFormat('HH:mm')
        widget.setButtonSymbols(QAbstractSpinBox.NoButtons)
        widget.setKeyboardTracking(False)
        widget.setAlignment(Qt.AlignCenter)
        widget.setFixedSize(78, 32)
        return widget

    def apply_settings_layout(self, width, force=False):
        if not hasattr(self, 'settings_canvas_layout'):
            return
        pad = 32 if width > 1280 else 20
        stacked = width < 1080
        state = (pad, stacked)
        if not force and state == self._settings_layout_state:
            return
        self._settings_layout_state = state
        self.settings_canvas_layout.setContentsMargins(pad, 24, pad, 32)
        for row in self._pref_rows:
            row.set_stacked(stacked)
        columns = 3 if stacked else 5
        if columns != self._pet_columns:
            self._pet_columns = columns
            if hasattr(self, 'pet_gallery_layout'):
                self._reflow_pet_gallery()

    def _reflow_pet_gallery(self):
        """列数变化只重排现有缩略图，避免拖动缩放时重建导致闪烁。"""
        tiles = getattr(self, '_pet_tiles', None)
        if not tiles:
            self.refresh_pet_gallery()
            return
        columns = self._pet_columns
        for tile in tiles:
            self.pet_gallery_layout.removeWidget(tile)
        for column in range(8):
            self.pet_gallery_layout.setColumnStretch(column, 0)
        self.pet_gallery_layout.setColumnStretch(columns, 1)
        for position, tile in enumerate(tiles):
            self.pet_gallery_layout.addWidget(tile, position // columns, position % columns)

    def refresh_settings_theme(self):
        if not hasattr(self, 'settings_page'):
            return
        t = tokens()
        for label in self.settings_page.findChildren(QLabel):
            name = getattr(label, '_token_name', None)
            if not name or not hasattr(label, '_style_base'):
                continue
            label.setStyleSheet(f'{label._style_base}color:{getattr(t, name)};background:transparent;')
        if hasattr(self, 'data_path'):
            self.data_path.set_color(t.ink_3)
        time_style = (f'QTimeEdit {{background:{t.surface};border:1px solid {t.border};'
                      f'border-radius:8px;padding:4px 8px;color:{t.ink};'
                      f'font-family:"{T.FONT_MONO}","Consolas",monospace;font-size:12px;font-weight:600;}}'
                      f'QTimeEdit:focus {{border-color:{t.brand};}}')
        for widget in getattr(self, '_time_edits', []):
            widget.setStyleSheet(time_style)
        danger_style = (f'QPushButton {{background:transparent;color:{t.alert};border:1px solid {t.border};'
                        f'border-radius:8px;padding:7px 14px;font-family:"{T.FONT_UI}";font-size:12px;}}'
                        f'QPushButton:hover {{background:{t.alert_wash};border-color:{t.alert};'
                        f'color:{t.alert};}}'
                        f'QPushButton:pressed {{background:{t.alert_wash};}}')
        for widget in self._danger_buttons:
            widget.setStyleSheet(danger_style)
        for widget in self.settings_page.findChildren(QWidget):
            if hasattr(widget, 'refresh_theme'):
                widget.refresh_theme()
            else:
                widget.update()

    def change_reminder_setting(self, key, checked):
        self.settings[key] = bool(checked)
        self._persist_quick('提醒设置已更新。')
        if key == 'early_nudge' and hasattr(self, 'refresh_home'):
            self.refresh_home()

    def _sync_dnd_state(self):
        if not hasattr(self, 'dnd_state'):
            return
        enabled = bool(self.settings.get('dnd_enabled', True))
        self.dnd_state.set_state('已开启' if enabled else '已关闭',
                                 'done' if enabled else 'next',
                                 'check' if enabled else '')

    def on_dnd_toggled(self, checked):
        self.settings['dnd_enabled'] = bool(checked)
        self._sync_dnd_state()
        self._persist_quick('免打扰已开启。' if checked else '免打扰已关闭。')

    def dnd_time_changed(self, *_):
        start = self.dnd_start_edit.time().toString('HH:mm')
        end = self.dnd_end_edit.time().toString('HH:mm')
        if (start, end) == (self.settings.get('dnd_start'), self.settings.get('dnd_end')):
            return
        self.settings.update(dnd_start=start, dnd_end=end)
        self._persist_quick(f'免打扰时段：{start} — {end}')

    def _persist_quick(self, message):
        try:
            self.persist_settings()
        except OSError:
            self.statusBar().showMessage('设置暂时无法保存，本次运行仍然有效。', 6000)
            return
        self.statusBar().showMessage(message, 4000)

    def restore_default_settings(self):
        answer = QMessageBox.question(
            self, '恢复默认',
            '只恢复主题、密度与提醒开关，清空数据、密钥和宠物图片不受影响。继续？')
        if answer != QMessageBox.Yes:
            return
        defaults = dict(_SETTINGS_DEFAULTS)
        self.settings.update(defaults)
        self._persist_quick('已恢复默认设置。')
        for widget, key in ((self.early_nudge_check, 'early_nudge'),
                            (self.sound_check, 'sound_enabled'),
                            (self.auto_postpone_check, 'auto_postpone')):
            widget.blockSignals(True)
            widget.setChecked(defaults[key])
            widget.blockSignals(False)
        self.dnd_switch.blockSignals(True)
        self.dnd_switch.setChecked(defaults['dnd_enabled'])
        self.dnd_switch.blockSignals(False)
        for widget, key in ((self.dnd_start_edit, 'dnd_start'), (self.dnd_end_edit, 'dnd_end')):
            widget.blockSignals(True)
            hour, minute = defaults[key].split(':')
            widget.setTime(QTime(int(hour), int(minute)))
            widget.blockSignals(False)
        self._sync_dnd_state()
        self.settings_theme_segment.set_current(defaults['theme'])
        self.settings_density_segment.set_current(defaults['density'])
        if hasattr(self, 'task_density'):
            self.task_density.set_current(defaults['density'])
        self.set_theme(defaults['theme'], persist=False)
        self.refresh_tasks()
        self.refresh_home()
        self.settings_notice.setText('已恢复默认设置；密钥、钉钉和宠物图片保持不变。')
        _pref_color(self.settings_notice, 'ink_3')

    def test_model_connection(self):
        base = self.base_url.text().strip()
        model = self.model.text().strip()
        if not base or not model:
            _pref_color(self.settings_test_status, 'alert')
            self.settings_test_status.setText('请先填写服务地址和模型。')
            return
        try:
            base = validate_endpoint(base)
        except ValueError as exc:
            _pref_color(self.settings_test_status, 'alert')
            self.settings_test_status.setText(str(exc))
            return
        candidate = {'base_url': base, 'model': model, 'api_key': self.key.text().strip()}
        self.test_button.setEnabled(False)
        _pref_color(self.settings_test_status, 'ink_3')
        self.settings_test_status.setText('正在测试连接…')

        def work():
            try:
                ms = test_connection(candidate)
                ok, message = True, f'连接成功：{model}，{ms} 毫秒。'
            except (OSError, ValueError) as exc:
                ok, message = False, str(exc)
            try:
                self.settings_test.emit(ok, message)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def on_settings_test(self, ok, message):
        if hasattr(self, 'test_button'):
            self.test_button.setEnabled(True)
        _pref_color(self.settings_test_status, 'calm' if ok else 'alert')
        self.settings_test_status.setText(message)
        self.statusBar().showMessage(message, 8000)

    def save_web_search_settings(self):
        key = self.tavily_key.text().strip()
        if len(key.encode('utf-8')) > 8192:
            QMessageBox.warning(self, '设置未保存', 'Tavily 密钥过长，请检查后重试。')
            return
        try:
            if key:
                self.secret_store.save_tavily(key)
            else:
                self.secret_store.remove_tavily()
            candidate = dict(self.settings, tavily_key=key,
                             web_search_enabled=self.web_search_enabled.isChecked())
            self.persist_settings(candidate)
            self.settings = candidate
            if hasattr(self, 'update_web_search_ui'):
                self.update_web_search_ui()
            message = ('联网搜索设置已保存；密钥由当前 Windows 用户加密保存。' if key
                       else '已清除 Tavily 密钥，联网搜索关闭。')
            self.websearch_status.setText(message)
            _pref_color(self.websearch_status, 'ink_3')
            self.statusBar().showMessage(message, 6000)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '设置未保存', str(exc))

    def test_websearch(self):
        key = self.tavily_key.text().strip()
        if not key:
            _pref_color(self.websearch_status, 'alert')
            self.websearch_status.setText('请先填写 Tavily API Key。')
            return
        if hasattr(self, 'test_web_button'):
            self.test_web_button.setEnabled(False)
        _pref_color(self.websearch_status, 'ink_3')
        self.websearch_status.setText('正在测试 Tavily 连接（会消耗 1 credit）…')

        def work():
            try:
                ms = websearch.test_connection(key)
                ok, message = True, f'联网搜索连接成功：{ms} 毫秒。'
            except (OSError, ValueError) as exc:
                ok, message = False, '联网搜索测试失败：' + str(exc)
            try:
                self.websearch_test.emit(ok, message)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def on_websearch_test(self, ok, message):
        if hasattr(self, 'test_web_button'):
            self.test_web_button.setEnabled(True)
        _pref_color(self.websearch_status, 'calm' if ok else 'alert')
        self.websearch_status.setText(message)
        self.statusBar().showMessage(message, 8000)

    def export_settings_data(self):
        name = f'desktop-pet-export-{datetime.now():%Y%m%d}.json'
        path, _ = QFileDialog.getSaveFileName(self, '导出数据', str(Path.home() / name),
                                              'JSON 文件 (*.json)')
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        try:
            self.store.export_data(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '导出未完成', str(exc))
            return
        tasks = len(self.store.pending()) + len(self.store.history('done'))
        message = f'已导出 {tasks} 条待办和 {len(self.store.sessions())} 段对话：{Path(path).name}'
        _pref_color(self.data_status, 'calm')
        self.data_status.setText(message)
        self.statusBar().showMessage(message, 8000)

    def open_data_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root)))

    def reset_pet_position(self):
        if hasattr(self, 'pet'):
            self.pet.reset_position()

    def clear_settings_data(self):
        first = QMessageBox.warning(
            self, '清空数据',
            '将清空全部待办、对话和草稿，并先自动备份数据库。\n'
            'API Key、钉钉配置和宠物图片不会被删除。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if first != QMessageBox.Yes:
            return
        second = QMessageBox.warning(
            self, '再次确认',
            '确定清空全部待办和对话？清空后可在数据目录用 .bak 备份恢复。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if second != QMessageBox.Yes:
            return
        try:
            backup = self.store.clear_data()
        except (OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, '清空未完成', str(exc))
            return
        self.active_session = 'default'
        self.refresh_sessions()
        self.load_conversation()
        self.refresh_tasks()
        self.refresh_home()
        self.refresh_pet_tag()
        message = f'数据已清空，备份：{Path(backup).name}' if backup else '数据已清空。'
        _pref_color(self.data_status, 'calm')
        self.data_status.setText(message)
        self.statusBar().showMessage(message, 8000)

    def persist_settings(self, settings=None):
        settings = self.settings if settings is None else settings
        path = self.root / 'settings.json'
        temp = path.with_suffix('.tmp')
        allowed = ('base_url', 'model', 'pet_image', 'pet_image_original', 'pet_images', 'active_session', 'stream',
                   'remember_key', 'pet_position', 'pet_paused', 'pet_walking', 'pet_animations',
                   'pet_animation_backup', 'pet_mode', 'theme', 'density', 'early_nudge', 'sound_enabled',
                   'auto_postpone', 'dnd_enabled', 'dnd_start', 'dnd_end', 'sidebar_collapsed',
                   'web_search_enabled')
        temp.write_text(json.dumps({k: settings[k] for k in allowed if k in settings}, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)

    def save_settings(self):
        try:
            base = validate_endpoint(self.base_url.text()) if self.base_url.text().strip() else ''
            model = self.model.text().strip()
            if bool(base) != bool(model):
                raise ValueError('请同时填写服务地址和模型，或同时留空使用规则模式')
            key = self.key.text().strip()
            if self.secret_endpoint and base != self.secret_endpoint and key == self.settings.get('api_key'):
                raise ValueError('服务地址已改变，请重新输入用于新服务的 API Key。')
            remember = self.remember_key.isChecked()
            if remember:
                if not base or not model:
                    raise ValueError('请先填写服务地址和模型，再记住密钥。')
                self.secret_store.save(base, key)
            else:
                self.secret_store.remove()
            candidate = dict(self.settings, base_url=base, model=model, api_key=key,
                             stream=self.stream_enabled.isChecked(), remember_key=remember)
            self.persist_settings(candidate)
            self.settings = candidate
            self.secret_endpoint = base if remember else None
            self.update_request_status()
            if hasattr(self, 'update_model_chip'):
                self.update_model_chip()
            if hasattr(self, 'refresh_chat_rail'):
                self.refresh_chat_rail()
            message = '设置已保存；密钥由当前 Windows 用户加密保存。' if remember else '设置已保存；API Key 仅在本次运行有效。'
            self.settings_notice.setText(message)
            _pref_color(self.settings_notice, 'ink_3')
            self.statusBar().showMessage(message, 6000)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '设置未保存', str(exc))

    def save_dingtalk(self):
        webhook = self.dingtalk_webhook_input.text().strip()
        secret = self.dingtalk_secret_input.text().strip()
        try:
            if webhook:
                webhook = validate_webhook(webhook)
                if not secret:
                    raise DingTalkError('启用加签的机器人需要填写加签密钥')
                self.secret_store.save_dingtalk(webhook, secret)
            else:
                self.secret_store.remove_dingtalk()
                secret = ''
                self.dingtalk_secret_input.clear()
            self.dingtalk_webhook, self.dingtalk_secret = webhook, secret
            message = '钉钉机器人已保存，仅标记钉钉通知的待办会推送。' if webhook else '已关闭钉钉通知。'
            self.dingtalk_status.setText(message)
            _pref_color(self.dingtalk_status, 'ink_3')
            self.statusBar().showMessage(message, 6000)
        except (ValueError, OSError) as exc:
            self.dingtalk_status.setText('保存失败：' + str(exc))
            _pref_color(self.dingtalk_status, 'alert')

    def test_dingtalk(self):
        webhook = self.dingtalk_webhook_input.text().strip()
        secret = self.dingtalk_secret_input.text().strip()
        try:
            webhook = validate_webhook(webhook)
            if not secret:
                raise DingTalkError('请填写加签密钥')
        except DingTalkError as exc:
            self.dingtalk_status.setText(str(exc))
            _pref_color(self.dingtalk_status, 'alert')
            return
        due_label = local_time((datetime.now().astimezone() + timedelta(hours=1)).isoformat())
        self.dingtalk_status.setText('正在发送测试消息…')
        _pref_color(self.dingtalk_status, 'ink_3')

        def work():
            try:
                dingtalk_send(webhook, secret, '钉钉通知测试', due_label, '不重复')
                ok, message = True, '测试消息已发送，请查看钉钉群。'
            except (OSError, ValueError) as exc:
                ok, message = False, '测试失败：' + str(exc)
            try:
                self.dingtalk_test.emit(ok, message)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def on_dingtalk_test(self, ok, message):
        self.dingtalk_status.setText(message)
        _pref_color(self.dingtalk_status, 'calm' if ok else 'alert')
        self.statusBar().showMessage(message, 8000)

    def endpoint_edited(self):
        if self.secret_endpoint and self.base_url.text().strip().rstrip('/') != self.secret_endpoint:
            self.key.clear()
            self.secret_endpoint = None
            self.settings_notice.setText('服务地址已改变，请填写新服务的密钥。')
            _pref_color(self.settings_notice, 'alert')

    def key_edited(self):
        self.secret_endpoint = None

    def save_startup(self):
        try:
            self.startup_manager.set_enabled(self.login_startup.isChecked())
            self.settings_notice.setText('启动设置已应用。移动应用目录或Python环境后，需要重新应用此设置。')
            _pref_color(self.settings_notice, 'ink_3')
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '启动设置未应用', str(exc))

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择宠物图片', '', '图片 (*.png *.jpg *.jpeg *.webp)')
        if not path:
            return
        try:
            if Path(path).stat().st_size > 10 * 1024 * 1024:
                raise ValueError('请选择 10 MB 以内的图片')
            reader = QImageReader(path)
            size = reader.size()
            if not reader.canRead() or size.width() <= 0 or size.height() <= 0 or size.width() * size.height() > 16000000:
                raise ValueError('图片无法读取或超过 1600 万像素')
            if reader.read().isNull():
                raise ValueError('图片解码失败')
            target = self.root / ('pet-' + uuid.uuid4().hex + Path(path).suffix.lower())
            shutil.copyfile(path, target)
            records = [dict(item) for item in self.settings.get('pet_images', [])]
            records.append({'image': str(target)})
            if self.apply_pet_image(str(target), records, '新形象准备好了。'):
                self.pet.say('新形象准备好了！')
            else:
                target.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '图片未导入', str(exc))

    def active_pet_record(self):
        path = self.settings.get('pet_image', '')
        if not path:
            return None
        for record in self.settings.get('pet_images', []):
            if record.get('image') == path:
                return record
        return None

    def refresh_pet_gallery(self):
        while self.pet_gallery_layout.count():
            item = self.pet_gallery_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        active = self.settings.get('pet_image', '')
        columns = self._pet_columns
        for column in range(8):
            self.pet_gallery_layout.setColumnStretch(column, 0)
        self.pet_gallery_layout.setColumnStretch(columns, 1)
        default_tile = PetImageTile(QPixmap.fromImage(default_pet_image()), not active)
        default_tile.setToolTip('默认形象')
        default_tile.clicked.connect(self.select_default_image)
        self.pet_gallery_layout.addWidget(default_tile, 0, 0)
        tiles = [default_tile]
        for index, record in enumerate(self.settings.get('pet_images', [])):
            path = record.get('image', '')
            tile = PetImageTile(QPixmap(path), path == active)
            tile.setToolTip(Path(path).name)
            tile.clicked.connect(lambda item=record: self.select_pet_image(item))
            position = index + 1
            self.pet_gallery_layout.addWidget(tile, position // columns, position % columns)
            tiles.append(tile)
        self._pet_tiles = tiles
        record = self.active_pet_record()
        self.remove_image_button.setEnabled(record is not None)
        self.cutout_button.setEnabled(record is not None)
        self.restore_button.setEnabled(bool(record and record.get('original') and Path(record['original']).is_file()))

    def select_default_image(self):
        if not self.settings.get('pet_image'):
            return
        self.apply_pet_image(None, None, '已切换到默认形象。')

    def select_pet_image(self, record):
        path = record.get('image', '')
        if not path or path == self.settings.get('pet_image'):
            return
        if not self.apply_pet_image(path, None, '已切换宠物图片。'):
            self.refresh_pet_gallery()

    def apply_pet_image(self, path, records=None, notice=''):
        """Apply an image (or the built-in pet); the picture is shown as-is."""
        if path and QImage(path).isNull():
            QMessageBox.warning(self, '图片无法使用', '图片无法读取，请重新上传。')
            return False
        # 0.20 起不再生成动作，直接使用原图。旧的生成流程保留备查：
        # image = default_pet_image() if not path else QImage(path)
        # folder = self.root / 'animations' / ('auto-' + uuid.uuid4().hex)
        # animations = save_motion(generate_motion(image), folder)
        candidate = {key: value for key, value in self.settings.items()
                     if key not in ('pet_animations', 'pet_animation_backup')}
        if records is not None:
            candidate['pet_images'] = records
        if path:
            candidate['pet_image'] = path
        else:
            candidate.pop('pet_image', None)
        try:
            self.persist_settings(candidate)
        except OSError:
            QMessageBox.warning(self, '设置未保存', '无法写入宠物设置，形象保持不变。')
            return False
        previous = self.settings
        self.settings = candidate
        self.cleanup_auto_animations(previous.get('pet_animations'))
        self.pet.sequences = {}
        self.pet.load_image(path or '')
        self.refresh_pet_gallery()
        message = notice or '已使用这张图片。'
        self.settings_notice.setText(message)
        _pref_color(self.settings_notice, 'ink_3')
        self.statusBar().showMessage(message, 6000)
        return True

    def cleanup_auto_animations(self, config):
        if not isinstance(config, dict):
            return
        folders = set()
        for entry in config.values():
            if not isinstance(entry, dict):
                continue
            frames = entry.get('frames')
            if not isinstance(frames, list) or not frames or not isinstance(frames[0], str):
                continue
            folder = Path(frames[0]).parent
            if folder.parent == self.root / 'animations' and folder.name.startswith('auto-'):
                folders.add(folder)
        for folder in folders:
            cleanup_generated(folder)

    def remove_pet_image(self):
        record = self.active_pet_record()
        if record is None:
            return
        answer = QMessageBox.question(self, '移除宠物图片', '移除当前图片？图片文件会从数据目录删除。')
        if answer != QMessageBox.Yes:
            return
        records = [dict(item) for item in self.settings.get('pet_images', []) if item.get('image') != record.get('image')]
        if not self.apply_pet_image(None, records, '图片已移除，已切换到默认形象。'):
            return
        referenced = {item.get('image') for item in records} | {item.get('original') for item in records}
        for key in ('image', 'original'):
            path = record.get(key)
            if not isinstance(path, str) or path in referenced:
                continue
            target = Path(path)
            if target.is_relative_to(self.root):
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass

    def remove_image_background(self):
        record = self.active_pet_record()
        path = self.settings.get('pet_image', '')
        if record is None or not path or not Path(path).is_file():
            QMessageBox.information(self, '请先上传图片', '默认宠物不需要去背景，请先上传宠物图片。')
            return
        reader = QImageReader(path)
        size = reader.size()
        if size.width() <= 0 or size.height() <= 0 or size.width() * size.height() > 16000000:
            QMessageBox.warning(self, '图片无法处理', '图片尺寸无效或超过1600万像素，请重新上传。')
            return
        image = reader.read()
        if image.isNull():
            QMessageBox.warning(self, '图片无法处理', '图片无法解码，请重新上传。')
            return
        dialog = CutoutDialog(image, self)
        target = self.root / ('pet-cutout-' + uuid.uuid4().hex + '.png')
        try:
            if dialog.exec_() != QDialog.Accepted:
                return
            if dialog.result_image.isNull() or not dialog.result_image.save(str(target), 'PNG'):
                raise OSError('无法保存处理结果')
            records = [dict(item) for item in self.settings.get('pet_images', [])]
            for item in records:
                if item.get('image') == path:
                    item['original'] = item.get('original') or path
                    item['image'] = str(target)
                    break
            else:
                records.append({'image': str(target), 'original': path})
            if not self.apply_pet_image(str(target), records, '背景处理已应用。'):
                target.unlink(missing_ok=True)
            else:
                self.pet.say('背景处理已应用，可以在设置中恢复原图。')
        except OSError:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            QMessageBox.warning(self, '处理结果未应用', '保存失败，原图与当前宠物保持不变。')
        finally:
            dialog.deleteLater()

    def restore_original_image(self):
        record = self.active_pet_record()
        original = record.get('original') if record else ''
        if not original or not Path(original).is_file():
            QMessageBox.information(self, '没有可恢复的原图', '请先上传图片并应用去背景。')
            return
        records = [dict(item) for item in self.settings.get('pet_images', [])]
        for item in records:
            if item.get('image') == record.get('image'):
                item['image'] = original
                item.pop('original', None)
                break
        if self.apply_pet_image(original, records, '已恢复去背景前的原图。'):
            self.pet.say('已恢复去背景前的原图。')

    # 0.20 起桌宠只显示静态图片，不再生成或导入动作；以下动作工作室实现保留备查，未启用。
    """
    def import_animation(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择一组动作帧（按文件名数字排序）', '', '图片 (*.png *.jpg *.jpeg *.webp)')
        if not paths:
            return
        folder = self.root / 'animations' / uuid.uuid4().hex
        try:
            entry = import_sequence(paths, folder, self.animation_fps.value())
            action = self.animation_action.currentData()
            animations = dict(self.settings.get('pet_animations', {}))
            animations[action] = entry
            candidate = dict(self.settings, pet_animations=animations)
            candidate.pop('pet_animation_backup', None)
            self.persist_settings(candidate)
            self.settings = candidate
            self.pet.load_animations()
            self.pet.play_action(action)
            self.settings_notice.setText('动作已导入；暂停状态下请先从宠物右键恢复动画。')
        except (OSError, ValueError):
            if folder.is_dir():
                for target in folder.glob('*.png'):
                    try:
                        target.unlink()
                    except OSError:
                        pass
                try:
                    folder.rmdir()
                except OSError:
                    pass
            QMessageBox.warning(self, '动作未导入', '请选择2～24张图片，每帧不超过100万像素，合计不超过16 MB，并检查数据目录是否可写。原动作保持不变。')

    def preview_animation(self):
        action = self.animation_action.currentData()
        if action not in self.pet.sequences:
            QMessageBox.information(self, '没有可播放的动作', '请先导入此动作；文件丢失或损坏时需要重新导入。')
            return
        self.pet.show()
        self.pet.ensure_visible()
        self.pet.play_action(action)
        if self.pet.paused:
            self.settings_notice.setText('动画已暂停，请从宠物右键菜单恢复动画。')

    def remove_animation(self):
        animations = dict(self.settings.get('pet_animations', {}))
        animations.pop(self.animation_action.currentData(), None)
        candidate = dict(self.settings, pet_animations=animations)
        candidate.pop('pet_animation_backup', None)
        try:
            self.persist_settings(candidate)
            self.settings = candidate
            self.pet.load_animations()
            self.settings_notice.setText('此动作已移除，其他动作和静态形象保留。')
        except OSError:
            QMessageBox.warning(self, '动作未移除', '设置保存失败，原动作保持不变。')

    def generate_image_motion(self):
        path = self.settings.get('pet_image', '')
        if not path or not Path(path).is_file():
            QMessageBox.information(self, '请先上传图片', '请先上传宠物图片；透明背景图片效果更好。')
            return
        reader = QImageReader(path)
        size = reader.size()
        if size.width() <= 0 or size.height() <= 0 or size.width() * size.height() > 16000000:
            QMessageBox.warning(self, '无法生成动作', '图片尺寸无效或超过1600万像素，请重新上传。')
            return
        image = reader.read()
        if image.isNull():
            QMessageBox.warning(self, '无法生成动作', '图片无法解码，请重新上传。')
            return
        dialog = MotionDialog(image, self)
        folder = self.root / 'animations' / uuid.uuid4().hex
        try:
            if dialog.exec_() != QDialog.Accepted:
                return
            animations = save_motion(dialog.frames, folder)
            candidate = dict(self.settings, pet_animations=animations,
                             pet_animation_backup=self.settings.get('pet_animations', {}))
            self.persist_settings(candidate)
            self.settings = candidate
            self.pet.load_animations()
            self.settings_notice.setText('基础动作已应用；可撤销最近生成。暂停时请从宠物右键恢复动画。')
            self.pet.say('新动作准备好了！')
        except (OSError, ValueError):
            cleanup_generated(folder)
            QMessageBox.warning(self, '动作未应用', '无法保存生成结果，原动作和形象保持不变。')
        finally:
            dialog.timer.stop()
            dialog.update_timer.stop()
            dialog.deleteLater()

    def undo_generated_motion(self):
        if 'pet_animation_backup' not in self.settings:
            QMessageBox.information(self, '没有可撤销的生成', '生成并应用基础动作后可撤销；手动导入或移除动作会结束这次撤销机会。')
            return
        candidate = dict(self.settings, pet_animations=self.settings['pet_animation_backup'])
        candidate.pop('pet_animation_backup', None)
        try:
            self.persist_settings(candidate)
            self.settings = candidate
            self.pet.load_animations()
            self.settings_notice.setText('已恢复生成前的动作配置，静态形象保持不变。')
        except OSError:
            QMessageBox.warning(self, '撤销未完成', '设置保存失败，当前动作保持不变。')
    """


# 0.30 旧设置页（Fluent SettingCardGroup + QFormLayout）保留备查，未启用。
_LEGACY_SETTINGS_030 = r'''
    def build_settings(self):
        page = QWidget()
        page.setStyleSheet('QFrame#petTile { background:#FFFFFF; border:1px solid #F3EADF; border-radius:12px; }'
                           'QFrame#petTile[selected="true"] { border:2px solid #E8735A; background:#FFF7F2; }')
        form = QFormLayout(page)
        form.setContentsMargins(30, 28, 30, 24)
        form.setVerticalSpacing(14)
        form.setHorizontalSpacing(22)
        heading = QLabel('偏好设置')
        heading.setObjectName('pageTitle')
        form.addRow(heading)
        root_form = form
        fluent_cards = []
        def section(title):
            nonlocal form
            if FLUENT_MODE:
                from qfluentwidgets import SettingCardGroup, CardWidget
                group = SettingCardGroup(title, page)
                group.titleLabel.setObjectName('sectionTitle')
                card = CardWidget(group)
                card.setStyleSheet('CardWidget {background:#FFFFFF;border:0;border-radius:16px;}')
                card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
                from .theme import add_soft_shadow
                add_soft_shadow(card)
                form = QFormLayout(card)
                form.setContentsMargins(20, 20, 20, 20)
                form.setVerticalSpacing(14)
                form.setHorizontalSpacing(20)
                group.addSettingCard(card)
                fluent_cards.append((group, card))
                root_form.addRow(group)
            else:
                label = QLabel(title)
                label.setObjectName('sectionTitle')
                form.addRow(label)
        section('模型与对话')
        note = QLabel('支持 Chat Completions 兼容服务。留空模型时使用本地规则模式。\n密钥默认只保留在本次运行中；可选择由当前 Windows 用户加密保存。')
        note.setWordWrap(True)
        form.addRow(note)
        self.base_url = QLineEdit(self.settings.get('base_url', ''))
        self.base_url.setPlaceholderText('供应商提供的 API 根地址，通常以 /v1 结尾')
        self.model = QLineEdit(self.settings.get('model', ''))
        self.key = QLineEdit(self.settings.get('api_key', ''))
        self.key.setEchoMode(QLineEdit.Password)
        form.addRow('服务地址', self.base_url)
        form.addRow('模型名称', self.model)
        form.addRow('API Key', self.key)
        self.remember_key = QCheckBox('安全记住 API Key（仅限当前 Windows 用户）')
        self.remember_key.setEnabled(self.secret_store.supported)
        self.remember_key.setChecked(self.settings.get('remember_key', False))
        form.addRow(self.remember_key)
        self.base_url.textEdited.connect(self.endpoint_edited)
        self.key.textEdited.connect(self.key_edited)
        self.stream_enabled = QCheckBox('逐步显示回复（服务不支持时可关闭）')
        self.stream_enabled.setChecked(self.settings.get('stream', True))
        form.addRow(self.stream_enabled)
        row = QHBoxLayout()
        button('保存模型设置', self.save_settings, row, primary=True)
        row.addStretch()
        form.addRow(row)
        section('启动与后台')
        self.login_startup = QCheckBox('登录 Windows 后启动，主窗口收起到托盘')
        self.login_startup.setEnabled(self.startup_manager.supported)
        if self.startup_manager.supported:
            try:
                self.login_startup.setChecked(self.startup_manager.enabled())
            except ValueError:
                self.settings_warning += ' 无法读取开机启动状态，可手动应用设置。'
        form.addRow(self.login_startup)
        startup_row = QHBoxLayout()
        startup_button = button('应用启动设置', self.save_startup, startup_row)
        startup_row.addStretch()
        startup_button.setEnabled(self.startup_manager.supported)
        form.addRow(startup_row)
        self.settings_notice = QLabel(self.settings_warning)
        self.settings_notice.setWordWrap(True)
        form.addRow(self.settings_notice)
        section('钉钉群通知')
        dingtalk_note = QLabel('仅当待办被明确标记“钉钉通知”时，到期才推送到钉钉群；其他提醒仍只在本地显示。\nWebhook 与加签密钥由当前 Windows 用户加密保存，不写入设置文件。')
        dingtalk_note.setWordWrap(True)
        form.addRow(dingtalk_note)
        self.dingtalk_webhook_input = QLineEdit(self.dingtalk_webhook)
        self.dingtalk_webhook_input.setEchoMode(QLineEdit.Password)
        self.dingtalk_webhook_input.setPlaceholderText('https://oapi.dingtalk.com/robot/send?access_token=…')
        self.dingtalk_secret_input = QLineEdit(self.dingtalk_secret)
        self.dingtalk_secret_input.setEchoMode(QLineEdit.Password)
        self.dingtalk_secret_input.setPlaceholderText('机器人“加签”密钥')
        form.addRow('Webhook', self.dingtalk_webhook_input)
        form.addRow('加签密钥', self.dingtalk_secret_input)
        dingtalk_row = QHBoxLayout()
        button('保存钉钉设置', self.save_dingtalk, dingtalk_row, primary=True)
        button('发送测试', self.test_dingtalk, dingtalk_row)
        dingtalk_row.addStretch()
        form.addRow(dingtalk_row)
        self.dingtalk_status = QLabel('已配置，仅标记的任务会推送。' if self.dingtalk_webhook else '尚未配置钉钉机器人。')
        self.dingtalk_status.setWordWrap(True)
        form.addRow(self.dingtalk_status)
        self.dingtalk_test.connect(self.on_dingtalk_test)
        section('宠物形象')
        self.pet_gallery_layout = QGridLayout()
        self.pet_gallery_layout.setContentsMargins(0, 0, 0, 0)
        self.pet_gallery_layout.setHorizontalSpacing(10)
        self.pet_gallery_layout.setVerticalSpacing(10)
        form.addRow(self.pet_gallery_layout)
        image_row = QHBoxLayout()
        button('上传新图片', self.choose_image, image_row)
        self.remove_image_button = button('移除这张图片', self.remove_pet_image, image_row)
        image_row.addStretch()
        form.addRow(image_row)
        cutout_row = QHBoxLayout()
        self.cutout_button = button('纯色背景移除', self.remove_image_background, cutout_row)
        self.restore_button = button('恢复原图', self.restore_original_image, cutout_row)
        cutout_row.addStretch()
        form.addRow(cutout_row)
        pet_note = QLabel('上传或切换后直接使用这张图片，不再生成动作。建议使用透明背景 PNG；纯色底图可先做背景移除。上传新图片会保留在下方历史中。')
        pet_note.setWordWrap(True)
        form.addRow(pet_note)
        hint = QLabel('3D 模式使用内置形象，可在宠物右键菜单中切换；上传图片用于 2D 模式。\n应用退出、关机或睡眠时无法即时提醒；再次运行或恢复时补检。\n数据目录：' + str(self.root))
        hint.setWordWrap(True)
        hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(hint)
        self.refresh_pet_gallery()
        for group, card in fluent_cards:
            card.setMinimumHeight(card.layout().sizeHint().height())
            group.adjustSize()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, '设置')
'''
