"""General WinUX application preferences."""

from __future__ import annotations

from .storage import JsonPreferenceStore
from ..services.file_color_rules import load_color_rules, normalize_color_rules


class GeneralPreferences:
    """Persist application-wide behavior in the shared settings document."""

    DEFAULT_AUTO_LOGIN = False
    DEFAULT_CONSOLE_VISIBLE = False
    DEFAULT_SHOW_HIDDEN_FILES = False
    DEFAULT_FILE_COLORS = True
    DEFAULT_PRESERVE_FILE_TIMESTAMPS = True

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
            "file_colors": bool(data.get("file_colors", self.DEFAULT_FILE_COLORS)),
            "file_color_rules": load_color_rules(data.get("file_color_rules")),
            "preserve_file_timestamps": bool(data.get('preserve_file_timestamps', self.DEFAULT_PRESERVE_FILE_TIMESTAMPS)),
        }

    def load_auto_login(self):
        return bool(self.load()["auto_login"])

    def save(self, *, auto_login, show_hidden_files=None, file_colors=None, file_color_rules=None,
             preserve_file_timestamps=None):
        data = self._store.load()
        data["auto_login"] = bool(auto_login)
        if show_hidden_files is not None:
            data["show_hidden_files"] = bool(show_hidden_files)
        if file_colors is not None:
            data["file_colors"] = bool(file_colors)
        if file_color_rules is not None:
            data["file_color_rules"] = normalize_color_rules(file_color_rules)
        if preserve_file_timestamps is not None:
            data['preserve_file_timestamps'] = bool(preserve_file_timestamps)
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
    def load_dock_state(self):
        """Return the last persisted QMainWindow-like dock layout state."""
        data = self._store.load()
        state = data.get("dock_state", {})
        return dict(state) if isinstance(state, dict) else {}

    def save_dock_state(self, state):
        """Persist dock placement without disturbing other general settings."""
        if not isinstance(state, dict):
            raise TypeError("dock state must be a dictionary")
        data = self._store.load()
        data["dock_state"] = dict(state)
        self._store.save(data)
        return True
