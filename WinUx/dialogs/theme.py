from __future__ import annotations

import dearpygui.dearpygui as dpg

from ..components.qt_style import QtFusionMetrics, QtFusionPalette
from ..components.shared_scroller import add_dpg_scroller_style


class DialogPalette:
    """Qt/Fusion-derived palette retained under the historical dialog API."""

    WINDOW_BG = QtFusionPalette.WINDOW
    SURFACE = QtFusionPalette.BASE
    FOOTER = QtFusionPalette.WINDOW
    CHILD_BG = QtFusionPalette.WINDOW
    TEXT = QtFusionPalette.TEXT
    MUTED = QtFusionPalette.TEXT_MUTED
    TITLE = QtFusionPalette.TEXT
    BORDER = QtFusionPalette.BORDER
    FRAME_BG = QtFusionPalette.BASE
    FRAME_HOVER = QtFusionPalette.HIGHLIGHT_HOVER
    BUTTON = QtFusionPalette.BUTTON
    BUTTON_HOVER = QtFusionPalette.BUTTON_HOVER
    BUTTON_ACTIVE = QtFusionPalette.BUTTON_ACTIVE
    HEADER = QtFusionPalette.TOOLBAR
    HEADER_HOVER = QtFusionPalette.HIGHLIGHT_HOVER
    SELECT = QtFusionPalette.HIGHLIGHT_SOFT
    SELECT_TEXT = QtFusionPalette.TEXT
    ERROR = QtFusionPalette.DANGER
    SUCCESS = (26, 127, 55, 255)


class DialogMetrics:
    # Shared QDialog/QFormLayout metrics.  Keep these values centralized so a
    # control never becomes taller or more padded merely because it lives in a
    # different dialog.  The dimensions are deliberately close to Qt Fusion on
    # Windows: compact 26 px controls, 10 px content margins and a 42 px
    # QDialogButtonBox-style footer.
    LABEL_WIDTH = 104
    BUTTON_WIDTH = 82
    BUTTON_HEIGHT = 26
    BUTTON_GAP = 6
    FOOTER_HEIGHT = 40
    WINDOW_PAD_X = 10
    WINDOW_PAD_Y = 8
    ROW_SPACING = 5
    FRAME_PAD_X = 5
    FRAME_PAD_Y = 4
    GROUP_PAD_X = 8
    GROUP_PAD_Y = 6
    BODY_FONT_SIZE = 14
    HEADING_FONT_SIZE = 15
    MIN_DIALOG_WIDTH = 360
    MIN_DIALOG_HEIGHT = 190
    NAV_WIDTH = 156
    STATUS_HEIGHT = 18
    CONTROL_HEIGHT = 26
    COMBO_ARROW_WIDTH = 24


_DIALOG_THEME = None
_PRIMARY_BUTTON_THEME = None
_SECONDARY_BUTTON_THEME = None
_DANGER_BUTTON_THEME = None
_TITLE_THEME = None
_ERROR_THEME = None
_SURFACE_THEME = None
_FOOTER_THEME = None
_BODY_THEME = None
_MUTED_TEXT_THEME = None
_ERROR_TEXT_THEME = None
_NAV_THEME = None
_LINE_EDIT_THEME = None
_LINE_EDIT_FOCUS_THEME = None
_LINE_EDIT_DISABLED_THEME = None
_LINE_EDIT_SHELL_THEME = None
_LINE_EDIT_SHELL_FOCUS_THEME = None
_LINE_EDIT_SHELL_DISABLED_THEME = None
_LINE_EDIT_EDITOR_THEME = None
_LINE_EDIT_EDITOR_DISABLED_THEME = None
_COMBO_THEME = None
_COMBO_FOCUS_THEME = None
_COMBO_DISABLED_THEME = None
_PLAIN_TEXT_EDIT_THEME = None


def _is_theme(item):
    return bool(item is not None and dpg.does_item_exist(item)
                and dpg.get_item_info(item).get("type", "").endswith("::mvTheme"))


