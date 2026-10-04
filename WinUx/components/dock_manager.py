"""QMainWindow-like dock orchestration for Dear PyGui.

``DockWidget`` owns the chrome and behaviour of one tool panel.  ``DockManager``
owns the relationship between several docks that share one dock area: active
selection, tabification, tab-strip layout, floating state and lightweight state
serialization.  Keeping this separate from :mod:`view` prevents every future
WinUx tool from re-implementing QMainWindow-style bookkeeping.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Callable, Dict, Iterable, Optional

import dearpygui.dearpygui as dpg

from .interaction_gate import acquire_pointer_input, release_pointer_input
from .qt_style import QtFusionPalette
from .tooltip import add_styled_tooltip


class DockManager:
    """Manage a tabified group of Qt-like ``DockWidget`` instances.

    The current WinUx main window exposes one shared dock site around Job Viewer.
    Several docks can therefore live in the same site and are automatically
    tabified, matching ``QMainWindow::tabifyDockWidget`` semantics.  Floating
    docks remain registered but are excluded from the dock site's tab group.

    The class intentionally works with small duck-typed window objects.  A
    managed window only needs ``root``, ``resize(width, height)``, ``set_dock_area``
    and ``dock_mode`` attributes, which keeps the manager reusable for future
    tools beyond Job Plots.
    """

    TAB_HEIGHT = 25
    TAB_MIN_WIDTH = 88
    TAB_MAX_WIDTH = 220
    TAB_GAP = 1
    TAB_PADDING_X = 10
    TAB_DRAG_START_DISTANCE = 4
    TAB_TEAROFF_DISTANCE = 18
    TAB_INSERT_MARKER_WIDTH = 2

    BG = QtFusionPalette.TITLE
    BORDER = QtFusionPalette.BORDER
    ACTIVE_BG = QtFusionPalette.BASE
    ACTIVE_HOVER = QtFusionPalette.WINDOW_ALT
    INACTIVE_BG = QtFusionPalette.WINDOW
    INACTIVE_HOVER = QtFusionPalette.BUTTON_HOVER
    TEXT = QtFusionPalette.TEXT
    ACCENT = QtFusionPalette.HIGHLIGHT

    def __init__(
            self,
            parent,
            *,
            dock_area: str = "right",
            tab_position: str = "bottom",
            on_active_changed: Optional[Callable[[Optional[str]], None]] = None,
            on_tab_tearoff: Optional[Callable[[str, tuple, tuple], None]] = None,
            on_tab_order_changed: Optional[Callable[[tuple], None]] = None):
        self.parent = parent
        self.dock_area = self._normalize_area(dock_area)
        self.tab_position = (
            "top" if str(tab_position or "bottom").strip().lower() == "top"
            else "bottom")
        self.on_active_changed = on_active_changed
        self.on_tab_tearoff = on_tab_tearoff
        self.on_tab_order_changed = on_tab_order_changed
        self._entries: "OrderedDict[str, Dict[str, object]]" = OrderedDict()
        self._active_key: Optional[str] = None
        self._last_layout_size = (0, 0)
        self._tabs_dirty = True
        self._tab_buttons: Dict[str, object] = {}
        self._last_tab_width = 0

        # QTabBar-like pointer state. A press starts as a normal tab click, then
        # becomes an exclusive drag only after the cursor moves a few pixels.
        # Once dragging, global background handlers are blocked until release.
        self._tab_mouse_was_down = False
        self._tab_press_key: Optional[str] = None
        self._tab_press_pos = None
        self._tab_drag_key: Optional[str] = None
        self._tab_drag_started = False
        self._tab_drag_insert_index = None
        self._tab_drag_owner = object()
        self._suppress_click_key: Optional[str] = None
        self._suppress_click_until_frame = -1

        self._build_themes()
        self.tab_strip = dpg.add_child_window(
            parent=self.parent,
            pos=(0, 0),
            width=1,
            height=self.TAB_HEIGHT,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
            show=False,
        )
        dpg.bind_item_theme(self.tab_strip, self._strip_theme)
        self.tab_group = dpg.add_group(parent=self.tab_strip, horizontal=True)
        # A thin insertion caret mirrors QTabBar's live reorder feedback. The
        # drawlist is visual only; pointer ownership is handled explicitly.
        self._tab_drag_overlay = dpg.add_drawlist(
            parent=self.tab_strip, pos=(0, 0), width=1, height=self.TAB_HEIGHT)
        self._tab_insert_marker = dpg.draw_line(
            (0, 2), (0, self.TAB_HEIGHT - 2),
            color=self.ACCENT, thickness=self.TAB_INSERT_MARKER_WIDTH,
            show=False, parent=self._tab_drag_overlay)

    @staticmethod
    def _normalize_area(area):
        value = str(area or "right").strip().lower()
        return value if value in ("left", "right", "top", "bottom") else "right"

    def _build_themes(self):
        with dpg.theme() as self._strip_theme:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, self.BG)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            with dpg.theme_component(dpg.mvGroup):
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, self.TAB_GAP, 0)

        with dpg.theme() as self._active_tab_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, self.ACTIVE_BG)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, self.ACTIVE_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, self.ACTIVE_BG)
                dpg.add_theme_color(dpg.mvThemeCol_Text, self.TEXT)
                dpg.add_theme_color(dpg.mvThemeCol_Border, self.BORDER)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, self.TAB_PADDING_X, 3)

        with dpg.theme() as self._inactive_tab_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, self.INACTIVE_BG)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, self.INACTIVE_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, self.ACTIVE_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_Text, self.TEXT)
                dpg.add_theme_color(dpg.mvThemeCol_Border, self.BORDER)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, self.TAB_PADDING_X, 3)

    @property
    def active_key(self):
        return self._active_key

    def keys(self):
        return tuple(self._entries)

    def docked_keys(self):
        return tuple(
            key for key, entry in self._entries.items()
            if not bool(entry.get("floating")))

    def floating_keys(self):
        return tuple(
            key for key, entry in self._entries.items()
            if bool(entry.get("floating")))

    def has_docked(self):
        return any(not bool(entry.get("floating"))
                   for entry in self._entries.values())

    def is_registered(self, key):
        return str(key) in self._entries

    def add_dock_widget(self, key, window, title=None, area=None, activate=True):
        """Register a dock and, by default, make it the active tab."""
        key = str(key)
        area = self._normalize_area(area or self.dock_area)
        existing = self._entries.get(key)
        if existing is None:
            self._entries[key] = {
                "window": window,
                "title": str(title or getattr(window, "label", key)),
                "area": area,
                "floating": str(getattr(window, "dock_mode", "docked")).lower()
                == "floating",
            }
        else:
            existing.update(
                window=window,
                title=str(title or existing.get("title") or key),
                area=area,
            )
        self.dock_area = area
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        if activate and not bool(self._entries[key].get("floating")):
            self.raise_dock_widget(key)
        else:
            self._ensure_active()
        return key

    # Qt-style convenience alias.
    register_dock = add_dock_widget

    def remove_dock_widget(self, key):
        key = str(key)
        entry = self._entries.pop(key, None)
        if entry is None:
            return False
        if self._active_key == key:
            self._active_key = None
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        self._ensure_active(notify=True)
        return True

    unregister_dock = remove_dock_widget

    def set_title(self, key, title):
        entry = self._entries.get(str(key))
        if entry is None:
            return False
        title = str(title or "")
        if str(entry.get("title") or "") != title:
            entry["title"] = title
            self._tabs_dirty = True
        return True

    def set_dock_area(self, key, area, *, group=False):
        key = str(key)
        area = self._normalize_area(area)
        if key not in self._entries:
            return False
        targets = self.docked_keys() if group else (key,)
        for target in targets:
            entry = self._entries.get(target)
            if entry is None:
                continue
            entry["area"] = area
            window = entry.get("window")
            setter = getattr(window, "set_dock_area", None)
            if callable(setter):
                setter(area)
        self.dock_area = area
        self._last_layout_size = (0, 0)
        return True

    def tabify_dock_widget(self, first, second):
        """Place two registered docks in the same area/tab group.

        WinUx currently exposes one dock site, so tabification means aligning the
        second dock's area with the first and making the second dock active.
        """
        first = str(first)
        second = str(second)
        if first not in self._entries or second not in self._entries:
            return False
        area = self._normalize_area(self._entries[first].get("area"))
        self.set_dock_area(second, area)
        self.set_floating(second, False)
        self.raise_dock_widget(second)
        return True

    def set_floating(self, key, floating=True):
        key = str(key)
        entry = self._entries.get(key)
        if entry is None:
            return False
        floating = bool(floating)
        entry["floating"] = floating
        if floating and self._active_key == key:
            self._active_key = None
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        if not floating:
            self.raise_dock_widget(key)
        else:
            self._ensure_active(notify=True)
        return True

    def raise_dock_widget(self, key):
        """Activate one dock in the tabified group, like ``QDockWidget::raise``."""
        key = str(key)
        entry = self._entries.get(key)
        if entry is None or bool(entry.get("floating")):
            return False
        changed = self._active_key != key
        self._active_key = key
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        if changed:
            self._notify_active_changed()
        return True

    activate = raise_dock_widget

    def _ensure_active(self, notify=False):
        docked = self.docked_keys()
        if self._active_key in docked:
            return self._active_key
        previous = self._active_key
        self._active_key = docked[-1] if docked else None
        if notify and previous != self._active_key:
            self._notify_active_changed()
        return self._active_key

    def _notify_active_changed(self):
        callback = self.on_active_changed
        if callable(callback):
            callback(self._active_key)

    @staticmethod
    def _elide(text, max_chars):
        text = str(text or "")
        max_chars = max(1, int(max_chars))
        if len(text) <= max_chars:
            return text
        if max_chars <= 4:
            return "." * max_chars
        return text[:max_chars - 3].rstrip() + "..."

    def _tab_clicked(self, sender=None, app_data=None, user_data=None):
        key = str(user_data)
        if key == self._suppress_click_key:
            # The button click generated by the mouse release belongs to a tab
            # drag/reorder/tear-off gesture, not to a second activation.
            return
        self.raise_dock_widget(key)
        # Apply immediately so the newly selected dock appears in the same UI
        # turn instead of waiting for the next viewport resize/layout cycle.
        width, height = self._last_layout_size
        if width > 0 and height > 0:
            self.layout(width, height, force=True)
        entry = self._entries.get(key)
        window = entry.get("window") if entry is not None else None
        focus = getattr(window, "focus", None)
        if callable(focus):
            focus()

    def tab_order(self):
        """Return the current visible order of docked tabs."""
        return self.docked_keys()

    def reorder_dock_widget(self, key, index):
        """Move one docked tab to *index* while preserving floating entries.

        This is the dependency-free equivalent of QTabBar::moveTab. Floating
        docks keep their relative positions in the registry and are ignored by
        the visible tab sequence.
        """
        key = str(key)
        docked = list(self.docked_keys())
        if key not in docked:
            return False
        old_index = docked.index(key)
        docked.pop(old_index)
        index = max(0, min(int(index), len(docked)))
        docked.insert(index, key)
        if docked == list(self.docked_keys()):
            return False

        iterator = iter(docked)
        reordered = OrderedDict()
        for old_key, entry in self._entries.items():
            if bool(entry.get("floating")):
                reordered[old_key] = entry
            else:
                replacement = next(iterator)
                reordered[replacement] = self._entries[replacement]
        self._entries = reordered
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        callback = self.on_tab_order_changed
        if callable(callback):
            callback(tuple(docked))
        return True

    move_tab = reorder_dock_widget

    @staticmethod
    def _distance(a, b):
        if a is None or b is None:
            return 0.0
        try:
            dx = float(a[0]) - float(b[0])
            dy = float(a[1]) - float(b[1])
            return (dx * dx + dy * dy) ** 0.5
        except Exception:
            return 0.0

    @staticmethod
    def _frame_count():
        try:
            return int(dpg.get_frame_count())
        except Exception:
            return 0

    @staticmethod
    def _mouse_position():
        try:
            return tuple(map(float, dpg.get_mouse_pos(local=False)))
        except Exception:
            return None

    @staticmethod
    def _left_mouse_down():
        try:
            return bool(dpg.is_mouse_button_down(dpg.mvMouseButton_Left))
        except Exception:
            return False

    def _hovered_tab_key(self):
        for key, button in tuple(self._tab_buttons.items()):
            try:
                if dpg.does_item_exist(button) and dpg.is_item_hovered(button):
                    return key
            except Exception:
                continue
        return None

    def _tab_strip_rect(self):
        try:
            x, y = map(float, dpg.get_item_rect_min(self.tab_strip))
            w, h = map(float, dpg.get_item_rect_size(self.tab_strip))
            if w > 0.0 and h > 0.0:
                return x, y, w, h
        except Exception:
            pass
        return None

    def _tab_button_rect(self, key):
        button = self._tab_buttons.get(str(key))
        if button is None:
            return None
        try:
            x, y = map(float, dpg.get_item_rect_min(button))
            w, h = map(float, dpg.get_item_rect_size(button))
            if w > 0.0 and h > 0.0:
                return x, y, w, h
        except Exception:
            pass
        return None

    def _pointer_outside_tab_strip(self, mouse):
        rect = self._tab_strip_rect()
        if mouse is None or rect is None:
            return False
        mx, my = mouse
        x, y, w, h = rect
        margin = float(self.TAB_TEAROFF_DISTANCE)
        return (mx < x - margin or mx > x + w + margin
                or my < y - margin or my > y + h + margin)

    def _tab_insert_index_at(self, mouse, drag_key):
        """Return insertion index among docked tabs excluding *drag_key*."""
        if mouse is None:
            return None
        mx = float(mouse[0])
        remaining = [key for key in self.docked_keys() if key != drag_key]
        index = 0
        for key in remaining:
            rect = self._tab_button_rect(key)
            if rect is None:
                continue
            x, _y, w, _h = rect
            if mx < x + w * 0.5:
                return index
            index += 1
        return index

    def _show_insert_marker(self, index, drag_key):
        strip = self._tab_strip_rect()
        if strip is None:
            return
        sx, sy, sw, sh = strip
        remaining = [key for key in self.docked_keys() if key != drag_key]
        x = 1.0
        if remaining:
            index = max(0, min(int(index), len(remaining)))
            if index < len(remaining):
                rect = self._tab_button_rect(remaining[index])
                if rect is not None:
                    x = rect[0] - sx
            else:
                rect = self._tab_button_rect(remaining[-1])
                if rect is not None:
                    x = rect[0] + rect[2] - sx
        x = max(1.0, min(float(sw) - 1.0, float(x)))
        try:
            dpg.configure_item(
                self._tab_drag_overlay, width=max(1, int(sw)),
                height=max(1, int(sh)))
            dpg.configure_item(
                self._tab_insert_marker,
                p1=(x, 2), p2=(x, max(3.0, sh - 2.0)), show=True)
        except Exception:
            pass

    def _hide_insert_marker(self):
        try:
            if dpg.does_item_exist(self._tab_insert_marker):
                dpg.configure_item(self._tab_insert_marker, show=False)
        except Exception:
            pass

    def _begin_tab_drag(self, key, mouse):
        self._tab_drag_key = str(key)
        self._tab_drag_started = True
        self._tab_drag_insert_index = self._tab_insert_index_at(
            mouse, self._tab_drag_key)
        self._suppress_click_key = self._tab_drag_key
        self._suppress_click_until_frame = self._frame_count() + 3
        acquire_pointer_input(self._tab_drag_owner)
        self.raise_dock_widget(self._tab_drag_key)
        if self._tab_drag_insert_index is not None:
            self._show_insert_marker(
                self._tab_drag_insert_index, self._tab_drag_key)

    def _reset_tab_drag(self, *, release_capture=True):
        if release_capture:
            release_pointer_input(self._tab_drag_owner)
        self._hide_insert_marker()
        self._tab_press_key = None
        self._tab_press_pos = None
        self._tab_drag_key = None
        self._tab_drag_started = False
        self._tab_drag_insert_index = None

    def update_interaction(self):
        """Poll QTabBar-like reorder and tear-off gestures once per frame.

        Dear PyGui does not provide native draggable tabs. Polling is kept in
        the reusable DockManager so every future tabified dock group inherits
        identical behaviour instead of duplicating mouse state in the host.
        """
        docked = self.docked_keys()
        down = self._left_mouse_down()
        frame = self._frame_count()
        if (self._suppress_click_key is not None
                and frame > self._suppress_click_until_frame
                and not down):
            self._suppress_click_key = None
            self._suppress_click_until_frame = -1
        if len(docked) <= 1 or not dpg.does_item_exist(self.tab_strip):
            if self._tab_drag_started or self._tab_press_key is not None:
                self._reset_tab_drag()
            self._tab_mouse_was_down = down
            return

        mouse = self._mouse_position()

        # First down frame over a tab: remember the potential click/drag.
        if down and not self._tab_mouse_was_down:
            key = self._hovered_tab_key()
            if key is not None:
                self._tab_press_key = key
                self._tab_press_pos = mouse

        # Promote the pending click to an exclusive drag after a small movement.
        if (down and self._tab_press_key is not None
                and not self._tab_drag_started
                and self._distance(mouse, self._tab_press_pos)
                >= float(self.TAB_DRAG_START_DISTANCE)):
            self._begin_tab_drag(self._tab_press_key, mouse)

        if down and self._tab_drag_started and self._tab_drag_key is not None:
            # Leaving the tab strip by a Qt-like threshold tears this one dock
            # out while other tabs remain docked.
            if self._pointer_outside_tab_strip(mouse):
                key = self._tab_drag_key
                button_rect = self._tab_button_rect(key)
                if button_rect is not None and mouse is not None:
                    drag_anchor = (
                        max(0.0, mouse[0] - button_rect[0]),
                        max(0.0, mouse[1] - button_rect[1]),
                    )
                else:
                    drag_anchor = (40.0, 10.0)
                callback = self.on_tab_tearoff
                self._reset_tab_drag()
                # Keep the stale button click suppressed until the physical
                # release callback from Dear PyGui has been drained.
                self._suppress_click_key = key
                self._suppress_click_until_frame = frame + 3
                if callable(callback) and mouse is not None:
                    callback(key, mouse, drag_anchor)
                self._tab_mouse_was_down = down
                return

            index = self._tab_insert_index_at(mouse, self._tab_drag_key)
            if index is not None:
                self._tab_drag_insert_index = index
                self._show_insert_marker(index, self._tab_drag_key)

        if (not down and self._tab_mouse_was_down
                and self._tab_drag_started and self._tab_drag_key is not None):
            key = self._tab_drag_key
            index = self._tab_drag_insert_index
            self._reset_tab_drag()
            self._suppress_click_key = key
            self._suppress_click_until_frame = frame + 2
            if index is not None:
                self.reorder_dock_widget(key, index)
                width, height = self._last_layout_size
                if width > 0 and height > 0:
                    self.layout(width, height, force=True)
        elif not down and self._tab_press_key is not None:
            # It stayed below the drag threshold: leave activation to the
            # normal button callback and just clear pending drag state.
            self._tab_press_key = None
            self._tab_press_pos = None

        self._tab_mouse_was_down = down

    def _rebuild_tabs(self, width):
        try:
            dpg.delete_item(self.tab_group, children_only=True)
        except Exception:
            pass
        self._tab_buttons.clear()
        docked = self.docked_keys()
        if len(docked) <= 1:
            self._tabs_dirty = False
            return

        usable = max(1, int(width) - max(0, len(docked) - 1) * self.TAB_GAP)
        tab_width = max(
            self.TAB_MIN_WIDTH,
            min(self.TAB_MAX_WIDTH, int(usable / max(1, len(docked)))))
        max_chars = max(6, int((tab_width - 2 * self.TAB_PADDING_X) / 7))

        for key in docked:
            entry = self._entries[key]
            label = self._elide(entry.get("title") or key, max_chars)
            button = dpg.add_button(
                parent=self.tab_group,
                label=label,
                width=tab_width,
                height=self.TAB_HEIGHT - 2,
                callback=self._tab_clicked,
                user_data=key,
            )
            self._tab_buttons[key] = button
            dpg.bind_item_theme(
                button,
                self._active_tab_theme
                if key == self._active_key else self._inactive_tab_theme)
            full_title = str(entry.get("title") or key)
            if full_title != label:
                add_styled_tooltip(button, full_title)
        self._tabs_dirty = False
        self._last_tab_width = int(width)

    def layout(self, width, height, force=False):
        """Lay out the active dock plus a Qt-like tab bar when needed."""
        width = max(1, int(width))
        height = max(1, int(height))
        if (not force and self._last_layout_size == (width, height)
                and not self._tabs_dirty):
            return
        self._last_layout_size = (width, height)
        active = self._ensure_active()
        docked = self.docked_keys()
        tabified = len(docked) > 1
        tab_h = min(self.TAB_HEIGHT, max(1, height - 1)) if tabified else 0
        content_h = max(1, height - tab_h)

        if tabified:
            tab_y = 0 if self.tab_position == "top" else content_h
            content_y = tab_h if self.tab_position == "top" else 0
            dpg.configure_item(
                self.tab_strip,
                pos=(0, tab_y), width=width, height=tab_h, show=True)
            try:
                dpg.configure_item(
                    self._tab_drag_overlay, pos=(0, 0), width=width, height=tab_h)
            except Exception:
                pass
            if self._tabs_dirty or int(width) != self._last_tab_width:
                # Re-elide/rebalance labels only when the tab membership,
                # active tab or available width actually changed.
                self._rebuild_tabs(width)
        else:
            content_y = 0
            dpg.configure_item(self.tab_strip, show=False)

        for key, entry in self._entries.items():
            if bool(entry.get("floating")):
                continue
            window = entry.get("window")
            root = getattr(window, "root", None)
            if root is None or not dpg.does_item_exist(root):
                continue
            is_active = key == active
            dpg.configure_item(root, show=is_active)
            if not is_active:
                continue
            dpg.configure_item(
                root, pos=(0, content_y), width=width, height=content_h)
            resize = getattr(window, "resize", None)
            if callable(resize):
                resize(width, content_h)

    def save_state(self):
        """Return a JSON-serializable equivalent of lightweight QMainWindow state."""
        return {
            "dock_area": self.dock_area,
            "active": self._active_key,
            "order": list(self._entries),
            "floating": [
                key for key, entry in self._entries.items()
                if bool(entry.get("floating"))
            ],
        }

    def restore_state(self, state):
        """Restore order/active/floating flags for already registered docks."""
        state = dict(state or {})
        order = [str(key) for key in state.get("order") or ()]
        if order:
            reordered = OrderedDict()
            for key in order:
                if key in self._entries:
                    reordered[key] = self._entries[key]
            for key, entry in self._entries.items():
                if key not in reordered:
                    reordered[key] = entry
            self._entries = reordered
        self.dock_area = self._normalize_area(
            state.get("dock_area") or self.dock_area)
        floating = {str(key) for key in state.get("floating") or ()}
        for key, entry in self._entries.items():
            entry["floating"] = key in floating
            entry["area"] = self.dock_area
        active = str(state.get("active") or "")
        self._active_key = active if active in self.docked_keys() else None
        self._ensure_active(notify=True)
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        return True

    def close(self):
        self._reset_tab_drag()
        self._entries.clear()
        self._active_key = None
        self._last_tab_width = 0
        if dpg.does_item_exist(self.tab_strip):
            try:
                dpg.delete_item(self.tab_strip)
            except Exception:
                pass
