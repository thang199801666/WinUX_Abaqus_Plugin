"""QMainWindow-like dock orchestration for Dear PyGui.

``DockWidget`` owns the chrome and behaviour of one tool panel.  ``DockManager``
owns the relationship between several docks that share one dock area: active
selection, tabification, tab-strip layout, floating state and lightweight state
serialization.  Keeping this separate from :mod:`view` prevents every future
host tool from re-implementing QMainWindow-style bookkeeping.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Callable, Dict, Iterable, Optional

from ..backends import dpg

from ..input_gate import (
    acquire_pointer_input, register_pointer_protected_item,
    release_pointer_input, unregister_pointer_protected_item,
)
from ..gui.palette import QtFusionMetrics, QtFusionPalette
from ..tooltip import add_styled_tooltip
from .dock_widget import DockDropPreview
from .layout_tree import DockLayoutTree


class DockManager:
    """Manage a QMainWindow-like split/tab tree of ``DockWidget`` instances.

    A host window may expose one or more shared dock sites around a central view.
    Dock leaves can be tabified or recursively split, and r69 gives every visible
    split boundary a protected draggable handle. Floating docks remain registered
    but are excluded from the embedded dock layout.

    The class intentionally works with small duck-typed window objects.  A
    managed window only needs ``root``, ``resize(width, height)``, ``set_dock_area``
    and ``dock_mode`` attributes, which keeps the manager reusable for future
    tools beyond Job Plots.
    """

    # QMainWindow::DockOption-compatible flags.  DockManager remains a small
    # retained-mode host rather than a full QMainWindow layout tree, but the
    # familiar policy API lets applications configure tabbing/nesting behavior
    # without reaching into DearUIQt internals.
    AnimatedDocks = 0x01
    AllowNestedDocks = 0x02
    AllowTabbedDocks = 0x04
    ForceTabbedDocks = 0x08
    VerticalTabs = 0x10
    GroupedDragging = 0x20
    DefaultDockOptions = AnimatedDocks | AllowTabbedDocks

    # Dependency-free counterparts of Qt::DockWidgetArea flags, used by
    # setTabPosition()/tabPosition().
    LeftDockWidgetArea = 0x01
    RightDockWidgetArea = 0x02
    TopDockWidgetArea = 0x04
    BottomDockWidgetArea = 0x08
    AllDockWidgetAreas = (
        LeftDockWidgetArea | RightDockWidgetArea
        | TopDockWidgetArea | BottomDockWidgetArea)
    _AREA_FLAGS = {
        "left": LeftDockWidgetArea, "right": RightDockWidgetArea,
        "top": TopDockWidgetArea, "bottom": BottomDockWidgetArea,
    }

    TAB_HEIGHT = 24
    TAB_MIN_WIDTH = 88
    TAB_MAX_WIDTH = 220
    TAB_GAP = 0
    TAB_PADDING_X = 9
    TAB_DRAG_START_DISTANCE = 4
    TAB_TEAROFF_DISTANCE = 18
    TAB_INSERT_MARKER_WIDTH = 2

    # Internal QSplitter-like dock separators. A 1 px visual line plus a wider
    # transparent hit target mirrors Qt's native splitter ergonomics while
    # keeping dock chrome visually light.
    SPLIT_HANDLE_WIDTH = 1
    SPLIT_HANDLE_HIT_WIDTH = 9
    SPLIT_MIN_EXTENT = 72

    # QMainWindow-like live docking feedback.  Edge zones intentionally occupy
    # less than half of a leaf so the centre remains an easy tabification target.
    DOCK_DROP_EDGE_FRACTION = 0.24
    DOCK_DROP_EDGE_MIN = 36
    DOCK_DROP_EDGE_MAX = 96
    DOCK_DROP_PARENT_MARGIN = 12

    BG = QtFusionPalette.TITLE
    BORDER = QtFusionPalette.BORDER
    ACTIVE_BG = QtFusionPalette.BASE
    ACTIVE_HOVER = QtFusionPalette.WINDOW_ALT
    INACTIVE_BG = QtFusionPalette.WINDOW
    INACTIVE_HOVER = QtFusionPalette.BUTTON_HOVER
    TEXT = QtFusionPalette.TEXT
    ACCENT = QtFusionPalette.HIGHLIGHT
    SPLIT_COLOR = QtFusionPalette.BORDER_LIGHT

    def __init__(
            self,
            parent,
            *,
            dock_area: str = "right",
            tab_position: str = "bottom",
            dock_options: Optional[int] = None,
            on_active_changed: Optional[Callable[[Optional[str]], None]] = None,
            on_tab_tearoff: Optional[Callable[[str, tuple, tuple], None]] = None,
            on_tab_order_changed: Optional[Callable[[tuple], None]] = None):
        self.parent = parent
        self.dock_area = self._normalize_area(dock_area)
        self.tab_position = (
            "top" if str(tab_position or "bottom").strip().lower() == "top"
            else "bottom")
        self._dock_options = int(
            self.DefaultDockOptions if dock_options is None else dock_options)
        if self._dock_options & self.VerticalTabs:
            self._dock_options |= self.AllowTabbedDocks
        if self._dock_options & self.GroupedDragging:
            self._dock_options |= self.AllowTabbedDocks
        self._document_mode = False
        self._tab_positions = {
            area: self.tab_position for area in ("left", "right", "top", "bottom")
        }
        self.on_active_changed = on_active_changed
        self.on_tab_tearoff = on_tab_tearoff
        self.on_tab_order_changed = on_tab_order_changed
        self._entries: "OrderedDict[str, Dict[str, object]]" = OrderedDict()
        self._layout_tree = DockLayoutTree()
        # State for docks created after restore_state(), mirroring
        # QMainWindow::restoreDockWidget. Entries are keyed by objectName.
        self._pending_restore: Dict[str, Dict[str, object]] = {}
        self._pending_active_identity: Optional[str] = None
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
        self._tab_drag_outside = False
        self._tab_drag_owner = object()
        self._suppress_click_key: Optional[str] = None
        self._suppress_click_until_frame = -1

        # r71: a standalone dock (one dock in a layout leaf) can be dragged
        # directly from its QDockWidget title bar.  Qt normally removes the
        # embedded title bar when docks are tabified, so DearUIQt deliberately
        # enables this gesture only for single-dock leaves; tabified docks keep
        # using the QTabBar drag path above.
        self._title_press_key: Optional[str] = None
        self._title_press_pos = None
        self._title_drag_key: Optional[str] = None
        self._title_drag_started = False
        self._title_drag_owner = object()
        # r72: GroupedDragging promotes a title drag to the entire source tab
        # leaf. Tab drags intentionally remain single-dock gestures, matching
        # QMainWindow::GroupedDragging semantics.
        self._title_drag_group_keys = ()
        self._title_drag_grouped = False
        self._title_drag_outside = False

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
        # r68: one DockManager may now render several independent tab groups
        # inside a recursive split tree. Keep the original strip as the first
        # view for source/binary compatibility and allocate secondary strips
        # only when a split actually contains another tab group.
        self._tab_views: Dict[str, Dict[str, object]] = {}
        self._legacy_tab_group_id = None
        self._legacy_tab_view = {
            "strip": self.tab_strip,
            "group": self.tab_group,
            "overlay": self._tab_drag_overlay,
            "marker": self._tab_insert_marker,
            "buttons": {},
            "width": 0,
            "keys": (),
            "active": None,
        }
        self._tab_key_to_group: Dict[str, str] = {}

        # r69: recursive split nodes expose native-feeling draggable separators.
        # Views are created lazily so the hit targets sit above dock contents in
        # Dear PyGui z-order, and every hit target is input-protected to prevent
        # Explorer/list controls underneath from receiving the same press.
        self._split_handle_views: Dict[str, Dict[str, object]] = {}
        self._split_handles: Dict[str, Dict[str, object]] = {}
        self._split_hover_id: Optional[str] = None
        self._split_drag_id: Optional[str] = None
        self._split_drag_owner = object()
        self._split_drag_start_mouse = None
        self._split_drag_start_sizes = None
        self._split_drag_restore_state = None

        # r70: dragging a tab over another dock leaf paints viewport-front
        # QMainWindow-style feedback.  The preview is visual-only; pointer
        # ownership remains with the tab drag until release or tear-off.
        self._drop_preview = DockDropPreview(
            tag="dearuiqt_dock_drop_preview_{}".format(id(self)))
        self._tab_drop_target = None
        self._last_layout_groups = ()

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
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, QtFusionMetrics.BUTTON_ROUNDING)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, self.TAB_PADDING_X, 2)

        with dpg.theme() as self._inactive_tab_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, self.INACTIVE_BG)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, self.INACTIVE_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, self.ACTIVE_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_Text, self.TEXT)
                dpg.add_theme_color(dpg.mvThemeCol_Border, QtFusionPalette.BORDER_LIGHT)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, QtFusionMetrics.BUTTON_ROUNDING)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, self.TAB_PADDING_X, 2)

        with dpg.theme() as self._split_handle_theme:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)

    # ------------------------------------------------------------------
    # QMainWindow-compatible docking policy API
    # ------------------------------------------------------------------
    def dockOptions(self):
        return int(self._dock_options)

    def setDockOptions(self, options):
        options = int(options)
        if options == int(self._dock_options):
            return False
        self._dock_options = options
        # Qt's VerticalTabs and GroupedDragging options imply AllowTabbedDocks.
        if self._dock_options & self.VerticalTabs:
            self._dock_options |= self.AllowTabbedDocks
        if self._dock_options & self.GroupedDragging:
            self._dock_options |= self.AllowTabbedDocks
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        return True

    def groupedDraggingEnabled(self):
        return bool(self._dock_options & self.GroupedDragging)

    def isAnimated(self):
        return bool(self._dock_options & self.AnimatedDocks)

    def setAnimated(self, enabled):
        options = int(self._dock_options)
        if enabled:
            options |= self.AnimatedDocks
        else:
            options &= ~self.AnimatedDocks
        return self.setDockOptions(options)

    def isDockNestingEnabled(self):
        return bool(self._dock_options & self.AllowNestedDocks)

    def setDockNestingEnabled(self, enabled):
        options = int(self._dock_options)
        if enabled:
            options |= self.AllowNestedDocks
        else:
            options &= ~self.AllowNestedDocks
        return self.setDockOptions(options)

    def documentMode(self):
        return bool(self._document_mode)

    def setDocumentMode(self, enabled):
        enabled = bool(enabled)
        changed = enabled != self._document_mode
        self._document_mode = enabled
        if changed:
            self._tabs_dirty = True
        return changed

    @classmethod
    def _areas_from_mask(cls, areas):
        if isinstance(areas, str):
            area = cls._normalize_area(areas)
            return (area,)
        if isinstance(areas, (tuple, list, set, frozenset)):
            return tuple(dict.fromkeys(cls._normalize_area(area) for area in areas))
        try:
            mask = int(areas)
        except Exception:
            return ()
        return tuple(
            area for area, flag in cls._AREA_FLAGS.items() if mask & int(flag))

    def setTabPosition(self, areas, tab_position):
        """Set the tab edge for one or more dock areas, Qt-style.

        DearUIQt's retained tab renderer currently supports North/South for
        horizontal strips.  West/East are accepted and normalized to North/
        South unless VerticalTabs is enabled, keeping the API stable for a
        future rotated-tab renderer.
        """
        raw = str(tab_position or "bottom").strip().lower()
        aliases = {
            "north": "top", "top": "top", "west": "top",
            "south": "bottom", "bottom": "bottom", "east": "bottom",
        }
        position = aliases.get(raw, "bottom")
        targets = self._areas_from_mask(areas)
        if not targets:
            return False
        changed = False
        for area in targets:
            if self._tab_positions.get(area) != position:
                self._tab_positions[area] = position
                changed = True
        current = self._normalize_area(self.dock_area)
        self.tab_position = self._tab_positions.get(current, self.tab_position)
        if changed:
            self._tabs_dirty = True
            self._last_layout_size = (0, 0)
        return changed

    def tabPosition(self, area):
        area = self._normalize_area(area)
        return self._tab_positions.get(area, self.tab_position)

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

    @staticmethod
    def _window_requested_visible(window):
        getter = getattr(window, "isVisible", None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:
                pass
        return True

    @classmethod
    def _window_user_movable(cls, window):
        """Return whether the dock may be repositioned by a pointer gesture."""
        dock = cls._dock_interface(window)
        movable = getattr(dock, "movable", None)
        if callable(movable):
            try:
                return bool(movable())
            except Exception:
                pass
        if movable is not None:
            try:
                return bool(movable)
            except Exception:
                pass
        features = getattr(dock, "features", None)
        try:
            value = features() if callable(features) else features
            if value is not None:
                flag = int(getattr(dock, "DockWidgetMovable", 0x02))
                return bool(int(value) & flag)
        except Exception:
            pass
        return True

    @classmethod
    def _window_user_floatable(cls, window):
        """Return whether a pointer drag may detach *window* from the dock site.

        Qt treats ``DockWidgetMovable`` and ``DockWidgetFloatable`` as separate
        permissions: a movable/non-floatable dock may still be rearranged inside
        QMainWindow, but leaving the dock site must not turn it into a top-level
        window.
        """
        dock = cls._dock_interface(window)
        floatable = getattr(dock, "floatable", None)
        if callable(floatable):
            try:
                return bool(floatable())
            except Exception:
                pass
        if floatable is not None:
            try:
                return bool(floatable)
            except Exception:
                pass
        features = getattr(dock, "features", None)
        try:
            value = features() if callable(features) else features
            if value is not None:
                flag = int(getattr(dock, "DockWidgetFloatable", 0x04))
                return bool(int(value) & flag)
        except Exception:
            pass
        return True

    @staticmethod
    def _dock_interface(window):
        """Return the QDockWidget-like object behind an optional host adapter."""
        dock = getattr(window, "dock", None)
        return dock if dock is not None else window

    def _resolve_key(self, dock_or_key):
        """Resolve a registry key from either the key or a dock/host object."""
        if isinstance(dock_or_key, (str, int)):
            key = str(dock_or_key)
            return key if key in self._entries else None
        for key, entry in self._entries.items():
            window = entry.get("window")
            if dock_or_key is window or dock_or_key is self._dock_interface(window):
                return key
        return None

    @classmethod
    def _dock_identity(cls, key, window):
        dock = cls._dock_interface(window)
        getter = getattr(dock, "objectName", None)
        if callable(getter):
            try:
                name = str(getter() or "")
                if name:
                    return name
            except Exception:
                pass
        tag = str(getattr(dock, "tag", "") or "")
        return tag or str(key)

    @classmethod
    def _area_allowed(cls, window, area):
        dock = cls._dock_interface(window)
        for name in ("isAreaAllowed", "is_area_allowed"):
            checker = getattr(dock, name, None)
            if callable(checker):
                try:
                    return bool(checker(area))
                except Exception:
                    return False
        return True

    @classmethod
    def _coerce_allowed_area(cls, window, area, fallback="right"):
        requested = cls._normalize_area(area)
        if cls._area_allowed(window, requested):
            return requested
        dock = cls._dock_interface(window)
        current = getattr(dock, "dock_area", None)
        if current is not None:
            current = cls._normalize_area(current)
            if cls._area_allowed(window, current):
                return current
        for candidate in (fallback, "right", "left", "bottom", "top"):
            candidate = cls._normalize_area(candidate)
            if cls._area_allowed(window, candidate):
                return candidate
        return None

    @classmethod
    def _apply_window_area(cls, window, area):
        setter = getattr(window, "set_dock_area", None)
        if callable(setter):
            try:
                setter(area)
                return
            except Exception:
                pass
        dock = cls._dock_interface(window)
        setter = getattr(dock, "set_dock_area", None)
        if callable(setter):
            try:
                setter(area)
            except Exception:
                pass

    @classmethod
    def _apply_window_floating(cls, window, floating):
        dock = cls._dock_interface(window)
        setter = getattr(dock, "set_floating", None)
        if callable(setter):
            try:
                setter(bool(floating))
            except Exception:
                pass

    @classmethod
    def _apply_window_visible(cls, window, visible):
        dock = cls._dock_interface(window)
        setter = getattr(dock, "set_visible", None)
        if callable(setter):
            try:
                setter(bool(visible), notify=False)
                return
            except TypeError:
                try:
                    setter(bool(visible))
                    return
                except Exception:
                    pass
            except Exception:
                pass

    def _apply_restored_entry(self, key, saved):
        entry = self._entries.get(str(key))
        if entry is None:
            return False
        window = entry.get("window")
        area = self._coerce_allowed_area(
            window, saved.get("area") or entry.get("area") or self.dock_area,
            fallback=self.dock_area)
        if area is not None:
            entry["area"] = area
            current_layout_area = self._layout_tree.area_of(str(key))
            if current_layout_area is not None and current_layout_area != area:
                self._layout_tree.move_to_area(str(key), area, activate=False)
            self._apply_window_area(window, area)
        floating = bool(saved.get("floating", entry.get("floating", False)))
        visible = bool(saved.get("visible", self._window_requested_visible(window)))
        entry["floating"] = floating
        self._apply_window_floating(window, floating)
        self._apply_window_visible(window, visible)
        return True

    def visible_docked_keys(self):
        ordered = []
        for key in self._layout_tree.flatten_keys():
            entry = self._entries.get(key)
            if entry is None or bool(entry.get("floating")):
                continue
            if self._window_requested_visible(entry.get("window")):
                ordered.append(key)
        for key, entry in self._entries.items():
            if key in ordered or bool(entry.get("floating")):
                continue
            if self._window_requested_visible(entry.get("window")):
                ordered.append(key)
        return tuple(ordered)

    def has_docked(self):
        return bool(self.visible_docked_keys())

    def is_registered(self, key):
        return str(key) in self._entries

    def add_dock_widget(self, key, window, title=None, area=None, activate=True):
        """Register a dock and, by default, add it to the area's tab group.

        ``splitDockWidget()`` is the explicit way to create a neighboring split;
        this preserves DearUIQt's historical add behaviour while allowing the
        manager to own a real recursive dock topology.
        """
        key = str(key)
        area = self._coerce_allowed_area(
            window, area or self.dock_area, fallback=self.dock_area)
        if area is None:
            return False
        existing = self._entries.get(key)
        is_new = existing is None
        if is_new:
            self._entries[key] = {
                "window": window,
                "title": str(title or getattr(window, "label", key)),
                "area": area,
                "floating": str(getattr(window, "dock_mode", "docked")).lower()
                == "floating",
            }
            self._layout_tree.add_tab(key, area, activate=activate)
        else:
            existing.update(
                window=window,
                title=str(title or existing.get("title") or key),
                area=area,
            )
            if not self._layout_tree.contains(key):
                self._layout_tree.add_tab(key, area, activate=activate)
            elif self._layout_tree.area_of(key) != area:
                self._layout_tree.move_to_area(key, area, activate=activate)
        self.dock_area = area
        self._apply_window_area(window, area)
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
        self._layout_tree.remove(key)
        if self._active_key == key:
            self._active_key = None
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        self._ensure_active(notify=True)
        return True

    unregister_dock = remove_dock_widget
    addDockWidget = add_dock_widget
    removeDockWidget = remove_dock_widget

    def dock_widget_area(self, key):
        key = str(key)
        entry = self._entries.get(key)
        if entry is None:
            return None
        area = self._layout_tree.area_of(key)
        return self._normalize_area(area or entry.get("area") or self.dock_area)

    dockWidgetArea = dock_widget_area

    def tabified_dock_widgets(self, key):
        key = str(key)
        entry = self._entries.get(key)
        if entry is None or bool(entry.get("floating")):
            return ()
        return tuple(
            other for other in self._layout_tree.tabified(key)
            if other in self._entries and not bool(self._entries[other].get("floating")))

    tabifiedDockWidgets = tabified_dock_widgets

    def restore_dock_widget(self, key):
        # Accept the registered key (legacy DearUIQt) or a dock/host object.
        # Late state restoration remains equivalent to
        # ``QMainWindow::restoreDockWidget`` for docks created after restoreState.
        resolved = self._resolve_key(key)
        if resolved is None:
            return False
        key = resolved
        entry = self._entries.get(key)
        if entry is None:
            return False
        window = entry.get("window")
        identity = self._dock_identity(key, window)
        pending = self._pending_restore.pop(identity, None)
        if pending is not None:
            # Format-3 layout state keeps late objectNames as placeholder leaves
            # in the recursive tree. Replace the temporary addDockWidget slot
            # with that persisted slot when restoreDockWidget() is requested.
            if identity != key and self._layout_tree.contains(identity):
                self._layout_tree.remove(key)
                self._layout_tree.rename(identity, key)
            self._apply_restored_entry(key, pending)
            self._tabs_dirty = True
            self._last_layout_size = (0, 0)
            if identity == self._pending_active_identity:
                self._pending_active_identity = None
                self.raise_dock_widget(key)
            else:
                self._ensure_active(notify=True)
            return True
        setter = getattr(window, "setVisible", None)
        if callable(setter):
            setter(True)
        self.set_floating(key, False)
        self.raise_dock_widget(key)
        return True

    restoreDockWidget = restore_dock_widget

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

        # WinUx historically moves an entire tab group with group=True.  When
        # every target belongs to one area and the destination is empty, move
        # the recursive root intact so nested split ratios are not flattened.
        if group and targets:
            source_areas = {
                self._layout_tree.area_of(target)
                for target in targets if self._layout_tree.area_of(target) is not None
            }
            all_allowed = all(
                self._area_allowed(self._entries[target].get("window"), area)
                for target in targets if target in self._entries)
            if len(source_areas) == 1 and all_allowed:
                source_area = next(iter(source_areas))
                if source_area == area or self._layout_tree.move_area_root(source_area, area):
                    changed = source_area != area
                    for target in targets:
                        entry = self._entries.get(target)
                        if entry is None:
                            continue
                        if entry.get("area") != area:
                            changed = True
                        entry["area"] = area
                        self._apply_window_area(entry.get("window"), area)
                    self.dock_area = area
                    self.tab_position = self._tab_positions.get(area, self.tab_position)
                    self._tabs_dirty = True
                    self._last_layout_size = (0, 0)
                    return changed or bool(targets)

        changed = False
        for target in targets:
            entry = self._entries.get(target)
            if entry is None:
                continue
            window = entry.get("window")
            allowed_area = self._coerce_allowed_area(
                window, area, fallback=entry.get("area") or self.dock_area)
            # QMainWindow must not force a QDockWidget into a disallowed area.
            if allowed_area is None or allowed_area != area:
                continue
            if entry.get("area") != area or self._layout_tree.area_of(target) != area:
                changed = True
            entry["area"] = area
            self._layout_tree.move_to_area(
                target, area, activate=(target == self._active_key))
            self._apply_window_area(window, area)
        if changed or self.dock_area == area:
            self.dock_area = area
            self.tab_position = self._tab_positions.get(area, self.tab_position)
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        return changed or any(
            self._normalize_area(self._entries[target].get("area")) == area
            for target in targets if target in self._entries)

    def tabify_dock_widget(self, first, second):
        """Stack *second* on top of *first* in one QTabBar-like dock group."""
        first = self._resolve_key(first)
        second = self._resolve_key(second)
        if first is None or second is None or first == second:
            return False
        if first not in self._entries or second not in self._entries:
            return False
        area = self._normalize_area(
            self._layout_tree.area_of(first) or self._entries[first].get("area"))
        if not self._area_allowed(self._entries[second].get("window"), area):
            return False
        self._entries[second]["area"] = area
        self._apply_window_area(self._entries[second].get("window"), area)
        self.set_floating(second, False)
        if not self._layout_tree.tabify(first, second):
            return False
        self.dock_area = area
        self.tab_position = self._tab_positions.get(area, self.tab_position)
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        self.raise_dock_widget(second)
        return True

    tabifyDockWidget = tabify_dock_widget

    def split_dock_widget(self, first, second, orientation):
        """Split *first* and place *second* beside/below it, Qt-style.

        ``Qt.Horizontal`` (1) places the second dock to the right; ``Qt.Vertical``
        (2) places it below.  When *first* is already tabified, Qt specifies
        that *second* becomes another tab instead of a neighboring split.
        """
        first = self._resolve_key(first)
        second = self._resolve_key(second)
        if first is None or second is None or first == second:
            return False
        first_entry = self._entries.get(first)
        second_entry = self._entries.get(second)
        if first_entry is None or second_entry is None:
            return False
        if bool(first_entry.get("floating")):
            return False
        area = self._normalize_area(
            self._layout_tree.area_of(first) or first_entry.get("area") or self.dock_area)
        if not self._area_allowed(second_entry.get("window"), area):
            return False
        second_entry["area"] = area
        self._apply_window_area(second_entry.get("window"), area)
        self.set_floating(second, False)
        result = self._layout_tree.split(first, second, orientation)
        if not result:
            return False
        self.dock_area = area
        self.tab_position = self._tab_positions.get(area, self.tab_position)
        self._active_key = second
        self._layout_tree.set_active(second)
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        self._notify_active_changed()
        return True

    splitDockWidget = split_dock_widget

    def dock_relative(self, target, moving, zone):
        """Apply an interactive left/right/top/bottom/center dock drop.

        Edge drops split the complete target leaf (including an existing tab
        group), while a centre drop tabifies the moving dock with that leaf.
        This is deliberately separate from ``splitDockWidget`` because Qt's
        programmatic split contract tabifies when *first* is already tabbed,
        whereas interactive edge docking visibly splits the tab group itself.
        """
        target = self._resolve_key(target)
        moving = self._resolve_key(moving)
        zone = str(zone or "center").strip().lower()
        if target is None or moving is None or target == moving:
            return False
        if zone not in ("left", "right", "top", "bottom", "center"):
            return False
        target_entry = self._entries.get(target)
        moving_entry = self._entries.get(moving)
        if target_entry is None or moving_entry is None:
            return False
        if bool(target_entry.get("floating")):
            return False
        area = self._normalize_area(
            self._layout_tree.area_of(target)
            or target_entry.get("area") or self.dock_area)
        if not self._area_allowed(moving_entry.get("window"), area):
            return False

        moving_entry["area"] = area
        moving_entry["floating"] = False
        self._apply_window_area(moving_entry.get("window"), area)
        self._apply_window_floating(moving_entry.get("window"), False)
        result = self._layout_tree.dock_relative(target, moving, zone)
        if not result:
            return False
        self.dock_area = area
        self.tab_position = self._tab_positions.get(area, self.tab_position)
        self._active_key = moving
        self._layout_tree.set_active(moving)
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        self._notify_active_changed()
        return True

    dockRelative = dock_relative

    def dock_group_relative(self, target, moving, zone):
        """Move the complete tab group containing *moving* as one dock unit.

        This is used only by QMainWindow::GroupedDragging title gestures. Tab
        drags continue to move one dock at a time. Every dock in the source
        group must accept the destination area before topology is mutated.
        """
        target = self._resolve_key(target)
        moving = self._resolve_key(moving)
        zone = str(zone or "center").strip().lower()
        if target is None or moving is None or target == moving:
            return False
        if zone not in ("left", "right", "top", "bottom", "center"):
            return False
        target_entry = self._entries.get(target)
        moving_entry = self._entries.get(moving)
        if target_entry is None or moving_entry is None:
            return False
        if bool(target_entry.get("floating")):
            return False
        source_keys = tuple(self._layout_tree.group_keys(moving))
        if not source_keys or target in source_keys:
            return False
        area = self._normalize_area(
            self._layout_tree.area_of(target)
            or target_entry.get("area") or self.dock_area)
        for key in source_keys:
            entry = self._entries.get(key)
            if entry is None or not self._area_allowed(entry.get("window"), area):
                return False

        result = self._layout_tree.dock_group_relative(target, moving, zone)
        if not result:
            return False
        for key in source_keys:
            entry = self._entries.get(key)
            if entry is None:
                continue
            entry["area"] = area
            entry["floating"] = False
            self._apply_window_area(entry.get("window"), area)
            self._apply_window_floating(entry.get("window"), False)
        self.dock_area = area
        self.tab_position = self._tab_positions.get(area, self.tab_position)
        self._active_key = moving
        self._layout_tree.set_active(moving)
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        self._notify_active_changed()
        return True

    dockGroupRelative = dock_group_relative

    def resize_docks(self, docks, sizes, orientation):
        """Resize sibling split docks using relative Qt-like size weights."""
        resolved = [self._resolve_key(dock) for dock in docks]
        if any(key is None for key in resolved):
            return False
        if not self._layout_tree.resize_docks(resolved, sizes, orientation):
            return False
        self._last_layout_size = (0, 0)
        return True

    resizeDocks = resize_docks

    def dock_layout_state(self):
        """Return a defensive snapshot of the dependency-free layout topology."""
        return self._layout_tree.to_state()

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
        """Activate one dock inside its tab group, like ``QDockWidget::raise``."""
        key = self._resolve_key(key)
        if key is None:
            return False
        entry = self._entries.get(key)
        if entry is None or bool(entry.get("floating")):
            return False
        changed = self._active_key != key
        self._active_key = key
        self._layout_tree.set_active(key)
        area = self._layout_tree.area_of(key)
        if area is not None:
            self.dock_area = self._normalize_area(area)
            self.tab_position = self._tab_positions.get(
                self.dock_area, self.tab_position)
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        if changed:
            self._notify_active_changed()
        return True

    activate = raise_dock_widget
    raiseDockWidget = raise_dock_widget

    def _ensure_active(self, notify=False):
        docked = self.visible_docked_keys()
        if self._active_key in docked:
            return self._active_key
        previous = self._active_key
        self._active_key = docked[-1] if docked else None
        if self._active_key is not None:
            self._layout_tree.set_active(self._active_key)
            area = self._layout_tree.area_of(self._active_key)
            if area is not None:
                self.dock_area = self._normalize_area(area)
                self.tab_position = self._tab_positions.get(
                    self.dock_area, self.tab_position)
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

    def _create_tab_view(self, group_id):
        strip = dpg.add_child_window(
            parent=self.parent,
            pos=(0, 0), width=1, height=self.TAB_HEIGHT,
            border=False, no_scrollbar=True, no_scroll_with_mouse=True,
            show=False,
        )
        dpg.bind_item_theme(strip, self._strip_theme)
        group = dpg.add_group(parent=strip, horizontal=True)
        overlay = dpg.add_drawlist(
            parent=strip, pos=(0, 0), width=1, height=self.TAB_HEIGHT)
        marker = dpg.draw_line(
            (0, 2), (0, self.TAB_HEIGHT - 2),
            color=self.ACCENT, thickness=self.TAB_INSERT_MARKER_WIDTH,
            show=False, parent=overlay)
        return {
            "strip": strip, "group": group, "overlay": overlay,
            "marker": marker, "buttons": {}, "width": 0,
            "keys": (), "active": None,
        }

    def _ensure_tab_view(self, group_id):
        group_id = str(group_id or "dock-tabs")
        view = self._tab_views.get(group_id)
        if view is not None:
            return view
        if self._legacy_tab_group_id is None:
            self._legacy_tab_group_id = group_id
            view = self._legacy_tab_view
        else:
            view = self._create_tab_view(group_id)
        self._tab_views[group_id] = view
        return view

    def _tab_view_for_key(self, key):
        group_id = self._tab_key_to_group.get(str(key))
        return self._tab_views.get(group_id) if group_id is not None else None

    def _hide_unused_tab_views(self, active_group_ids):
        active_group_ids = set(map(str, active_group_ids))
        for group_id, view in tuple(self._tab_views.items()):
            if group_id in active_group_ids:
                continue
            try:
                dpg.configure_item(view["strip"], show=False)
            except Exception:
                pass
            for key in tuple(view.get("buttons") or {}):
                self._tab_buttons.pop(key, None)
                self._tab_key_to_group.pop(key, None)
            view["buttons"] = {}
            view["keys"] = ()
            view["active"] = None

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
        """Return visible QTabBar order for the globally active dock group."""
        active = self._active_key
        group = self._layout_tree.group_keys(active) if active is not None else ()
        if not group:
            return self.visible_docked_keys()
        return tuple(
            key for key in group if key in self._entries
            and not bool(self._entries[key].get("floating"))
            and self._window_requested_visible(self._entries[key].get("window")))

    def reorder_dock_widget(self, key, index):
        """Move one tab within its current tabified dock group."""
        key = str(key)
        group_before = self._layout_tree.group_keys(key)
        if key not in group_before:
            return False
        visible_group = [candidate for candidate in group_before
                         if candidate in self._entries
                         and not bool(self._entries[candidate].get("floating"))
                         and self._window_requested_visible(
                             self._entries[candidate].get("window"))]
        if key not in visible_group:
            return False
        old_index = visible_group.index(key)
        index = max(0, min(int(index), len(visible_group) - 1))
        if old_index == index:
            return False

        # Translate the visible QTabBar slot back to the full group's index so
        # hidden tabs keep their relative positions, matching Qt tab groups.
        target_key = visible_group[index]
        full = list(group_before)
        full.remove(key)
        target_index = full.index(target_key) if target_key in full else len(full)
        if old_index < index:
            target_index += 1
        self._layout_tree.reorder_tab(key, target_index)

        # Preserve the legacy flat registry order for callers which iterate
        # keys while the actual topology lives in DockLayoutTree.
        flat = list(self._layout_tree.flatten_keys())
        reordered = OrderedDict()
        for candidate in flat:
            if candidate in self._entries:
                reordered[candidate] = self._entries[candidate]
        for candidate, entry in self._entries.items():
            if candidate not in reordered:
                reordered[candidate] = entry
        self._entries = reordered
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        callback = self.on_tab_order_changed
        if callable(callback):
            callback(tuple(self._layout_tree.group_keys(key)))
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

    @staticmethod
    def _escape_pressed():
        key = getattr(dpg, "mvKey_Escape", None)
        if key is None:
            return False
        try:
            return bool(dpg.is_key_pressed(key, repeat=False))
        except TypeError:
            try:
                return bool(dpg.is_key_pressed(key))
            except Exception:
                return False
        except Exception:
            return False

    @staticmethod
    def _split_handle_id(handle):
        path = tuple(handle.get("path") or ())
        path_text = ".".join(map(str, path)) if path else "root"
        return "{}:{}:{}-{}".format(
            handle.get("area") or "right", path_text,
            int(handle.get("before_index", 0)),
            int(handle.get("after_index", 1)))

    def _create_split_handle_view(self, handle_id):
        hitbox = dpg.add_child_window(
            parent=self.parent, pos=(0, 0), width=1, height=1,
            border=False, no_scrollbar=True, no_scroll_with_mouse=True,
            show=False)
        dpg.bind_item_theme(hitbox, self._split_handle_theme)
        register_pointer_protected_item(hitbox)
        overlay = dpg.add_drawlist(
            parent=hitbox, pos=(0, 0), width=1, height=1)
        line = dpg.draw_line(
            (0, 0), (0, 1), color=self.SPLIT_COLOR, thickness=1,
            parent=overlay)
        view = {
            "hitbox": hitbox, "overlay": overlay, "line": line,
            "orientation": None, "handle_id": str(handle_id),
        }
        self._split_handle_views[str(handle_id)] = view
        return view

    def _ensure_split_handle_view(self, handle_id):
        handle_id = str(handle_id)
        return (self._split_handle_views.get(handle_id)
                or self._create_split_handle_view(handle_id))

    def _split_handle_line_geometry(self, handle, hit_rect):
        _x, _y, width, height = hit_rect
        orientation = handle.get("orientation")
        if orientation == DockLayoutTree.HORIZONTAL:
            center = max(0.0, float(width) * 0.5)
            return (center, 0.0), (center, max(1.0, float(height)))
        center = max(0.0, float(height) * 0.5)
        return (0.0, center), (max(1.0, float(width)), center)

    def _sync_split_handle_views(self, handles):
        active_ids = set()
        self._split_handles = {}
        for handle in handles or ():
            handle = dict(handle)
            handle_id = self._split_handle_id(handle)
            handle["id"] = handle_id
            active_ids.add(handle_id)
            self._split_handles[handle_id] = handle
            view = self._ensure_split_handle_view(handle_id)
            hx, hy, hw, hh = handle.get("hit_rect") or (0, 0, 1, 1)
            hw, hh = max(1, int(hw)), max(1, int(hh))
            try:
                # A dock created after an earlier split handle is a later DPG
                # sibling and would otherwise paint above the transparent grab
                # target. Re-appending the hitbox keeps separators at the top of
                # the local dock stack without introducing a global overlay.
                dpg.move_item(view["hitbox"], parent=self.parent)
                dpg.configure_item(
                    view["hitbox"], pos=(int(hx), int(hy)), width=hw,
                    height=hh, show=True)
                dpg.configure_item(
                    view["overlay"], pos=(0, 0), width=hw, height=hh)
                p1, p2 = self._split_handle_line_geometry(
                    handle, (hx, hy, hw, hh))
                dpg.configure_item(view["line"], p1=p1, p2=p2)
                view["orientation"] = handle.get("orientation")
            except Exception:
                pass

        for handle_id, view in tuple(self._split_handle_views.items()):
            if handle_id in active_ids:
                continue
            try:
                dpg.configure_item(view["hitbox"], show=False)
            except Exception:
                pass
            if self._split_hover_id == handle_id:
                self._split_hover_id = None
            if self._split_drag_id == handle_id:
                self._cancel_split_drag()

        self._refresh_split_handle_visuals()

    def _hovered_split_handle_id(self, mouse=None):
        for handle_id, view in tuple(self._split_handle_views.items()):
            if handle_id not in self._split_handles:
                continue
            hitbox = view.get("hitbox")
            try:
                if (hitbox is not None and dpg.does_item_exist(hitbox)
                        and dpg.is_item_hovered(hitbox)):
                    return handle_id
            except Exception:
                pass
            # Some DPG builds report hover one frame late for newly positioned
            # child windows. Fall back to screen-space item rectangles.
            if mouse is not None and hitbox is not None:
                try:
                    x, y = map(float, dpg.get_item_rect_min(hitbox))
                    width, height = map(float, dpg.get_item_rect_size(hitbox))
                    mx, my = map(float, mouse)
                    if x <= mx <= x + width and y <= my <= y + height:
                        return handle_id
                except Exception:
                    pass
        return None

    def _apply_split_cursor(self, handle_id):
        handle = self._split_handles.get(str(handle_id))
        if handle is None:
            return False
        cursor_name = (
            "mvMouseCursor_ResizeEW"
            if handle.get("orientation") == DockLayoutTree.HORIZONTAL
            else "mvMouseCursor_ResizeNS")
        cursor = getattr(dpg, cursor_name, None)
        if cursor is None:
            return False
        try:
            dpg.set_mouse_cursor(cursor)
            return True
        except Exception:
            return False

    def _refresh_split_handle_visuals(self):
        for handle_id, view in tuple(self._split_handle_views.items()):
            line = view.get("line")
            if line is None:
                continue
            active = handle_id == self._split_drag_id
            hovered = handle_id == self._split_hover_id
            try:
                dpg.configure_item(
                    line,
                    color=self.ACCENT if (active or hovered) else self.SPLIT_COLOR,
                    thickness=2 if active else 1)
            except Exception:
                pass

    def _begin_split_drag(self, handle_id, mouse):
        handle_id = str(handle_id)
        handle = self._split_handles.get(handle_id)
        if handle is None or mouse is None:
            return False
        if not acquire_pointer_input(self._split_drag_owner):
            return False
        self._split_drag_id = handle_id
        self._split_drag_start_mouse = tuple(map(float, mouse))
        self._split_drag_start_sizes = (
            float(handle.get("before_extent") or 1),
            float(handle.get("after_extent") or 1))
        # Keep an exact topology snapshot so Esc can roll an opaque resize back
        # to the pre-drag split weights instead of merely releasing capture.
        self._split_drag_restore_state = self._layout_tree.to_state()
        self._split_hover_id = handle_id
        self._refresh_split_handle_visuals()
        return True

    def _cancel_split_drag(self, *, restore=False):
        release_pointer_input(self._split_drag_owner)
        restore_state = self._split_drag_restore_state if restore else None
        width, height = self._last_layout_size
        self._split_drag_id = None
        self._split_drag_start_mouse = None
        self._split_drag_start_sizes = None
        self._split_drag_restore_state = None
        if restore_state is not None:
            self._layout_tree = DockLayoutTree.from_state(restore_state)
            self._tabs_dirty = True
            # Force geometry/handle regeneration from the restored weights only
            # after clearing drag identity, avoiding re-entrant cancel paths if
            # the restored topology has a different separator id.
            self._last_layout_size = (0, 0)
            if width > 0 and height > 0:
                self.layout(width, height, force=True)
        self._refresh_split_handle_visuals()

    def _drag_split_handle(self, mouse):
        handle_id = self._split_drag_id
        handle = self._split_handles.get(str(handle_id)) if handle_id else None
        if (handle is None or mouse is None or self._split_drag_start_mouse is None
                or self._split_drag_start_sizes is None):
            return False
        orientation = handle.get("orientation")
        axis = 0 if orientation == DockLayoutTree.HORIZONTAL else 1
        try:
            delta = float(mouse[axis]) - float(self._split_drag_start_mouse[axis])
        except Exception:
            return False
        before, after = DockLayoutTree.clamp_split_pair(
            self._split_drag_start_sizes[0], self._split_drag_start_sizes[1],
            delta, minimum=self.SPLIT_MIN_EXTENT)
        changed = self._layout_tree.resize_split_handle(
            handle.get("area") or self.dock_area, handle.get("path") or (),
            handle.get("before_index", 0), handle.get("after_index", 1),
            before, after)
        if not changed:
            return False
        width, height = self._last_layout_size
        self._tabs_dirty = True
        if width > 0 and height > 0:
            self.layout(width, height, force=True)
        return True

    def _update_split_interaction(self, down, mouse, pressed_now):
        if self._split_drag_id is not None:
            self._split_hover_id = self._split_drag_id
            self._apply_split_cursor(self._split_drag_id)
            if down:
                self._drag_split_handle(mouse)
                self._refresh_split_handle_visuals()
                return True
            self._cancel_split_drag()
            self._split_hover_id = self._hovered_split_handle_id(mouse)
            self._refresh_split_handle_visuals()
            if self._split_hover_id is not None:
                self._apply_split_cursor(self._split_hover_id)
            return True

        hovered = self._hovered_split_handle_id(mouse)
        if hovered != self._split_hover_id:
            self._split_hover_id = hovered
            self._refresh_split_handle_visuals()
        if hovered is not None:
            self._apply_split_cursor(hovered)
            if pressed_now:
                return self._begin_split_drag(hovered, mouse)
        return False

    def split_handle_geometries(self):
        """Return defensive splitter geometry snapshots for diagnostics/tests."""
        return tuple(dict(handle) for handle in self._split_handles.values())

    def _hovered_tab_key(self):
        for key, button in tuple(self._tab_buttons.items()):
            try:
                if dpg.does_item_exist(button) and dpg.is_item_hovered(button):
                    return key
            except Exception:
                continue
        return None

    def _tab_strip_rect(self, key=None):
        view = self._tab_view_for_key(key) if key is not None else self._legacy_tab_view
        strip = view.get("strip") if view is not None else self.tab_strip
        try:
            x, y = map(float, dpg.get_item_rect_min(strip))
            w, h = map(float, dpg.get_item_rect_size(strip))
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

    def _parent_screen_rect(self):
        """Return the dock site's screen-space rectangle when available."""
        try:
            x, y = map(float, dpg.get_item_rect_min(self.parent))
            w, h = map(float, dpg.get_item_rect_size(self.parent))
            if w > 0.0 and h > 0.0:
                return x, y, w, h
        except Exception:
            pass
        width, height = self._last_layout_size
        if width > 0 and height > 0:
            return 0.0, 0.0, float(width), float(height)
        return None

    @staticmethod
    def _point_in_rect(mouse, rect, margin=0.0):
        if mouse is None or rect is None:
            return False
        mx, my = map(float, mouse)
        x, y, width, height = map(float, rect)
        margin = max(0.0, float(margin))
        return (x - margin <= mx <= x + width + margin
                and y - margin <= my <= y + height + margin)

    @classmethod
    def _drop_zone_for_rect(cls, mouse, rect):
        """Resolve a five-way QMainWindow-like target inside *rect*.

        Corners choose the nearest edge instead of depending on branch order,
        which keeps diagonal tab drags predictable at any leaf aspect ratio.
        """
        if mouse is None or rect is None:
            return None
        mx, my = map(float, mouse)
        x, y, width, height = map(float, rect)
        if width <= 0.0 or height <= 0.0:
            return None
        if not cls._point_in_rect((mx, my), (x, y, width, height)):
            return None
        local_x = mx - x
        local_y = my - y
        edge_x = min(
            float(cls.DOCK_DROP_EDGE_MAX),
            max(float(cls.DOCK_DROP_EDGE_MIN), width * cls.DOCK_DROP_EDGE_FRACTION),
            width * 0.45)
        edge_y = min(
            float(cls.DOCK_DROP_EDGE_MAX),
            max(float(cls.DOCK_DROP_EDGE_MIN), height * cls.DOCK_DROP_EDGE_FRACTION),
            height * 0.45)
        candidates = []
        if local_x <= edge_x:
            candidates.append((local_x / max(1.0, edge_x), "left"))
        if width - local_x <= edge_x:
            candidates.append(((width - local_x) / max(1.0, edge_x), "right"))
        if local_y <= edge_y:
            candidates.append((local_y / max(1.0, edge_y), "top"))
        if height - local_y <= edge_y:
            candidates.append(((height - local_y) / max(1.0, edge_y), "bottom"))
        if not candidates:
            return "center"
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    @staticmethod
    def _drop_preview_rect(rect, zone):
        x, y, width, height = map(float, rect)
        zone = str(zone or "center").strip().lower()
        if zone == "left":
            return x, y, max(1.0, width * 0.5), height
        if zone == "right":
            half = max(1.0, width * 0.5)
            return x + width - half, y, half, height
        if zone == "top":
            return x, y, width, max(1.0, height * 0.5)
        if zone == "bottom":
            half = max(1.0, height * 0.5)
            return x, y + height - half, width, half
        # Centre tabification feedback is slightly inset so it reads as a
        # distinct target rather than looking like an edge split of 100%.
        pad_x = min(28.0, max(6.0, width * 0.12))
        pad_y = min(24.0, max(6.0, height * 0.12))
        return (
            x + pad_x, y + pad_y,
            max(1.0, width - 2.0 * pad_x),
            max(1.0, height - 2.0 * pad_y))

    def _dock_drop_target_for_keys(self, mouse, drag_key, drag_keys=None):
        """Return the live drop target under *mouse* for a dock/group drag."""
        if mouse is None or drag_key is None:
            return None
        parent_rect = self._parent_screen_rect()
        if not self._point_in_rect(mouse, parent_rect):
            return None
        px, py, _pw, _ph = parent_rect
        drag_key = str(drag_key)
        excluded = {str(key) for key in (drag_keys or (drag_key,))}
        for group in self._last_layout_groups:
            gx, gy, gw, gh = group.get("rect") or (0, 0, 0, 0)
            screen_rect = (px + gx, py + gy, gw, gh)
            if not self._point_in_rect(mouse, screen_rect):
                continue
            keys = [str(key) for key in group.get("keys") or ()]
            target_key = next((key for key in keys if key not in excluded), None)
            # The source leaf cannot accept a relative drop from itself; for
            # GroupedDragging every dock in the source tab group is excluded.
            if target_key is None:
                return None
            zone = self._drop_zone_for_rect(mouse, screen_rect)
            if zone is None:
                return None
            return {
                "group_id": group.get("group_id"),
                "target_key": target_key,
                "drag_key": drag_key,
                "zone": zone,
                "rect": tuple(map(float, screen_rect)),
                "preview_rect": self._drop_preview_rect(screen_rect, zone),
            }
        return None

    def _dock_drop_target_at(self, mouse, drag_key):
        """Compatibility resolver for one-dock live drop feedback."""
        return self._dock_drop_target_for_keys(mouse, drag_key)

    def dock_drop_target_at(self, mouse, drag_key):
        """Public defensive snapshot used by hosts/tests for live feedback."""
        target = self._dock_drop_target_at(mouse, drag_key)
        return None if target is None else dict(target)

    def _set_tab_drop_target(self, target):
        target = None if target is None else dict(target)
        if target == self._tab_drop_target:
            return
        self._tab_drop_target = target
        if target is None:
            self._drop_preview.hide()
            return
        x, y, width, height = target["preview_rect"]
        self._drop_preview.show(
            x, y, width, height,
            inset=(target.get("zone") == "center"))

    def _clear_tab_drop_target(self):
        self._tab_drop_target = None
        self._drop_preview.hide()

    def _pointer_outside_tab_strip(self, mouse, key=None):
        rect = self._tab_strip_rect(key)
        if mouse is None or rect is None:
            return False
        mx, my = mouse
        x, y, w, h = rect
        margin = float(self.TAB_TEAROFF_DISTANCE)
        return (mx < x - margin or mx > x + w + margin
                or my < y - margin or my > y + h + margin)

    def _pointer_outside_dock_site(self, mouse):
        return not self._point_in_rect(
            mouse, self._parent_screen_rect(), margin=self.DOCK_DROP_PARENT_MARGIN)

    def _tab_insert_index_at(self, mouse, drag_key):
        """Return insertion index within the dragged dock's own tab group."""
        if mouse is None:
            return None
        mx = float(mouse[0])
        remaining = [key for key in self._layout_tree.group_keys(drag_key)
                     if key != drag_key and key in self._tab_buttons]
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
        view = self._tab_view_for_key(drag_key)
        strip = self._tab_strip_rect(drag_key)
        if view is None or strip is None:
            return
        sx, sy, sw, sh = strip
        remaining = [key for key in self._layout_tree.group_keys(drag_key)
                     if key != drag_key and key in self._tab_buttons]
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
                view["overlay"], width=max(1, int(sw)), height=max(1, int(sh)))
            dpg.configure_item(
                view["marker"], p1=(x, 2), p2=(x, max(3.0, sh - 2.0)), show=True)
        except Exception:
            pass

    def _hide_insert_marker(self):
        for view in tuple(self._tab_views.values()) or (self._legacy_tab_view,):
            try:
                marker = view.get("marker")
                if marker is not None and dpg.does_item_exist(marker):
                    dpg.configure_item(marker, show=False)
            except Exception:
                pass

    def _hovered_title_key(self):
        """Return the single-leaf dock whose default title handle is hovered."""
        # Iterate in reverse registry order so later-created DPG siblings win
        # when retained geometry overlaps for one transition frame.
        for key, entry in reversed(tuple(self._entries.items())):
            if bool(entry.get("floating")):
                continue
            window = entry.get("window")
            if not self._window_requested_visible(window):
                continue
            group_keys = tuple(self._layout_tree.group_keys(key))
            if (len(self._layout_tree.group_keys(key)) != 1
                    and not self.groupedDraggingEnabled()):
                continue
            if not self._window_user_movable(window):
                continue
            dock = self._dock_interface(window)
            handle = getattr(dock, "drag_handle", None)
            if handle is None:
                continue
            try:
                if dpg.does_item_exist(handle) and dpg.is_item_hovered(handle):
                    return str(key)
            except Exception:
                continue
        return None

    def _title_drag_anchor(self, key, mouse):
        entry = self._entries.get(str(key))
        if entry is None or mouse is None:
            return (40.0, 10.0)
        dock = self._dock_interface(entry.get("window"))
        handle = getattr(dock, "drag_handle", None)
        if handle is None:
            return (40.0, 10.0)
        try:
            hx, hy = map(float, dpg.get_item_rect_min(handle))
            return (max(0.0, float(mouse[0]) - hx),
                    max(0.0, float(mouse[1]) - hy))
        except Exception:
            return (40.0, 10.0)

    def _begin_title_drag(self, key, mouse):
        key = str(key)
        entry = self._entries.get(key)
        if entry is None or not self._window_user_movable(entry.get("window")):
            self._title_press_key = None
            self._title_press_pos = None
            return False
        group_keys = tuple(self._layout_tree.group_keys(key))
        grouped = bool(self.groupedDraggingEnabled() and len(group_keys) > 1)
        if grouped:
            # A group gesture must never smuggle a non-movable QDockWidget to a
            # new location. Refuse the gesture rather than silently splitting
            # the restricted member away from the group.
            for candidate in group_keys:
                candidate_entry = self._entries.get(candidate)
                if (candidate_entry is None or not self._window_user_movable(
                        candidate_entry.get("window"))):
                    self._title_press_key = None
                    self._title_press_pos = None
                    return False
        if not acquire_pointer_input(self._title_drag_owner):
            return False
        self._clear_tab_drop_target()
        self._title_drag_key = key
        self._title_drag_group_keys = group_keys if grouped else (key,)
        self._title_drag_grouped = grouped
        self._title_drag_outside = False
        self._title_drag_started = True
        self.raise_dock_widget(self._title_drag_key)
        return True

    def _reset_title_drag(self, *, release_capture=True):
        if release_capture:
            release_pointer_input(self._title_drag_owner)
        self._clear_tab_drop_target()
        self._title_press_key = None
        self._title_press_pos = None
        self._title_drag_key = None
        self._title_drag_started = False
        self._title_drag_group_keys = ()
        self._title_drag_grouped = False
        self._title_drag_outside = False

    def _request_drag_tearoff(self, key, mouse, drag_anchor):
        """Float one pointer-dragged dock through the host or DockWidget API."""
        key = str(key)
        entry = self._entries.get(key)
        if entry is None or not self._window_user_floatable(entry.get("window")):
            return False
        callback = self.on_tab_tearoff
        if callable(callback) and mouse is not None:
            result = callback(key, mouse, drag_anchor)
            return result is not False

        # Generic DearUIQt hosts may not need a process-isolated/native tear-off
        # callback. Let QDockWidget own the top-level transition, then mirror the
        # state in DockManager if the host did not already do so synchronously.
        dock = self._dock_interface(entry.get("window"))
        setter = getattr(dock, "setFloating", None)
        if not callable(setter):
            return False
        try:
            result = setter(True)
        except Exception:
            return False
        if key in self._entries and not bool(self._entries[key].get("floating")):
            self.set_floating(key, True)
        return result is not False

    def _group_drop_allowed(self, target_key, group_keys):
        target_entry = self._entries.get(str(target_key))
        if target_entry is None:
            return False
        area = self._normalize_area(
            self._layout_tree.area_of(str(target_key))
            or target_entry.get("area") or self.dock_area)
        return all(
            key in self._entries
            and self._area_allowed(self._entries[key].get("window"), area)
            for key in tuple(group_keys or ()))

    def _request_group_tearoff(self, keys, mouse, drag_anchor):
        keys = tuple(str(key) for key in keys if str(key) in self._entries)
        if not keys:
            return False
        if not all(self._window_user_floatable(
                self._entries[key].get("window")) for key in keys):
            return False
        accepted = True
        for index, key in enumerate(keys):
            anchor = (float(drag_anchor[0]) + 12.0 * index,
                      float(drag_anchor[1]) + 12.0 * index)
            if not self._request_drag_tearoff(key, mouse, anchor):
                accepted = False
        return accepted

    def _tearoff_title_drag(self, key, mouse):
        """Detach one title-dragged dock, preserving the pointer anchor."""
        drag_anchor = self._title_drag_anchor(key, mouse)
        self._reset_title_drag()
        return self._request_drag_tearoff(key, mouse, drag_anchor)

    def _update_title_interaction(self, down, mouse, pressed_now):
        """Drive QDockWidget-title dragging, including GroupedDragging."""
        if pressed_now and not self._tab_drag_started:
            key = self._hovered_title_key()
            if key is not None:
                self._title_press_key = key
                self._title_press_pos = mouse

        if (down and self._title_press_key is not None
                and not self._title_drag_started
                and self._distance(mouse, self._title_press_pos)
                >= float(self.TAB_DRAG_START_DISTANCE)):
            self._begin_title_drag(self._title_press_key, mouse)

        if down and self._title_drag_started and self._title_drag_key is not None:
            key = self._title_drag_key
            drag_keys = self._title_drag_group_keys or (key,)
            drop_target = (
                self._dock_drop_target_for_keys(mouse, key, drag_keys=drag_keys)
                if self._title_drag_grouped
                else self._dock_drop_target_at(mouse, key))
            if (drop_target is not None and self._title_drag_grouped
                    and not self._group_drop_allowed(
                        drop_target.get("target_key"), drag_keys)):
                drop_target = None
            self._title_drag_outside = bool(
                drop_target is None and self._pointer_outside_dock_site(mouse))
            self._set_tab_drop_target(drop_target)
            return True

        if (not down and self._title_drag_started
                and self._title_drag_key is not None):
            key = self._title_drag_key
            group_keys = tuple(self._title_drag_group_keys or (key,))
            grouped = bool(self._title_drag_grouped)
            outside = bool(self._title_drag_outside)
            drag_anchor = self._title_drag_anchor(key, mouse)
            previous_layout_size = self._last_layout_size
            drop_target = (
                None if self._tab_drop_target is None
                else dict(self._tab_drop_target))
            self._reset_title_drag()
            if drop_target is not None:
                if grouped:
                    self.dock_group_relative(
                        drop_target.get("target_key"), key,
                        drop_target.get("zone") or "center")
                else:
                    self.dock_relative(
                        drop_target.get("target_key"), key,
                        drop_target.get("zone") or "center")
                width, height = previous_layout_size
                if width > 0 and height > 0:
                    self.layout(width, height, force=True)
            elif outside:
                entry = self._entries.get(str(key))
                if grouped:
                    self._request_group_tearoff(group_keys, mouse, drag_anchor)
                elif (entry is not None
                        and self._window_user_floatable(entry.get("window"))):
                    self._request_drag_tearoff(key, mouse, drag_anchor)
            return True

        if not down and self._title_press_key is not None:
            self._title_press_key = None
            self._title_press_pos = None
        return self._title_press_key is not None

    def _begin_tab_drag(self, key, mouse):
        entry = self._entries.get(str(key))
        if entry is not None and not self._window_user_movable(entry.get("window")):
            self._tab_press_key = None
            self._tab_press_pos = None
            return False
        self._clear_tab_drop_target()
        self._tab_drag_key = str(key)
        self._tab_drag_started = True
        self._tab_drag_outside = False
        self._tab_drag_insert_index = self._tab_insert_index_at(
            mouse, self._tab_drag_key)
        self._suppress_click_key = self._tab_drag_key
        self._suppress_click_until_frame = self._frame_count() + 3
        acquire_pointer_input(self._tab_drag_owner)
        self.raise_dock_widget(self._tab_drag_key)
        if self._tab_drag_insert_index is not None:
            self._show_insert_marker(
                self._tab_drag_insert_index, self._tab_drag_key)
        return True

    def _reset_tab_drag(self, *, release_capture=True):
        if release_capture:
            release_pointer_input(self._tab_drag_owner)
        self._clear_tab_drop_target()
        self._hide_insert_marker()
        self._tab_press_key = None
        self._tab_press_pos = None
        self._tab_drag_key = None
        self._tab_drag_started = False
        self._tab_drag_insert_index = None
        self._tab_drag_outside = False

    def cancel_active_drag(self):
        """Cancel the current dock gesture, mirroring Qt's Esc drag cancel."""
        cancelled = False
        if self._split_drag_id is not None:
            self._cancel_split_drag(restore=True)
            cancelled = True
        if self._title_drag_started or self._title_press_key is not None:
            self._reset_title_drag()
            cancelled = True
        if self._tab_drag_started or self._tab_press_key is not None:
            key = self._tab_drag_key or self._tab_press_key
            self._reset_tab_drag()
            if key is not None:
                self._suppress_click_key = str(key)
                self._suppress_click_until_frame = self._frame_count() + 3
            cancelled = True
        self._clear_tab_drop_target()
        self._hide_insert_marker()
        return cancelled

    cancelDrag = cancel_active_drag

    def update_interaction(self):
        """Poll dock splitter and QTabBar gestures once per frame.

        Dear PyGui does not provide native QMainWindow dock separators or
        draggable tabs. Keeping both interactions here gives every host the same
        pointer-capture, click-through prevention and resize/reorder semantics.
        """
        docked = self.visible_docked_keys()
        down = self._left_mouse_down()
        frame = self._frame_count()
        mouse = self._mouse_position()
        pressed_now = bool(down and not self._tab_mouse_was_down)

        # Esc cancels before any interaction path can commit a drop/tear-off.
        # Opaque splitter drags restore their pre-drag weight snapshot.
        if self._escape_pressed():
            if self.cancel_active_drag():
                self._tab_mouse_was_down = down
                return

        # Split handles get first refusal on the gesture. Their transparent
        # protected hitboxes prevent click-through, and explicit pointer capture
        # keeps the drag exclusive even after leaving the separator rectangle.
        if self._update_split_interaction(down, mouse, pressed_now):
            if self._tab_drag_started or self._tab_press_key is not None:
                self._reset_tab_drag()
            if self._title_drag_started or self._title_press_key is not None:
                self._reset_title_drag()
            self._tab_mouse_was_down = down
            return

        # A standalone QDockWidget title bar uses the same five-way target
        # resolver as QTabBar drags. This path runs before the no-tab early
        # return so a layout containing only one dock is still draggable.
        if self._update_title_interaction(down, mouse, pressed_now):
            if self._tab_drag_started or self._tab_press_key is not None:
                self._reset_tab_drag()
            self._tab_mouse_was_down = down
            return

        if (self._suppress_click_key is not None
                and frame > self._suppress_click_until_frame
                and not down):
            self._suppress_click_key = None
            self._suppress_click_until_frame = -1
        if not self._tab_buttons:
            if self._tab_drag_started or self._tab_press_key is not None:
                self._reset_tab_drag()
            self._tab_mouse_was_down = down
            return

        # First down frame over a tab: remember the potential click/drag.
        if down and not self._tab_mouse_was_down:
            key = self._hovered_tab_key()
            if key is not None:
                self._title_press_key = None
                self._title_press_pos = None
                self._tab_press_key = key
                self._tab_press_pos = mouse

        # Promote the pending click to an exclusive drag after a small movement.
        if (down and self._tab_press_key is not None
                and not self._tab_drag_started
                and self._distance(mouse, self._tab_press_pos)
                >= float(self.TAB_DRAG_START_DISTANCE)):
            self._begin_tab_drag(self._tab_press_key, mouse)

        if down and self._tab_drag_started and self._tab_drag_key is not None:
            outside_source_strip = self._pointer_outside_tab_strip(
                mouse, self._tab_drag_key)
            # Preserve ordinary QTabBar reordering while the pointer is still
            # in the source strip. Five-way docking begins only after the tab
            # has been dragged into dock content/another leaf.
            drop_target = (
                self._dock_drop_target_at(mouse, self._tab_drag_key)
                if outside_source_strip else None)
            self._set_tab_drop_target(drop_target)
            if drop_target is not None:
                self._tab_drag_outside = False
                # A dock leaf owns the gesture while its five-way live target
                # is active; the reorder caret would be conflicting feedback.
                self._hide_insert_marker()
            # Tear-off is now reserved for actually leaving the dock site. In
            # r69 any movement beyond the source tab strip detached immediately,
            # which made it impossible to drag a tab into another split leaf.
            elif (outside_source_strip and self._pointer_outside_dock_site(mouse)):
                # r72 defers floating until mouse release so Esc can cancel the
                # drag without changing dock topology/native window state.
                key = self._tab_drag_key
                entry = self._entries.get(str(key))
                self._tab_drag_outside = bool(
                    entry is not None
                    and self._window_user_floatable(entry.get("window")))
                self._hide_insert_marker()

            elif not outside_source_strip:
                self._tab_drag_outside = False
                index = self._tab_insert_index_at(mouse, self._tab_drag_key)
                if index is not None:
                    self._tab_drag_insert_index = index
                    self._show_insert_marker(index, self._tab_drag_key)

        if (not down and self._tab_mouse_was_down
                and self._tab_drag_started and self._tab_drag_key is not None):
            key = self._tab_drag_key
            index = self._tab_drag_insert_index
            outside = bool(self._tab_drag_outside)
            previous_layout_size = self._last_layout_size
            drop_target = (
                None if self._tab_drop_target is None
                else dict(self._tab_drop_target))
            button_rect = self._tab_button_rect(key)
            if button_rect is not None and mouse is not None:
                drag_anchor = (
                    max(0.0, mouse[0] - button_rect[0]),
                    max(0.0, mouse[1] - button_rect[1]),
                )
            else:
                drag_anchor = (40.0, 10.0)
            self._reset_tab_drag()
            self._suppress_click_key = key
            self._suppress_click_until_frame = frame + 2
            if drop_target is not None:
                self.dock_relative(
                    drop_target.get("target_key"), key,
                    drop_target.get("zone") or "center")
                width, height = previous_layout_size
                if width > 0 and height > 0:
                    self.layout(width, height, force=True)
            elif outside:
                self._request_drag_tearoff(key, mouse, drag_anchor)
            elif index is not None:
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

    def _rebuild_tab_view(self, group_id, keys, active, width):
        view = self._ensure_tab_view(group_id)
        group_item = view["group"]
        for key in tuple(view.get("buttons") or {}):
            self._tab_buttons.pop(key, None)
            self._tab_key_to_group.pop(key, None)
        try:
            dpg.delete_item(group_item, children_only=True)
        except Exception:
            pass
        view["buttons"] = {}
        keys = tuple(key for key in keys if key in self._entries)
        if len(keys) <= 1:
            view["keys"] = keys
            view["active"] = active
            return view

        usable = max(1, int(width) - max(0, len(keys) - 1) * self.TAB_GAP)
        tab_width = max(
            self.TAB_MIN_WIDTH,
            min(self.TAB_MAX_WIDTH, int(usable / max(1, len(keys)))))
        max_chars = max(6, int((tab_width - 2 * self.TAB_PADDING_X) / 7))
        for key in keys:
            entry = self._entries[key]
            label = self._elide(entry.get("title") or key, max_chars)
            button = dpg.add_button(
                parent=group_item,
                label=label,
                width=tab_width,
                height=self.TAB_HEIGHT - 2,
                callback=self._tab_clicked,
                user_data=key,
            )
            view["buttons"][key] = button
            self._tab_buttons[key] = button
            self._tab_key_to_group[key] = str(group_id)
            dpg.bind_item_theme(
                button,
                self._active_tab_theme if key == active else self._inactive_tab_theme)
            full_title = str(entry.get("title") or key)
            if full_title != label:
                add_styled_tooltip(button, full_title)
        view["width"] = int(width)
        view["keys"] = keys
        view["active"] = active
        return view

    def _rebuild_tabs(self, width):
        """Compatibility helper rebuilding the active dock's tab group."""
        active = self._active_key or self._ensure_active()
        keys = self._layout_tree.group_keys(active) if active is not None else ()
        group_id = self._layout_tree.group_id_of(active) if active is not None else None
        if group_id is not None:
            self._rebuild_tab_view(group_id, keys, active, width)
        self._tabs_dirty = False
        self._last_tab_width = int(width)

    def layout(self, width, height, force=False):
        """Lay out every visible split/tab group in the current dock area."""
        width = max(1, int(width))
        height = max(1, int(height))
        if (not force and self._last_layout_size == (width, height)
                and not self._tabs_dirty):
            return
        self._last_layout_size = (width, height)
        self._ensure_active()
        visible = set(self.visible_docked_keys())
        details = self._layout_tree.layout_details(
            self.dock_area, width, height, visible_keys=visible,
            handle_width=self.SPLIT_HANDLE_WIDTH,
            handle_hit_width=self.SPLIT_HANDLE_HIT_WIDTH)
        groups = details["groups"]
        self._last_layout_groups = tuple(dict(group) for group in groups)
        self._sync_split_handle_views(details["handles"])

        # Start hidden; each visible layout leaf re-enables exactly one dock
        # per tab group. Split siblings remain visible simultaneously.
        for key, entry in self._entries.items():
            if bool(entry.get("floating")):
                continue
            window = entry.get("window")
            root = getattr(window, "root", None)
            if root is None or not dpg.does_item_exist(root):
                continue
            dpg.configure_item(root, show=False)
            effective = getattr(window, "_set_effective_visibility", None)
            if callable(effective):
                effective(False)

        used_tab_groups = set()
        current_tab_position = self.tabPosition(self.dock_area)
        self.tab_position = current_tab_position
        for group in groups:
            gx, gy, gw, gh = group["rect"]
            keys = tuple(group.get("keys") or ())
            if not keys:
                continue
            active = group.get("active") if group.get("active") in keys else keys[-1]
            group_id = str(group.get("group_id") or "dock-tabs")
            tabified = len(keys) > 1
            tab_h = min(self.TAB_HEIGHT, max(1, gh - 1)) if tabified else 0
            content_h = max(1, gh - tab_h)
            content_y = gy

            if tabified:
                used_tab_groups.add(group_id)
                view = self._ensure_tab_view(group_id)
                tab_y = gy if current_tab_position == "top" else gy + content_h
                content_y = gy + tab_h if current_tab_position == "top" else gy
                dpg.configure_item(
                    view["strip"], pos=(gx, tab_y), width=gw, height=tab_h, show=True)
                try:
                    dpg.configure_item(
                        view["overlay"], pos=(0, 0), width=gw, height=tab_h)
                except Exception:
                    pass
                if (self._tabs_dirty or view.get("width") != int(gw)
                        or tuple(view.get("keys") or ()) != keys
                        or view.get("active") != active):
                    self._rebuild_tab_view(group_id, keys, active, gw)

            for key in keys:
                entry = self._entries.get(key)
                if entry is None or bool(entry.get("floating")):
                    continue
                window = entry.get("window")
                root = getattr(window, "root", None)
                if root is None or not dpg.does_item_exist(root):
                    continue
                requested_visible = self._window_requested_visible(window)
                is_active = bool(key == active and requested_visible)
                dpg.configure_item(root, show=is_active)
                effective = getattr(window, "_set_effective_visibility", None)
                if callable(effective):
                    effective(is_active)
                if not is_active:
                    continue
                dpg.configure_item(
                    root, pos=(gx, content_y), width=gw, height=content_h)
                resize = getattr(window, "resize", None)
                if callable(resize):
                    resize(gw, content_h)

        self._hide_unused_tab_views(used_tab_groups)
        self._tabs_dirty = False
        self._last_tab_width = width

    def save_state(self, version=0):
        """Return a versioned, JSON-serializable QMainWindow-like dock state.

        Format 3 persists the recursive split/tab tree in addition to per-dock
        state. Keys inside the tree are encoded as QDockWidget ``objectName``
        identities, so state remains stable when host registry keys change.
        """
        docks = []
        order = []
        active_identity = None
        identity_by_key = {}
        for key, entry in self._entries.items():
            window = entry.get("window")
            identity = self._dock_identity(key, window)
            identity_by_key[key] = identity
            order.append(identity)
            if key == self._active_key:
                active_identity = identity
            docks.append({
                "object_name": identity,
                "key": key,
                "area": self._normalize_area(
                    self._layout_tree.area_of(key)
                    or entry.get("area") or self.dock_area),
                "floating": bool(entry.get("floating")),
                "visible": self._window_requested_visible(window),
            })
        return {
            "format": 3,
            "version": int(version),
            "dock_area": self.dock_area,
            "tab_position": self.tab_position,
            "tab_positions": dict(self._tab_positions),
            "active": active_identity,
            "order": order,
            "docks": docks,
            "layout": self._layout_tree.to_state(
                key_encoder=lambda key: identity_by_key.get(str(key), str(key))),
            # Keep the historical field so older readers can still recover
            # the coarse floating state from a newer payload.
            "floating": [item["key"] for item in docks if item["floating"]],
        }

    def restore_state(self, state, version=0):
        """Restore versioned tab/split topology without forcing invalid areas.

        Format 3 restores the recursive layout tree by ``objectName``. Unknown
        object names remain as placeholders until ``restoreDockWidget()`` is
        called for a dock created after restoreState(). Formats 1/2 remain
        supported for profiles written by r65-r67.
        """
        state = dict(state or {})
        state_format = int(state.get("format") or 1)
        if state_format >= 2 and int(state.get("version", 0)) != int(version):
            return False

        self.tab_position = (
            "top" if str(state.get("tab_position") or self.tab_position).lower() == "top"
            else "bottom")
        saved_tab_positions = dict(state.get("tab_positions") or {})
        for area in ("left", "right", "top", "bottom"):
            value = str(saved_tab_positions.get(area) or self.tab_position).lower()
            self._tab_positions[area] = "top" if value == "top" else "bottom"
        self.dock_area = self._normalize_area(
            state.get("dock_area") or self.dock_area)
        self.tab_position = self._tab_positions.get(
            self.dock_area, self.tab_position)

        if state_format >= 2:
            saved_docks = {
                str(item.get("object_name") or item.get("key") or ""): dict(item)
                for item in state.get("docks") or ()
                if str(item.get("object_name") or item.get("key") or "")
            }
            identities = {
                self._dock_identity(key, entry.get("window")): key
                for key, entry in self._entries.items()
            }
            self._pending_restore = dict(saved_docks)

            reordered = OrderedDict()
            for identity in state.get("order") or ():
                key = identities.get(str(identity))
                if key is not None and key not in reordered:
                    reordered[key] = self._entries[key]
            for key, entry in self._entries.items():
                if key not in reordered:
                    reordered[key] = entry
            self._entries = reordered

            if state_format >= 3 and isinstance(state.get("layout"), dict):
                self._layout_tree = DockLayoutTree.from_state(state.get("layout"))
                # Replace persisted objectName leaves with live registry keys;
                # leave unknown identities intact for late restoreDockWidget().
                for identity, key in identities.items():
                    if identity == key:
                        continue
                    if self._layout_tree.contains(identity):
                        self._layout_tree.rename(identity, key)
                # A currently registered dock absent from the saved tree remains
                # usable and joins its saved/coerced area as a regular tab.
                for identity, key in identities.items():
                    if not self._layout_tree.contains(key):
                        entry = self._entries[key]
                        saved = saved_docks.get(identity) or {}
                        area = self._coerce_allowed_area(
                            entry.get("window"),
                            saved.get("area") or entry.get("area") or self.dock_area,
                            fallback=self.dock_area)
                        if area is not None:
                            self._layout_tree.add_tab(key, area, activate=False)
            else:
                # r66/r67 format-2 state had no recursive topology: rebuild the
                # historical one-tab-group-per-area layout from saved ordering.
                self._layout_tree = DockLayoutTree()
                for identity in state.get("order") or ():
                    key = identities.get(str(identity))
                    if key is None:
                        continue
                    saved = saved_docks.get(str(identity)) or {}
                    area = self._normalize_area(
                        saved.get("area") or self._entries[key].get("area") or self.dock_area)
                    self._layout_tree.add_tab(key, area, activate=False)
                for key, entry in self._entries.items():
                    if not self._layout_tree.contains(key):
                        self._layout_tree.add_tab(
                            key, entry.get("area") or self.dock_area, activate=False)

            for identity, key in identities.items():
                saved = self._pending_restore.pop(identity, None)
                if saved is not None:
                    self._apply_restored_entry(key, saved)

            active_identity = str(state.get("active") or "")
            active_key = identities.get(active_identity)
            self._active_key = (
                active_key if active_key in self.visible_docked_keys() else None)
            self._pending_active_identity = (
                active_identity if active_identity and self._active_key is None
                and active_identity in self._pending_restore else None)
            if self._active_key is not None:
                self._layout_tree.set_active(self._active_key)
        else:
            # Backward-compatible r65 payload: keys are the persistence ids and
            # one global dock_area applies to every entry.
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
            self._layout_tree = DockLayoutTree()
            floating = {str(key) for key in state.get("floating") or ()}
            for key, entry in self._entries.items():
                window = entry.get("window")
                area = self._coerce_allowed_area(
                    window, self.dock_area, fallback=entry.get("area") or self.dock_area)
                if area is not None:
                    entry["area"] = area
                    self._layout_tree.add_tab(key, area, activate=False)
                    self._apply_window_area(window, area)
                entry["floating"] = key in floating
                self._apply_window_floating(window, key in floating)
            self._pending_active_identity = None
            active = str(state.get("active") or "")
            self._active_key = active if active in self.visible_docked_keys() else None
            if self._active_key is not None:
                self._layout_tree.set_active(self._active_key)

        self._ensure_active(notify=True)
        self._tabs_dirty = True
        self._last_layout_size = (0, 0)
        return True

    # QMainWindow spelling for callers that deliberately use the Qt API
    # surface. Snake-case names remain canonical inside DearUIQt.
    saveState = save_state
    restoreState = restore_state

    def close(self):
        self._reset_tab_drag()
        self._reset_title_drag()
        self._cancel_split_drag()
        self._drop_preview.destroy()
        self._last_layout_groups = ()
        for view in tuple(self._split_handle_views.values()):
            hitbox = view.get("hitbox") if isinstance(view, dict) else None
            if hitbox is None:
                continue
            unregister_pointer_protected_item(hitbox)
            try:
                if dpg.does_item_exist(hitbox):
                    dpg.delete_item(hitbox)
            except Exception:
                pass
        self._split_handle_views.clear()
        self._split_handles.clear()
        self._split_hover_id = None
        self._entries.clear()
        self._pending_restore.clear()
        self._pending_active_identity = None
        self._layout_tree.clear()
        self._active_key = None
        self._last_tab_width = 0
        seen = set()
        views = list(self._tab_views.values()) + [self._legacy_tab_view]
        for view in views:
            strip = view.get("strip") if isinstance(view, dict) else None
            if strip is None or strip in seen:
                continue
            seen.add(strip)
            try:
                if dpg.does_item_exist(strip):
                    dpg.delete_item(strip)
            except Exception:
                pass
        self._tab_views.clear()
        self._tab_buttons.clear()
        self._tab_key_to_group.clear()

