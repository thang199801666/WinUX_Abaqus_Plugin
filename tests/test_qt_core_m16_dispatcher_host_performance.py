import time
from unittest.mock import patch

from DearUIQt import QApplication, QCoreApplication, QGuiRuntime, QWindowHost, QWindowHostState
from WinUx.runtime.ui_dispatcher import UiDispatcher


def _cleanup_app():
    app = QCoreApplication.instance()
    if app is not None:
        app.delete()


def test_qcore_no_longer_owns_gui_input_constants():
    _cleanup_app()
    core = QCoreApplication()
    try:
        assert not hasattr(core, "_DEFAULT_INPUT_KEY_NAMES")
        assert not hasattr(core, "_NATIVE_MOUSE_BUTTON_NAMES")
    finally:
        core.delete()
    app = QApplication()
    try:
        assert app._DEFAULT_INPUT_KEY_NAMES
        assert app._NATIVE_MOUSE_BUTTON_NAMES
    finally:
        app.delete()


def test_ui_dispatcher_delayed_work_uses_canonical_scheduler_and_one_budget():
    dispatcher = UiDispatcher()
    delivered = []
    with patch("WinUx.runtime.ui_dispatcher.time.monotonic", return_value=10.0):
        token = dispatcher.after(20, delivered.append, "timer", priority=5)
        dispatcher.post(delivered.append, "immediate", priority=0)
        assert token is not None
        assert dispatcher.diagnosticsSnapshot()["scheduled_callbacks"] == 1
        assert dispatcher.processEvents(max_callbacks=1) == 1
        assert delivered == ["immediate"]
    with patch("WinUx.runtime.ui_dispatcher.time.monotonic", return_value=10.03):
        assert dispatcher.processEvents(max_callbacks=1) == 1
    assert delivered == ["immediate", "timer"]
    dispatcher.close()


def test_window_host_typed_state_and_teardown_reason():
    rejected = QWindowHost(close=lambda: False)
    assert rejected.state() is QWindowHostState.Alive
    assert rejected.close(reason="native_close") is False
    assert rejected.state() is QWindowHostState.Alive
    snap = rejected.diagnosticsSnapshot()
    assert snap["state"] == "alive"
    assert snap["last_transition_reason"] == "close_rejected"
    assert snap["teardown_reason"] is None

    accepted = QWindowHost(close=lambda: True)
    assert accepted.close(reason="owner_destroyed") is True
    assert accepted.state() is QWindowHostState.Closed
    assert accepted.teardownReason() == "owner_destroyed"
    assert accepted.diagnosticsSnapshot()["teardown_reason"] == "owner_destroyed"


def test_frame_performance_snapshot_is_read_only_and_quantitative():
    class Backend:
        pass

    runtime = QGuiRuntime(Backend())
    host = runtime.windowHost()
    host.setGeometry((0, 0, 100, 80))
    host.requestUpdate((1, 2, 3, 4))
    before = host.dirtyRegion()
    runtime.noteFrameSkipped("idle", 25.0)
    runtime.noteFrameSkipped("idle", 50.0)
    snapshot = runtime.framePerformanceSnapshot()
    after = host.dirtyRegion()
    assert snapshot["has_dirty_region"] is True
    assert snapshot["idle_candidate"] is False
    assert snapshot["idle_fraction_5s"] > 0.0
    assert snapshot["average_wait_ms_5s"] == 37.5
    assert (before.x(), before.y(), before.width(), before.height()) == (
        after.x(), after.y(), after.width(), after.height())