def _control_frame(theme_component, *, focused=False, disabled=False):
    """Apply the common Qt/Fusion frame contract to one input component."""
    p = QtFusionPalette
    background = p.BUTTON_DISABLED if disabled else p.BASE
    border = p.BORDER_LIGHT if disabled else (p.FOCUS if focused else p.BORDER)
    text = p.TEXT_DISABLED if disabled else p.TEXT
    dpg.add_theme_color(dpg.mvThemeCol_FrameBg, background)
    dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, background)
    dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, background)
    dpg.add_theme_color(dpg.mvThemeCol_Text, text)
    dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
    cursor_role = getattr(dpg, "mvThemeCol_InputTextCursor", None)
    if cursor_role is not None:
        dpg.add_theme_color(cursor_role, p.TEXT_DISABLED if disabled else p.TEXT)
    dpg.add_theme_color(dpg.mvThemeCol_Border, border)
    dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (0, 120, 215, 115))
    # Use the same effective 26 px editor height as QLineEdit/QSpinBox.
    # A 5 px vertical frame pad keeps native mvCombo and mvInputText frames
    # visually equal to the 26 px retained spin-box shell.
    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 5)
    dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
    # QLineEdit/QComboBox frames on Fusion are effectively square.  One pixel
    # rounding avoids harsh raster corners without the pill-like ImGui look.
    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 1)


def line_edit_shell_theme(*, focused=False, disabled=False):
    """Outer QLineEdit frame used by single-line editors.

    The active InputText itself stays on one stable borderless theme for its
    entire editing session.  Only this shell changes border colour on focus.
    Rebinding an active Dear ImGui InputText theme can interrupt its internal
    edit state and is the main reason a field can show a blue frame but no
    blinking caret.
    """
    global _LINE_EDIT_SHELL_THEME, _LINE_EDIT_SHELL_FOCUS_THEME, _LINE_EDIT_SHELL_DISABLED_THEME
    slot = 'disabled' if disabled else ('focus' if focused else 'normal')
    current = {
        'normal': _LINE_EDIT_SHELL_THEME,
        'focus': _LINE_EDIT_SHELL_FOCUS_THEME,
        'disabled': _LINE_EDIT_SHELL_DISABLED_THEME,
    }[slot]
    if _is_theme(current):
        return current
    p = QtFusionPalette
    border = p.BORDER_LIGHT if disabled else (p.FOCUS if focused else p.BORDER)
    background = p.BUTTON_DISABLED if disabled else p.BASE
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, background)
            dpg.add_theme_color(dpg.mvThemeCol_Border, border)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 1)
    if slot == 'normal':
        _LINE_EDIT_SHELL_THEME = theme
    elif slot == 'focus':
        _LINE_EDIT_SHELL_FOCUS_THEME = theme
    else:
        _LINE_EDIT_SHELL_DISABLED_THEME = theme
    return theme


def line_edit_editor_theme(*, disabled=False):
    """Stable borderless editor theme hosted inside ``line_edit_shell_theme``."""
    global _LINE_EDIT_EDITOR_THEME, _LINE_EDIT_EDITOR_DISABLED_THEME
    current = _LINE_EDIT_EDITOR_DISABLED_THEME if disabled else _LINE_EDIT_EDITOR_THEME
    if _is_theme(current):
        return current
    p = QtFusionPalette
    background = p.BUTTON_DISABLED if disabled else p.BASE
    text = p.TEXT_DISABLED if disabled else p.TEXT
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvInputText):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, background)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, background)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, background)
            dpg.add_theme_color(dpg.mvThemeCol_Text, text)
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            cursor_role = getattr(dpg, "mvThemeCol_InputTextCursor", None)
            if cursor_role is not None:
                dpg.add_theme_color(cursor_role, p.TEXT_DISABLED if disabled else p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (0, 120, 215, 115))
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 3)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
    if disabled:
        _LINE_EDIT_EDITOR_DISABLED_THEME = theme
    else:
        _LINE_EDIT_EDITOR_THEME = theme
    return theme


