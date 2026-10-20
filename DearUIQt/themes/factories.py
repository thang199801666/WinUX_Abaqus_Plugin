"""Backend-resolving public theme factories.

``DearUIQt.gui.style`` contains renderer implementation details and therefore
accepts an explicit renderer.  Applications import factories from
``DearUIQt.themes`` instead: the active backend is resolved here, while tests
may still inject one explicitly.
"""
from __future__ import annotations

from ..backends import get_backend
from ..gui import style as _style
from ..gui.palette import QtFusionMetrics, QtFusionPalette
from .spec import (
    ThemeColor, ThemeStyle, ThemeTarget, make_theme, theme_component, with_scrollbar,
)


def _backend(value):
    return value if value is not None else get_backend()


def application_theme(backend=None):
    return _style.application_theme(_backend(backend))


def fusion_desktop_theme(backend=None, *, background=None,
                         tag="dearuiqt.theme.fusion.desktop", cache=True):
    """Full Fusion desktop baseline for retained application shells.

    Unlike :func:`application_theme`, this factory is expressed entirely with
    DearUIQt theme roles and includes scrollbar/tool-button/checkbox states.
    It is intended for applications migrating a renderer-global style without
    exposing ``mvThemeCol_*`` / ``mvStyleVar_*`` symbols in feature code.
    """
    p = QtFusionPalette
    m = QtFusionMetrics
    base = p.BASE if background is None else background
    clear = (0, 0, 0, 0)
    all_component = theme_component(
        ThemeTarget.ALL,
        colors={
            ThemeColor.WINDOW_BACKGROUND: base,
            ThemeColor.CHILD_BACKGROUND: base,
            ThemeColor.POPUP_BACKGROUND: p.MENU,
            ThemeColor.TEXT: p.TEXT,
            ThemeColor.TEXT_DISABLED: p.TEXT_DISABLED,
            ThemeColor.TEXT_SELECTED_BACKGROUND: (0, 120, 215, 105),
            ThemeColor.BORDER: p.BORDER_LIGHT,
            ThemeColor.BORDER_SHADOW: clear,
            ThemeColor.FRAME_BACKGROUND: base,
            ThemeColor.FRAME_BACKGROUND_HOVERED: base,
            ThemeColor.FRAME_BACKGROUND_ACTIVE: base,
            ThemeColor.BUTTON: p.BUTTON,
            ThemeColor.BUTTON_HOVERED: p.BUTTON_HOVER,
            ThemeColor.BUTTON_ACTIVE: p.BUTTON_ACTIVE,
            ThemeColor.HEADER: p.HIGHLIGHT_SOFT,
            ThemeColor.HEADER_HOVERED: p.HIGHLIGHT_HOVER,
            ThemeColor.HEADER_ACTIVE: p.HIGHLIGHT_SOFT,
            ThemeColor.CHECK_MARK: p.HIGHLIGHT,
            ThemeColor.TITLE_BACKGROUND: p.TITLE,
            ThemeColor.TITLE_BACKGROUND_ACTIVE: p.TITLE_ACTIVE,
            ThemeColor.TITLE_BACKGROUND_COLLAPSED: p.TITLE,
            ThemeColor.SEPARATOR: p.BORDER_LIGHT,
            ThemeColor.SEPARATOR_HOVERED: p.HIGHLIGHT,
            ThemeColor.SEPARATOR_ACTIVE: p.HIGHLIGHT,
        },
        styles={
            ThemeStyle.FRAME_ROUNDING: m.FRAME_ROUNDING,
            ThemeStyle.GRAB_ROUNDING: m.GRAB_ROUNDING,
            ThemeStyle.WINDOW_BORDER_SIZE: 1,
            ThemeStyle.FRAME_BORDER_SIZE: 1,
        },
    )
    for role, value in (
        (ThemeColor.MENU_BAR_BACKGROUND, p.TOOLBAR),
        (ThemeColor.TAB, p.BUTTON),
        (ThemeColor.TAB_HOVERED, p.BUTTON_HOVER),
        (ThemeColor.TAB_ACTIVE, base),
        (ThemeColor.RESIZE_GRIP, clear),
        (ThemeColor.RESIZE_GRIP_HOVERED, clear),
        (ThemeColor.RESIZE_GRIP_ACTIVE, clear),
    ):
        all_component = all_component.with_color(role, value, optional=True)
    all_component = with_scrollbar(all_component)
    button_component = theme_component(
        ThemeTarget.PUSH_BUTTON,
        enabled_state=True,
        colors={ThemeColor.TEXT: p.TEXT, ThemeColor.BORDER: p.BORDER},
        styles={
            ThemeStyle.FRAME_ROUNDING: m.BUTTON_ROUNDING,
            ThemeStyle.FRAME_BORDER_SIZE: 1,
            ThemeStyle.FRAME_PADDING: (6, 3),
        },
    )
    disabled_button_component = theme_component(
        ThemeTarget.PUSH_BUTTON,
        enabled_state=False,
        colors={
            ThemeColor.TEXT: p.TEXT_DISABLED,
            ThemeColor.TEXT_DISABLED: p.TEXT_DISABLED,
            ThemeColor.BORDER: p.BORDER_LIGHT,
        },
        styles={
            ThemeStyle.FRAME_ROUNDING: m.BUTTON_ROUNDING,
            ThemeStyle.FRAME_BORDER_SIZE: 1,
            ThemeStyle.FRAME_PADDING: (6, 3),
        },
    )
    image_component = theme_component(
        ThemeTarget.IMAGE_BUTTON,
        enabled_state=True,
        colors={
            ThemeColor.BUTTON: clear,
            ThemeColor.BUTTON_HOVERED: p.BUTTON_HOVER,
            ThemeColor.BUTTON_ACTIVE: p.BUTTON_ACTIVE,
            ThemeColor.BORDER: clear,
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 0,
            ThemeStyle.FRAME_ROUNDING: m.BUTTON_ROUNDING,
        },
    )
    disabled_image_component = theme_component(
        ThemeTarget.IMAGE_BUTTON,
        enabled_state=False,
        colors={
            ThemeColor.BUTTON: clear,
            ThemeColor.BUTTON_HOVERED: clear,
            ThemeColor.BUTTON_ACTIVE: clear,
            ThemeColor.BORDER: clear,
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 0,
            ThemeStyle.FRAME_ROUNDING: m.BUTTON_ROUNDING,
        },
    )
    checkbox_component = theme_component(
        ThemeTarget.CHECK_BOX,
        colors={
            ThemeColor.FRAME_BACKGROUND: base,
            ThemeColor.FRAME_BACKGROUND_HOVERED: p.HIGHLIGHT_HOVER,
            ThemeColor.FRAME_BACKGROUND_ACTIVE: p.HIGHLIGHT_SOFT,
            ThemeColor.BORDER: p.BORDER_DARK,
            ThemeColor.CHECK_MARK: p.HIGHLIGHT,
        },
        styles={
            ThemeStyle.FRAME_PADDING: (1, 1),
            ThemeStyle.FRAME_BORDER_SIZE: 1,
            ThemeStyle.FRAME_ROUNDING: 1,
        },
    )
    return make_theme(
        all_component, button_component, disabled_button_component,
        image_component, disabled_image_component, checkbox_component,
        backend=_backend(backend), tag=tag, cache=cache)


