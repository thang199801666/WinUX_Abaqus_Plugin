"""Headless regression tests for cooperative WinUx/DearUIQt event-loop budgets."""
from collections import deque
from types import SimpleNamespace
import threading
import time

from DearUIQt.runtime import StandaloneUiHost
from WinUx.runtime.ui_dispatcher import UiDispatcher
from tests.test_crash_regressions import load_callback_pump


def test_expired_timer_storm_is_promoted_in_bounded_batches():
    dispatcher = UiDispatcher()
    received = []
    try:
        for value in range(1500):
            dispatcher.after(1, received.append, value)
        time.sleep(0.015)
        assert dispatcher.drain(max_callbacks=9) == 9
        assert received == list(range(9))
        # The ready FIFO contains only the next limited batch, not 1,500 jobs.
        assert dispatcher.snapshot()["queued_callbacks"] <= 9
        assert dispatcher.snapshot()["scheduled_callbacks"] >= 1400
        for _ in range(250):
            if dispatcher.snapshot()["scheduled_callbacks"] == 0 and not dispatcher.snapshot()["queued_callbacks"]:
                break
            dispatcher.drain(max_callbacks=9)
        assert received == list(range(1500))
    finally:
        dispatcher.close()


def test_dispatcher_cancelled_tombstones_do_not_consume_promotion_budget():
    dispatcher = UiDispatcher()
    seen = []
    try:
        tokens = [dispatcher.after(1, seen.append, i) for i in range(125)]
        for token in tokens[:90]:
            assert dispatcher.after_cancel(token)
        time.sleep(0.010)
        assert dispatcher.drain(max_callbacks=4) == 4
        for _ in range(20):
            dispatcher.drain(max_callbacks=4)
        assert seen == list(range(90, 125))
    finally:
        dispatcher.close()


def test_standalone_host_stops_self_rescheduling_timer_storm_per_frame():
    host = StandaloneUiHost(object())
    values = []

    def repeat():
        values.append(threading.get_ident())
        if len(values) < 600:
            host.after(0, repeat)

    host.after(0, repeat)
    # New callbacks scheduled within a turn run on a later turn, not in a
    # reentrant tight loop that can block native input indefinitely.
    assert host.pump(max_callbacks=25, time_budget_ms=None) == 1
    assert len(values) == 1
    for _ in range(600):
        host.pump(max_callbacks=25, time_budget_ms=None)
    assert len(values) == 600
    assert set(values) == {threading.get_ident()}


def test_standalone_host_limits_large_immediate_batches():
    host = StandaloneUiHost(object())
    seen = []
    for i in range(700):
        host.after(0, seen.append, i)
    assert host.pump(max_callbacks=23, time_budget_ms=None) == 23
    assert seen == list(range(23))
    for _ in range(40):
        host.pump(max_callbacks=23, time_budget_ms=None)
    assert seen == list(range(700))


def test_standalone_host_cancellation_compacts_retained_deadlines():
    host = StandaloneUiHost(object())
    tokens = [host.after(60_000, lambda: None) for _ in range(160)]
    host.pump()
    assert len(host._queue) == 160
    for token in tokens[:150]:
        assert host.after_cancel(token)
    assert len(host._scheduled_callbacks) == 10
    assert len(host._queue) <= 64


def test_dpg_callback_storm_does_not_monopolize_ui_frame():
    jobs = []
    seen = []

    def fetch():
        nonlocal jobs
        batch, jobs = jobs, []
        return batch

    pump = load_callback_pump(None)
    view = SimpleNamespace(
        _dpg_callbacks=deque(), _alive=True,
        _gui_runtime=SimpleNamespace(callbackQueue=fetch, backend=SimpleNamespace(
            run_callbacks=lambda batch: batch[0][0]())),
        _handle_ui_callback_error=lambda *_: (_ for _ in ()).throw(AssertionError("error")),
    )
    jobs = [(lambda i=i: seen.append(i),) for i in range(850)]
    pump(view)
    assert 0 < len(seen) <= 256
    assert len(view._dpg_callbacks) == 850 - len(seen)
    for _ in range(20):
        pump(view)
        if not view._dpg_callbacks:
            break
    assert seen == list(range(850))


def test_plot_dock_skips_native_font_measurement_on_unchanged_frames(monkeypatch):
    from WinUx.ui.components import job_plots
    from unittest.mock import Mock

    metrics = Mock()
    metrics.size.return_value = SimpleNamespace(width=lambda: 8, height=lambda: 14)
    factory = Mock(return_value=metrics)
    monkeypatch.setattr(job_plots, "QFontMetrics", factory)
    monkeypatch.setattr(job_plots.time, "monotonic", lambda: 42.0)
    panel = SimpleNamespace(
        dock=object(),
        _dock_content_widget=SimpleNamespace(
            exists=lambda: True,
            globalGeometry=lambda: SimpleNamespace(width=lambda: 600, height=lambda: 380)),
        _status_label=SimpleNamespace(text=lambda: "Live"),
        _count_label=SimpleNamespace(text=lambda: "2 / 15"),
        _font_probe_cache=(8, 14), _font_probe_checked_at=41.9,
        _client_layout_signature=(600, 380, "Live", "2 / 15", (8, 14)),
    )
    assert job_plots.JobPlotsWindow._sync_client_layout(panel) is False
    factory.assert_not_called()
    panel._font_probe_checked_at = 40.0
    assert job_plots.JobPlotsWindow._sync_client_layout(panel) is False
    assert metrics.size.call_count == 1  # periodic font/DPI validity check
