import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = (
    "WinUx/ui/components/explorer_rendering.py",
    "WinUx/ui/behaviors/splitter_behavior.py",
    "WinUx/plotdigitizer/ui/dialog.py",
    "WinUx/ui/components/file_panel.py",
)


def _direct_dpg_attributes(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "dpg"
    ]


def test_r90_migrated_hotspots_do_not_call_renderer_api_directly():
    for relative in TARGETS:
        assert not _direct_dpg_attributes(relative), relative


def test_explorer_splitter_and_file_panel_no_longer_import_backend_module():
    for relative in (
        "WinUx/ui/components/explorer_rendering.py",
        "WinUx/ui/behaviors/splitter_behavior.py",
        "WinUx/ui/components/file_panel.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "DearUIQt.backends" not in source, relative
