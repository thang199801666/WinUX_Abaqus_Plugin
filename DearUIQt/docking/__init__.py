"""Reusable dock chrome, tab manager and target-preview primitives."""
from .dock_widget import DockWidget, DockDropPreview
from .dock_manager import DockManager
from .layout_tree import DockLayoutTree

QDockWidget = DockWidget
__all__ = ["DockWidget", "QDockWidget", "DockManager", "DockLayoutTree", "DockDropPreview"]
