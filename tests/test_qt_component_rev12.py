"""Static contracts for the rev12 Qt/Fusion dialog/table polish."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_editable_job_grids_share_qtableview_chrome():
    manager = text("WinUx/dialogs/job_manager_form.py")
    schedule = text("WinUx/dialogs/job_schedule_form.py")
    dialog = text("WinUx/dialogs/qt_dialog.py")
    assert "def style_table(self, table):" in dialog
    assert "qt_item_view_theme" in dialog
    assert "self.style_table(self.table)" in manager
    assert "self.style_table(self.table)" in schedule
    assert "ROW_HEIGHT = 26" in manager


def test_transfer_rows_are_flat_qframes_not_separator_stacks():
    source = text("WinUx/dialogs/transfer_center_form.py")
    style = text("WinUx/widgets/imgui_qt_style.py")
    assert "transfer_row_theme" in source
    assert "height=72, border=True" in source
    assert "ChildRounding, 0" in style
    assert "dpg.add_separator()" not in source


def test_odb_extract_uses_side_by_side_axis_panes():
    source = text("WinUx/dialogs/odb_extract_form.py")
    assert "axes_layout = dpg.add_table" in source
    assert "for axis in (\"x\", \"y\")" in source
    assert "width=84" in source
    assert "height=125" in source
    assert "form_layout(label_width=118)" in source


def test_job_schedule_command_buttons_are_compact():
    source = text("WinUx/dialogs/job_schedule_form.py")
    assert '("Commands", 152)' in source
    assert 'width=64' in source
    assert 'width=72' in source
