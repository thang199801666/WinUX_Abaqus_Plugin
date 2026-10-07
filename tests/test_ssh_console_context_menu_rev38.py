from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")


def test_rmb_hit_is_captured_before_deferred_open():
    block = CONSOLE.split("    def _right_release_fallback", 1)[1].split(
        "    def _open_context_menu_fallback", 1)[0]
    assert "position = tuple(map(int, dpg.get_mouse_pos(local=False)))" in block
    assert "self._terminal_rect_contains(position)" in block
    assert "self.view.after(0, self._open_context_menu_fallback, position)" in block


def test_deferred_open_does_not_recheck_hover():
    block = CONSOLE.split("    def _open_context_menu_fallback", 1)[1].split(
        "    def _canvas_left_click", 1)[0]
    assert "self.native_right_click(*position)" in block
    assert "if not self._over_terminal()" not in block
    assert "is_item_hovered" not in block


def test_terminal_hit_test_uses_visible_child_rect():
    block = CONSOLE.split("    def _terminal_rect_contains", 1)[1].split(
        "    def _right_release_fallback", 1)[0]
    assert "dpg.get_item_rect_min(self.content)" in block
    assert "dpg.get_item_rect_size(self.content)" in block
    assert "width > 0 and height > 0" in block


def test_drawlist_has_deferred_right_click_fallback():
    menu = CONSOLE.split("class _ConsoleContextMenu:", 1)[1].split("def terminal_theme", 1)[0]
    assert "button=dpg.mvMouseButton_Right" in menu
    assert "callback=owner._canvas_right_click" in menu
    block = CONSOLE.split("    def _canvas_right_click", 1)[1].split(
        "    def _canvas_left_click", 1)[0]
    assert "_queue_context_menu_after_right_release(position)" in block
    assert "dpg.is_mouse_button_down(dpg.mvMouseButton_Right)" in block
    assert "after_render(self._open_context_menu_fallback, position)" in block
