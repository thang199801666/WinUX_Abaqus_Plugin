"""General WinUX application preferences."""

from __future__ import annotations

from .storage import JsonPreferenceStore


class GeneralPreferences:
    """Persist application-wide behavior in the shared settings document."""

    DEFAULT_AUTO_LOGIN = False
    DEFAULT_CONSOLE_VISIBLE = False
    DEFAULT_SHOW_HIDDEN_FILES = False

    def __init__(self, root=None):
        self._store = JsonPreferenceStore("settings.json", root=root)
        self.path = self._store.path

    def load(self):
        data = self._store.load()
        return {
            "auto_login": bool(
                data.get("auto_login", self.DEFAULT_AUTO_LOGIN)
            ),
            "console_visible": bool(
                data.get("console_visible", self.DEFAULT_CONSOLE_VISIBLE)
            ),
            "show_hidden_files": bool(
                data.get("show_hidden_files", self.DEFAULT_SHOW_HIDDEN_FILES)
            ),
        }

    def load_auto_login(self):
        return bool(self.load()["auto_login"])

    def save(self, *, auto_login, show_hidden_files=None):
        data = self._store.load()
        data["auto_login"] = bool(auto_login)
        if show_hidden_files is not None:
            data["show_hidden_files"] = bool(show_hidden_files)
        self._store.save(data)

    def save_auto_login(self, enabled):
        self.save(auto_login=enabled)

    def load_show_hidden_files(self):
        return bool(self.load()["show_hidden_files"])

    def save_show_hidden_files(self, enabled):
        data = self._store.load()
        data["show_hidden_files"] = bool(enabled)
        self._store.save(data)

    def load_console_visible(self):
        return bool(self.load()["console_visible"])

    def save_console_visible(self, visible):
        data = self._store.load()
        data["console_visible"] = bool(visible)
        self._store.save(data)
