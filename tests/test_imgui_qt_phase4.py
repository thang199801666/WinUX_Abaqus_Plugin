from pathlib import Path

from WinUx.widgets.menu import _normalize_action

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ROOT / "WinUx" / "widgets"
JOBS = ROOT / "WinUx" / "components" / "jobs_view.py"


def test_menu_spec_preserves_texture_icon_for_imgui_renderer():
    marker = object()
    item = _normalize_action({"label": "Open", "action": "open", "icon": marker})
    assert item["icon"] is marker


def test_imgui_menu_renders_icon_check_and_hover_submenu_slots():
    source = (WIDGETS / "menu.py").read_text(encoding="utf-8")
    for token in (
        "b.add_image(icon",
        "def _redraw_check",
        "def _redraw_submenu_arrow",
        "b.add_drawlist(width=self.CHECK_SLOT",
        "b.add_drawlist(width=self.ARROW_SLOT",
        "def _row_hovered",
        "def _show_submenu",
    ):
        assert token in source
    assert "✓" not in source
    assert "›" not in source


def test_job_viewer_uses_restored_explorer_details_view_contract():
    source = JOBS.read_text(encoding="utf-8")
    assert "ExplorerListView" in source
    assert "ListViewItem" in source
    assert "ImGuiDataGridView" not in source
    assert "theme=ListViewTheme.JOB_VIEWER" in source


def test_job_viewer_preserves_odb_plots_menu_runtime_state():
    source = JOBS.read_text(encoding="utf-8")
    for token in (
        '"action": "job_check_odb"',
        '"action": "job_extract_odb"',
        '"action": "job_plots"',
        "set_context_menu_item_checked",
        "set_context_menu_item_enabled",
        "self.listview.get_selected()",
    ):
        assert token in source
