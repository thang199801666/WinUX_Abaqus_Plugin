from collections import deque
import importlib
import sys
import threading
from pathlib import Path

from DearUIQt.dispatch import LatestCallQueue
from DearUIQt.qt.application import QApplication
from DearUIQt.qt.core import QObject, QEvent, Qt
from DearUIQt.qt.widget import QWidget


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)

    def pump(self):
        while self.pending:
            callback, args = self.pending.popleft()
            callback(*args)


class EventObject(QObject):
    def __init__(self, *args, window=False, **kwargs):
        self.events = []
        self._window = window
        super().__init__(*args, **kwargs)

    def event(self, event):
        self.events.append(event.type())
        return True

    def isWindow(self):
        return self._window


class FakeBackend:
    def __init__(self):
        self.config = {1: {"show": True}}
        self.deleted = []
        self.focused = None

    def configure_item(self, tag, **kwargs):
        self.config.setdefault(tag, {}).update(kwargs)

    def get_item_configuration(self, tag):
        return dict(self.config.get(tag, {}))

    def focus_item(self, tag):
        self.focused = tag

    def get_item_state(self, tag):
        return {"focused": self.focused == tag}

    def does_item_exist(self, tag):
        return tag not in self.deleted

    def delete_item(self, tag):
        self.deleted.append(tag)

    def get_item_parent(self, _tag):
        return 0


def test_latest_queue_batches_independent_keys_into_one_ui_wakeup():
    scheduler = Scheduler()
    queue = LatestCallQueue(scheduler.after)
    values = []
    queue.post("x", values.append, 1)
    queue.post("y", values.append, 2)
    queue.post("z", values.append, 3)
    assert len(scheduler.pending) == 1
    scheduler.pump()
    assert values == [1, 2, 3]


def test_latest_queue_reentrant_work_runs_on_next_turn():
    scheduler = Scheduler()
    queue = LatestCallQueue(scheduler.after)
    values = []

    def first():
        values.append("first")
        queue.post("again", values.append, "next")

    queue.post("first", first)
    callback, args = scheduler.pending.popleft()
    callback(*args)
    assert values == ["first"]
    assert len(scheduler.pending) == 1
    scheduler.pump()
    assert values == ["first", "next"]


def test_qapplication_compresses_layout_requests_to_one_event_loop_delivery():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        target = EventObject(after=scheduler.after)
        for _ in range(100):
            app.postEvent(target, QEvent(QEvent.LayoutRequest))
        assert len(scheduler.pending) == 1
        scheduler.pump()
        assert target.events == [QEvent.LayoutRequest]
    finally:
        app.delete()


def test_qapplication_tracks_focus_and_active_window_without_worker_thread():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        window = EventObject(after=scheduler.after, window=True)
        child = EventObject(parent=window, after=scheduler.after)
        changes = []
        app.focusChanged.connect(lambda old, new: changes.append((old, new)))
        assert app._set_focus_widget(child)
        assert app.focusWidget() is child
        assert app.activeWindow() is window
        assert QEvent.FocusIn in child.events
        assert QEvent.WindowActivate in window.events
        assert app._set_focus_widget(None)
        assert app.focusWidget() is None
        assert app.activeWindow() is None
        assert QEvent.FocusOut in child.events
        assert QEvent.WindowDeactivate in window.events
        assert len(changes) == 2
        assert all(threading.get_ident() == app.threadId() for _ in [0])
    finally:
        app.delete()


def test_qwidget_close_matches_qt_hide_vs_delete_on_close():
    scheduler = Scheduler()
    backend = FakeBackend()
    widget = QWidget(1, after=scheduler.after, backend=backend)
    assert widget.close()
    assert backend.config[1]["show"] is False
    assert backend.deleted == []

    backend.config[1]["show"] = True
    widget._properties["show"] = True
    widget.setAttribute(Qt.WA_DeleteOnClose, True)
    assert widget.close()
    # WA_DeleteOnClose uses deferred deletion, like Qt.
    assert backend.deleted == []
    scheduler.pump()
    assert backend.deleted == [1]


def test_qt_namespace_import_is_lazy_and_does_not_import_dearpygui():
    # This test protects cold-start behavior: core imports must not force menu,
    # scroller and DearPyGui modules into every dialog process.
    script = Path(__file__).resolve().parents[1] / "DearUIQt" / "qt" / "__init__.py"
    source = script.read_text(encoding="utf-8")
    assert "_LAZY_EXPORTS" in source
    assert "from .menu import" not in source
    assert "from .buttons import" not in source
