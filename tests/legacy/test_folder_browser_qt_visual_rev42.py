from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_search_is_one_qlineedit_style_shell_with_embedded_icon():
    source = FORM.read_text(encoding="utf-8")
    assert "self.search_shell = dpg.add_child_window" in source
    assert "browser_field_shell_theme()" in source
    assert "browser_embedded_editor_theme()" in source


def test_view_mode_is_qtoolbar_button_pair_not_combo_box():
    source = FORM.read_text(encoding="utf-8")
    assert "self._details_view_control = QToolButton(" in source
    assert "self._list_view_control = QToolButton(" in source
    assert "self.details_view_button = self._details_view_control.tag" in source
    assert "self.list_view_button = self._list_view_control.tag" in source
    assert 'view_mode_texture("details")' in source
    assert 'view_mode_texture("list")' in source
    assert "browser_tool_button_theme(checked=True)" in source


def test_new_folder_action_and_inline_rename_use_dearuiqt_controls():
    source = FORM.read_text(encoding="utf-8")
    assert "self._new_folder_control = QToolButton(" in source
    assert "self.new_folder_button = self._new_folder_control.tag" in source
    assert "self._rename_editor_control = QLineEdit(" in source
    assert "self._new_folder_control.setEnabled(False)" in source


def test_details_view_keeps_the_stable_outer_scroll_contract():
    source = FORM.read_text(encoding="utf-8")
    assert "resizable=self.details_mode" not in source
    assert "scrollY=True" not in source


def test_qfiledialog_navigation_shortcuts_include_search_and_parent():
    source = FORM.read_text(encoding="utf-8")
    assert "dpg.mvKey_F" in source
    assert "self.focus_editor(self.filter_edit)" in source
    assert "key == dpg.mvKey_Up and alt" in source
