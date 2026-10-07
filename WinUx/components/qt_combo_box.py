"""Qt/Fusion-like editable combo box implemented with Dear PyGui only.

The editable text field and the history drop-down share one visual shell, but
use Dear ImGui's native combo popup stack so the list remains visible above
modal dialogs.  The input is submitted first and reserves the arrow strip; a
full-width transparent ``mvCombo`` is then drawn over the shell.  ImGui's
first-item hover rule leaves text clicks with the input while the uncovered
right-hand arrow remains owned by the combo.  Because the combo itself spans
the complete shell, its native drop-down inherits the full control width.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from .qt_style import QtFusionPalette
from ..widgets.core import Signal
from ..widgets.imgui_qt_style import METRICS


_SHELL_THEME = "winux.qt_combo.shell.normal"
_FOCUSED_SHELL_THEME = "winux.qt_combo.shell.focus"
_DISABLED_SHELL_THEME = "winux.qt_combo.shell.disabled"
_INPUT_THEME = "winux.qt_combo.editor.normal"
_DISABLED_INPUT_THEME = "winux.qt_combo.editor.disabled"
_ARROW_THEME = "winux.qt_combo.arrow.normal"
_DISABLED_ARROW_THEME = "winux.qt_combo.arrow.disabled"


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
            # One real table border is the Qt-style separator between the
            # editable field and the native combo arrow.  This remains exactly
            # one physical line instead of consuming a layout column.
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, (220, 220, 220, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderStrong, (220, 220, 220, 255))
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
                dpg.add_theme_color(cursor_role, p.TEXT_DISABLED if disabled else p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (0, 120, 215, 115))
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 4)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
    return tag


def _arrow_theme(*, disabled=False):
    """Theme the full-width native combo frame and its Qt arrow sub-control."""
    tag = _DISABLED_ARROW_THEME if disabled else _ARROW_THEME
    if dpg.does_item_exist(tag):
        return tag
    p = QtFusionPalette
    base = (0, 0, 0, 0)
    # Qt/Fusion keeps the arrow area only subtly different from the editor.
    # That visual edge replaces the old thick separator strip.
    arrow = p.BUTTON_DISABLED if disabled else (248, 248, 248, 255)
    face = arrow  # compatibility name: suppress a nested nav-focus rectangle
    hover = arrow if disabled else (238, 238, 238, 255)
    active = arrow if disabled else (226, 226, 226, 255)
    text = p.TEXT_DISABLED if disabled else p.TEXT
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvCombo):
            # The combo spans the whole shell only to own a modal-safe native
            # popup.  Its preview frame stays transparent so the real editable
            # InputText underneath remains the visible editor.
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, base)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, base)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, base)
            dpg.add_theme_color(dpg.mvThemeCol_Button, arrow)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, active)
            dpg.add_theme_color(dpg.mvThemeCol_Text, text)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_NavHighlight, face)
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Header, p.SELECTION_INACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.HIGHLIGHT_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.HIGHLIGHT_SOFT)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 2, 4)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, 1)
            dpg.add_theme_style(dpg.mvStyleVar_PopupBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 2, 2)
    return tag


class ImGuiComboBox:
    """Editable QComboBox-like retained control with reliable text editing.

    A borderless ``mvInputText`` owns the editable area while a transparent,
    full-width native ``mvCombo`` owns the arrow and modal-safe history popup.
    The input is submitted first and stops before the arrow strip, so text
    clicks still activate the real editor even though both controls share the
    same visual shell.
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
        self._geometry_handlers = dpg.generate_uuid()
        self._max_visible_items = self.MAX_VISIBLE_ROWS
        self._native_popup_hint = False
        self._value = str(default_value if default_value is not None else
                          (self.items[0] if self.items else ""))

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

        # The editor is submitted before the transparent popup owner and stops
        # before the arrow strip.  ImGui therefore gives text-region hover/click
        # ownership to InputText, while only the uncovered right-hand strip is
        # available to the native combo's arrow.
        self._row = dpg.add_group(
            parent=self.shell, horizontal=True, horizontal_spacing=0, pos=(1, 1))

        editor_right_reserve = self.ARROW_WIDTH + 1
        self.input = dpg.add_input_text(
            tag=self.tag,
            parent=self._row,
            default_value=self._value,
            width=-editor_right_reserve,
            readonly=not self.editable,
            callback=self._input_changed,
            on_enter=False,
            auto_select_all=False,
        )
        dpg.bind_item_theme(self.input, _input_theme())

        # Native modal-safe popup owner.  This combo deliberately spans the
        # complete shell so Dear ImGui gives its drop-down the same minimum
        # width.  It is created *after* the editor, while the editor itself is
        # narrower by ARROW_WIDTH.  Therefore InputText wins hit testing over
        # the text region and the combo wins only in the uncovered arrow strip.
        # The preview value is kept empty and the frame is transparent, so the
        # user sees exactly one editor rather than two overlapping controls.
        self.button = dpg.add_combo(
            self.items,
            label="",
            parent=self.shell,
            pos=(0, 0),
            width=-1,
            default_value="",
            no_preview=False,
            popup_align_left=True,
            fit_width=False,
            callback=self._native_selected,
        )
        dpg.bind_item_theme(self.button, _arrow_theme())

        # Compatibility names retained for callers written against earlier
        # wrappers. The native combo itself is the popup/list owner.
        self.search = None
        self.listbox = self.button
        self.separator = None
        self._popup = None
        self._popup_items = []
        self._popup_index = -1

        self._install_input_state_handlers()
        self._install_button_state_handlers()
        self._install_geometry_handlers()
        self._install_handlers()
        self._refresh_shell_theme()

    def _native_value_for(self, text):
        text = str(text or "")
        if text in self.items:
            return text
        return self.items[0] if self.items else ""

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
        try:
            old_index = self.items.index(old_text)
        except ValueError:
            old_index = -1
        self._value = str(value or "")
        if dpg.does_item_exist(self.input):
            dpg.set_value(self.input, self._value)
        if self.button and dpg.does_item_exist(self.button):
            # Keep the overlay preview blank; selection is mirrored only into
            # the editable InputText.  The history list remains unchanged.
            dpg.set_value(self.button, "")
        new_index = self.current_index() if dpg.does_item_exist(self.input) else -1
        if old_text != self._value:
            self.currentTextChanged.emit(self._value)
        if old_index != new_index:
            self.currentIndexChanged.emit(new_index)
        if emit and callable(self.callback):
            self.callback(self.input, self._value, self)

    setCurrentText = set_current_text

    def add_items(self, items):
        self.items.extend(str(item) for item in items)
        self._sync_native_items()

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
        self._sync_native_items()
        self.set_current_text("")

    def setMaxVisibleItems(self, count):
        # Dear ImGui owns native combo popup sizing. Keep the Qt-compatible API
        # for callers even though DPG exposes only coarse combo height modes.
        self._max_visible_items = max(1, int(count))

    def maxVisibleItems(self):
        return int(self._max_visible_items)

    def set_enabled(self, enabled=True):
        self.enabled = bool(enabled)
        if dpg.does_item_exist(self.input):
            dpg.configure_item(self.input, enabled=self.enabled)
            dpg.bind_item_theme(self.input, _input_theme(disabled=not self.enabled))
        if self.button and dpg.does_item_exist(self.button):
            dpg.configure_item(self.button, enabled=self.enabled)
            dpg.bind_item_theme(self.button, _arrow_theme(disabled=not self.enabled))
        self._refresh_shell_theme()
        return self

    setEnabled = set_enabled

    def isEnabled(self):
        return bool(self.enabled)

    def popup_open(self):
        # DPG does not expose the internal BeginCombo popup id.  The hint is
        # deliberately conservative and used only to suppress a dialog default
        # action for the frame in which the arrow was activated/selection made.
        return bool(self._native_popup_hint)

    def open_popup(self):
        """Qt compatibility helper.

        Dear PyGui has no public API to programmatically call BeginCombo/OpenPopup
        for an existing mvCombo.  Focusing the native sub-control preserves the
        keyboard contract without reintroducing a second custom popup.
        """
        if self.enabled and self.button and dpg.does_item_exist(self.button):
            try:
                dpg.focus_item(self.button)
                self._native_popup_hint = True
            except Exception:
                pass
        self._refresh_shell_theme()

    showPopup = open_popup

    def close_popup(self):
        # Native BeginCombo popups auto-dismiss on selection/click-away/Escape.
        self._native_popup_hint = False
        self._refresh_shell_theme()

    hidePopup = close_popup

    def toggle_popup(self, sender=None, app_data=None, user_data=None):
        # Kept for API compatibility.  Mouse opening is owned by mvCombo.
        self.open_popup()

    def focus_editor(self):
        if self.enabled and dpg.does_item_exist(self.input):
            try:
                dpg.focus_item(self.input)
            except Exception:
                pass

    def _sync_native_items(self):
        if not self.button or not dpg.does_item_exist(self.button):
            return
        dpg.configure_item(self.button, items=list(self.items))
        # Never draw a second preview over the editable field.
        dpg.set_value(self.button, "")

    def _native_selected(self, sender=None, app_data=None, user_data=None):
        value = str(app_data or "")
        if not value and sender and dpg.does_item_exist(sender):
            try:
                value = str(dpg.get_value(sender) or "")
            except Exception:
                value = ""
        if not value:
            return
        self._native_popup_hint = False
        self.set_current_text(value, emit=True)
        if self.button and dpg.does_item_exist(self.button):
            dpg.set_value(self.button, "")
        self.activated.emit(self.current_index())

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
        return bool(self._item_focused(self.input) or self._item_focused(self.button))

    def _refresh_shell_theme(self, *_args):
        if not self.shell or not dpg.does_item_exist(self.shell):
            return
        focused = self.enabled and self._owns_keyboard()
        dpg.bind_item_theme(
            self.shell,
            _shell_theme(focused=focused, disabled=not self.enabled),
        )

    def _install_input_state_handlers(self):
        try:
            with dpg.item_handler_registry(tag=self._input_handlers):
                if hasattr(dpg, "add_item_focus_handler"):
                    dpg.add_item_focus_handler(callback=self._refresh_shell_theme)
                if hasattr(dpg, "add_item_activated_handler"):
                    dpg.add_item_activated_handler(callback=self._refresh_shell_theme)
                if hasattr(dpg, "add_item_deactivated_handler"):
                    dpg.add_item_deactivated_handler(callback=self._refresh_shell_theme)
            dpg.bind_item_handler_registry(self.input, self._input_handlers)
        except Exception:
            self._input_handlers = None

    def _button_activated(self, *_args):
        self._native_popup_hint = True
        self._refresh_shell_theme()

    def _button_deactivated(self, *_args):
        # Do not immediately assume the popup is closed; selection callback or
        # the next outside click will clear the hint.  The hint does not drive
        # popup rendering, only LoginForm's default-button suppression.
        self._refresh_shell_theme()

    def _install_button_state_handlers(self):
        try:
            with dpg.item_handler_registry(tag=self._button_handlers):
                if hasattr(dpg, "add_item_activated_handler"):
                    dpg.add_item_activated_handler(callback=self._button_activated)
                if hasattr(dpg, "add_item_deactivated_handler"):
                    dpg.add_item_deactivated_handler(callback=self._button_deactivated)
            dpg.bind_item_handler_registry(self.button, self._button_handlers)
        except Exception:
            self._button_handlers = None

    def _install_geometry_handlers(self):
        """Keep the editor overlay aligned with the native combo frame."""
        try:
            with dpg.item_handler_registry(tag=self._geometry_handlers):
                if hasattr(dpg, "add_item_resize_handler"):
                    dpg.add_item_resize_handler(callback=self._sync_geometry)
            dpg.bind_item_handler_registry(self.shell, self._geometry_handlers)
        except Exception:
            self._geometry_handlers = None

    def _sync_geometry(self, *_args):
        # The horizontal row owns layout; only reassert the fill-minus-arrow
        # editor width and compact arrow width after DPI/reparent changes.
        if self._row and dpg.does_item_exist(self._row):
            try:
                dpg.configure_item(self._row, pos=(1, 1))
            except Exception:
                pass
        if self.input and dpg.does_item_exist(self.input):
            try:
                dpg.configure_item(self.input, width=-(self.ARROW_WIDTH + 1))
            except Exception:
                pass
        if self.button and dpg.does_item_exist(self.button):
            try:
                # Keep Dear ImGui's popup owner bound to the complete available
                # shell width. Negative width tracks DPI/reflow automatically.
                dpg.configure_item(self.button, width=-1, pos=(0, 0))
            except Exception:
                pass

    def _install_handlers(self):
        try:
            with dpg.handler_registry(tag=self._handlers):
                for key_name, callback in (
                    ("mvKey_F4", self._f4_pressed),
                    ("mvKey_Escape", self._escape_pressed),
                    ("mvKey_Up", self._up_pressed),
                    ("mvKey_Down", self._down_pressed),
                ):
                    key = getattr(dpg, key_name, None)
                    if key is not None:
                        dpg.add_key_press_handler(key=key, callback=callback)
                dpg.add_mouse_click_handler(
                    button=dpg.mvMouseButton_Left, callback=self._mouse_clicked)
        except Exception:
            self._handlers = None

    @staticmethod
    def _point_inside(item, x, y):
        if not item or not dpg.does_item_exist(item):
            return False
        try:
            rx, ry = dpg.get_item_rect_min(item)
            rw, rh = dpg.get_item_rect_size(item)
            return rx <= x < rx + rw and ry <= y < ry + rh
        except Exception:
            return False

    def _mouse_clicked(self, sender=None, app_data=None, user_data=None):
        if not self._native_popup_hint:
            return
        try:
            x, y = dpg.get_mouse_pos(local=False)
            if self._point_inside(self.shell, x, y):
                return
        except Exception:
            return
        # The native combo itself already handled popup dismissal.
        self._native_popup_hint = False

    def _f4_pressed(self, sender=None, app_data=None, user_data=None):
        if not self.enabled or not self._owns_keyboard():
            return
        # Dear PyGui does not expose OpenPopup for an existing mvCombo.
        # Transfer keyboard focus to the native combo; Space/Enter/Down then
        # follow Dear ImGui's own combo navigation without a custom overlay.
        self.open_popup()

    def _escape_pressed(self, sender=None, app_data=None, user_data=None):
        self._native_popup_hint = False
        self._refresh_shell_theme()

    def _up_pressed(self, sender=None, app_data=None, user_data=None):
        if not self.enabled or not self._item_focused(self.input) or not self.items:
            return
        index = self.current_index()
        self.set_current_index((index if index >= 0 else 0) - 1, emit=True)

    def _down_pressed(self, sender=None, app_data=None, user_data=None):
        if not self.enabled or not self._item_focused(self.input) or not self.items:
            return
        index = self.current_index()
        self.set_current_index((index if index >= 0 else -1) + 1, emit=True)

    def _input_changed(self, sender=None, app_data=None, user_data=None):
        value = self.current_text()
        old = self._value
        try:
            old_index = self.items.index(old)
        except ValueError:
            old_index = -1
        self._value = value
        new_index = self.current_index()
        if self.button and dpg.does_item_exist(self.button):
            # The native combo owns only the arrow/popup.  Never let its preview
            # paint a duplicate value over the editable InputText.
            dpg.set_value(self.button, "")
        if value != old:
            self.editTextChanged.emit(value)
            self.currentTextChanged.emit(value)
        if old_index != new_index:
            self.currentIndexChanged.emit(new_index)
        if callable(self.callback):
            self.callback(self.input, value, self)

    def destroy(self):
        for item in (
            self._handlers,
            self._input_handlers,
            self._button_handlers,
            self._geometry_handlers,
            self.shell,
        ):
            if item and dpg.does_item_exist(item):
                try:
                    dpg.delete_item(item)
                except Exception:
                    pass


QtComboBox = ImGuiComboBox

__all__ = ["ImGuiComboBox", "QtComboBox"]
