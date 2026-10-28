"""Optional per-Windows-user DPAPI storage. No plaintext fallback."""
import ctypes
import json
import sys
from pathlib import Path
from ctypes import wintypes


class SecretStorageError(ValueError):
    pass


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data, decrypt=False):
    if sys.platform != 'win32':
        raise SecretStorageError('此平台尚未接入安全密钥存储，请使用本次运行模式。')
    source = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
            code = ctypes.get_last_error()
            raise SecretStorageError(f'Windows 无法读取或保存安全密钥（错误代码 {code:#x}），请重新输入或关闭记住密钥。')
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        if outgoing.data:
            kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


class SecretStore:
    MAGIC = b'DesktopPetDPAPI1\n'
    API_PATH = 'api-key.dpapi'
    DINGTALK_PATH = 'dingtalk.dpapi'

    def __init__(self, root, protector=None, supported=None):
        self.root = Path(root)
        self.path = self.root / self.API_PATH
        self.protector = protector or dpapi
        self.supported = sys.platform == 'win32' if supported is None else supported

    def _write(self, name, payload, label):
        if not self.supported:
            raise SecretStorageError(f'此平台尚未接入安全密钥存储，无法保存{label}。')
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        if len(data) > 16384:
            raise SecretStorageError(f'{label}过长，请检查后重试。')
        path = self.root / name
        temporary = path.with_suffix('.tmp')
        try:
            temporary.write_bytes(self.MAGIC + self.protector(data))
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read(self, name, label):
        path = self.root / name
        if not path.exists():
            return None
        if not self.supported:
            raise SecretStorageError(f'此平台尚未接入安全密钥存储，无法读取{label}。')
        if path.stat().st_size > 65536:
            raise SecretStorageError(f'{label}文件异常，请重新输入。')
        data = path.read_bytes()
        if not data.startswith(self.MAGIC):
            raise SecretStorageError(f'{label}文件格式不正确，请重新输入。')
        try:
            payload = json.loads(self.protector(data[len(self.MAGIC):], decrypt=True))
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except (ValueError, UnicodeError, TypeError):
            raise SecretStorageError(f'无法恢复{label}，请重新输入；原文件未自动删除。') from None

    def save(self, endpoint, key):
        if not key or len(key.encode('utf-8')) > 8192:
            raise SecretStorageError('请输入有效密钥，长度不得超过8192字节。')
        self._write(self.API_PATH, {'endpoint': endpoint, 'key': key}, '安全密钥')

    def load(self, endpoint):
        payload = self._read(self.API_PATH, '安全密钥')
        if payload is None:
            return ''
        if not isinstance(payload.get('key'), str):
            raise SecretStorageError('无法恢复安全密钥，请重新输入；原文件未自动删除。')
        return payload['key'] if payload.get('endpoint') == endpoint else ''

    def save_dingtalk(self, webhook, secret):
        if not isinstance(webhook, str) or not webhook or len(webhook.encode('utf-8')) > 4096:
            raise SecretStorageError('请输入有效的钉钉 Webhook 地址')
        if not isinstance(secret, str) or not secret or len(secret.encode('utf-8')) > 512:
            raise SecretStorageError('请输入有效的钉钉加签密钥')
        self._write(self.DINGTALK_PATH, {'webhook': webhook, 'secret': secret}, '钉钉机器人配置')

    def load_dingtalk(self):
        payload = self._read(self.DINGTALK_PATH, '钉钉机器人配置')
        if payload is None:
            return '', ''
        webhook, secret = payload.get('webhook'), payload.get('secret')
        if not isinstance(webhook, str) or not isinstance(secret, str):
            raise SecretStorageError('钉钉机器人配置格式不正确，请重新填写。')
        return webhook, secret

    def remove(self):
        (self.root / self.API_PATH).unlink(missing_ok=True)

    def remove_dingtalk(self):
        (self.root / self.DINGTALK_PATH).unlink(missing_ok=True)
