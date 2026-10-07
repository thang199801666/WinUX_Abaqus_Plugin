"""Static contracts for WinUx 1.1.0 Qt component polish revision 13."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_local_folder_browser_uses_shared_qt_controls_and_item_view_chrome():
    src = read("dialogs/local_folder_form.py")
    assert "qt_item_view_theme" in src
    assert "dpg.bind_item_theme(self.table, browser_details_theme())" in src
    assert 'self.view_mode = self.combo(' in src
    assert 'folder_form = self.form_layout(' in src
    assert 'height=23' in src


def test_folder_browser_toolbar_uses_compact_layout_metrics():
    style = read("dialogs/folder_browser_style.py")
    address = read("dialogs/folder_browser_address.py")
    assert "def browser_layout_theme(" in style
    assert "height=26" in style
    assert "browser_layout_theme(cell_padding=(1, 0))" in address
    assert "height=27" in address


def test_job_edit_summary_uses_shared_summary_grid_not_raw_table():
    dialog = read("dialogs/qt_dialog.py")
    edit = read("dialogs/job_edit_form.py")
    assert "def summary_grid(self, items" in dialog
    assert "self.summary_grid(" in edit
    assert "with dpg.table(parent=summary" not in edit


def test_settings_long_sections_use_one_qformlayout_per_section():
    src = read("dialogs/settings_form.py")
    assert 'form = self.form_layout(parent=cores, label_width=132)' in src
    assert 'form = self.form_layout(parent=update_source, label_width=158)' in src
    assert 'form = self.form_layout(parent=qstat, label_width=186)' in src
    assert 'form = self.form_layout(parent=odb, label_width=210)' in src
    assert src.count("self.form_layout_row(") >= 18


def test_auxiliary_folder_forms_use_shared_form_layout():
    server = read("dialogs/server_path_form.py")
    sync = read("dialogs/sync_preview_form.py")
    assert 'form = self.form_layout(parent=self.content, label_width=88)' in server
    assert 'paths_form = self.form_layout(parent=self.content, label_width=54)' in sync
    assert 'self.local_path = self.form_layout_row(' in sync
    assert 'self.server_path = self.form_layout_row(' in sync


def test_product_version_remains_fixed_at_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
