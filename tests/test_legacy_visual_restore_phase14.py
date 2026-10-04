from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "WinUx" / "view.py"
JOBS = ROOT / "WinUx" / "components" / "jobs_view.py"
LAYOUT = ROOT / "WinUx" / "components" / "explorer_layout.py"
RENDERING = ROOT / "WinUx" / "components" / "explorer_rendering.py"


def test_main_menu_keeps_native_dpg_roots_and_fixed_command_rows():
    source = VIEW.read_text(encoding="utf-8")
    block = source[source.index("    def _build_menu(self):"):source.index("    def show_manual", source.index("    def _build_menu(self):"))]
    assert "with dpg.menu_bar() as menu_bar" in block
    assert "horizontal_spacing=6" in block
    assert "width=190" in block


def test_job_viewer_uses_same_explorer_details_view_as_pre_migration_build():
    source = JOBS.read_text(encoding="utf-8")
    assert "ExplorerListView(" in source
    assert "show_column_separators=True" in source
    assert "single_selection=True" in source
    assert "set_metrics(row_height=24, header_height=28, cell_padding=5)" in source
    assert "on_context_menu_open=self._context_open" in source


def test_explorer_header_sort_indicator_is_geometry_not_font_symbol():
    rendering = RENDERING.read_text(encoding="utf-8")
    layout = LAYOUT.read_text(encoding="utf-8")
    assert "indicator_tag = dpg.draw_triangle(" in rendering
    assert "parts[\"indicator\"], p1=p1, p2=p2, p3=p3, show=True" in layout
    assert "▲" not in rendering + layout
    assert "▼" not in rendering + layout


def test_primary_imgui_ui_sources_do_not_use_decorative_unicode_glyphs():
    paths = [
        ROOT / "WinUx" / "widgets" / "menu.py",
        ROOT / "WinUx" / "widgets" / "controls.py",
        ROOT / "WinUx" / "components" / "qt_combo_box.py",
        ROOT / "WinUx" / "components" / "toolbar.py",
        ROOT / "WinUx" / "components" / "dock_widget.py",
        ROOT / "WinUx" / "components" / "explorer_list_view.py",
        ROOT / "WinUx" / "components" / "explorer_drag_preview.py",
        ROOT / "WinUx" / "components" / "job_plots.py",
    ]
    forbidden = ("✓", "›", "▲", "▼", "▴", "▾", "×", "…", "•")
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for glyph in forbidden:
        assert glyph not in source
