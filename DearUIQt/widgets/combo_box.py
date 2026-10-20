"""Qt/Fusion-like combo boxes implemented with Dear PyGui only.

Editable combos keep Dear ImGui's native full-width ``mvCombo`` as the popup
owner.  A small child window containing ``mvInputText`` covers only the preview
area on the left.  The native combo arrow remains completely exposed on the
right, so it retains normal BeginCombo hit-testing while its popup inherits the
full control width and native popup positioning.
"""
from __future__ import annotations

from ..backends import dpg

from ..gui.palette import QtFusionPalette
from ..backends.dearpygui import dpg_window_rect, add_dpg_scroller_style
from ..core.object import Qt, Signal
from .widget import QWidget
from ..gui.style import METRICS


_SHELL_THEME = "dearuiqt.qt_combo.shell.normal"
_FOCUSED_SHELL_THEME = "dearuiqt.qt_combo.shell.focus"
_DISABLED_SHELL_THEME = "dearuiqt.qt_combo.shell.disabled"
_INPUT_THEME = "dearuiqt.qt_combo.editor.normal"
_DISABLED_INPUT_THEME = "dearuiqt.qt_combo.editor.disabled"
_EDITOR_CLIP_THEME = "dearuiqt.qt_combo.editor.clip"
_COMBO_THEME = "dearuiqt.qt_combo.native.normal"
_DISABLED_COMBO_THEME = "dearuiqt.qt_combo.native.disabled"


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
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 2)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1)
    return tag


def _editor_clip_theme():
    if dpg.does_item_exist(_EDITOR_CLIP_THEME):
        return _EDITOR_CLIP_THEME
    with dpg.theme(tag=_EDITOR_CLIP_THEME):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    return _EDITOR_CLIP_THEME


def _input_theme(*, disabled=False):
    tag = _DISABLED_INPUT_THEME if disabled else _INPUT_THEME
    if dpg.does_item_exist(tag):
        return tag
    p = QtFusionPalette
    bg = p.BUTTON_DISABLED if disabled else p.BASE
    text = p.TEXT_DISABLED if disabled else p.TEXT
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvInputText, enabled_state=not disabled):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, bg)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, bg)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, bg)
            dpg.add_theme_color(dpg.mvThemeCol_Text, text)
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            cursor_role = getattr(dpg, "mvThemeCol_InputTextCursor", None)
            if cursor_role is not None:
                dpg.add_theme_color(cursor_role, p.TEXT_DISABLED if disabled else p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (0, 120, 215, 115))
            dpg.add_theme_style(
                dpg.mvStyleVar_FramePadding,
                METRICS.frame_pad_x - METRICS.border_size,
                METRICS.combo_editor_frame_pad_y,
            )
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
    return tag


def _combo_theme(*, disabled=False):
    """Style the full-width native combo that owns the popup and arrow."""
    tag = _DISABLED_COMBO_THEME if disabled else _COMBO_THEME
    if dpg.does_item_exist(tag):
        return tag
    p = QtFusionPalette
    base = p.BUTTON_DISABLED if disabled else p.BASE
    arrow = p.BUTTON_DISABLED if disabled else p.BASE
    hover = arrow if disabled else p.BUTTON_HOVER
    active = arrow if disabled else p.BUTTON_ACTIVE
    text = p.TEXT_DISABLED if disabled else p.TEXT
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvCombo, enabled_state=not disabled):
            # The preview is mostly covered by the editor child; keep the native
            # frame opaque so the uncovered arrow strip has no visual seams.
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, base)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, base)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, base)
            dpg.add_theme_color(dpg.mvThemeCol_Button, arrow)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, active)
            dpg.add_theme_color(dpg.mvThemeCol_Text, text)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_NavHighlight, base)
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, p.BASE)
            # Popup scrolling follows the application-wide QListView contract
            # instead of maintaining a second, narrower blue-gray scrollbar.
            add_dpg_scroller_style(dpg, track=p.WINDOW_ALT)
            dpg.add_theme_color(dpg.mvThemeCol_Header, p.SELECTION_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.SELECTION_ACTIVE_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.SELECTION_ACTIVE_PRESSED)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 2,
                                METRICS.editor_frame_pad_y - METRICS.border_size)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 2)
            dpg.add_theme_style(dpg.mvStyleVar_SelectableTextAlign, 0.0, 0.5)
            dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, 2)
            dpg.add_theme_style(dpg.mvStyleVar_PopupBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 2, 2)
    return tag


