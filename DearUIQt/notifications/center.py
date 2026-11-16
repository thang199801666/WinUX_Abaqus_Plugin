"""Bounded in-memory notification history; no application wiring."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class QNotificationRecord:
    request: object
    dismissed_reason: object = None
    dismissed_monotonic: float = 0.0
    read: bool = False


class QNotificationCenter:
    def __init__(self, capacity=100):
        self.capacity = max(1, int(capacity or 1))
        self._records = deque(maxlen=self.capacity)

    def append(self, request):
        self._records.appendleft(QNotificationRecord(request=request))
        return request

    def markDismissed(self, notification_id, reason=None):
        changed = False
        updated = deque(maxlen=self.capacity)
        now = time.monotonic()
        for record in self._records:
            request = getattr(record, "request", None)
            if getattr(request, "notification_id", None) == notification_id:
                record = QNotificationRecord(
                    request=request, dismissed_reason=reason,
                    dismissed_monotonic=now, read=record.read)
                changed = True
            updated.append(record)
        self._records = updated
        return changed

    def markRead(self, notification_id=None):
        updated = deque(maxlen=self.capacity)
        changed = False
        for record in self._records:
            request = getattr(record, "request", None)
            match = notification_id is None or getattr(request, "notification_id", None) == notification_id
            if match and not record.read:
                record = QNotificationRecord(
                    request=request, dismissed_reason=record.dismissed_reason,
                    dismissed_monotonic=record.dismissed_monotonic, read=True)
                changed = True
            updated.append(record)
        self._records = updated
        return changed

    def unreadCount(self):
        return sum(1 for record in self._records if not record.read)

    def records(self):
        return tuple(self._records)

    def clear(self):
        self._records.clear()


__all__ = ["QNotificationRecord", "QNotificationCenter"]
