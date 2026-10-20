"""QMenu-like modeless command surface.

Unlike :class:`QMenu`, ``QModelessMenu`` deliberately uses an ordinary window
rather than the renderer popup stack.  The class exists for surfaces such as
terminals where opening a context menu must never capture a nested native or
ImGui popup loop and outside clicks must still reach their destination.
"""
from __future__ import annotations

import time

from ..core import QObject, QPoint, Signal
from ..gui import QtFusionPalette
from ..themes import (
    ThemeTarget, ThemeColor, ThemeStyle, theme_component, make_theme,
    menu_surface_theme,
)
from .buttons import QPushButton
from .primitives import QSeparator
from .popup_panel import QPopupPanel


class QModelessMenu(QObject):
    """Small keyboard-navigable modeless menu with deterministic row geometry."""

    DEFAULT_WIDTH = 202
    DEFAULT_ROW_HEIGHT = 25
    DEFAULT_SEPARATOR_HEIGHT = 7

    def __init__(self, actions=(), *, separators_after=(), width=DEFAULT_WIDTH,
                 row_height=DEFAULT_ROW_HEIGHT, separator_height=DEFAULT_SEPARATOR_HEIGHT,
                 backend=None, after=None, parent=None):
        super().__init__(parent=parent, after=after)
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        self.backend = backend
        self.triggered = Signal(self)
        self.aboutToShow = Signal(self)
        self.aboutToHide = Signal(self)
        self.WIDTH = max(80, int(width))
        self.ROW_HEIGHT = max(18, int(row_height))
        self.SEPARATOR_HEIGHT = max(1, int(separator_height))
        self.ACTIONS = tuple(self._normalize_action(x) for x in actions)
        self.SEPARATORS_AFTER = frozenset(str(x) for x in separators_after)
        self._items = {}
        self._controls = {}
        self._enabled = {}
        self._shortcuts = {}
        self._row_handler_registries = []
        self._visible = False
        self._current_action = None
        self._context = None
        self._last_open_time = 0.0
        self._last_open_position = None
        self._themes = []

        self._normal_theme = self._make_row_theme(
            QtFusionPalette.MENU, QtFusionPalette.MENU_HOVER,
            QtFusionPalette.MENU_ACTIVE, QtFusionPalette.TEXT)
        self._current_theme = self._make_row_theme(
            QtFusionPalette.MENU_ACTIVE, QtFusionPalette.MENU_ACTIVE,
            QtFusionPalette.MENU_ACTIVE, QtFusionPalette.TEXT)
        self._disabled_theme = self._make_row_theme(
            QtFusionPalette.MENU, QtFusionPalette.MENU,
            QtFusionPalette.MENU, QtFusionPalette.TEXT_DISABLED)
        height = (
            6 + self.ROW_HEIGHT * len(self.ACTIONS)
            + self.SEPARATOR_HEIGHT * len(self.SEPARATORS_AFTER) + 8
        )
        self._panel = QPopupPanel(
            width=self.WIDTH, height=height, backend=backend, after=after,
            object_name="QModelessMenu")
        self._panel.setParent(self)
        self.tag = self._panel.tag
        for action, label, shortcut in self.ACTIONS:
            self._add_item(action, label, shortcut)
            if action in self.SEPARATORS_AFTER:
                separator = QSeparator(parent=self._panel, backend=backend)
                separator.setTheme(self._separator_theme())
        self._window_theme = menu_surface_theme(
            padding=(3, 3), spacing=(0, 1), backend=backend, tag=None, cache=False)
        self._panel.setTheme(self._window_theme)

    @staticmethod
    def _normalize_action(spec):
        if isinstance(spec, dict):
            return (str(spec.get("action") or spec.get("id") or spec.get("label") or ""),
                    str(spec.get("label") or ""), str(spec.get("shortcut") or ""))
        if isinstance(spec, (tuple, list)):
            if len(spec) < 2:
                raise ValueError("menu action requires at least (action, label)")
            action, label = spec[0], spec[1]
            shortcut = spec[2] if len(spec) > 2 else ""
            return str(action), str(label), str(shortcut or "")
        raise TypeError("menu action must be dict, tuple or list")

    def _separator_theme(self):
        theme = make_theme(theme_component(
            ThemeTarget.SEPARATOR,
            colors={
                ThemeColor.SEPARATOR: QtFusionPalette.BORDER_LIGHT,
                ThemeColor.SEPARATOR_HOVERED: QtFusionPalette.BORDER_LIGHT,
                ThemeColor.SEPARATOR_ACTIVE: QtFusionPalette.BORDER_LIGHT,
            },
        ), backend=self.backend)
        self._themes.append(theme)
        return theme

    def _make_row_theme(self, face, hover, active, text):
        theme = make_theme(theme_component(
            ThemeTarget.PUSH_BUTTON,
            colors={
                ThemeColor.BUTTON: face,
                ThemeColor.BUTTON_HOVERED: hover,
                ThemeColor.BUTTON_ACTIVE: active,
                ThemeColor.TEXT: text,
                ThemeColor.BORDER: (0, 0, 0, 0),
            },
            styles={
                ThemeStyle.FRAME_BORDER_SIZE: 0,
                ThemeStyle.FRAME_ROUNDING: 0,
                ThemeStyle.FRAME_PADDING: (7, 3),
                ThemeStyle.BUTTON_TEXT_ALIGN: (0.0, 0.5),
            },
        ), backend=self.backend)
        self._themes.append(theme)
        return theme

    @staticmethod
    def _row_label(label, shortcut):
        if not shortcut:
            return label
        gap = max(2, 22 - len(label) - len(shortcut))
        return "{}{}{}".format(label, " " * gap, shortcut)

    def _add_item(self, action, label, shortcut):
        control = QPushButton(
            self._row_label(label, shortcut), width=self.WIDTH - 8,
            height=self.ROW_HEIGHT, parent=self._panel, backend=self.backend)
        control.clicked.connect(lambda action_key=action: self._clicked(user_data=action_key))
        self._controls[action] = control
        self._items[action] = control.tag
        self._shortcuts[action] = shortcut
        self._enabled[action] = True
        control.setTheme(self._normal_theme)
        try:
            with self.backend.item_handler_registry() as registry:
                self.backend.add_item_hover_handler(callback=self._hovered, user_data=action)
            self.backend.bind_item_handler_registry(control.tag, registry)
            self._row_handler_registries.append(registry)
        except Exception:
            pass

    def _hovered(self, sender=None, app_data=None, user_data=None):
        if not self._visible:
            return
        action = str(user_data or "")
        if self._enabled.get(action, False):
            self._set_current(action)
        elif self._current_action == action:
            self._set_current(None)

    def _clicked(self, sender=None, app_data=None, user_data=None):
        action = str(user_data or "")
        if not self._enabled.get(action, True):
            return False
        self._set_current(action)
        self.triggered.emit(action, self._context)
        return True

    def _apply_theme(self, action):
        control = self._controls.get(action)
        if control is None or control._deleted:
            return
        if not self._enabled.get(action, True):
            theme = self._disabled_theme
        elif action == self._current_action:
            theme = self._current_theme
        else:
            theme = self._normal_theme
        # Keep the native control technically enabled so the backend cannot
        # replace our left-aligned menu metrics with a disabled-button style.
        control.setEnabled(True)
        control.setTheme(theme)

    def _set_current(self, action):
        action = str(action) if action is not None else None
        if action is not None and not self._enabled.get(action, False):
            action = None
        old = self._current_action
        self._current_action = action
        if old is not None:
            self._apply_theme(old)
        if action is not None:
            self._apply_theme(action)

    def _enabled_actions(self):
        return [action for action, _label, _shortcut in self.ACTIONS
                if self._enabled.get(action, True)]

    def setActionEnabled(self, action, enabled):
        action, enabled = str(action), bool(enabled)
        self._enabled[action] = enabled
        if not enabled and self._current_action == action:
            self._current_action = None
        self._apply_theme(action)
        return action in self._items

    def isActionEnabled(self, action):
        return bool(self._enabled.get(str(action), False))

    def move_current(self, delta):
        if not self._visible:
            return False
        actions = self._enabled_actions()
        if not actions:
            self._set_current(None)
            return False
        try:
            index = actions.index(self._current_action)
        except ValueError:
            index = -1 if delta >= 0 else 0
        index = (index + (1 if delta >= 0 else -1)) % len(actions)
        self._set_current(actions[index])
        return True

    def activate_current(self):
        return self.trigger(self._current_action)

    def trigger(self, action):
        if not self._visible:
            return False
        action = str(action or "")
        if action not in self._items or not self._enabled.get(action, False):
            return False
        self._set_current(action)
        self.triggered.emit(action, self._context)
        return True

    @property
    def is_open(self):
        return bool(self._visible)

    def popup(self, position=None, *, context=None):
        if position is None:
            from ..gui.system import QCursor
            position = QCursor.pos(backend=self.backend)
        point = position if isinstance(position, QPoint) else QPoint(*position)
        point = self._panel.clampPosition(point)
        normalized = point.toTuple()
        now = time.monotonic()
        duplicate = (
            self._visible and self._last_open_position == normalized
            and now - self._last_open_time < 0.12
        )
        self._last_open_time = now
        self._last_open_position = normalized
        self._context = context
        if duplicate:
            return True
        self.aboutToShow.emit()
        self._panel.showAt(point, clamp=False, focus=False)
        self._visible = True
        enabled = self._enabled_actions()
        self._set_current(enabled[0] if enabled else None)
        return True

    def hide(self):
        if self._visible:
            self.aboutToHide.emit()
        self._visible = False
        self._set_current(None)
        self._panel.hide()
        return True

    def containsGlobalPoint(self, point):
        return self._panel.containsGlobalPoint(point)

    def context(self):
        return self._context

    def delete(self):
        if self._deleted:
            return
        self._visible = False
        self._current_action = None
        self._context = None
        for registry in tuple(self._row_handler_registries):
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass
        self._row_handler_registries.clear()
        for theme in tuple(self._themes) + (self._window_theme,):
            try:
                if theme and self.backend.does_item_exist(theme):
                    self.backend.delete_item(theme)
            except Exception:
                pass
        super().delete()


__all__ = ["QModelessMenu"]
