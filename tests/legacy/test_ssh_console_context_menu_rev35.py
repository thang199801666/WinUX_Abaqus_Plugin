from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")


def test_console_menu_is_modeless_qmenu_like_and_keyboard_driven():
    assert "class _ConsoleContextMenu" in CONSOLE
    assert "def move_current" in CONSOLE
    assert "def activate_current" in CONSOLE
    assert "menu.move_current(-1)" in CONSOLE
    assert "menu.move_current(1)" in CONSOLE
    assert "menu.activate_current()" in CONSOLE
    assert "popup=True" not in CONSOLE[CONSOLE.index("class _ConsoleContextMenu"):CONSOLE.index("def terminal_theme")]


def test_console_menu_clamps_position_and_deduplicates_native_fallback_open():
    block = CONSOLE[CONSOLE.index("class _ConsoleContextMenu"):CONSOLE.index("def terminal_theme")]
    assert "def _clamp_position" in block
    assert "get_viewport_client_width" in block
    assert "get_viewport_client_height" in block
    assert "now - self._last_open_time < 0.12" in block


def test_console_menu_action_state_is_synchronized_on_open():
    method = CONSOLE.split("    def _prepare_context_menu_state(self):", 1)[1].split(
        "    def _hide_context_menu", 1)[0]
    for action in ("copy", "paste", "select_all", "find", "clear"):
        assert f'menu.setActionEnabled("{action}"' in method
    assert "_win_clipboard_has_text()" in method


def test_context_action_hides_surface_and_returns_focus_without_replaying_click():
    method = CONSOLE.split("    def _menu_action(self, callback):", 1)[1].split(
        "    def invoke_default", 1)[0]
    assert "self._hide_context_menu()" in method
    assert "self._suppress_left_click_until = time.monotonic() + 0.12" in method
    assert "self.focus_input(follow_tail=False)" in method
