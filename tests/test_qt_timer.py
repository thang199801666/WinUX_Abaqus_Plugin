import heapq
import itertools
import threading

import pytest

from DearUIQt.qt import QObject, QTimer


class Scheduler:
    def __init__(self):
        self.time = 0
        self.jobs = []
        self.sequence = itertools.count()

    def after(self, delay, callback, *args):
        heapq.heappush(self.jobs, (self.time + delay, next(self.sequence), callback, args))

    def advance(self, milliseconds):
        self.time += milliseconds
        while self.jobs and self.jobs[0][0] <= self.time:
            _, _, callback, args = heapq.heappop(self.jobs)
            callback(*args)


def test_repeating_timer_uses_ui_scheduler_without_extra_threads():
    scheduler = Scheduler()
    parent = QObject(after=scheduler.after)
    timer = QTimer(parent)
    calls = []
    timer.timeout.connect(lambda: calls.append(threading.get_ident()))
    timer.start(100)
    scheduler.advance(99)
    assert not calls
    scheduler.advance(1)
    scheduler.advance(100)
    assert calls == [threading.get_ident()] * 2
    assert timer.isActive() and timer.interval() == 100
    parent.delete()
    scheduler.advance(1000)
    assert len(calls) == 2 and not timer.isActive()


def test_stop_and_restart_invalidate_already_queued_ticks():
    scheduler = Scheduler()
    timer = QTimer(after=scheduler.after)
    calls = []
    timer.timeout.connect(lambda: calls.append(scheduler.time))
    timer.start(100)
    timer.stop()
    timer.start(200)
    scheduler.advance(100)
    assert not calls
    scheduler.advance(100)
    assert calls == [200]


def test_single_shot_is_inactive_before_callback_and_can_restart():
    scheduler = Scheduler()
    timer = QTimer(after=scheduler.after)
    timer.setSingleShot(True)
    calls = []

    def timeout():
        calls.append(timer.isActive())
        if len(calls) == 1:
            timer.start(10)

    timer.timeout.connect(timeout)
    timer.start(10)
    scheduler.advance(10)
    scheduler.advance(10)
    scheduler.advance(100)
    assert calls == [False, False]


def test_changing_interval_restarts_active_timer_without_duplicate_callbacks():
    scheduler = Scheduler()
    timer = QTimer(after=scheduler.after)
    calls = []
    timer.timeout.connect(lambda: calls.append(scheduler.time))
    timer.start(100)
    timer.setInterval(200)
    scheduler.advance(100)
    assert not calls
    scheduler.advance(100)
    assert calls == [200]


def test_zero_timer_yields_instead_of_spinning_in_the_same_drain():
    scheduler = Scheduler()
    timer = QTimer(after=scheduler.after)
    calls = []
    timer.timeout.connect(lambda: calls.append(True))
    timer.start(0)
    scheduler.advance(0)
    assert not calls
    scheduler.advance(1)
    assert calls == [True]


@pytest.mark.parametrize("value", [-1, True, 0.5, "100", None])
def test_invalid_intervals_do_not_start_timer(value):
    timer = QTimer(after=Scheduler().after)
    with pytest.raises(ValueError):
        timer.setInterval(value)
    assert not timer.isActive()


def test_timer_requires_scheduler_and_owner_thread():
    timer = QTimer()
    with pytest.raises(RuntimeError):
        timer.start(100)
    scheduler = Scheduler()
    timer = QTimer(after=scheduler.after)
    failures = []

    def start():
        try:
            timer.start(10)
        except RuntimeError:
            failures.append(True)

    worker = threading.Thread(target=start)
    worker.start()
    worker.join()
    assert failures == [True] and not scheduler.jobs


def test_dialog_timer_factory_is_owned_and_invalid_configuration_does_not_leak():
    from WinUx.dialogs.qt_dialog import QtDialog
    scheduler = Scheduler()
    dialog = object.__new__(QtDialog)
    dialog._widget_owner = QObject(after=scheduler.after)
    dialog.winfo_exists = lambda: True
    calls = []
    timer = dialog.create_timer(10, lambda: calls.append(True))
    assert timer.parent is dialog._widget_owner
    scheduler.advance(10)
    assert calls == [True]
    with pytest.raises(TypeError):
        dialog.create_timer(10, None)
    assert dialog._widget_owner.children() == [timer]
    dialog._widget_owner.delete()
    scheduler.advance(100)
    assert calls == [True]


def test_scheduler_failure_does_not_leave_timer_falsely_active():
    scheduler = Scheduler()
    timer = QTimer(after=scheduler.after)
    timer.start(10)

    def failed_schedule(*args):
        raise RuntimeError("scheduler closed")

    timer._after = failed_schedule
    with pytest.raises(RuntimeError):
        scheduler.advance(10)
    assert not timer.isActive()
