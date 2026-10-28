"""Current-user Windows login startup. Accessed only through explicit settings."""
import subprocess
import sys
from pathlib import Path


class StartupError(ValueError):
    pass


class StartupManager:
    REG_PATH = r'Software\Microsoft\Windows\CurrentVersion\Run'
    NAME = 'DesktopPet'

    def __init__(self, root=None, executable=None, registry=None, supported=None, frozen=None):
        self.root = Path(root) if root else Path(__file__).resolve().parent.parent
        self.executable = Path(executable or sys.executable)
        self.registry = registry
        self.supported = sys.platform == 'win32' if supported is None else supported
        self.frozen = getattr(sys, 'frozen', False) if frozen is None else frozen

    def backend(self):
        if not self.supported:
            raise StartupError('此平台的开机启动尚未适配。')
        if self.registry is not None:
            return self.registry
        import winreg
        return winreg

    def command(self):
        launcher = self.root / 'launch.py'
        executable = self.executable
        hidden = executable.with_name('pythonw.exe')
        if executable.name.lower() == 'python.exe' and hidden.exists():
            executable = hidden
        if not executable.is_file() or (not self.frozen and not launcher.is_file()):
            raise StartupError('启动文件不存在，请检查应用位置和Python环境。')
        args = [str(executable), '--background'] if self.frozen else [str(executable), str(launcher), '--background']
        result = subprocess.list2cmdline(args)
        if len(result) > 260:
            raise StartupError('启动路径过长，请将应用放在较短的目录后再开启。')
        return result

    def enabled(self):
        registry = self.backend()
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, self.REG_PATH, 0, registry.KEY_READ) as key:
                value, _ = registry.QueryValueEx(key, self.NAME)
                return bool(value)
        except FileNotFoundError:
            return False
        except OSError:
            raise StartupError('无法读取开机启动状态。') from None

    def set_enabled(self, enabled):
        registry = self.backend()
        command = self.command() if enabled else None
        try:
            if enabled:
                with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, self.REG_PATH, 0, registry.KEY_SET_VALUE) as key:
                    registry.SetValueEx(key, self.NAME, 0, registry.REG_SZ, command)
            else:
                try:
                    with registry.OpenKey(registry.HKEY_CURRENT_USER, self.REG_PATH, 0, registry.KEY_SET_VALUE) as key:
                        registry.DeleteValue(key, self.NAME)
                except FileNotFoundError:
                    pass
        except OSError:
            raise StartupError('无法更改开机启动，请检查当前用户权限。') from None
