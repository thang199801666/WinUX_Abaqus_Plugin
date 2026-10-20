import threading
import time

import pytest

from DearUIQt.qt.concurrent import (
    QFuture,
    QFutureWatcher,
    QThreadPool,
    QtConcurrent,
)


class UiScheduler:
    """Minimal ``after`` queue that is drained by the owning test thread."""

    def __init__(self):
        self.owner = threading.get_ident()
        self.pending = []
        self.lock = threading.Lock()

    def after(self, _delay, callback, *args):
        with self.lock:
            self.pending.append((callback, args))

    def drain(self):
        assert threading.get_ident() == self.owner
        while True:
            with self.lock:
                if not self.pending:
                    return
                callback, args = self.pending.pop(0)
            callback(*args)


def _drain_until(scheduler, predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        scheduler.drain()
        if predicate():
            return True
        time.sleep(.005)
    scheduler.drain()
    return predicate()


def test_qthreadpool_reuses_bounded_workers():
    pool = QThreadPool(maxThreadCount=3, maxPending=32, name="test-qt")
    gate = threading.Event()
    names = set()
    lock = threading.Lock()

    def job(value):
        gate.wait(1)
        with lock:
            names.add(threading.current_thread().name)
        return value * 2

    futures = [pool.start(job, index) for index in range(12)]
    gate.set()
    assert [future.result(2) for future in futures] == [index * 2 for index in range(12)]
    assert 1 <= len(names) <= 3
    assert all(name.startswith("test-qt-") for name in names)
    assert pool.waitForDone(2)
    pool.close(wait=True)


def test_qthreadpool_does_not_strand_second_job_in_dequeue_active_gap(monkeypatch):
    """A blocking reader must never strand its paired writer in the queue.

    Reproduce the exact floating-dialog race: worker #1 has already dequeued
    the reader but has not incremented ``_active`` when the writer is submitted.
    The pool must still see two unfinished jobs and start worker #2.
    """
    pool = QThreadPool(maxThreadCount=2, maxPending=8, name="dequeue-gap")
    first_begin_entered = threading.Event()
    release_first_begin = threading.Event()
    second_ran = threading.Event()
    begin_lock = threading.Lock()
    first_call = {"pending": True}
    original_begin = QFuture._begin

    def gated_begin(future):
        should_block = False
        with begin_lock:
            if first_call["pending"]:
                first_call["pending"] = False
                should_block = True
        if should_block:
            first_begin_entered.set()
            assert release_first_begin.wait(2)
        return original_begin(future)

    monkeypatch.setattr(QFuture, "_begin", gated_begin)
    first = pool.start(lambda: None)
    assert first_begin_entered.wait(2)

    second = pool.start(lambda: second_ran.set())
    try:
        assert second_ran.wait(1), "second job was stranded behind a dequeued blocking job"
        assert second.result(1) is None
    finally:
        release_first_begin.set()

    assert first.result(2) is None
    pool.close(wait=True)


def test_future_propagates_result_error_and_queued_cancel():
    pool = QThreadPool(maxThreadCount=1, maxPending=8, name="future-test")
    blocker = threading.Event()
    first = pool.start(lambda: blocker.wait(1))
    cancelled = pool.start(lambda: 99)
    assert cancelled.cancel()
    blocker.set()
    assert first.result(2) is True
    with pytest.raises(Exception) as cancelled_error:
        cancelled.result(2)
    assert cancelled_error.type.__name__ == "CancelledError"

    def fail():
        raise ValueError("boom")

    failed = pool.start(fail)
    with pytest.raises(ValueError, match="boom"):
        failed.result(2)
    pool.close(wait=True)


def test_future_watcher_marshals_terminal_signal_once_to_ui_thread():
    pool = QThreadPool(maxThreadCount=1, maxPending=8, name="watcher-test")
    scheduler = UiScheduler()
    future = pool.start(lambda: 42)
    # Intentionally allow the tiny job to finish before watcher attachment;
    # this exercises the finished-vs-snapshot race fixed by the watcher.
    assert future.waitForFinished(2)

    watcher = QFutureWatcher(after=scheduler.after)
    events = []
    watcher.resultReady.connect(lambda value: events.append(("result", value, threading.get_ident())))
    watcher.finished.connect(lambda: events.append(("finished", None, threading.get_ident())))
    watcher.setFuture(future)

    assert _drain_until(scheduler, lambda: len(events) >= 2)
    scheduler.drain()
    assert events == [
        ("result", 42, scheduler.owner),
        ("finished", None, scheduler.owner),
    ]
    pool.close(wait=True)


def test_qtconcurrent_uses_explicit_pool():
    pool = QThreadPool(maxThreadCount=1, maxPending=4, name="explicit")
    future = QtConcurrent.run(lambda left, right: left + right, 20, 22, pool=pool)
    assert future.result(2) == 42
    pool.close(wait=True)


def test_qfuture_supports_executor_style_done_callback():
    pool = QThreadPool(maxThreadCount=1, maxPending=4, name="callback")
    called = threading.Event()
    observed = []

    future = pool.start(lambda: 21 * 2)

    def completed(done):
        observed.append((done.result(), threading.current_thread().name))
        called.set()

    future.add_done_callback(completed)
    assert called.wait(2)
    assert observed[0][0] == 42
    assert observed[0][1].startswith("callback-") or observed[0][1] == threading.current_thread().name

    late = []
    future.add_done_callback(lambda done: late.append(done.result()))
    assert late == [42]
    pool.close(wait=True)
