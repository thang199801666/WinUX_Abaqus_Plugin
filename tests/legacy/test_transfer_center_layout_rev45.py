from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_transfer_row_layout_uses_compact_content_and_fixed_center_progress_text():
    source = FORM.read_text(encoding="utf-8")
    assert 'layout_table = dpg.add_table(parent=group' in source
    assert 'content = dpg.add_group(parent=row_parent)' in source
    assert 'controls_table = dpg.add_table(parent=content' in source
    assert 'with dpg.table_row(parent=controls_table) as progress_row:' in source
    assert 'progress_host = dpg.add_child_window(parent=progress_row, width=-1,' in source
    assert 'progress = self.progress_bar(0.0, parent=progress_host, overlay="")' in source
    assert 'percentage = dpg.add_text("0.0%", parent=progress_host)' in source
    assert 'action = self.action("Cancel", lambda: self._request_row_action(row_id),' in source
    assert 'width=self.ACTION_WIDTH, height=self.PROGRESS_HEIGHT' in source
    assert '"native_parents": (progress_row, progress_host)' in source
