import ast
from pathlib import Path

from DearUIQt.dialogs.qt_dialog import QtDialog


def _direct_dpg_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "dpg"
    )


def _backend_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("DearUIQt.backends")
    ]


def test_qtdialog_exposes_runtime_guard_for_compatibility_wait_loops():
    assert callable(getattr(QtDialog, "runtime_running", None))


def test_r94_migrated_dialogs_use_public_dearuiqt_boundaries_only():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "WinUx/dialogs/login_form.py",
        root / "WinUx/dialogs/diagnostics_form.py",
        root / "WinUx/dialogs/progress_form.py",
        root / "WinUx/dialogs/job_edit_form.py",
    ]
    for path in paths:
        assert _direct_dpg_calls(path) == 0, path
        assert not _backend_imports(path), path


def test_r94_global_direct_backend_boundary_is_below_140_calls():
    root = Path(__file__).resolve().parents[1]
    total = 0
    files = 0
    backend_import_files = 0
    for path in (root / "WinUx").rglob("*.py"):
        count = _direct_dpg_calls(path)
        if count:
            total += count
            files += 1
        if _backend_imports(path):
            backend_import_files += 1
    assert total <= 135
    assert files <= 20
    assert backend_import_files <= 21