def line_edit_theme(*, focused=False, disabled=False):
    """Return a QLineEdit-like item theme, including a blue focus frame."""
    global _LINE_EDIT_THEME, _LINE_EDIT_FOCUS_THEME, _LINE_EDIT_DISABLED_THEME
    slot = ('disabled' if disabled else ('focus' if focused else 'normal'))
    current = {
        'normal': _LINE_EDIT_THEME,
        'focus': _LINE_EDIT_FOCUS_THEME,
        'disabled': _LINE_EDIT_DISABLED_THEME,
    }[slot]
    if _is_theme(current):
        return current
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvInputText) as component:
            _control_frame(component, focused=focused, disabled=disabled)
    if slot == 'normal':
        _LINE_EDIT_THEME = theme
    elif slot == 'focus':
        _LINE_EDIT_FOCUS_THEME = theme
    else:
        _LINE_EDIT_DISABLED_THEME = theme
    return theme


def combo_theme(*, focused=False, disabled=False):
    """Return a QComboBox-like theme for non-editable native DPG combos."""
    global _COMBO_THEME, _COMBO_FOCUS_THEME, _COMBO_DISABLED_THEME
    slot = ('disabled' if disabled else ('focus' if focused else 'normal'))
    current = {
        'normal': _COMBO_THEME,
        'focus': _COMBO_FOCUS_THEME,
        'disabled': _COMBO_DISABLED_THEME,
    }[slot]
    if _is_theme(current):
        return current
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvCombo) as component:
            _control_frame(component, focused=focused, disabled=disabled)
            # Qt Fusion treats the arrow as a sub-control of the same field;
            # the closed control does not look like a grey push button glued to
            # a white editor.  Use the field surface at rest and highlight only
            # the arrow region on hover/press.
            button = p.BUTTON_DISABLED if disabled else p.BASE
            dpg.add_theme_color(dpg.mvThemeCol_Button, button)
            dpg.add_theme_color(
                dpg.mvThemeCol_ButtonHovered,
                button if disabled else p.HIGHLIGHT_HOVER,
            )
            dpg.add_theme_color(
                dpg.mvThemeCol_ButtonActive,
                button if disabled else p.HIGHLIGHT_SOFT,
            )
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, p.MENU)
            dpg.add_theme_color(dpg.mvThemeCol_Header, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.MENU_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.MENU_ACTIVE)
            dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, 1)
            dpg.add_theme_style(dpg.mvStyleVar_PopupBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 6, 3)
    if slot == 'normal':
        _COMBO_THEME = theme
    elif slot == 'focus':
        _COMBO_FOCUS_THEME = theme
    else:
        _COMBO_DISABLED_THEME = theme
    return theme



def plain_text_edit_theme():
    """Qt/Fusion QPlainTextEdit-like theme for multiline diagnostics/log views.

    Multiline ``mvInputText`` items keep Dear ImGui's native editing and
    scrolling behavior, but their frame/scrollbar chrome should match the
    rest of WinUx rather than inheriting the generic dialog theme.
    """
    global _PLAIN_TEXT_EDIT_THEME
    if _is_theme(_PLAIN_TEXT_EDIT_THEME):
        return _PLAIN_TEXT_EDIT_THEME
    p = QtFusionPalette
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvInputText):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (0, 120, 215, 115))
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 5)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
        with dpg.theme_component(dpg.mvAll):
            add_dpg_scroller_style(dpg, track=p.WINDOW_ALT)
    _PLAIN_TEXT_EDIT_THEME = theme
    return theme

def _item_enabled(item):
    try:
        return bool(dpg.get_item_configuration(item).get('enabled', True))
    except Exception:
        return True


def _item_has_focus(item):
    try:
        state = dpg.get_item_state(item) or {}
        return bool(state.get('focused', False) or state.get('active', False))
    except Exception:
        return False


def refresh_line_edit_theme(item):
    if not dpg.does_item_exist(item):
        return
    enabled = _item_enabled(item)
    dpg.bind_item_theme(
        item,
        line_edit_theme(focused=enabled and _item_has_focus(item), disabled=not enabled),
    )


