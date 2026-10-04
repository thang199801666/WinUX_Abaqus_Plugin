"""Composable UI behavior used by :mod:`WinUx.view`."""

from .splitter_layout import SplitterLayoutMixin
from .plot_docking import PlotDockingMixin
from .console_docking import ConsoleDockingMixin
from .pointer_routing import PointerRoutingMixin

__all__ = [
    "SplitterLayoutMixin",
    "PlotDockingMixin",
    "ConsoleDockingMixin",
    "PointerRoutingMixin",
]