def button_theme(backend=None, *, role="secondary", disabled=False, focused=False, default=False, checked=False):
    return _style.button_theme(_backend(backend), role=role, disabled=disabled, focused=focused, default=default, checked=checked)


def splitter_theme(backend=None, *, active=False):
    return _style.splitter_theme(_backend(backend), active=active)


def splitter_hitbox_theme(backend=None):
    return _style.splitter_hitbox_theme(_backend(backend))


def panel_surface_theme(backend=None, *, bordered=True, compact=False, alternate=False):
    return _style.panel_surface_theme(_backend(backend), bordered=bordered, compact=compact, alternate=alternate)


def plot_surface_theme(backend=None):
    return _style.plot_surface_theme(_backend(backend))


def panel_header_theme(backend=None):
    return _style.panel_header_theme(_backend(backend))


def status_text_theme(backend=None, *, muted=False):
    return _style.status_text_theme(_backend(backend), muted=muted)


def text_theme(backend=None, *, color=None, tag=None, cache=False):
    """Create a simple text-color theme without exposing renderer symbols."""
    if color is None:
        color = QtFusionPalette.TEXT
    return make_theme(theme_component(
        ThemeTarget.TEXT, colors={ThemeColor.TEXT: color}),
        backend=_backend(backend), tag=tag, cache=cache)


def tool_bar_theme(backend=None):
    return _style.tool_bar_theme(_backend(backend))


def tool_button_theme(backend=None, *, disabled=False, frame_padding=(4, 3)):
    return _style.tool_button_theme(_backend(backend), disabled=disabled, frame_padding=frame_padding)


def path_bar_theme(backend=None):
    return _style.path_bar_theme(_backend(backend))


def status_bar_theme(backend=None):
    return _style.status_bar_theme(_backend(backend))


def menu_bar_theme(backend=None):
    return _style.menu_bar_theme(_backend(backend))


