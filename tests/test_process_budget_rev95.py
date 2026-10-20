"""Regression coverage for r95 floating-process ownership/budget."""
from pathlib import Path
from unittest import mock
import subprocess

from DearUIQt.core.process import QProcess

ROOT = Path(__file__).resolve().parents[1]


def text(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_main_view_does_not_keep_closed_dialog_processes_resident():
    source = text("WinUx/view.py")
    assert "self._dialog_resident_limit = 0" in source


def test_default_startup_prewarm_uses_one_process_without_headroom():
    source = text("WinUx/ui/hosting/host.py")
    assert "QDialogHostPool(capacity=1, reusable=True, resident_headroom=0)" in source
    assert "process.close(timeout=0.35, force=True)" in source


def test_qprocess_force_close_terminates_tree_and_reaps_after_grace_timeout():
    process = QProcess(childLabel="test")
    native = mock.Mock()
    native.pid = 321
    native.poll.return_value = None
    native.wait.side_effect = [subprocess.TimeoutExpired("x", 0.01), 0]
    process._process = native
    process._state = process.Running

    with mock.patch.object(process, "terminateTree") as terminate_tree:
        process.close(timeout=0.01, force=True)

    terminate_tree.assert_called_once_with()
    assert native.wait.call_count == 2
