"""General WinUX application preferences."""

from __future__ import annotations

from .storage import JsonPreferenceStore
from ..services.file_color_rules import load_color_rules, normalize_color_rules
from .appearance import (
    DEFAULT_UI_FONT_FAMILY, DEFAULT_UI_FONT_SIZE, DEFAULT_UI_FONT_STYLE,
    DEFAULT_UI_THEME, normalize_ui_theme,
    normalize_ui_font_family, normalize_ui_font_style, normalize_ui_font_size,
)


class GeneralPreferences:
    """Persist application-wide behavior in the shared settings document."""

    DEFAULT_AUTO_LOGIN = False
    DEFAULT_CONSOLE_VISIBLE = False
    DEFAULT_SHOW_HIDDEN_FILES = False
    DEFAULT_FILE_COLORS = True
    DEFAULT_PRESERVE_FILE_TIMESTAMPS = True
    DEFAULT_UI_FONT_FAMILY = DEFAULT_UI_FONT_FAMILY
    DEFAULT_UI_FONT_SIZE = DEFAULT_UI_FONT_SIZE
    DEFAULT_UI_FONT_STYLE = DEFAULT_UI_FONT_STYLE
    DEFAULT_UI_THEME = DEFAULT_UI_THEME

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
            "ui_theme": normalize_ui_theme(data.get("ui_theme", self.DEFAULT_UI_THEME)),
            "ui_font_family": normalize_ui_font_family(
                data.get("ui_font_family", self.DEFAULT_UI_FONT_FAMILY)),
            "ui_font_size": normalize_ui_font_size(
                data.get("ui_font_size", self.DEFAULT_UI_FONT_SIZE)),
            "ui_font_style": normalize_ui_font_style(
                data.get("ui_font_family", self.DEFAULT_UI_FONT_FAMILY),
                data.get("ui_font_style", self.DEFAULT_UI_FONT_STYLE)),
            "dock_state": (dict(data.get("dock_state") or {})
                           if isinstance(data.get("dock_state"), dict) else {}),
        }

    def load_auto_login(self):
        return bool(self.load()["auto_login"])

    def save(self, *, auto_login, show_hidden_files=None, file_colors=None, file_color_rules=None,
             preserve_file_timestamps=None, ui_theme=None, ui_font_family=None, ui_font_size=None, ui_font_style=None):
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
        if ui_theme is not None:
            data['ui_theme'] = normalize_ui_theme(ui_theme)
        if ui_font_family is not None:
            data['ui_font_family'] = normalize_ui_font_family(ui_font_family)
        if ui_font_size is not None:
            data['ui_font_size'] = normalize_ui_font_size(ui_font_size)
        if ui_font_style is not None:
            family = data.get('ui_font_family', self.DEFAULT_UI_FONT_FAMILY)
            data['ui_font_style'] = normalize_ui_font_style(family, ui_font_style)
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
