from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py"


def test_icon_helpers_resolve_dearuiqt_layout_cells_to_native_parent_tags():
    source = FORM.read_text(encoding="utf-8")
    assert 'def _native_parent_tag(parent):' in source
    assert 'tag = getattr(parent, "tag", None)' in source
    assert 'layout_tag = getattr(parent, "_layout_tag", None)' in source
    assert 'host = dpg.add_group(parent=self._native_parent_tag(parent)' in source
    assert 'parent=self._native_parent_tag(parent),' in source


def test_manual_command_cells_are_allowed_to_remain_qgridlayout_wrappers():
    source = FORM.read_text(encoding="utf-8")
    assert 'parent=self.manual_commands.cell(0, 0)' in source
    assert 'parent=self.manual_commands.cell(0, 1)' in source
