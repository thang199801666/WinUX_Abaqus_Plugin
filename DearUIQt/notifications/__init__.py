"""Reusable desktop notification primitives for DearUIQt.

The package is inert until a caller explicitly constructs/configures a manager.
This makes it safe to ship before an application adopts notifications.
"""
from importlib import import_module

_LAZY_EXPORTS = {
    "NotificationKind": ".model",
    "DismissReason": ".model",
    "QNotificationAction": ".model",
    "QNotificationRequest": ".model",
    "QNotificationEntry": ".model",
    "QNotificationTheme": ".theme",
    "WorkArea": ".placement",
    "monitor_work_area": ".placement",
    "stack_positions": ".placement",
    "QNotificationRecord": ".center",
    "QNotificationCenter": ".center",
    "WindowsToastWindow": ".native_windows",
    "WindowsToastHost": ".native_windows",
    "QNotificationManager": ".manager",
    "QNotification": ".facade",
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
