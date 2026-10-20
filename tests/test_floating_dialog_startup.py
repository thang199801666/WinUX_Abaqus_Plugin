"""Keep cold imports small and nested selector prewarming bounded."""
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest


def test_factory_import_does_not_load_concrete_forms():
    root = Path(__file__).resolve().parents[1]
    script = """
import json, sys
import WinUx.dialogs.floating_forms
print(json.dumps(sorted(name for name in sys.modules
    if name.startswith('WinUx.dialogs.') and name.endswith('_form'))))
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=str(root),
                            capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(result.stdout.strip()) == []


def test_shared_appearance_import_does_not_load_browser_or_ribbon():
    root = Path(__file__).resolve().parents[1]
    script = """
import json, sys
import WinUx.ui.appearance
print(json.dumps(sorted(name for name in sys.modules if name in (
    'WinUx.dialogs.local_file_form', 'WinUx.dialogs.local_folder_form',
    'WinUx.ui.ribbon', 'WinUx.ui.file_dialog'))))
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=str(root),
                            capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(result.stdout.strip()) == []


def test_shared_facade_keeps_every_public_export_resolvable_and_cached():
    import WinUx.ui as shared
    assert set(shared.__all__) == set(shared._LAZY_EXPORTS)
    for name in shared.__all__:
        assert name in dir(shared)
        value = getattr(shared, name)
        assert shared.__dict__[name] is value
        assert getattr(shared, name) is value
    with pytest.raises(AttributeError):
        getattr(shared, "not_a_public_control")


@pytest.mark.parametrize("kind,live,existing,expected", [
    ("plotdigitizer", True, False, True),
    ("plotdigitizer", False, False, False),
    ("plotdigitizer", True, True, False),
    ("local_file", True, False, False),
    ("local_folder", True, False, False),
])
def test_nested_pool_only_starts_for_a_live_tool_and_never_recurses(kind, live, existing, expected):
    from WinUx.dialogs.floating_runtime import FloatingDialogRuntime
    runtime = object.__new__(FloatingDialogRuntime)
    runtime.initial = {"kind": kind}
    runtime.form = SimpleNamespace(winfo_exists=lambda: live)
    runtime.view = SimpleNamespace()
    old_pool = object()
    if existing:
        runtime.view._dialog_prewarm_pool = old_pool
    with patch("WinUx.dialogs.prewarm_pool.DialogPrewarmPool") as pool:
        runtime._start_selector_prewarm()
        if expected:
            pool.assert_called_once_with(capacity=1, reusable=True)
            assert runtime.view._dialog_prewarm_pool is pool.return_value
            runtime._start_selector_prewarm()
            pool.assert_called_once()
        else:
            pool.assert_not_called()
            if existing:
                assert runtime.view._dialog_prewarm_pool is old_pool


def test_closing_host_closes_nested_pool_before_dialogs():
    from WinUx.dialogs.floating_dialog import close_floating_dialogs
    calls = []
    pool = SimpleNamespace(close=lambda: calls.append("pool"))
    dialog = MagicMock()
    dialog.destroy.side_effect = lambda **kwargs: calls.append("dialog")
    view = SimpleNamespace(_dialog_prewarm_pool=pool, _floating_dialogs={dialog})
    close_floating_dialogs(view)
    assert calls == ["pool", "dialog"]
    assert view._floating_focus_suppressed


def reusable_pool():
    from WinUx.dialogs.prewarm_pool import DialogPrewarmPool
    pool = object.__new__(DialogPrewarmPool)
    pool.capacity, pool.reusable = 1, True
    pool._closed = False
    pool._lock = threading.Lock()
    pool._workers = []
    worker = MagicMock()
    worker.lease = "current"
    worker.source_signature = ("source",)
    worker.closed = False
    worker.process.poll.return_value = None
    worker.reuse_count = 0
    worker.idle_ack = False
    worker.source_epoch = None
    pool._leased = {worker}
    pool.refill = MagicMock()
    return pool, worker


def test_old_lease_cannot_return_or_retire_a_current_host():
    pool, worker = reusable_pool()
    with patch("WinUx.dialogs.prewarm_pool.runtime_source_signature", return_value=("source",)):
        assert not pool.release(worker, "old")
        pool.retire(worker, "old")
    assert worker in pool._leased
    worker.close.assert_not_called()
    assert not pool._workers


