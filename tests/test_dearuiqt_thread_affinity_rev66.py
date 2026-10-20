import threading
import time
from collections import deque

from DearUIQt.QtCore import QObject, QMetaObject, QThread, QTimer, Qt, Signal


class MainScheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)

    def pump(self):
        while self.pending:
            callback, args = self.pending.popleft()
            callback(*args)


class Worker(QObject):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.value = 0
        self.calls = []
        self.changed = Signal(self)

    def setValue(self, value):
        self.value = value
        self.calls.append(threading.get_ident())
        self.changed.emit(value)


class AutoConnectOwner(QObject):
    def __init__(self):
        super().__init__()
        self.values = []
        self.child = Worker(parent=self)
        self.child.setObjectName("worker")

    def on_worker_changed(self, value):
        self.values.append(value)


def wait_for(predicate, timeout=1.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def test_qobject_tree_moves_to_qthread_and_queued_invoke_runs_on_worker():
    thread = QThread(name="dearuiqt-affinity-test")
    root = Worker()
    child = Worker(parent=root)
    thread_changes = []

    class Filter(QObject):
        def eventFilter(self, watched, event):
            if event.type() == event.ThreadChange:
                thread_changes.append(watched)
            return False

    event_filter = Filter()
    root.installEventFilter(event_filter)
    child.installEventFilter(event_filter)
    assert root.moveToThread(thread)
    assert root.thread() is thread
    assert child.thread() is thread
    assert root.threadId() == thread.affinityId()
    assert root in thread_changes and child in thread_changes

    assert QMetaObject.invokeMethod(root, "setValue", Qt.QueuedConnection, 42)
    assert thread.start()
    assert wait_for(lambda: root.value == 42)
    assert root.calls == [thread.workerThreadId()]
    thread.quit()
    assert thread.wait(1000)


def test_auto_connection_delivers_to_moved_receiver_thread():
    thread = QThread(name="dearuiqt-signal-test")
    receiver = Worker()
    receiver.moveToThread(thread)
    sender = Worker()
    sender.changed.connect(receiver.setValue, receiver=receiver)
    thread.start()
    sender.changed.emit(7)
    assert wait_for(lambda: receiver.value == 7)
    assert receiver.calls[-1] == thread.workerThreadId()
    thread.quit()
    assert thread.wait(1000)


def test_qtimer_uses_qthread_scheduler_after_move():
    thread = QThread(name="dearuiqt-timer-test")
    timer = QTimer()
    timer.moveToThread(thread)
    fired = threading.Event()
    calls = []

    def timeout():
        calls.append(threading.get_ident())
        fired.set()
        thread.quit()

    timer.timeout.connect(timeout)
    timer.setSingleShot(True) if False else None  # mutation must occur on affinity thread
    QMetaObject.invokeMethod(timer, "setSingleShot", Qt.QueuedConnection, True)
    QMetaObject.invokeMethod(timer, "start", Qt.QueuedConnection, 5)
    thread.start()
    assert fired.wait(1.0)
    assert calls == [thread.workerThreadId()] or thread.workerThreadId() is None
    assert thread.wait(1000)


def test_qmetaobject_auto_connect_slots_by_object_name():
    owner = AutoConnectOwner()
    assert QMetaObject.connectSlotsByName(owner) == 1
    owner.child.changed.emit(12)
    assert owner.values == [12]
    # Duplicate auto-connect calls are idempotent through Signal.connect.
    assert QMetaObject.connectSlotsByName(owner) == 0
    owner.child.changed.emit(13)
    assert owner.values == [12, 13]


def test_qmetaobject_queued_invoke_is_dropped_after_receiver_delete():
    thread = QThread(name="dearuiqt-delete-test")
    worker = Worker()
    worker.moveToThread(thread)
    assert QMetaObject.invokeMethod(worker, "setValue", Qt.QueuedConnection, 99)
    # Deletion before the thread starts nulls the guarded receiver.
    worker.delete()
    thread.start()
    time.sleep(0.03)
    assert worker.value == 0
    thread.quit()
    assert thread.wait(1000)


def test_qthread_callback_exception_is_isolated_and_event_loop_continues():
    thread = QThread(name="dearuiqt-exception-test")
    errors = []
    completed = threading.Event()
    thread.exceptionRaised.connect(errors.append)
    thread.after(0, lambda: (_ for _ in ()).throw(ValueError("boom")))
    thread.after(1, completed.set)
    thread.start()
    assert completed.wait(1.0)
    assert errors and isinstance(errors[0], ValueError)
    thread.quit()
    assert thread.wait(1000)


def test_dearuiqt_thread_and_metaobject_facades_remain_backend_light():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    code = (
        "import sys; from DearUIQt.QtCore import QThread, QMetaObject, QObject; "
        "assert QThread.__name__ == 'QThread'; assert QMetaObject.__name__ == 'QMetaObject'; "
        "assert QObject.__name__ == 'QObject'; assert 'dearpygui.dearpygui' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_event_filter_is_suspended_after_watched_object_moves_threads():
    thread = QThread(name="dearuiqt-filter-affinity")
    watched = Worker()
    seen = []

    class Filter(QObject):
        def eventFilter(self, obj, event):
            seen.append((obj, event.type()))
            return False

    event_filter = Filter()
    watched.installEventFilter(event_filter)
    watched.moveToThread(thread)
    # ThreadChange was delivered before the move while affinities still matched.
    before = len(seen)
    thread.start()
    QMetaObject.invokeMethod(watched, "sendEvent", Qt.QueuedConnection, __import__("DearUIQt.QtCore", fromlist=["QEvent"]).QEvent(1000))
    time.sleep(0.03)
    assert len(seen) == before
    thread.quit()
    assert thread.wait(1000)
