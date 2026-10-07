from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_qfiledialog_toolbar_is_consolidated_into_one_row():
    source = FORM.read_text(encoding="utf-8")
    assert "self.location_toolbar = dpg.add_child_window" in source
    assert "self.command_toolbar = dpg.add_child_window" not in source
    assert "self.new_folder_button = dpg.add_image_button" in source
    assert 'self.details_view_button = dpg.add_image_button' in source
    assert 'self.list_view_button = dpg.add_image_button' in source
    assert "toolbar_separator = dpg.add_separator" in source


def test_details_view_uses_qheaderview_like_scoped_theme():
    source = FORM.read_text(encoding="utf-8")
    assert "browser_details_theme()" in source


def test_sidebar_elides_long_shell_names_without_losing_full_path_tooltip():
    source = FORM.read_text(encoding="utf-8")
    assert "def _elide_sidebar_label" in source
    assert "dpg.get_text_size" in source
    assert "return text[:lo] + ellipsis" in source
    assert "self._set_place_label(label_item, name)" in source
    assert "add_styled_tooltip(label_item, str(path))" in source


def test_sidebar_and_toolbar_metrics_are_compact_qt_like():
    source = STYLE.read_text(encoding="utf-8")
    assert "toolbar_height: int = 34" in source
    assert "sidebar_width: int = 196" in source
    assert "header_height: int = 24" in source
