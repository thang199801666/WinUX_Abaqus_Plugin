"""Qt/Fusion-inspired Dear ImGui style foundation for WinUx.

This module deliberately does not import Qt, Tk or Dear PyGui at import time.
Callers pass their Dear PyGui backend so the same widget contracts remain easy
to unit-test with a fake backend.  The implementation is 100% Dear ImGui/DPG;
Qt terminology is used only for visual and behavioral semantics.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..components.qt_style import QtFusionMetrics, QtFusionPalette


@dataclass(frozen=True)
class ImGuiQtControlMetrics:
    control_height: int = 26
    button_height: int = 26
    frame_pad_x: int = 6
    frame_pad_y: int = 4
    border_size: int = 1
    frame_rounding: int = 1
    arrow_width: int = 22
    spin_arrow_width: int = 17
    check_size: int = 14
    row_height: int = 26
    popup_row_height: int = 24
    header_height: int = 26
    tab_height: int = 26
    menu_row_height: int = 23
    form_label_top_pad: int = 4


METRICS = ImGuiQtControlMetrics()


def _theme_exists(backend, tag):
    try:
        return bool(backend.does_item_exist(tag))
    except Exception:
        return False


def _make_theme(backend, tag, builder):
    if _theme_exists(backend, tag):
        return tag
    with backend.theme(tag=tag):
        builder()
    return tag


def line_edit_theme(backend, *, disabled=False, focused=False):
    """Direct ``mvInputText`` theme with a QLineEdit-like focus frame.

    Focus is represented only by the native InputText border colour.  No shell,
    overlay or click handler is introduced, so Dear ImGui still owns mouse
    activation, selection, insertion position and caret blinking end-to-end.
    """
    state = "disabled" if disabled else ("focus" if focused else "normal")
    tag = "winux.imguiqt.lineedit.{}".format(state)
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvInputText):
            bg = p.BUTTON_DISABLED if disabled else p.BASE
            text = p.TEXT_DISABLED if disabled else p.TEXT
            border = p.BORDER_LIGHT if disabled else (p.FOCUS if focused else p.BORDER)
            backend.add_theme_color(backend.mvThemeCol_FrameBg, bg)
            backend.add_theme_color(backend.mvThemeCol_FrameBgHovered, bg)
            backend.add_theme_color(backend.mvThemeCol_FrameBgActive, bg)
            backend.add_theme_color(backend.mvThemeCol_Text, text)
            backend.add_theme_color(backend.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            cursor_role = getattr(backend, "mvThemeCol_InputTextCursor", None)
            if cursor_role is not None:
                backend.add_theme_color(cursor_role, p.TEXT_DISABLED if disabled else p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_TextSelectedBg, (0, 120, 215, 115))
            backend.add_theme_color(backend.mvThemeCol_Border, border)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(
                backend.mvStyleVar_FramePadding,
                METRICS.frame_pad_x,
                METRICS.frame_pad_y + 1,
            )
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, METRICS.border_size)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, METRICS.frame_rounding)
    return _make_theme(backend, tag, build)


def button_theme(backend, *, role="secondary", disabled=False, focused=False, default=False):
    """Fusion-like QPushButton surface including default/focus semantics."""
    role = str(role or "secondary").lower()
    if role not in ("secondary", "primary", "danger", "flat"):
        role = "secondary"
    state = "disabled" if disabled else ("focus" if focused else "normal")
    tag = "winux.imguiqt.button.{}.{}.{}".format(
        role, state, "default" if default else "plain")
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvButton):
            if disabled:
                face = hover = active = p.BUTTON_DISABLED
                text = p.TEXT_DISABLED
                border = p.BORDER_LIGHT
            elif role == "danger":
                face, hover, active = p.BUTTON, (252, 235, 233, 255), (248, 218, 214, 255)
                text = p.DANGER
                border = p.FOCUS if focused else p.DANGER
            elif role == "flat":
                face, hover, active = p.WINDOW, p.BUTTON_HOVER, p.BUTTON_ACTIVE
                text = p.TEXT
                border = p.FOCUS if focused else p.WINDOW
            else:
                face, hover, active = p.BUTTON, p.BUTTON_HOVER, p.BUTTON_ACTIVE
                text = p.TEXT
                border = p.FOCUS if (focused or default or role == "primary") else p.BORDER
            backend.add_theme_color(backend.mvThemeCol_Button, face)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, hover)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, active)
            backend.add_theme_color(backend.mvThemeCol_Text, text)
            backend.add_theme_color(backend.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            backend.add_theme_color(backend.mvThemeCol_Border, border)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, METRICS.border_size)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, METRICS.frame_rounding)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 8, 3)
            text_align = getattr(backend, "mvStyleVar_ButtonTextAlign", None)
            if text_align is not None:
                backend.add_theme_style(text_align, 0.5, 0.5)
    return _make_theme(backend, tag, build)


def checkbox_theme(backend, *, disabled=False, checked=False, focused=False):
    """QCheckBox-like indicator states using the native Dear ImGui checkbox.

    Dear ImGui still owns the checkbox hit target and checkmark geometry.  The
    retained wrapper swaps only state themes so a checked indicator gets the
    Fusion blue fill/white mark while unchecked remains white with a dark edge.
    """
    state = "disabled" if disabled else ("focus" if focused else "normal")
    tag = "winux.imguiqt.checkbox.{}.{}".format(
        "checked" if checked else "unchecked", state)
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvCheckbox):
            if disabled:
                bg = p.SELECTION_INACTIVE if checked else p.BUTTON_DISABLED
                hover = active = bg
                mark = p.TEXT_DISABLED
                border = p.BORDER_LIGHT
                text = p.TEXT_DISABLED
            elif checked:
                bg = p.HIGHLIGHT
                hover = p.PRIMARY_HOVER
                active = p.PRIMARY_ACTIVE
                mark = p.HIGHLIGHT_TEXT
                border = p.FOCUS if focused else p.HIGHLIGHT
                text = p.TEXT
            else:
                bg = p.BASE
                hover = p.HIGHLIGHT_HOVER
                active = p.HIGHLIGHT_SOFT
                mark = p.HIGHLIGHT_TEXT
                border = p.FOCUS if focused else p.BORDER
                text = p.TEXT
            backend.add_theme_color(backend.mvThemeCol_FrameBg, bg)
            backend.add_theme_color(backend.mvThemeCol_FrameBgHovered, hover)
            backend.add_theme_color(backend.mvThemeCol_FrameBgActive, active)
            backend.add_theme_color(backend.mvThemeCol_CheckMark, mark)
            backend.add_theme_color(backend.mvThemeCol_Text, text)
            backend.add_theme_color(backend.mvThemeCol_Border, border)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            # A Qt/Fusion indicator is close to the font height, not the
            # oversized ImGui default square. Keep the native hit target while
            # reducing only the painted indicator geometry.
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 6, 3)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 1)
    return _make_theme(backend, tag, build)


def radio_group_theme(backend, *, disabled=False, focused=False):
    """Fusion-like styling for Dear ImGui's native radio-button group.

    The native radio item remains the complete hit target; this theme changes
    only palette/spacing roles so keyboard navigation and mouse selection stay
    owned by Dear ImGui.
    """
    state = "disabled" if disabled else ("focus" if focused else "normal")
    tag = "winux.imguiqt.radio.{}".format(state)
    p = QtFusionPalette
    component = getattr(backend, "mvRadioButton", None)

    def build():
        if component is None:
            return
        with backend.theme_component(component):
            bg = p.BUTTON_DISABLED if disabled else p.BASE
            hover = bg if disabled else p.HIGHLIGHT_HOVER
            active = bg if disabled else p.HIGHLIGHT_SOFT
            text = p.TEXT_DISABLED if disabled else p.TEXT
            mark = p.TEXT_DISABLED if disabled else p.HIGHLIGHT
            backend.add_theme_color(backend.mvThemeCol_FrameBg, bg)
            backend.add_theme_color(backend.mvThemeCol_FrameBgHovered, hover)
            backend.add_theme_color(backend.mvThemeCol_FrameBgActive, active)
            backend.add_theme_color(backend.mvThemeCol_CheckMark, mark)
            backend.add_theme_color(backend.mvThemeCol_Text, text)
            backend.add_theme_color(backend.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            backend.add_theme_color(
                backend.mvThemeCol_NavHighlight,
                p.FOCUS if focused and not disabled else p.HIGHLIGHT,
            )
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 1, 1)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 6, 4)
    return _make_theme(backend, tag, build)


def progress_theme(backend, *, state="normal"):
    state = str(state or "normal").lower()
    if state not in ("normal", "error", "paused", "success"):
        state = "normal"
    tag = "winux.imguiqt.progress.{}".format(state)
    p = QtFusionPalette
    fill = {
        "normal": p.HIGHLIGHT,
        "error": p.DANGER,
        "paused": (205, 132, 0, 255),
        "success": (26, 127, 55, 255),
    }[state]

    def build():
        with backend.theme_component(backend.mvProgressBar):
            backend.add_theme_color(backend.mvThemeCol_FrameBg, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER)
            backend.add_theme_color(backend.mvThemeCol_PlotHistogram, fill)
            backend.add_theme_color(backend.mvThemeCol_PlotHistogramHovered, fill)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 1)
    return _make_theme(backend, tag, build)


def transfer_progress_host_theme(backend):
    """Transparent host used to layer a centered percentage over a progress bar."""
    tag = "winux.imguiqt.transferprogresshost"

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, (0, 0, 0, 0))
            backend.add_theme_color(backend.mvThemeCol_Border, (0, 0, 0, 0))
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def transfer_progress_text_theme(backend, *, light=False):
    """Readable centered progress text for light and filled portions."""
    tag = "winux.imguiqt.transferprogresstext.{}".format("light" if light else "dark")
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvText):
            backend.add_theme_color(
                backend.mvThemeCol_Text,
                (255, 255, 255, 255) if light else p.TEXT,
            )
    return _make_theme(backend, tag, build)


def transfer_row_theme(backend):
    """Flat QFrame-like surface for one Transfer Center item.

    Transfer rows are interactive status records, not cards.  Use a square,
    single-pixel frame with the base palette and compact padding so multiple
    rows read like a QListView rather than stacked Dear ImGui child panels.
    """
    tag = "winux.imguiqt.transferrow"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 8, 6)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 6, 4)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
        with backend.theme_component(backend.mvTable):
            backend.add_theme_style(backend.mvStyleVar_CellPadding, 0, 1)
    return _make_theme(backend, tag, build)


def group_box_theme(backend):
    tag = "winux.imguiqt.groupbox"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.WINDOW)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 8, 6)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 1)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 6, 4)
    return _make_theme(backend, tag, build)



def spin_editor_theme(backend, *, kind="int", disabled=False):
    """Borderless scalar editor used inside :class:`ImGuiSpinBox` shells."""
    kind = "float" if str(kind).lower().startswith("float") else "int"
    tag = "winux.imguiqt.spin.editor.{}.{}".format(
        kind, "disabled" if disabled else "normal")
    p = QtFusionPalette
    component_name = "mvInputFloat" if kind == "float" else "mvInputInt"
    component = getattr(backend, component_name, None)

    def build():
        if component is None:
            return
        with backend.theme_component(component):
            bg = p.BUTTON_DISABLED if disabled else p.BASE
            backend.add_theme_color(backend.mvThemeCol_FrameBg, bg)
            backend.add_theme_color(backend.mvThemeCol_FrameBgHovered, bg)
            backend.add_theme_color(backend.mvThemeCol_FrameBgActive, bg)
            backend.add_theme_color(
                backend.mvThemeCol_Text,
                p.TEXT_DISABLED if disabled else p.TEXT,
            )
            cursor_role = getattr(backend, "mvThemeCol_InputTextCursor", None)
            if cursor_role is not None:
                backend.add_theme_color(
                    cursor_role, p.TEXT_DISABLED if disabled else p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_TextSelectedBg, (0, 120, 215, 115))
            backend.add_theme_style(
                backend.mvStyleVar_FramePadding,
                METRICS.frame_pad_x,
                METRICS.frame_pad_y,
            )
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
    return _make_theme(backend, tag, build)


def spin_shell_theme(backend, *, focused=False, disabled=False):
    """One outer frame shared by the scalar editor and up/down sub-control."""
    state = "disabled" if disabled else ("focus" if focused else "normal")
    tag = "winux.imguiqt.spin.shell.{}".format(state)
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(
                backend.mvThemeCol_ChildBg,
                p.BUTTON_DISABLED if disabled else p.BASE,
            )
            backend.add_theme_color(
                backend.mvThemeCol_Border,
                p.BORDER_LIGHT if disabled else (p.FOCUS if focused else p.BORDER),
            )
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, METRICS.frame_rounding)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, METRICS.border_size)
        with backend.theme_component(backend.mvTable):
            backend.add_theme_style(backend.mvStyleVar_CellPadding, 0, 0)
    return _make_theme(backend, tag, build)


def spin_button_theme(backend, *, disabled=False):
    """Qt-style small spin-button sub-control with no independent border."""
    tag = "winux.imguiqt.spin.button.{}".format("disabled" if disabled else "normal")
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvButton):
            face = p.BUTTON_DISABLED if disabled else p.BASE
            backend.add_theme_color(backend.mvThemeCol_Button, face)
            backend.add_theme_color(
                backend.mvThemeCol_ButtonHovered,
                face if disabled else p.HIGHLIGHT_HOVER,
            )
            backend.add_theme_color(
                backend.mvThemeCol_ButtonActive,
                face if disabled else p.HIGHLIGHT_SOFT,
            )
            backend.add_theme_color(
                backend.mvThemeCol_Text,
                p.TEXT_DISABLED if disabled else p.TEXT,
            )
            backend.add_theme_color(backend.mvThemeCol_Border, face)
            # Spin arrows are sub-controls of one framed editor.  Suppress an
            # independent navigation rectangle and keep glyphs geometrically
            # centered in their 17 px strip.
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, face)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 0, 0)
            text_align = getattr(backend, "mvStyleVar_ButtonTextAlign", None)
            if text_align is not None:
                backend.add_theme_style(text_align, 0.5, 0.5)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
    return _make_theme(backend, tag, build)



def compact_stack_theme(backend):
    """Zero item spacing for compact vertical alignment lanes.

    Used by table cells that need Qt-like vertical centering without Dear
    ImGui's default item gap being added after a spacer.
    """
    tag = "winux.imguiqt.compactstack"

    def build():
        with backend.theme_component(backend.mvAll):
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 0, 0)

    return _make_theme(backend, tag, build)

def spin_button_stack_theme(backend):
    """Remove vertical ImGui item spacing between the two spin sub-buttons."""
    tag = "winux.imguiqt.spin.buttonstack"

    def build():
        with backend.theme_component(backend.mvAll):
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 0, 0)

    return _make_theme(backend, tag, build)


def separator_theme(backend):
    tag = "winux.imguiqt.separator.vertical"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.BORDER_LIGHT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def form_label_cell_theme(backend):
    """Vertically center labels inside a compact QFormLayout row.

    Dear ImGui tables do not expose Qt's per-cell vertical alignment.  Hosting
    the label in a borderless 26 px child gives the label a predictable top
    inset while keeping the table itself responsible for column geometry.
    """
    tag = "winux.imguiqt.form.labelcell"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.WINDOW)
            backend.add_theme_color(backend.mvThemeCol_Border, p.WINDOW)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 5)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)

    return _make_theme(backend, tag, build)


def form_row_theme(backend):
    """Compact QFormLayout-like row table with no hidden cell padding.

    DPG tables inherit application-level ``CellPadding``.  A separate table is
    used for each labeled form row, so inherited padding accumulates visually
    and makes dialogs look much looser than Qt/Fusion.  Keep row geometry in
    one reusable theme instead.
    """
    tag = "winux.imguiqt.formrow"

    def build():
        with backend.theme_component(backend.mvTable):
            backend.add_theme_style(backend.mvStyleVar_CellPadding, 0, 2)

    return _make_theme(backend, tag, build)


def tab_widget_theme(backend):
    """Compact Fusion-like QTabWidget/QTabBar theme for native DPG tabs.

    Keep the native ImGui tab implementation for input/clipping, but remove
    the pill/card treatment that makes default Dear ImGui tabs look foreign in
    a Windows/Qt shell.  Tabs share edges, use a flat base surface and reserve
    the blue accent for navigation/focus rather than painting a large rounded
    button.
    """
    tag = "winux.imguiqt.tabs"
    p = QtFusionPalette

    def build():
        tab_component = getattr(backend, "mvTab", None)
        if tab_component is not None:
            with backend.theme_component(tab_component):
                backend.add_theme_color(backend.mvThemeCol_Tab, p.BUTTON)
                backend.add_theme_color(backend.mvThemeCol_TabHovered, p.BUTTON_HOVER)
                backend.add_theme_color(backend.mvThemeCol_TabActive, p.BASE)
                backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
                backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
                backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
                backend.add_theme_style(backend.mvStyleVar_FramePadding, 9, 4)
                backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
                backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1)
        tab_bar_component = getattr(backend, "mvTabBar", None)
        if tab_bar_component is not None:
            with backend.theme_component(tab_bar_component):
                backend.add_theme_color(backend.mvThemeCol_Tab, p.BUTTON)
                backend.add_theme_color(backend.mvThemeCol_TabHovered, p.BUTTON_HOVER)
                backend.add_theme_color(backend.mvThemeCol_TabActive, p.BASE)
                backend.add_theme_color(backend.mvThemeCol_Separator, p.BORDER_LIGHT)
                backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
                backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 0, 0)
    return _make_theme(backend, tag, build)


def tool_bar_theme(backend):
    """Compact QToolBar-like surface used by the two Explorer file panes."""
    tag = "winux.imguiqt.toolbar"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.TOOLBAR)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 3, 2)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 2, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
        with backend.theme_component(backend.mvTable):
            backend.add_theme_style(backend.mvStyleVar_CellPadding, 0, 0)
    return _make_theme(backend, tag, build)


def tool_button_theme(backend, *, disabled=False):
    """Qt/Fusion QToolButton visual contract for image/text toolbar actions."""
    tag = "winux.imguiqt.toolbutton.{}".format("disabled" if disabled else "normal")
    p = QtFusionPalette

    def style(component):
        with backend.theme_component(component):
            face = (0, 0, 0, 0)
            hover = face if disabled else p.BUTTON_HOVER
            active = face if disabled else p.BUTTON_ACTIVE
            backend.add_theme_color(backend.mvThemeCol_Button, face)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, hover)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, active)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT_DISABLED if disabled else p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_Border, (0, 0, 0, 0))
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 1)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 4, 3)

    def build():
        style(backend.mvImageButton)
        style(backend.mvButton)
    return _make_theme(backend, tag, build)


def path_bar_theme(backend):
    """Read-only QLineEdit-like path selector rendered as a clickable button."""
    tag = "winux.imguiqt.pathbar"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvButton):
            backend.add_theme_color(backend.mvThemeCol_Button, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, p.HIGHLIGHT_HOVER)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 1)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 6, 2)
            align = getattr(backend, "mvStyleVar_ButtonTextAlign", None)
            if align is not None:
                backend.add_theme_style(align, 0.0, 0.5)
    return _make_theme(backend, tag, build)


def status_bar_theme(backend):
    """Compact QStatusBar surface used below the two Explorer panes.

    A status bar should read as the bottom edge of the view rather than a
    second toolbar.  Use the alternate window surface, one-pixel-friendly
    vertical padding and muted spacing while the layout owner provides the
    actual 20 px strip height.
    """
    tag = "winux.imguiqt.statusbar"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.WINDOW_ALT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 6, 1)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 5, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def status_text_theme(backend, *, muted=False):
    tag = "winux.imguiqt.status.text.{}".format("muted" if muted else "normal")
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvText):
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT_MUTED if muted else p.TEXT)
    return _make_theme(backend, tag, build)



def application_theme(backend):
    """Application-wide Qt/Fusion baseline for Dear ImGui widgets.

    More specific component themes (Explorer, dialogs, toolbars, item views)
    intentionally override this baseline.  Keeping the generic state colours in
    one place prevents unstyled controls from falling back to Dear ImGui's
    default dark/rounded visual language.
    """
    tag = "winux.imguiqt.application"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvAll):
            backend.add_theme_color(backend.mvThemeCol_WindowBg, p.WINDOW)
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.WINDOW)
            backend.add_theme_color(backend.mvThemeCol_PopupBg, p.MENU)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER)
            backend.add_theme_color(backend.mvThemeCol_Separator, p.BORDER_LIGHT)
            backend.add_theme_color(backend.mvThemeCol_FrameBg, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_FrameBgHovered, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_FrameBgActive, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_Button, p.BUTTON)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
            backend.add_theme_color(backend.mvThemeCol_Header, p.HIGHLIGHT_SOFT)
            backend.add_theme_color(backend.mvThemeCol_HeaderHovered, p.HIGHLIGHT_HOVER)
            backend.add_theme_color(backend.mvThemeCol_HeaderActive, p.HIGHLIGHT_SOFT)
            backend.add_theme_color(backend.mvThemeCol_CheckMark, p.HIGHLIGHT)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_color(backend.mvThemeCol_MenuBarBg, p.TOOLBAR)
            backend.add_theme_style(backend.mvStyleVar_WindowRounding, QtFusionMetrics.WINDOW_ROUNDING)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 1)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 6, 4)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 5, 4)
    return _make_theme(backend, tag, build)


def menu_bar_theme(backend):
    """Qt/Fusion-like QMenuBar/QMenu baseline for application command menus.

    The command rows intentionally use a clearer blue hover/pressed surface,
    darker text and slightly taller padding.  This keeps the menu looking like
    a native Qt command list instead of a set of labels floating on a pale
    popup background.
    """
    tag = "winux.imguiqt.menubar.rev58"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvAll):
            backend.add_theme_color(backend.mvThemeCol_MenuBarBg, p.TOOLBAR)
            backend.add_theme_color(backend.mvThemeCol_PopupBg, p.MENU)
            backend.add_theme_color(backend.mvThemeCol_WindowBg, p.MENU)
            backend.add_theme_color(backend.mvThemeCol_Text, (24, 24, 24, 255))
            backend.add_theme_color(backend.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER)
            backend.add_theme_color(backend.mvThemeCol_Separator, p.BORDER_LIGHT)
            backend.add_theme_color(backend.mvThemeCol_Header, (0, 0, 0, 0))
            backend.add_theme_color(backend.mvThemeCol_HeaderHovered, p.HIGHLIGHT_HOVER)
            backend.add_theme_color(backend.mvThemeCol_HeaderActive, p.HIGHLIGHT_SOFT)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 4, 5)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 4, 2)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 6, 2)
            backend.add_theme_style(backend.mvStyleVar_PopupRounding, QtFusionMetrics.POPUP_ROUNDING)
            backend.add_theme_style(backend.mvStyleVar_WindowBorderSize, 1)
        menu_component = getattr(backend, "mvMenu", None)
        if menu_component is not None:
            with backend.theme_component(menu_component):
                backend.add_theme_style(backend.mvStyleVar_FramePadding, 8, 4)
        selectable = getattr(backend, "mvSelectable", None)
        if selectable is not None:
            with backend.theme_component(selectable):
                backend.add_theme_color(backend.mvThemeCol_HeaderHovered, p.HIGHLIGHT_HOVER)
                backend.add_theme_color(backend.mvThemeCol_HeaderActive, p.HIGHLIGHT_SOFT)
                backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
                backend.add_theme_style(backend.mvStyleVar_FramePadding, 7, 5)
                backend.add_theme_style(backend.mvStyleVar_SelectableTextAlign, 0.0, 0.5)
    return _make_theme(backend, tag, build)


def command_button_theme(backend, *, checked=False, disabled=False):
    """QToolButton-like command surface for top-level utility actions."""
    state = "disabled" if disabled else ("checked" if checked else "normal")
    tag = "winux.imguiqt.commandbutton." + state
    p = QtFusionPalette

    def style(component):
        with backend.theme_component(component):
            normal = p.HIGHLIGHT_SOFT if checked and not disabled else (0, 0, 0, 0)
            hover = normal if disabled else p.BUTTON_HOVER
            active = normal if disabled else p.BUTTON_ACTIVE
            backend.add_theme_color(backend.mvThemeCol_Button, normal)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, hover)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, active)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT_DISABLED if disabled else p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER if checked and not disabled else (0, 0, 0, 0))
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1 if checked and not disabled else 0)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 1)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 4, 3)

    def build():
        style(backend.mvButton)
        style(backend.mvImageButton)
    return _make_theme(backend, tag, build)


def panel_surface_theme(backend, *, bordered=True, compact=False, alternate=False):
    """QWidget/QFrame-like panel surface shared by docks and tool panes."""
    state = "alt" if alternate else "base"
    density = "compact" if compact else "normal"
    border_state = "border" if bordered else "flat"
    tag = "winux.imguiqt.panel.{}.{}.{}".format(state, density, border_state)
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(
                backend.mvThemeCol_ChildBg,
                p.WINDOW_ALT if alternate else p.BASE,
            )
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
            backend.add_theme_style(
                backend.mvStyleVar_WindowPadding,
                5 if compact else 8,
                4 if compact else 7,
            )
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 5, 4)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 1 if bordered else 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def panel_header_theme(backend):
    """Flat QToolBar/QWidget header strip for docked tool panels.

    This is intentionally distinct from the Explorer navigation toolbar: panel
    headers carry status text and small utility actions, so they use the dialog
    window surface with a one-pixel bottom-edge colour rather than a raised
    button-bar treatment.  Geometry remains owned by the host component.
    """
    tag = "winux.imguiqt.panel.header"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.WINDOW_ALT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 6, 3)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 5, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def dock_frame_theme(backend):
    """One-pixel QDockWidget frame without an ImGui child-window border."""
    tag = "winux.imguiqt.dock.frame"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.BORDER)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
    return _make_theme(backend, tag, build)


def dock_title_theme(backend, *, active=True):
    """Compact QDockWidget title surface."""
    tag = "winux.imguiqt.dock.title.{}".format("active" if active else "inactive")
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(
                backend.mvThemeCol_ChildBg,
                p.TITLE_ACTIVE if active else p.TITLE,
            )
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def dock_content_theme(backend):
    """Flush QDockWidget client widget surface."""
    tag = "winux.imguiqt.dock.content"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.BASE)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def dock_control_theme(backend, *, close=False, disabled=False):
    """QDockWidget title button; close uses Windows/Qt danger hover semantics."""
    state = "disabled" if disabled else "normal"
    tag = "winux.imguiqt.dock.control.{}.{}".format("close" if close else "tool", state)
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvButton):
            normal = (0, 0, 0, 0)
            if disabled:
                hover = active = normal
                text = p.TEXT_DISABLED
            elif close:
                hover = (232, 17, 35, 255)
                active = (196, 18, 32, 255)
                text = p.TEXT
            else:
                hover = p.BUTTON_HOVER
                active = p.BUTTON_ACTIVE
                text = p.TEXT
            backend.add_theme_color(backend.mvThemeCol_Button, normal)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, hover)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, active)
            backend.add_theme_color(backend.mvThemeCol_Text, text)
            backend.add_theme_color(backend.mvThemeCol_Border, (0, 0, 0, 0))
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 0, 0)
    return _make_theme(backend, tag, build)


def splitter_theme(backend, *, active=False):
    """QSplitter handle: one painted pixel with a larger independent hitbox."""
    tag = "winux.imguiqt.splitter.{}".format("active" if active else "normal")
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvButton):
            line = p.FOCUS if active else p.BORDER_LIGHT
            backend.add_theme_color(backend.mvThemeCol_Button, line)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, line)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, line)
            backend.add_theme_color(backend.mvThemeCol_Border, line)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 0, 0)
    return _make_theme(backend, tag, build)


def splitter_hitbox_theme(backend):
    """Invisible QSplitter grab halo; geometry lives in layout, not paint."""
    tag = "winux.imguiqt.splitter.hitbox"

    def build():
        with backend.theme_component(backend.mvButton):
            transparent = (0, 0, 0, 0)
            backend.add_theme_color(backend.mvThemeCol_Button, transparent)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, transparent)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, transparent)
            backend.add_theme_color(backend.mvThemeCol_Border, transparent)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 0, 0)
    return _make_theme(backend, tag, build)

def bind_theme(backend, item, theme_factory, **kwargs):
    """Best-effort theme bind for real DPG backends; harmless in fake tests."""
    try:
        backend.bind_item_theme(item, theme_factory(backend, **kwargs))
        return True
    except Exception:
        return False


# Explicit backend names for new code.  QtFusion* are retained for historical
# callers, but these aliases make it clear that the renderer is Dear ImGui.
ImGuiQtPalette = QtFusionPalette
ImGuiQtMetrics = QtFusionMetrics


__all__ = [
    "ImGuiQtControlMetrics", "ImGuiQtPalette", "ImGuiQtMetrics", "METRICS",
    "line_edit_theme", "button_theme", "checkbox_theme", "radio_group_theme", "progress_theme", "transfer_row_theme",
    "group_box_theme", "form_row_theme", "form_label_cell_theme", "spin_editor_theme", "spin_shell_theme",
    "spin_button_theme", "spin_button_stack_theme", "compact_stack_theme", "separator_theme", "tab_widget_theme",
    "tool_bar_theme", "tool_button_theme", "path_bar_theme",
    "status_bar_theme", "status_text_theme", "application_theme",
    "menu_bar_theme", "command_button_theme", "panel_surface_theme", "panel_header_theme",
    "dock_frame_theme", "dock_title_theme", "dock_content_theme",
    "dock_control_theme", "splitter_theme", "splitter_hitbox_theme",
    "bind_theme",
]
