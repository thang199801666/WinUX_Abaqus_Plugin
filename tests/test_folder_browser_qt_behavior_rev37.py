from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_folder_rows_have_robust_qfiledialog_double_click_activation():
    source = FORM.read_text(encoding="utf-8")
    assert "def _system_double_click_interval" in source
    assert "dpg.is_mouse_button_double_clicked" in source
    assert "self.doubleClicked.emit(key)" in source
    assert "self.doubleClicked.emit(key)" in source
    assert "self.activated.emit(key)" in source


def test_folder_dialog_connects_activation_to_navigation():
    source = FORM.read_text(encoding="utf-8")
    assert "self.listbox.doubleClicked.connect(self._enter_key)" in source
    assert "def _enter_key(self, key):" in source
    assert "self._navigate(path)" in source


def test_folder_view_uses_qt_keyboard_navigation_contract():
    source = FORM.read_text(encoding="utf-8")
    assert "self.active_table = self.listbox" in source
    assert "dpg.mvKey_Return" in source
    assert "dpg.mvKey_Back" in source
    assert "def _list_keyboard_active" in source


def test_folder_browser_qt_polish_keeps_sidebar_and_details_themes_scoped():
    source = FORM.read_text(encoding="utf-8")
    assert "browser_sidebar_theme()" in source
    assert "browser_sidebar_row_theme()" in source
    assert "browser_details_theme()" in source
    assert "browser_divider_theme()" in source
    assert 'dpg.add_text("Folder:", parent=selection_row)' in source
