"""General WinUX application preferences."""

from __future__ import annotations

from .storage import JsonPreferenceStore


class GeneralPreferences:
    """Persist application-wide behavior in the shared settings document."""

    DEFAULT_AUTO_LOGIN = False
    DEFAULT_CONSOLE_VISIBLE = False

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
        }

    def load_auto_login(self):
        return bool(self.load()["auto_login"])

    def save(self, *, auto_login):
        data = self._store.load()
        data["auto_login"] = bool(auto_login)
        self._store.save(data)

    def save_auto_login(self, enabled):
        self.save(auto_login=enabled)
    def load_console_visible(self):
        return bool(self.load()["console_visible"])

    def save_console_visible(self, visible):
        data = self._store.load()
        data["console_visible"] = bool(visible)
        self._store.save(data)
