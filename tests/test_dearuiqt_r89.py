from pathlib import Path
from unittest.mock import Mock

from DearUIQt.core import QObject
from DearUIQt.widgets import QMenu, QInlineEditPanel
from DearUIQt.widgets.menu import _normalize_action
from DearUIQt.themes import inline_editor_theme_spec, worksheet_theme_spec

ROOT = Path(__file__).resolve().parents[1]


def test_qmenu_preserves_shortcuts_and_toolkit_neutral_navigation():
    spec = _normalize_action({"id": "rename", "action": "rename", "label": "Rename", "shortcut": "F2"})
    assert spec["shortcut"] == "F2"

    menu = object.__new__(QMenu)
    QObject.__init__(menu)
    menu._parent_menu = None
    menu._open_submenu = None
    menu._submenus = {}
    menu._active_action = "open"
    menu._row_specs = {
        "open": {"id": "open", "action": "open", "enabled": True},
        "rename": {"id": "rename", "action": "rename", "enabled": True},
    }
    menu._visible_action_ids = lambda: ["open", "rename"]
    menu._set_active_action = lambda action: setattr(menu, "_active_action", action)
    menu._row_clicked = Mock()

    assert menu.navigate("down")
    assert menu._active_action == "rename"
    assert menu.navigate("activate")
    menu._row_clicked.assert_called_once_with(user_data="rename")


def test_r89_public_components_and_theme_specs_are_reusable():
    assert QInlineEditPanel is not None
    assert inline_editor_theme_spec() is not None
    assert worksheet_theme_spec() is not None


def test_r89_migrated_winux_modules_do_not_own_renderer_calls():
    migrated = [
        ROOT / "WinUx/ui/components/explorer_context_menu.py",
        ROOT / "WinUx/ui/components/explorer_rename_textbox.py",
        ROOT / "WinUx/ui/components/reference_data_table.py",
        ROOT / "WinUx/dialogs/reference_chart_form.py",
    ]
    for path in migrated:
        source = path.read_text(encoding="utf-8")
        assert "DearUIQt.backends" not in source, path
        assert "dpg." not in source, path


def test_explorer_context_menu_delegates_popup_engine_to_qmenu():
    source = (ROOT / "WinUx/ui/components/explorer_context_menu.py").read_text(encoding="utf-8")
    dispatch = (ROOT / "WinUx/ui/components/explorer_pointer_dispatch.py").read_text(encoding="utf-8")
    assert "QMenu(" in source
    assert "menu.navigate(user_data)" in source
    assert "menu.containsPopupPoint" in source
    assert "self._show_item_context_menu" in dispatch
    assert "dpg.set_item_pos(self.itemmenu_tag" not in dispatch
