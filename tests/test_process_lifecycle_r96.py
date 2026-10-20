"""r96 regression coverage for WinUx-owned helper process cleanup."""
from pathlib import Path
from unittest import mock

from DearUIQt.core.process import QProcess
from WinUx.dialogs.server_notepad_dialog import ServerNotepadDialog

ROOT = Path(__file__).resolve().parents[1]


def text(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_qprocess_communicate_marks_completed_process_finished():
    process = QProcess(childLabel="test")
    native = mock.Mock()
    native.pid = 4321
    native.communicate.return_value = (b"ok", b"")
    native.poll.return_value = 7
    process._process = native
    process._state = process.Running

    output = process.communicate()

    assert output == (b"ok", b"")
    assert process.state() == process.NotRunning
    assert process.exitCode() == 7


def test_server_notepad_uses_qprocess_and_bounded_tree_reap():
    source = text("WinUx/dialogs/server_notepad_dialog.py")
    assert "QProcess.launch(" in source
    assert "subprocess.Popen(" not in source
    assert "process.close(timeout=max(0.0, float(timeout)), force=True)" in source
    assert "if process is not None and process.poll() is not None:" in source


def test_server_notepad_registry_entry_survives_failed_reap():
    process = mock.Mock()
    process.poll.return_value = None
    with mock.patch(
        "WinUx.dialogs.server_notepad_dialog.unregister_child_process"
    ) as unregister:
        ServerNotepadDialog._reap_process(process, 0.01)
    process.close.assert_called_once_with(timeout=0.01, force=True)
    unregister.assert_not_called()


def test_legacy_process_folder_chooser_is_removed():
    assert not (ROOT / "WinUx/services/folder_chooser.py").exists()
    assert not (ROOT / "WinUx/services/folder_chooser_process.py").exists()
    source = text("WinUx/dialogs/local_folder_form.py")
    assert "DearUIQt" in source
    assert "self.runAsync(" in source
