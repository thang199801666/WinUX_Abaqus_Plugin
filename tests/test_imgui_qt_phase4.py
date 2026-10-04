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
        'mark = "✓"',
        '"›" if spec.get("children")',
        "def _row_hovered",
        "def _show_submenu",
    ):
        assert token in source


def test_job_viewer_is_migrated_from_explorer_to_imgui_data_grid():
    source = JOBS.read_text(encoding="utf-8")
    assert "ImGuiDataGridView" in source
    assert "QtGridRow" in source
    assert "ExplorerListView" not in source
    assert "ListViewItem" not in source


def test_job_grid_preserves_odb_plots_menu_runtime_state():
    source = JOBS.read_text(encoding="utf-8")
    for token in (
        '"action": "job_check_odb"',
        '"action": "job_extract_odb"',
        '"action": "job_plots"',
        "set_context_menu_item_checked",
        "set_context_menu_item_enabled",
        "selectedRows()",
    ):
        assert token in source
