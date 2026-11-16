"""Qt/Fusion-inspired Dear ImGui style foundation for DearUIQt.

This module deliberately does not import Qt, Tk or Dear PyGui at import time.
Callers pass their Dear PyGui backend so the same widget contracts remain easy
to unit-test with a fake backend.  The implementation is 100% Dear ImGui/DPG;
Qt terminology is used only for visual and behavioral semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from functools import lru_cache

from .palette import QtFusionMetrics, QtFusionPalette, color_scheme
from ..backends.dearpygui_scroller import add_dpg_scroller_style


@dataclass(frozen=True)
class ImGuiQtControlMetrics:
    control_height: int = 26
    button_height: int = 26
    tool_button_height: int = 28
    tool_button_icon_size: int = 20
    frame_pad_x: int = 6
    frame_pad_y: int = 4
    editor_frame_pad_y: int = 6
    # Editable QComboBox previews use an explicit full-height 24 px editor.
    # Dear ImGui positions InputText glyphs from the top FramePadding value, so
    # 2 px aligns the text baseline with the adjacent QLineEdit controls while
    # the explicit editor height keeps the entire preview area clickable.
    combo_editor_frame_pad_y: int = 2
    spin_frame_pad_y: int = 5
    border_size: int = 1
    frame_rounding: int = QtFusionMetrics.FRAME_ROUNDING
    button_rounding: int = 5
    arrow_width: int = 22
    spin_arrow_width: int = 17
    check_size: int = 14
    row_height: int = 26
    popup_row_height: int = 24
    header_height: int = 26
    tab_height: int = 26
    menu_row_height: int = 23
    form_label_top_pad: int = 6
    button_pad_x: int = 8
    button_pad_y: int = 3
    tool_button_pad_x: int = 4
    tool_button_pad_y: int = 3
    tab_pad_x: int = 9
    tab_pad_y: int = 4
    menu_bar_pad_x: int = 6
    menu_bar_pad_y: int = 2
    menu_bar_height: int = 20
    splitter_handle_width: int = 5
    splitter_grab_width: int = 7

    def scaled(self, scale):
        """Return an immutable DPI-scaled metric set.

        DearUIQt keeps ``METRICS`` at 96-DPI logical defaults for source
        compatibility. Backends/widgets that operate in physical pixels can
        materialize a scaled copy without mutating process-global style state.
        """
        try:
            factor = float(scale)
        except (TypeError, ValueError, OverflowError):
            factor = 1.0
        factor = max(.25, min(8.0, factor))
        values = {}
        for field in fields(self):
            original = int(getattr(self, field.name))
            scaled = int(round(original * factor))
            if original > 0:
                scaled = max(1, scaled)
            values[field.name] = scaled
        return type(self)(**values)


@lru_cache(maxsize=32)
def _metrics_for_scale_key(scale_milli):
    return METRICS.scaled(float(scale_milli) / 1000.0)


def metrics_for_dpi(dpi=96.0):
    try:
        factor = float(dpi) / 96.0
    except (TypeError, ValueError, OverflowError):
        factor = 1.0
    factor = max(.25, min(8.0, factor))
    # Immutable metrics are safely shared. Quantising to 1/1000 of a scale
    # avoids allocating a dataclass per widget while preserving sub-pixel-DPI
    # distinctions far beyond the integer pixel metrics the backend consumes.
    return _metrics_for_scale_key(int(round(factor * 1000.0)))


def metrics_for_screen(screen):
    callback = getattr(screen, 'dpiScale', None)
    if callable(callback):
        try:
            return METRICS.scaled(callback())
        except Exception:
            pass
    getter = getattr(screen, 'logicalDotsPerInch', None)
    if callable(getter):
        try:
            return metrics_for_dpi(getter())
        except Exception:
            pass
    return METRICS


def metrics_for_backend(backend=None, *, item=None):
    """Return logical control metrics for a renderer/backend surface.

    Backends may report DPI directly.  Production Dear PyGui currently does
    not, so :mod:`DearUIQt.gui.dpi` can resolve the native top-level HWND on
    Windows.  Passing ``item`` enables per-monitor metrics for secondary
    windows while preserving the 96-DPI compatibility baseline elsewhere.
    """
    if backend is None:
        return METRICS
    try:
        from ..backends import dpg, get_backend
        if backend is dpg:
            backend = get_backend()
    except Exception:
        pass
    try:
        from .dpi import logical_dpi_for_backend
        metrics = metrics_for_dpi(logical_dpi_for_backend(backend, item=item))
        return _font_adjusted_metrics(metrics, backend)
    except Exception:
        return _font_adjusted_metrics(METRICS, backend)


def _metrics_tag(metrics, *names):
    """Compact stable suffix preventing cross-DPI theme cache reuse."""
    if not names:
        names = ('control_height', 'frame_pad_x', 'frame_pad_y', 'border_size')
    return '.m' + 'x'.join(str(int(getattr(metrics, name))) for name in names)



# Application typography profile per renderer backend. DPI controls physical
# scaling; this profile keeps control chrome proportional to the active font.
_TYPOGRAPHY_LINE_HEIGHTS = {}
_REFERENCE_LINE_HEIGHT = 15.0

def set_application_typography(backend, font=None):
    """Record the active application font metrics for *backend*.

    Returns the measured line height.  Existing widgets can then refresh their
    style/geometry via ``QWidget.refreshApplicationTypography``.
    """
    try:
        from .system import QFontMetrics
        line = max(1, int(QFontMetrics(font, backend=backend).lineSpacing()))
    except Exception:
        line = int(_REFERENCE_LINE_HEIGHT)
    _TYPOGRAPHY_LINE_HEIGHTS[id(backend)] = line
    return line

def clear_application_typography(backend):
    _TYPOGRAPHY_LINE_HEIGHTS.pop(id(backend), None)

def _font_adjusted_metrics(metrics, backend):
    line = _TYPOGRAPHY_LINE_HEIGHTS.get(id(backend))
    if not line:
        return metrics
    # Preserve the 15 px baseline exactly.  Smaller fonts may compact controls
    # modestly, while larger fonts get enough vertical room to avoid clipping.
    factor = max(0.85, min(2.5, float(line) / _REFERENCE_LINE_HEIGHT))
    if abs(factor - 1.0) < 0.01:
        return metrics
    values = {f.name: int(getattr(metrics, f.name)) for f in fields(metrics)}
    vertical = (
        'control_height','button_height','tool_button_height','row_height',
        'popup_row_height','header_height','tab_height','menu_row_height',
        'frame_pad_y','editor_frame_pad_y','combo_editor_frame_pad_y',
        'spin_frame_pad_y','button_pad_y','tool_button_pad_y','tab_pad_y',
        'menu_bar_pad_y','menu_bar_height','form_label_top_pad','check_size',
    )
    for name in vertical:
        base = int(getattr(metrics, name))
        values[name] = max(1, int(round(base * factor)))
    # Ensure framed controls are always taller than the measured glyph box.
    border = int(values.get('border_size', 1))
    minimum_control = int(line + max(6, round(line * 0.45)) + border * 2)
    values['control_height'] = max(values['control_height'], minimum_control)
    values['button_height'] = max(values['button_height'], minimum_control)
    values['row_height'] = max(values['row_height'], line + max(5, round(line * .35)))
    values['header_height'] = max(values['header_height'], line + max(6, round(line * .40)))
    return type(metrics)(**values)

METRICS = ImGuiQtControlMetrics()


def _theme_exists(backend, tag):
    try:
        return bool(backend.does_item_exist(tag))
    except Exception:
        return False


def _make_theme(backend, tag, builder):
    # Theme resources are immutable once materialized.  Include the active
    # palette scheme in cache tags so a runtime Light/Dark switch can create a
    # fresh resource instead of accidentally reusing colors from the previous
    # scheme.
    try:
        from .palette import color_scheme
        tag = "{}.{}".format(tag, color_scheme().lower())
    except Exception:
        pass
    if _theme_exists(backend, tag):
        return tag
    with backend.theme(tag=tag):
        # Widget frames must not inherit ImGui's offset border shadow from an
        # application theme: it softens corners and looks like a second edge.
        shadow = getattr(backend, "mvThemeCol_BorderShadow", None)
        target = getattr(backend, "mvAll", None)
        if shadow is not None and target is not None:
            with backend.theme_component(target):
                backend.add_theme_color(shadow, (0, 0, 0, 0))
        builder()
    return tag


def line_edit_theme(backend, *, disabled=False, focused=False):
    """Direct ``mvInputText`` theme with a QLineEdit-like focus frame.

    Focus is represented only by the native InputText border colour.  No shell,
    overlay or click handler is introduced, so Dear ImGui still owns mouse
    activation, selection, insertion position and caret blinking end-to-end.
    """
    state = "disabled" if disabled else ("focus" if focused else "normal")
    metrics = metrics_for_backend(backend)
    tag = "dearuiqt.qt.lineedit.{}{}".format(
        state, _metrics_tag(metrics, 'frame_pad_x', 'editor_frame_pad_y', 'border_size', 'frame_rounding'))
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvInputText, enabled_state=not disabled):
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
            backend.add_theme_color(backend.mvThemeCol_TextSelectedBg, p.HIGHLIGHT[:3] + (115,))
            backend.add_theme_color(backend.mvThemeCol_Border, border)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(
                backend.mvStyleVar_FramePadding,
                metrics.frame_pad_x,
                metrics.editor_frame_pad_y,
            )
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, metrics.border_size)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, metrics.frame_rounding)
    return _make_theme(backend, tag, build)


def button_theme(backend, *, role="secondary", disabled=False, focused=False, default=False, checked=False, hovered=False,
                 frame_padding=(8, 3)):
    """Fusion-like QPushButton surface including default/focus semantics."""
    role = str(role or "secondary").lower()
    if role not in ("secondary", "primary", "danger", "flat"):
        role = "secondary"
    state = "disabled" if disabled else ("focus" if focused else "normal")
    metrics = metrics_for_backend(backend)
    if tuple(frame_padding) == (8, 3):
        frame_padding = (metrics.button_pad_x, metrics.button_pad_y)
    tag = "dearuiqt.qt.button.{}.{}.{}{}".format(
        role, state, "default" if default else "plain",
        _metrics_tag(metrics, 'button_rounding', 'border_size'))
    if checked:
        tag += ".checked"
    if hovered and not disabled:
        tag += ".hover"
    if tuple(frame_padding) != (8, 3):
        tag += ".padding.{}.{}".format(*frame_padding)
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvButton, enabled_state=not disabled):
            # Keep push buttons visibly raised above a WINDOW-colored panel.
            # QtFusionPalette.BUTTON intentionally equals WINDOW in the base
            # palette, which made controls inside Plot Digitizer read like
            # recessed/flat fields.  A brighter idle face plus a slightly
            # stronger edge restores the visual separation without changing
            # button geometry or introducing fake drop shadows.
            dark = color_scheme() == "Dark"
            raised_face = p.BUTTON if dark else (249, 249, 249, 255)
            raised_border = p.BORDER_DARK if dark else (154, 154, 154, 255)
            raised_hover = p.BUTTON_HOVER
            raised_active = p.BUTTON_ACTIVE
            if disabled:
                face = hover = active = p.BUTTON_DISABLED if dark else (238, 238, 238, 255)
                text = p.TEXT_DISABLED
                border = p.BORDER_LIGHT
            elif role == "danger":
                face, hover, active = p.ERROR_BG, p.DANGER_HOVER, p.DANGER_ACTIVE
                border = p.FOCUS if focused else p.DANGER
                text = p.HIGHLIGHT_TEXT if dark else p.DANGER
            elif role == "flat":
                face, hover, active = p.WINDOW, p.BUTTON_HOVER, p.BUTTON_ACTIVE
                text = p.TEXT
                border = p.FOCUS if focused else p.WINDOW
            else:
                face, hover, active = raised_face, raised_hover, raised_active
                text = p.TEXT
                border = p.FOCUS if (focused or default or role == "primary") else raised_border
            if checked and not disabled:
                face = active
                border = p.FOCUS
            if hovered and not disabled:
                face = hover
                border = p.FOCUS
            backend.add_theme_color(backend.mvThemeCol_Button, face)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, hover)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, active)
            backend.add_theme_color(backend.mvThemeCol_Text, text)
            backend.add_theme_color(backend.mvThemeCol_TextDisabled, p.TEXT_DISABLED)
            backend.add_theme_color(backend.mvThemeCol_Border, border)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, metrics.border_size)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, metrics.button_rounding)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, *frame_padding)
            text_align = getattr(backend, "mvStyleVar_ButtonTextAlign", None)
            if text_align is not None:
                backend.add_theme_style(text_align, 0.5, 0.5)
    return _make_theme(backend, tag, build)


def checkbox_theme(backend, *, disabled=False, checked=False, focused=False):
    """QCheckBox-like indicator states using the native Dear ImGui checkbox.

    Dear ImGui still owns the checkbox hit target and checkmark geometry.  The
    retained wrapper swaps only state themes. Fusion uses a dark checkmark on
    a light indicator, reserving blue for the focus outline.
    """
    state = "disabled" if disabled else ("focus" if focused else "normal")
    metrics = metrics_for_backend(backend)
    tag = "dearuiqt.qt.checkbox.{}.{}{}".format(
        "checked" if checked else "unchecked", state,
        _metrics_tag(metrics, 'check_size', 'border_size', 'frame_rounding'))
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvCheckbox, enabled_state=not disabled):
            if disabled:
                bg = p.BUTTON_DISABLED
                hover = active = bg
                mark = p.TEXT_DISABLED
                border = p.BORDER_LIGHT
                text = p.TEXT_DISABLED
            elif checked:
                bg = p.BASE
                hover = p.HIGHLIGHT_HOVER
                active = p.HIGHLIGHT_SOFT
                mark = p.TEXT
                border = p.FOCUS if focused else p.BORDER
                text = p.TEXT
            else:
                bg = p.BASE
                hover = p.HIGHLIGHT_HOVER
                active = p.HIGHLIGHT_SOFT
                mark = p.TEXT
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
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 7, 3)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, metrics.border_size)
            # Native ImGui owns the indicator and hit target; a small radius
            # removes the harsh square corners while preserving the compact
            # Qt/Fusion checkbox silhouette.
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 2)
    return _make_theme(backend, tag, build)


def radio_group_theme(backend, *, disabled=False, focused=False):
    """Fusion-like styling for Dear ImGui's native radio-button group.

    The native radio item remains the complete hit target; this theme changes
    only palette/spacing roles so keyboard navigation and mouse selection stay
    owned by Dear ImGui.
    """
    state = "disabled" if disabled else ("focus" if focused else "normal")
    metrics = metrics_for_backend(backend)
    tag = "dearuiqt.qt.radio.{}{}".format(
        state, _metrics_tag(metrics, 'check_size', 'border_size'))
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
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 7, 4)
    return _make_theme(backend, tag, build)


def slider_theme(backend, *, disabled=False, focused=False):
    """Fusion-like QSlider palette over Dear ImGui's native slider."""
    state = "disabled" if disabled else ("focus" if focused else "normal")
    tag = "dearuiqt.slider.{}".format(state)
    p = QtFusionPalette
    component = getattr(backend, "mvSliderInt", None)

    def build():
        if component is None:
            return
        with backend.theme_component(component, enabled_state=not disabled):
            frame = p.BUTTON_DISABLED if disabled else p.BASE
            grab = p.TEXT_DISABLED if disabled else p.HIGHLIGHT
            grab_active = grab if disabled else p.PRIMARY_ACTIVE
            border = p.BORDER_LIGHT if disabled else (p.FOCUS if focused else p.BORDER)
            backend.add_theme_color(backend.mvThemeCol_FrameBg, frame)
            backend.add_theme_color(backend.mvThemeCol_FrameBgHovered, frame)
            backend.add_theme_color(backend.mvThemeCol_FrameBgActive, frame)
            backend.add_theme_color(backend.mvThemeCol_SliderGrab, grab)
            backend.add_theme_color(backend.mvThemeCol_SliderGrabActive, grab_active)
            backend.add_theme_color(backend.mvThemeCol_Border, border)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 1)
            backend.add_theme_style(backend.mvStyleVar_GrabRounding, 1)
    return _make_theme(backend, tag, build)


