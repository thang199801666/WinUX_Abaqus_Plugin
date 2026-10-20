from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
VIEW = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")


def _menu_class():
    return CONSOLE.split("class _ConsoleContextMenu:", 1)[1].split("def terminal_theme", 1)[0]


def test_console_rmb_never_enters_dear_imgui_item_handler():
    menu = _menu_class()
    assert "button=dpg.mvMouseButton_Right" not in menu
    assert "add_mouse_click_handler(button=dpg.mvMouseButton_Right" not in CONSOLE


def test_main_wndproc_consumes_both_rmb_edges_for_console():
    assert "WM_RBUTTONDOWN = 0x0204" in VIEW
    assert "WM_RBUTTONUP = 0x0205" in VIEW
    down = VIEW.split("if message == WM_RBUTTONDOWN:", 1)[1].split(
        "if message == WM_RBUTTONUP:", 1)[0]
    up = VIEW.split("if message == WM_RBUTTONUP:", 1)[1].split(
        "if message in (WM_KILLFOCUS", 1)[0]
    assert "self._console_native_rmb_panel = panel" in down
    assert "return 0" in down
    assert "self._console_native_rmb_panel = None" in up
    assert "self.after(0, panel.native_right_click, x, y)" in up
    assert "return 0" in up
    assert "CallWindowProcW" not in down
    assert "CallWindowProcW" not in up


def test_wndproc_rmb_hit_test_is_pure_python():
    block = CONSOLE.split("def native_client_point_over_console", 1)[1].split(
        "def native_right_click", 1)[0]
    assert "dpg." not in block
    code_lines = [line for line in block.splitlines() if not line.lstrip().startswith(("\"", "#"))]
    assert "winfo_exists(" not in "\n".join(code_lines)
    assert "_native_canvas_rect" in block


def test_canvas_rect_is_cached_from_normal_ui_loop():
    assert "def _update_native_canvas_rect(self):" in CONSOLE
    paint = CONSOLE.split("def _paint_tick(self):", 1)[1].split(
        "def _paint(self):", 1)[0]
    assert "self._update_native_canvas_rect()" in paint


def test_context_menu_open_is_deferred_until_after_native_dispatch():
    method = CONSOLE.split("def native_right_click(self, x=None, y=None):", 1)[1].split(
        "def _canvas_left_click", 1)[0]
    assert "menu.popup(position, context=self)" in method
    wnd = VIEW.split("if message == WM_RBUTTONUP:", 1)[1].split(
        "if message in (WM_KILLFOCUS", 1)[0]
    assert "self.after(0, panel.native_right_click, x, y)" in wnd


def test_context_menu_stays_modeless_and_non_popup():
    menu = _menu_class()
    assert "popup=True" not in menu
    assert "TrackPopupMenuEx" not in menu
    assert "dpg.focus_item(self.tag)" not in menu
