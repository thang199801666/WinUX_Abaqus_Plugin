"""Native mouse regression: abaqus python tests/test_menu_hover.py."""
import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.gui.system import QCursor
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    view._gui_runtime.show()
    cursor = QCursor.screenPos()
    point = [cursor.x(), cursor.y()]

    def pump(frames=16):
        for _ in range(frames):
            ctypes.windll.user32.SetCursorPos(*point)
            view.update()
            time.sleep(.01)

    pump()
    bar = view._menu_bar_wrapper
    from ctypes import wintypes
    ctypes.windll.user32.SetWindowPos(
        wintypes.HWND(view._find_main_viewport_hwnd()), wintypes.HWND(-1),
        0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(view._find_main_viewport_hwnd()))
    pump(6)
    shown, hidden = {}, {}
    for menu in bar._menus:
        shown[menu] = hidden[menu] = 0
        def on_show(_context=None, menu=menu):
            shown[menu] += 1
        def on_hide(_context=None, menu=menu):
            hidden[menu] += 1
        menu.aboutToShow.connect(on_show)
        menu.aboutToHide.connect(on_hide)

    def hover(menu):
        rect = bar._button_anchor_rect(bar._buttons[menu])
        x, y, width, height = bar._button_anchor_screen_rect(rect)
        point[:] = [int(x + width / 2), int(y + height / 2)]
        pump()

    first = bar._menus[0]
    hover(first)
    assert not bar._menu_is_shown(first), 'Hover alone must not activate a closed menu bar'
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
    pump(2)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
    pump()
    assert bar._menu_is_shown(first)
    for menu in bar._menus[1:4]:
        hover(menu)
        assert bar._active_menu is menu and menu.isVisible()
        baseline = (dict(shown), dict(hidden))
        pump(60)
        assert (shown, hidden) == baseline, 'Menu toggled repeatedly while hover was stationary'
        # Replaying a stale sibling callback must not switch away or reopen.
        for stale in bar._menus:
            if stale is not menu:
                bar._button_hovered(user_data=stale)
        bar._open_menu(menu)
        pump(8)
        assert (shown, hidden) == baseline, 'Stale hover/repeated open caused flicker'
    geometry = menu.globalGeometry()
    point[:] = [geometry.x() + geometry.width() // 2, geometry.y() + 12]
    baseline = (dict(shown), dict(hidden))
    pump(30)
    assert menu.isVisible() and (shown, hidden) == baseline, 'Entering dropdown caused flicker'
    menu.hide()
    pump(4)
    ctypes.windll.user32.SetCursorPos(cursor.x(), cursor.y())
    view.request_shutdown()
    view._gui_runtime.destroy()
    print('PASS: native click, hover switching, stationary hover, stale callbacks, idempotent open', flush=True)


if __name__ == '__main__':
    main()