def progress_theme(backend, *, state="normal"):
    state = str(state or "normal").lower()
    if state not in ("normal", "error", "paused", "success"):
        state = "normal"
    tag = "dearuiqt.qt.progress.{}".format(state)
    p = QtFusionPalette
    fill = {
        "normal": p.HIGHLIGHT,
        "error": p.DANGER,
        "paused": p.WARNING,
        "success": p.SUCCESS,
    }[state]

    def build():
        with backend.theme_component(backend.mvProgressBar):
            backend.add_theme_color(backend.mvThemeCol_FrameBg, p.WINDOW_ALT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.TABLE_BORDER)
            backend.add_theme_color(backend.mvThemeCol_PlotHistogram, fill)
            backend.add_theme_color(backend.mvThemeCol_PlotHistogramHovered, fill)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, METRICS.frame_rounding)
    return _make_theme(backend, tag, build)


def transfer_progress_host_theme(backend):
    """Transparent host used to layer a centered percentage over a progress bar."""
    tag = "dearuiqt.qt.transferprogresshost"

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, (0, 0, 0, 0))
            backend.add_theme_color(backend.mvThemeCol_Border, (0, 0, 0, 0))
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def transfer_list_theme(backend):
    """Compact scrolling list host for dense Transfer Center rows."""
    tag = "dearuiqt.qt.transferlist"

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 5)
    return _make_theme(backend, tag, build)


