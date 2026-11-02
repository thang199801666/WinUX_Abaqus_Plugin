"""Ready-made generic appearance templates for :mod:`DearUIQt.ribbon`.

Appearance templates are intentionally content-agnostic.  They combine a
``RibbonDisplayTemplate`` (geometry), ``RibbonVisualStyle`` (palette/chrome),
and semantic render modes for tabs, groups and command surfaces.  Applications
still own every tab, group, command, callback and icon.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


TAB_RENDER_STYLES = ("filled", "underline", "top-line", "side-accent", "pill")
GROUP_RENDER_STYLES = ("separator", "flat", "bordered", "card")
BUTTON_RENDER_STYLES = ("flat", "raised", "outlined")


def _normalize(value: str, allowed: tuple[str, ...], label: str) -> str:
    key = str(value or "").strip().lower()
    if key not in allowed:
        raise ValueError("{} must be one of: {}".format(label, ", ".join(allowed)))
    return key


def normalize_tab_render_style(value: str) -> str:
    return _normalize(value, TAB_RENDER_STYLES, "tab render style")


def normalize_group_render_style(value: str) -> str:
    return _normalize(value, GROUP_RENDER_STYLES, "group render style")


def normalize_button_render_style(value: str) -> str:
    return _normalize(value, BUTTON_RENDER_STYLES, "button render style")


@dataclass(frozen=True)
class RibbonAppearanceTemplate:
    """One reusable visual recipe for any RibbonBar content."""

    key: str
    name: str
    description: str = ""
    display_template: str = "balanced"
    visual_style: str = "clean"
    tab_style: str = "filled"
    group_style: str = "separator"
    button_style: str = "flat"

    def __post_init__(self):
        if not str(self.key).strip():
            raise ValueError("Ribbon appearance template key cannot be empty.")
        if not str(self.display_template).strip():
            raise ValueError("display_template cannot be empty.")
        if not str(self.visual_style).strip():
            raise ValueError("visual_style cannot be empty.")
        object.__setattr__(self, "tab_style", normalize_tab_render_style(self.tab_style))
        object.__setattr__(self, "group_style", normalize_group_render_style(self.group_style))
        object.__setattr__(self, "button_style", normalize_button_render_style(self.button_style))

    def derive(self, *, key: str, name: str | None = None, **overrides):
        """Create a new appearance recipe by overriding this generic preset."""
        values = dict(overrides)
        values["key"] = key
        values["name"] = self.name if name is None else name
        return replace(self, **values)


_APPEARANCE_TEMPLATES: dict[str, RibbonAppearanceTemplate] = {}


def register_ribbon_appearance_template(
    template: RibbonAppearanceTemplate, *, replace: bool = False
) -> RibbonAppearanceTemplate:
    if not isinstance(template, RibbonAppearanceTemplate):
        raise TypeError("template must be a RibbonAppearanceTemplate")
    key = str(template.key).strip().lower()
    if key in _APPEARANCE_TEMPLATES and not replace:
        raise ValueError("Ribbon appearance template {!r} is already registered.".format(key))
    _APPEARANCE_TEMPLATES[key] = template
    return template


def get_ribbon_appearance_template(
    template: str | RibbonAppearanceTemplate,
) -> RibbonAppearanceTemplate:
    if isinstance(template, RibbonAppearanceTemplate):
        return template
    key = str(template or "modern-clean").strip().lower()
    try:
        return _APPEARANCE_TEMPLATES[key]
    except KeyError as exc:
        raise KeyError(
            "Unknown ribbon appearance template {!r}. Available: {}".format(
                key, ", ".join(sorted(_APPEARANCE_TEMPLATES)) or "<none>"
            )
        ) from exc


def ribbon_appearance_template_names() -> tuple[str, ...]:
    return tuple(sorted(_APPEARANCE_TEMPLATES))


class RibbonAppearanceTemplateFactory:
    """Registry/factory for complete, content-independent ribbon appearances."""

    @staticmethod
    def names() -> tuple[str, ...]:
        return ribbon_appearance_template_names()

    @staticmethod
    def get(template: str | RibbonAppearanceTemplate) -> RibbonAppearanceTemplate:
        return get_ribbon_appearance_template(template)

    @staticmethod
    def register(
        template: RibbonAppearanceTemplate, *, replace: bool = False
    ) -> RibbonAppearanceTemplate:
        return register_ribbon_appearance_template(template, replace=replace)

    @staticmethod
    def create(parent, template: str | RibbonAppearanceTemplate = "modern-clean", **kwargs):
        from .bar import RibbonBar
        return RibbonBar(parent, appearance_template=template, **kwargs)

    @staticmethod
    def variant(base: str | RibbonAppearanceTemplate, *, key: str, name: str | None = None,
                register: bool = False, replace_existing: bool = False, **overrides):
        """Derive a reusable template from another preset without copying its fields."""
        template = get_ribbon_appearance_template(base).derive(
            key=key, name=name, **overrides)
        if register:
            register_ribbon_appearance_template(template, replace=replace_existing)
        return template


CLASSIC_OFFICE_APPEARANCE = register_ribbon_appearance_template(RibbonAppearanceTemplate(
    key="classic-office",
    name="Classic Office",
    description="Traditional desktop ribbon with filled tabs, separated groups and flat commands.",
    display_template="classic",
    visual_style="classic",
    tab_style="filled",
    group_style="separator",
    button_style="flat",
))

MODERN_CLEAN_APPEARANCE = register_ribbon_appearance_template(RibbonAppearanceTemplate(
    key="modern-clean",
    name="Modern Clean",
    description="Balanced Windows-like geometry with accent tabs and restrained group borders.",
    display_template="balanced",
    visual_style="clean",
    tab_style="underline",
    group_style="bordered",
    button_style="flat",
))

SOFT_CARD_APPEARANCE = register_ribbon_appearance_template(RibbonAppearanceTemplate(
    key="soft-card",
    name="Soft Card",
    description="Rounded tabs, card groups and raised command surfaces for a softer modern UI.",
    display_template="balanced",
    visual_style="soft",
    tab_style="pill",
    group_style="card",
    button_style="raised",
))

COMPACT_FLAT_APPEARANCE = register_ribbon_appearance_template(RibbonAppearanceTemplate(
    key="compact-flat",
    name="Compact Flat",
    description="Short desktop ribbon with accent tabs and low-chrome command surfaces.",
    display_template="compact",
    visual_style="clean",
    tab_style="underline",
    group_style="separator",
    button_style="flat",
))

DENSE_OUTLINE_APPEARANCE = register_ribbon_appearance_template(RibbonAppearanceTemplate(
    key="dense-outline",
    name="Dense Outline",
    description="High-density engineering layout with bordered groups and outlined commands.",
    display_template="dense",
    visual_style="flat",
    tab_style="underline",
    group_style="bordered",
    button_style="outlined",
))

TOUCH_SOFT_APPEARANCE = register_ribbon_appearance_template(RibbonAppearanceTemplate(
    key="touch-soft",
    name="Touch Soft",
    description="Large hit targets with rounded tabs, cards and raised command surfaces.",
    display_template="touch",
    visual_style="soft",
    tab_style="pill",
    group_style="card",
    button_style="raised",
))

MINIMAL_APPEARANCE = register_ribbon_appearance_template(RibbonAppearanceTemplate(
    key="minimal",
    name="Minimal",
    description="Compact content-first ribbon with accent tabs and nearly borderless groups.",
    display_template="minimal",
    visual_style="minimal",
    tab_style="underline",
    group_style="flat",
    button_style="flat",
))

HIGH_CONTRAST_APPEARANCE = register_ribbon_appearance_template(RibbonAppearanceTemplate(
    key="high-contrast",
    name="High Contrast",
    description="Clear filled tabs, bordered groups and outlined commands for strong state visibility.",
    display_template="balanced",
    visual_style="high-contrast",
    tab_style="filled",
    group_style="bordered",
    button_style="outlined",
))

TOPLINE_CLEAN_APPEARANCE = register_ribbon_appearance_template(RibbonAppearanceTemplate(
    key="topline-clean",
    name="Topline Clean",
    description="Balanced clean ribbon with a retained active line above each selected tab.",
    display_template="balanced",
    visual_style="clean",
    tab_style="top-line",
    group_style="bordered",
    button_style="flat",
))

SIDE_ACCENT_DENSE_APPEARANCE = register_ribbon_appearance_template(RibbonAppearanceTemplate(
    key="side-accent-dense",
    name="Side Accent Dense",
    description="Dense engineering-oriented geometry with a retained side accent on active tabs.",
    display_template="dense",
    visual_style="flat",
    tab_style="side-accent",
    group_style="bordered",
    button_style="outlined",
))


__all__ = [
    "TAB_RENDER_STYLES", "GROUP_RENDER_STYLES", "BUTTON_RENDER_STYLES",
    "normalize_tab_render_style", "normalize_group_render_style", "normalize_button_render_style",
    "RibbonAppearanceTemplate", "RibbonAppearanceTemplateFactory",
    "register_ribbon_appearance_template", "get_ribbon_appearance_template",
    "ribbon_appearance_template_names",
    "CLASSIC_OFFICE_APPEARANCE", "MODERN_CLEAN_APPEARANCE", "SOFT_CARD_APPEARANCE",
    "COMPACT_FLAT_APPEARANCE", "DENSE_OUTLINE_APPEARANCE", "TOUCH_SOFT_APPEARANCE",
    "MINIMAL_APPEARANCE", "HIGH_CONTRAST_APPEARANCE",
    "TOPLINE_CLEAN_APPEARANCE", "SIDE_ACCENT_DENSE_APPEARANCE",
]
