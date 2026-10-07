from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
MENU = CONSOLE.split("class _ConsoleContextMenu:", 1)[1].split("def terminal_theme", 1)[0]


def test_qmenu_groups_actions_with_two_nonmodal_separators():
    assert 'SEPARATORS_AFTER = frozenset(("paste", "find"))' in MENU
    assert "if action in self.SEPARATORS_AFTER" in MENU
    assert "dpg.add_separator()" in MENU


def test_hover_updates_keyboard_current_action_without_focus_capture():
    assert "dpg.add_item_hover_handler" in MENU
    assert "def _hovered" in MENU
    assert "self._set_current(action)" in MENU
    assert "dpg.focus_item" not in MENU
    assert "dpg.capture" not in MENU.lower()


def test_visible_menu_routes_accelerators_through_menu_actions():
    for action in ("copy", "paste", "select_all", "find"):
        assert f'self._context_menu_key_action("{action}")' in CONSOLE
    assert "def trigger(self, action)" in MENU
    assert "underlying terminal" in CONSOLE


def test_outside_right_release_dismisses_without_consuming_destination_click():
    block = CONSOLE.split("    def _right_release_fallback", 1)[1].split(
        "    def _open_context_menu_fallback", 1
    )[0]
    assert "if bool(getattr(menu, \"is_open\", False))" in block
    assert "self.view.after(0, self._hide_context_menu)" in block
