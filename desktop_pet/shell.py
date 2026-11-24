"""Shell-side state shared by the WebView UI: settings.json, secrets and pet images."""
import json
import shutil
import uuid
from pathlib import Path

from PySide6.QtGui import QImage, QImageReader
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from .core import DEFAULT_DND_END, DEFAULT_DND_START, parse_clock, parse_due
from .motion import cleanup_generated
from .secure_storage import SecretStore
from .startup import StartupManager
from .ui.cutout import CutoutDialog
from .ui.theme import apply_theme, application_icon


def local_time(value):
    return parse_due(value).astimezone().strftime('%Y-%m-%d %H:%M')


class ShellMixin:
    """Configuration and pet-image flow used by the bridge and the tray/pet windows."""

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
                                                        'active_session', 'chat_session_day', 'density', 'dnd_start', 'dnd_end',
                                                        'last_update_check', 'skipped_version',
                                                        'update_notified_version')
                                 if isinstance(loaded.get(k), str)}
                for key in ('stream', 'remember_key', 'pet_paused', 'pet_walking'):
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
                             ('web_search_enabled', True), ('knowledge_enabled', False)):
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
        # 内置密钥优先；无内置文件时才回退到用户旧 DPAPI 密钥。
        from .bundled_secrets import bundled_tavily_key
        self.settings['tavily_key'] = bundled_tavily_key()
        if not self.settings['tavily_key']:
            try:
                self.settings['tavily_key'] = self.secret_store.load_tavily()
            except (OSError, ValueError):
                self.settings_warning += ' Tavily 密钥未能恢复，请检查内置 bundled_tavily.key。'
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

    def persist_settings(self, settings=None):
        settings = self.settings if settings is None else settings
        path = self.root / 'settings.json'
        temp = path.with_suffix('.tmp')
        allowed = ('base_url', 'model', 'pet_image', 'pet_images', 'active_session', 'chat_session_day', 'stream',
                   'remember_key', 'pet_position', 'pet_paused', 'pet_walking', 'pet_mode',
                   'theme', 'density', 'early_nudge', 'sound_enabled', 'auto_postpone',
                   'dnd_enabled', 'dnd_start', 'dnd_end', 'web_search_enabled',
                   'knowledge_enabled', 'last_inbox_review', 'last_update_check', 'skipped_version',
                   'update_notified_version')
        temp.write_text(json.dumps({k: settings[k] for k in allowed if k in settings}, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)

    def set_theme(self, theme, persist=True):
        theme = 'dark' if theme == 'dark' else 'light'
        self.theme = theme
        self.settings['theme'] = theme
        if persist:
            try:
                self.persist_settings()
            except OSError:
                self.statusBar().showMessage('主题设置暂时无法保存，本次运行仍然有效。', 6000)
        apply_theme(QApplication.instance(), theme)
        icon = application_icon()
        self.setWindowIcon(icon)
        tray = getattr(self, 'tray', None)
        if tray is not None:
            tray.setIcon(icon)

    def reset_pet_position(self):
        if hasattr(self, 'pet'):
            self.pet.reset_position()

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

    def apply_pet_image(self, path, records=None, notice=''):
        """Apply an image (or the built-in pet); the picture is shown as-is."""
        if path and QImage(path).isNull():
            QMessageBox.warning(self, '图片无法使用', '图片无法读取，请重新上传。')
            return False
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
        message = notice or '已使用这张图片。'
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
            if dialog.exec() != QDialog.Accepted:
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

    def web_search_ready(self):
        return bool(self.settings.get('tavily_key'))

    def knowledge_ready(self):
        try:
            return self.knowledge.stats()['docs'] > 0
        except (ValueError, OSError):
            return False
