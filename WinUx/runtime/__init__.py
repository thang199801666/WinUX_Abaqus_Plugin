"""Small runtime primitives with dependency-safe lazy exports.

Importing :mod:`WinUx.runtime` is part of the main controller/view startup path.
Keep the package initializer free of eager submodule imports so the application
loads only the runtime primitives it actually needs for the first frame.
"""
from __future__ import annotations

from importlib import import_module

_LAZY_RUNTIME = {
    "UIHangWatchdog": (".hang_watchdog", "UIHangWatchdog"),
    "BackgroundTaskHandle": (".task_manager", "BackgroundTaskHandle"),
    "BackgroundTaskManager": (".task_manager", "BackgroundTaskManager"),
    "hide_registered_process_windows": (".child_processes", "hide_registered_process_windows"),
    "register_child_process": (".child_processes", "register_child_process"),
    "registered_child_pids": (".child_processes", "registered_child_pids"),
    "terminate_registered_children": (".child_processes", "terminate_registered_children"),
    "unregister_child_process": (".child_processes", "unregister_child_process"),
    "BoundedTextBuffer": (".text_buffer", "BoundedTextBuffer"),
    "UiDispatcher": (".ui_dispatcher", "UiDispatcher"),
}

__all__ = list(_LAZY_RUNTIME)


def __getattr__(name):
    target = _LAZY_RUNTIME.get(name)
    if target is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
