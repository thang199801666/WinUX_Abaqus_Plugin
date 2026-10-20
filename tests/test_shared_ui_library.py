"""Guards for the standalone :mod:`DearUIQt` wrapper and WinUx UI boundary."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_dearuiqt_is_the_only_physical_reusable_wrapper_root():
    library = ROOT / "DearUIQt"
    ui = ROOT / "WinUx" / "ui"
    assert library.is_dir()
    assert (library / "qt").is_dir()
    assert (library / "docking").is_dir()
    assert (library / "dialogs").is_dir()
    assert (ui / "components").is_dir()
    assert (ui / "behaviors").is_dir()
    assert not (ui / "framework").exists()
    for legacy in ("shared_ui", "ui_framework", "widgets", "components"):
        assert not (ROOT / "WinUx" / legacy).exists()


def test_dearuiqt_core_import_is_lightweight():
    code = '''
import sys
from DearUIQt import QObject, QTimer, QThreadPool, QtConcurrent
assert 'dearpygui.dearpygui' not in sys.modules
f = QtConcurrent.run(lambda: 42)
assert f.result(timeout=2) == 42
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        env={**__import__('os').environ, 'PYTHONPATH': str(ROOT)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_dearuiqt_does_not_import_winux():
    source = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "DearUIQt").rglob("*.py")
    )
    assert "from WinUx" not in source
    assert "import WinUx" not in source


def test_winux_source_uses_dearuiqt_not_removed_framework_namespace():
    source = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "WinUx").rglob("*.py")
    )
    assert "WinUx.ui.framework" not in source
    assert "WinUx.shared_ui" not in source
    assert "WinUx.ui_framework" not in source
    assert "WinUx.widgets" not in source


def test_exporter_copies_root_dearuiqt_package(tmp_path):
    from tools.export_ui_framework import export_framework
    output = export_framework(tmp_path / "library", import_package="portable_ui")
    assert (output / "portable_ui" / "qt" / "core.py").is_file()
    assert (output / "portable_ui" / "docking" / "dock_widget.py").is_file()
    assert (output / "portable_ui" / "widgets" / "color_field.py").is_file()
    assert not list(output.rglob("*.md"))
    assert not list(output.rglob("*.markdown"))
