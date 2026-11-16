import time

from DearUIQt.core import QEvent, QKeyEvent as CoreQKeyEvent, QMouseEvent as CoreQMouseEvent, Qt
from DearUIQt.gui import QKeyEvent, QMouseEvent, QWheelEvent, QPopupSurface, QWindowHost
from WinUx.runtime.hang_watchdog import UIHangWatchdog


def test_gui_events_are_physical_qtgui_classes_with_core_compatibility():
    assert CoreQKeyEvent is QKeyEvent
    assert CoreQMouseEvent is QMouseEvent
    assert QKeyEvent.__module__ == "DearUIQt.gui.events"
    assert QMouseEvent.__module__ == "DearUIQt.gui.events"
    assert QWheelEvent.__module__ == "DearUIQt.gui.events"
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_A, text="a")
    assert event.key() == Qt.Key_A
    assert event.text() == "a"


def test_window_host_transition_history_is_bounded_and_copied():
    host = QWindowHost(close=lambda: False)
    for _ in range(30):
        assert host.close() is False
    history = host.transitionHistory()
    assert 1 <= len(history) <= 16
    assert history[-1]["state"] == "alive"
    assert history[-1]["reason"] == "close_rejected"
    snapshot = host.diagnosticsSnapshot()
    assert snapshot["transition_history"][-1]["state"] == "alive"
    snapshot["transition_history"][-1]["state"] = "mutated"
    assert host.transitionHistory()[-1]["state"] == "alive"


def test_popup_transition_history_tracks_input_and_host_teardown():
    host = QWindowHost(close=lambda: True)
    popup = QPopupSurface()
    assert popup.beginShow(host=host, geometry=(1, 2, 10, 12))
    assert popup.markVisible()
    assert popup.acquireInput()
    assert host.close(reason="test_shutdown")
    snap = popup.diagnosticsSnapshot()
    actions = [item["action"] for item in snap["transition_history"]]
    assert "begin_show" in actions
    assert "visible" in actions
    assert "acquire_input" in actions
    assert "begin_hide" in actions
    assert "hidden" in actions
    assert snap["last_teardown_correlation_id"] == host.teardownCorrelationId()
    assert popup.isConsistent()


def test_watchdog_health_provider_rate_limits_breaches(monkeypatch):
    watchdog = object.__new__(UIHangWatchdog)
    import threading
    watchdog._lock = threading.RLock()
    watchdog._health_providers = {}
    watchdog._health_last_report = {}
    logs = []
    monkeypatch.setattr("WinUx.runtime.hang_watchdog.log_event", logs.append)
    watchdog.add_health_provider(
        "idle", lambda: {"idle_render_threshold_breached": True},
        repeat_seconds=5.0, breach_checks=1, recovery_checks=1)
    watchdog._check_health_providers(10.0)
    watchdog._check_health_providers(12.0)
    watchdog._check_health_providers(15.1)
    assert len(logs) == 2
    assert all("idle" in line for line in logs)
