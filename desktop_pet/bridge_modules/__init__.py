"""Bridge module handlers: each module adapts JSON calls onto existing backend objects.

Install with bridge_modules.install(host); the window (MainWindow) is carried in
host.context['window'] so handlers can reach store/settings/secret_store/knowledge.
"""
from . import chat, knowledge, pet, secrets, settings, system, tasks, update


def install(host):
    host.register_module('settings', settings.handle)
    host.register_module('secrets', secrets.handle)
    host.register_module('system', system.handle)
    host.register_module('startup', system.handle_startup)
    host.register_module('knowledge', knowledge.handle)
    host.register_module('pet', pet.handle)
    host.register_module('tasks', tasks.handle)
    host.register_module('drafts', tasks.handle_drafts)
    host.register_module('chat', chat.handle)
    host.register_module('update', update.handle)