def test_host_is_returned_only_once_and_capacity_remains_bounded():
    pool, worker = reusable_pool()
    with patch("WinUx.dialogs.prewarm_pool.runtime_source_signature", return_value=("source",)):
        assert pool.release(worker, "current")
        assert not pool.release(worker, "current")
    assert pool._workers == [worker]
    assert not pool._leased
    assert worker.reuse_count == 1
    worker.ready.set.assert_called_once()


@pytest.mark.parametrize("reason", ["source", "shutdown", "exit"])
def test_unclean_or_outdated_hosts_are_retired_instead_of_reused(reason):
    pool, worker = reusable_pool()
    signature = ("changed",) if reason == "source" else ("source",)
    if reason == "shutdown":
        pool._closed = True
    elif reason == "exit":
        worker.process.poll.return_value = 1
    with patch("WinUx.dialogs.prewarm_pool.runtime_source_signature", return_value=signature):
        assert not pool.release(worker, "current")
    worker.close.assert_called_once()
    assert not pool._workers and not pool._leased


def test_pool_shutdown_closes_idle_and_active_hosts():
    pool, active = reusable_pool()
    idle = MagicMock()
    pool._workers = [idle]
    pool.close()
    idle.close.assert_called_once()
    active.close.assert_called_once()
    assert pool._closed and not pool._workers and not pool._leased


@pytest.mark.parametrize("reusable", [False, True])
def test_stale_commands_cannot_mutate_any_next_lease_even_a_non_reusable_tool(reusable):
    from WinUx.dialogs.floating_runtime import FloatingDialogRuntime
    runtime = object.__new__(FloatingDialogRuntime)
    runtime.lease = "new"
    runtime.reusable = reusable
    runtime.form = MagicMock()
    with patch("WinUx.dialogs.floating_runtime.deliver_command") as deliver:
        assert runtime._handle_command({"command": "close", "lease": "old"})
        assert runtime._handle_command({"command": "open_image", "lease": "old", "args": ["old.png"]})
        runtime.form.destroy.assert_not_called()
        deliver.assert_not_called()
        assert not runtime._handle_command({"command": "close", "lease": "new"})
        runtime.form.destroy.assert_called_once()


@pytest.mark.parametrize("requested,allowed,expected", [(True, True, True), (True, False, False), (False, True, False)])
def test_host_reuse_is_negotiated_before_publication(requested, allowed, expected):
    from WinUx.dialogs.floating_dialog import FloatingDialogController
    controller = object.__new__(FloatingDialogController)
    controller._closed = False
    controller._reuse_host = requested
    controller._visible = True
    controller.modal = False
    controller._accept_native_hwnd = MagicMock()
    controller.post = MagicMock()
    controller._deliver_event({"event": "prepared", "reuse_host": allowed})
    assert controller._reuse_host is expected
    controller.post.assert_called_once_with("publish")


def test_reuse_capability_is_explicit_and_conservative():
    from WinUx.dialogs.qt_dialog import QtDialog
    from WinUx.dialogs.login_form import LoginForm
    from WinUx.dialogs.odb_check_form import ODBCheckDialog
    from WinUx.dialogs.odb_extract_form import ODBExtractDialog, ODBXYResultDialog
    from WinUx.dialogs.local_file_form import LocalFileDialog
    from WinUx.dialogs.settings_form import SettingsDialog
    from WinUx.dialogs.server_path_form import ServerPathDialog
    from WinUx.dialogs.job_edit_form import JobEditDialog
    from WinUx.dialogs.job_manager_form import JobManagerDialog
    from WinUx.plotdigitizer.ui import PlotDigitizerDialog
    assert not QtDialog.REUSABLE_HOST
    for form_type in (LoginForm, ODBCheckDialog, ODBExtractDialog, ODBXYResultDialog,
                      LocalFileDialog, SettingsDialog, ServerPathDialog,
                      JobEditDialog, JobManagerDialog):
        assert form_type.REUSABLE_HOST
    assert not PlotDigitizerDialog.REUSABLE_HOST


@pytest.mark.parametrize("authorized,owner,lease,fast,expected", [
    (42, 90, "lease", True, True), (43, 90, "lease", True, False),
    (42, 42, "lease", True, False), (42, 90, None, True, False),
    (42, 90, "lease", False, False), (True, 90, "lease", True, False),
    (None, 90, "lease", True, False),
])
def test_publish_preapproval_requires_the_exact_authenticated_host(authorized, owner, lease, fast, expected):
    from WinUx.dialogs.floating_runtime import _publish_preauthorized
    initial = {"authorized_hwnd": authorized, "owner_hwnd": owner, "lease": lease, "fast_startup": fast}
    assert _publish_preauthorized(initial, SimpleNamespace(native=SimpleNamespace(hwnd=42))) is expected
    assert not _publish_preauthorized(initial, None)


