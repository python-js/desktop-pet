"""Settings page and local configuration persistence."""
import json
import shutil
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QImageReader, QPixmap
from PyQt5.QtWidgets import (QWidget,QFormLayout,QLabel,QLineEdit,QCheckBox,QHBoxLayout,QMessageBox,QFileDialog,QScrollArea,QDialog,QGridLayout,QFrame,QSizePolicy,QApplication)
from ..core import validate_endpoint
from ..dingtalk import DingTalkError, send as dingtalk_send, validate_webhook
from ..secure_storage import SecretStore
from ..startup import StartupManager
from .common import button, local_time
from .cutout import CutoutDialog
from ..motion import generate_motion, save_motion, cleanup_generated
from .pet import default_pet_image
from .controls import CheckBox as QCheckBox, FLUENT_MODE
from .controls import LineEdit as QLineEdit
from qfluentwidgets import ScrollArea as QScrollArea


class PetImageTile(QFrame):
    clicked = pyqtSignal()

    def __init__(self, pixmap, selected=False, parent=None):
        super().__init__(parent)
        self.setObjectName('petTile')
        self.setFixedSize(96, 96)
        self.setProperty('selected', selected)
        self.setCursor(Qt.PointingHandCursor)
        label = QLabel(self)
        label.setGeometry(8, 8, 80, 80)
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        label.setAttribute(Qt.WA_TransparentForMouseEvents)

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
                self.settings = {k: loaded[k] for k in ('base_url', 'model', 'pet_image', 'pet_image_original', 'active_session') if isinstance(loaded.get(k), str)}
                for key in ('stream', 'remember_key', 'pet_paused', 'pet_walking'):
                    if isinstance(loaded.get(key), bool):
                        self.settings[key] = loaded[key]
                if loaded.get('pet_mode') in ('2d', '3d'):
                    self.settings['pet_mode'] = loaded['pet_mode']
                position = loaded.get('pet_position')
                if isinstance(position, list) and len(position) == 2 and all(type(v) is int and abs(v) <= 100000 for v in position):
                    self.settings['pet_position'] = position
        except (OSError, ValueError):
            pass
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

    def persist_settings(self, settings=None):
        settings = self.settings if settings is None else settings
        path = self.root / 'settings.json'
        temp = path.with_suffix('.tmp')
        allowed = ('base_url', 'model', 'pet_image', 'pet_image_original', 'pet_images', 'active_session', 'stream', 'remember_key', 'pet_position', 'pet_paused', 'pet_walking', 'pet_animations', 'pet_animation_backup', 'pet_mode')
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
            message = '设置已保存；密钥由当前 Windows 用户加密保存。' if remember else '设置已保存；API Key 仅在本次运行有效。'
            self.settings_notice.setText(message)
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
            self.statusBar().showMessage(message, 6000)
        except (ValueError, OSError) as exc:
            self.dingtalk_status.setText('保存失败：' + str(exc))

    def test_dingtalk(self):
        webhook = self.dingtalk_webhook_input.text().strip()
        secret = self.dingtalk_secret_input.text().strip()
        try:
            webhook = validate_webhook(webhook)
            if not secret:
                raise DingTalkError('请填写加签密钥')
        except DingTalkError as exc:
            self.dingtalk_status.setText(str(exc))
            return
        due_label = local_time((datetime.now().astimezone() + timedelta(hours=1)).isoformat())
        self.dingtalk_status.setText('正在发送测试消息…')

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
        self.statusBar().showMessage(message, 8000)

    def endpoint_edited(self):
        if self.secret_endpoint and self.base_url.text().strip().rstrip('/') != self.secret_endpoint:
            self.key.clear()
            self.secret_endpoint = None
            self.settings_notice.setText('服务地址已改变，请填写新服务的密钥。')

    def key_edited(self):
        self.secret_endpoint = None

    def save_startup(self):
        try:
            self.startup_manager.set_enabled(self.login_startup.isChecked())
            self.settings_notice.setText('启动设置已应用。移动应用目录或Python环境后，需要重新应用此设置。')
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
                widget.deleteLater()
        active = self.settings.get('pet_image', '')
        default_tile = PetImageTile(QPixmap.fromImage(default_pet_image()), not active)
        default_tile.setToolTip('默认形象')
        default_tile.clicked.connect(self.select_default_image)
        self.pet_gallery_layout.addWidget(default_tile, 0, 0)
        for index, record in enumerate(self.settings.get('pet_images', [])):
            path = record.get('image', '')
            tile = PetImageTile(QPixmap(path), path == active)
            tile.setToolTip(Path(path).name)
            tile.clicked.connect(lambda item=record: self.select_pet_image(item))
            position = index + 1
            self.pet_gallery_layout.addWidget(tile, position // 6, position % 6)
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

