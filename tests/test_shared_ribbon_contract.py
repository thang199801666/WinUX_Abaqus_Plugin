from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _ribbon_source():
    base = ROOT / "DearUIQt/ribbon"
    return "\n".join(
        (base / name).read_text(encoding="utf-8")
        for name in ("bar.py", "state.py", "internals.py")
    )


def test_shared_ribbon_exposes_one_key_based_manager():
    source = _ribbon_source()
    assert "class RibbonBar(RibbonStateMixin, RibbonInternalsMixin, QWidget):" in source
    for method in (
        "add_application_menu", "add_quick_button", "add_tab", "set_active_tab",
        "add_group", "add_button", "add_menu_button", "add_split_button",
        "set_button_enabled", "set_button_checked", "set_button_visible",
        "set_group_enabled", "set_group_visible", "toggle_minimized", "button_tag",
    ):
        assert "def {}(".format(method) in source


def test_shared_ui_facade_exports_ribbon_bar():
    source = (ROOT / "WinUx" / "ui" / "__init__.py").read_text(encoding="utf-8")
    assert '"RibbonBar": ".ribbon"' in source
    assert '"RibbonBar"' in source


def test_plot_digitizer_uses_shared_ribbon_instead_of_assembling_native_tabs():
    source = (ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py").read_text(encoding="utf-8")
    assert "RibbonBar" in source
    toolbar = source[source.index("    def _build_toolbar(self):"):source.index("    def _build_workspace(self):")]
    assert "self.ribbon.add_tab" in toolbar
    assert "self.ribbon.add_group" in toolbar
    assert "self.ribbon.add_button" in toolbar
    assert "dpg.tab_bar" not in toolbar
    assert "browser_toolbar_theme" not in source


def test_ribbon_packs_small_commands_and_supports_cad_style_chrome():
    source = _ribbon_source()
    assert "SMALL_ROWS = 3" in source
    assert "def _small_button_parent(" in source
    assert "def add_application_menu(" in source
    assert "def add_quick_button(" in source
    assert "def add_split_button(" in source
    assert "def set_minimized(" in source
    assert "_application_theme" in source


def test_plot_digitizer_omits_quick_access_and_uses_home_tab_directly():
    source = (ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py").read_text(encoding="utf-8")
    toolbar = source[source.index("    def _build_toolbar(self):"):source.index("    def _build_workspace(self):")]
    assert "quick_access=False" in toolbar
    assert "add_application_menu" not in toolbar
    assert "add_quick_button" not in toolbar
    assert 'add_tab("home", "Home"' in toolbar
    assert "_toggle_ribbon" not in toolbar


def test_sparse_plot_digitizer_ribbon_uses_only_large_commands_and_dedicated_raster_icons():
    source = (ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py").read_text(encoding="utf-8")
    toolbar = source[source.index("    def _build_toolbar(self):"):source.index("    def _build_workspace(self):")]
    assert 'layout="large"' in toolbar
    assert 'size="small"' not in toolbar
    assert 'ICON_ROOT = "plotdigitizer_icons"' in source
    assert 'image=self._icon("open_image")' in toolbar
    assert 'image=self._icon("save_project")' in toolbar
    assert 'image=self._icon("export_csv")' in toolbar


def test_ribbon_supports_auto_size_large_groups_and_png_image_commands():
    source = _ribbon_source()
    assert 'layout: str = "mixed"' in source
    assert 'size: str = "auto"' in source
    assert "def _resolve_button_size(" in source
    assert "def _add_large_image_command(" in source
    assert "def _load_texture(" in source
    assert "self.texture_loader" in source
    assert "def set_button_image(" in source


def test_ribbon_component_still_supports_qat_icons_and_flat_large_command_captions():
    ribbon = _ribbon_source()
    dialog = (ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py").read_text(encoding="utf-8")
    assert "image: str | None = None" in ribbon
    assert 'self._load_texture(image, 16)' in ribbon
    adapter = (ROOT / "WinUx" / "ui" / "ribbon.py").read_text(encoding="utf-8")
    assert 'ResourceTextures.get' in adapter
    assert 'icon_path' in adapter
    assert 'def _large_label_theme(' in ribbon
    assert 'self._surface_theme("separator")' in ribbon
    assert 'image=self._icon("open_image")' in dialog
    assert 'image=self._icon("undo")' in dialog
    assert 'quick_access=False' in dialog


def test_ribbon_v6_large_commands_are_single_tiles_and_separators_are_draw_lines():
    ribbon = _ribbon_source()
    textures = (ROOT / "DearUIQt/ribbon/textures.py").read_text(encoding="utf-8")
    assert "class RibbonTileTextures" in textures
    assert "Build a large command as one clickable tile" in ribbon
    assert "self.backend.add_image_button(" in ribbon
    assert "self.backend.add_drawlist(" in ribbon
    assert "self.backend.draw_line(" in ribbon


def test_ribbon_v7_tile_captions_use_small_pixel_aware_text():
    ribbon = _ribbon_source()
    textures = (ROOT / "DearUIQt/ribbon/textures.py").read_text(encoding="utf-8")
    dialog = (ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py").read_text(encoding="utf-8")
    assert "TILE_FONT_SIZE = 9" in ribbon
    assert "max_text_width" in textures
    assert "draw.textbbox" in textures
    assert "width_of(full) <= max_width" in textures
    assert "quick_access=False" in dialog


def test_ribbon_v8_large_tiles_cannot_be_clipped_by_group_controls():
    ribbon = _ribbon_source()
    textures = (ROOT / "DearUIQt/ribbon/textures.py").read_text(encoding="utf-8")
    assert "controls_height = max(" in ribbon
    assert "self.LARGE_BUTTON_HEIGHT + 4" in ribbon
    assert "base_y = max(icon_size + 7" in textures
    assert "TILE_FONT_SIZE = 9" in ribbon


def test_plot_digitizer_keeps_compact_ribbon_geometry_but_uses_larger_icons_inside_tiles():
    ribbon = _ribbon_source()
    dialog = (ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py").read_text(encoding="utf-8")
    assert '"LARGE_BUTTON_HEIGHT": 54' in ribbon
    assert 'density="compact"' in dialog
    assert 'self.ribbon.LARGE_ICON_SIZE = 32' in dialog
    assert 'width=64, image=' in dialog