def command_button_theme(backend=None, *, checked=False, disabled=False):
    return _style.command_button_theme(_backend(backend), checked=checked, disabled=disabled)


def compact_stack_theme(backend=None):
    return _style.compact_stack_theme(_backend(backend))


def aligned_cell_theme(backend=None):
    return _style.aligned_cell_theme(_backend(backend))


def transparent_header_cell_theme(backend=None):
    return _style.transparent_header_cell_theme(_backend(backend))


def transfer_list_theme(backend=None):
    return _style.transfer_list_theme(_backend(backend))


def transfer_row_theme(backend=None):
    return _style.transfer_row_theme(_backend(backend))


def form_row_theme(backend=None):
    return _style.form_row_theme(_backend(backend))


def transfer_progress_host_theme(backend=None):
    return _style.transfer_progress_host_theme(_backend(backend))


def transfer_progress_text_theme(backend=None, *, light=False):
    return _style.transfer_progress_text_theme(_backend(backend), light=light)


def progress_theme(backend=None, *, state="normal"):
    return _style.progress_theme(_backend(backend), state=state)


def transfer_status_text_theme(backend=None, *, state="normal"):
    return _style.transfer_status_text_theme(_backend(backend), state=state)


def menu_surface_theme(backend=None, *, padding=(4, 3), spacing=(0, 0),
                       tag="dearuiqt.theme.menu.surface", cache=True):
    """Return the shared Qt/Fusion popup-menu surface theme.

    Applications should use this factory rather than renderer constants.  The
    result is cached by tag by default so QMenu and custom menu-like surfaces
    share one native theme allocation.
    """
    p = QtFusionPalette
    m = QtFusionMetrics
    return make_theme(theme_component(
        ThemeTarget.ALL,
        colors={
            ThemeColor.WINDOW_BACKGROUND: p.MENU,
            ThemeColor.CHILD_BACKGROUND: p.MENU,
            ThemeColor.POPUP_BACKGROUND: p.MENU,
            ThemeColor.TEXT: p.TEXT,
            ThemeColor.TEXT_DISABLED: p.TEXT_DISABLED,
            ThemeColor.SEPARATOR: p.BORDER_LIGHT,
            ThemeColor.BORDER: p.BORDER,
        },
        styles={
            ThemeStyle.WINDOW_PADDING: padding,
            ThemeStyle.ITEM_SPACING: spacing,
            ThemeStyle.WINDOW_ROUNDING: m.POPUP_ROUNDING,
            ThemeStyle.POPUP_ROUNDING: m.POPUP_ROUNDING,
            ThemeStyle.WINDOW_BORDER_SIZE: 1,
        },
    ), backend=_backend(backend), tag=tag, cache=cache)


def menu_button_theme(backend=None, *, disabled=False, keyboard=False,
                      align=(0.0, 0.5), frame_padding=(8, 4),
                      tag=None, cache=True):
    """Qt/Fusion menu command button theme used by custom retained menus."""
    p = QtFusionPalette
    clear = (0, 0, 0, 0)
    disabled = bool(disabled)
    keyboard = bool(keyboard) and not disabled
    colors = {
        ThemeColor.BUTTON: p.MENU_HOVER if keyboard else clear,
        ThemeColor.BUTTON_HOVERED: clear if disabled else p.MENU_HOVER,
        ThemeColor.BUTTON_ACTIVE: clear if disabled else p.MENU_ACTIVE,
        ThemeColor.TEXT: p.TEXT_DISABLED if disabled else p.TEXT,
        ThemeColor.BORDER: p.FOCUS if keyboard else clear,
    }
    if disabled:
        colors[ThemeColor.TEXT_DISABLED] = p.TEXT_DISABLED
    if tag is None and cache:
        tag = "dearuiqt.theme.menu.button.{}.{}.{}.{}".format(
            "disabled" if disabled else "enabled",
            "keyboard" if keyboard else "normal",
            str(tuple(frame_padding)).replace(" ", ""),
            str(tuple(align)).replace(" ", ""),
        )
    return make_theme(theme_component(
        ThemeTarget.PUSH_BUTTON,
        colors=colors,
        styles={
            ThemeStyle.FRAME_PADDING: frame_padding,
            ThemeStyle.FRAME_ROUNDING: 0,
            ThemeStyle.FRAME_BORDER_SIZE: 1 if keyboard else 0,
            ThemeStyle.BUTTON_TEXT_ALIGN: align,
        },
    ), backend=_backend(backend), tag=tag, cache=cache)


