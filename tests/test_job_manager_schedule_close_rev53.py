from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from WinUx.dialogs.logic.job_manager import JobManagerLogic


ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "job_manager_form.py"
ADAPTER = ROOT / "WinUx" / "dialogs" / "floating_adapters.py"
LOGIC = ROOT / "WinUx" / "dialogs" / "logic" / "job_manager.py"


class _View:
    def __init__(self):
        self.after_render_calls = []

    def after_render(self, callback, *args):
        self.after_render_calls.append((callback, args))
        return True


class _Dialog(JobManagerLogic):
    def __init__(self):
        self.view = _View()
        self._pending_queue_job_names = set()
        self._submission_finished = False
        self._close_requested = False
        self.commands = []
        self.destroyed = False

    def winfo_exists(self):
        return not self.destroyed

    def post(self, command, *args, **kwargs):
        self.commands.append((command, args, kwargs))
        return True

    def destroy(self):
        self.destroyed = True


def test_future_scheduled_jobs_do_not_enter_queue_visibility_wait_set():
    dialog = _Dialog()
    path = Path("future-job.inp")
    dialog.submission_scheduled(path, datetime.now() + timedelta(hours=1))
    assert dialog._pending_queue_job_names == set()
    assert any(command == "status" and "scheduled for" in args[0]
               for command, args, _kwargs in dialog.commands)


def test_schedule_only_batch_closes_without_waiting_for_job_viewer():
    dialog = _Dialog()
    dialog.submission_scheduled(Path("future-job.inp"), datetime.now() + timedelta(hours=1))
    dialog.submission_finished(1, 0)
    assert dialog._submission_finished is True
    assert dialog._close_requested is True
    assert len(dialog.view.after_render_calls) == 1
    assert not any(command == "status" and args[0] == "Waiting for submitted jobs in Job Viewer..."
                   for command, args, _kwargs in dialog.commands)


def test_immediate_submission_waits_until_job_is_visible_in_job_viewer():
    dialog = _Dialog()
    path = Path("now-job.inp")
    dialog.submission_job_complete(path, "ok")
    dialog.submission_finished(1, 0)
    assert dialog._pending_queue_job_names == {"now-job"}
    assert dialog._close_requested is False
    assert any(command == "status" and args[0] == "Waiting for submitted jobs in Job Viewer..."
               for command, args, _kwargs in dialog.commands)

    dialog.job_view_updated([SimpleNamespace(name="other-job")])
    assert dialog._close_requested is False
    assert dialog.view.after_render_calls == []

    dialog.job_view_updated([SimpleNamespace(name="now-job")])
    assert dialog._close_requested is True
    assert len(dialog.view.after_render_calls) == 1


def test_mixed_future_and_immediate_batch_waits_only_for_immediate_job():
    dialog = _Dialog()
    dialog.submission_scheduled(Path("later.inp"), datetime.now() + timedelta(hours=1))
    dialog.submission_job_complete(Path("now.inp"), "ok")
    dialog.submission_finished(2, 0)
    assert dialog._pending_queue_job_names == {"now"}
    dialog.job_view_updated([SimpleNamespace(name="now")])
    assert dialog._close_requested is True


def test_both_native_frontends_initialize_pending_queue_tracking():
    form = FORM.read_text(encoding="utf-8")
    adapter = ADAPTER.read_text(encoding="utf-8")
    logic = LOGIC.read_text(encoding="utf-8")
    assert "self._pending_queue_job_names = set()" in form
    assert "self._pending_queue_job_names = set()" in adapter
    assert "self._pending_queue_job_names.clear()" in logic
    assert "self._successful_job_names" not in form
    assert "self._successful_job_names" not in adapter
    assert "self._successful_job_names" not in logic
