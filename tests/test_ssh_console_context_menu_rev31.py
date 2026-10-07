from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
VIEW = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")


def test_console_context_menu_has_no_native_nested_modal_loop():
    assert "TrackPopupMenuEx(" not in CONSOLE
    assert "CreatePopupMenu" not in CONSOLE


def test_console_pointer_clicks_are_item_scoped_on_canvas():
    assert "with dpg.item_handler_registry() as self._handler_registry:" in CONSOLE
    assert CONSOLE.count("dpg.add_item_clicked_handler(") >= 3
    assert "button=dpg.mvMouseButton_Left" in CONSOLE
    assert "button=dpg.mvMouseButton_Right" in CONSOLE
    assert "button=dpg.mvMouseButton_Middle" in CONSOLE
    assert "dpg.bind_item_handler_registry(owner.canvas, self._handler_registry)" in CONSOLE
    assert "add_mouse_click_handler(button=dpg.mvMouseButton_Right" not in CONSOLE
    assert "button=dpg.mvMouseButton_Right, callback=self._right_click" not in CONSOLE


def test_console_selection_no_longer_runs_from_global_click_callback():
    selection = CONSOLE.split("    def _canvas_left_click", 1)[1].split(
        "    def _mouse_click", 1
    )[0]
    global_click = CONSOLE.split("    def _mouse_click", 1)[1].split(
        "    def _deactivate_keyboard_if_pointer_outside", 1
    )[0]
    assert "self._cell_from_mouse()" in selection
    assert "self.view.after(0, self._deactivate_keyboard_if_pointer_outside)" in global_click
    assert "self._cell_from_mouse()" not in global_click
    assert "self.focus_input(" not in global_click


def test_console_context_menu_is_real_imgui_popup():
    assert "popup=True" in CONSOLE
    assert "no_open_over_existing_popup=False" in CONSOLE
    assert "dpg.add_selectable(" in CONSOLE


def test_console_popup_does_not_use_custom_global_pointer_gate():
    create = CONSOLE.split("    def _create_context_menu(self):", 1)[1].split(
        "    def _context_menu_triggered", 1
    )[0]
    assert "register_pointer_protected_item" not in create


def test_main_wndproc_is_not_extended_for_console_rmb():
    assert "WM_RBUTTONUP" not in VIEW
    assert "native_right_click" not in VIEW
