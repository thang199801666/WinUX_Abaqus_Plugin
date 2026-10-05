from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / 'WinUx' / 'dialogs' / 'console_form.py').read_text(encoding='utf-8')
VIEW = (ROOT / 'WinUx' / 'view.py').read_text(encoding='utf-8')


def test_console_has_no_dpg_global_right_click_handler():
    assert 'add_mouse_click_handler(button=dpg.mvMouseButton_Right, callback=self._right_click)' not in CONSOLE
    assert 'button=dpg.mvMouseButton_Right, callback=self._right_click' not in CONSOLE


def test_native_viewport_hook_routes_rbutton_up():
    assert 'WM_RBUTTONUP = 0x0205' in VIEW
    assert 'panel.native_right_click' in VIEW
    assert 'self.after(0, panel.native_right_click, x, y)' in VIEW


def test_native_wndproc_does_not_call_dpg_for_rmb_hit_test():
    block = VIEW.split('elif message == WM_RBUTTONUP:', 1)[1].split('return user32.CallWindowProcW', 1)[0]
    assert 'dpg.' not in block


def test_console_hit_tests_only_after_native_dispatch():
    assert 'def native_right_click(self, x, y):' in CONSOLE
    assert 'def _point_over_terminal(self, x, y):' in CONSOLE
    assert 'self._point_over_terminal(x, y)' in CONSOLE
