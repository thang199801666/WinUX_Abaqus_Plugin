"""Ribbon theme factory separated from RibbonBar behavior.

The factory receives a ribbon instance and uses its backend, sizing constants
and theme cache. Keeping theme construction here reduces RibbonBar complexity
without changing the public RibbonBar API.
"""
from __future__ import annotations

from ..gui.palette import QtFusionMetrics, QtFusionPalette


class RibbonThemeFactory:
    def __init__(self, ribbon):
        self._ribbon = ribbon

    def __getattr__(self, name):
        return getattr(self._ribbon, name)

    def _cached_theme(self, key, builder):
        theme = self._themes.get(tuple(key))
        try:
            if theme is not None and self.backend.does_item_exist(theme):
                return theme
        except Exception:
            pass
        theme = builder()
        self._themes[tuple(key)] = theme
        return theme

    def _surface_theme(self, kind):
        p = QtFusionPalette

        def build():
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvChildWindow):
                    if kind == "separator":
                        bg = p.BORDER_LIGHT
                    elif kind in ("root", "quick", "tabs"):
                        bg = p.WINDOW
                    else:
                        bg = p.BASE
                    self.backend.add_theme_color(self.backend.mvThemeCol_ChildBg, bg)
                    if kind == "body":
                        border = p.BORDER_LIGHT
                    else:
                        border = (0, 0, 0, 0)
                    self.backend.add_theme_color(self.backend.mvThemeCol_Border, border)
                    if kind == "group":
                        padding = (self.GROUP_HORIZONTAL_PADDING, 2)
                    elif kind == "separator":
                        padding = (0, 8)
                    elif kind in ("body", "page"):
                        padding = (2, 2)
                    else:
                        padding = (self.CONTROLS_HORIZONTAL_PADDING, 1)
                    self.backend.add_theme_style(self.backend.mvStyleVar_WindowPadding, *padding)
                    self.backend.add_theme_style(self.backend.mvStyleVar_ItemSpacing, 2, 1)
                    self.backend.add_theme_style(
                        self.backend.mvStyleVar_ChildBorderSize,
                        1 if kind == "body" else 0,
                    )
                    self.backend.add_theme_style(self.backend.mvStyleVar_ChildRounding, 0)
            return theme

        return self._cached_theme(("surface", kind), build)

    def _tab_theme(self, active):
        p = QtFusionPalette

        def build():
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvButton):
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_Button,
                        p.BASE if active else (0, 0, 0, 0),
                    )
                    self.backend.add_theme_color(self.backend.mvThemeCol_ButtonHovered, p.BUTTON_HOVER)
                    self.backend.add_theme_color(self.backend.mvThemeCol_ButtonActive, p.BUTTON_ACTIVE)
                    self.backend.add_theme_color(self.backend.mvThemeCol_Text, p.TEXT)
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_Border,
                        (214, 112, 28, 255) if active else (0, 0, 0, 0),
                    )
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameBorderSize, 1 if active else 0)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameRounding, QtFusionMetrics.BUTTON_ROUNDING)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FramePadding, 8, 3)
            return theme

        return self._cached_theme(("tab", bool(active)), build)

    def _button_theme(self, *, checked=False, disabled=False, compact=False):
        p = QtFusionPalette

        def build():
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvButton, enabled_state=not disabled):
                    normal = p.HIGHLIGHT_SOFT if checked and not disabled else (0, 0, 0, 0)
                    self.backend.add_theme_color(self.backend.mvThemeCol_Button, normal)
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_ButtonHovered,
                        normal if disabled else p.BUTTON_HOVER,
                    )
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_ButtonActive,
                        normal if disabled else p.BUTTON_ACTIVE,
                    )
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_Text,
                        p.TEXT_DISABLED if disabled else p.TEXT,
                    )
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_Border,
                        p.BORDER if checked and not disabled else (0, 0, 0, 0),
                    )
                    self.backend.add_theme_style(
                        self.backend.mvStyleVar_FrameBorderSize,
                        1 if checked and not disabled else 0,
                    )
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameRounding, QtFusionMetrics.BUTTON_ROUNDING)
                    self.backend.add_theme_style(
                        self.backend.mvStyleVar_FramePadding,
                        3 if compact else 5,
                        1 if compact else 3,
                    )
            return theme

        return self._cached_theme(("button", bool(checked), bool(disabled), bool(compact)), build)

    def _large_label_theme(self, *, checked=False, disabled=False):
        p = QtFusionPalette

        def build():
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvButton, enabled_state=not disabled):
                    normal = p.HIGHLIGHT_SOFT if checked and not disabled else (0, 0, 0, 0)
                    self.backend.add_theme_color(self.backend.mvThemeCol_Button, normal)
                    self.backend.add_theme_color(self.backend.mvThemeCol_ButtonHovered,
                                                 normal if disabled else p.BUTTON_HOVER)
                    self.backend.add_theme_color(self.backend.mvThemeCol_ButtonActive,
                                                 normal if disabled else p.BUTTON_ACTIVE)
                    self.backend.add_theme_color(self.backend.mvThemeCol_Text,
                                                 p.TEXT_DISABLED if disabled else p.TEXT)
                    self.backend.add_theme_color(self.backend.mvThemeCol_Border, (0, 0, 0, 0))
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameBorderSize, 0)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameRounding, QtFusionMetrics.BUTTON_ROUNDING)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FramePadding, 2, 1)
            return theme

        return self._cached_theme(("large-label", bool(checked), bool(disabled)), build)

    def _image_button_theme(self, *, checked=False, disabled=False):
        p = QtFusionPalette

        def build():
            with self.backend.theme() as theme:
                component = getattr(self.backend, "mvImageButton", None)
                if component is not None:
                    # ImageButton width/height size the image, unlike Button's
                    # outer rectangle. Zero frame padding makes the declared
                    # tile size its actual hit target in both native states.
                    for enabled_state in (True, False):
                        with self.backend.theme_component(component, enabled_state=enabled_state):
                            inactive = disabled or not enabled_state
                            normal = p.HIGHLIGHT_SOFT if checked and not inactive else (0, 0, 0, 0)
                            self.backend.add_theme_color(self.backend.mvThemeCol_Button, normal)
                            self.backend.add_theme_color(
                                self.backend.mvThemeCol_ButtonHovered, normal if inactive else p.BUTTON_HOVER)
                            self.backend.add_theme_color(
                                self.backend.mvThemeCol_ButtonActive, normal if inactive else p.BUTTON_ACTIVE)
                            self.backend.add_theme_color(
                                self.backend.mvThemeCol_Border, p.BORDER if checked and not inactive else (0, 0, 0, 0))
                            self.backend.add_theme_style(self.backend.mvStyleVar_FrameBorderSize, 1 if checked and not inactive else 0)
                            self.backend.add_theme_style(self.backend.mvStyleVar_FrameRounding, QtFusionMetrics.BUTTON_ROUNDING)
                            self.backend.add_theme_style(self.backend.mvStyleVar_FramePadding, 0, 0)
            return theme

        return self._cached_theme(("image-button", bool(checked), bool(disabled)), build)

    def _application_theme(self):
        p = QtFusionPalette

        def build():
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvButton):
                    self.backend.add_theme_color(self.backend.mvThemeCol_Button, (214, 112, 28, 255))
                    self.backend.add_theme_color(self.backend.mvThemeCol_ButtonHovered, (229, 132, 42, 255))
                    self.backend.add_theme_color(self.backend.mvThemeCol_ButtonActive, (190, 92, 18, 255))
                    self.backend.add_theme_color(self.backend.mvThemeCol_Text, (255, 255, 255, 255))
                    self.backend.add_theme_color(self.backend.mvThemeCol_Border, p.BORDER)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameBorderSize, 1)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FrameRounding, QtFusionMetrics.BUTTON_ROUNDING)
                    self.backend.add_theme_style(self.backend.mvStyleVar_FramePadding, 4, 2)
            return theme

        return self._cached_theme(("application",), build)

    def _text_theme(self, *, muted=False):
        p = QtFusionPalette

        def build():
            with self.backend.theme() as theme:
                with self.backend.theme_component(self.backend.mvText):
                    self.backend.add_theme_color(
                        self.backend.mvThemeCol_Text,
                        p.TEXT_MUTED if muted else p.TEXT,
                    )
            return theme

        return self._cached_theme(("text", bool(muted)), build)


__all__ = ["RibbonThemeFactory"]
