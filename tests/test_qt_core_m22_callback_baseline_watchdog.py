from DearUIQt.core.dispatcher import QEventDispatcher
from DearUIQt.runtime import QGuiRuntime
from WinUx.runtime.ui_dispatcher import UiDispatcher


def test_callback_execution_latency_is_separate_from_turn_latency():
    now = [0.0]
    dispatcher = QEventDispatcher(clock=lambda: now[0])

    def first():
        now[0] += 0.002

    def second():
        now[0] += 0.007

    dispatcher.post(first)
    dispatcher.post(second)
    assert dispatcher.processEvents() == 2
    callbacks = dispatcher.callbackDiagnosticsSnapshot()
    turns = dispatcher.turnDiagnosticsSnapshot()
    assert callbacks['sample_count'] == 2
    assert callbacks['execution_duration_ms_p50'] >= 2.0
    assert callbacks['execution_duration_ms_p95'] >= 6.0
    assert callbacks['execution_duration_ms_max'] >= 7.0
    assert turns['turn_duration_ms_p95'] >= 9.0
    # Reading metrics must not deliver newly posted work.
    dispatcher.post(lambda: None)
    before = dispatcher.pendingCount()
    dispatcher.callbackDiagnosticsSnapshot()
    assert dispatcher.pendingCount() == before


def test_callback_error_metrics_are_retained_even_when_handler_consumes_error():
    dispatcher = QEventDispatcher()
    seen = []

    def fail():
        raise ValueError('m22')

    dispatcher.post(fail)
    assert dispatcher.processEvents(on_error=lambda callback, exc: seen.append(type(exc))) == 1
    snap = dispatcher.callbackDiagnosticsSnapshot()
    assert seen == [ValueError]
    assert snap['errors_total'] == 1
    assert snap['last_callback']['error'] is True


def test_compact_dispatcher_snapshot_contains_turn_and_callback_p95():
    dispatcher = UiDispatcher()
    dispatcher.post(lambda: None)
    dispatcher.processEvents()
    snap = dispatcher.compactDiagnosticsSnapshot()
    assert snap['pending'] == 0
    assert 'turn_p95_ms' in snap
    assert 'callback_p95_ms' in snap
    assert 'callback_errors' in snap


def test_frame_regression_is_sample_gated_and_thresholded():
    class Backend:
        pass

    runtime = QGuiRuntime(Backend())
    for _ in range(3):
        runtime.noteFrameSkipped('idle', wait_ms=10)
    gated = runtime.framePerformanceRegressionSnapshot(
        min_current_samples=5, min_baseline_samples=5)
    assert gated['ready'] is False
    assert gated['threshold_breached'] is False

    # Seed older samples that are inside the 30 s baseline but outside the
    # 5 s current window, then append a recent rendered burst.
    import time
    now = time.monotonic()
    for _ in range(20):
        runtime._frame_history.append((now - 20.0, 'skipped', 'idle', 10.0))
    for _ in range(8):
        runtime._frame_history.append((now, 'rendered', None, None))
    snap = runtime.framePerformanceRegressionSnapshot(
        min_current_samples=5, min_baseline_samples=5,
        max_render_rate_ratio=1.01,
        max_idle_fraction_drop=0.01,
        max_wait_p95_delta_ms=1.0)
    assert snap['ready'] is True
    assert snap['threshold_breached'] is True
    assert any(snap['checks'].values())
