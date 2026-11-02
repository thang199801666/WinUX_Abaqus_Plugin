"""Ribbon theme factory separated from RibbonBar behavior.

Palette/chrome comes from :class:`RibbonVisualStyle`, geometry comes from the
active :class:`RibbonDisplayTemplate`, and semantic surface treatment comes from
``tab_render_style``, ``group_render_style`` and ``button_render_style``.  None
of these layers know application command/tab names.
"""
from __future__ import annotations


def _alpha(color) -> int:
    try:
        return int(tuple(color)[3])
    except Exception:
        return 255


class RibbonThemeFactory:
    def __init__(self, ribbon):
        self._ribbon = ribbon

    def __getattr__(self, name):
        return getattr(self._ribbon, name)

    def _cached_theme(self, key, builder):
        # All appearance axes participate in cache identity so runtime render
        # changes can never reuse a theme built for another surface treatment.
        cache_key = (
            self.visual_style_key,
            self.tab_render_style,
            self.group_render_style,
            self.button_render_style,
        ) + tuple(key)
        theme = self._themes.get(cache_key)
        try:
            if theme is not None and self.backend.does_item_exist(theme):
                return theme
        except Exception:
            pass
        theme = builder()
        self._themes[cache_key] = theme
        return theme

    def _group_chrome(self):
        style = self.visual_style
        mode = self.group_render_style
        if mode == "flat":
            return style.page_bg, (0, 0, 0, 0), 0, 0
        if mode == "bordered":
            border = style.group_border if _alpha(style.group_border) else style.body_border
            return style.group_bg, border, max(1, style.group_border_size), min(2, style.group_rounding)
        if mode == "card":
            border = style.group_border if _alpha(style.group_border) else style.body_border
            return style.group_bg, border, max(1, style.group_border_size), max(4, style.group_rounding)
        # separator: historical behavior, including visual-style-specific cards.
        return style.group_bg, style.group_border, style.group_border_size, style.group_rounding

    def _surface_theme(self, kind):
        style = self.visual_style

        def build():
            backgrounds = {
                "root": style.root_bg,
                "quick": style.quick_bg,
                "tabs": style.tabs_bg,
                "body": style.body_bg,
                "page": style.page_bg,
                "group": style.group_bg,
                "controls": style.controls_bg,
                "separator": style.separator,
            }
            group_bg, group_border, group_border_size, group_rounding = self._group_chrome()
            if kind == "group":
                backgrounds["group"] = group_bg
            elif kind == "controls" and self.group_render_style == "flat":
                backgrounds["controls"] = style.page_bg
            elif kind == "tab_host":
                backgrounds["tab_host"] = (0, 0, 0, 0)
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvChildWindow):
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_ChildBg,
                        backgrounds.get(kind, style.body_bg),
                    )
                    if kind == "body":
                        border = style.body_border
                        border_size = style.body_border_size
                    elif kind == "group":
                        border = group_border
                        border_size = group_border_size
                    else:
                        border = (0, 0, 0, 0)
                        border_size = 0
                    self.backend.add_theme_color(self.backend.mvThemeCol_Border, border)
                    if kind == "group":
                        padding = (self.GROUP_HORIZONTAL_PADDING, 2)
                        rounding = group_rounding
                    elif kind == "tab_host":
                        padding = (0, 0)
                        rounding = 0
                    elif kind == "separator":
                        padding = (0, 8)
                        rounding = 0
                    elif kind in ("body", "page"):
                        padding = (2, 2)
                        rounding = 0
                    else:
                        padding = (self.CONTROLS_HORIZONTAL_PADDING, 1)
                        rounding = 0
                    self.backend.add_theme_style(self.backend.mvStyleVar_WindowPadding, *padding)
                    self.backend.add_theme_style(
                        self.backend.mvStyleVar_ItemSpacing,
                        self.SURFACE_SPACING_X,
                        self.SURFACE_SPACING_Y,
                    )
                    self.backend.add_theme_style(self.backend.mvStyleVar_ChildBorderSize, border_size)
                    self.backend.add_theme_style(self.backend.mvStyleVar_ChildRounding, rounding)
            return theme

        return self._cached_theme(("surface", kind), build)

    def _tab_chrome(self, active):
        style = self.visual_style
        mode = self.tab_render_style
        if mode in ("underline", "top-line", "side-accent"):
            # The active edge is rendered by RibbonTabRenderer as a real draw
            # primitive below the button.  Keep the button itself borderless.
            return (
                (0, 0, 0, 0),
                style.tab_hover,
                style.tab_pressed,
                (0, 0, 0, 0),
                0,
                0,
            )
        if mode == "pill":
            normal = style.tab_active if active else style.tab_normal
            border = style.tab_active_border if active else (0, 0, 0, 0)
            border_size = max(0, style.tab_active_border_size if active else 0)
            return normal, style.tab_hover, style.tab_pressed, border, border_size, max(6, self.TAB_HEIGHT // 2)
        rounding = self.BUTTON_ROUNDING if style.tab_rounding is None else style.tab_rounding
        return (
            style.tab_active if active else style.tab_normal,
            style.tab_hover,
            style.tab_pressed,
            style.tab_active_border if active else (0, 0, 0, 0),
            style.tab_active_border_size if active else 0,
            rounding,
        )

    def _tab_theme(self, active):
        style = self.visual_style

        def build():
            normal, hovered, pressed, border, border_size, rounding = self._tab_chrome(active)
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvButton):
                    self.backend.add_theme_color(self.backend.mvThemeCol_Button, normal)
                    self.backend.add_theme_color(self.backend.mvThemeCol_ButtonHovered, hovered)
                    self.backend.add_theme_color(self.backend.mvThemeCol_ButtonActive, pressed)
                    self.backend.add_theme_color(self.backend.mvThemeCol_Text, style.text)
                    self.backend.add_theme_color(self.backend.mvThemeCol_Border, border)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameBorderSize, border_size)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameRounding, rounding)
                    self.backend.add_theme_style(
                        self.backend.mvStyleVar_FramePadding,
                        self.TAB_PADDING_X,
                        self.TAB_PADDING_Y,
                    )
            return theme

        return self._cached_theme(("tab", bool(active)), build)

    def _button_chrome(self, *, checked=False, disabled=False):
        style = self.visual_style
        if checked and not disabled:
            return (
                style.button_checked,
                style.button_hover,
                style.button_pressed,
                style.button_checked_border,
                style.button_checked_border_size,
            )

        mode = self.button_render_style
        if mode == "raised":
            normal = style.button_normal if _alpha(style.button_normal) else style.group_bg
            border = style.button_border if _alpha(style.button_border) else style.body_border
            return normal, style.button_hover, style.button_pressed, border, max(1, style.button_border_size)
        if mode == "outlined":
            border = style.button_border if _alpha(style.button_border) else style.button_checked_border
            if not _alpha(border):
                border = style.body_border
            return (0, 0, 0, 0), style.button_hover, style.button_pressed, border, max(1, style.button_border_size)
        return (
            style.button_normal,
            style.button_hover,
            style.button_pressed,
            style.button_border,
            style.button_border_size,
        )

    def _button_rounding(self):
        style = self.visual_style
        base = self.BUTTON_ROUNDING if style.button_rounding is None else style.button_rounding
        if self.button_render_style == "raised":
            return max(3, base)
        return base

    def _button_theme(self, *, checked=False, disabled=False, compact=False):
        style = self.visual_style

        def build():
            normal, hovered, pressed, border, border_size = self._button_chrome(
                checked=checked, disabled=disabled)
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvButton, enabled_state=not disabled):
                    self.backend.add_theme_color(self.backend.mvThemeCol_Button, normal)
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_ButtonHovered,
                        normal if disabled else hovered,
                    )
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_ButtonActive,
                        normal if disabled else pressed,
                    )
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_Text,
                        style.disabled_text if disabled else style.text,
                    )
                    self.backend.add_theme_color(self.backend.mvThemeCol_Border, border)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameBorderSize, border_size)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameRounding, self._button_rounding())
                    self.backend.add_theme_style(
                        self.backend.mvStyleVar_FramePadding,
                        self.COMPACT_BUTTON_PADDING_X if compact else self.BUTTON_PADDING_X,
                        self.COMPACT_BUTTON_PADDING_Y if compact else self.BUTTON_PADDING_Y,
                    )
            return theme

        return self._cached_theme(("button", bool(checked), bool(disabled), bool(compact)), build)

    def _large_label_theme(self, *, checked=False, disabled=False):
        style = self.visual_style

        def build():
            normal, hovered, pressed, border, border_size = self._button_chrome(
                checked=checked, disabled=disabled)
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvButton, enabled_state=not disabled):
                    self.backend.add_theme_color(self.backend.mvThemeCol_Button, normal)
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_ButtonHovered,
                        normal if disabled else hovered,
                    )
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_ButtonActive,
                        normal if disabled else pressed,
                    )
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_Text,
                        style.disabled_text if disabled else style.text,
                    )
                    self.backend.add_theme_color(self.backend.mvThemeCol_Border, border)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameBorderSize, border_size)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameRounding, self._button_rounding())
                    self.backend.add_theme_style(self.backend.mvStyleVar_FramePadding, 2, 1)
            return theme

        return self._cached_theme(("large-label", bool(checked), bool(disabled)), build)

    def _image_button_theme(self, *, checked=False, disabled=False):
        def build():
            with self.backend.theme() as theme:
                component = getattr(self.backend, "mvImageButton", None)
                if component is not None:
                    for enabled_state in (True, False):
                        with self.backend.theme_component(component, enabled_state=enabled_state):
                            inactive = disabled or not enabled_state
                            normal, hovered, pressed, border, border_size = self._button_chrome(
                                checked=checked, disabled=inactive)
                            self.backend.add_theme_color(self.backend.mvThemeCol_Button, normal)
                            self.backend.add_theme_color(
                                self.backend.mvThemeCol_ButtonHovered,
                                normal if inactive else hovered,
                            )
                            self.backend.add_theme_color(
                                self.backend.mvThemeCol_ButtonActive,
                                normal if inactive else pressed,
                            )
                            self.backend.add_theme_color(self.backend.mvThemeCol_Border, border)
                            self.backend.add_theme_style(self.backend.mvStyleVar_FrameBorderSize, border_size)
                            self.backend.add_theme_style(self.backend.mvStyleVar_FrameRounding, self._button_rounding())
                            self.backend.add_theme_style(self.backend.mvStyleVar_FramePadding, 0, 0)
            return theme

        return self._cached_theme(("image-button", bool(checked), bool(disabled)), build)

    def _application_theme(self):
        style = self.visual_style

        def build():
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvButton):
                    self.backend.add_theme_color(self.backend.mvThemeCol_Button, style.application_normal)
                    self.backend.add_theme_color(self.backend.mvThemeCol_ButtonHovered, style.application_hover)
                    self.backend.add_theme_color(self.backend.mvThemeCol_ButtonActive, style.application_pressed)
                    self.backend.add_theme_color(self.backend.mvThemeCol_Text, style.application_text)
                    self.backend.add_theme_color(self.backend.mvThemeCol_Border, style.application_border)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameBorderSize, style.application_border_size)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameRounding, self._button_rounding())
                    self.backend.add_theme_style(self.backend.mvStyleVar_FramePadding, 4, 2)
            return theme

        return self._cached_theme(("application",), build)

    def _text_theme(self, *, muted=False):
        style = self.visual_style

        def build():
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvText):
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_Text,
                        style.muted_text if muted else style.text,
                    )
            return theme

        return self._cached_theme(("text", bool(muted)), build)


__all__ = ["RibbonThemeFactory"]
