from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_folder_browser_themes_use_dearuiqt_theme_contract_not_renderer_constants():
    source = (ROOT / "WinUx/dialogs/folder_browser_style.py").read_text(encoding="utf-8")
    assert "ThemeTarget" in source and "theme_component" in source and "make_theme" in source
    assert "dpg.mvThemeCol_" not in source
    assert "dpg.mvStyleVar_" not in source
    assert len(re.findall(r"\\bdpg\\.", source)) <= 20


def test_toolbar_search_themes_use_dearuiqt_theme_contract():
    source = (ROOT / "WinUx/ui/components/toolbar.py").read_text(encoding="utf-8")
    assert "ThemeTarget" in source and "theme_component" in source
    assert "dpg.mvThemeCol_" not in source
    assert "dpg.mvStyleVar_" not in source


def test_winux_theme_factories_no_longer_require_renderer_argument():
    files = [
        ROOT / "WinUx/view.py",
        ROOT / "WinUx/dialogs/transfer_center_form.py",
        ROOT / "WinUx/dialogs/job_manager_form.py",
        ROOT / "WinUx/dialogs/job_schedule_form.py",
        ROOT / "WinUx/plotdigitizer/ui/dialog.py",
        ROOT / "WinUx/ui/components/job_plots.py",
        ROOT / "WinUx/ui/components/toolbar.py",
    ]
    joined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    forbidden = (
        "application_theme(dpg", "splitter_theme(dpg", "splitter_hitbox_theme(dpg",
        "aligned_cell_theme(dpg", "compact_stack_theme(dpg", "transfer_list_theme(dpg",
        "transfer_row_theme(dpg", "form_row_theme(dpg", "progress_theme(dpg",
        "panel_header_theme(dpg", "transparent_header_cell_theme(dpg",
        "imgui_tool_bar_theme(dpg", "imgui_tool_button_theme(dpg",
    )
    assert not any(token in joined for token in forbidden)


def test_winux_raw_renderer_calls_are_reduced_from_r82_baseline():
    calls = 0
    direct_imports = []
    for path in (ROOT / "WinUx").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        calls += len(re.findall(r"\\bdpg\\.", source))
        if re.search(r"^\\s*(?:from|import)\\s+dearpygui\\b", source, re.MULTILINE):
            direct_imports.append(path)
    assert direct_imports == []
    assert calls <= 2400
