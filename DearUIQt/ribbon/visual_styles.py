"""Generic visual styles for :mod:`DearUIQt.ribbon`.

Visual styles describe *chrome*, not application content or layout.  They can be
combined with any :class:`RibbonDisplayTemplate`: colors, borders, rounding and
interactive states are kept separate from tabs/groups/commands and from geometry.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..gui.palette import QtFusionPalette


Color = tuple[int, int, int, int]


def _rgba(value) -> Color:
    values = tuple(int(channel) for channel in value)
    if len(values) == 3:
        values += (255,)
    if len(values) != 4:
        raise ValueError("Ribbon colors must be RGB or RGBA tuples.")
    return tuple(max(0, min(255, channel)) for channel in values)


def _with_alpha(value, alpha: int) -> Color:
    color = _rgba(value)
    return color[:3] + (max(0, min(255, int(alpha))),)


@dataclass(frozen=True)
class RibbonVisualStyle:
    """Backend-independent colors and chrome for a ribbon surface.

    The style intentionally does not contain dimensions or application command
    names.  Geometry belongs to :class:`RibbonDisplayTemplate`.
    """

    key: str
    name: str
    description: str = ""

    root_bg: Color = QtFusionPalette.WINDOW
    quick_bg: Color = QtFusionPalette.WINDOW
    tabs_bg: Color = QtFusionPalette.WINDOW
    body_bg: Color = QtFusionPalette.BASE
    page_bg: Color = QtFusionPalette.BASE
    group_bg: Color = QtFusionPalette.BASE
    controls_bg: Color = QtFusionPalette.BASE

    body_border: Color = QtFusionPalette.BORDER_LIGHT
    body_border_size: int = 1
    group_border: Color = (0, 0, 0, 0)
    group_border_size: int = 0
    group_rounding: int = 0
    separator: Color = QtFusionPalette.BORDER_LIGHT

    text: Color = QtFusionPalette.TEXT
    muted_text: Color = QtFusionPalette.TEXT_MUTED
    disabled_text: Color = QtFusionPalette.TEXT_DISABLED

    tab_normal: Color = (0, 0, 0, 0)
    tab_hover: Color = QtFusionPalette.BUTTON_HOVER
    tab_pressed: Color = QtFusionPalette.BUTTON_ACTIVE
    tab_active: Color = QtFusionPalette.BASE
    tab_active_border: Color = QtFusionPalette.HIGHLIGHT
    tab_active_border_size: int = 1
    tab_rounding: int | None = None

    button_normal: Color = (0, 0, 0, 0)
    button_hover: Color = QtFusionPalette.BUTTON_HOVER
    button_pressed: Color = QtFusionPalette.BUTTON_ACTIVE
    button_checked: Color = QtFusionPalette.HIGHLIGHT_SOFT
    button_border: Color = (0, 0, 0, 0)
    button_border_size: int = 0
    button_checked_border: Color = QtFusionPalette.SELECTION_BORDER
    button_checked_border_size: int = 1
    button_rounding: int | None = None

    application_normal: Color = QtFusionPalette.PRIMARY
    application_hover: Color = QtFusionPalette.PRIMARY_HOVER
    application_pressed: Color = QtFusionPalette.PRIMARY_ACTIVE
    application_text: Color = QtFusionPalette.HIGHLIGHT_TEXT
    application_border: Color = QtFusionPalette.BORDER
    application_border_size: int = 1

    def __post_init__(self):
        if not str(self.key).strip():
            raise ValueError("Ribbon visual style key cannot be empty.")
        color_fields = (
            "root_bg", "quick_bg", "tabs_bg", "body_bg", "page_bg", "group_bg", "controls_bg",
            "body_border", "group_border", "separator", "text", "muted_text", "disabled_text",
            "tab_normal", "tab_hover", "tab_pressed", "tab_active", "tab_active_border",
            "button_normal", "button_hover", "button_pressed", "button_checked", "button_border",
            "button_checked_border", "application_normal", "application_hover", "application_pressed",
            "application_text", "application_border",
        )
        for field_name in color_fields:
            object.__setattr__(self, field_name, _rgba(getattr(self, field_name)))
        for field_name in (
            "body_border_size", "group_border_size", "group_rounding", "tab_active_border_size",
            "button_border_size", "button_checked_border_size", "application_border_size",
        ):
            if int(getattr(self, field_name)) < 0:
                raise ValueError("{} cannot be negative.".format(field_name))
        for field_name in ("tab_rounding", "button_rounding"):
            value = getattr(self, field_name)
            if value is not None and int(value) < 0:
                raise ValueError("{} cannot be negative.".format(field_name))


_VISUAL_STYLES: dict[str, RibbonVisualStyle] = {}


def register_ribbon_visual_style(
    style: RibbonVisualStyle, *, replace: bool = False
) -> RibbonVisualStyle:
    if not isinstance(style, RibbonVisualStyle):
        raise TypeError("style must be a RibbonVisualStyle")
    key = str(style.key).strip().lower()
    if key in _VISUAL_STYLES and not replace:
        raise ValueError("Ribbon visual style {!r} is already registered.".format(key))
    _VISUAL_STYLES[key] = style
    return style


def get_ribbon_visual_style(style: str | RibbonVisualStyle) -> RibbonVisualStyle:
    if isinstance(style, RibbonVisualStyle):
        return style
    key = str(style or "classic").strip().lower()
    try:
        return _VISUAL_STYLES[key]
    except KeyError as exc:
        raise KeyError(
            "Unknown ribbon visual style {!r}. Available: {}".format(
                key, ", ".join(sorted(_VISUAL_STYLES)) or "<none>"
            )
        ) from exc


def ribbon_visual_style_names() -> tuple[str, ...]:
    return tuple(sorted(_VISUAL_STYLES))


class RibbonVisualStyleFactory:
    """Registry/factory helpers for generic ribbon chrome presets."""

    @staticmethod
    def names() -> tuple[str, ...]:
        return ribbon_visual_style_names()

    @staticmethod
    def get(style: str | RibbonVisualStyle) -> RibbonVisualStyle:
        return get_ribbon_visual_style(style)

    @staticmethod
    def register(style: RibbonVisualStyle, *, replace: bool = False) -> RibbonVisualStyle:
        return register_ribbon_visual_style(style, replace=replace)


CLASSIC_VISUAL_STYLE = register_ribbon_visual_style(RibbonVisualStyle(
    key="classic",
    name="Classic",
    description="Traditional desktop ribbon: white active tab, subtle flat commands and clear separators.",
    application_normal=(214, 112, 28, 255),
    application_hover=(229, 132, 42, 255),
    application_pressed=(190, 92, 18, 255),
    tab_active_border=(214, 112, 28, 255),
))

CLEAN_VISUAL_STYLE = register_ribbon_visual_style(RibbonVisualStyle(
    key="clean",
    name="Clean",
    description="Neutral Windows-like ribbon with a blue focus accent and low visual noise.",
    root_bg=QtFusionPalette.WINDOW_ALT,
    quick_bg=QtFusionPalette.WINDOW_ALT,
    tabs_bg=QtFusionPalette.WINDOW_ALT,
    body_bg=QtFusionPalette.BASE,
    page_bg=QtFusionPalette.BASE,
    group_bg=QtFusionPalette.BASE,
    controls_bg=QtFusionPalette.BASE,
    body_border=QtFusionPalette.BORDER_LIGHT,
    tab_active=QtFusionPalette.BASE,
    tab_active_border=QtFusionPalette.FOCUS,
    button_checked=QtFusionPalette.SELECTION_ACTIVE,
    button_checked_border=QtFusionPalette.SELECTION_BORDER,
))

SOFT_VISUAL_STYLE = register_ribbon_visual_style(RibbonVisualStyle(
    key="soft",
    name="Soft",
    description="Soft cards and rounded interactive surfaces for icon-forward ribbons.",
    root_bg=QtFusionPalette.WINDOW_ALT,
    quick_bg=QtFusionPalette.WINDOW_ALT,
    tabs_bg=QtFusionPalette.WINDOW_ALT,
    body_bg=QtFusionPalette.WINDOW_ALT,
    page_bg=QtFusionPalette.WINDOW_ALT,
    group_bg=QtFusionPalette.BASE,
    controls_bg=QtFusionPalette.BASE,
    group_border=QtFusionPalette.BORDER_LIGHT,
    group_border_size=1,
    group_rounding=4,
    separator=_with_alpha(QtFusionPalette.BORDER_LIGHT, 120),
    tab_normal=(0, 0, 0, 0),
    tab_active=QtFusionPalette.BASE,
    tab_active_border=QtFusionPalette.SELECTION_BORDER,
    tab_rounding=4,
    button_hover=QtFusionPalette.HIGHLIGHT_HOVER,
    button_pressed=QtFusionPalette.SELECTION_ACTIVE_PRESSED,
    button_checked=QtFusionPalette.SELECTION_ACTIVE,
    button_checked_border=QtFusionPalette.SELECTION_BORDER,
    button_rounding=5,
))

FLAT_VISUAL_STYLE = register_ribbon_visual_style(RibbonVisualStyle(
    key="flat",
    name="Flat",
    description="Dense low-chrome ribbon with transparent groups and accent-only interaction states.",
    root_bg=QtFusionPalette.WINDOW,
    quick_bg=QtFusionPalette.WINDOW,
    tabs_bg=QtFusionPalette.WINDOW,
    body_bg=QtFusionPalette.WINDOW,
    page_bg=QtFusionPalette.WINDOW,
    group_bg=QtFusionPalette.WINDOW,
    controls_bg=QtFusionPalette.WINDOW,
    body_border=_with_alpha(QtFusionPalette.BORDER_LIGHT, 150),
    separator=_with_alpha(QtFusionPalette.BORDER, 110),
    tab_active=_with_alpha(QtFusionPalette.HIGHLIGHT_SOFT, 130),
    tab_active_border=QtFusionPalette.FOCUS,
    button_hover=_with_alpha(QtFusionPalette.BUTTON_HOVER, 185),
    button_pressed=_with_alpha(QtFusionPalette.BUTTON_ACTIVE, 210),
    button_checked=_with_alpha(QtFusionPalette.HIGHLIGHT_SOFT, 190),
    button_checked_border=_with_alpha(QtFusionPalette.FOCUS, 180),
    button_rounding=2,
))

MINIMAL_VISUAL_STYLE = register_ribbon_visual_style(RibbonVisualStyle(
    key="minimal",
    name="Minimal",
    description="Almost borderless chrome for maximum content emphasis.",
    root_bg=QtFusionPalette.WINDOW,
    quick_bg=QtFusionPalette.WINDOW,
    tabs_bg=QtFusionPalette.WINDOW,
    body_bg=QtFusionPalette.WINDOW,
    page_bg=QtFusionPalette.WINDOW,
    group_bg=QtFusionPalette.WINDOW,
    controls_bg=QtFusionPalette.WINDOW,
    body_border=(0, 0, 0, 0),
    body_border_size=0,
    separator=(0, 0, 0, 0),
    tab_active=_with_alpha(QtFusionPalette.HIGHLIGHT_SOFT, 120),
    tab_active_border=QtFusionPalette.FOCUS,
    tab_active_border_size=0,
    button_hover=_with_alpha(QtFusionPalette.BUTTON_HOVER, 160),
    button_pressed=_with_alpha(QtFusionPalette.BUTTON_ACTIVE, 190),
    button_checked=_with_alpha(QtFusionPalette.HIGHLIGHT_SOFT, 160),
    button_checked_border=(0, 0, 0, 0),
    button_checked_border_size=0,
    application_border=(0, 0, 0, 0),
    application_border_size=0,
    tab_rounding=2,
    button_rounding=2,
))

HIGH_CONTRAST_VISUAL_STYLE = register_ribbon_visual_style(RibbonVisualStyle(
    key="high-contrast",
    name="High Contrast",
    description="Stronger borders and interaction contrast for visibility-sensitive desktop workflows.",
    body_border=QtFusionPalette.BORDER_DARK,
    group_border=QtFusionPalette.BORDER,
    group_border_size=1,
    separator=QtFusionPalette.BORDER_DARK,
    tab_hover=QtFusionPalette.SELECTION_ACTIVE_HOVER,
    tab_pressed=QtFusionPalette.SELECTION_ACTIVE_PRESSED,
    tab_active=QtFusionPalette.SELECTION_ACTIVE,
    tab_active_border=QtFusionPalette.FOCUS,
    tab_active_border_size=1,
    button_hover=QtFusionPalette.SELECTION_ACTIVE_HOVER,
    button_pressed=QtFusionPalette.SELECTION_ACTIVE_PRESSED,
    button_checked=QtFusionPalette.SELECTION_ACTIVE,
    button_border=QtFusionPalette.BORDER_LIGHT,
    button_border_size=1,
    button_checked_border=QtFusionPalette.FOCUS,
    button_checked_border_size=1,
))


__all__ = [
    "RibbonVisualStyle", "RibbonVisualStyleFactory",
    "register_ribbon_visual_style", "get_ribbon_visual_style", "ribbon_visual_style_names",
    "CLASSIC_VISUAL_STYLE", "CLEAN_VISUAL_STYLE", "SOFT_VISUAL_STYLE", "FLAT_VISUAL_STYLE",
    "MINIMAL_VISUAL_STYLE", "HIGH_CONTRAST_VISUAL_STYLE",
]
