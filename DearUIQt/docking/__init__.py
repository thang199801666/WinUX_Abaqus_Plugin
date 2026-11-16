"""Reusable dock chrome, tab manager and target-preview primitives."""
from .dock_widget import DockWidget, DockDropPreview
from .dock_manager import DockManager
from .layout_tree import DockLayoutTree
from .window_lifecycle import QDockWindowLifecycle
from .widget_state import QDockWidgetStateController
from .tab_group import QDockTabGroupController
from .command import QDockCommand
from .main_window_commands import QMainWindowDockCommandBus
from .history import QDockCommandHistory
from .drop_target import QDockDropTargetResolver
from .preview_controller import QDockPreviewController
from .drop_controller import QDockDropController
from .transition import QDockTransition
from .commit_transaction import QDockCommitTransaction
from .float_transaction import QDockFloatTransaction

QDockWidget = DockWidget
__all__ = ["DockWidget", "QDockWidget", "DockManager", "DockLayoutTree", "DockDropPreview", "QDockWindowLifecycle", "QDockWidgetStateController", "QDockTabGroupController", "QDockCommand", "QMainWindowDockCommandBus", "QDockCommandHistory", "QDockDropTargetResolver", "QDockPreviewController", "QDockDropController", "QDockTransition", "QDockCommitTransaction", "QDockFloatTransaction"]
