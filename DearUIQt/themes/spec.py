"""Declarative, renderer-neutral theme specifications.

Consuming applications should describe visual roles using these DearUIQt enums
instead of importing renderer constants such as ``mvThemeCol_*`` or
``mvStyleVar_*``.  The renderer mapping lives here at the framework boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Tuple

from ..backends import get_backend


class ThemeTarget(Enum):
    ALL = "mvAll"
    CHILD_WINDOW = "mvChildWindow"
    WINDOW = "mvWindowAppItem"
    TABLE = "mvTable"
    PUSH_BUTTON = "mvButton"
    IMAGE_BUTTON = "mvImageButton"
    SELECTABLE = "mvSelectable"
    TEXT = "mvText"
    LINE_EDIT = "mvInputText"
    COMBO_BOX = "mvCombo"
    SEPARATOR = "mvSeparator"
    CHECK_BOX = "mvCheckbox"
    RADIO_BUTTON = "mvRadioButton"
    SLIDER = "mvSliderInt"
    PROGRESS_BAR = "mvProgressBar"


class ThemeColor(Enum):
    WINDOW_BACKGROUND = "mvThemeCol_WindowBg"
    POPUP_BACKGROUND = "mvThemeCol_PopupBg"
    CHILD_BACKGROUND = "mvThemeCol_ChildBg"
    BORDER = "mvThemeCol_Border"
    BORDER_SHADOW = "mvThemeCol_BorderShadow"
    TEXT = "mvThemeCol_Text"
    TEXT_DISABLED = "mvThemeCol_TextDisabled"
    TEXT_SELECTED_BACKGROUND = "mvThemeCol_TextSelectedBg"
    FRAME_BACKGROUND = "mvThemeCol_FrameBg"
    FRAME_BACKGROUND_HOVERED = "mvThemeCol_FrameBgHovered"
    FRAME_BACKGROUND_ACTIVE = "mvThemeCol_FrameBgActive"
    BUTTON = "mvThemeCol_Button"
    BUTTON_HOVERED = "mvThemeCol_ButtonHovered"
    BUTTON_ACTIVE = "mvThemeCol_ButtonActive"
    HEADER = "mvThemeCol_Header"
    HEADER_HOVERED = "mvThemeCol_HeaderHovered"
    HEADER_ACTIVE = "mvThemeCol_HeaderActive"
    NAV_HIGHLIGHT = "mvThemeCol_NavHighlight"
    TABLE_HEADER_BACKGROUND = "mvThemeCol_TableHeaderBg"
    TABLE_BORDER_STRONG = "mvThemeCol_TableBorderStrong"
    TABLE_BORDER_LIGHT = "mvThemeCol_TableBorderLight"
    TABLE_ROW_BACKGROUND = "mvThemeCol_TableRowBg"
    TABLE_ROW_BACKGROUND_ALT = "mvThemeCol_TableRowBgAlt"
    SEPARATOR = "mvThemeCol_Separator"
    SEPARATOR_HOVERED = "mvThemeCol_SeparatorHovered"
    SEPARATOR_ACTIVE = "mvThemeCol_SeparatorActive"
    SCROLLBAR_BACKGROUND = "mvThemeCol_ScrollbarBg"
    SCROLLBAR_GRAB = "mvThemeCol_ScrollbarGrab"
    SCROLLBAR_GRAB_HOVERED = "mvThemeCol_ScrollbarGrabHovered"
    SCROLLBAR_GRAB_ACTIVE = "mvThemeCol_ScrollbarGrabActive"
    CHECK_MARK = "mvThemeCol_CheckMark"
    SLIDER_GRAB = "mvThemeCol_SliderGrab"
    SLIDER_GRAB_ACTIVE = "mvThemeCol_SliderGrabActive"
    PLOT_HISTOGRAM = "mvThemeCol_PlotHistogram"
    PLOT_HISTOGRAM_HOVERED = "mvThemeCol_PlotHistogramHovered"
    INPUT_TEXT_CURSOR = "mvThemeCol_InputTextCursor"
    RESIZE_GRIP = "mvThemeCol_ResizeGrip"
    RESIZE_GRIP_HOVERED = "mvThemeCol_ResizeGripHovered"
    RESIZE_GRIP_ACTIVE = "mvThemeCol_ResizeGripActive"
    TITLE_BACKGROUND = "mvThemeCol_TitleBg"
    TITLE_BACKGROUND_ACTIVE = "mvThemeCol_TitleBgActive"
    TITLE_BACKGROUND_COLLAPSED = "mvThemeCol_TitleBgCollapsed"
    MENU_BAR_BACKGROUND = "mvThemeCol_MenuBarBg"
    TAB = "mvThemeCol_Tab"
    TAB_HOVERED = "mvThemeCol_TabHovered"
    TAB_ACTIVE = "mvThemeCol_TabActive"


class ThemeStyle(Enum):
    WINDOW_PADDING = "mvStyleVar_WindowPadding"
    WINDOW_ROUNDING = "mvStyleVar_WindowRounding"
    POPUP_ROUNDING = "mvStyleVar_PopupRounding"
    ALPHA = "mvStyleVar_Alpha"
    WINDOW_BORDER_SIZE = "mvStyleVar_WindowBorderSize"
    ITEM_SPACING = "mvStyleVar_ItemSpacing"
    ITEM_INNER_SPACING = "mvStyleVar_ItemInnerSpacing"
    CHILD_BORDER_SIZE = "mvStyleVar_ChildBorderSize"
    CHILD_ROUNDING = "mvStyleVar_ChildRounding"
    CELL_PADDING = "mvStyleVar_CellPadding"
    FRAME_PADDING = "mvStyleVar_FramePadding"
    FRAME_BORDER_SIZE = "mvStyleVar_FrameBorderSize"
    FRAME_ROUNDING = "mvStyleVar_FrameRounding"
    BUTTON_TEXT_ALIGN = "mvStyleVar_ButtonTextAlign"
    SELECTABLE_TEXT_ALIGN = "mvStyleVar_SelectableTextAlign"
    SCROLLBAR_SIZE = "mvStyleVar_ScrollbarSize"
    SCROLLBAR_ROUNDING = "mvStyleVar_ScrollbarRounding"
    GRAB_ROUNDING = "mvStyleVar_GrabRounding"
    WINDOW_TITLE_ALIGN = "mvStyleVar_WindowTitleAlign"


@dataclass(frozen=True)
class ThemeValue:
    role: Enum
    value: Tuple[Any, ...]
    optional: bool = False


@dataclass(frozen=True)
class ThemeComponentSpec:
    target: ThemeTarget
    colors: Tuple[ThemeValue, ...] = ()
    styles: Tuple[ThemeValue, ...] = ()
    enabled_state: Optional[bool] = None
    optional: bool = False

    def with_color(self, role: ThemeColor, value: Any, *, optional: bool = False):
        return replace(self, colors=self.colors + (ThemeValue(role, (value,), optional),))

    def with_style(self, role: ThemeStyle, *values: Any, optional: bool = False):
        return replace(self, styles=self.styles + (ThemeValue(role, tuple(values), optional),))


@dataclass(frozen=True)
class ThemeSpec:
    components: Tuple[ThemeComponentSpec, ...]
    tag: Optional[str] = None
    cache: bool = False

    def create(self, *, backend=None):
        return create_theme(self, backend=backend)

    def createObject(self, *, backend=None, parent=None, after=None):
        """Materialize this specification as an owned :class:`QTheme`."""
        from .resource import QTheme
        return QTheme(self, backend=backend, parent=parent, after=after)


def _coerce_values(mapping: Optional[Mapping[Enum, Any]], *, style: bool) -> Tuple[ThemeValue, ...]:
    if not mapping:
        return ()
    values = []
    for role, value in mapping.items():
        if style:
            args = tuple(value) if isinstance(value, (tuple, list)) else (value,)
        else:
            args = (value,)
        values.append(ThemeValue(role, args))
    return tuple(values)


def component(
    target: ThemeTarget,
    *,
    colors: Optional[Mapping[ThemeColor, Any]] = None,
    styles: Optional[Mapping[ThemeStyle, Any]] = None,
    enabled_state: Optional[bool] = None,
    optional: bool = False,
) -> ThemeComponentSpec:
    """Create one declarative theme component.

    ``colors`` values are passed as a single renderer color value. ``styles``
    values may be scalars or tuples/lists and are expanded as renderer style
    arguments.  Optional renderer symbols can be added later with
    :meth:`ThemeComponentSpec.with_color` / ``with_style``.
    """
    if not isinstance(target, ThemeTarget):
        raise TypeError("target must be a ThemeTarget")
    return ThemeComponentSpec(
        target=target,
        colors=_coerce_values(colors, style=False),
        styles=_coerce_values(styles, style=True),
        enabled_state=enabled_state,
        optional=bool(optional),
    )


def theme(*components: ThemeComponentSpec, tag: Optional[str] = None, cache: bool = False) -> ThemeSpec:
    if not components:
        raise ValueError("a theme requires at least one component")
    if not all(isinstance(item, ThemeComponentSpec) for item in components):
        raise TypeError("theme components must be ThemeComponentSpec instances")
    return ThemeSpec(tuple(components), tag=tag, cache=bool(cache))


def _symbol(backend, role: Enum, *, optional: bool = False):
    name = role.value
    value = getattr(backend, name, None)
    if value is None and not optional:
        raise AttributeError("renderer does not provide theme symbol {!r}".format(name))
    return value


def _theme_exists(backend, tag) -> bool:
    if not tag:
        return False
    try:
        return bool(backend.does_item_exist(tag))
    except Exception:
        return False


def create_theme(spec: ThemeSpec, *, backend=None):
    """Materialize ``spec`` using the active renderer and return its theme id."""
    if not isinstance(spec, ThemeSpec):
        raise TypeError("spec must be a ThemeSpec")
    backend = backend or get_backend()
    if spec.cache and spec.tag and _theme_exists(backend, spec.tag):
        return spec.tag

    theme_kwargs = {"tag": spec.tag} if spec.tag is not None else {}
    with backend.theme(**theme_kwargs) as theme_id:
        for item in spec.components:
            target = _symbol(backend, item.target, optional=item.optional)
            if target is None:
                continue
            kwargs = {}
            if item.enabled_state is not None:
                kwargs["enabled_state"] = bool(item.enabled_state)
            with backend.theme_component(target, **kwargs):
                for entry in item.colors:
                    role = _symbol(backend, entry.role, optional=entry.optional)
                    if role is not None:
                        backend.add_theme_color(role, entry.value[0])
                for entry in item.styles:
                    role = _symbol(backend, entry.role, optional=entry.optional)
                    if role is not None:
                        backend.add_theme_style(role, *entry.value)
    return theme_id



def with_scrollbar(component_spec: ThemeComponentSpec, *, track=None) -> ThemeComponentSpec:
    """Add DearUIQt's shared scrollbar palette/metrics to a component spec.

    The consuming application stays renderer-neutral; renderer-specific symbol
    translation still happens only when the ThemeSpec is materialized.
    """
    if not isinstance(component_spec, ThemeComponentSpec):
        raise TypeError("component_spec must be a ThemeComponentSpec")
    from ..backends.dearpygui_scroller import SharedScrollerMetrics, SharedScrollerPalette
    p = SharedScrollerPalette
    m = SharedScrollerMetrics
    return (component_spec
            .with_color(ThemeColor.SCROLLBAR_BACKGROUND, tuple(track or p.TRACK))
            .with_color(ThemeColor.SCROLLBAR_GRAB, p.THUMB)
            .with_color(ThemeColor.SCROLLBAR_GRAB_HOVERED, p.THUMB_HOVER)
            .with_color(ThemeColor.SCROLLBAR_GRAB_ACTIVE, p.THUMB_ACTIVE)
            .with_style(ThemeStyle.SCROLLBAR_SIZE, m.THICKNESS)
            .with_style(ThemeStyle.SCROLLBAR_ROUNDING, m.ROUNDING))


def make_theme(*components: ThemeComponentSpec, backend=None, tag: Optional[str] = None, cache: bool = False):
    """Convenience shortcut combining :func:`theme` and :func:`create_theme`."""
    return create_theme(theme(*components, tag=tag, cache=cache), backend=backend)


theme_component = component
theme_spec = theme


__all__ = [
    "ThemeTarget", "ThemeColor", "ThemeStyle", "ThemeValue",
    "ThemeComponentSpec", "ThemeSpec", "component", "theme", "theme_component", "theme_spec",
    "create_theme", "make_theme", "with_scrollbar",
]
