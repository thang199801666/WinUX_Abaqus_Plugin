"""Composable application UI behaviors grouped by responsibility."""
from .splitter.layout import SplitterLayoutMixin
from .docking.plot import PlotDockingMixin
from .docking.console import ConsoleDockingMixin
from .input.pointer import PointerRoutingMixin
from .window import (
    ApplicationMenuMixin, CompactJobMonitorMixin, DialogFacadeMixin,
    StartupDockingMixin, ViewLifecycleMixin,
)

__all__ = [
    "SplitterLayoutMixin",
    "PlotDockingMixin",
    "ConsoleDockingMixin",
    "PointerRoutingMixin",
    "ApplicationMenuMixin",
    "CompactJobMonitorMixin",
    "DialogFacadeMixin",
    "StartupDockingMixin",
    "ViewLifecycleMixin",
]