def menu_image_button_theme(backend=None, *, disabled=False, frame_padding=(6, 6),
                            tag=None, cache=True):
    """Qt/Fusion icon-button theme for menu rows."""
    p = QtFusionPalette
    clear = (0, 0, 0, 0)
    disabled = bool(disabled)
    if tag is None and cache:
        tag = "dearuiqt.theme.menu.image_button.{}.{}.{}".format(
            "disabled" if disabled else "enabled", frame_padding[0], frame_padding[1])
    component = theme_component(
        ThemeTarget.IMAGE_BUTTON,
        colors={
            ThemeColor.BUTTON: clear,
            ThemeColor.BUTTON_HOVERED: clear if disabled else p.MENU_HOVER,
            ThemeColor.BUTTON_ACTIVE: clear if disabled else p.MENU_ACTIVE,
            ThemeColor.BORDER: clear,
        },
        styles={
            ThemeStyle.FRAME_PADDING: frame_padding,
            ThemeStyle.FRAME_ROUNDING: 0,
            ThemeStyle.FRAME_BORDER_SIZE: 0,
        },
    )
    if disabled:
        component = component.with_style(ThemeStyle.ALPHA, 0.38)
    return make_theme(component, backend=_backend(backend), tag=tag, cache=cache)





def inline_editor_theme_spec(*, text_color=None, selection_color=None, border=None):
    """Return a square, Explorer-like inline text editor ThemeSpec."""
    from .spec import theme
    p = QtFusionPalette
    text_color = p.TEXT if text_color is None else text_color
    selection_color = p.HIGHLIGHT if selection_color is None else selection_color
    border = (72, 72, 72, 255) if border is None else border
    white = (255, 255, 255, 255)
    all_component = theme_component(
        ThemeTarget.ALL,
        colors={
            ThemeColor.WINDOW_BACKGROUND: white,
            ThemeColor.CHILD_BACKGROUND: white,
            ThemeColor.FRAME_BACKGROUND: white,
            ThemeColor.FRAME_BACKGROUND_HOVERED: white,
            ThemeColor.FRAME_BACKGROUND_ACTIVE: white,
            ThemeColor.TEXT: text_color,
            ThemeColor.TEXT_SELECTED_BACKGROUND: selection_color,
            ThemeColor.BORDER: border,
        },
        styles={
            ThemeStyle.WINDOW_PADDING: (0, 0),
            ThemeStyle.WINDOW_ROUNDING: 0,
            ThemeStyle.WINDOW_BORDER_SIZE: 1,
            ThemeStyle.FRAME_PADDING: (1, 1),
            ThemeStyle.FRAME_ROUNDING: 0,
            ThemeStyle.FRAME_BORDER_SIZE: 0,
            ThemeStyle.ITEM_SPACING: (0, 0),
        },
    )
    input_component = theme_component(
        ThemeTarget.LINE_EDIT,
        colors={
            ThemeColor.FRAME_BACKGROUND: white,
            ThemeColor.FRAME_BACKGROUND_HOVERED: white,
            ThemeColor.FRAME_BACKGROUND_ACTIVE: white,
            ThemeColor.TEXT: text_color,
            ThemeColor.TEXT_SELECTED_BACKGROUND: selection_color,
        },
        styles={
            ThemeStyle.FRAME_BORDER_SIZE: 0,
            ThemeStyle.FRAME_ROUNDING: 0,
        },
        optional=True,
    )
    return theme(all_component, input_component)

def worksheet_theme_spec(*, header_background=None, transparent_editor=True):
    """Declarative compact spreadsheet/table theme.

    The returned :class:`ThemeSpec` is intentionally not materialized so the
    caller can own it as a :class:`QTheme` through ``createObject()``.  This
    keeps worksheet/table styling renderer-neutral and lifetime-safe.
    """
    from .spec import theme
    p = QtFusionPalette
    header = p.TOOLBAR if header_background is None else header_background
    clear = (255, 255, 255, 0) if transparent_editor else p.BASE
    table_component = theme_component(
        ThemeTarget.TABLE,
        colors={
            ThemeColor.TABLE_HEADER_BACKGROUND: header,
            ThemeColor.TABLE_BORDER_LIGHT: p.BORDER_LIGHT,
            ThemeColor.TABLE_BORDER_STRONG: p.BORDER,
        },
        styles={ThemeStyle.CELL_PADDING: (3, 1)},
    )
    editor_component = theme_component(
        ThemeTarget.LINE_EDIT,
        colors={
            ThemeColor.FRAME_BACKGROUND: clear,
            ThemeColor.FRAME_BACKGROUND_HOVERED: p.HIGHLIGHT_HOVER,
            ThemeColor.FRAME_BACKGROUND_ACTIVE: p.BASE,
        },
        styles={
            ThemeStyle.FRAME_PADDING: (4, 2),
            ThemeStyle.FRAME_BORDER_SIZE: 0,
            ThemeStyle.FRAME_ROUNDING: 0,
        },
    )
    return theme(table_component, editor_component)

