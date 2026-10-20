"""Dear ImGui popup menus with a compact Qt/Fusion-like contract.

The renderer intentionally avoids Qt/Tk.  Each row is built from Dear PyGui
primitives so host applications can show texture icons, check marks and hover-open submenus
without falling back to a second UI toolkit.
"""
from __future__ import annotations

from ..core.object import QEvent, QKeyEvent, QObject, Signal, QPoint, QRect
from ..gui.action import QAction
from ..gui.palette import QtFusionMetrics, QtFusionPalette
from ..themes import (
    ThemeTarget, ThemeColor, ThemeStyle, theme_component, make_theme,
    menu_surface_theme,
)
from ..backends.dearpygui import dpg_window_rect
from ..input_gate import (
    acquire_popup_input, release_popup_input,
    register_pointer_protected_item, unregister_pointer_protected_item,
)


def _normalize_action(spec):
    if isinstance(spec, QAction):
        if spec._deleted:
            return None
        return {"id": spec._action_key, "label": spec.text(), "action": spec._action_key,
                "_qaction": spec, "enabled": spec.isEnabled(), "visible": spec.isVisible(),
                "checkable": spec.isCheckable(), "checked": spec.isChecked(),
                "children": [], "separator": False, "icon": spec.icon()}
    if isinstance(spec, dict):
        item = dict(spec)
        if isinstance(item.get("_qaction"), QAction):
            return _normalize_action(item["_qaction"])
    elif isinstance(spec, (tuple, list)):
        if len(spec) < 2:
            raise ValueError("menu tuples require at least (label, action)")
        item = {"label": spec[0], "action": spec[1]}
    else:
        raise TypeError("menu item must be a dict, tuple, or list")
    item.setdefault("id", item.get("action") or item.get("label"))
    item.setdefault("label", "")
    item.setdefault("action", None)
    item.setdefault("icon", None)
    item.setdefault("shortcut", None)
    item.setdefault("enabled", True)
    item.setdefault("visible", True)
    item.setdefault("checkable", False)
    item.setdefault("checked", False)
    item.setdefault("separator", item.get("label") == "---")
    item["children"] = [value for child in (item.get("children") or ())
                        if (value := _normalize_action(child)) is not None]
    return item


def _action_objects(specs, thread_id):
    live = set()
    for spec in specs:
        action = spec.get("_qaction")
        if action is not None:
            if action.threadId() != thread_id:
                raise RuntimeError("menu actions must belong to the menu's thread")
            live.add(action)
        live.update(_action_objects(spec.get("children", []), thread_id))
    return live


_MENU_THEME_TAG = "dearuiqt.qt.menu"
_MENU_ROW_THEME_TAGS = {}
_MENU_TEXT_THEME_TAGS = {}


def _exists(backend, item):
    try:
        return bool(item is not None and backend.does_item_exist(item))
    except Exception:
        return False


def _menu_theme(backend):
    # Centralized in DearUIQt.themes so QMenu and application-owned popup
    # surfaces cannot drift to different renderer-specific constants.
    return menu_surface_theme(backend=backend, tag=_MENU_THEME_TAG, cache=True)


def _row_theme(backend, *, hovered=False, disabled=False):
    key = (bool(hovered), bool(disabled))
    cached = _MENU_ROW_THEME_TAGS.get(key)
    if _exists(backend, cached):
        return cached
    p = QtFusionPalette
    tag = "dearuiqt.qt.menu.row.{}.{}".format(
        "hover" if hovered else "normal",
        "disabled" if disabled else "enabled",
    )
    value = make_theme(theme_component(
        ThemeTarget.CHILD_WINDOW,
        colors={
            ThemeColor.CHILD_BACKGROUND:
                p.MENU_HOVER if hovered and not disabled else p.MENU,
            ThemeColor.BORDER: (0, 0, 0, 0),
        },
        styles={
            ThemeStyle.WINDOW_PADDING: (0, 0),
            ThemeStyle.CHILD_BORDER_SIZE: 0,
            ThemeStyle.CHILD_ROUNDING: 0,
            ThemeStyle.ITEM_SPACING: (0, 0),
        },
    ), backend=backend, tag=tag, cache=True)
    _MENU_ROW_THEME_TAGS[key] = value
    return value


def _text_theme(backend, disabled=False):
    key = bool(disabled)
    cached = _MENU_TEXT_THEME_TAGS.get(key)
    if _exists(backend, cached):
        return cached
    p = QtFusionPalette
    tag = "dearuiqt.qt.menu.text.{}".format("disabled" if disabled else "enabled")
    value = make_theme(theme_component(
        ThemeTarget.TEXT,
        colors={ThemeColor.TEXT: p.TEXT_DISABLED if disabled else p.TEXT},
    ), backend=backend, tag=tag, cache=True)
    _MENU_TEXT_THEME_TAGS[key] = value
    return value



