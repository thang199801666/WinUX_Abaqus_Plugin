"""Queueing, stacking, timeout and deduplication policy for notifications."""
from __future__ import annotations

from collections import deque
import threading
import time

from .center import QNotificationCenter
from .model import (
    DismissReason, NotificationKind, QNotificationEntry, QNotificationRequest,
)
from .placement import stack_positions
from .theme import QNotificationTheme


class QNotificationManager:
    def __init__(self, *, host=None, owner_hwnd=0, theme=None, scheduler=None,
                 center=None, max_visible=4, dispatcher=None):
        self.theme = theme or QNotificationTheme()
        if host is None:
            from .native_windows import WindowsToastHost
            host = WindowsToastHost(theme=self.theme, owner_hwnd=owner_hwnd)
        self.host = host
        self.scheduler = scheduler
        self.center = center or QNotificationCenter()
        self.max_visible = max(1, int(max_visible or 1))
        self.dispatcher = dispatcher
        self._ui_thread = threading.get_ident()
        self._queue = deque()
        self._visible = []
        self._entries = {}
        self._closed = False
        host.on_hover = self._host_hover
        host.on_close = self._host_close
        host.on_click = self._host_click

    def _on_ui(self, callback, *args):
        if threading.get_ident() == self._ui_thread:
            return callback(*args)
        if callable(self.dispatcher):
            return self.dispatcher(callback, *args)
        after = getattr(self.scheduler, "after", None) if self.scheduler is not None else None
        if callable(after):
            return after(0, callback, *args)
        raise RuntimeError("worker notifications require a UI dispatcher/scheduler")

    def show(self, title=None, message="", *, kind=NotificationKind.INFO,
             timeout_ms=5000, request=None, notification_id=None, source="",
             dedupe_key="", persistent=False, on_click=None, on_dismiss=None,
             actions=()):
        if request is None:
            options = dict(
                title=title or "", message=message, kind=kind,
                timeout_ms=timeout_ms, source=source, dedupe_key=dedupe_key,
                persistent=persistent, on_click=on_click,
                on_dismiss=on_dismiss, actions=tuple(actions or ()),
            )
            if notification_id:
                options["notification_id"] = str(notification_id)
            request = QNotificationRequest(**options)
        return self._on_ui(self._show_request, request)

    def _show_request(self, request):
        if self._closed:
            return None
        key = request.dedupe_key
        if key:
            for entry in list(self._visible) + list(self._queue):
                if entry.request.dedupe_key == key:
                    # Keep the stable manager id so existing timeout/close handles
                    # remain valid while the visible content is replaced.
                    request = request.updated(notification_id=entry.request.notification_id)
                    entry.request = request
                    if entry.window is not None:
                        entry.window.update(request)
                        self._schedule_timeout(entry, reset=True)
                    return request.notification_id
        entry = QNotificationEntry(request=request, remaining_ms=request.timeout_ms)
        self._entries[request.notification_id] = entry
        self._queue.append(entry)
        self.center.append(request)
        self._fill_visible()
        return request.notification_id

    def dismiss(self, notification_id, reason=DismissReason.PROGRAMMATIC):
        return self._on_ui(self._dismiss, notification_id, reason)

    def _dismiss(self, notification_id, reason):
        entry = self._entries.pop(notification_id, None)
        if entry is None:
            return False
        self._cancel_timer(entry)
        try:
            self._queue.remove(entry)
        except ValueError:
            pass
        if entry in self._visible:
            self._visible.remove(entry)
        if entry.window is not None:
            entry.window.hide(animate=True)
            entry.window.destroy()
            entry.window = None
        entry.visible = False
        self.center.markDismissed(notification_id, reason)
        callback = entry.request.on_dismiss
        if callable(callback):
            try:
                callback(reason)
            except TypeError:
                callback()
        self._layout()
        self._fill_visible()
        return True

    def clear(self):
        for notification_id in list(self._entries):
            self._dismiss(notification_id, DismissReason.PROGRAMMATIC)

    def close(self):
        if self._closed:
            return
        for notification_id in list(self._entries):
            self._dismiss(notification_id, DismissReason.SHUTDOWN)
        self._closed = True

    def _fill_visible(self):
        while self._queue and len(self._visible) < self.max_visible:
            entry = self._queue.popleft()
            entry.window = self.host.create(entry.request)
            entry.visible = True
            entry.shown_monotonic = time.monotonic()
            self._visible.append(entry)
            self._layout()
            entry.window.show(animate=True)
            self._schedule_timeout(entry, reset=True)

    def _layout(self):
        if not self._visible:
            return
        area = self.host.workArea()
        sizes = [entry.window.size for entry in reversed(self._visible)]
        scaled = self.theme.scaled(area.dpi)
        positions = stack_positions(area, sizes, margin=scaled.margin, gap=scaled.gap)
        for entry, point in zip(reversed(self._visible), positions):
            entry.window.move(*point)

    def _cancel_timer(self, entry):
        token, entry.timer_token = entry.timer_token, None
        if token is not None and self.scheduler is not None:
            cancel = getattr(self.scheduler, "after_cancel", None)
            if callable(cancel):
                cancel(token)

    def _schedule_timeout(self, entry, reset=False):
        self._cancel_timer(entry)
        request = entry.request
        if request.persistent or request.timeout_ms <= 0 or entry.hovered:
            return
        if reset or entry.remaining_ms <= 0:
            entry.remaining_ms = request.timeout_ms
        entry.deadline_monotonic = time.monotonic() + entry.remaining_ms / 1000.0
        after = getattr(self.scheduler, "after", None) if self.scheduler is not None else None
        if callable(after):
            entry.timer_token = after(entry.remaining_ms, self._timeout, request.notification_id)

    def _timeout(self, notification_id):
        self._on_ui(self._dismiss, notification_id, DismissReason.TIMEOUT)

    def _host_hover(self, window, hovered):
        entry = self._entry_for_window(window)
        if entry is None:
            return
        entry.hovered = bool(hovered)
        if hovered:
            if entry.deadline_monotonic:
                entry.remaining_ms = max(1, int((entry.deadline_monotonic - time.monotonic()) * 1000))
            self._cancel_timer(entry)
        else:
            self._schedule_timeout(entry, reset=False)

    def _host_close(self, window):
        entry = self._entry_for_window(window)
        if entry is not None:
            self._dismiss(entry.request.notification_id, DismissReason.CLOSE)

    def _host_click(self, window):
        entry = self._entry_for_window(window)
        if entry is None:
            return
        callback = entry.request.on_click
        if callable(callback):
            callback()
        self._dismiss(entry.request.notification_id, DismissReason.CLICK)

    def _entry_for_window(self, window):
        for entry in self._visible:
            if entry.window is window:
                return entry
        return None


    def pump(self, message_limit=64):
        """Process native toast messages and scheduler-free timeouts.

        Applications that inject their own ``after`` scheduler do not need the
        deadline part of this method, but may still call it when the native host
        is not already serviced by their Windows message loop.  Standalone users
        can call ``pump`` once per frame/tick and get a completely thread-free
        notification subsystem.
        """
        if threading.get_ident() != self._ui_thread:
            raise RuntimeError("notification pump must run on the manager UI thread")
        pump = getattr(self.host, "pumpMessages", None)
        processed = pump(message_limit) if callable(pump) else 0
        if self.scheduler is None:
            now = time.monotonic()
            expired = [
                entry.request.notification_id for entry in tuple(self._visible)
                if (not entry.hovered and entry.deadline_monotonic
                    and entry.deadline_monotonic <= now)
            ]
            for notification_id in expired:
                self._dismiss(notification_id, DismissReason.TIMEOUT)
        return processed

    def visibleRequests(self):
        return tuple(entry.request for entry in self._visible)

    def queuedRequests(self):
        return tuple(entry.request for entry in self._queue)


__all__ = ["QNotificationManager"]
