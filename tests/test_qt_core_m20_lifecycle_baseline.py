import time


def test_core_object_no_direct_qtgui_event_compatibility_edge():
    import DearUIQt.core.object as core_object
    assert "QKeyEvent" not in core_object.__all__
    assert "QMouseEvent" not in core_object.__all__
    assert "QWheelEvent" not in core_object.__all__
    assert not hasattr(core_object, "QKeyEvent")

    # Namespace-level compatibility remains source compatible.
    from DearUIQt.core import QKeyEvent
    from DearUIQt.gui.events import QKeyEvent as GuiKeyEvent
    assert QKeyEvent is GuiKeyEvent


def test_lifecycle_record_is_shared_typed_and_primitive_only():
    from DearUIQt.gui import (
        QLifecycleTransitionRecord, QWindowHost, QPopupSurface,
    )

    host = QWindowHost()
    host.close(reason="m20")
    assert host._transition_history
    assert all(isinstance(row, QLifecycleTransitionRecord)
               for row in host._transition_history)

    popup = QPopupSurface()
    popup_host = QWindowHost()
    popup.beginShow(host=popup_host)
    popup.markVisible()
    popup.beginHide(reason="m20")
    popup.markHidden()
    assert popup._transition_history
    assert all(isinstance(row, QLifecycleTransitionRecord)
               for row in popup._transition_history)

    compact = popup.compactTransitionHistory()
    assert compact
    assert all("time_monotonic" not in row for row in compact)


def test_ui_dispatcher_exposes_only_canonical_scheduler_spellings():
    from WinUx.runtime.ui_dispatcher import UiDispatcher

    dispatcher = UiDispatcher()
    try:
        assert hasattr(dispatcher, "setWakeCallback")
        assert hasattr(dispatcher, "nextDeadlineMs")
        assert hasattr(dispatcher, "hasPendingEvents")
        assert not hasattr(dispatcher, "set_wake_callback")
        assert not hasattr(dispatcher, "next_deadline_ms")
        assert not hasattr(dispatcher, "has_immediate_work")
        assert not hasattr(dispatcher, "post_once")
        assert not hasattr(dispatcher, "queue")
    finally:
        dispatcher.close()


def test_frame_baseline_reports_wait_percentiles_without_consuming_damage():
    from DearUIQt.runtime import QGuiRuntime

    class Backend:
        pass

    runtime = QGuiRuntime(Backend())
    host = runtime.windowHost()
    host.requestUpdate((1, 2, 3, 4))
    runtime.noteFrameSkipped("idle", wait_ms=10)
    runtime.noteFrameSkipped("idle", wait_ms=30)
    runtime.noteFrameSkipped("idle", wait_ms=20)

    baseline = runtime.framePerformanceBaselineSnapshot(window_seconds=30.0)
    assert baseline["sample_count"] >= 3
    assert baseline["wait_p50_ms"] == 20.0
    assert baseline["wait_p95_ms"] >= 28.0
    assert baseline["idle_fraction"] == 1.0
    assert host.dirtyRegion() is not None

    perf = runtime.framePerformanceSnapshot()
    assert "baseline_30s" in perf
    assert perf["baseline_30s"]["wait_p50_ms"] == 20.0
    assert host.dirtyRegion() is not None
