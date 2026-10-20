from collections import deque

from DearUIQt.dispatch import LatestCallQueue
from DearUIQt.qt.application import QApplication
from DearUIQt.qt.core import QObject, QEvent
from DearUIQt.qt.timer import QTimer
from DearUIQt.runtime import StandaloneUiHost


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)

    def pump_one(self):
        callback, args = self.pending.popleft()
        return callback(*args)

    def pump(self):
        while self.pending:
            self.pump_one()


class Receiver(QObject):
    def __init__(self, *args, **kwargs):
        self.events = []
        super().__init__(*args, **kwargs)

    def event(self, event):
        self.events.append(event.type())
        return super().event(event) or True


def test_bounded_application_turn_keeps_tail_compression_key():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        busy = Receiver(after=scheduler.after)
        tail = Receiver(after=scheduler.after)
        for index in range(app._posted_event_budget):
            app.postEvent(busy, QEvent(QEvent.User + index))
        app.postEvent(tail, QEvent(QEvent.DeferredDelete))

        # Drain only the bounded prefix. The deferred-delete tail should remain
        # under its stable compression key rather than being reinserted under a
        # fresh object identity.
        assert app.processEvents(max_events=app._posted_event_budget) == app._posted_event_budget
        assert len(app._posted) == 1
        app.postEvent(tail, QEvent(QEvent.DeferredDelete))
        assert len(app._posted) == 1
        assert (id(tail), QEvent.DeferredDelete) in app._posted
    finally:
        app.delete()


def test_layout_coalescing_uses_qobject_tree_semantics_for_wide_siblings():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        parent = Receiver(after=scheduler.after)
        children = [Receiver(parent=parent, after=scheduler.after) for _ in range(64)]
        for child in children:
            app.postEvent(child, QEvent(QEvent.LayoutRequest))
        assert len(app._posted) == len(children)

        # A parent invalidation supersedes all pending descendant layout passes.
        app.postEvent(parent, QEvent(QEvent.LayoutRequest))
        assert list(app._posted.values()) == [(parent, app._posted[(id(parent), QEvent.LayoutRequest)][1])]
        scheduler.pump()
        assert parent.events.count(QEvent.LayoutRequest) == 1
        assert all(QEvent.LayoutRequest not in child.events for child in children)
    finally:
        app.delete()


def test_latest_call_queue_retains_tail_and_reentrant_latest_value():
    scheduler = Scheduler()
    queue = LatestCallQueue(scheduler.after, max_batch=3)
    seen = []

    def first(value):
        seen.append(value)
        queue.post(5, seen.append, "five-new")

    queue.post(0, first, "zero")
    for index in range(1, 8):
        queue.post(index, seen.append, index)
    scheduler.pump_one()
    assert seen == ["zero", 1, 2]
    assert len(scheduler.pending) == 1
    scheduler.pump()
    assert seen == ["zero", 1, 2, 3, 4, "five-new", 6, 7]


def test_standalone_host_cancellation_releases_callback_payload_immediately():
    host = StandaloneUiHost(object())
    calls = []
    token = host.after(60_000, calls.append, "stale")
    assert token in host._scheduled_callbacks
    assert host.after_cancel(token) is True
    assert token not in host._scheduled_callbacks
    host.pump()
    assert calls == []


def test_qtimer_restart_uses_host_cancellation_when_available():
    host = StandaloneUiHost(object())
    timer = QTimer(after=host.after)
    timer.start(60_000)
    first = timer._scheduled_handle
    assert first in host._scheduled_callbacks
    timer.start(30_000)
    second = timer._scheduled_handle
    assert first not in host._scheduled_callbacks
    assert second in host._scheduled_callbacks
    timer.stop()
    assert second not in host._scheduled_callbacks
