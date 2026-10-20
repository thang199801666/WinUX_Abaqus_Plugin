from datetime import datetime, timedelta
from types import SimpleNamespace
import threading
from unittest.mock import Mock

from WinUx.controllers.job_schedule import JobScheduleController


def fixture():
    callbacks = []
    app = SimpleNamespace(
        _closing=False,
        _job_edit_settings={"123": {"delete_after_enabled": True}},
        server=SimpleNamespace(connected=True, username="owner"),
        view=SimpleNamespace(
            after=lambda delay, callback, *args: callbacks.append((callback, args)),
            winfo_exists=lambda: True,
            job_schedule_dialog=None,
            right=SimpleNamespace(status=SimpleNamespace(set=Mock())),
        ),
        _remove_shared_schedule=Mock(),
    )
    return app, callbacks


def make_delete_task(*, requested=False, job_id="123"):
    target = datetime.now() + timedelta(minutes=30)
    task = {
        "job_id": job_id,
        "job_name": "Test-17-0284",
        "mode": "Delete After 00:30",
        "delete_time": target.strftime("%Y-%m-%d %H:%M:%S"),
        "target": target,
        "cancel": threading.Event(),
        "owner": "owner",
        "schedule_id": "delete|{}".format(job_id),
    }
    if requested:
        task["delete_requested"] = True
    return task


def test_naturally_finished_job_removes_future_delete_schedule_without_history_row():
    app, callbacks = fixture()
    scheduler = JobScheduleController(app)
    task = make_delete_task()
    scheduler.delete_tasks["123"] = task

    assert scheduler.reconcile_deletions([]) == 1
    assert "123" not in scheduler.delete_tasks
    assert "123" not in app._job_edit_settings
    assert task["cancel"].is_set()
    assert "delete|123" not in scheduler.history
    app._remove_shared_schedule.assert_called_once_with("delete|123")
    assert callbacks, "open Job Schedule dialogs should be refreshed promptly"


def test_job_removed_after_winux_qdel_is_recorded_complete_then_retired():
    app, _callbacks = fixture()
    scheduler = JobScheduleController(app)
    task = make_delete_task(requested=True)
    scheduler.delete_tasks["123"] = task

    assert scheduler.reconcile_deletions([]) == 1
    assert scheduler.history["delete|123"]["status"] == "Complete"
    app._remove_shared_schedule.assert_called_once_with("delete|123")


def test_live_job_keeps_delete_schedule_pending():
    app, callbacks = fixture()
    scheduler = JobScheduleController(app)
    task = make_delete_task()
    scheduler.delete_tasks["123"] = task
    live = SimpleNamespace(job_id=123)

    assert scheduler.reconcile_deletions([live]) == 0
    assert scheduler.delete_tasks["123"] is task
    assert not task["cancel"].is_set()
    app._remove_shared_schedule.assert_not_called()
    assert not callbacks


def test_rows_no_longer_report_naturally_finished_job_as_waiting():
    app, _callbacks = fixture()
    scheduler = JobScheduleController(app)
    task = make_delete_task()
    scheduler.delete_tasks["123"] = task
    assert any(row[4] == "Waiting" for row in scheduler.rows())

    scheduler.reconcile_deletions([])

    assert scheduler.rows() == []
