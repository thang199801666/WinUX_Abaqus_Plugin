"""Composable application UI behaviors built on the canonical WinUx UI kit."""
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
