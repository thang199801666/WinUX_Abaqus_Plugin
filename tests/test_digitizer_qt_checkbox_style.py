"""Static guard for the compact Qt/Fusion Plot Digitizer checkbox style."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "WinUx" / "plotdigitizer" / "ui" / "checklist.py"


def _assignments(tree):
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except Exception:
                pass
    return values


def test_compact_qt_checkbox_geometry():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    values = _assignments(tree)
    assert values["CHECKBOX_ROUNDING"] == 2
    assert values["CHECKBOX_LEFT"] == 7
    assert values["CHECKBOX_TOP"] == 5
    assert values["CAPTION_START_X"] == 29


def test_qt_checkbox_theme_uses_fusion_roles_and_zero_padding():
    text = SOURCE.read_text(encoding="utf-8")
    assert "ThemeStyle.FRAME_PADDING: (0, 0)" in text
    assert "ThemeColor.CHECK_MARK: p.TEXT if enabled else p.TEXT_DISABLED" in text
    assert "ThemeColor.FRAME_BACKGROUND_HOVERED: p.HIGHLIGHT_HOVER" in text
    assert "p.FOCUS if focused else p.BORDER" in text


def test_workflow_semantic_fill_stays_subtle():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DigitizerCheckList")
    values = {}
    for node in cls.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except Exception:
                pass
    # Both status fills stay close to white; they should read as row status,
    # not as a filled button behind the checkbox.
    assert min(values["COMPLETE"][:3]) >= 240
    assert min(values["UNFINISHED"][:3]) >= 240
