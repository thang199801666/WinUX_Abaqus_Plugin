from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
VIEW = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")


def test_wndproc_no_longer_consumes_console_right_button():
    hook = VIEW.split("    def _install_console_character_hook(self):", 1)[1].split(
        "    # Compatibility alias", 1)[0]
    assert "WM_RBUTTONDOWN" not in hook
    assert "WM_RBUTTONUP" not in hook
    assert "panel.native_right_click" not in hook
    assert "Pointer/context-menu input is" in hook


def test_console_uses_one_deferred_global_right_release_path():
    assert "button=dpg.mvMouseButton_Right, callback=self._right_release_fallback" in CONSOLE
    block = CONSOLE.split("    def _right_release_fallback", 1)[1].split(
        "    def _open_context_menu_fallback", 1)[0]
    assert "self.view.after(0, self._open_context_menu_fallback)" in block
    assert "_native_canvas_rect" not in block
    assert "after_render" not in block


def test_deferred_rmb_hit_test_uses_dpg_hover_and_always_clears_pending():
    block = CONSOLE.split("    def _open_context_menu_fallback", 1)[1].split(
        "    def _canvas_left_click", 1)[0]
    assert "if not self._over_terminal():" in block
    assert "self.native_right_click()" in block
    assert "finally:" in block
    assert "self._context_menu_pending = False" in block


def test_drawlist_still_has_no_right_click_item_handler():
    menu = CONSOLE.split("class _ConsoleContextMenu:", 1)[1].split("def terminal_theme", 1)[0]
    assert "button=dpg.mvMouseButton_Right" not in menu
    assert "TrackPopupMenuEx" not in menu
    assert "popup=True" not in menu