def compact_layout_surface_theme(backend=None, *, padding=(0, 0), spacing=(0, 0),
                                 inner_spacing=(0, 0), cell_padding=(0, 0),
                                 child_border=0, tag=None, cache=False):
    """Create a zero/compact-spacing layout surface without renderer symbols.

    This is intended for application shell layouts where the native renderer's
    default padding would otherwise create seams between retained child panels.
    """
    return make_theme(theme_component(
        ThemeTarget.ALL,
        styles={
            ThemeStyle.WINDOW_PADDING: padding,
            ThemeStyle.ITEM_SPACING: spacing,
            ThemeStyle.ITEM_INNER_SPACING: inner_spacing,
            ThemeStyle.CHILD_BORDER_SIZE: child_border,
            ThemeStyle.CELL_PADDING: cell_padding,
        },
    ), backend=_backend(backend), tag=tag, cache=cache)


def floating_window_theme(backend=None, *, transparent_resize_grip=True,
                          padding=(0, 0), rounding=1, border_size=1,
                          title_align=(0.0, 0.5), tag=None, cache=False):
    """Qt/Fusion top-level/floating window chrome.

    The optional title alignment is ignored by older renderers that do not
    expose the corresponding style variable.  Applications therefore never
    need a renderer-version feature probe.
    """
    p = QtFusionPalette
    clear = (0, 0, 0, 0)
    colors = {
        ThemeColor.BORDER: p.BORDER,
        ThemeColor.WINDOW_BACKGROUND: p.WINDOW,
        ThemeColor.TITLE_BACKGROUND: p.TITLE,
        ThemeColor.TITLE_BACKGROUND_ACTIVE: p.TITLE_ACTIVE,
        ThemeColor.TITLE_BACKGROUND_COLLAPSED: p.TITLE,
        ThemeColor.TEXT: p.TEXT,
    }
    if transparent_resize_grip:
        colors.update({
            ThemeColor.RESIZE_GRIP: clear,
            ThemeColor.RESIZE_GRIP_HOVERED: clear,
            ThemeColor.RESIZE_GRIP_ACTIVE: clear,
        })
    component = theme_component(
        ThemeTarget.ALL, colors=colors,
        styles={
            ThemeStyle.WINDOW_ROUNDING: rounding,
            ThemeStyle.WINDOW_BORDER_SIZE: border_size,
            ThemeStyle.WINDOW_PADDING: padding,
        },
    ).with_style(ThemeStyle.WINDOW_TITLE_ALIGN, *title_align, optional=True)
    return make_theme(component, backend=_backend(backend), tag=tag, cache=cache)

def viewport_surface_theme(backend=None, *, background, text=None, border=None,
                           padding=(0, 0), spacing=(0, 0), scrollbar=True,
                           tag=None, cache=False):
    """Generic retained viewport/child surface without renderer constants."""
    colors = {ThemeColor.CHILD_BACKGROUND: background,
              ThemeColor.WINDOW_BACKGROUND: background}
    if text is not None:
        colors[ThemeColor.TEXT] = text
    if border is not None:
        colors[ThemeColor.BORDER] = border
    component = theme_component(
        ThemeTarget.ALL, colors=colors,
        styles={ThemeStyle.WINDOW_PADDING: padding, ThemeStyle.ITEM_SPACING: spacing},
    )
    if scrollbar:
        component = with_scrollbar(component)
    return make_theme(component, backend=_backend(backend), tag=tag, cache=cache)


__all__ = [
    "application_theme", "fusion_desktop_theme", "button_theme", "splitter_theme", "splitter_hitbox_theme",
    "panel_surface_theme", "panel_header_theme", "status_text_theme", "tool_bar_theme",
    "tool_button_theme", "path_bar_theme", "status_bar_theme", "menu_bar_theme",
    "command_button_theme", "compact_stack_theme", "aligned_cell_theme",
    "transparent_header_cell_theme", "transfer_list_theme", "transfer_row_theme",
    "form_row_theme", "transfer_progress_host_theme", "transfer_progress_text_theme",
    "progress_theme", "transfer_status_text_theme",
    "menu_surface_theme", "menu_button_theme", "menu_image_button_theme",
    "viewport_surface_theme", "compact_layout_surface_theme", "floating_window_theme",
]
