"""Behavior guards for controller components extracted from WinUXController."""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from WinUx.controllers.job_plot import JobPlotController
from WinUx.controllers.schedule_manifest import ScheduleManifestController


class _FakeWindow:
    def __init__(self):
        self.catalog = None
        self.frame = None
        self.status = None
        self.error = None

    def set_catalog(self, payload):
        self.catalog = payload

    def update_frame(self, payload):
        self.frame = payload

    def set_status(self, message):
        self.status = message

    def set_error(self, message):
        self.error = message


class _FakeView:
    def __init__(self, window=None):
        self.window = window
        self.job_plot_windows = {}

    def get_job_plots(self, _job_id):
        return self.window


def _plot_controller(window=None):
    app = SimpleNamespace(
        view=_FakeView(window),
        server=SimpleNamespace(),
        _closing=False,
    )
    return JobPlotController(app)


def test_job_plot_component_owns_selection_snapshot_and_copies_payload_items():
    plots = _plot_controller()
    cancel = threading.Event()
    plots._watchers["42"] = {
        "cancel": cancel,
        "selection": [],
        "job_name": "demo",
        "thread": None,
    }
    original = [{"region": "Assembly", "output": "ALLIE"}]
    plots.selection_changed("42", original)
    original[0]["output"] = "changed"
    snapshot = plots.selection_snapshot("42")
    assert snapshot == [{"region": "Assembly", "output": "ALLIE"}]
    snapshot[0]["output"] = "mutated"
    assert plots.selection_snapshot("42")[0]["output"] == "ALLIE"


def test_job_plot_component_stop_all_cancels_every_watcher_without_joining():
    plots = _plot_controller()
    first = threading.Event()
    second = threading.Event()
    plots._watchers.update({
        "1": {"cancel": first},
        "2": {"cancel": second},
    })
    plots.stop_all()
    assert first.is_set() and second.is_set()
    assert plots._watchers == {}


def test_job_plot_component_routes_payload_types_to_existing_window():
    window = _FakeWindow()
    plots = _plot_controller(window)
    plots.apply_payload("1", {"type": "catalog", "value": 1})
    plots.apply_payload("1", {"type": "frame", "value": 2})
    plots.apply_payload("1", {"type": "status", "message": "waiting"})
    plots.apply_payload("1", {"type": "fatal", "error": "failed"})
    assert window.catalog["value"] == 1
    assert window.frame["value"] == 2
    assert window.status == "waiting"
    assert window.error == "failed"


def test_schedule_manifest_component_serializes_run_task_without_ui_state():
    component = object.__new__(ScheduleManifestController)
    component.app = SimpleNamespace(
        server=SimpleNamespace(username="alice"),
    )
    task = {
        "schedule_id": "run|demo",
        "path": Path("/scratch/demo.inp"),
        "job_name": "demo",
        "target": datetime(2026, 10, 3, 12, 30, 0),
        "mode": "Run At",
        "job": {
            "path": Path("/scratch/demo.inp"),
            "nested": [Path("/scratch/include.inc")],
        },
    }
    entry = component.manifest_entry(task, "run")
    assert entry["owner"] == "alice"
    assert entry["path"] == str(task["path"])
    assert entry["job"]["path"] == str(task["job"]["path"])
    assert entry["job"]["nested"] == [str(task["job"]["nested"][0])]
    assert entry["target"] == "2026-10-03T12:30:00"


def _schedule_component():
    class View:
        def after(self, _delay, callback, *args):
            callback(*args)

        def winfo_exists(self):
            return True

    app = SimpleNamespace(
        server=SimpleNamespace(username="alice", connected=True),
        view=View(),
        _closing=False,
        _job_edit_settings={},
        _remove_shared_schedule=lambda _schedule_id: None,
        _save_shared_schedule=lambda _task, _kind: True,
    )
    from WinUx.controllers.job_schedule import JobScheduleController
    return JobScheduleController(app)


def test_job_schedule_component_installs_overdue_run_as_immediate_catch_up():
    schedule = _schedule_component()
    schedule.install_shared([{
        "schedule_id": "run|job-key",
        "kind": "run",
        "path": "/scratch/job.inp",
        "job": {"path": "/scratch/job.inp"},
        "job_name": "job",
        "owner": "alice",
        "mode": "Run At",
        "target": "2026-10-03T00:00:00",
    }])
    task = schedule.run_tasks["job-key"]
    assert task["catch_up"] is True
    assert task["retry_at"] <= datetime.now()


def test_job_schedule_component_rows_keep_legacy_dialog_shape():
    schedule = _schedule_component()
    target = datetime.now()
    schedule.run_tasks["run-1"] = {
        "key": "run-1", "job_name": "demo", "mode": "Run At",
        "target": target, "cancel": threading.Event(),
    }
    rows = schedule.rows()
    assert len(rows) == 1
    assert rows[0][0] == "demo"
    assert rows[0][4:] == ("Waiting", "run", "run-1")