def transfer_progress_text_theme(backend, *, light=False):
    """Readable centered progress text for light and filled portions."""
    tag = "dearuiqt.qt.transferprogresstext.{}".format("light" if light else "dark")
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

    Transfer rows are interactive status records, not heavy cards.  Use a
    single-pixel table border and a subtle radius so multiple rows still read
    like a QListView while matching the rounded Qt/Windows 11 controls.
    """
    tag = "dearuiqt.qt.transferrow"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_Border, p.TABLE_BORDER)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 8, 5)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 5, 3)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 4)
        with backend.theme_component(backend.mvTable):
            backend.add_theme_style(backend.mvStyleVar_CellPadding, 0, 0)
    return _make_theme(backend, tag, build)


def transfer_status_text_theme(backend, *, state="normal"):
    """Semantic text colours for Transfer Center state labels."""
    state = str(state or "normal").lower()
    if state not in ("normal", "muted", "running", "success", "error", "warning"):
        state = "normal"
    tag = "dearuiqt.qt.transferstatus.{}".format(state)
    p = QtFusionPalette
    color = {
        "normal": p.TEXT,
        "muted": p.TEXT_MUTED,
        "running": p.HIGHLIGHT,
        "success": p.SUCCESS,
        "error": p.DANGER,
        "warning": p.WARNING,
    }[state]

    def build():
        with backend.theme_component(backend.mvText):
            backend.add_theme_color(backend.mvThemeCol_Text, color)
    return _make_theme(backend, tag, build)


def group_box_theme(backend):
    tag = "dearuiqt.qt.groupbox"
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
    metrics = metrics_for_backend(backend)
    tag = "dearuiqt.qt.spin.editor.{}.{}{}".format(
        kind, "disabled" if disabled else "normal",
        _metrics_tag(metrics, 'frame_pad_x', 'spin_frame_pad_y'))
    p = QtFusionPalette
    component_name = "mvInputFloat" if kind == "float" else "mvInputInt"
    component = getattr(backend, component_name, None)

    def build():
        if component is None:
            return
        with backend.theme_component(component, enabled_state=not disabled):
            # The shared shell owns the surface and rounded corners. A second
            # opaque rectangular input background bleeds into its inner arc.
            bg = (0, 0, 0, 0)
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
            backend.add_theme_color(backend.mvThemeCol_TextSelectedBg, p.HIGHLIGHT[:3] + (115,))
            backend.add_theme_style(
                backend.mvStyleVar_FramePadding,
                metrics.frame_pad_x,
                metrics.spin_frame_pad_y,
            )
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
            backend.add_theme_color(backend.mvThemeCol_BorderShadow, (0, 0, 0, 0))
    return _make_theme(backend, tag, build)


def spin_shell_theme(backend, *, focused=False, disabled=False):
    """One outer frame shared by the scalar editor and up/down sub-control."""
    state = "disabled" if disabled else ("focus" if focused else "normal")
    metrics = metrics_for_backend(backend)
    tag = "dearuiqt.qt.spin.shell.{}{}".format(
        state, _metrics_tag(metrics, 'border_size', 'frame_rounding'))
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_BorderShadow, (0, 0, 0, 0))
            backend.add_theme_color(
                backend.mvThemeCol_ChildBg,
                p.BUTTON_DISABLED if disabled else p.BASE,
            )
            backend.add_theme_color(
                backend.mvThemeCol_Border,
                p.BORDER_LIGHT if disabled else (p.FOCUS if focused else p.BORDER),
            )
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, metrics.border_size, metrics.border_size)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, metrics.frame_rounding)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, metrics.border_size)
        with backend.theme_component(backend.mvTable):
            backend.add_theme_style(backend.mvStyleVar_CellPadding, 0, 0)
    return _make_theme(backend, tag, build)


def spin_button_theme(backend, *, disabled=False):
    """Qt-style small spin-button sub-control with no independent border."""
    tag = "dearuiqt.qt.spin.button.{}".format("disabled" if disabled else "normal")
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvButton):
            face = p.BUTTON_DISABLED if disabled else p.BUTTON
            backend.add_theme_color(backend.mvThemeCol_Button, face)
            backend.add_theme_color(
                backend.mvThemeCol_ButtonHovered,
                face if disabled else p.WINDOW_ALT,
            )
            backend.add_theme_color(
                backend.mvThemeCol_ButtonActive,
                face if disabled else p.BUTTON_DISABLED,
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
    tag = "dearuiqt.qt.compactstack"

    def build():
        with backend.theme_component(backend.mvAll):
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 0, 0)

    return _make_theme(backend, tag, build)


def aligned_cell_theme(backend):
    """Zero implicit text baseline/padding for mixed-control table cells."""
    tag = "dearuiqt.qt.alignedcell"

    def build():
        with backend.theme_component(backend.mvAll):
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 0, 0)
    return _make_theme(backend, tag, build)

def transparent_header_cell_theme(backend):
    """Transparent table-header host used for centered custom header labels.

    Dear PyGui child windows have their own background by default.  When a
    child is used only as a geometry host inside a table cell, that background
    appears as a grey tile.  Keep the child fully transparent so the table's
    own header/row surface remains visually continuous.
    """
    tag = "dearuiqt.qt.tableheader.transparentcell"

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, (0, 0, 0, 0))
            backend.add_theme_color(backend.mvThemeCol_Border, (0, 0, 0, 0))
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
        with backend.theme_component(backend.mvAll):
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 0, 0)
    return _make_theme(backend, tag, build)

def spin_button_stack_theme(backend):
    """Remove vertical ImGui item spacing between the two spin sub-buttons."""
    tag = "dearuiqt.qt.spin.buttonstack"

    def build():
        with backend.theme_component(backend.mvAll):
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 0, 0)

    return _make_theme(backend, tag, build)


def separator_theme(backend):
    tag = "dearuiqt.qt.separator.vertical"
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
    tag = "dearuiqt.qt.form.labelcell"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.WINDOW)
            backend.add_theme_color(backend.mvThemeCol_Border, p.WINDOW)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, METRICS.form_label_top_pad)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
        with backend.theme_component(backend.mvText):
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 0, 0)

    return _make_theme(backend, tag, build)


def form_row_theme(backend):
    """Compact QFormLayout-like row table with no hidden cell padding.

    DPG tables inherit application-level ``CellPadding``.  A separate table is
    used for each labeled form row, so inherited padding accumulates visually
    and makes dialogs look much looser than Qt/Fusion.  Keep row geometry in
    one reusable theme instead.
    """
    tag = "dearuiqt.qt.formrow"

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
    metrics = metrics_for_backend(backend)
    tag = "dearuiqt.qt.tabs{}".format(
        _metrics_tag(metrics, 'tab_pad_x', 'tab_pad_y', 'border_size'))
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
                backend.add_theme_style(backend.mvStyleVar_FramePadding, metrics.tab_pad_x, metrics.tab_pad_y)
                backend.add_theme_style(backend.mvStyleVar_FrameRounding, 0)
                backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, metrics.border_size)
                for name, value in (("mvStyleVar_TabRounding", 0), ("mvStyleVar_TabBorderSize", 1)):
                    role = getattr(backend, name, None)
                    if role is not None:
                        backend.add_theme_style(role, value)
        tab_bar_component = getattr(backend, "mvTabBar", None)
        if tab_bar_component is not None:
            with backend.theme_component(tab_bar_component):
                backend.add_theme_color(backend.mvThemeCol_Tab, p.BUTTON)
                backend.add_theme_color(backend.mvThemeCol_TabHovered, p.BUTTON_HOVER)
                backend.add_theme_color(backend.mvThemeCol_TabActive, p.BASE)
                backend.add_theme_color(backend.mvThemeCol_Separator, p.BORDER_LIGHT)
                backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
                backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 0, 0)
                for name, value in (("mvStyleVar_TabRounding", 0), ("mvStyleVar_TabBorderSize", 1)):
                    role = getattr(backend, name, None)
                    if role is not None:
                        backend.add_theme_style(role, value)
    return _make_theme(backend, tag, build)


def tool_bar_theme(backend):
    """Compact QToolBar-like surface used by the two Explorer file panes."""
    tag = "dearuiqt.qt.toolbar"
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


def tool_button_theme(backend, *, disabled=False, frame_padding=(4, 3)):
    """Qt/Fusion QToolButton visual contract for image/text toolbar actions.

    ``frame_padding`` is configurable so dense image buttons can keep the same
    outer geometry while fitting their raster icon inside the button instead
    of increasing the button size.
    """
    metrics = metrics_for_backend(backend)
    try:
        pad_x, pad_y = frame_padding
    except Exception:
        pad_x, pad_y = 4, 3
    if (pad_x, pad_y) == (4, 3):
        pad_x, pad_y = metrics.tool_button_pad_x, metrics.tool_button_pad_y
    pad_x, pad_y = max(0, int(pad_x)), max(0, int(pad_y))
    tag = "dearuiqt.qt.toolbutton.{}.pad{}x{}.r{}".format(
        "disabled" if disabled else "normal", pad_x, pad_y, metrics.button_rounding)
    p = QtFusionPalette

    def style(component):
        with backend.theme_component(component, enabled_state=not disabled):
            face = (0, 0, 0, 0)
            hover = face if disabled else p.BUTTON_HOVER
            active = face if disabled else p.BUTTON_ACTIVE
            backend.add_theme_color(backend.mvThemeCol_Button, face)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, hover)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, active)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT_DISABLED if disabled else p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_Border, (0, 0, 0, 0))
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, metrics.button_rounding)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, pad_x, pad_y)

    def build():
        style(backend.mvImageButton)
        style(backend.mvButton)
    return _make_theme(backend, tag, build)


def path_bar_theme(backend):
    """Read-only QLineEdit-like path selector rendered as a clickable button."""
    tag = "dearuiqt.qt.pathbar.rev52"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvButton):
            backend.add_theme_color(backend.mvThemeCol_Button, p.BASE)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, p.WINDOW_ALT)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, p.HIGHLIGHT_HOVER)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.BORDER_LIGHT)
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 1)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, METRICS.frame_rounding)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 7, 2)
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
    tag = "dearuiqt.qt.statusbar.rev52"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.WINDOW_ALT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.TABLE_BORDER)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 6, 2)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 4, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def status_text_theme(backend, *, muted=False):
    tag = "dearuiqt.qt.status.text.{}".format("muted" if muted else "normal")
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
    tag = "dearuiqt.qt.application.rev51"
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
            # Use the exact same scrollbar palette/geometry as QListView and
            # QFileDialog-style item views.  This is deliberately attached to
            # mvAll so generic child windows, popups, editors and floating
            # surfaces no longer fall back to Dear ImGui's stock scrollbar.
            add_dpg_scroller_style(backend, track=p.WINDOW_ALT)
            # Keep application content close to the native client border.
            # WinUx uses absolute/retained child layouts internally, so this
            # controls only the shell-to-content margin, not widget internals.
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 2, 2)
            backend.add_theme_style(backend.mvStyleVar_WindowRounding, QtFusionMetrics.WINDOW_ROUNDING)
            backend.add_theme_style(backend.mvStyleVar_PopupRounding, QtFusionMetrics.POPUP_ROUNDING)
            # Generic/unwrapped controls must use the same 5 px Qt/Win11
            # radius as retained QLineEdit/QComboBox/QPushButton wrappers.
            # Keeping mvAll at 1 px made otherwise identical controls snap
            # back to square corners in mixed legacy/retained layouts.
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, METRICS.frame_rounding)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, METRICS.border_size)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 6, 4)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 5, 4)
        # Dear PyGui keeps separate enabled/disabled theme components. Keep
        # button geometry identical across both states so a control does not
        # snap back to square corners when an action disables itself.
        for enabled_state in (True, False):
            for component in (backend.mvInputText, backend.mvCombo):
                with backend.theme_component(component, enabled_state=enabled_state):
                    backend.add_theme_style(backend.mvStyleVar_FrameRounding, METRICS.frame_rounding)
            with backend.theme_component(backend.mvButton, enabled_state=enabled_state):
                backend.add_theme_style(backend.mvStyleVar_FrameRounding, METRICS.button_rounding)
            image_button = getattr(backend, "mvImageButton", None)
            if image_button is not None:
                with backend.theme_component(image_button, enabled_state=enabled_state):
                    backend.add_theme_style(backend.mvStyleVar_FrameRounding, METRICS.button_rounding)
    return _make_theme(backend, tag, build)


def menu_bar_theme(backend):
    """Qt/Fusion-like QMenuBar/QMenu baseline for application command menus.

    The command rows intentionally use a clearer blue hover/pressed surface,
    darker text and slightly taller padding.  This keeps the menu looking like
    a native Qt command list instead of a set of labels floating on a pale
    popup background.
    """
    tag = "dearuiqt.qt.menubar.rev59"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvAll):
            backend.add_theme_color(backend.mvThemeCol_MenuBarBg, p.TOOLBAR)
            backend.add_theme_color(backend.mvThemeCol_PopupBg, p.MENU)
            backend.add_theme_color(backend.mvThemeCol_WindowBg, p.MENU)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
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
    tag = "dearuiqt.qt.commandbutton." + state
    p = QtFusionPalette

    def style(component):
        with backend.theme_component(component, enabled_state=not disabled):
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
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, METRICS.button_rounding)
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
    tag = "dearuiqt.qt.panel.{}.{}.{}".format(state, density, border_state)
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
    tag = "dearuiqt.qt.panel.header.rev53"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(backend.mvThemeCol_ChildBg, p.TITLE_ACTIVE)
            backend.add_theme_color(backend.mvThemeCol_Border, p.TITLE_BORDER)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 8, 3)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 6, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def dock_frame_theme(backend):
    """One-pixel QDockWidget frame without an ImGui child-window border."""
    tag = "dearuiqt.qt.dock.frame"
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
    # rev60: force a fresh retained resource after the Light/Dark dock-title
    # migration.  Older in-process resources could otherwise keep the light
    # TITLE_ACTIVE surface even after the application palette became Dark.
    tag = "dearuiqt.qt.dock.title.rev60.{}".format("active" if active else "inactive")
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvChildWindow):
            backend.add_theme_color(
                backend.mvThemeCol_ChildBg,
                p.TITLE_ACTIVE if active else p.TITLE,
            )
            backend.add_theme_color(backend.mvThemeCol_Border, p.TITLE_BORDER)
            backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 0)
            backend.add_theme_style(backend.mvStyleVar_ChildRounding, 0)
    return _make_theme(backend, tag, build)


def dock_content_theme(backend):
    """Flush QDockWidget client widget surface."""
    tag = "dearuiqt.qt.dock.content"
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
    tag = "dearuiqt.qt.dock.control.{}.{}".format("close" if close else "tool", state)
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvButton, enabled_state=not disabled):
            normal = (0, 0, 0, 0)
            if disabled:
                hover = active = normal
                text = p.TEXT_DISABLED
            elif close:
                hover = p.DANGER_HOVER
                active = p.DANGER_ACTIVE
                text = p.TEXT
            else:
                hover = p.DOCK_BUTTON_HOVER
                active = p.DOCK_BUTTON_ACTIVE
                text = p.TEXT
            backend.add_theme_color(backend.mvThemeCol_Button, normal)
            backend.add_theme_color(backend.mvThemeCol_ButtonHovered, hover)
            backend.add_theme_color(backend.mvThemeCol_ButtonActive, active)
            backend.add_theme_color(backend.mvThemeCol_Text, text)
            backend.add_theme_color(backend.mvThemeCol_Border, (0, 0, 0, 0))
            backend.add_theme_color(backend.mvThemeCol_NavHighlight, p.FOCUS)
            backend.add_theme_style(backend.mvStyleVar_FrameBorderSize, 0)
            backend.add_theme_style(backend.mvStyleVar_FrameRounding, 4)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 0, 0)
    return _make_theme(backend, tag, build)


def splitter_theme(backend, *, active=False):
    """QSplitter handle: one painted pixel with a larger independent hitbox."""
    tag = "dearuiqt.qt.splitter.{}".format("active" if active else "normal")
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvButton):
            line = p.FOCUS if active else p.TABLE_BORDER
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
    tag = "dearuiqt.qt.splitter.hitbox"

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
    "metrics_for_dpi", "metrics_for_screen", "metrics_for_backend",
    "line_edit_theme", "button_theme", "checkbox_theme", "radio_group_theme", "slider_theme", "progress_theme", "transfer_list_theme", "transfer_row_theme",
    "transfer_status_text_theme", "group_box_theme", "form_row_theme", "form_label_cell_theme", "spin_editor_theme", "spin_shell_theme",
    "spin_button_theme", "spin_button_stack_theme", "compact_stack_theme", "aligned_cell_theme", "transparent_header_cell_theme", "separator_theme", "tab_widget_theme",
    "tool_bar_theme", "tool_button_theme", "path_bar_theme",
    "status_bar_theme", "status_text_theme", "application_theme",
    "menu_bar_theme", "command_button_theme", "panel_surface_theme", "panel_header_theme",
    "dock_frame_theme", "dock_title_theme", "dock_content_theme",
    "dock_control_theme", "splitter_theme", "splitter_hitbox_theme",
    "bind_theme", "QStyle", "QProxyStyle", "QStyleFactory",
]

def plot_surface_theme(backend):
    """Fusion-like light plot palette kept behind DearUIQt's renderer boundary."""
    tag = "dearuiqt.qt.plot.surface"
    p = QtFusionPalette

    def build():
        with backend.theme_component(backend.mvPlot):
            def color(role_name, value):
                role = getattr(backend, role_name, None)
                if role is not None:
                    backend.add_theme_color(role, value, category=backend.mvThemeCat_Plots)

            dark = color_scheme() == "Dark"
            plot_bg = p.BASE if dark else (255, 255, 255, 255)
            color("mvPlotCol_PlotBg", plot_bg)
            color("mvPlotCol_FrameBg", plot_bg)
            legend_bg = tuple(p.MENU[:3]) + (240,) if dark else (255, 255, 255, 240)
            color("mvPlotCol_LegendBg", legend_bg)
            color("mvPlotCol_LegendBorder", p.BORDER if dark else (182, 182, 182, 255))
            plot_text = p.TEXT if dark else (20, 20, 20, 255)
            for role_name in ("mvPlotCol_TitleText", "mvPlotCol_LegendText",
                              "mvPlotCol_InlayText", "mvPlotCol_AxisText"):
                color(role_name, plot_text)
            grid = tuple(p.TABLE_GRID[:3]) + (180,) if dark else (216, 216, 216, 180)
            color("mvPlotCol_AxisGrid", grid)
            # ImPlot draws the axis interaction rectangles over the frame.
            # An opaque AxisBg therefore hides the plot frame along the X/Y
            # title gutters (most visible along the bottom edge).  Keep all
            # axis interaction backgrounds transparent so labels/ticks remain
            # readable without painting a solid panel over the plot border.
            color("mvPlotCol_AxisBg", (0, 0, 0, 0))
            color("mvPlotCol_AxisBgHovered", (0, 0, 0, 0))
            color("mvPlotCol_AxisBgActive", (0, 0, 0, 0))

            # ImPlot's built-in axis menu is rendered while the plot item theme
            # is active, so core ImGui popup metrics applied here affect only
            # plot-owned popups instead of loosening the compact application
            # shell.  WinUx deliberately keeps application WindowPadding at
            # 2 px; without this override the axis checkboxes sit almost on the
            # popup border and the Min/Max editors have no breathing room.
            backend.add_theme_color(
                backend.mvThemeCol_PopupBg, p.MENU if dark else (250, 250, 250, 255))
            backend.add_theme_color(
                backend.mvThemeCol_Border, p.BORDER if dark else (176, 176, 176, 255))
            backend.add_theme_color(
                backend.mvThemeCol_FrameBg, p.BASE if dark else (255, 255, 255, 255))
            backend.add_theme_color(
                backend.mvThemeCol_FrameBgHovered, p.WINDOW_ALT if dark else (248, 250, 252, 255))
            backend.add_theme_color(
                backend.mvThemeCol_FrameBgActive, p.BUTTON_ACTIVE if dark else (244, 248, 252, 255))
            backend.add_theme_color(backend.mvThemeCol_HeaderHovered, p.MENU_HOVER)
            backend.add_theme_color(backend.mvThemeCol_HeaderActive, p.MENU_ACTIVE)
            backend.add_theme_color(backend.mvThemeCol_CheckMark, p.HIGHLIGHT)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 8, 6)
            backend.add_theme_style(backend.mvStyleVar_FramePadding, 5, 3)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 6, 3)
            backend.add_theme_style(backend.mvStyleVar_ItemInnerSpacing, 6, 3)
            backend.add_theme_style(backend.mvStyleVar_PopupRounding, 3)
            backend.add_theme_style(backend.mvStyleVar_WindowBorderSize, 1)
    return _make_theme(backend, tag, build)


