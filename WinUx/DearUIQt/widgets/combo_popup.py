"""Compact Qt-style choice popup using the shared QMenu input/lifetime engine."""
from .menu import QMenu
from ..gui.palette import QtFusionPalette
from ..core import Qt


class ComboPopup(QMenu):
    ICON_SLOT = 0
    CHECK_SLOT = 0
    ARROW_SLOT = 0
    ROW_PAD_X = 2
    LABEL_PAD = 6
    WINDOW_PAD_X = 1
    WINDOW_PAD_Y = 1
    TEXT_Y_NUDGE = -3

    def __init__(self, *args, **kwargs):
        self._choice_themes = {}
        super().__init__(*args, **kwargs)
        self._apply_surface()

    def _theme(self, selected=False, text=False):
        key = bool(selected), bool(text)
        if key in self._choice_themes:
            return self._choice_themes[key]
        b, p = self.backend, QtFusionPalette
        with b.theme() as theme:
            with b.theme_component(b.mvText if text else b.mvChildWindow):
                if text:
                    b.add_theme_color(b.mvThemeCol_Text, (255, 255, 255, 255) if selected else p.TEXT)
                else:
                    b.add_theme_color(b.mvThemeCol_ChildBg, p.HIGHLIGHT if selected else p.BASE)
                    b.add_theme_color(b.mvThemeCol_Border, (0, 0, 0, 0))
                    b.add_theme_style(b.mvStyleVar_WindowPadding, 0, 0)
                    b.add_theme_style(b.mvStyleVar_ItemSpacing, 0, 0)
                    b.add_theme_style(b.mvStyleVar_ChildBorderSize, 0)
        self._choice_themes[key] = theme
        return theme

    def _apply_surface(self):
        b, p = self.backend, QtFusionPalette
        with b.theme() as theme:
            with b.theme_component(b.mvAll):
                b.add_theme_color(b.mvThemeCol_WindowBg, p.BASE)
                b.add_theme_color(b.mvThemeCol_ChildBg, p.BASE)
                b.add_theme_color(b.mvThemeCol_Border, p.BORDER_DARK)
                b.add_theme_style(b.mvStyleVar_WindowPadding, 1, 1)
                b.add_theme_style(b.mvStyleVar_ItemSpacing, 0, 0)
                b.add_theme_style(b.mvStyleVar_WindowRounding, 0)
                b.add_theme_style(b.mvStyleVar_WindowBorderSize, 1)
                b.add_theme_style(b.mvStyleVar_ChildRounding, 0)
                b.add_theme_style(b.mvStyleVar_ChildBorderSize, 1)
        self._surface_theme = theme
        b.bind_item_theme(self.tag, theme)

    def _estimate_width(self, specs):
        return self._min_width

    def _set_active_action(self, action_id):
        previous = self._active_action
        super()._set_active_action(action_id)
        highlighted = getattr(self, "highlighted", None)
        if action_id is not None and action_id != previous and callable(highlighted):
            highlighted(int(action_id))

    def _build_row(self, spec, width):
        super()._build_row(spec, width)
        self._set_row_hover(str(spec.get("action") or spec.get("id") or ""), False)

    def _set_row_hover(self, action_id, hovered):
        parts = self._items.get(action_id)
        if parts is None:
            return
        self.backend.bind_item_theme(parts["row"], self._theme(hovered))
        self.backend.bind_item_theme(parts["label"], self._theme(hovered, text=True))

    def configureChoices(self, labels, width, max_rows):
        self._min_width = self._max_width = max(24, int(width))
        self.setActions([{"id": str(i), "action": str(i), "label": str(label)}
                         for i, label in enumerate(labels)])
        height = 2 * self.WINDOW_PAD_Y + min(len(labels), max_rows) * self.ROW_HEIGHT
        limits = ({} if getattr(self, "_parent_window", None) is not None else
                  {"min_size": (self._min_width, 1), "max_size": (self._min_width, max(2, height))})
        self.backend.configure_item(
            self.tag, width=self._min_width, height=max(2, height),
            no_scrollbar=len(labels) <= max_rows, no_scroll_with_mouse=False, **limits)

    def selectRow(self, index):
        self._set_active_action(str(index) if index >= 0 else None)
        try:
            config = self.backend.get_item_configuration(self.tag)
            height = config.get("height", 0) - 2 * self.WINDOW_PAD_Y
            scroll = self.backend.get_y_scroll(self.tag)
            top = max(0, index) * self.ROW_HEIGHT
            if top < scroll:
                self.backend.set_y_scroll(self.tag, top)
            elif top + self.ROW_HEIGHT > scroll + height:
                self.backend.set_y_scroll(self.tag, max(0, top + self.ROW_HEIGHT - height))
        except Exception:
            pass

    def navigate(self, command):
        # A combo list stops at either end instead of wrapping like QMenu.
        if command in ("up", "down", "home", "end"):
            ids = self._visible_action_ids()
            if not ids:
                return False
            current = ids.index(self._active_action) if self._active_action in ids else 0
            index = (0 if command == "home" else len(ids) - 1 if command == "end"
                     else max(0, min(len(ids) - 1, current + (1 if command == "down" else -1))))
            self.selectRow(index)
            return True
        return super().navigate(command)

    def _handle_key(self, key):
        if not self.isVisible():
            return False
        b = self.backend
        commands = (("Up", Qt.Key_Up, "up"), ("Down", Qt.Key_Down, "down"),
                    ("Home", Qt.Key_Home, "home"), ("End", Qt.Key_End, "end"))
        for name, qt_key, command in commands:
            if key in (qt_key, getattr(b, "mvKey_" + name, None)):
                return self.navigate(command)
        if key in (Qt.Key_Escape, Qt.Key_F4, getattr(b, "mvKey_Escape", None),
                   getattr(b, "mvKey_F4", None)):
            self.hide()
            cancelled = getattr(self, "cancelled", None)
            if callable(cancelled):
                cancelled()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space,
                   getattr(b, "mvKey_Return", None), getattr(b, "mvKey_Enter", None)):
            return self.navigate("activate")
        return False

    def delete(self):
        themes = list(self._choice_themes.values()) + [self._surface_theme]
        super().delete()
        for theme in themes:
            if self.backend.does_item_exist(theme):
                self.backend.delete_item(theme)
