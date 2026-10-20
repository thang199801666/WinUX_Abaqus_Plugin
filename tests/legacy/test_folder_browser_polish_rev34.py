"""Regression guards for the stable Explorer-style Dear ImGui folder browser."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
ADDRESS = ROOT / "WinUx" / "dialogs" / "folder_browser_address.py"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_folder_list_keeps_shared_item_view_theme_and_frozen_details_header():
    source = FORM.read_text(encoding="utf-8")
    assert "browser_details_theme()" in source
    assert "freeze_rows=1 if self.details_mode else 0" in source
    assert 'label="Date modified"' in source
    assert 'label="Type"' in source


def test_search_stays_in_compact_location_bar_without_nested_focus_shells():
    source = FORM.read_text(encoding="utf-8")
    assert 'navigation_texture("search")' in source
    assert 'hint="Search this folder"' in source
    assert "self.filter_edit = self.line_edit" in source


def test_address_bar_uses_shared_line_edit_and_safe_first_frame_width_probe():
    source = ADDRESS.read_text(encoding="utf-8")
    assert "self.editor = dialog.line_edit" in source
    assert "def _available_width" in source
    assert "len(rect) >= 1" in source
    assert "self._last_valid_width" in source


def test_browser_style_remains_scoped_to_folder_browser():
    source = STYLE.read_text(encoding="utf-8")
    assert "def browser_surface_theme" in source
    assert "def browser_layout_theme" in source
    assert "def navigation_button_theme" in source
