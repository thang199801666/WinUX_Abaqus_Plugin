"""Optional convenience facade with no implicit manager construction."""
from __future__ import annotations

from .model import NotificationKind


class QNotification:
    """Qt-style convenience API.

    ``configure(manager)`` is intentionally explicit. Importing DearUIQt or this
    module never creates native windows, worker threads, timers or hooks.
    """

    _manager = None

    @classmethod
    def configure(cls, manager):
        previous = cls._manager
        cls._manager = manager
        return previous

    @classmethod
    def manager(cls):
        return cls._manager

    @classmethod
    def _show(cls, kind, title, message="", **options):
        if cls._manager is None:
            raise RuntimeError("QNotification has no configured QNotificationManager")
        return cls._manager.show(title, message, kind=kind, **options)

    @classmethod
    def info(cls, title, message="", **options):
        return cls._show(NotificationKind.INFO, title, message, **options)

    @classmethod
    def success(cls, title, message="", **options):
        return cls._show(NotificationKind.SUCCESS, title, message, **options)

    @classmethod
    def warning(cls, title, message="", **options):
        return cls._show(NotificationKind.WARNING, title, message, **options)

    @classmethod
    def error(cls, title, message="", **options):
        return cls._show(NotificationKind.ERROR, title, message, **options)


__all__ = ["QNotification"]