def test_transfer_component_rejects_recursive_local_drop():
    from WinUx.controllers.transfer import TransferController

    model = SimpleNamespace(normalize=lambda value: Path(value).resolve())
    app = SimpleNamespace(model=model, server=SimpleNamespace(connected=True))
    transfer = TransferController(app)
    source_panel = SimpleNamespace(panel_id="local")
    target_panel = SimpleNamespace(panel_id="local")
    source = Path("/tmp/source")
    assert transfer.drop_is_valid(source_panel, target_panel, [source], source / "child") is False


def test_transfer_component_allows_cross_panel_destination_without_local_normalization():
    from WinUx.controllers.transfer import TransferController

    app = SimpleNamespace(
        model=SimpleNamespace(),
        server=SimpleNamespace(connected=True),
    )
    transfer = TransferController(app)
    source_panel = SimpleNamespace(panel_id="local")
    target_panel = SimpleNamespace(panel_id="server")
    assert transfer.drop_is_valid(source_panel, target_panel, [Path("/tmp/a")], "/scratch") is True


def test_connection_component_adopts_existing_legacy_state_without_replacing_it():
    from WinUx.controllers.connection import ConnectionController

    lock = threading.Lock()
    online = threading.Event()
    app = SimpleNamespace(
        _reconnect_lock=lock,
        _reconnect_active=True,
        _connection_online=online,
        _connection_generation=9,
    )
    component = ConnectionController(app, adopt_existing=True)
    assert component.app is app
    assert app._reconnect_lock is lock
    assert app._connection_online is online
    assert app._reconnect_active is True
    assert app._connection_generation == 9


def test_connection_component_ensure_online_sets_shared_event_without_reconnecting():
    from WinUx.controllers.connection import ConnectionController

    online = threading.Event()
    app = SimpleNamespace(
        _reconnect_lock=threading.Lock(),
        _reconnect_active=False,
        _connection_online=online,
        _connection_generation=0,
        server=SimpleNamespace(connected=True, host="server", username="alice"),
        view=SimpleNamespace(),
    )
    component = ConnectionController(app, adopt_existing=True)
    assert component.ensure_online() is True
    assert online.is_set()


def test_job_polling_signature_ignores_elapsed_but_tracks_state_changes():
    from WinUx.controllers.job_polling import JobPollingController

    first = SimpleNamespace(
        job_id="1", name="demo", user="alice", tokens="4",
        status="R", elapsed="00:00:01")
    later = SimpleNamespace(
        job_id="1", name="demo", user="alice", tokens="4",
        status="R", elapsed="12:34:56")
    finished = SimpleNamespace(
        job_id="1", name="demo", user="alice", tokens="4",
        status="C", elapsed="12:34:57")
    assert JobPollingController.signature([first]) == JobPollingController.signature([later])
    assert JobPollingController.signature([first]) != JobPollingController.signature([finished])


def test_job_polling_manual_refresh_wakes_existing_poller_without_second_qstat():
    from unittest import mock
    from WinUx.controllers.job_polling import JobPollingController

    cancel = threading.Event()
    force_fast = threading.Event()
    wakeup = threading.Event()
    server = SimpleNamespace(connected=True, list_jobs=mock.Mock())
    app = SimpleNamespace(
        server=server,
        view=SimpleNamespace(),
        _closing=False,
        _job_poll_cancel=cancel,
        _job_poll_policy=None,
        _job_poll_force_fast=force_fast,
        _job_poll_wakeup=wakeup,
    )
    JobPollingController(app, adopt_existing=True).refresh_now()
    assert force_fast.is_set()
    assert wakeup.is_set()
    server.list_jobs.assert_not_called()


def test_successful_login_returns_focus_to_main_owner_after_modal_close():
    from unittest import mock
    from WinUx.controllers.connection import ConnectionController

    dialog = mock.Mock()
    dialog.winfo_exists.return_value = True
    server = mock.Mock(host="cluster", username="alice")
    view = mock.Mock()
    app = SimpleNamespace(
        view=view,
        server=server,
        _connection_online=threading.Event(),
        _flush_schedule_manifest_async=mock.Mock(),
        _restore_shared_schedules=mock.Mock(),
        _start_job_polling=mock.Mock(),
        navigation_preferences=mock.Mock(),
    )
    component = ConnectionController(app)

    component.login_succeeded(dialog, "/scratch", [{"name": "job.inp"}])

    dialog.destroy.assert_called_once_with(return_focus=True)
    view.display_server_directory.assert_called_once_with(
        "/scratch", [{"name": "job.inp"}], "cluster", reset_history=True)
    assert app._connection_online.is_set()
