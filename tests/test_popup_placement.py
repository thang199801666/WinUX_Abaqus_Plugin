"""Real renderer regression: abaqus python tests/test_popup_placement.py."""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.backends.dearpygui import dpg_window_rect
from DearUIQt.dialogs.placement import centered_over
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.gui.placement import below_anchor, fit_popup, item_screen_rect
from DearUIQt.notifications.placement import monitor_work_area
from DearUIQt.widgets import QToolButton, QComboBox, QMenu
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    # Include negative monitor origins, edge flips and oversized popups.
    for bounds in ((0, 0, 1920, 1040), (-1920, -200, 0, 840)):
        l, t, r, b = bounds
        for anchor in ((l, t, l + 80, t + 25), (r - 80, b - 25, r, b)):
            x, y = below_anchor(anchor, (266, 246), bounds)
            assert l <= x <= r - 266 and t <= y <= b - 246
        assert fit_popup((r, b), (3000, 2000), bounds) == (l, t)

    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    native = NativeWindowBackend()
    user32 = ctypes.windll.user32

    def pump(frames=16):
        for _ in range(frames):
            view.update()
            time.sleep(.01)

    def rect_for(item):
        hwnd = native.winId(item)
        assert hwnd, 'Missing native window'
        rect = wintypes.RECT()
        assert user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        return rect.left, rect.top, rect.right, rect.bottom

    def contained(item):
        l, t, r, b = rect_for(item)
        area = monitor_work_area(point=(l, t))
        assert area.left <= l < r <= area.right, (l, t, r, b, area)
        assert area.top <= t < b <= area.bottom, (l, t, r, b, area)

    def verify_popup(popup, anchor):
        pump()
        contained(popup.tag)
        config = dpg.get_item_configuration(popup.tag)
        bounds = popup._global_popup_bounds((anchor[0], anchor[1]))
        expected = below_anchor(anchor, (config['width'], config['height']), bounds)
        actual = popup.globalGeometry()
        assert abs(actual.x() - expected[0]) <= 2, (actual.toTuple(), expected)
        assert abs(actual.y() - expected[1]) <= 2, (actual.toTuple(), expected)
        popup.hide()
        pump(4)

    view._gui_runtime.show()
    pump()
    main_hwnd = view._find_main_viewport_hwnd()
    area = monitor_work_area(owner_hwnd=main_hwnd)
    cases = [('top-left', area.left + 12, area.top + 12),
             ('top-right', area.right - view.WIDTH, area.top + 12),
             ('bottom-left', area.left + 12, area.bottom - view.HEIGHT),
             ('bottom-right', area.right - view.WIDTH, area.bottom - view.HEIGHT),
             ('PiP', None, None)]
    for label, x, y in cases:
        if label == 'PiP':
            view.collapse_to_job_monitor()
        else:
            user32.SetWindowPos(wintypes.HWND(main_hwnd), wintypes.HWND(0),
                                x, y, view.WIDTH, view.HEIGHT, 0x0014)
        pump()
        if label != 'PiP':
            bar = view._menu_bar_wrapper
            for menu in bar._menus[:2]:
                button = bar._buttons[menu]
                x0, y0, w0, h0 = bar._button_anchor_screen_rect(bar._button_anchor_rect(button))
                assert bar._open_menu(menu)
                verify_popup(menu, (x0, y0, x0 + w0, y0 + h0))
        context = QMenu([
            {'label': 'New', 'action': 'group', 'children': [
                {'label': 'New Folder', 'action': 'child', 'shortcut': 'F7'},
                {'label': 'New File', 'action': 'file'}]},
            {'label': 'Details', 'action': 'details'},
        ], min_width=266)
        for point in ((area.left + 1, area.top + 1),
                      (area.right - 1, area.top + 1),
                      (area.left + 1, area.bottom - 1),
                      (area.right - 1, area.bottom - 1)):
            assert context.popupGlobal(point)
            pump()
            contained(context.tag)
            assert context._show_submenu('group', context._row_specs['group'])
            pump()
            submenu = context._submenus['group']
            contained(submenu.tag)
            assert dpg.get_item_configuration(submenu.tag)['width'] < (
                dpg.get_item_configuration(context.tag)['width'])
            ml, mt, mr, mb = rect_for(context.tag)
            sl, st, sr, sb = rect_for(submenu.tag)
            gap = context.SUBMENU_GAP
            assert abs(sl - (mr + gap)) <= 2 or abs(sr - (ml - gap)) <= 2
            context.hide()
            pump(4)
        context.delete()
        for modal in (True, False):
            dialog = QtDialog(view, 'Placement test', width=440, height=280,
                              modal=modal, footer=False, resizable=False)
            button = QToolButton('Dropdown', parent=dialog.content, width=160)
            menu = QMenu([{'label': 'Action {}'.format(i), 'action': str(i)}
                          for i in range(6)])
            button.setMenu(menu)
            combo = QComboBox(['Choice {}'.format(i) for i in range(20)],
                              parent=dialog.content, width=180)
            dialog.show()
            pump(24)
            contained(dialog.tag)
            dl, dt, dr, db = rect_for(dialog.tag)
            owner_rect = wintypes.RECT()
            user32.GetWindowRect(wintypes.HWND(main_hwnd), ctypes.byref(owner_rect))
            expected = centered_over(
                (owner_rect.left, owner_rect.top, owner_rect.right - owner_rect.left,
                 owner_rect.bottom - owner_rect.top), (dr - dl, db - dt),
                (area.left, area.top, area.right - area.left, area.bottom - area.top))
            assert abs(dl - expected[0]) <= 2 and abs(dt - expected[1]) <= 2, (
                label, modal, (dl, dt), expected)
            anchor = item_screen_rect(dpg, button.tag)
            assert button.showMenu()
            verify_popup(menu, anchor)
            anchor = item_screen_rect(dpg, combo.tag)
            assert combo.showPopup()
            verify_popup(combo._choice_popup, anchor)
            combo.setPopupParent(dialog.tag)
            pump(4)
            assert combo.showPopup()
            assert combo._choice_popup._parent_window is None
            verify_popup(combo._choice_popup, item_screen_rect(dpg, combo.tag))
            combo.hidePopup()
            child = QtDialog(view, 'Nested placement', width=320, height=180,
                             parent=dialog, footer=False, resizable=False)
            child.show()
            pump(24)
            contained(child.tag)
            cl, ct, cr, cb = rect_for(child.tag)
            expected = centered_over(
                (dl, dt, dr - dl, db - dt), (cr - cl, cb - ct),
                (area.left, area.top, area.right - area.left, area.bottom - area.top))
            assert abs(cl - expected[0]) <= 2 and abs(ct - expected[1]) <= 2
            child.destroy()
            pump(8)
            menu.delete()
            dialog.destroy()
            pump(16)
        print('PASS:', label, 'dialogs, nested dialog, dropdowns, context menu/submenu', flush=True)
    view.restore_from_job_monitor()
    pump()
    view.request_shutdown()
    view._gui_runtime.destroy()
    print('PASS: popup placement suite', flush=True)


if __name__ == '__main__':
    main()