@pytest.mark.parametrize("change,fast,expected", [
    ({}, True, 1), ({}, False, 2), ({0: "login"}, True, 2),
    ({1: 900}, True, 2), ({2: 700}, True, 2), ({3: 0}, True, 2),
    ({3: 192}, True, 2), ({4: False}, True, 2), ({5: True}, True, 2),
])
def test_short_layout_path_requires_an_identical_known_contract(change, fast, expected):
    from WinUx.dialogs.floating_runtime import _settle_frame_count
    original = ("local_file", 840, 580, 96, True, False, False)
    spec = list(original)
    for index, value in change.items():
        spec[index] = value
    assert _settle_frame_count(SimpleNamespace(last_layout_spec=original), tuple(spec), fast) == expected
    assert _settle_frame_count(None, tuple(spec), fast) == 3
    assert _settle_frame_count(SimpleNamespace(last_layout_spec=None), tuple(spec), fast) == 2


@pytest.mark.parametrize("minimize,maximize", [(True, False), (False, True), (True, True)])
def test_minimizable_or_maximizable_hosts_keep_conservative_layout(minimize, maximize):
    from WinUx.dialogs.floating_runtime import _settle_frame_count
    spec = ("local_file", 840, 580, 96, True, minimize, maximize)
    assert _settle_frame_count(SimpleNamespace(last_layout_spec=spec), spec, True) == 2


def test_same_metadata_with_a_new_source_epoch_cannot_reuse_a_host():
    from WinUx.dialogs.source_signature_cache import SourceSnapshot
    pool, worker = reusable_pool()
    worker.source_epoch = 2
    pool._source_cache = SimpleNamespace(failed=False, generation=3,
        snapshot=lambda: SourceSnapshot(("source",), 3))
    with patch("WinUx.dialogs.prewarm_pool.runtime_source_signature", side_effect=AssertionError("UI scan")):
        assert not pool.release(worker, "current")
    worker.close.assert_called_once()


def test_pending_source_validation_parks_idle_host_until_background_refresh():
    from WinUx.dialogs.source_signature_cache import SourceSnapshot
    pool, worker = reusable_pool()
    worker.source_epoch = 2
    pool._source_cache = SimpleNamespace(failed=False, generation=2, snapshot=lambda: None)
    with patch("WinUx.dialogs.prewarm_pool.runtime_source_signature", side_effect=AssertionError("UI scan")):
        assert not pool.release(worker, "current")
    assert pool._workers == [worker] and worker.idle_ack
    worker.close.assert_not_called()
    worker.ready.set.assert_not_called()
    pool._refresh_identity(SourceSnapshot(("source",), 2))
    worker.ready.set.assert_called_once()


def test_child_error_retains_lease_so_parent_does_not_drop_actionable_traceback():
    import json
    from WinUx.services import floating_dialog_process as process
    connection = MagicMock()
    initial = {"command": "init", "kind": "unknown", "lease": "current"}
    runtime = SimpleNamespace(stage="create-form:unknown", run=Mock(side_effect=ValueError("synthetic failure")))
    with patch.dict("os.environ", {"WINUX_FLOAT_DIALOG_PORT": "12345", "WINUX_FLOAT_DIALOG_TOKEN": "test", "WINUX_FLOAT_DIALOG_PREWARM": "0"}), \
            patch.object(process.socket, "create_connection", return_value=connection), \
            patch.object(process, "read_messages", return_value=iter([initial])), \
            patch.object(process, "FloatingDialogRuntime", return_value=runtime):
        assert process.main() == 1
    error = json.loads(connection.sendall.call_args_list[-1].args[0])
    assert error["event"] == "error" and error["lease"] == "current"
    assert "synthetic failure" in error["traceback"]


def test_failed_watch_falls_back_to_scan_without_trusting_a_pre_failure_host():
    pool, worker = reusable_pool()
    worker.source_epoch = 2
    pool._source_cache = SimpleNamespace(failed=True, generation=3,
        snapshot=Mock(side_effect=AssertionError("failed watch must not be used")))
    with patch("WinUx.dialogs.prewarm_pool.runtime_source_signature", return_value=("source",)) as scan:
        assert not pool.release(worker, "current")
        scan.assert_called_once()
    worker.close.assert_called_once()
