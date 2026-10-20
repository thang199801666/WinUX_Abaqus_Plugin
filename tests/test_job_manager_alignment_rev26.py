from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "WinUx" / "dialogs" / "job_manager_form.py").read_text(encoding="utf-8")


def test_job_manager_table_fills_body_without_reserved_status_strip():
    assert "height=-1, width=-1, resizable=True" in SOURCE
    assert "height=-22" not in SOURCE


def test_job_manager_status_is_owned_by_button_box_middle_slot():
    assert "status_item=self.status" in SOURCE


def test_job_manager_mixed_controls_use_qtablewidget_cell_layouts():
    assert "QTableWidget(" in SOURCE
    assert "def cell(column, top=0):" in SOURCE
    assert "QVBoxLayout(parent=native_row" in SOURCE
    assert "aligned_cell_theme()" in SOURCE
    assert "centered_checkbox_cell" in SOURCE
    assert "dpg.table_row(" not in SOURCE
    assert "dpg.add_table_column(" not in SOURCE


def test_product_version_matches_current_release_line():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.4"
