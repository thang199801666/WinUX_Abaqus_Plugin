from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_explorer_toolbar_uses_compact_qtoolbar_metrics_without_shrinking_path_field():
    src = read("components/toolbar.py")
    assert "COLLAPSED_HEIGHT = 36" in src
    assert "SEARCH_ROW_HEIGHT = 32" in src
    assert "init_width_or_weight=32" in src
    assert "width=28, height=26" in src
    assert "width=18" in src and "height=18" in src
    assert "height=26" in src


def test_main_menu_command_rows_keep_icon_gutter_and_reduce_excess_width():
    src = read("view.py")
    block = src[src.index("    def _build_menu(self):"):src.index("    def show_manual", src.index("    def _build_menu(self):"))]
    assert "horizontal_spacing=7" in block
    assert "width=184" in block
    assert "with dpg.menu_bar() as menu_bar" in block


def test_qheaderview_reserves_sort_space_only_when_needed_and_keeps_drag_line_thin():
    layout = read("components/explorer_layout.py")
    view = read("components/explorer_list_view.py")
    assert "right_reserve = 24.0 if sorted_column else 14.0" in layout
    assert "column_width - right_reserve" in layout
    assert "elif not self._header_sections_clickable" in view
    block = view.split("def _set_separator_hover_state", 1)[1].split("def _update_resize_cursor", 1)[0]
    assert "thickness=1.0" in block
    assert "thickness=2.0" not in block


def test_dock_title_controls_use_larger_hit_target_without_larger_titlebar():
    src = read("components/dock_widget.py")
    assert "TITLE_HEIGHT = 22" in src
    assert "CONTROL_SIZE = 20" in src
    assert "CONTROL_GAP = 0" in src
    assert "half = self.CONTROL_SIZE / 2.0" in src


def test_dialog_forms_share_one_qformlayout_table_for_related_fields():
    site = read("dialogs/site_manager_form.py")
    edit = read("dialogs/job_edit_form.py")
    assert "form = self.form_layout(parent=details)" in site
    assert "self.form_layout_row(" in site
    assert "form = self.form_layout(parent=schedule)" in edit
    assert edit.count("self.form_layout_row(") >= 3


def test_product_version_remains_fixed_at_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