class ImGuiComboBox:
    """Editable QComboBox-like control using one native full-width popup owner.

    The native combo is submitted first across the complete field width.  The
    editable InputText lives in a child window above only the preview region.
    Because that child ends before the arrow strip, Dear ImGui routes text-area
    input to InputText and arrow-area input to mvCombo with no overlapping hit
    target at the mouse position.
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
            height=self.CONTROL_HEIGHT,
            border=True,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        self.shell = self.container
        dpg.bind_item_theme(self.shell, _shell_theme())

        self._editor_right_reserve = max(
            self.ARROW_WIDTH,
            self.CONTROL_HEIGHT - 2 * METRICS.border_size,
        ) + 1

        # Full-width native BeginCombo.  Do NOT use no_preview=True: Dear ImGui
        # intentionally collapses a NoPreview combo to the arrow width, which
        # also makes its popup narrow.  A normal preview gives the popup the full
        # field bounding box and native below-control placement.
        self.button = dpg.add_combo(
            self.items,
            label="",
            parent=self.shell,
            pos=(1, 1),
            width=-2,
            default_value="",
            no_preview=False,
            popup_align_left=True,
            fit_width=False,
            callback=self._native_selected,
        )
        dpg.bind_item_theme(self.button, _combo_theme())

        # Reverse-clipping is the key detail: clip only the editor overlay, not
        # the native combo.  The arrow portion of mvCombo therefore remains a
        # real, unobstructed Dear ImGui hit target.
        self._editor_clip = dpg.add_child_window(
            parent=self.shell,
            pos=(1, 1),
            width=-self._editor_right_reserve,
            height=self.CONTROL_HEIGHT - 2 * METRICS.border_size,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        dpg.bind_item_theme(self._editor_clip, _editor_clip_theme())

        self.input = dpg.add_input_text(
            tag=self.tag,
            parent=self._editor_clip,
            default_value=self._value,
            width=-1,
            height=self.CONTROL_HEIGHT - 2 * METRICS.border_size,
            readonly=not self.editable,
            callback=self._input_changed,
            on_enter=False,
            auto_select_all=False,
        )
        dpg.bind_item_theme(self.input, _input_theme())

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
            # Keep the native preview empty; InputText is the visible editor.
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

    def _sync_native_items(self):
        if self.button and dpg.does_item_exist(self.button):
            dpg.configure_item(self.button, items=list(self.items))
            dpg.set_value(self.button, "")

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
        # DearPyGui does not expose the exact BeginCombo popup-row count, but
        # keep the Qt-compatible property for callers and future backends.
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
            dpg.bind_item_theme(self.button, _combo_theme(disabled=not self.enabled))
        self._refresh_shell_theme()
        return self

    setEnabled = set_enabled

    def isEnabled(self):
        return bool(self.enabled)

    def popup_open(self):
        # DPG does not expose BeginCombo's internal popup id.  The hint is used
        # only to suppress dialog default actions while the native combo is in
        # its activation/selection flow.
        return bool(self._native_popup_hint)

    def open_popup(self):
        if self.enabled and self.button and dpg.does_item_exist(self.button):
            try:
                dpg.focus_item(self.button)
                self._native_popup_hint = True
            except Exception:
                pass
        self._refresh_shell_theme()

    showPopup = open_popup

    def close_popup(self):
        self._native_popup_hint = False
        self._refresh_shell_theme()

    hidePopup = close_popup

    def toggle_popup(self, sender=None, app_data=None, user_data=None):
        self.open_popup()

    def focus_editor(self):
        if self.enabled and dpg.does_item_exist(self.input):
            try:
                dpg.focus_item(self.input)
            except Exception:
                pass

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
        self.focus_editor()

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
        try:
            with dpg.item_handler_registry(tag=self._geometry_handlers):
                if hasattr(dpg, "add_item_resize_handler"):
                    dpg.add_item_resize_handler(callback=self._sync_geometry)
            dpg.bind_item_handler_registry(self.shell, self._geometry_handlers)
        except Exception:
            self._geometry_handlers = None

    def _sync_geometry(self, *_args):
        if self.button and dpg.does_item_exist(self.button):
            try:
                dpg.configure_item(self.button, pos=(1, 1), width=-2)
            except Exception:
                pass
        if self._editor_clip and dpg.does_item_exist(self._editor_clip):
            try:
                dpg.configure_item(
                    self._editor_clip,
                    pos=(1, 1),
                    width=-self._editor_right_reserve,
                    height=self.CONTROL_HEIGHT - 2 * METRICS.border_size,
                )
            except Exception:
                pass
        if self.input and dpg.does_item_exist(self.input):
            try:
                dpg.configure_item(
                    self.input,
                    width=-1,
                    height=self.CONTROL_HEIGHT - 2 * METRICS.border_size,
                )
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
        except (KeyError, TypeError, RuntimeError):
            rect = dpg_window_rect(dpg, item, clip=True)
            return bool(rect and rect[0] <= x < rect[2] and rect[1] <= y < rect[3])

    def _mouse_clicked(self, sender=None, app_data=None, user_data=None):
        if not self._native_popup_hint:
            return
        try:
            x, y = dpg.get_mouse_pos(local=False)
            if self._point_inside(self.shell, x, y):
                return
        except Exception:
            return
        self._native_popup_hint = False

    def _f4_pressed(self, sender=None, app_data=None, user_data=None):
        if not self.enabled or not self._owns_keyboard():
            return
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


class QComboBox(QWidget):
    """QObject-owned QComboBox facade with a backend-neutral item model.

    The historical :class:`ImGuiComboBox` remains available for WinUx's
    editable-login compatibility path. New code receives a real QWidget/QObject
    with stable ownership, item-data and signal semantics. Editable and
    read-only combos share the compact field and popup engine; limited
    backends retain the native combo/editor compatibility path.
    """

    NoInsert = 0
    InsertAtTop = 1
    InsertAtCurrent = 2
    InsertAtBottom = 3
    InsertAfterCurrent = 4
    InsertBeforeCurrent = 5
    InsertAlphabetically = 6

    def __init__(self, items=(), *, current=None, parent=None, after=None,
                 backend=None, editable=False, width=-1, callback=None):
        backend, options = self._construction(parent, backend)
        self.currentIndexChanged = Signal()
        self.currentTextChanged = Signal()
        self.activated = Signal()
        self.editTextChanged = Signal()
        self.highlighted = Signal()
        self._items = []
        self._item_data = []
        self._editable = bool(editable)
        self._insert_policy = self.NoInsert
        self._max_visible_items = 10
        self._external_callback = callback
        self._legacy = None
        self._choice_field = None
        self._choice_popup = None
        self._choice_popup_parent = None
        self._choice_popup_closed_frame = -1
        self._choice_keys = None
        self._choice_target = None
        values = [str(item) for item in items]
        selected = str(current if current is not None else (values[0] if values else ""))
        if not self._editable and selected not in values:
            selected = values[0] if values else ""

        use_choice_field = all(callable(getattr(backend, name, None)) for name in
                               ("add_button", "add_drawlist", "draw_line", "draw_rectangle",
                                "theme", "theme_component", "item_handler_registry"))
        if self._editable and not use_choice_field:
            # The compatibility editor owns several auxiliary handler items.
            # It intentionally targets the process default DPG backend; reject
            # a different injected renderer rather than silently mixing trees.
            from ..backends import get_backend
            if backend is not get_backend():
                raise RuntimeError("editable QComboBox requires the active DearPyGui backend")
            legacy = ImGuiComboBox(
                values, default_value=selected, width=width,
                callback=self._legacy_changed, parent=options.get("parent"), editable=True)
            self._legacy = legacy
            tag = legacy.container
        elif use_choice_field:
            from .combo_field import ComboField
            self._choice_field = ComboField(
                backend, options.get("parent"), width, selected,
                self.showPopup, self._choice_focus_received,
                editable=self._editable, text_changed=self._choice_edited)
            tag = self._choice_field.tag
        else:
            tag = backend.add_combo(
                values,
                default_value=selected if selected in values else (values[0] if values else ""),
                width=width,
                callback=self._native_changed,
                **options,
            )

        super().__init__(tag, parent=parent, after=after, backend=backend)
        for signal in (self.currentIndexChanged, self.currentTextChanged,
                       self.activated, self.editTextChanged, self.highlighted):
            signal.owner = self
        self._items = values
        self._item_data = [{} for _ in values]
        self._properties.update(value=selected, enabled=True)
        if self._legacy is not None:
            self._properties["value"] = self._legacy.currentText()
            self._legacy.currentIndexChanged.connect(self.currentIndexChanged.emit)
            self._legacy.currentTextChanged.connect(self.currentTextChanged.emit)
            self._legacy.activated.connect(self.activated.emit)
            self._legacy.editTextChanged.connect(self.editTextChanged.emit)
        if self._choice_field is not None:
            self._install_choice_input()

    def _layout_tag(self):
        return self.tag

    def _native_changed(self, sender=None, value=None, user_data=None):
        old = str(self._properties.get("value", ""))
        value = str(value or "")
        self._user_value(value)
        if old != value:
            self.currentTextChanged.emit(value)
            self.currentIndexChanged.emit(self.currentIndex())
        self.activated.emit(self.currentIndex())
        if callable(self._external_callback):
            self._external_callback(sender, value, self)

    def _legacy_changed(self, sender=None, value=None, user_data=None):
        self._properties["value"] = str(value or "")
        if callable(self._external_callback):
            self._external_callback(sender, value, self)

    def count(self):
        return len(self._items)

    def currentIndex(self):
        text = self.currentText()
        try:
            return self._items.index(text)
        except ValueError:
            return -1

    def currentText(self):
        if self._legacy is not None:
            return self._legacy.currentText()
        if self._choice_field is not None:
            if self._editable:
                return str(self.backend.get_value(self._choice_field.button) or "")
            return str(self._properties.get("value", ""))
        try:
            return str(self.backend.get_value(self.tag) or "")
        except Exception:
            return str(self._properties.get("value", ""))

    def currentData(self, role=Qt.UserRole):
        return self.itemData(self.currentIndex(), role)

    def setCurrentIndex(self, index):
        index = int(index)
        if index < -1 or index >= len(self._items):
            return False
        text = "" if index == -1 else self._items[index]
        return self.setCurrentText(text)

    def setCurrentText(self, text):
        text = str(text or "")
        if not self._editable and text not in self._items and text:
            return False
        old_text = self.currentText()
        old_index = self.currentIndex()
        if self._legacy is not None:
            # Legacy editable combo already emits current/edit/index signals;
            # forwarding those once through the connections installed in
            # __init__ preserves Qt semantics without duplicate emissions.
            self._legacy.setCurrentText(text)
            self._properties["value"] = self._legacy.currentText()
            return True
        if self._choice_field is not None:
            self._choice_field.setText(text)
        else:
            self.backend.set_value(self.tag, text)
        self._properties["value"] = text
        new_index = self.currentIndex()
        if old_text != text:
            if self._editable:
                self.editTextChanged.emit(text)
            self.currentTextChanged.emit(text)
        if old_index != new_index:
            self.currentIndexChanged.emit(new_index)
        return True

    def itemText(self, index):
        index = int(index)
        return self._items[index] if 0 <= index < len(self._items) else ""

    def itemData(self, index, role=Qt.UserRole):
        index = int(index)
        if not 0 <= index < len(self._item_data):
            return None
        return self._item_data[index].get(int(role))

    def setItemData(self, index, value, role=Qt.UserRole):
        index = int(index)
        if not 0 <= index < len(self._item_data):
            return False
        self._item_data[index][int(role)] = value
        return True

    def addItem(self, text, userData=None):
        self.insertItem(self.count(), text, userData)

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)

    def insertItem(self, index, text, userData=None):
        index = max(0, min(int(index), len(self._items)))
        self._items.insert(index, str(text))
        self._item_data.insert(index, {Qt.UserRole: userData} if userData is not None else {})
        self._sync_items()

    def removeItem(self, index):
        index = int(index)
        if not 0 <= index < len(self._items):
            return False
        self._items.pop(index)
        self._item_data.pop(index)
        self._sync_items()
        return True

    def clear(self):
        self._items.clear()
        self._item_data.clear()
        self._sync_items()
        self.setCurrentText("")

    def findText(self, text):
        try:
            return self._items.index(str(text))
        except ValueError:
            return -1

    def setEditable(self, editable):
        editable = bool(editable)
        if editable == self._editable:
            return
        # Renderer-neutral rebuild of an existing native combo is intentionally
        # not hidden behind this setter. Qt code should select editability during
        # construction; callers can recreate the widget when changing modes.
        raise RuntimeError("changing QComboBox editability after construction is not supported")

    def isEditable(self):
        return bool(self._editable)

    def lineEdit(self):
        if not self._editable:
            return None
        from .retained import QRetainedItem
        tag = self._choice_field.button if self._choice_field is not None else self._legacy.input
        return QRetainedItem(tag, backend=self.backend)

    def setInsertPolicy(self, policy):
        self._insert_policy = int(policy)

    def insertPolicy(self):
        return self._insert_policy

    def setMaxVisibleItems(self, count):
        self._max_visible_items = max(1, int(count))
        if self._legacy is not None:
            self._legacy.setMaxVisibleItems(self._max_visible_items)
        if self._choice_popup is not None and self._choice_popup.isVisible():
            self.showPopup()

    def maxVisibleItems(self):
        return self._max_visible_items

    def setEnabled(self, enabled=True):
        enabled = bool(enabled)
        self._properties["enabled"] = enabled
        if self._legacy is not None:
            self._legacy.setEnabled(enabled)
        elif self._choice_field is not None:
            if not enabled:
                self.hidePopup()
            self._choice_field.setEnabled(enabled)
        else:
            self._configure("enabled", enabled)

    def isEnabled(self):
        return bool(self._properties.get("enabled", True))

    def showPopup(self):
        if self._legacy is not None:
            return self._legacy.showPopup()
        if self._choice_field is not None:
            if not self.isEnabled() or not self._items or not self.isVisible():
                return False
            from .combo_popup import ComboPopup
            if self._choice_popup is None:
                self._choice_popup = ComboPopup(backend=self.backend, parent=self,
                                                parent_window=self._choice_popup_parent)
                self._choice_popup.triggered.connect(self._choice_activated)
                self._choice_popup.cancelled = self._choice_field.focus
                self._choice_popup.highlighted = self.highlighted.emit
                self._choice_popup.aboutToShow.connect(lambda _context: self._choice_field.setPopupVisible(True))
                self._choice_popup.aboutToHide.connect(self._choice_popup_hidden)
            field = self._choice_field
            field.syncGeometry()
            popup = self._choice_popup
            popup.configureChoices(self._items, field._width, self._max_visible_items)
            rect = dpg_window_rect(self.backend, self.tag, clip=True)
            if rect is None:
                return False
            left, top, right, bottom = rect
            height = self.backend.get_item_configuration(popup.tag)["height"]
            # Multi-viewport coordinates are desktop coordinates. Constrain to
            # the owning viewport, not an assumed (0, 0) desktop origin.
            from ..backends.native_windows import NativeWindowBackend
            native = NativeWindowBackend(self.backend).isEnabled()
            if self._choice_popup_parent is not None:
                bounds = dpg_window_rect(self.backend, self._choice_popup_parent) or rect
                available = max(top - bounds[1], bounds[3] - bottom)
                rows = max(1, int((available - 2) // popup.ROW_HEIGHT))
                if rows < min(len(self._items), self._max_visible_items):
                    popup.configureChoices(self._items, field._width, rows)
                    height = self.backend.get_item_configuration(popup.tag)["height"]
            elif native:
                owner = self.tag
                while True:
                    parent = self.backend.get_item_info(owner).get("parent")
                    if not parent:
                        break
                    owner = parent
                bounds = dpg_window_rect(self.backend, owner) or rect
            else:
                bounds = (0, 0, self.backend.get_viewport_client_width(),
                          self.backend.get_viewport_client_height())
            x = max(bounds[0], min(left, bounds[2] - field._width))
            y = bottom if bottom + height <= bounds[3] else max(bounds[1], top - height)
            shown = popup.popup()
            position = ((x - bounds[0], y - bounds[1])
                        if self._choice_popup_parent is not None else (x, y))
            self.backend.set_item_pos(popup.tag, tuple(map(int, position)))
            popup.selectRow(max(0, self.currentIndex()))
            return shown
        try:
            self.backend.focus_item(self.tag)
        except Exception:
            pass

    def hidePopup(self):
        if self._legacy is not None:
            self._legacy._escape_pressed()
        if self._choice_popup is not None:
            return self._choice_popup.hide()

    def setPopupParent(self, parent):
        """Keep a history popup inside its native/modal dialog's render tree."""
        self.hidePopup()
        if self._choice_popup is not None:
            self._choice_popup.delete()
            self._choice_popup = None
        self._choice_popup_parent = getattr(parent, "tag", parent)

    def popupVisible(self):
        if self._choice_popup is not None:
            return self._choice_popup.isVisible()
        return bool(self._legacy is not None and self._legacy.popup_open())

    def _choice_activated(self, action, context=None):
        index = int(action)
        if not 0 <= index < len(self._items):
            return
        self.hidePopup()
        self._choice_field.focus()
        self.setCurrentIndex(index)
        self.activated.emit(index)
        if callable(self._external_callback):
            self._external_callback(self.tag, self.currentText(), self)

    def _choice_popup_hidden(self, context=None):
        self._choice_field.setPopupVisible(False)
        try:
            self._choice_popup_closed_frame = int(self.backend.get_frame_count())
        except Exception:
            self._choice_popup_closed_frame = -1

    def _choice_edited(self, sender, value, user_data=None):
        old = str(self._properties.get("value", ""))
        if value == old:
            return
        old_index = self.findText(old)
        self._user_value(value)
        self.editTextChanged.emit(value)
        self.currentTextChanged.emit(value)
        if old_index != self.currentIndex():
            self.currentIndexChanged.emit(self.currentIndex())
        if callable(self._external_callback):
            self._external_callback(sender, value, self)

    def _choice_focus_received(self):
        target = self._choice_target
        if target is not None:
            target.setFocus()

    def _install_choice_input(self):
        from ..core import QInputTarget, QGlobalInputBinding
        from ..core.application import QApplication
        self._choice_target = QInputTarget(parent=self, key_handler=self._choice_key_event)
        app = QApplication.instance()
        if app is not None and app.hasInputBackend(self.backend):
            return
        self._choice_keys = QGlobalInputBinding(backend=self.backend, parent=self)
        def handler_for(key):
            def handler(sender=None, app_data=None, user_data=None):
                application = QApplication.instance()
                if application is not None and application.hasInputBackend(self.backend):
                    return
                if self._choice_field.hasFocus() and not self.popupVisible():
                    self._handle_choice_key(key)
            return handler
        for key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End,
                    Qt.Key_F4, Qt.Key_Space, Qt.Key_Return):
            self._choice_keys.onKeyPress(key, handler_for(key))
        self._choice_keys.activate()

    def _choice_key_event(self, event):
        from ..core import QEvent
        return bool(event.type() == QEvent.KeyPress and self._handle_choice_key(event.key(), event.modifiers()))

    def _handle_choice_key(self, key, modifiers=0):
        if not self.isEnabled() or not self.isVisible() or not self._items:
            return False
        for qt_key, names in (
                (Qt.Key_Up, ("mvKey_Up",)), (Qt.Key_Down, ("mvKey_Down",)),
                (Qt.Key_Home, ("mvKey_Home",)), (Qt.Key_End, ("mvKey_End",)),
                (Qt.Key_F4, ("mvKey_F4",)), (Qt.Key_Space, ("mvKey_Spacebar",)),
                (Qt.Key_Return, ("mvKey_Return", "mvKey_Enter"))):
            if key == qt_key or any(key == getattr(self.backend, name, None) for name in names):
                key = qt_key
                break
        if self._editable and key in (Qt.Key_Return, Qt.Key_Space, Qt.Key_Home, Qt.Key_End):
            # Enter belongs to the form when history is closed; editing keys
            # remain with InputText instead of opening/changing the dropdown.
            return False
        if key in (Qt.Key_F4, Qt.Key_Space, Qt.Key_Return) or (
                key == Qt.Key_Down and modifiers & Qt.AltModifier):
            self.showPopup()
            return True
        if key not in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End):
            return False
        current = self.currentIndex()
        index = (0 if key == Qt.Key_Home else len(self._items) - 1 if key == Qt.Key_End
                 else max(0, min(len(self._items) - 1, current + (1 if key == Qt.Key_Down else -1))))
        self.setCurrentIndex(index)
        if current != index:
            self.activated.emit(index)
            if callable(self._external_callback):
                self._external_callback(self.tag, self.currentText(), self)
        return True

    def hideEvent(self, event):
        self.hidePopup()
        super().hideEvent(event)

    def setFocus(self):
        if self._choice_field is not None:
            if self.isEnabled():
                self._choice_field.focus()
            return
        return super().setFocus()

    def sizeHint(self):
        from ..core import QSize
        if self._choice_field is not None:
            width = max(80, self._choice_field._width)
            return QSize(width, self._choice_field.height)
        return super().sizeHint()

    def _sync_items(self):
        if self._legacy is not None:
            self._legacy.items = list(self._items)
            self._legacy._sync_native_items()
        elif self._choice_field is None:
            self.backend.configure_item(self.tag, items=list(self._items))
        if self._choice_popup is not None:
            self.hidePopup()
        if self.currentText() not in self._items and not self._editable:
            self.setCurrentIndex(0 if self._items else -1)

    def delete(self):
        if self._choice_popup is not None:
            self._choice_popup.delete()
            self._choice_popup = None
        if self._choice_field is not None:
            self._choice_field.delete()
        if self._legacy is not None:
            self._legacy.destroy()
        super().delete()


QtComboBox = ImGuiComboBox

__all__ = ["ImGuiComboBox", "QtComboBox", "QComboBox"]