def refresh_combo_theme(item):
    if not dpg.does_item_exist(item):
        return
    enabled = _item_enabled(item)
    dpg.bind_item_theme(
        item,
        combo_theme(focused=enabled and _item_has_focus(item), disabled=not enabled),
    )


def _bind_focus_refresh(item, callback):
    """Bind lightweight state handlers; caller owns/deletes the registry."""
    callback(item)
    try:
        with dpg.item_handler_registry() as registry:
            # Focus covers keyboard/tab navigation; activated/deactivated cover
            # mouse editing and popup close.  Re-reading item state prevents a
            # release from accidentally removing a still-focused blue frame.
            if hasattr(dpg, 'add_item_focus_handler'):
                dpg.add_item_focus_handler(callback=lambda *_: callback(item))
            if hasattr(dpg, 'add_item_activated_handler'):
                dpg.add_item_activated_handler(callback=lambda *_: callback(item))
            if hasattr(dpg, 'add_item_deactivated_handler'):
                dpg.add_item_deactivated_handler(callback=lambda *_: callback(item))
        dpg.bind_item_handler_registry(item, registry)
        return registry
    except Exception:
        return None


def bind_line_edit_style(item):
    """Style a native input as QLineEdit and return its handler registry."""
    return _bind_focus_refresh(item, refresh_line_edit_theme)


def bind_combo_style(item):
    """Style a native combo as QComboBox and return its handler registry."""
    return _bind_focus_refresh(item, refresh_combo_theme)


