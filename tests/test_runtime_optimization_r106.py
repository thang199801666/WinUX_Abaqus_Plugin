from collections import deque
import queue

from DearUIQt.core.application import QApplication
from DearUIQt.core.object import QObject, QEvent, Qt
from DearUIQt.modelview import QTableWidget, QTableWidgetItem
from WinUx.runtime.ui_dispatcher import UiDispatcher
from tests.test_dearuiqt_modelview_r79 import FakeBackend


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)


def test_recursive_delete_purges_application_state_once_for_whole_subtree():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        root = QObject(after=scheduler.after)
        children = [QObject(parent=root, after=scheduler.after) for _ in range(250)]
        for child in children:
            app.postEvent(child, QEvent(QEvent.KeyPress))
            app.queueNativeUpdate(child, {"show": False})

        calls = []
        original = app._purge_object_subtree_state

        def counted(target):
            calls.append(target)
            return original(target)

        app._purge_object_subtree_state = counted
        root.delete()

        assert calls == [root]
        assert not app._posted
        assert not app._native_updates
        assert all(child._deleted for child in children)
    finally:
        app.delete()


def test_qtablewidgetitem_uses_compact_hot_role_storage():
    item = QTableWidgetItem("12.5")
    assert not hasattr(item, "__dict__")
    assert item._extra_data is None
    assert item.text() == "12.5"
    assert item.data(Qt.DisplayRole) == "12.5"
    assert item.data(Qt.EditRole) == "12.5"

    item.setData(Qt.EditRole, None)
    assert item.text() == ""
    assert item.data(Qt.EditRole) is None

    item.setToolTip("value")
    assert item.toolTip() == "value"
    assert item._extra_data == {Qt.ToolTipRole: "value"}


def test_default_enabled_table_items_do_not_emit_redundant_native_configure():
    class CountingBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.configure_calls = []

        def configure_item(self, tag, **kwargs):
            self.configure_calls.append((tag, dict(kwargs)))
            return super().configure_item(tag, **kwargs)

    backend = CountingBackend()
    table = QTableWidget(1, 1, backend=backend)
    backend.configure_calls.clear()
    item = QTableWidgetItem("value")
    table.setItem(0, 0, item)
    assert backend.configure_calls == []

    item.setFlags(Qt.ItemIsSelectable)
    assert backend.configure_calls == [(table.nativeItem(0, 0), {"enabled": False})]


def test_ui_dispatcher_uses_lightweight_unbounded_mpsc_queue():
    dispatcher = UiDispatcher()
    try:
        assert isinstance(dispatcher.queue, queue.SimpleQueue)
        values = []
        for value in range(32):
            dispatcher.after(0, values.append, value)
        assert dispatcher.drain(max_callbacks=7) == 7
        assert values == list(range(7))
        dispatcher.drain()
        assert values == list(range(32))
    finally:
        dispatcher.close()


def test_background_manager_close_releases_pending_closures_and_stops_idle_workers():
    import threading
    from WinUx.runtime.task_manager import BackgroundTaskManager

    manager = BackgroundTaskManager(max_workers=1, max_pending=8, name="r106-close")
    release = threading.Event()
    started = threading.Event()

    def blocking():
        started.set()
        release.wait(1.0)

    running = manager.submit("running", blocking)
    assert started.wait(0.5)
    pending = [manager.submit("pending-{}".format(i), lambda: None) for i in range(6)]

    manager.close(cancel_pending=True)
    assert all(handle.done and handle.state == "cancelled" for handle in pending)
    assert manager.snapshot()["queue_size"] == 1  # one sentinel for the worker

    release.set()
    manager._workers[0].join(0.5)
    assert not manager._workers[0].is_alive()
    assert running.done
