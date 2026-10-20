"""Shared polished tooltip styling for DearUIQt controls."""

from __future__ import annotations

from .backends import dpg

from .gui.palette import QtFusionMetrics, QtFusionPalette


TOOLTIP_DELAY = 0.45
TOOLTIP_WRAP_WIDTH = 420

_TOOLTIP_THEME = None
_TOOLTIP_THEME_BACKEND = None


def tooltip_theme(*, backend=None):
    """Return a compact Qt/QToolTip-like theme."""
    global _TOOLTIP_THEME, _TOOLTIP_THEME_BACKEND
    backend = dpg if backend is None else backend
    if (_TOOLTIP_THEME_BACKEND is backend and _TOOLTIP_THEME is not None
            and backend.does_item_exist(_TOOLTIP_THEME)):
        return _TOOLTIP_THEME

    p = QtFusionPalette
    with backend.theme() as _TOOLTIP_THEME:
        with backend.theme_component(backend.mvAll):
            backend.add_theme_color(backend.mvThemeCol_WindowBg, p.TOOLTIP_BG)
            backend.add_theme_color(backend.mvThemeCol_PopupBg, p.TOOLTIP_BG)
            backend.add_theme_color(backend.mvThemeCol_Text, p.TEXT)
            backend.add_theme_color(backend.mvThemeCol_Border, p.TOOLTIP_BORDER)
            backend.add_theme_color(backend.mvThemeCol_Separator, p.BORDER_LIGHT)
            backend.add_theme_style(backend.mvStyleVar_WindowPadding, 7, 5)
            backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 5, 3)
            backend.add_theme_style(backend.mvStyleVar_WindowRounding, QtFusionMetrics.POPUP_ROUNDING)
            backend.add_theme_style(backend.mvStyleVar_PopupRounding, QtFusionMetrics.POPUP_ROUNDING)
            backend.add_theme_style(backend.mvStyleVar_WindowBorderSize, 1)
    _TOOLTIP_THEME_BACKEND = backend
    return _TOOLTIP_THEME

def add_styled_tooltip(parent, text, *, delay=TOOLTIP_DELAY, backend=None):
    """Attach one consistently styled text tooltip to *parent*."""
    backend = dpg if backend is None else backend
    with backend.tooltip(
        parent,
        delay=float(delay),
        hide_on_activity=True,
    ) as tag:
        backend.add_text(str(text), wrap=TOOLTIP_WRAP_WIDTH)
    backend.bind_item_theme(tag, tooltip_theme(backend=backend))
    return tag


def reset_tooltip_runtime_resources():
    """Forget the theme tag after a Dear PyGui context is destroyed."""
    global _TOOLTIP_THEME, _TOOLTIP_THEME_BACKEND
    _TOOLTIP_THEME = None
    _TOOLTIP_THEME_BACKEND = None


__all__ = [
    "TOOLTIP_DELAY",
    "TOOLTIP_WRAP_WIDTH",
    "add_styled_tooltip",
    "reset_tooltip_runtime_resources",
    "tooltip_theme",
]