def dialog_theme():
    """Theme common DPG dialogs like a compact Qt/Fusion ``QDialog``."""
    global _DIALOG_THEME
    if _is_theme(_DIALOG_THEME):
        return _DIALOG_THEME

    p = QtFusionPalette
    m = QtFusionMetrics
    with dpg.theme() as _DIALOG_THEME:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, p.WINDOW)
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.WINDOW)
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, p.MENU)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (0, 120, 215, 105))
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, p.SHADOW)
            dpg.add_theme_color(dpg.mvThemeCol_Separator, p.BORDER_LIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Button, p.BUTTON)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_Header, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.HIGHLIGHT_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, p.HIGHLIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_NavHighlight, p.FOCUS)
            # Native Qt dialogs on Windows block the owner but do not paint the
            # heavy Dear ImGui modal dim layer over it.
            dpg.add_theme_color(dpg.mvThemeCol_ModalWindowDimBg, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_TitleBg, p.TITLE)
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, p.TITLE_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgCollapsed, p.TITLE)
            dpg.add_theme_color(dpg.mvThemeCol_MenuBarBg, p.TOOLBAR)
            dpg.add_theme_color(dpg.mvThemeCol_TableHeaderBg, p.TOOLBAR)
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderStrong, p.BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, p.BORDER_LIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_TableRowBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_TableRowBgAlt, p.ALTERNATE_BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Tab, p.BUTTON)
            dpg.add_theme_color(dpg.mvThemeCol_TabHovered, p.BUTTON_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_TabActive, p.BASE)
            add_dpg_scroller_style(dpg)
            dpg.add_theme_style(
                dpg.mvStyleVar_WindowPadding,
                DialogMetrics.WINDOW_PAD_X,
                DialogMetrics.WINDOW_PAD_Y,
            )
            dpg.add_theme_style(
                dpg.mvStyleVar_FramePadding,
                DialogMetrics.FRAME_PAD_X,
                DialogMetrics.FRAME_PAD_Y,
            )
            dpg.add_theme_style(
                dpg.mvStyleVar_ItemSpacing,
                m.ITEM_SPACING_X,
                DialogMetrics.ROW_SPACING,
            )
            dpg.add_theme_style(dpg.mvStyleVar_ItemInnerSpacing, 5, 4)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, m.WINDOW_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, m.POPUP_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, m.FRAME_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, m.CHILD_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, m.GRAB_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, m.WINDOW_BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, m.FRAME_BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 4, 2)

        # The primary client area has no extra inset. Body/card/footer children
        # own their padding, matching the earlier modern Tk dialog shell.
        with dpg.theme_component(dpg.mvWindowAppItem):
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)

        # Normal QDialog buttons are neutral.  The default/accept button is
        # explicitly rebound to ``primary_button_theme`` by DialogBase.
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, p.BUTTON)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, m.FRAME_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 3)

        with dpg.theme_component(dpg.mvCheckbox):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, p.HIGHLIGHT_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, p.HIGHLIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER_DARK)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, m.CHECKBOX_PAD, m.CHECKBOX_PAD)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 1)

        # Generic QLineEdit/QSpinBox/QListView chrome.  Text fields and combos
        # that are created through QtDialog are rebound to state-aware item
        # themes below, while these defaults keep legacy/direct controls visually
        # compatible.
        for component in (dpg.mvInputText, dpg.mvInputInt, dpg.mvInputFloat,
                          dpg.mvListbox):
            with dpg.theme_component(component):
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, p.BASE)
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, p.BASE)
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, p.BASE)
                dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
                dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
                cursor_role = getattr(dpg, "mvThemeCol_InputTextCursor", None)
                if cursor_role is not None:
                    dpg.add_theme_color(cursor_role, p.TEXT)
                dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
                dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (0, 120, 215, 115))
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 3)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 1)

        # QComboBox preview and arrow share one outer frame; the arrow subcontrol
        # uses Qt button roles while the preview remains a white editor surface.
        with dpg.theme_component(dpg.mvCombo):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Button, p.BUTTON)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, p.MENU)
            dpg.add_theme_color(dpg.mvThemeCol_Header, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.MENU_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.MENU_ACTIVE)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 3)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 1)
            dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, 1)

        with dpg.theme_component(dpg.mvRadioButton):
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, p.HIGHLIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 4)

        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_color(dpg.mvThemeCol_Header, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.HIGHLIGHT_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.HIGHLIGHT_SOFT)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_style(dpg.mvStyleVar_SelectableTextAlign, 0.0, 0.5)

        with dpg.theme_component(dpg.mvProgressBar):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_PlotHistogram, p.HIGHLIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_PlotHistogramHovered, p.HIGHLIGHT)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 1)

        with dpg.theme_component(dpg.mvTable):
            dpg.add_theme_color(dpg.mvThemeCol_TableHeaderBg, p.TOOLBAR)
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderStrong, p.BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, p.BORDER_LIGHT)
            dpg.add_theme_color(dpg.mvThemeCol_TableRowBg, p.BASE)
            dpg.add_theme_color(dpg.mvThemeCol_TableRowBgAlt, p.ALTERNATE_BASE)
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 5, 3)
    return _DIALOG_THEME


def primary_button_theme():
    """Qt default button: neutral face with the blue default/focus border."""
    global _PRIMARY_BUTTON_THEME
    if _is_theme(_PRIMARY_BUTTON_THEME):
        return _PRIMARY_BUTTON_THEME
    p = QtFusionPalette
    with dpg.theme() as _PRIMARY_BUTTON_THEME:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, p.BUTTON)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.FOCUS)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 3)
    return _PRIMARY_BUTTON_THEME


def secondary_button_theme():
    global _SECONDARY_BUTTON_THEME
    if _is_theme(_SECONDARY_BUTTON_THEME):
        return _SECONDARY_BUTTON_THEME
    p = QtFusionPalette
    with dpg.theme() as _SECONDARY_BUTTON_THEME:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, p.BUTTON)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 3)
    return _SECONDARY_BUTTON_THEME


def danger_button_theme():
    global _DANGER_BUTTON_THEME
    if _is_theme(_DANGER_BUTTON_THEME):
        return _DANGER_BUTTON_THEME
    p = QtFusionPalette
    with dpg.theme() as _DANGER_BUTTON_THEME:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, p.BUTTON)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (252, 235, 233, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (248, 218, 214, 255))
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.DANGER)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.DANGER)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 3)
    return _DANGER_BUTTON_THEME


