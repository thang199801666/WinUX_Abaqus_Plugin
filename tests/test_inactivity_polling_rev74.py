import threading

from WinUx.preferences.performance import PerformancePreferences
from WinUx.services.inactivity_polling import UserInactivityPolicy


def settings(**overrides):
    values = PerformancePreferences._validated(overrides)
    return values


def test_inactivity_stages_and_qstat_backoff_progress_to_full_pause():
    now = [0.0]
    policy = UserInactivityPolicy(clock=lambda: now[0], settings=settings())
    assert policy.stage() == policy.ACTIVE
    assert policy.qstat_delay(5) == 5

    now[0] = 121
    assert policy.stage() == policy.IDLE
    assert policy.qstat_delay(5) == 60

    now[0] = 601
    assert policy.stage() == policy.AWAY
    assert policy.qstat_delay(30) == 180

    now[0] = 1801
    assert policy.stage() == policy.DEEP_IDLE
    assert policy.qstat_delay(30) is None


def test_resume_from_deep_idle_resets_age_and_notifies_waiters():
    now = [0.0]
    policy = UserInactivityPolicy(clock=lambda: now[0], settings=settings())
    now[0] = 1900
    generation = policy.resume_generation
    result = []

    waiter = threading.Thread(
        target=lambda: result.append(policy.wait_for_resume(generation, timeout=1.0)))
    waiter.start()
    now[0] = 1901
    assert policy.note_activity() == policy.DEEP_IDLE
    waiter.join(1.0)
    assert not waiter.is_alive()
    assert result == [generation + 1]
    assert policy.stage() == policy.ACTIVE
    assert policy.qstat_delay(5) == 5


def test_odb_monitor_keeps_sparse_heartbeat_and_recovers_active_limits():
    now = [0.0]
    policy = UserInactivityPolicy(clock=lambda: now[0], settings=settings())
    base = {
        "min_interval": 1.0,
        "max_interval": 60.0,
        "quiet_seconds_to_max": 180.0,
    }
    now[0] = 1801
    deep = policy.effective_odb_settings(base)
    assert deep["inactivity_stage"] == policy.DEEP_IDLE
    assert deep["min_interval"] == 60.0
    assert deep["max_interval"] == 600.0

    now[0] = 1802
    policy.note_activity()
    active = policy.effective_odb_settings(base)
    assert active["inactivity_stage"] == policy.ACTIVE
    assert active["min_interval"] == 1.0
    assert active["max_interval"] == 60.0


def test_performance_preferences_normalize_inactivity_threshold_order():
    values = PerformancePreferences._validated({
        "inactivity_idle_seconds": 600,
        "inactivity_away_seconds": 60,
        "inactivity_deep_idle_seconds": 120,
        "inactivity_idle_qstat_interval": 90,
        "inactivity_away_qstat_interval": 30,
    })
    assert values["inactivity_away_seconds"] == 600
    assert values["inactivity_deep_idle_seconds"] == 600
    assert values["inactivity_away_qstat_interval"] == 90


def test_qapplication_exposes_one_shared_user_activity_signal():
    source = open("DearUIQt/qt/application.py", encoding="utf-8").read()
    assert "self.userActivity = Signal(self)" in source
    assert 'self.userActivity.emit("pointer-move")' in source
    assert 'self.userActivity.emit("key-press")' in source


def test_remote_pollers_share_app_inactivity_policy():
    qstat = open("WinUx/controllers/job_polling.py", encoding="utf-8").read()
    plot = open("WinUx/controllers/job_plot.py", encoding="utf-8").read()
    reconnect = open("WinUx/controllers/connection.py", encoding="utf-8").read()
    remote_odb = open("WinUx/services/remote_odb.py", encoding="utf-8").read()
    assert "inactivity.qstat_delay" in qstat
    assert "effective_adaptive_settings" in plot
    assert "inactivity.stage() == inactivity.DEEP_IDLE" in reconnect
    assert "next_adaptive_check = now + 0.5" in remote_odb


def test_floating_dialog_feature_events_also_wake_inactivity_policy():
    source = open("WinUx/ui/hosting/floating_dialog.py", encoding="utf-8").read()
    assert 'get("user_activity")' in source
    assert 'activity("floating-dialog")' in source


def test_deep_idle_job_poller_skips_qstat_until_woken(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from WinUx.controllers.job_polling import JobPollingController

    now = [1900.0]
    policy = UserInactivityPolicy(clock=lambda: now[0], settings=settings())
    # Move the last activity origin to t=0 while keeping the fake current clock
    # at deep idle age.
    policy._last_activity_at = 0.0
    cancel = threading.Event()
    force_fast = threading.Event()
    wakeup = Mock()
    wakeup.wait.side_effect = lambda delay: cancel.set()
    wakeup.clear = Mock()
    server = SimpleNamespace(connected=True, list_jobs=Mock(return_value=[]))
    app = SimpleNamespace(
        _closing=False,
        _connection_generation=1,
        _inactivity_policy=policy,
        server=server,
        view=SimpleNamespace(after=lambda *args: None, winfo_exists=lambda: True),
        _apply_job_update=lambda *args: None,
    )
    polling = JobPollingController(app)
    events = iter((cancel, wakeup, force_fast))
    monkeypatch.setattr("WinUx.controllers.job_polling.threading.Event", lambda: next(events))
    monkeypatch.setattr(
        "WinUx.controllers.job_polling.PerformancePreferences.load",
        lambda _self: settings())
    monkeypatch.setattr(
        "WinUx.controllers.job_polling.threading.Thread",
        lambda **kwargs: SimpleNamespace(start=kwargs["target"]))

    polling.start()
    server.list_jobs.assert_not_called()
    wakeup.wait.assert_called_once_with(60.0)
