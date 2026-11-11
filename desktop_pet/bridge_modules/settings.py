"""settings.*: whitelist read/write of settings.json plus settings.changed broadcast."""
import sqlite3
from pathlib import Path

from ..bridge import BridgeError
from ..core import parse_clock

BOOL_KEYS = ('stream', 'remember_key', 'pet_paused', 'pet_walking',
             'early_nudge', 'sound_enabled', 'auto_postpone', 'dnd_enabled',
             'web_search_enabled', 'knowledge_enabled')
CHOICE_KEYS = {'pet_mode': ('2d', '3d'), 'theme': ('light', 'dark'),
               'density': ('comfortable', 'compact')}
STR_KEYS = ('base_url', 'model', 'pet_image', 'active_session')
CLOCK_KEYS = ('dnd_start', 'dnd_end')
# Keys never handed to the web layer: api_key, tavily_key (DPAPI secrets), pet_images is
# managed by the shell-side image flow and read-only here.
READ_ONLY_KEYS = ('pet_images', 'pet_position')
ALL_KEYS = BOOL_KEYS + tuple(CHOICE_KEYS) + STR_KEYS + CLOCK_KEYS + READ_ONLY_KEYS


def handle(action, args, host):
    window = host.context['window']
    if action == 'getAll':
        return {key: window.settings.get(key) for key in ALL_KEYS if key in window.settings}
    if action == 'set':
        patch = args.get('patch')
        if not isinstance(patch, dict) or not patch:
            raise BridgeError('patch 必须是非空对象')
        unknown = sorted(set(patch) - set(ALL_KEYS))
        if unknown:
            raise BridgeError(f'未知设置项: {", ".join(unknown)}')
        if any(key in patch for key in READ_ONLY_KEYS):
            raise BridgeError(f'该设置项由壳子管理，不可从页面修改: '
                              f'{", ".join(k for k in READ_ONLY_KEYS if k in patch)}')
        validated = dict(patch)
        for key, value in patch.items():
            if key in BOOL_KEYS:
                if not isinstance(value, bool):
                    raise BridgeError(f'{key} 必须是布尔值')
                validated[key] = value
            elif key in CHOICE_KEYS:
                if value not in CHOICE_KEYS[key]:
                    raise BridgeError(f'{key} 取值必须是 {" / ".join(CHOICE_KEYS[key])}')
                validated[key] = value
            elif key in STR_KEYS:
                if not isinstance(value, str) or len(value) > 4096:
                    raise BridgeError(f'{key} 必须是不超过 4096 字符的文本')
                validated[key] = value.strip()
            elif key in CLOCK_KEYS:
                try:
                    validated[key] = parse_clock(value)
                except ValueError:
                    raise BridgeError(f'{key} 必须是 HH:MM 格式') from None
        for key, value in validated.items():
            window.settings[key] = value
        window.persist_settings()
        set_theme = getattr(window, 'set_theme', None)
        if 'theme' in validated and set_theme:
            # Keep tray/pet window on the Qt side in sync; persist=False because
            # the patch above already wrote settings.json.
            set_theme(validated['theme'], persist=False)
        host.emit_event('settings.changed', {'patch': patch})
        return {}
    if action == 'exportData':
        store = getattr(window, 'store', None)
        if store is None:
            raise BridgeError('数据存储不可用', code='NOT_AVAILABLE')
        path = str(args.get('path') or '').strip()
        if not path:
            raise BridgeError('path 不能为空')
        try:
            store.export_data(path)
            return {'file': Path(path).name,
                    'tasks': len(store.pending()) + len(store.history('done')),
                    'sessions': len(store.sessions())}
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise BridgeError(f'导出未完成：{exc}') from None
    if action == 'clearData':
        store = getattr(window, 'store', None)
        if store is None:
            raise BridgeError('数据存储不可用', code='NOT_AVAILABLE')
        try:
            backup = store.clear_data()
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise BridgeError(f'清空未完成：{exc}') from None
        window.settings['active_session'] = 'default'
        window.active_session = 'default'
        host.emit_event('tasks.changed', {'reason': 'cleared'})
        return {'backup': Path(backup).name if backup else None}
    raise BridgeError(f'未知方法: settings.{action}', code='NOT_FOUND')
