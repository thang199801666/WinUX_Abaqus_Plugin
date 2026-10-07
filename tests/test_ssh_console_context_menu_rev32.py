from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
VIEW = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")


def _menu_class():
    return CONSOLE.split("class _ConsoleContextMenu:", 1)[1].split("def terminal_theme", 1)[0]


def test_console_context_menu_uses_no_modal_or_imgui_popup_stack():
    block = _menu_class()
    assert "TrackPopupMenuEx" not in block
    assert "CreatePopupMenu" not in block
    assert "popup=True" not in block
    assert "no_open_over_existing_popup" not in block


def test_console_context_menu_does_not_focus_or_capture_pointer():
    block = _menu_class()
    assert "dpg.focus_item(self.tag)" not in block
    assert "register_pointer_protected_item" not in block
    assert "acquire_pointer_input" not in block
    assert "release_pointer_input" not in block


def test_context_menu_rmb_is_scoped_to_console_canvas():
    block = _menu_class()
    assert "with dpg.item_handler_registry() as self._handler_registry:" in block
    assert "button=dpg.mvMouseButton_Right" in block
    assert "dpg.bind_item_handler_registry(owner.canvas, self._handler_registry)" in block
    assert "add_mouse_click_handler(button=dpg.mvMouseButton_Right" not in CONSOLE
    assert "WM_RBUTTONUP" not in VIEW


def test_context_menu_outside_left_click_is_dismissed_after_destination_dispatch():
    global_click = CONSOLE.split("    def _mouse_click", 1)[1].split(
        "    def _mouse_over_context_menu", 1
    )[0]
    assert "self.view.after(0, self._deactivate_keyboard_if_pointer_outside)" in global_click
    assert "self._hide_context_menu()" in global_click
    assert "self._mouse_over_context_menu()" in global_click


def test_context_menu_rows_are_plain_buttons_not_selectable_popup_rows():
    block = _menu_class()
    assert "dpg.add_button(" in block
    assert "dpg.add_selectable(" not in block
