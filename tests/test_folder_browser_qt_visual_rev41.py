from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
ADDRESS = ROOT / "WinUx" / "dialogs" / "folder_browser_address.py"


def test_breadcrumb_separators_are_geometry_not_font_glyphs():
    style = STYLE.read_text(encoding="utf-8")
    address = ADDRESS.read_text(encoding="utf-8")
    assert "def create_breadcrumb_chevron" in style
    assert "dpg.draw_line" in style
    assert "create_breadcrumb_chevron(self.breadcrumbs)" in address
    assert 'chr(GLYPHS["Chevron"])' not in address


def test_address_segments_and_blank_area_use_distinct_qt_themes():
    style = STYLE.read_text(encoding="utf-8")
    address = ADDRESS.read_text(encoding="utf-8")
    assert "def browser_breadcrumb_button_theme" in style
    assert "def browser_breadcrumb_blank_theme" in style
    assert "self._segment_theme = browser_breadcrumb_button_theme()" in address
    assert "self._blank_theme = browser_breadcrumb_blank_theme()" in address
    assert "dpg.bind_item_theme(self.editor, browser_embedded_editor_theme())" in address


def test_toolbar_action_cluster_has_qtoolbar_separator_and_compact_view_control():
    form = FORM.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "browser_toolbar_divider_theme" in form
    assert "def browser_toolbar_divider_theme" in style
    assert 'browser_tool_button_theme' in form
    assert 'add_styled_tooltip(self.details_view_button, "Details view")' in form
    assert 'add_styled_tooltip(self.list_view_button, "List view")' in form


def test_folder_dialog_has_room_for_single_row_toolbar():
    form = FORM.read_text(encoding="utf-8")
    assert 'min_size=(700, 430)' in form
