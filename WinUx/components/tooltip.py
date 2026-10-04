"""Shared polished tooltip styling for WinUX controls."""

from __future__ import annotations

import dearpygui.dearpygui as dpg

from .qt_style import QtFusionMetrics, QtFusionPalette


TOOLTIP_DELAY = 0.45
TOOLTIP_WRAP_WIDTH = 420

_TOOLTIP_THEME = None


def tooltip_theme():
    """Return a compact Qt/QToolTip-like theme."""
    global _TOOLTIP_THEME
    if _TOOLTIP_THEME is not None and dpg.does_item_exist(_TOOLTIP_THEME):
        return _TOOLTIP_THEME

    p = QtFusionPalette
    with dpg.theme() as _TOOLTIP_THEME:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, p.TOOLTIP_BG)
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, p.TOOLTIP_BG)
            dpg.add_theme_color(dpg.mvThemeCol_Text, p.TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, p.TOOLTIP_BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_Separator, p.BORDER_LIGHT)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 7, 5)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 5, 3)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, QtFusionMetrics.POPUP_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, QtFusionMetrics.POPUP_ROUNDING)
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
    return _TOOLTIP_THEME

def add_styled_tooltip(parent, text, *, delay=TOOLTIP_DELAY):
    """Attach one consistently styled text tooltip to *parent*."""
    with dpg.tooltip(
        parent,
        delay=float(delay),
        hide_on_activity=True,
    ) as tag:
        dpg.add_text(str(text), wrap=TOOLTIP_WRAP_WIDTH)
    dpg.bind_item_theme(tag, tooltip_theme())
    return tag


def reset_tooltip_runtime_resources():
    """Forget the theme tag after a Dear PyGui context is destroyed."""
    global _TOOLTIP_THEME
    _TOOLTIP_THEME = None


__all__ = [
    "TOOLTIP_DELAY",
    "TOOLTIP_WRAP_WIDTH",
    "add_styled_tooltip",
    "reset_tooltip_runtime_resources",
    "tooltip_theme",
]