class ImGuiMenu(QObject):
    """Reusable icon-capable popup menu rendered only with Dear PyGui.

    The public surface is deliberately QMenu-like, but the implementation is a
    retained Dear ImGui widget.  Submenus are separate popup windows opened on
    row hover; rows support textures, checkable state and runtime enablement.
    """

    # Keep every visual in a row on one explicit pixel grid.  Dear PyGui
    # tables align text, images and drawlists with different internal metrics,
    # which makes menu icons appear a few pixels above/below their labels.
    # QMenu instead owns the complete row geometry, so use fixed gutters and
    # absolute child positions just like a QStyle menu-item layout.
    ROW_HEIGHT = 23
    ICON_SIZE = 16
    # Check indicators share the normal leading icon slot. Reserving a
    # separate check gutter made icon-only context menus look unnecessarily
    # indented whenever one action happened to be checkable.
    CHECK_SLOT = 0
    ICON_SLOT = 22
    ARROW_SLOT = 14
    SHORTCUT_GAP = 22
    ROW_PAD_X = 3
    LABEL_PAD = 5
    # Dear ImGui's text ink sits a few pixels below the item's geometric
    # center while many Win32-derived icon textures have visual mass slightly
    # above their image rect center.  Correct both sides toward one shared
    # optical baseline instead of aligning only their bounding rectangles.
    ICON_Y_NUDGE = 2
    TEXT_Y_NUDGE = -4
    WINDOW_PAD_X = 4
    WINDOW_PAD_Y = 3
    SEPARATOR_PAD_Y = 2
    SEPARATOR_HEIGHT = 1

    def __init__(self, actions=(), *, backend=None, after=None,
                 min_width=150, max_width=420, _parent_menu=None, parent_window=None,
                 parent=None):
        # Submenus are QObject children of their parent menu. Root menus may be
        # parented to a dialog/widget by callers, matching QMenu ownership while
        # leaving the native Dear PyGui popup parent independent.
        qobject_parent = _parent_menu if _parent_menu is not None else parent
        super().__init__(parent=qobject_parent, after=after)
        actions = list(actions or ())
        specs = [value for item in actions if (value := _normalize_action(item)) is not None]
        _action_objects(specs, self.threadId())  # reject before native allocation
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        self.backend = backend
        self.triggered = Signal(self)
        self.aboutToShow = Signal(self)
        self.aboutToHide = Signal(self)
        self._actions = []
        self._action_inputs = []
        self._action_connections = []
        self._has_checkables = False
        self._items = {}
        self._rows = {}
        self._row_specs = {}
        self._handlers = []
        self._submenus = {}
        self._open_submenu = None
        self._arrow_offsets = {}
        self._last_row_click_frame = None
        self._context = None
        self._min_width = int(min_width)
        self._max_width = int(max_width)
        self._parent_menu = _parent_menu
        self._parent_window = parent_window
        self._active_action = None
        self._keyboard_registry = None
        # Popup exclusion is intentionally *logical*, not a viewport-sized
        # transparent Dear ImGui window.  On embedded/native-hosted DPG builds a
        # no-background top-level window can expose the renderer clear surface
        # (black) instead of the widgets beneath it.  QApplication +
        # input_gate.acquire_popup_input() already provide the Qt-style
        # application mouse grab needed to suppress geometry-polled/global
        # handlers without adding any visual surface at all.
        #
        # Keep the old compatibility attributes/methods as inert shims because
        # a few staged-migration collaborators still query them.
        self._input_shield_tag = None
        self._input_shield_top = 0.0
        self.tag = backend.generate_uuid()
        self._popup_input_owned = False
        self._opened_frame = -1
        # Coordinate contract of the most recent popup. Root context menus use
        # desktop screen coordinates; menu-bar/tool-button menus remain
        # renderer/viewport-local. Nested submenus inherit the root contract.
        self._popup_global_position = False
        if parent_window is None:
            # Dear ImGui popup windows are auto-dismissed by the engine the
            # moment any nested popup is opened (the parent popup is dropped
            # from ImGui's popup stack) and they can never be re-shown
            # afterwards: OpenPopup only fires on the show toggle, after which
            # BeginPopup keeps failing and DPG latches ``show=False``. QMenu
            # therefore owns plain top-level windows instead. Click-outside
            # dismissal, keyboard routing and pointer exclusivity already run
            # through QMenu's own handlers and the input gate, so the engine's
            # popup bookkeeping is not needed and actively harmful here.
            with backend.window(
                    tag=self.tag, show=False, width=self._min_width,
                    height=40,
                    # Dear PyGui windows default to min_size=(100, 100). That
                    # silently forces short menus to 100 px tall and leaves a
                    # large blank strip under the final action. QMenu sizes to
                    # its contents instead, so only constrain the width here.
                    min_size=(self._min_width, 1),
                    max_size=(self._max_width, 30000),
                    no_title_bar=True, no_resize=True, no_move=True,
                    no_saved_settings=True, no_scrollbar=True,
                    no_scroll_with_mouse=True):
                pass
        else:
            # Modal dialogs own their ImGui popup stack. Embed the menu in the
            # dialog's render/input hierarchy rather than opening a root popup.
            backend.add_child_window(
                parent=parent_window, tag=self.tag, show=False,
                width=self._min_width, height=40, border=True,
                no_scrollbar=True, no_scroll_with_mouse=True)
        register_pointer_protected_item(self.tag)
        try:
            backend.bind_item_theme(self.tag, _menu_theme(backend))
        except Exception:
            pass
        self.setActions(actions)
        if self._parent_menu is None:
            self._install_keyboard_handlers()


    def _install_keyboard_handlers(self):
        """Install pointer observation and prefer QApplication keyboard routing.

        Historical QMenu instances installed six global key callbacks each.  A
        live QApplication now owns one shared native keyboard bridge and sends
        QKeyEvent to the active popup.  Standalone menus keep the old key
        handlers as a compatibility fallback when no application is present.
        """
        b = self.backend
        central_keyboard = False
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None and application.threadId() == self.threadId():
                central_keyboard = bool(application.installInputBackend(b))
        except Exception:
            central_keyboard = False
        try:
            with b.handler_registry() as registry:
                if not central_keyboard:
                    keys = [b.mvKey_Up, b.mvKey_Down, b.mvKey_Return,
                            b.mvKey_Left, b.mvKey_Right, b.mvKey_Escape]
                    for key in keys:
                        b.add_key_press_handler(
                            key=key, callback=self._key_pressed, user_data=key)
                b.add_mouse_click_handler(
                    button=b.mvMouseButton_Left, callback=self._pointer_clicked)
                b.add_mouse_click_handler(
                    button=b.mvMouseButton_Right, callback=self._pointer_clicked)
            self._keyboard_registry = registry
        except Exception:
            self._keyboard_registry = None

    def _visible_action_ids(self):
        return [
            str(spec.get("action") or spec.get("id") or "")
            for spec in self._actions
            if spec.get("visible", True) and not spec.get("separator")
               and bool(spec.get("enabled", True))
        ]

    def _pointer_frame(self):
        """Return the native input frame, or None for minimal/test backends."""
        try:
            return int(self._root_menu().backend.get_frame_count())
        except Exception:
            return None

    def _opening_pointer_frame(self):
        root = self._root_menu()
        frame = self._pointer_frame()
        return frame is not None and frame == getattr(root, "_opened_frame", -1)

    def _row_click_already_dispatched(self):
        """Deduplicate the global click callback and the drawn-row callback."""
        root = self._root_menu()
        frame = self._pointer_frame()
        if frame is None:
            return False
        if getattr(root, "_last_row_click_frame", None) == frame:
            return True
        root._last_row_click_frame = frame
        return False

    def _pointer_row_rect(self, row):
        """Return the visible screen/viewport rect for a row after scrolling.

        ``dpg_window_rect`` intentionally reconstructs child-window geometry
        without parent scroll offsets. That is useful for layout, but popup
        pointer hit-testing must operate on the row's *painted* position. A
        scrolled combo popup otherwise maps a click to the pre-scroll row and
        returns the wrong model index.
        """
        rect = dpg_window_rect(self.backend, row, clip=False)
        if rect is None:
            return None
        left, top, right, bottom = map(float, rect)
        try:
            scroll_x = float(self.backend.get_x_scroll(self.tag))
        except Exception:
            scroll_x = 0.0
        try:
            scroll_y = float(self.backend.get_y_scroll(self.tag))
        except Exception:
            scroll_y = 0.0
        left -= scroll_x
        right -= scroll_x
        top -= scroll_y
        bottom -= scroll_y

        popup_rect = dpg_window_rect(self.backend, self.tag, clip=False)
        if popup_rect is not None:
            pleft, ptop, pright, pbottom = map(float, popup_rect)
            left = max(left, pleft)
            top = max(top, ptop)
            right = min(right, pright)
            bottom = min(bottom, pbottom)
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom

    def _drawlist_hovered(self, sender=None, app_data=None, user_data=None):
        # A row-wide drawlist anchors the filled triangle at the right edge.
        # DPG treats it as a hit-tested item, so forward hover explicitly.
        self._row_hovered(sender, app_data, user_data)

    def _drawlist_clicked(self, sender=None, app_data=None, user_data=None):
        # The visual drawlist covers the row. Route its click to the same
        # action used by the parent child-window/global pointer dispatcher.
        root = self._root_menu()
        try:
            if not root.backend.is_item_shown(root.tag):
                return
        except Exception:
            return
        if self._opening_pointer_frame() or self._row_click_already_dispatched():
            return
        self._row_clicked(user_data=user_data)

    def _pointer_clicked(self, *_args):
        root = self._root_menu()
        try:
            if not root.backend.is_item_shown(root.tag):
                return
        except Exception:
            return
        # Ignore the mouse gesture that opened the root popup and a click
        # already delivered by the row-wide drawlist in this native frame.
        if self._opening_pointer_frame():
            return
        frame = self._pointer_frame()
        if frame is not None and root._last_row_click_frame == frame:
            return

        x, y = root.backend.get_mouse_pos(local=False)

        # Hit-test each open submenu first, then its ancestors. Clicking
        # another group in the parent must still switch submenus.
        menu = root._deepest_open_menu()
        while menu is not None:
            try:
                visible = bool(menu.backend.is_item_shown(menu.tag))
            except Exception:
                visible = False
            if visible:
                for action, row in tuple(menu._rows.items()):
                    bounds = menu._pointer_row_rect(row)
                    if bounds is None:
                        continue
                    left, top, right, bottom = bounds
                    if left <= x < right and top <= y < bottom:
                        if not root._row_click_already_dispatched():
                            menu._row_clicked(user_data=action)
                        return
            menu = menu._parent_menu

        # A click inside a popup but on separator/padding keeps it open.
        for candidate in root._walk_menus():
            try:
                if not candidate.backend.is_item_shown(candidate.tag):
                    continue
            except Exception:
                continue
            bounds = dpg_window_rect(candidate.backend, candidate.tag, clip=False)
            if bounds is None:
                continue
            left, top, right, bottom = bounds
            if left <= x < right and top <= y < bottom:
                return

        root.hide(consume_pointer=True)

    def _set_active_action(self, action_id):
        action_id = None if action_id is None else str(action_id)
        self._active_action = action_id
        for key in tuple(self._rows):
            self._set_row_hover(key, key == action_id)

    def _deepest_open_menu(self):
        menu = self
        seen = set()
        while menu._open_submenu is not None and id(menu) not in seen:
            seen.add(id(menu))
            child = menu._submenus.get(menu._open_submenu)
            if child is None:
                break
            menu = child
        return menu

    def _key_pressed(self, sender=None, app_data=None, user_data=None):
        return self._handle_key(user_data)

    def _handle_key(self, key):
        root = self._root_menu()
        try:
            if not root.backend.is_item_shown(root.tag):
                return False
        except Exception:
            return False
        menu = root._deepest_open_menu()
        ids = menu._visible_action_ids()
        if key == menu.backend.mvKey_Escape:
            root.hide()
            return True
        if key == menu.backend.mvKey_Left and menu._parent_menu is not None:
            parent = menu._parent_menu
            parent._hide_open_submenu()
            return True
        if not ids:
            return False
        if menu._active_action not in ids:
            menu._set_active_action(ids[0])
        index = ids.index(menu._active_action)
        if key == menu.backend.mvKey_Up:
            menu._set_active_action(ids[(index - 1) % len(ids)])
            return True
        if key == menu.backend.mvKey_Down:
            menu._set_active_action(ids[(index + 1) % len(ids)])
            return True
        spec = menu._row_specs.get(menu._active_action)
        if spec is None:
            return False
        if key == menu.backend.mvKey_Right and spec.get("children"):
            menu._show_submenu(menu._active_action, spec)
            child = menu._submenus.get(menu._active_action)
            if child is not None:
                child_ids = child._visible_action_ids()
                child._set_active_action(child_ids[0] if child_ids else None)
            return True
        if key == menu.backend.mvKey_Return or key == getattr(menu.backend, "mvKey_Enter", None):
            menu._row_clicked(user_data=menu._active_action)
            return True
        return False

    def event(self, event):
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            return bool(self._handle_key(event.key()))
        return super().event(event)

    def setActions(self, actions):
        if self._deleted:
            raise RuntimeError("cannot configure a deleted menu")
        inputs = list(actions or ())
        specs = [value for item in inputs if (value := _normalize_action(item)) is not None]
        live = _action_objects(specs, self.threadId())
        for connection in self._action_connections:
            connection.disconnect()
        self._action_connections.clear()
        self._action_inputs = inputs
        for action in live:
            self._action_connections.extend([
                action.changed.connect(self._refresh_actions),
                action.destroyed.connect(self._action_destroyed),
            ])
        self._actions = specs
        return self._rebuild_action_rows()

    def _action_destroyed(self, action):
        self.setActions(self._current_action_inputs())

    def _current_action_inputs(self):
        # Preserve mutable legacy checked/enabled state while refreshing a
        # neighboring QAction. Re-normalizing the caller's original dicts would
        # silently reset a legacy row to its construction-time state.
        def inputs(specs):
            result = []
            for spec in specs:
                action = spec.get("_qaction")
                if action is not None:
                    if not action._deleted:
                        result.append(action)
                else:
                    item = dict(spec)
                    item["children"] = inputs(spec.get("children", []))
                    result.append(item)
            return result
        return inputs(self._actions)

    def _refresh_actions(self):
        if not self._deleted:
            current = self._active_action
            self.setActions(self._current_action_inputs())
            ids = self._visible_action_ids()
            self._set_active_action(current if current in ids else (ids[0] if ids else None))

    def addAction(self, action):
        if isinstance(action, str):
            action = QAction(action, self)
        if not isinstance(action, QAction):
            raise TypeError("addAction requires QAction or text")
        self.setActions(self._current_action_inputs() + [action])
        return action

    def actions(self):
        return [spec["_qaction"] for spec in self._actions
                if spec.get("_qaction") is not None and not spec["_qaction"]._deleted]

    def removeAction(self, action):
        self.setActions([item for item in self._current_action_inputs() if item is not action])

    def _rebuild_action_rows(self):
        self._clear_rows()
        visible = [spec for spec in self._actions if spec.get("visible", True)]
        # Menus without any checkable actions should not reserve an empty
        # checkmark gutter. This keeps icon+label rows aligned to the left like
        # native Explorer/Qt context menus instead of looking indented.
        self._has_checkables = any(
            bool(spec.get("checkable")) for spec in visible
            if not spec.get("separator")
        )
        width = self._estimate_width(visible)
        height = self.WINDOW_PAD_Y * 2
        separator_height = self.SEPARATOR_PAD_Y * 2 + self.SEPARATOR_HEIGHT
        for spec in visible:
            height += separator_height if spec.get("separator") else self.ROW_HEIGHT
            self._build_row(spec, width)
        try:
            self.backend.configure_item(
                self.tag,
                width=max(self._min_width, min(self._max_width, width)),
                height=max(16, height),
            )
        except Exception:
            pass
        return self

    def _measure_text(self, text):
        """Return stable default-font metrics for menu layout.

        DearPyGui can briefly report invalid metrics before the font atlas has
        rendered its first frame, so keep a deterministic Segoe-like fallback.
        The measured height is also used to vertically center ``add_text`` on
        the same axis as the 16 px icon.
        """
        text = str(text or "")
        try:
            measured = self.backend.get_text_size(text or "Ag")
            if measured is not None and len(measured) >= 2:
                width = float(measured[0])
                height = float(measured[1])
                if width >= 0.0 and height > 0.0:
                    return width, height
        except Exception:
            pass
        return max(0.0, len(text) * 7.0), 14.0

    def _estimate_width(self, specs):
        longest = max(
            (self._measure_text(spec.get("label", ""))[0] for spec in specs
             if not spec.get("separator")),
            default=56.0,
        )
        shortcut_width = max(
            (self._measure_text(spec.get("shortcut", ""))[0] for spec in specs
             if not spec.get("separator") and spec.get("shortcut")),
            default=0.0,
        )
        check_slot = 0
        shortcut_slot = shortcut_width + self.SHORTCUT_GAP if shortcut_width else 0.0
        # Width is expressed in the popup coordinate system, including the
        # outer QMenu padding.  The fixed gutters guarantee that every label
        # starts at exactly the same X regardless of icon/check state while
        # accelerators occupy a dedicated, right-aligned column like QMenu.
        fixed = (
            self.WINDOW_PAD_X * 2 + self.ROW_PAD_X * 2 + check_slot +
            self.ICON_SLOT + self.LABEL_PAD * 2 + self.ARROW_SLOT + shortcut_slot
        )
        return max(
            self._min_width,
            min(self._max_width, int(round(fixed + longest))),
        )

    def _clear_rows(self):
        for submenu in tuple(self._submenus.values()):
            try:
                submenu.delete()
            except Exception:
                pass
        self._submenus.clear()
        self._open_submenu = None
        for registry in tuple(self._handlers):
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass
        self._handlers.clear()
        for child in list(self.backend.get_item_children(self.tag, 1) or []):
            try:
                self.backend.delete_item(child)
            except Exception:
                pass
        self._items.clear()
        self._rows.clear()
        self._row_specs.clear()
        self._arrow_offsets.clear()

    def _glyph_color(self, enabled=True):
        return QtFusionPalette.TEXT if enabled else QtFusionPalette.TEXT_DISABLED

    def _redraw_check(self, canvas, *, checked=False, enabled=True):
        """Paint a compact Qt-style check mark with draw primitives."""
        if canvas is None:
            return
        b = self.backend
        try:
            b.delete_item(canvas, children_only=True)
        except Exception:
            pass
        if not checked:
            return
        color = self._glyph_color(enabled)
        b.draw_line((4, 12), (7, 15), color=color, thickness=1.4, parent=canvas)
        b.draw_line((7, 15), (13, 8), color=color, thickness=1.4, parent=canvas)

    def _sync_leading_indicator(self, spec, items):
        """Keep the compact icon/check slot synchronized for one menu row."""
        if spec is None:
            return
        checked = bool(spec.get("checkable") and spec.get("checked"))
        enabled = bool(spec.get("enabled", True))
        self._redraw_check(items.get("check"), checked=checked, enabled=enabled)
        icon = items.get("icon")
        if icon is not None:
            try:
                self.backend.configure_item(icon, show=not checked)
            except Exception:
                pass

    def _redraw_submenu_arrow(self, canvas, *, visible=False, enabled=True):
        """Paint a compact solid right-facing triangle in the row's right arrow slot."""
        if canvas is None:
            return
        b = self.backend
        try:
            b.delete_item(canvas, children_only=True)
        except Exception:
            pass
        if not visible:
            return
        color = self._glyph_color(enabled)
        x = float(self._arrow_offsets.get(canvas, 0.0))
        # Draw in row coordinates instead of relying on nested drawlist offset
        # placement so submenu indicators stay anchored to the far-right slot.
        b.draw_triangle(
            (x + 6, 8), (x + 12, 12), (x + 6, 16),
            color=color, fill=color, thickness=1.0, parent=canvas,
        )

    def _build_row(self, spec, width):
        b = self.backend
        if spec.get("separator"):
            b.add_spacer(parent=self.tag, height=self.SEPARATOR_PAD_Y)
            b.add_separator(parent=self.tag)
            b.add_spacer(parent=self.tag, height=self.SEPARATOR_PAD_Y)
            return
        action_id = str(spec.get("action") or spec.get("id") or "")
        row_width = max(1, int(width) - self.WINDOW_PAD_X * 2)
        row = b.add_child_window(
            parent=self.tag, width=row_width,
            height=self.ROW_HEIGHT, border=False,
            no_scrollbar=True, no_scroll_with_mouse=True,
        )
        self._rows[action_id] = row
        self._row_specs[action_id] = spec
        try:
            b.bind_item_theme(row, _row_theme(
                b, hovered=False, disabled=not bool(spec.get("enabled", True))))
        except Exception:
            pass

        # Do not use a Dear ImGui table for menu rows. Tables apply different
        # vertical metrics to images, text and drawlists, which produces the
        # visibly staggered icons/baselines seen in popup menus. Position all
        # four QMenu columns in one coordinate system instead.
        check_slot = 0
        check_x = self.ROW_PAD_X
        icon_x = (
            self.ROW_PAD_X + check_slot +
            max(0, (self.ICON_SLOT - self.ICON_SIZE) // 2)
        )
        icon_y = max(
            0,
            (self.ROW_HEIGHT - self.ICON_SIZE) // 2 + self.ICON_Y_NUDGE,
        )
        label_x = self.ROW_PAD_X + check_slot + self.ICON_SLOT + self.LABEL_PAD
        _text_width, text_height = self._measure_text(spec.get("label", ""))
        label_y = max(0, int(round((self.ROW_HEIGHT - text_height) / 2.0)) +
                      self.TEXT_Y_NUDGE)
        arrow_x = max(label_x, row_width - self.ROW_PAD_X - self.ARROW_SLOT)
        shortcut = str(spec.get("shortcut") or "")
        shortcut_width, shortcut_height = self._measure_text(shortcut) if shortcut else (0.0, text_height)
        shortcut_x = max(
            label_x,
            int(round(arrow_x - self.SHORTCUT_GAP - shortcut_width)),
        )
        shortcut_y = max(0, int(round((self.ROW_HEIGHT - shortcut_height) / 2.0)) +
                         self.TEXT_Y_NUDGE)

        check_item = None
        if self._has_checkables:
            # Compact Explorer-style leading column: unchecked actions keep
            # their icon; a checked action replaces that icon with the check
            # mark in the exact same slot. No separate empty gutter is needed.
            check_item = b.add_drawlist(
                parent=row, width=self.ICON_SLOT, height=self.ROW_HEIGHT,
                pos=(check_x, 0),
            )
            self._redraw_check(
                check_item,
                checked=bool(spec.get("checkable") and spec.get("checked")),
                enabled=bool(spec.get("enabled", True)),
            )

        icon_item = None
        icon = spec.get("icon")
        if icon is not None:
            try:
                native_icon = icon.nativeId() if hasattr(icon, "nativeId") else icon
                icon_item = b.add_image(
                    native_icon, parent=row, width=self.ICON_SIZE, height=self.ICON_SIZE,
                    pos=(icon_x, icon_y),
                    show=not bool(spec.get("checkable") and spec.get("checked")),
                )
            except Exception:
                icon_item = None

        label_item = b.add_text(
            str(spec.get("label", "")), parent=row, pos=(label_x, label_y),
        )
        shortcut_item = None
        if shortcut:
            shortcut_item = b.add_text(
                shortcut, parent=row, pos=(shortcut_x, shortcut_y),
            )
        arrow_item = b.add_drawlist(
            parent=row, width=row_width, height=self.ROW_HEIGHT,
            pos=(0, 0),
        )
        self._arrow_offsets[arrow_item] = float(arrow_x)
        self._redraw_submenu_arrow(
            arrow_item,
            visible=bool(spec.get("children")),
            enabled=bool(spec.get("enabled", True)),
        )
        try:
            text_theme = _text_theme(
                b, disabled=not bool(spec.get("enabled", True)))
            b.bind_item_theme(label_item, text_theme)
            if shortcut_item is not None:
                b.bind_item_theme(shortcut_item, text_theme)
        except Exception:
            pass
        self._items[action_id] = {
            "row": row,
            "check": check_item,
            "icon": icon_item,
            "label": label_item,
            "shortcut": shortcut_item,
            "arrow": arrow_item,
        }
        try:
            with b.item_handler_registry() as registry:
                b.add_item_hover_handler(
                    callback=self._row_hovered, user_data=action_id)
            b.bind_item_handler_registry(row, registry)
            self._handlers.append(registry)
        except Exception:
            pass
        try:
            # r115 uses a full-row drawlist for a correctly positioned filled
            # triangle. It can become Dear ImGui's hovered/clicked item instead
            # of the child window, so it must forward both input events.
            with b.item_handler_registry() as registry:
                b.add_item_hover_handler(
                    callback=self._drawlist_hovered, user_data=action_id)
                b.add_item_clicked_handler(
                    button=b.mvMouseButton_Left,
                    callback=self._drawlist_clicked, user_data=action_id)
            b.bind_item_handler_registry(arrow_item, registry)
            self._handlers.append(registry)
        except Exception:
            pass

    def _set_row_hover(self, action_id, hovered):
        spec = self._row_specs.get(action_id)
        row = self._rows.get(action_id)
        if spec is None or row is None:
            return
        try:
            self.backend.bind_item_theme(row, _row_theme(
                self.backend, hovered=bool(hovered),
                disabled=not bool(spec.get("enabled", True))))
        except Exception:
            pass

    def _row_hovered(self, sender=None, app_data=None, user_data=None):
        action_id = str(user_data or "")
        spec = self._row_specs.get(action_id)
        if spec is None:
            return
        self._set_active_action(action_id)
        if spec.get("children") and spec.get("enabled", True):
            self._show_submenu(action_id, spec)
        else:
            self._hide_open_submenu()

    def _row_clicked(self, sender=None, app_data=None, user_data=None):
        action_id = str(user_data or "")
        spec = self._row_specs.get(action_id)
        if spec is None or not spec.get("enabled", True):
            return
        if spec.get("children"):
            self._show_submenu(action_id, spec)
            return
        shared_action = spec.get("_qaction")
        if shared_action is not None:
            if not shared_action.isEnabled() or not shared_action.isVisible():
                return
            root = self._root_menu()
            context = root._context
            root.hide(consume_pointer=True)
            if shared_action.trigger():
                root.triggered.emit(shared_action, context)
            return
        action = str(spec.get("action") or spec.get("id") or "")
        if spec.get("checkable"):
            spec["checked"] = not bool(spec.get("checked"))
            item = self._items.get(action_id, {})
            self._sync_leading_indicator(spec, item)
        root = self._root_menu()
        root.triggered.emit(action, root._context)
        root.hide(consume_pointer=True)

    def _root_menu(self):
        menu = self
        while menu._parent_menu is not None:
            menu = menu._parent_menu
        return menu

    def _show_submenu(self, action_id, spec):
        if self._open_submenu == action_id:
            submenu = self._submenus.get(action_id)
            if submenu is not None and submenu.isVisible():
                return
            # DPG may dismiss a nested popup itself (outside click/focus).
            # Do not leave the old id latched and ignore the next click.
            self._open_submenu = None
        self._hide_open_submenu()
        submenu = self._submenus.get(action_id)
        if submenu is None:
            submenu = ImGuiMenu(
                spec.get("children") or (), backend=self.backend, after=self._after,
                min_width=self._min_width, max_width=self._max_width,
                _parent_menu=self,
                parent_window=self._parent_window,
            )
            # Leaf triggers are emitted by the root menu directly, but keep the
            # signal forwarding useful for programmatic callers/tests.
            self._submenus[action_id] = submenu
        row = self._rows.get(action_id)
        if row is None:
            return False
        # DPG 2.x child windows do not consistently expose rect_min. Use the
        # shared parent-relative window-geometry adapter for global placement.
        rect = dpg_window_rect(self.backend, row, clip=False)
        if rect is None:
            try:
                left, top = self.backend.get_item_rect_min(row)
                width, height = self.backend.get_item_rect_size(row)
                rect = (left, top, left + width, top + height)
            except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
                return False
        left, top, right, _bottom = rect
        # Submenus must stay in the same coordinate space as the root menu.
        # Context menus are opened with desktop/screen coordinates while
        # menu-bar/tool-button menus use renderer-local coordinates. Mixing
        # those spaces is what made a submenu jump to the desktop's left edge
        # when WinUx was moved away from (0, 0).
        root = self._root_menu()
        global_space = bool(getattr(root, "_popup_global_position", False))
        try:
            child_width = float((self.backend.get_item_configuration(submenu.tag) or {}).get('width')
                                or submenu._min_width)
            viewport_width = float(self.backend.get_viewport_client_width())
            if global_space:
                getter = getattr(self.backend, "get_viewport_pos", None)
                viewport = getter() if callable(getter) else (0.0, 0.0)
                viewport_left = float(viewport[0])
                viewport_right = viewport_left + viewport_width
                popup_x = (left - child_width + 2
                           if right - 2 + child_width > viewport_right
                           else right - 2)
                popup_x = max(viewport_left, popup_x)
            else:
                popup_x = (left - child_width + 2
                           if right - 2 + child_width > viewport_width
                           else right - 2)
                popup_x = max(0.0, popup_x)
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
            popup_x = right - 2
        try:
            opener = submenu.popupGlobal if global_space else submenu.popup
            if opener((popup_x, top), context=root._context):
                self._open_submenu = action_id
                return True
        except Exception:
            # UI teardown can race a pending hover/click callback. The submenu
            # remains closed and the next interaction may retry safely.
            return False
        return False

    def _hide_open_submenu(self):
        if self._open_submenu is None:
            return
        submenu = self._submenus.get(self._open_submenu)
        if submenu is not None:
            submenu.hide()
        self._open_submenu = None


    def setInputShieldTop(self, top):
        """Compatibility shim for the retired physical popup shield.

        Popup exclusivity now lives in QApplication/input_gate.  Retaining the
        value is harmless and keeps older callers source-compatible, but no
        viewport-sized Dear ImGui window is ever allocated or shown.
        """
        try:
            self._input_shield_top = max(0.0, float(top))
        except Exception:
            self._input_shield_top = 0.0

    def _show_input_shield(self):
        """Deprecated no-op; popup input is captured logically."""
        return False

    def _hide_input_shield(self):
        """Deprecated no-op retained for staged-migration callers."""
        return None

    def exists(self):
        if self._deleted:
            return False
        try:
            return bool(self.backend.does_item_exist(self.tag))
        except Exception:
            return True

    def isVisible(self):
        if not self.exists():
            return False
        try:
            return bool(self.backend.is_item_shown(self.tag))
        except Exception:
            return False

    def globalGeometry(self, *, clipped=True):
        if not self.exists():
            return QRect()
        if clipped:
            try:
                rect = dpg_window_rect(self.backend, self.tag, clip=True)
                if rect is not None:
                    left, top, right, bottom = rect
                    return QRect(int(round(left)), int(round(top)),
                                 max(0, int(round(right-left))),
                                 max(0, int(round(bottom-top))))
            except Exception:
                pass
        try:
            left, top = self.backend.get_item_rect_min(self.tag)
            width, height = self.backend.get_item_rect_size(self.tag)
            return QRect(int(round(left)), int(round(top)),
                         max(0, int(round(width))), max(0, int(round(height))))
        except Exception:
            return QRect()

    def containsGlobalPoint(self, point):
        point = point if isinstance(point, QPoint) else QPoint(*point)
        return self.globalGeometry(clipped=True).contains(point)

    def containsPopupPoint(self, point):
        """Return whether *point* is inside this menu or an open submenu."""
        point = point if isinstance(point, QPoint) else QPoint(*point)
        if self.isVisible() and self.containsGlobalPoint(point):
            return True
        for submenu in self._submenus.values():
            if submenu.isVisible() and submenu.containsPopupPoint(point):
                return True
        return False

    def navigate(self, command):
        """Drive popup keyboard navigation using a toolkit-neutral command.

        Supported commands are ``up``, ``down``, ``left``, ``right`` and
        ``activate``.  This is intentionally higher-level than renderer key
        codes so embedded views can forward their existing keyboard bridge to
        QMenu during staged migration.
        """
        command = str(command or "").lower()
        root = self._root_menu()
        menu = root._deepest_open_menu()
        ids = menu._visible_action_ids()
        if command in {"up", "down"}:
            if not ids:
                return False
            try:
                index = ids.index(menu._active_action)
            except ValueError:
                index = 0 if command == "down" else len(ids) - 1
            else:
                index = (index + (1 if command == "down" else -1)) % len(ids)
            menu._set_active_action(ids[index])
            return True
        if command == "right":
            spec = menu._row_specs.get(str(menu._active_action or ""))
            if spec and spec.get("children") and spec.get("enabled", True):
                menu._show_submenu(menu._active_action, spec)
                child = menu._submenus.get(menu._active_action)
                if child is not None:
                    child_ids = child._visible_action_ids()
                    child._set_active_action(child_ids[0] if child_ids else None)
                return True
            return False
        if command == "left":
            if menu._parent_menu is not None:
                parent = menu._parent_menu
                menu.hide()
                parent._open_submenu = None
                return True
            return False
        if command == "activate":
            if menu._active_action is not None:
                menu._row_clicked(user_data=menu._active_action)
                return True
            return False
        return False

    def popupGlobal(self, position=None, *, context=None):
        """Open this menu at an unambiguous desktop-screen position.

        Dear PyGui native/embedded Windows builds disagree about whether
        ``get_mouse_pos(local=False)`` is viewport- or desktop-relative. A
        context menu therefore uses Win32's screen cursor and keeps that screen
        coordinate all the way to the top-level popup. The point is clamped to
        the WinUx viewport's *screen* rectangle, so a menu cannot jump to the
        desktop origin when the main window is moved away from (0, 0).
        """
        if position is None:
            from ..gui.system import QCursor
            position = QCursor.screenPos(backend=self.backend).toTuple()
        elif isinstance(position, QPoint):
            position = position.toTuple()
        return self.popup(position, context=context, _global_position=True)

    def popup(self, position=None, *, context=None, _global_position=False):
        self._context = context
        self._popup_global_position = bool(_global_position)
        if self._parent_menu is None:
            self.aboutToShow.emit(context)
        if position is not None:
            try:
                config = self.backend.get_item_configuration(self.tag) or {}
                width = float(config.get("width") or self._min_width)
                height = float(config.get("height") or 40)
                x, y = map(float, position)
                if self._parent_window is not None:
                    bounds = dpg_window_rect(self.backend, self._parent_window)
                    if bounds is not None:
                        left, top, right, bottom = bounds
                        x = max(0.0, min(x - left, right - left - width - 2.0))
                        y = max(0.0, min(y - top, bottom - top - height - 2.0))
                else:
                    viewport_w = float(self.backend.get_viewport_client_width())
                    viewport_h = float(self.backend.get_viewport_client_height())
                    if _global_position:
                        getter = getattr(self.backend, "get_viewport_pos", None)
                        viewport = getter() if callable(getter) else (0.0, 0.0)
                        vx, vy = float(viewport[0]), float(viewport[1])
                        x = max(vx, min(x, max(vx, vx + viewport_w - width - 2.0)))
                        y = max(vy, min(y, max(vy, vy + viewport_h - height - 2.0)))
                    else:
                        # Menu-bar/tool-button anchors and submenus already use
                        # renderer coordinates; preserve their existing contract.
                        x = max(0.0, min(x, max(0.0, viewport_w - width - 2.0)))
                        y = max(0.0, min(y, max(0.0, viewport_h - height - 2.0)))
                position = (x, y)
                self.backend.set_item_pos(self.tag, tuple(position))
            except Exception:
                pass
        acquired_here = False
        try:
            self.backend.configure_item(self.tag, show=True)
            if self._parent_menu is None:
                try:
                    self.backend.focus_item(self.tag)
                except Exception:
                    pass
                try:
                    self._opened_frame = int(self.backend.get_frame_count())
                except Exception:
                    self._opened_frame = -1
            if self._parent_menu is None and not self._popup_input_owned:
                self._popup_input_owned = bool(acquire_popup_input(self))
                acquired_here = self._popup_input_owned
            if self._parent_menu is None:
                try:
                    from ..core.application import QApplication
                    application = QApplication.instance()
                    if application is not None and application.threadId() == self.threadId():
                        application._register_popup(self)
                except Exception:
                    pass
            ids = self._visible_action_ids()
            self._set_active_action(ids[0] if ids else None)
            return True
        except Exception:
            if acquired_here:
                release_popup_input(self, consume_gesture=False)
                self._popup_input_owned = False
            try:
                self.backend.configure_item(self.tag, show=False)
            except Exception:
                pass
            return False

    def hide(self, *, consume_pointer=False):
        self._hide_open_submenu()
        for submenu in tuple(self._submenus.values()):
            try:
                submenu.hide()
            except Exception:
                pass
        hidden = True
        try:
            self.backend.configure_item(self.tag, show=False)
        except Exception:
            hidden = False
        if self._parent_menu is None:
            try:
                from ..core.application import QApplication
                application = QApplication.instance()
                if application is not None and application.threadId() == self.threadId():
                    application._unregister_popup(self)
            except Exception:
                pass
            # The popup release latch below consumes the closing gesture for
            # global handlers in the current frame.  No visual shield exists.
            # Never strand a popup mouse grab because the renderer rejected a
            # hide/configure call during shutdown or context recreation.
            if self._popup_input_owned:
                release_popup_input(self, consume_gesture=bool(consume_pointer))
                self._popup_input_owned = False
            if hidden:
                self.aboutToHide.emit(self._context)
        return hidden

    def context(self):
        return self._context

    def _find_spec(self, action):
        target = str(action)
        stack = list(self._actions)
        while stack:
            spec = stack.pop(0)
            if str(spec.get("action") or spec.get("id") or "") == target:
                return spec
            stack[0:0] = list(spec.get("children") or ())
        return None

    def setActionEnabled(self, action, enabled):
        if isinstance(action, QAction):
            action.setEnabled(enabled)
            return
        target = str(action)
        spec = self._find_spec(target)
        if spec is None:
            return False
        spec["enabled"] = bool(enabled)
        # Specs that live in a child menu need their child renderer updated.
        for menu in self._walk_menus():
            local_spec = menu._row_specs.get(target)
            if local_spec is None:
                continue
            local_spec["enabled"] = bool(enabled)
            menu._set_row_hover(target, False)
            items = menu._items.get(target, {})
            for text_item in (items.get("label"), items.get("shortcut")):
                if text_item is not None:
                    try:
                        menu.backend.bind_item_theme(
                            text_item, _text_theme(menu.backend, disabled=not bool(enabled)))
                    except Exception:
                        pass
            menu._sync_leading_indicator(local_spec, items)
            menu._redraw_submenu_arrow(
                items.get("arrow"), visible=bool(local_spec.get("children")),
                enabled=bool(enabled))
            return True
        return True

    def setActionChecked(self, action, checked):
        if isinstance(action, QAction):
            action.setChecked(checked)
            return
        target = str(action)
        spec = self._find_spec(target)
        if spec is None:
            return False
        spec["checked"] = bool(checked)
        for menu in self._walk_menus():
            local_spec = menu._row_specs.get(target)
            if local_spec is None:
                continue
            local_spec["checked"] = bool(checked)
            items = menu._items.get(target, {})
            menu._sync_leading_indicator(local_spec, items)
            return True
        return True

    def isActionChecked(self, action):
        """Return the checked state for a checkable action id/QAction."""
        if isinstance(action, QAction):
            return bool(action.isChecked())
        spec = self._find_spec(action)
        return bool(spec is not None and spec.get("checkable") and spec.get("checked"))

    def _walk_menus(self):
        yield self
        for submenu in tuple(self._submenus.values()):
            yield from submenu._walk_menus()

    def delete(self):
        if self._deleted:
            return
        if self._parent_menu is None:
            try:
                from ..core.application import QApplication
                application = QApplication.instance()
                if application is not None and application.threadId() == self.threadId():
                    application._unregister_popup(self)
            except Exception:
                pass
        if self._parent_menu is None and self._popup_input_owned:
            release_popup_input(self, consume_gesture=False)
            self._popup_input_owned = False
        unregister_pointer_protected_item(self.tag)
        self._clear_rows()
        if self._keyboard_registry is not None:
            try:
                if self.backend.does_item_exist(self._keyboard_registry):
                    self.backend.delete_item(self._keyboard_registry)
            except Exception:
                pass
            self._keyboard_registry = None
        try:
            if self.backend.does_item_exist(self.tag):
                self.backend.delete_item(self.tag)
            shield = self._input_shield_tag
            if shield is not None and self.backend.does_item_exist(shield):
                self.backend.delete_item(shield)
            self._input_shield_tag = None
        finally:
            try:
                super().delete()
            finally:
                self._action_inputs.clear()
                self._action_connections.clear()


QMenu = ImGuiMenu

__all__ = ["ImGuiMenu", "QMenu"]