class QStyle:
    """Backend-neutral Qt-style policy object.

    DearUIQt's renderer-specific theme factories remain module functions, while
    QStyle owns application/widget policy such as pixel metrics and palette.
    This mirrors Qt's separation between style policy and the platform renderer.
    """

    PM_DefaultFrameWidth = 0
    PM_ButtonMargin = 1
    PM_ScrollBarExtent = 2
    PM_SplitterWidth = 3
    PM_TabBarTabHSpace = 4
    PM_TabBarTabVSpace = 5
    PM_ToolBarItemSpacing = 6
    PM_LayoutHorizontalSpacing = 7
    PM_LayoutVerticalSpacing = 8

    def __init__(self, name="Fusion"):
        self._name = str(name or "Fusion")

    def objectName(self):
        return self._name

    def pixelMetric(self, metric, option=None, widget=None):
        metric = int(metric)
        del option
        metrics = METRICS
        getter = getattr(widget, 'controlMetrics', None) if widget is not None else None
        if callable(getter):
            try:
                metrics = getter()
            except Exception:
                metrics = METRICS
        scale = metrics.control_height / max(1.0, float(METRICS.control_height))
        scaled = lambda value: max(1, int(round(float(value) * scale)))
        values = {
            self.PM_DefaultFrameWidth: int(metrics.border_size),
            self.PM_ButtonMargin: int(metrics.frame_pad_x),
            self.PM_ScrollBarExtent: scaled(14),
            self.PM_SplitterWidth: int(metrics.splitter_handle_width),
            self.PM_TabBarTabHSpace: scaled(QtFusionMetrics.ITEM_SPACING_X),
            self.PM_TabBarTabVSpace: scaled(QtFusionMetrics.ITEM_SPACING_Y),
            self.PM_ToolBarItemSpacing: scaled(QtFusionMetrics.ITEM_SPACING_X),
            self.PM_LayoutHorizontalSpacing: scaled(QtFusionMetrics.ITEM_SPACING_X),
            self.PM_LayoutVerticalSpacing: scaled(QtFusionMetrics.ITEM_SPACING_Y),
        }
        return int(values.get(metric, 0))

    def standardPalette(self):
        from .palette import QPalette
        return QPalette.fusion()

    def polish(self, target):
        return target

    def unpolish(self, target):
        return target


