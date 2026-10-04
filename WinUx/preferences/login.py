"""Persistent SSH login history protected by the current Windows user."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

from .storage import JsonPreferenceStore


class _DataBlob(ctypes.Structure):
    _fields_ = (("size", wintypes.DWORD),
                ("data", ctypes.POINTER(ctypes.c_byte)))


def _blob(value):
    buffer = ctypes.create_string_buffer(value)
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect(value):
    raw = value.encode("utf-8")
    source, source_buffer = _blob(raw)
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), "WinUX SSH password", None, None, None, 0,
            ctypes.byref(result)):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(result.data, result.size)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        _local_free(result.data)


def _unprotect(value):
    raw = base64.b64decode(value.encode("ascii"))
    source, source_buffer = _blob(raw)
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0,
            ctypes.byref(result)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.data, result.size).decode("utf-8")
    finally:
        _local_free(result.data)


def _local_free(pointer):
    local_free = ctypes.windll.kernel32.LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p
    local_free(ctypes.cast(pointer, ctypes.c_void_p))


class LoginPreferences:
    """Store successful hosts, usernames and optionally their passwords."""

    MAX_RECENT_USERNAMES = 6

    def __init__(self, root=None):
        self._store = JsonPreferenceStore("login.json", root=root)
        self.path = self._store.path

    def load(self):
        data = self._load_raw()
        hosts = data.get("hosts", {})
        usernames = self._recent_usernames(data.get("usernames", []))
        last_host = str(data.get("last_host", ""))
        last_username = str(data.get("last_username", ""))
        password = self.password_for(last_username, data)
        return {
            "hosts": list(hosts),
            "ports": {str(host): str(port) for host, port in hosts.items()},
            # Persistence is oldest -> newest; the popup is easier to use when
            # its most recently successful username appears first.
            "usernames": list(reversed(usernames)),
            "host": last_host,
            "port": str(hosts.get(last_host, 22)),
            "username": last_username,
            "password": password,
            "remember": bool(password),
        }

    def save_success(self, values, remember=False):
        data = self._load_raw()
        host = str(values["host"]).strip()
        username = str(values["username"]).strip()
        hosts = data.setdefault("hosts", {})
        hosts[host] = int(values["port"])
        usernames = self._recent_usernames(data.get("usernames", []))
        if username:
            usernames = [value for value in usernames if value != username]
            usernames.append(username)
        usernames = usernames[-self.MAX_RECENT_USERNAMES:]
        data["usernames"] = usernames
        data["last_host"] = host
        data["last_username"] = username
        passwords = data.get("passwords", {})
        if not isinstance(passwords, dict):
            passwords = {}
        if remember:
            passwords[username] = _protect(str(values.get("password", "")))
        else:
            passwords.pop(username, None)
        data["passwords"] = {
            value: encrypted
            for value, encrypted in passwords.items()
            if value in usernames
        }
        self._write(data)

    def add_username(self, username):
        data = self._load_raw()
        value = str(username).strip()
        if not value:
            return
        usernames = [item for item in self._recent_usernames(
            data.get("usernames", [])) if item != value]
        usernames.append(value)
        data["usernames"] = usernames[-self.MAX_RECENT_USERNAMES:]
        passwords = data.get("passwords", {})
        if isinstance(passwords, dict):
            data["passwords"] = {
                item: encrypted
                for item, encrypted in passwords.items()
                if item in data["usernames"]
            }
        self._write(data)

    def remove_username(self, username):
        data = self._load_raw()
        value = str(username).strip()
        data["usernames"] = [item for item in self._recent_usernames(
            data.get("usernames", []))
                             if item != value]
        data.setdefault("passwords", {}).pop(value, None)
        if data.get("last_username") == value:
            data["last_username"] = (data["usernames"][-1]
                                     if data["usernames"] else "")
        self._write(data)

    @classmethod
    def _recent_usernames(cls, values):
        """Normalize a persisted oldest-to-newest MRU username list."""
        if not isinstance(values, (list, tuple)):
            return []
        recent = []
        for raw_value in values:
            value = str(raw_value).strip()
            if not value:
                continue
            if value in recent:
                recent.remove(value)
            recent.append(value)
        return recent[-cls.MAX_RECENT_USERNAMES:]

    def password_for(self, username, data=None):
        encrypted = (data or self._load_raw()).get("passwords", {}).get(username)
        if not encrypted:
            return ""
        try:
            return _unprotect(encrypted)
        except (OSError, ValueError, TypeError):
            return ""

    def _load_raw(self):
        try:
            data = self._store.load()
            if "hosts" in data:
                return data
            # Migrate the original single-login format in memory.
            host = str(data.get("host", ""))
            username = str(data.get("username", ""))
            migrated = {
                "hosts": {host: int(data.get("port", 22))} if host else {},
                "usernames": [username] if username else [],
                "last_host": host, "last_username": username, "passwords": {},
            }
            if username and data.get("password"):
                migrated["passwords"][username] = data["password"]
            return migrated
        except (OSError, ValueError, TypeError):
            return {}

    def _write(self, data):
        self._store.save(data)

    # Compatibility with older callers.
    def save(self, values):
        self.save_success(values, remember=True)

    def clear(self):
        self._store.clear()
