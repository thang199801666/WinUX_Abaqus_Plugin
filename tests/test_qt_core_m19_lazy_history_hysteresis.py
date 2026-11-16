import importlib
import sys
import threading


def test_core_object_does_not_eager_import_gui_events():
    from pathlib import Path
    import DearUIQt.core.object as core_object
    source = Path(core_object.__file__).read_text(encoding="utf-8")
    assert "from ..gui.events import QKeyEvent" not in source
    assert "Compatibility-only lazy bridge" not in source
    assert "QKeyEvent" not in getattr(core_object, "__all__", ())


def test_core_namespace_event_compatibility_identity():
    from DearUIQt.core import QKeyEvent, QMouseEvent, QWheelEvent
    from DearUIQt.gui import QKeyEvent as GKey, QMouseEvent as GMouse, QWheelEvent as GWheel
    assert QKeyEvent is GKey
    assert QMouseEvent is GMouse
    assert QWheelEvent is GWheel


def test_host_and_popup_compact_histories_are_bounded_and_filterable():
    from DearUIQt.gui import QWindowHost, QPopupSurface

    host = QWindowHost()
    host.close(reason="test")
    assert host.transitionHistory(reason="test")
    compact = host.compactDiagnosticsSnapshot()
    assert compact["id"] == host.correlationId()
    assert len(compact["h"]) <= 16
    assert all("time_monotonic" not in row for row in compact["h"])

    popup = QPopupSurface()
    popup.beginShow(host=QWindowHost())
    popup.markVisible()
    popup.acquireInput()
    popup.beginHide(reason="test_hide")
    popup.markHidden()
    assert popup.transitionHistory(action="begin_hide", reason="test_hide")
    pcompact = popup.compactDiagnosticsSnapshot()
    assert len(pcompact["h"]) <= 24
    assert all("time_monotonic" not in row for row in pcompact["h"])


def test_watchdog_health_hysteresis_requires_consecutive_checks(monkeypatch):
    from WinUx.runtime import hang_watchdog as module

    logs = []
    monkeypatch.setattr(module, "log_event", logs.append)
    wd = module.UIHangWatchdog.__new__(module.UIHangWatchdog)
    wd._lock = threading.RLock()
    wd._health_providers = {}
    wd._health_last_report = {}
    wd._health_state = {}

    values = iter([
        {"threshold_breached": True},
        {"threshold_breached": False},
        {"threshold_breached": True},
        {"threshold_breached": True},
        {"threshold_breached": False},
        {"threshold_breached": False},
    ])
    wd.add_health_provider("idle", lambda: next(values), repeat_seconds=5,
                           breach_checks=2, recovery_checks=2)
    for now in (10, 11, 12, 20, 21, 22):
        wd._check_health_providers(now)
    assert len(logs) == 1
    assert "watchdog_hysteresis" in logs[0]
    assert wd._health_state["idle"]["latched"] is False
