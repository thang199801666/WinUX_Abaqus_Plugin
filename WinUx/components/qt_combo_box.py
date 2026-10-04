"""Qt/Fusion-like editable combo box built only from Dear PyGui primitives.

This module intentionally contains no Qt/Tk/native-widget dependency.  The
editor is a real ``mvInputText`` so Dear ImGui owns text editing and the caret;
the arrow is a small drawlist hit target inside the same framed shell, and the
popup is a DPG popup window containing selectables.  The triangle is geometry,
not a font glyph, so Windows font fallback cannot turn it into a replacement
symbol.  The control therefore
looks like one QComboBox while keeping the InputText completely unobstructed.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from .qt_style import QtFusionPalette, QtFusionMetrics
from ..widgets.core import Signal
from ..widgets.imgui_qt_style import METRICS
from .interaction_gate import (
    register_pointer_protected_item,
    unregister_pointer_protected_item,
)


_SHELL_THEME = "winux.qt_combo.shell.normal"
_FOCUSED_SHELL_THEME = "winux.qt_combo.shell.focus"
_DISABLED_SHELL_THEME = "winux.qt_combo.shell.disabled"
_INPUT_THEME = "winux.qt_combo.editor.normal"
_DISABLED_INPUT_THEME = "winux.qt_combo.editor.disabled"
_ARROW_THEME = "winux.qt_combo.arrow.normal"
_DISABLED_ARROW_THEME = "winux.qt_combo.arrow.disabled"
_POPUP_THEME = "winux.qt_combo.popup"


def _shell_theme(*, focused=False, disabled=False):
    tag = (_DISABLED_SHELL_THEME if disabled else
           (_FOCUSED_SHELL_THEME if focused else _SHELL_THEME))
    if dpg.does_item_exist(tag):
        return tag
    p = QtFusionPalette
    border = p.BORDER_LIGHT if disabled else (p.FOCUS if focused else p.BORDER)
    background = p.BUTTON_DISABLED if disabled else p.BASE
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, background)
            dpg.add_theme_color(dpg.mvThemeCol_Border, border)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 1)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1)
        with dpg.theme_component(dpg.mvTable):
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 0, 0)
    return tag


def _input_theme(*, disabled=False):
    tag = _DISABLED_INPUT_THEME if disabled else _INPUT_THEME
    if dpg.does_item_exist(tag):
        return tag
    p = QtFusionPalette
    bg = p.BUTTON_DISABLED if disabled else p.BASE
    text = p.TEXT_DISABLED if disabled else p.TEXT
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvInputText):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, bg)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, bg)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, bg)
            dpg.add_theme_color(dpg.mvThemeCol_Text, text)
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            cursor_role = getattr(dpg, "mvThemeCol_InputTextCursor", None)
            if cursor_role is not None:
                # Explicit cursor colour fixes the light-theme case where the
                # bundled Dear ImGui can inherit a cursor too close to white.
                dpg.add_theme_color(cursor_role, p.TEXT_DISABLED if disabled else p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (0, 120, 215, 115))
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 4)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
    return tag


def _arrow_theme(*, disabled=False):
    tag = _DISABLED_ARROW_THEME if disabled else _ARROW_THEME
    if dpg.does_item_exist(tag):
        return tag
    p = QtFusionPalette
    face = p.BUTTON_DISABLED if disabled else p.BASE
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, face)
            dpg.add_theme_color(
                dpg.mvThemeCol_ButtonHovered,
                face if disabled else p.HIGHLIGHT_HOVER,
            )
            dpg.add_theme_color(
                dpg.mvThemeCol_ButtonActive,
                face if disabled else p.HIGHLIGHT_SOFT,
            )
            dpg.add_theme_color(
                dpg.mvThemeCol_Text,
                p.TEXT_DISABLED if disabled else p.TEXT,
            )
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BASE)
            # The outer combo shell owns the focus frame.  Keep the arrow
            # sub-control from drawing a second navigation rectangle, and
            # explicitly center the small down-triangle like QStyle does.
            dpg.add_theme_color(dpg.mvThemeCol_NavHighlight, face)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
            text_align = getattr(dpg, "mvStyleVar_ButtonTextAlign", None)
            if text_align is not None:
                dpg.add_theme_style(text_align, 0.5, 0.48)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            # One outer frame owns the whole control.  A second button border
            # makes the combo look like two widgets glued together, so the
            # arrow sub-control is intentionally borderless.
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
    return tag



def _separator_theme():
    tag = "winux.qt_combo.separator"
    if dpg.does_item_exist(tag):
        return tag
    p = QtFusionPalette
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.BORDER_LIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER_LIGHT)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return tag

def _popup_theme():
    if dpg.does_item_exist(_POPUP_THEME):
        return _POPUP_THEME
    p = QtFusionPalette
    with dpg.theme(tag=_POPUP_THEME):
        with dpg.theme_component(dpg.mvWindowAppItem):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, p.MENU)
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, p.MENU)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 2, 2)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 1)
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_color(dpg.mvThemeCol_Header, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.MENU_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.MENU_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 4)
            dpg.add_theme_style(dpg.mvStyleVar_SelectableTextAlign, 0.0, 0.5)
    return _POPUP_THEME


class ImGuiComboBox:
    """Editable QComboBox-like control implemented entirely in Dear PyGui.

    The text editor itself is never covered by an invisible item and is never
    re-focused from a click callback.  A normal mouse click therefore reaches
    Dear ImGui's InputText directly, preserving its native insertion cursor and
    caret placement.  Focus styling is painted on the outer shell only.
    """

    ARROW_WIDTH = METRICS.arrow_width
    CONTROL_HEIGHT = METRICS.control_height
    POPUP_ROW_HEIGHT = METRICS.popup_row_height
    MAX_VISIBLE_ROWS = 8

    def __init__(self, items=(), default_value=None, width=-1,
                 callback=None, parent=None, editable=True, tag=None):
        self.items = [str(item) for item in items]
        self.callback = callback
        self.editable = bool(editable)
        self.enabled = True
        self.currentTextChanged = Signal()
        self.currentIndexChanged = Signal()
        self.activated = Signal()
        self.editTextChanged = Signal()
        self.width = int(width) if width is not None else -1
        self.parent = parent
        self.tag = tag or dpg.generate_uuid()
        self._handlers = dpg.generate_uuid()
        self._input_handlers = dpg.generate_uuid()
        self._button_handlers = dpg.generate_uuid()
        self._value = (str(default_value) if default_value is not None
                       else (self.items[0] if self.items else ""))
        self._popup = None
        self._popup_items = []
        self._popup_index = -1
        self._max_visible_items = self.MAX_VISIBLE_ROWS

        shell_width = self.width if self.width >= 0 else -1
        self.container = dpg.add_child_window(
            parent=parent or 0,
            width=shell_width,
            height=self.CONTROL_HEIGHT + 2,
            border=True,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        self.shell = self.container
        dpg.bind_item_theme(self.shell, _shell_theme())

        with dpg.table(
            parent=self.shell,
            header_row=False,
            width=-1,
            height=self.CONTROL_HEIGHT,
            policy=dpg.mvTable_SizingStretchProp,
            pad_outerX=False,
            borders_innerH=False,
            borders_outerH=False,
            borders_innerV=False,
            borders_outerV=False,
        ):
            dpg.add_table_column(width_stretch=True, init_width_or_weight=1.0)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=1)
            dpg.add_table_column(
                width_fixed=True, init_width_or_weight=self.ARROW_WIDTH)
            with dpg.table_row():
                self.input = dpg.add_input_text(
                    tag=self.tag,
                    default_value=self._value,
                    width=-1,
                    readonly=not self.editable,
                    callback=self._input_changed,
                    on_enter=False,
                    auto_select_all=False,
                )
                self.separator = dpg.add_child_window(
                    width=1, height=self.CONTROL_HEIGHT, border=False,
                    no_scrollbar=True, no_scroll_with_mouse=True,
                )
                self.button = dpg.add_drawlist(
                    width=self.ARROW_WIDTH,
                    height=self.CONTROL_HEIGHT,
                )
                cx = self.ARROW_WIDTH * 0.5
                cy = self.CONTROL_HEIGHT * 0.5 + 0.5
                self._arrow_triangle = dpg.draw_triangle(
                    (cx - 4.0, cy - 2.0),
                    (cx + 4.0, cy - 2.0),
                    (cx, cy + 2.5),
                    color=QtFusionPalette.TEXT,
                    fill=QtFusionPalette.TEXT,
                    parent=self.button,
                )

        # Compatibility names retained for existing callers/tests.
        self.search = None
        self.listbox = self.button

        dpg.bind_item_theme(self.input, _input_theme())
        dpg.bind_item_theme(self.separator, _separator_theme())
        self._render_arrow()
        self._create_popup()
        self._install_input_state_handlers()
        self._install_button_state_handlers()
        self._install_handlers()
        self._refresh_shell_theme()

    # ------------------------------------------------------------------ API
    def current_text(self):
        return str(dpg.get_value(self.input) or "")

    currentText = current_text

    def current_index(self):
        value = self.current_text()
        try:
            return self.items.index(value)
        except ValueError:
            return -1

    currentIndex = current_index

    def set_current_index(self, index, emit=False):
        if not self.items:
            self.set_current_text("", emit=emit)
            return -1
        index = max(0, min(int(index), len(self.items) - 1))
        self.set_current_text(self.items[index], emit=emit)
        return index

    setCurrentIndex = set_current_index

    def set_current_text(self, value, emit=False):
        old_text = self.current_text() if dpg.does_item_exist(self.input) else self._value
        old_index = self.current_index() if dpg.does_item_exist(self.input) else -1
        self._value = str(value or "")
        if dpg.does_item_exist(self.input):
            dpg.set_value(self.input, self._value)
        new_index = self.current_index() if dpg.does_item_exist(self.input) else -1
        self._sync_popup_selection()
        if old_text != self._value:
            self.currentTextChanged.emit(self._value)
        if old_index != new_index:
            self.currentIndexChanged.emit(new_index)
        if emit and callable(self.callback):
            self.callback(self.input, self._value, self)

    setCurrentText = set_current_text

    def add_items(self, items):
        self.items.extend(str(item) for item in items)
        self._rebuild_popup_items()

    addItems = add_items

    def addItem(self, text):
        self.add_items([text])

    def count(self):
        return len(self.items)

    def itemText(self, index):
        index = int(index)
        return self.items[index] if 0 <= index < len(self.items) else ""

    def setEditable(self, editable):
        self.editable = bool(editable)
        if dpg.does_item_exist(self.input):
            dpg.configure_item(self.input, readonly=not self.editable)

    def isEditable(self):
        return bool(self.editable)

    def clear(self):
        self.items = []
        self._popup_index = -1
        self._rebuild_popup_items()
        self.set_current_text("")

    def setMaxVisibleItems(self, count):
        self._max_visible_items = max(1, int(count))

    def maxVisibleItems(self):
        return int(self._max_visible_items)

    def set_enabled(self, enabled=True):
        self.enabled = bool(enabled)
        if dpg.does_item_exist(self.input):
            dpg.configure_item(self.input, enabled=self.enabled)
            dpg.bind_item_theme(self.input, _input_theme(disabled=not self.enabled))
        # Drawlists do not expose an enabled flag.  The click callback checks
        # ``self.enabled`` and the triangle is recoloured explicitly.
        self._render_arrow()
        if not self.enabled:
            self.close_popup()
        self._refresh_shell_theme()
        return self

    setEnabled = set_enabled

    def isEnabled(self):
        return bool(self.enabled)

    def popup_open(self):
        if not self._popup or not dpg.does_item_exist(self._popup):
            return False
        try:
            return bool(dpg.is_item_shown(self._popup))
        except Exception:
            return False

    def _render_arrow(self):
        """Keep the geometric arrow without reconfiguring draw commands.

        Dear PyGui 2.3.1 on Windows can raise a C-extension SystemError when
        ``configure_item`` is used to mutate draw-triangle colour/fill after
        creation.  The combo remains functionally disabled through
        ``self.enabled``/``open_popup``; the arrow itself is deliberately
        static so startup never touches the unsafe draw-item configure path.
        """
        return

    def _popup_geometry(self):
        x, y = dpg.get_item_rect_min(self.shell)
        width, height = dpg.get_item_rect_size(self.shell)
        rows = max(1, min(len(self.items), self._max_visible_items))
        popup_width = max(80, int(width))
        popup_height = rows * self.POPUP_ROW_HEIGHT + 4
        try:
            viewport_width = int(dpg.get_viewport_client_width())
            viewport_height = int(dpg.get_viewport_client_height())
        except Exception:
            viewport_width = max(popup_width, int(x + popup_width))
            viewport_height = max(popup_height, int(y + height + popup_height))
        popup_x = max(0, min(int(x), max(0, viewport_width - popup_width)))
        below_y = int(y + height)
        above_y = int(y - popup_height)
        popup_y = below_y if below_y + popup_height <= viewport_height else max(0, above_y)
        return popup_x, popup_y, popup_width, popup_height

    def _scroll_popup_to_index(self, index):
        if index < 0 or not self._popup or not dpg.does_item_exist(self._popup):
            return
        try:
            visible = max(1, self._max_visible_items)
            first = max(0, index - visible + 1)
            dpg.set_y_scroll(self._popup, first * self.POPUP_ROW_HEIGHT)
        except Exception:
            pass

    def open_popup(self):
        if not self.enabled or not self.items:
            return
        if not self._popup or not dpg.does_item_exist(self._popup):
            self._create_popup()
        try:
            self._popup_index = self.current_index()
            if self._popup_index < 0:
                self._popup_index = 0
            self._sync_popup_selection(self._popup_index)
            x, y, width, height = self._popup_geometry()
            # Configure while hidden, then reveal at the final position.  This
            # mirrors QComboBox popup placement and avoids a one-frame jump.
            dpg.configure_item(self._popup, width=width, height=height, show=False)
            dpg.set_item_pos(self._popup, (x, y))
            self._scroll_popup_to_index(self._popup_index)
            dpg.configure_item(self._popup, show=True)
            dpg.focus_item(self._popup)
        except Exception:
            pass
        self._refresh_shell_theme()

    showPopup = open_popup

    def close_popup(self):
        if self._popup and dpg.does_item_exist(self._popup):
            try:
                dpg.configure_item(self._popup, show=False)
            except Exception:
                pass
        self._popup_index = -1
        self._sync_popup_selection()
        self._refresh_shell_theme()

    hidePopup = close_popup

    def toggle_popup(self, sender=None, app_data=None, user_data=None):
        if self.popup_open():
            self.close_popup()
        else:
            self.open_popup()

    def focus_editor(self):
        """Compatibility helper for explicit keyboard navigation focus only.

        Do not call this from a mouse-click handler. Mouse clicks must be left
        entirely to ImGui InputText so the native insertion point/caret survives.
        """
        if self.enabled and dpg.does_item_exist(self.input):
            try:
                dpg.focus_item(self.input)
            except Exception:
                pass

    # -------------------------------------------------------------- popup
    def _create_popup(self):
        if self._popup and dpg.does_item_exist(self._popup):
            return
        self._popup = dpg.add_window(
            popup=True,
            show=False,
            no_title_bar=True,
            no_move=True,
            no_resize=True,
            no_collapse=True,
            no_saved_settings=True,
            width=160,
            height=100,
        )
        dpg.bind_item_theme(self._popup, _popup_theme())
        # Dear PyGui global mouse handlers continue firing behind popup
        # windows. Register this popup as a protected foreground surface so
        # Explorer/ListView drag, selection and splitters never receive the
        # same click used to choose a combo item.
        register_pointer_protected_item(self._popup)
        self._rebuild_popup_items()

    def _rebuild_popup_items(self):
        if not self._popup or not dpg.does_item_exist(self._popup):
            return
        for item in list(self._popup_items):
            if dpg.does_item_exist(item):
                dpg.delete_item(item)
        self._popup_items = []
        current = self.current_text() if dpg.does_item_exist(self.input) else self._value
        for value in self.items:
            tag = dpg.add_selectable(
                parent=self._popup,
                label=value,
                width=-1,
                default_value=(value == current),
                callback=self._popup_selected,
                user_data=value,
            )
            self._popup_items.append(tag)

    def _sync_popup_selection(self, index=None):
        """Mirror QComboBox current-index/highlight state in the popup list."""
        if index is None:
            current = self.current_text() if dpg.does_item_exist(self.input) else self._value
            index = self.items.index(current) if current in self.items else -1
        for row, item in enumerate(self._popup_items):
            if dpg.does_item_exist(item):
                try:
                    dpg.set_value(item, row == index)
                except Exception:
                    pass

    def _popup_selected(self, sender=None, app_data=None, user_data=None):
        value = str(user_data if user_data is not None else "")
        self.set_current_text(value, emit=True)
        self.activated.emit(self.current_index())
        self.close_popup()

    # -------------------------------------------------------------- behavior
    @staticmethod
    def _item_focused(tag):
        if not tag or not dpg.does_item_exist(tag):
            return False
        try:
            state = dpg.get_item_state(tag) or {}
            return bool(state.get("focused", False) or state.get("active", False))
        except Exception:
            return False

    def _owns_keyboard(self):
        return bool(
            self._item_focused(self.input)
            or self._item_focused(self.button)
            or self.popup_open()
        )

    def _refresh_shell_theme(self, *_args):
        if not self.shell or not dpg.does_item_exist(self.shell):
            return
        focused = self.enabled and self._owns_keyboard()
        dpg.bind_item_theme(
            self.shell,
            _shell_theme(focused=focused, disabled=not self.enabled),
        )
        self._render_arrow()

    def _install_input_state_handlers(self):
        try:
            with dpg.item_handler_registry(tag=self._input_handlers):
                # Do NOT install a clicked handler here.  Programmatic
                # focus_item() from a click callback converts InputText to nav
                # focus on some DPG builds and is the reason WinUx showed a blue
                # focus frame without a blinking insertion caret.
                if hasattr(dpg, "add_item_focus_handler"):
                    dpg.add_item_focus_handler(callback=self._refresh_shell_theme)
                if hasattr(dpg, "add_item_activated_handler"):
                    dpg.add_item_activated_handler(callback=self._refresh_shell_theme)
                if hasattr(dpg, "add_item_deactivated_handler"):
                    dpg.add_item_deactivated_handler(callback=self._refresh_shell_theme)
            dpg.bind_item_handler_registry(self.input, self._input_handlers)
        except Exception:
            self._input_handlers = None

    def _install_button_state_handlers(self):
        try:
            with dpg.item_handler_registry(tag=self._button_handlers):
                dpg.add_item_clicked_handler(
                    button=dpg.mvMouseButton_Left,
                    callback=self.toggle_popup,
                )
                if hasattr(dpg, "add_item_activated_handler"):
                    dpg.add_item_activated_handler(callback=self._refresh_shell_theme)
                if hasattr(dpg, "add_item_deactivated_handler"):
                    dpg.add_item_deactivated_handler(callback=self._refresh_shell_theme)
            dpg.bind_item_handler_registry(self.button, self._button_handlers)
        except Exception:
            self._button_handlers = None

    def _install_handlers(self):
        try:
            with dpg.handler_registry(tag=self._handlers):
                for key_name, callback in (
                    ("mvKey_F4", self._f4_pressed),
                    ("mvKey_Escape", self._escape_pressed),
                    ("mvKey_Up", self._up_pressed),
                    ("mvKey_Down", self._down_pressed),
                    ("mvKey_Return", self._return_pressed),
                ):
                    key = getattr(dpg, key_name, None)
                    if key is not None:
                        dpg.add_key_press_handler(key=key, callback=callback)
        except Exception:
            self._handlers = None

    def _f4_pressed(self, sender=None, app_data=None, user_data=None):
        if self._owns_keyboard() and self.enabled:
            self.toggle_popup()

    def _escape_pressed(self, sender=None, app_data=None, user_data=None):
        if self.popup_open():
            self.close_popup()

    def _move_popup_highlight(self, delta):
        if not self.items:
            return
        index = self._popup_index if self._popup_index >= 0 else self.current_index()
        if index < 0:
            index = 0
        self._popup_index = max(0, min(len(self.items) - 1, index + int(delta)))
        self._sync_popup_selection(self._popup_index)
        self._scroll_popup_to_index(self._popup_index)

    def _up_pressed(self, sender=None, app_data=None, user_data=None):
        if not self.enabled:
            return
        if self.popup_open():
            self._move_popup_highlight(-1)
            return
        if not self._item_focused(self.input):
            return
        index = self.current_index()
        self.set_current_index((index if index >= 0 else 0) - 1, emit=True)

    def _down_pressed(self, sender=None, app_data=None, user_data=None):
        if not self.enabled:
            return
        if self.popup_open():
            self._move_popup_highlight(1)
            return
        if not self._item_focused(self.input):
            return
        index = self.current_index()
        self.set_current_index((index if index >= 0 else -1) + 1, emit=True)

    def _return_pressed(self, sender=None, app_data=None, user_data=None):
        if not self.popup_open() or not self.enabled:
            return
        index = self._popup_index
        if 0 <= index < len(self.items):
            self.set_current_text(self.items[index], emit=True)
            self.activated.emit(index)
        self.close_popup()

    def _input_changed(self, sender=None, app_data=None, user_data=None):
        value = self.current_text()
        old = self._value
        old_index = self.items.index(old) if old in self.items else -1
        self._value = value
        new_index = self.current_index()
        self._sync_popup_selection()
        if value != old:
            self.editTextChanged.emit(value)
            self.currentTextChanged.emit(value)
        if old_index != new_index:
            self.currentIndexChanged.emit(new_index)
        if callable(self.callback):
            self.callback(self.input, value, self)

    def destroy(self):
        if self._popup:
            unregister_pointer_protected_item(self._popup)
        for item in (
            self._handlers,
            self._input_handlers,
            self._button_handlers,
            self._popup,
            self.separator,
            self.container,
        ):
            if item and dpg.does_item_exist(item):
                dpg.delete_item(item)


QtComboBox = ImGuiComboBox

__all__ = ["ImGuiComboBox", "QtComboBox"]
