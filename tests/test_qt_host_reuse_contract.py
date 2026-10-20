"""Source-level contracts for the reusable Qt-style dialog host layer."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_child_runtime_reader_uses_shared_qthreadpool():
    runtime = source("WinUx/ui/hosting/floating_runtime.py")
    assert "_RUNTIME_IO_POOL = QThreadPool" in runtime
    assert "_RUNTIME_IO_POOL.start(reader)" in runtime
    assert "_RUNTIME_IO_POOL.start(self._read_commands)" in runtime
    assert "threading.Thread(" not in runtime


def test_host_reuse_has_final_dynamic_form_audit():
    dialog = source("DearUIQt/dialogs/qt_dialog.py")
    runtime = source("WinUx/ui/hosting/floating_runtime.py")
    assert "def canReuseHost(self):" in dialog
    assert 'probe = getattr(self.form, "canReuseHost", None)' in runtime


def test_heavy_dialogs_opt_into_reuse_after_lifecycle_cleanup():
    for relative in (
        "WinUx/dialogs/reference_chart_form.py",
        "WinUx/dialogs/console_form.py",
        "WinUx/dialogs/transfer_center_form.py",
        "WinUx/plotdigitizer/ui/dialog.py",
    ):
        assert "REUSABLE_HOST = True" in source(relative), relative


def test_plot_digitizer_uses_shared_qt_concurrent_submitter():
    ui = source("WinUx/plotdigitizer/ui/dialog.py")
    tasks = source("WinUx/plotdigitizer/application/tasks.py")
    assert "submitter=QtConcurrent.run" in ui
    assert "self._executor = ThreadPoolExecutor" not in tasks
    assert "_SHARED_SMART_DETECT_EXECUTOR" in tasks
    assert "self._reuse_safe_on_close" in ui


def test_console_periodic_ui_work_is_qtimer_owned_and_transfer_needs_no_paint_timer():
    console = source("WinUx/dialogs/console_form.py")
    transfer = source("WinUx/dialogs/transfer_center_form.py")
    assert "self.create_timer(100, self._refresh)" in console
    assert "self.create_timer(33, self._paint_tick)" in console
    assert "self.view.after(100, self._refresh)" not in console
    assert "self.view.after(33, self._paint_tick)" not in console
    assert "_progress_paint_timer" not in transfer
    assert "self.view.after(16" not in transfer
