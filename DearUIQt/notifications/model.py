"""Pure notification data models.

This module intentionally has no renderer or Win32 imports.  Applications may
construct notification requests on worker threads and hand them to a UI-side
manager later.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import itertools
import time


class NotificationKind(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class DismissReason(str, Enum):
    TIMEOUT = "timeout"
    CLOSE = "close"
    CLICK = "click"
    REPLACED = "replaced"
    PROGRAMMATIC = "programmatic"
    SHUTDOWN = "shutdown"


_ids = itertools.count(1)


def _new_id():
    return "toast-{}-{}".format(int(time.time() * 1000), next(_ids))


@dataclass(frozen=True)
class QNotificationAction:
    """One optional notification action.

    The native toast host currently exposes the primary/body action.  Named
    actions are retained in the model now so a richer renderer can add buttons
    without changing the public request contract.
    """

    text: str
    callback: object = None
    action_id: str = ""

    def invoke(self):
        if callable(self.callback):
            return self.callback()
        return None


@dataclass(frozen=True)
class QNotificationRequest:
    title: str
    message: str = ""
    kind: NotificationKind = NotificationKind.INFO
    timeout_ms: int = 5000
    notification_id: str = field(default_factory=_new_id)
    source: str = ""
    dedupe_key: str = ""
    persistent: bool = False
    on_click: object = None
    on_dismiss: object = None
    actions: tuple = field(default_factory=tuple)
    created_monotonic: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        object.__setattr__(self, "title", str(self.title or ""))
        object.__setattr__(self, "message", str(self.message or ""))
        object.__setattr__(self, "source", str(self.source or ""))
        object.__setattr__(self, "dedupe_key", str(self.dedupe_key or ""))
        try:
            kind = self.kind if isinstance(self.kind, NotificationKind) else NotificationKind(str(self.kind))
        except Exception:
            kind = NotificationKind.INFO
        object.__setattr__(self, "kind", kind)
        timeout = max(0, int(self.timeout_ms or 0))
        object.__setattr__(self, "timeout_ms", timeout)
        object.__setattr__(self, "actions", tuple(self.actions or ()))

    def updated(self, **changes):
        return replace(self, **changes)


@dataclass
class QNotificationEntry:
    """Mutable manager-side state for one visible/queued request."""

    request: QNotificationRequest
    window: object = None
    shown_monotonic: float = 0.0
    deadline_monotonic: float = 0.0
    remaining_ms: int = 0
    timer_token: object = None
    hovered: bool = False
    visible: bool = False


__all__ = [
    "NotificationKind", "DismissReason", "QNotificationAction",
    "QNotificationRequest", "QNotificationEntry",
]
