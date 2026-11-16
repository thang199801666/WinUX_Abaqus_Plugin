from DearUIQt.core.dispatcher import QEventDispatcher
from DearUIQt.gui import QWindowHost, QPopupSurface
from DearUIQt.runtime import QGuiRuntime


def test_dispatcher_turn_diagnostics_are_bounded_and_observational():
    now = [0.0]
    dispatcher = QEventDispatcher(clock=lambda: now[0])
    order = []

    def first():
        order.append("first")
        now[0] += 0.004

    def second():
        order.append("second")
        now[0] += 0.006

    dispatcher.post(first)
    dispatcher.post(second)
    cancelled = dispatcher.after(100, lambda: None)
    assert dispatcher.after_cancel(cancelled) is True
    assert dispatcher.processEvents() == 2

    snap = dispatcher.turnDiagnosticsSnapshot()
    assert order == ["first", "second"]
    assert snap["turns_total"] == 1
    assert snap["ready_total"] == 2
    assert snap["processed_total"] == 2
    assert snap["cancelled_total"] == 1
    assert snap["turn_duration_ms_p95"] >= 9.0
    assert snap["last_turn"]["processed"] == 2
    # Snapshot must not process/cancel any pending work.
    dispatcher.post(lambda: order.append("later"))
    before = dispatcher.pendingCount()
    dispatcher.turnDiagnosticsSnapshot()
    assert dispatcher.pendingCount() == before


def test_shared_lifecycle_diagnostics_helpers_preserve_host_popup_schemas():
    host = QWindowHost()
    host.close(reason="m21")
    host_rows = host.transitionHistory(reason="m21")
    assert host_rows and host_rows[-1]["reason"] == "m21"
    assert host.compactTransitionHistory()[-1]["r"] == "m21"

    popup_host = QWindowHost()
    popup = QPopupSurface()
    popup.beginShow(host=popup_host)
    popup.markVisible()
    popup.beginHide(reason="m21")
    popup.markHidden()
    popup_rows = popup.transitionHistory(action="begin_hide", reason="m21")
    assert popup_rows and popup_rows[-1]["state"] >= 0
    assert popup.compactTransitionHistory()[-2]["r"] == "m21"


def test_frame_performance_comparison_requires_minimum_samples():
    class Backend:
        pass

    runtime = QGuiRuntime(Backend())
    for _ in range(3):
        runtime.noteFrameSkipped("idle", wait_ms=20)
    gated = runtime.framePerformanceComparisonSnapshot(
        min_current_samples=5, min_baseline_samples=5)
    assert gated["ready"] is False

    for _ in range(8):
        runtime.noteFrameSkipped("idle", wait_ms=30)
    ready = runtime.framePerformanceComparisonSnapshot(
        min_current_samples=5, min_baseline_samples=5)
    assert ready["ready"] is True
    assert ready["current"]["sample_count"] >= 5
    assert ready["baseline"]["sample_count"] >= 5
    assert "wait_p95_delta_ms" in ready


def test_frame_performance_warning_is_sample_gated():
    class Backend:
        pass

    runtime = QGuiRuntime(Backend())
    # Small startup sample must not arm performance warning eligibility.
    runtime.noteFrameSkipped("idle", wait_ms=1)
    perf = runtime.framePerformanceSnapshot()
    assert perf["idle_render_warning_eligible"] is False
    assert perf["idle_render_threshold_breached"] is False
    assert perf["comparison_5s_vs_30s"]["ready"] is False
