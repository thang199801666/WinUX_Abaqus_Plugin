"""Dear PyGui integration helpers.

This module is the explicit backend-specific escape hatch for host applications
that need native geometry/scroller utilities.  General application code should
prefer :mod:`DearUIQt.core`, :mod:`DearUIQt.gui`, :mod:`DearUIQt.widgets`, and
:mod:`DearUIQt.layouts`.
"""
from .dearpygui_scroller import (
    SharedScrollerMetrics,
    SharedScrollerPalette,
    DpgScrollerArrowOverlay,
    QScroller,
    dpg_window_rect,
    add_dpg_scroller_style,
    configure_ttk_scroller_styles,
    make_ttk_scroller,
    ttk_scroller_style_name,
)

# Public Qt-style aliases.  Backend-specific implementation stays private to
# DearUIQt while application code imports these from ``DearUIQt.widgets``.
QScrollerMetrics = SharedScrollerMetrics
QScrollerArrowOverlay = DpgScrollerArrowOverlay

__all__ = [
    "SharedScrollerMetrics", "SharedScrollerPalette",
    "DpgScrollerArrowOverlay", "QScroller", "QScrollerMetrics", "QScrollerArrowOverlay", "dpg_window_rect",
    "add_dpg_scroller_style", "configure_ttk_scroller_styles",
    "make_ttk_scroller", "ttk_scroller_style_name",
]
