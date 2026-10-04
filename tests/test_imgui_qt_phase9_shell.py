from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "widgets" / "imgui_qt_style.py"
DOCK = ROOT / "WinUx" / "components" / "dock_widget.py"
VIEW = ROOT / "WinUx" / "view.py"
SPLITTER = ROOT / "WinUx" / "ui" / "splitter_layout.py"
PLOTS = ROOT / "WinUx" / "components" / "job_plots.py"
TOOLTIP = ROOT / "WinUx" / "components" / "tooltip.py"


def test_shell_foundation_exposes_shared_dock_panel_and_splitter_themes():
    source = STYLE.read_text(encoding="utf-8")
    for token in (
        "def panel_surface_theme", "def dock_frame_theme", "def dock_title_theme",
        "def dock_content_theme", "def dock_control_theme", "def splitter_theme",
        "def splitter_hitbox_theme",
    ):
        assert token in source


def test_dock_widget_uses_shared_title_controls_and_qtooltip_surface():
    source = DOCK.read_text(encoding="utf-8")
    assert "dock_frame_theme(dpg)" in source
    assert "dock_title_theme(dpg, active=True)" in source
    assert "dock_content_theme(dpg)" in source
    assert "dock_control_theme(dpg, close=True)" in source
    assert 'add_styled_tooltip(self.close_button, "Close")' in source
    assert "_sync_close_glyph_visual" in source


def test_all_workspace_splitters_share_one_visual_contract_and_active_feedback():
    view = VIEW.read_text(encoding="utf-8")
    splitter = SPLITTER.read_text(encoding="utf-8")
    assert "splitter_theme(dpg, active=False)" in view
    assert "splitter_theme(dpg, active=True)" in view
    assert "splitter_hitbox_theme(dpg)" in view
    for item in (
        "self.file_panel_separator", "self.horizontal_splitter",
        "self.console_separator", "self.job_plot_separator",
    ):
        assert item in splitter
    assert "self._plot_splitter_hover_theme" in splitter


def test_plot_panels_and_dynamic_tooltips_use_shared_qt_fusion_surfaces():
    plots = PLOTS.read_text(encoding="utf-8")
    assert "panel_surface_theme(" in plots
    assert "checkbox_theme(dpg)" in plots
    assert "tooltip_theme()" in plots
    tooltip = TOOLTIP.read_text(encoding="utf-8")
    assert "QtFusionPalette" in tooltip
    assert "hide_on_activity=True" in tooltip


def test_shell_phase_remains_dear_imgui_only():
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (STYLE, DOCK, VIEW, SPLITTER, PLOTS, TOOLTIP)
    )
    assert "PyQt" not in combined
    assert "PySide" not in combined
    assert "tkinter" not in combined