class QProxyStyle(QStyle):
    """Style wrapper that delegates policy to another QStyle."""

    def __init__(self, base_style=None):
        if isinstance(base_style, str) or base_style is None:
            base_style = QStyleFactory.create(base_style or "Fusion")
        if not isinstance(base_style, QStyle):
            raise TypeError("base_style must be QStyle or a registered style name")
        self._base_style = base_style
        super().__init__("Proxy({})".format(base_style.objectName()))

    def baseStyle(self):
        return self._base_style

    def setBaseStyle(self, style):
        if not isinstance(style, QStyle):
            raise TypeError("style must be QStyle")
        self._base_style = style

    def pixelMetric(self, metric, option=None, widget=None):
        return self._base_style.pixelMetric(metric, option, widget)

    def standardPalette(self):
        return self._base_style.standardPalette()


class QStyleFactory:
    """Small style registry matching Qt's QStyleFactory surface."""

    _registry = {"fusion": lambda: QStyle("Fusion")}

    @classmethod
    def keys(cls):
        return ["Fusion"]

    @classmethod
    def registerStyle(cls, name, factory):
        key = str(name or "").strip().lower()
        if not key or not callable(factory):
            raise ValueError("style registration requires a name and callable factory")
        cls._registry[key] = factory

    @classmethod
    def create(cls, name):
        key = str(name or "Fusion").strip().lower()
        factory = cls._registry.get(key)
        if factory is None:
            return None
        style = factory()
        if not isinstance(style, QStyle):
            raise TypeError("style factory must return QStyle")
        return style
