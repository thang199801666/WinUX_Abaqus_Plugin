from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / 'WinUx' / 'dialogs' / 'console_form.py').read_text(encoding='utf-8')
VIEW = (ROOT / 'WinUx' / 'view.py').read_text(encoding='utf-8')


def test_main_hwnd_resolution_no_longer_depends_only_on_left_listview():
    block = VIEW.split('    def _find_main_viewport_hwnd(self):', 1)[1].split(
        '    def _install_console_character_hook(self):', 1)[0]
    assert '_main_viewport_hwnd' in block
    assert 'EnumWindows' in block
    assert 'GetWindowThreadProcessId' in block
    assert 'GetCurrentProcessId' in block
    assert 'title == "WinUX"' in block


def test_native_rmb_hit_test_accepts_client_and_screen_coordinates():
    block = CONSOLE.split('    def native_client_point_over_console(', 1)[1].split(
        '    def native_right_click(', 1)[0]
    assert 'screen_x=None, screen_y=None' in block
    assert 'points = [(float(x), float(y))]' in block
    assert 'points.append((float(screen_x), float(screen_y)))' in block
    assert 'dpg.' not in block


def test_wndproc_converts_client_pointer_to_screen_before_console_hit_test():
    assert 'ClientToScreen' in VIEW
    assert 'def _console_rmb_hit(panel, window, x, y):' in VIEW
    assert 'hit_test(x, y, screen[0], screen[1])' in VIEW


def test_native_right_click_is_opened_after_dispatch_using_dpg_mouse_position():
    up = VIEW.split('if message == WM_RBUTTONUP:', 1)[1].split(
        'if message in (WM_KILLFOCUS', 1)[0]
    assert 'self.after(0, panel.native_right_click)' in up
    assert 'self.after(0, panel.native_right_click, x, y)' not in up
    method = CONSOLE.split('    def native_right_click(self, x=None, y=None):', 1)[1].split(
        '    def _right_release_fallback', 1)[0]
    assert 'dpg.get_mouse_pos(local=False)' in method


def test_console_has_after_render_rmb_fallback_without_item_scoped_right_click():
    assert 'button=dpg.mvMouseButton_Right, callback=self._right_release_fallback' in CONSOLE
    fallback = CONSOLE.split('    def _right_release_fallback(', 1)[1].split(
        '    def _open_context_menu_fallback', 1)[0]
    assert 'after_render' in fallback
    menu = CONSOLE.split('class _ConsoleContextMenu:', 1)[1].split('def terminal_theme', 1)[0]
    assert 'button=dpg.mvMouseButton_Right' not in menu
    assert 'TrackPopupMenuEx' not in menu
    assert 'popup=True' not in menu
