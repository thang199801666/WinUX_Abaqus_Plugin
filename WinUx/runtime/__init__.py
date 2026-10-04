"""Small runtime primitives that do not depend on a GUI toolkit."""

from .hang_watchdog import UIHangWatchdog
from .task_manager import BackgroundTaskHandle, BackgroundTaskManager
from .child_processes import (
    hide_registered_process_windows, register_child_process,
    registered_child_pids, terminate_registered_children,
    unregister_child_process,
)
from .text_buffer import BoundedTextBuffer
from .ui_dispatcher import UiDispatcher

__all__ = [
    "BackgroundTaskHandle",
    "BackgroundTaskManager",
    "hide_registered_process_windows",
    "register_child_process",
    "registered_child_pids",
    "terminate_registered_children",
    "unregister_child_process",
    "BoundedTextBuffer",
    "UIHangWatchdog",
    "UiDispatcher",
]
