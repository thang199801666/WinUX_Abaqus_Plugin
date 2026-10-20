import sys
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from DearUIQt.qt.process import QProcess
from WinUx.ui.hosting.host import (
    DialogPrewarmPool,
    PreparedWorker,
    QDialogHost,
    QDialogHostManager,
    QDialogHostPool,
    QDialogLease,
    dialog_host_manager,
)


def fake_host(*, reusable=True, reuse_count=0, lease="lease"):
    return SimpleNamespace(
        token="token", lease=lease, reusable=reusable, reuse_count=reuse_count,
        process=MagicMock(), listener=MagicMock(), connection=None, messages=None,
        hwnd=42, log_path="dialog.log", close=MagicMock(),
    )


def test_legacy_host_names_are_aliases_not_duplicate_implementations():
    assert PreparedWorker is QDialogHost
    assert DialogPrewarmPool is QDialogHostPool


def test_dialog_host_manager_prefers_warm_host_and_returns_one_lease_object():
    host = fake_host(reuse_count=3)
    pool = MagicMock(reusable=True)
    pool.claim.return_value = host
    view = SimpleNamespace(_dialog_host_pool=pool, _dialog_prewarm_pool=pool)
    manager = QDialogHostManager(view, pool)

    lease = manager.acquire("settings")

    assert isinstance(lease, QDialogLease)
    assert lease.host is host
    assert lease.from_prewarm
    assert lease.reused
    assert lease.reusable
    pool.claim.assert_called_once_with(refill=False, kind="settings")
    pool.reserve_cold.assert_not_called()


def test_dialog_lease_release_and_retire_are_idempotent():
    host = fake_host()
    manager = MagicMock()
    lease = QDialogLease(manager, host, from_prewarm=True, pooled=True)
    manager.release.return_value = True

    assert lease.release()
    assert not lease.release()
    assert not lease.retire()
    manager.release.assert_called_once_with(lease)
    manager.retire.assert_not_called()


def test_dialog_host_manager_is_one_service_per_view_and_syncs_legacy_pool():
    view = SimpleNamespace()
    first = dialog_host_manager(view)
    second = dialog_host_manager(view)
    assert first is second
    assert view._dialog_host_pool is view._dialog_prewarm_pool
    first.close()



def test_dialog_lease_cancel_has_terminal_state_and_retires_once():
    host = fake_host()
    manager = MagicMock()
    lease = QDialogLease(manager, host, pooled=False)
    assert lease.state() == "active" and lease.isActive()
    assert lease.cancel()
    assert lease.state() == "cancelled" and not lease.isActive()
    assert not lease.cancel() and not lease.release()
    manager.retire.assert_called_once_with(lease)


def test_manager_shutdown_retires_unpooled_fallback_lease():
    host = fake_host(reusable=False, lease=None)
    pool = MagicMock(reusable=False)
    pool.claim.return_value = None
    view = SimpleNamespace(_dialog_host_pool=pool, _dialog_prewarm_pool=pool)
    manager = QDialogHostManager(view, pool)
    manager._track(QDialogLease(manager, host, pooled=False))
    lease = next(iter(manager._leases))
    manager.close()
    host.close.assert_called_once()
    assert lease.state() == "retired" and not lease.isActive()


def test_qprocess_wraps_subprocess_lifecycle_without_exposing_popen_to_clients():
    process = QProcess(childLabel="test-helper")
    process.startCommand([sys.executable, "-c", "pass"])
    assert process.processId() > 0
    assert process.wait(timeout=5) == 0
    assert process.state() == QProcess.NotRunning


def test_floating_controller_has_no_direct_process_or_pool_ownership():
    source = (Path(__file__).resolve().parents[1] /
              "WinUx/ui/hosting/floating_dialog.py").read_text(encoding="utf-8")
    assert "subprocess.Popen" not in source
    assert "taskkill" not in source
    assert "register_child_process" not in source
    assert ".reserve_cold(" not in source
    assert ".claim(" not in source
    assert "self._host_manager.acquire(" in source
    assert "self._host_lease.release()" in source
    assert "self._host_lease.retire()" in source


def test_shared_qt_lifecycle_exports_remain_backend_light():
    import WinUx.ui as shared
    before = set(sys.modules)
    assert shared.QProcess is QProcess
    assert shared.QDialogHostManager is QDialogHostManager
    loaded = set(sys.modules) - before
    assert not any(name.startswith("dearpygui") for name in loaded)
