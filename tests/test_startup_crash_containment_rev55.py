from pathlib import Path
import threading

from WinUx.runtime.ui_dispatcher import UiDispatcher
from WinUx.runtime.task_manager import BackgroundTaskManager


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "WinUx" / "view.py"


def test_ui_dispatcher_falls_back_to_ui_thread_if_scheduler_thread_cannot_start(monkeypatch):
    original_start = threading.Thread.start

    def fail_scheduler(self):
        if self.name == "winux-ui-scheduler":
            raise RuntimeError("thread quota")
        return original_start(self)

    monkeypatch.setattr(threading.Thread, "start", fail_scheduler)
    dispatcher = UiDispatcher()
    seen = []
    dispatcher.after(0, seen.append, "now")
    dispatcher.after(1, seen.append, "later")
    dispatcher.drain()
    assert seen == ["now"]
    import time
    time.sleep(0.01)
    dispatcher.drain()
    assert seen == ["now", "later"]
    snapshot = dispatcher.snapshot()
    assert snapshot["scheduler_fallback"] is True
    assert snapshot["scheduler_alive"] is False
    dispatcher.close()


def test_background_pool_rejects_work_instead_of_crashing_if_workers_cannot_start(monkeypatch):
    original_start = threading.Thread.start

    def fail_workers(self):
        if self.name.startswith("quota-test-"):
            raise RuntimeError("thread quota")
        return original_start(self)

    monkeypatch.setattr(threading.Thread, "start", fail_workers)
    manager = BackgroundTaskManager(max_workers=2, name="quota-test")
    handle = manager.submit("demo", lambda: 1)
    assert handle.state == "rejected"
    assert handle.done
    assert "unavailable" in str(handle.exception)
    snapshot = manager.snapshot()
    assert snapshot["workers"] == 0
    assert snapshot["worker_start_error"]
    manager.close()


def test_main_view_contains_recoverable_per_frame_failures_and_nonfatal_error_ui():
    source = VIEW.read_text(encoding="utf-8")
    assert "def _safe_frame_step(self, name, callback, *args, **kwargs):" in source
    assert "Non-fatal UI frame step failed" in source
    assert 'self._safe_frame_step("job plot window sync", self._sync_job_plot_windows)' in source
    assert '"QApplication input bridge installation failed during startup"' in source
    assert '"Dock drop preview initialization failed during startup"' in source
    assert '"UI hang watchdog could not start"' in source
    # Error presentation is diagnostic; a second UI failure must not re-raise.
    block = source.split("def _handle_ui_callback_error", 1)[1].split("def protocol", 1)[0]
    assert "fatal=False" in block
    assert "raise" not in block