def title_theme():
    global _TITLE_THEME
    if _is_theme(_TITLE_THEME):
        return _TITLE_THEME
    with dpg.theme() as _TITLE_THEME:
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, DialogPalette.TITLE)
    return _TITLE_THEME


def error_theme():
    global _ERROR_THEME
    if _is_theme(_ERROR_THEME):
        return _ERROR_THEME
    with dpg.theme() as _ERROR_THEME:
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, DialogPalette.ERROR)
    return _ERROR_THEME


def surface_theme():
    """QGroupBox-like surface: same window background, subtle square border."""
    global _SURFACE_THEME
    if not _is_theme(_SURFACE_THEME):
        with dpg.theme() as _SURFACE_THEME:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, DialogPalette.WINDOW_BG)
                dpg.add_theme_color(dpg.mvThemeCol_Border, DialogPalette.BORDER)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, DialogMetrics.GROUP_PAD_X, DialogMetrics.GROUP_PAD_Y)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 1)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 5, DialogMetrics.ROW_SPACING)
    return _SURFACE_THEME


def body_theme():
    global _BODY_THEME
    if not _is_theme(_BODY_THEME):
        with dpg.theme() as _BODY_THEME:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, DialogPalette.WINDOW_BG)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, DialogMetrics.WINDOW_PAD_X, DialogMetrics.WINDOW_PAD_Y)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 5, DialogMetrics.ROW_SPACING)
    return _BODY_THEME


def footer_theme():
    global _FOOTER_THEME
    if not _is_theme(_FOOTER_THEME):
        with dpg.theme() as _FOOTER_THEME:
            with dpg.theme_component(dpg.mvChildWindow):
                # QDialogButtonBox is part of the dialog surface; avoid a
                # separate gray footer band that makes small forms look split in two.
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, QtFusionPalette.WINDOW)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 10, 6)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, DialogMetrics.BUTTON_GAP, 0)
            with dpg.theme_component(dpg.mvTable):
                dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 0, 0)
    return _FOOTER_THEME


def muted_text_theme():
    global _MUTED_TEXT_THEME
    if not _is_theme(_MUTED_TEXT_THEME):
        with dpg.theme() as _MUTED_TEXT_THEME:
            with dpg.theme_component(dpg.mvText):
                dpg.add_theme_color(dpg.mvThemeCol_Text, DialogPalette.MUTED)
    return _MUTED_TEXT_THEME


def error_text_theme():
    global _ERROR_TEXT_THEME
    if not _is_theme(_ERROR_TEXT_THEME):
        with dpg.theme() as _ERROR_TEXT_THEME:
            with dpg.theme_component(dpg.mvText):
                dpg.add_theme_color(dpg.mvThemeCol_Text, DialogPalette.ERROR)
    return _ERROR_TEXT_THEME


def navigation_theme():
    """QListView-like navigation pane used by Settings and future dialogs.

    The pane intentionally reads as a navigation view, not a stack of ImGui
    buttons: flat rows, one subtle selected fill, no rounded cards and a light
    frame around the whole viewport.
    """
    global _NAV_THEME
    if not _is_theme(_NAV_THEME):
        p = QtFusionPalette
        with dpg.theme() as _NAV_THEME:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, p.WINDOW)
                dpg.add_theme_color(dpg.mvThemeCol_Border, p.BORDER_LIGHT)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 6, 6)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 1)
            with dpg.theme_component(dpg.mvSelectable):
                dpg.add_theme_color(dpg.mvThemeCol_Header, p.HIGHLIGHT_SOFT)
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, p.HIGHLIGHT_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, p.BUTTON_ACTIVE)
                dpg.add_theme_color(dpg.mvThemeCol_NavHighlight, p.FOCUS)
                dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
                dpg.add_theme_style(dpg.mvStyleVar_SelectableTextAlign, 0.0, 0.5)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 3)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
    return _NAV_THEME
