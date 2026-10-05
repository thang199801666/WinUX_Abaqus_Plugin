from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_menu_bar_binds_roomy_theme_instead_of_inheriting_compact_app_spacing():
    view = _read("view.py")
    style = _read("widgets/imgui_qt_style.py")
    block = view[view.index("    def _build_menu(self):"):view.index(
        "    @staticmethod\n    def _add_icon_menu_item", view.index("    def _build_menu(self):"))]
    assert "menu_theme = resource_menu_theme()" in block
    assert "dpg.bind_item_theme(menu_bar, menu_theme)" in block
    assert "for root_menu in (file_menu, bookmarks_menu, commands_menu, view_menu, help_menu)" in block
    assert "mvStyleVar_ItemSpacing, 4, 1" in style
    assert "mvStyleVar_FramePadding, 8, 3" in style


def test_file_toolbar_restores_pre_migration_height_and_button_density():
    toolbar = _read("components/toolbar.py")
    assert "COLLAPSED_HEIGHT = 36" in toolbar
    assert "SEARCH_ROW_HEIGHT = 32" in toolbar
    assert "mvStyleVar_CellPadding, 0, 3" in toolbar
    assert "width=28, height=26" in toolbar
    # Rev8 keeps the pre-migration toolbar density but uses the normal Windows
    # application face for the path field, matching QLineEdit/QComboBox rather
    # than the earlier bold heading treatment.
    assert 'windir / "Fonts" / "segoeui.ttf"' in toolbar
    assert 'dpg.add_font(str(font_path), 14)' in toolbar


def test_job_viewer_has_dedicated_qt_header_theme_and_standard_sort_marker():
    jobs = _read("components/jobs_view.py")
    themes = _read("components/explorer_themes.py")
    layout = _read("components/explorer_layout.py")
    assert "theme=ListViewTheme.JOB_VIEWER" in jobs
    assert 'JOB_VIEWER = "Job Viewer"' in themes
    assert '"header_alignment": "column"' in themes
    assert '"sort_indicator_mode": "edge"' in themes
    assert 'indicator_mode = self.theme_config.get("sort_indicator_mode", "edge")' in layout
    assert 'indicator_mode = self.theme_config.get("sort_indicator_mode", "edge")' in layout


def test_job_viewer_has_direct_right_click_fallback_without_replacing_primary_dispatch():
    jobs = _read("components/jobs_view.py")
    assert "def _install_context_menu_fallback" in jobs
    assert "dpg.mvMouseButton_Right" in jobs
    assert "self.listview._context_menu_is_visible()" in jobs
    assert "self.listview._on_right_click()" in jobs
    assert "dpg.set_frame_callback(dpg.get_frame_count() + 1, ensure_menu)" in jobs


def test_combo_and_spin_arrows_are_geometry_not_font_glyphs():
    combo = _read("components/qt_combo_box.py")
    controls = _read("widgets/controls.py")
    assert "self.button = dpg.add_combo(" in combo
    assert "no_preview=True" in combo
    assert "with dpg.theme_component(dpg.mvCombo):" in combo
    assert 'label="v"' not in combo
    assert "def _create_spin_arrow" in controls
    assert "backend.draw_triangle(" in controls
    assert 'label="^"' not in controls
    assert 'label="v"' not in controls


def test_login_returns_to_compact_pre_migration_form_without_connection_groupbox():
    form = _read("dialogs/login_form.py")
    host = _read("dialogs/login_dialog.py")
    assert 'super().__init__(view, "SSH Login", 420, 204)' in form
    assert 'self.preferred_size = (420, 184)' in form
    assert 'self._form = self.form_layout(parent=self.content, label_width=78)' in form
    assert '"Host:", initial.get("hosts"' in form
    assert 'self._line_field("Port:"' in form
    assert '"Username:", initial.get("usernames"' in form
    assert 'self._line_field(' in form and '"Password:"' in form
    assert 'self.section("Connection")' not in form
    assert "width=420, height=226" in host


def test_phase15_main_ui_stays_dear_imgui_only():
    source = "\n".join(_read(path) for path in (
        "view.py",
        "components/toolbar.py",
        "components/jobs_view.py",
        "components/explorer_layout.py",
        "components/qt_combo_box.py",
        "dialogs/login_form.py",
        "widgets/controls.py",
    ))
    for forbidden in ("import tkinter", "from tkinter", "PyQt6", "PySide6"):
        assert forbidden not in source
