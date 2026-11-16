"""Regression: the QFileDialog address/history popup must not be a dialog child."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "WinUx" / "dialogs" / "selectors" / "folder_browser_address.py"


def _class_source():
    return SOURCE.read_text(encoding="utf-8")


def test_location_menu_is_root_popup_not_dialog_child():
    source = _class_source()
    assert "QMenu(parent=dialog, parent_window=None" in source
    assert "QMenu(parent=dialog, parent_window=dialog.tag" not in source


def test_location_popup_uses_screen_coordinate_contract():
    source = _class_source()
    assert "visible_item_screen_rect" in source
    assert "menu.popupBelow(anchor, global_position=True" in source
    assert "global_position=False" not in source[source.index("def _show_locations"):source.index("def _location_selected")]


def test_module_parses():
    ast.parse(_class_source())
