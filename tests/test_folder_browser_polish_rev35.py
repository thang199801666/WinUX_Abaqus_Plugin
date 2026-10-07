"""Navigation/callback regressions for the folder browser."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
ADDRESS = ROOT / "WinUx" / "dialogs" / "folder_browser_address.py"


def test_sidebar_navigation_uses_dpg_user_data_not_fourth_capture_parameter():
    source = FORM.read_text(encoding="utf-8")
    assert "user_data=str(path)" in source
    assert "callback=self._place_clicked" in source
    assert "_u, p=str(path)" not in source


def test_breadcrumb_navigation_uses_dpg_user_data_not_fourth_capture_parameter():
    source = ADDRESS.read_text(encoding="utf-8")
    assert "user_data=str(ancestor)" in source
    assert "callback=lambda _s, _a, p: self.dialog._navigate(p)" in source
    assert "_u, p=str(ancestor)" not in source


def test_address_refresh_never_indexes_unvalidated_rect_tuple():
    source = ADDRESS.read_text(encoding="utf-8")
    assert "rect = dpg.get_item_rect_size(self.body)" in source
    assert "if isinstance(rect, (tuple, list)) and len(rect) >= 1" in source
    assert "dpg.get_item_rect_size(self.body)[0]" not in source
