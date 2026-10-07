"""Alignment regression retained after replacing overlay rows in 1.1.27."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_folder_name_row_uses_one_compact_horizontal_line():
    source = FORM.read_text(encoding="utf-8")
    assert "name = dpg.add_group(parent=row, horizontal=True, horizontal_spacing=4)" in source
    assert "dpg.add_image(texture, parent=name, width=16, height=16)" in source
    assert "tag, label=item.text, width=0, height=METRICS.row_height" in source


def test_full_row_selection_is_kept_without_name_overlay_text():
    source = FORM.read_text(encoding="utf-8")
    assert "self.backend.highlight_table_row(self.table, row_index, color)" in source
    assert "self.name_texts" not in source
