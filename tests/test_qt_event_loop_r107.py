"""Regression tests for Qt-style event-turn and pointer hot path."""
from collections import deque

from DearUIQt.core.application import QApplication
from DearUIQt.core.object import QObject, QEvent


class Scheduler:
    def __init__(self):
        self.queue = deque()

    def after(self, delay, callback, *args):
        self.queue.append((callback, args))
        return len(self.queue)

    def drain(self):
        for _ in range(30):
            if not self.queue:
                return
            callback, args = self.queue.popleft()
            callback(*args)
        raise AssertionError("event loop did not become idle")


class Receiver(QObject):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []
        self.on_event = None

    def event(self, event):
        self.events.append(event.type())
        if self.on_event:
            self.on_event()
        return True


def test_nested_processing_preserves_outer_turn_and_fifo():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        one = Receiver(after=scheduler.after)
        two = Receiver(after=scheduler.after)
        nested = []
        def on_event():
            app.postEvent(two, QEvent(QEvent.User + 3))
            nested.append(app.processEvents())
        one.on_event = on_event
        app.postEvent(one, QEvent(QEvent.User + 1))
        app.postEvent(two, QEvent(QEvent.User + 2))
        assert app.processEvents() == 2
        assert nested == [0]
        assert two.events == [QEvent.User + 2]
        scheduler.drain()
        assert two.events == [QEvent.User + 2, QEvent.User + 3]
    finally:
        app.delete()


def test_pointer_lookup_only_compacts_when_stale():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        target = Receiver(after=scheduler.after)
        target.hitTest = lambda point: True
        app.registerPointerTarget(target)
        original = app._compact_pointer_targets
        calls = []
        def spy(targets):
            calls.append(True)
            return original(targets)
        app._compact_pointer_targets = spy
        for _ in range(100):
            assert app._pointer_target_at((0, 0)) is target
        assert calls == []
        target.delete()
        assert app._pointer_target_at((0, 0)) is None
        assert not app._pointer_targets
    finally:
        app.delete()
