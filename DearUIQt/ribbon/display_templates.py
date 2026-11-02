"""Reusable visual/layout presets for :mod:`DearUIQt.ribbon`.

Unlike composition templates, display templates never define application tabs,
groups, commands, callbacks or resources.  They only describe how any ribbon is
rendered: geometry, spacing, icon scale, stacking density and visual chrome.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RibbonAdaptivePolicy:
    """Visual reduction policy used when a ribbon is narrower than its content.

    This policy contains geometry only.  It never names tabs, groups or commands.
    """

    enabled: bool = True
    medium_scale: float = 0.84
    small_scale: float = 0.68
    medium_min_width: int = 64
    small_min_width: int = 48
    min_command_width: int = 44

    def __post_init__(self):
        if not 0 < float(self.small_scale) <= float(self.medium_scale) <= 1.0:
            raise ValueError("adaptive scales must satisfy 0 < small <= medium <= 1")
        for name in ("medium_min_width", "small_min_width", "min_command_width"):
            if int(getattr(self, name)) <= 0:
                raise ValueError("{} must be greater than zero.".format(name))

    def group_widths(self, natural_width: int) -> tuple[int, int, int]:
        natural = max(1, int(natural_width))
        medium = min(natural, max(int(self.medium_min_width), int(round(natural * self.medium_scale))))
        small = min(medium, max(int(self.small_min_width), int(round(natural * self.small_scale))))
        return natural, medium, small

    def command_width(self, natural_width: int, state: str) -> int:
        natural = max(1, int(natural_width))
        state = str(state or "large").lower()
        if state == "medium":
            scale = self.medium_scale
        elif state == "small":
            scale = self.small_scale
        else:
            scale = 1.0
        return min(natural, max(int(self.min_command_width), int(round(natural * scale))))


@dataclass(frozen=True)
class RibbonDisplayTemplate:
    """Backend-independent geometry preset used while constructing a RibbonBar."""

    key: str
    name: str
    description: str = ""
    quick_access_default: bool = True
    visual_style: str = "classic"
    quick_access_height: int = 25

    tab_height: int = 30
    tab_indicator_height: int = 2
    body_height: int = 124
    group_footer_height: int = 20
    group_gap: int = 2
    command_gap: int = 2
    group_horizontal_padding: int = 3
    controls_horizontal_padding: int = 2
    group_min_width: int = 72
    group_separator_width: int = 7

    large_button_width: int = 96
    large_button_height: int = 82
    large_icon_size: int = 40
    large_label_height: int = 28
    small_button_width: int = 98
    small_button_height: int = 20
    small_rows: int = 3
    split_arrow_width: int = 22

    tile_font_size: int = 9
    tile_line_height: int = 11
    tile_text_margin: int = 6

    tab_min_width: int = 58
    tab_char_width: int = 7
    tab_padding_x: int = 8
    tab_padding_y: int = 3
    group_caption_char_width: int = 7

    button_padding_x: int = 5
    button_padding_y: int = 3
    compact_button_padding_x: int = 3
    compact_button_padding_y: int = 1
    button_rounding: int = 3
    surface_spacing_x: int = 2
    surface_spacing_y: int = 1

    overflow_width: int = 65
    responsive_padding: int = 10
    show_group_labels: bool = True
    show_group_separators: bool = True
    adaptive_policy: RibbonAdaptivePolicy = field(default_factory=RibbonAdaptivePolicy)

    def __post_init__(self):
        if not str(self.key).strip():
            raise ValueError("Ribbon display template key cannot be empty.")
        if not str(self.visual_style).strip():
            raise ValueError("Ribbon display template visual_style cannot be empty.")
        if not isinstance(self.adaptive_policy, RibbonAdaptivePolicy):
            raise TypeError("adaptive_policy must be a RibbonAdaptivePolicy")
        positive = (
            "quick_access_height", "tab_height", "tab_indicator_height", "body_height", "large_button_width", "large_button_height",
            "large_icon_size", "small_button_width", "small_button_height", "small_rows",
            "split_arrow_width", "tab_min_width", "tab_char_width", "group_caption_char_width",
            "overflow_width",
        )
        for field_name in positive:
            if int(getattr(self, field_name)) <= 0:
                raise ValueError("{} must be greater than zero.".format(field_name))

    def metrics(self) -> dict[str, int]:
        """Return RibbonBar instance-constant overrides for this preset."""
        return {
            "QUICK_ACCESS_HEIGHT": self.quick_access_height,
            "TAB_HEIGHT": self.tab_height,
            "TAB_INDICATOR_HEIGHT": self.tab_indicator_height,
            "BODY_HEIGHT": self.body_height,
            "GROUP_FOOTER_HEIGHT": self.group_footer_height,
            "GROUP_GAP": self.group_gap,
            "COMMAND_GAP": self.command_gap,
            "GROUP_HORIZONTAL_PADDING": self.group_horizontal_padding,
            "CONTROLS_HORIZONTAL_PADDING": self.controls_horizontal_padding,
            "GROUP_MIN_WIDTH": self.group_min_width,
            "GROUP_SEPARATOR_WIDTH": self.group_separator_width,
            "LARGE_BUTTON_WIDTH": self.large_button_width,
            "LARGE_BUTTON_HEIGHT": self.large_button_height,
            "LARGE_ICON_SIZE": self.large_icon_size,
            "LARGE_LABEL_HEIGHT": self.large_label_height,
            "SMALL_BUTTON_WIDTH": self.small_button_width,
            "SMALL_BUTTON_HEIGHT": self.small_button_height,
            "SMALL_ROWS": self.small_rows,
            "SPLIT_ARROW_WIDTH": self.split_arrow_width,
            "TILE_FONT_SIZE": self.tile_font_size,
            "TILE_LINE_HEIGHT": self.tile_line_height,
            "TILE_TEXT_MARGIN": self.tile_text_margin,
            "TAB_MIN_WIDTH": self.tab_min_width,
            "TAB_CHAR_WIDTH": self.tab_char_width,
            "TAB_PADDING_X": self.tab_padding_x,
            "TAB_PADDING_Y": self.tab_padding_y,
            "GROUP_CAPTION_CHAR_WIDTH": self.group_caption_char_width,
            "BUTTON_PADDING_X": self.button_padding_x,
            "BUTTON_PADDING_Y": self.button_padding_y,
            "COMPACT_BUTTON_PADDING_X": self.compact_button_padding_x,
            "COMPACT_BUTTON_PADDING_Y": self.compact_button_padding_y,
            "BUTTON_ROUNDING": self.button_rounding,
            "SURFACE_SPACING_X": self.surface_spacing_x,
            "SURFACE_SPACING_Y": self.surface_spacing_y,
            "OVERFLOW_WIDTH": self.overflow_width,
            "RESPONSIVE_PADDING": self.responsive_padding,
        }


_DISPLAY_TEMPLATES: dict[str, RibbonDisplayTemplate] = {}


def register_ribbon_display_template(
    template: RibbonDisplayTemplate, *, replace: bool = False
) -> RibbonDisplayTemplate:
    if not isinstance(template, RibbonDisplayTemplate):
        raise TypeError("template must be a RibbonDisplayTemplate")
    key = str(template.key).strip().lower()
    if key in _DISPLAY_TEMPLATES and not replace:
        raise ValueError("Ribbon display template {!r} is already registered.".format(key))
    _DISPLAY_TEMPLATES[key] = template
    return template


def get_ribbon_display_template(template: str | RibbonDisplayTemplate) -> RibbonDisplayTemplate:
    if isinstance(template, RibbonDisplayTemplate):
        return template
    key = str(template or "classic").strip().lower()
    try:
        return _DISPLAY_TEMPLATES[key]
    except KeyError as exc:
        raise KeyError(
            "Unknown ribbon display template {!r}. Available: {}".format(
                key, ", ".join(sorted(_DISPLAY_TEMPLATES)) or "<none>"
            )
        ) from exc


def ribbon_display_template_names() -> tuple[str, ...]:
    return tuple(sorted(_DISPLAY_TEMPLATES))


class RibbonDisplayTemplateFactory:
    """Registry/factory for ready-made visual RibbonBar presets."""

    @staticmethod
    def names() -> tuple[str, ...]:
        return ribbon_display_template_names()

    @staticmethod
    def get(template: str | RibbonDisplayTemplate) -> RibbonDisplayTemplate:
        return get_ribbon_display_template(template)

    @staticmethod
    def register(template: RibbonDisplayTemplate, *, replace: bool = False) -> RibbonDisplayTemplate:
        return register_ribbon_display_template(template, replace=replace)

    @staticmethod
    def create(parent, template: str | RibbonDisplayTemplate = "classic", **kwargs):
        from .bar import RibbonBar
        return RibbonBar(parent, display_template=template, **kwargs)


CLASSIC_DISPLAY_TEMPLATE = register_ribbon_display_template(RibbonDisplayTemplate(
    key="classic",
    name="Classic",
    description="Traditional Office-style ribbon proportions with clear group captions.",
))

BALANCED_DISPLAY_TEMPLATE = register_ribbon_display_template(RibbonDisplayTemplate(
    key="balanced",
    name="Balanced",
    description="Moderate height and spacing for general desktop applications.",
    visual_style="clean",
    adaptive_policy=RibbonAdaptivePolicy(medium_scale=0.86, small_scale=0.70, medium_min_width=62, small_min_width=46, min_command_width=42),
    tab_height=30, body_height=108, group_footer_height=18,
    group_gap=3, command_gap=2,
    large_button_width=82, large_button_height=68, large_icon_size=32, large_label_height=22,
    small_button_width=92, small_button_height=22, small_rows=3,
    split_arrow_width=22,
))

COMPACT_DISPLAY_TEMPLATE = register_ribbon_display_template(RibbonDisplayTemplate(
    key="compact",
    name="Compact",
    description="Reduced-height ribbon that retains captions and three-row command stacks.",
    visual_style="clean",
    adaptive_policy=RibbonAdaptivePolicy(medium_scale=0.90, small_scale=0.76, medium_min_width=58, small_min_width=44, min_command_width=40),
    quick_access_default=False,
    quick_access_height=23, tab_height=28, body_height=92, group_footer_height=18,
    group_gap=2, command_gap=1,
    group_horizontal_padding=2, controls_horizontal_padding=2,
    large_button_width=66, large_button_height=54, large_icon_size=24, large_label_height=18,
    small_button_width=88, small_button_height=18, small_rows=3,
    split_arrow_width=20,
    tile_font_size=8, tile_line_height=10, tile_text_margin=4,
    tab_min_width=54, tab_padding_x=7, tab_padding_y=2,
    button_padding_x=4, button_padding_y=2,
))

DENSE_DISPLAY_TEMPLATE = register_ribbon_display_template(RibbonDisplayTemplate(
    key="dense",
    name="Dense",
    description="Maximum command density for engineering and data-heavy desktop tools.",
    visual_style="flat",
    adaptive_policy=RibbonAdaptivePolicy(medium_scale=0.93, small_scale=0.82, medium_min_width=54, small_min_width=42, min_command_width=38),
    quick_access_default=False,
    quick_access_height=22, tab_height=26, body_height=84, group_footer_height=16,
    group_gap=1, command_gap=1,
    group_horizontal_padding=2, controls_horizontal_padding=1,
    large_button_width=58, large_button_height=46, large_icon_size=20, large_label_height=16,
    small_button_width=80, small_button_height=17, small_rows=3,
    split_arrow_width=18,
    tile_font_size=8, tile_line_height=9, tile_text_margin=3,
    tab_min_width=50, tab_char_width=6, tab_padding_x=6, tab_padding_y=2,
    group_caption_char_width=6,
    button_padding_x=3, button_padding_y=1,
    compact_button_padding_x=2, compact_button_padding_y=1,
    button_rounding=2,
    surface_spacing_x=1, surface_spacing_y=1,
    overflow_width=58, responsive_padding=6,
))

LARGE_ICONS_DISPLAY_TEMPLATE = register_ribbon_display_template(RibbonDisplayTemplate(
    key="large-icons",
    name="Large Icons",
    description="Visual command-first layout with larger icon tiles while preserving desktop spacing.",
    visual_style="soft",
    adaptive_policy=RibbonAdaptivePolicy(medium_scale=0.80, small_scale=0.62, medium_min_width=68, small_min_width=50, min_command_width=46),
    tab_height=31, body_height=136, group_footer_height=20,
    group_gap=3, command_gap=3,
    large_button_width=104, large_button_height=92, large_icon_size=48, large_label_height=28,
    small_button_width=106, small_button_height=22, small_rows=3,
    split_arrow_width=24,
    tile_font_size=9, tile_line_height=11, tile_text_margin=7,
))

TOUCH_DISPLAY_TEMPLATE = register_ribbon_display_template(RibbonDisplayTemplate(
    key="touch",
    name="Touch",
    description="Larger hit targets and spacing for touch screens or high-DPI interaction.",
    visual_style="soft",
    adaptive_policy=RibbonAdaptivePolicy(medium_scale=0.90, small_scale=0.78, medium_min_width=78, small_min_width=64, min_command_width=58),
    quick_access_height=32, tab_height=36, body_height=148, group_footer_height=22,
    group_gap=5, command_gap=4,
    group_horizontal_padding=5, controls_horizontal_padding=4,
    large_button_width=112, large_button_height=98, large_icon_size=48, large_label_height=30,
    small_button_width=124, small_button_height=28, small_rows=3,
    split_arrow_width=30,
    tile_font_size=10, tile_line_height=13, tile_text_margin=8,
    tab_min_width=70, tab_char_width=8, tab_padding_x=11, tab_padding_y=5,
    group_caption_char_width=8,
    button_padding_x=8, button_padding_y=5,
    compact_button_padding_x=6, compact_button_padding_y=3,
    button_rounding=5,
    surface_spacing_x=4, surface_spacing_y=3,
    overflow_width=76, responsive_padding=14,
))

MINIMAL_DISPLAY_TEMPLATE = register_ribbon_display_template(RibbonDisplayTemplate(
    key="minimal",
    name="Minimal",
    description="Low-chrome ribbon for applications that prioritize content area.",
    visual_style="minimal",
    adaptive_policy=RibbonAdaptivePolicy(medium_scale=0.92, small_scale=0.80, medium_min_width=52, small_min_width=40, min_command_width=38),
    quick_access_default=False,
    quick_access_height=22, tab_height=27, body_height=78, group_footer_height=0,
    group_gap=1, command_gap=1,
    group_horizontal_padding=2, controls_horizontal_padding=1,
    large_button_width=60, large_button_height=50, large_icon_size=22, large_label_height=16,
    small_button_width=84, small_button_height=19, small_rows=3,
    split_arrow_width=19,
    tile_font_size=8, tile_line_height=9, tile_text_margin=3,
    tab_min_width=52, tab_char_width=6, tab_padding_x=6, tab_padding_y=2,
    group_caption_char_width=6,
    button_padding_x=3, button_padding_y=1,
    compact_button_padding_x=2, compact_button_padding_y=1,
    button_rounding=2,
    surface_spacing_x=1, surface_spacing_y=0,
    overflow_width=58, responsive_padding=6,
    show_group_labels=False, show_group_separators=False,
))


__all__ = [
    "RibbonAdaptivePolicy", "RibbonDisplayTemplate", "RibbonDisplayTemplateFactory",
    "register_ribbon_display_template", "get_ribbon_display_template",
    "ribbon_display_template_names",
    "CLASSIC_DISPLAY_TEMPLATE", "BALANCED_DISPLAY_TEMPLATE",
    "COMPACT_DISPLAY_TEMPLATE", "DENSE_DISPLAY_TEMPLATE",
    "LARGE_ICONS_DISPLAY_TEMPLATE", "TOUCH_DISPLAY_TEMPLATE",
    "MINIMAL_DISPLAY_TEMPLATE",
]
