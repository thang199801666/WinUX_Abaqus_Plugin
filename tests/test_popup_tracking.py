"""Live popup anchors: abaqus python tests/test_popup_tracking.py."""
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
from DearUIQt.backends.dearpygui import dpg_window_rect
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.backends.native_presentation import presentation_for
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.gui.placement import item_screen_rect, below_anchor, at_point
from DearUIQt.widgets import QMenu, QToolButton, QComboBox
from DearUIQt.widgets.modeless_menu import QModelessMenu
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    view._gui_runtime.show()
    native = NativeWindowBackend()
    u = ctypes.windll.user32
    def pump(frames=16):
        for _ in range(frames):
            view.update()
            time.sleep(.01)
    def move(hwnd, x, y, width, height):
        assert u.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(0),
                              x, y, width, height, 0x0014)
        pump(24)
    def lifetime(menu):
        events = []
        menu.aboutToShow.connect(lambda *_: events.append('show'))
        menu.aboutToHide.connect(lambda *_: events.append('hide'))
        return events
    def aligned(menu, anchor):
        assert menu.isVisible(), 'Tracking unexpectedly dismissed a popup'
        size = menu._popup_size()
        expected = below_anchor(anchor, size, menu._global_popup_bounds(anchor[:2]))
        actual = menu.globalGeometry()
        assert abs(actual.x() - expected[0]) <= 1, (actual.toTuple(), expected)
        assert abs(actual.y() - expected[1]) <= 1, (actual.toTuple(), expected)
        assert actual.width() == size[0] and actual.height() == size[1]

    pump()
    hwnd = view._find_main_viewport_hwnd()
    move(hwnd, 80, 80, 850, 620)
    bar = view._menu_bar_wrapper
    menu = bar._menus[0]
    events = lifetime(menu)
    assert bar._open_menu(menu)
    pump()
    original_hwnd = native.winId(menu.tag)
    presentation = presentation_for(view._gui_runtime.backend)
    cloaks = []
    original_cloak = presentation._cloak
    def record_cloak(window, enabled):
        cloaks.append((window, enabled))
        return original_cloak(window, enabled)
    presentation._cloak = record_cloak
    for x, y, w, h in ((260, 150, 850, 620), (180, 110, 1100, 740), (90, 90, 760, 560)):
        move(hwnd, x, y, w, h)
        rect = bar._button_anchor_screen_rect(bar._button_anchor_rect(bar._buttons[menu]))
        x0, y0, aw, ah = rect
        aligned(menu, (x0, y0, x0 + aw, y0 + ah))
        assert native.winId(menu.tag) == original_hwnd
        assert events == ['show'] and not cloaks, 'Movement reopened or re-cloaked the menu'
    for mode in (3, 9):
        u.ShowWindow(wintypes.HWND(hwnd), mode)
        pump(24)
        x0, y0, aw, ah = bar._button_anchor_screen_rect(bar._button_anchor_rect(bar._buttons[menu]))
        aligned(menu, (x0, y0, x0 + aw, y0 + ah))
        assert events == ['show'] and not cloaks
    u.ShowWindow(wintypes.HWND(hwnd), 6)
    pump(8)
    assert not menu.isVisible(), 'Minimizing the owner left a popup on the desktop'
    u.ShowWindow(wintypes.HWND(hwnd), 9)
    pump(16)
    pump(4)
    print('PASS: menu bar follows main move/resize without reopening or flashing', flush=True)

    context = QMenu([{'label': 'New', 'action': 'new', 'children': [
        {'label': 'Folder', 'action': 'folder'}, {'label': 'File', 'action': 'file'}]}])
    owner = view.left.listview.window_tag
    before = item_screen_rect(dpg, owner)
    point = (before[0] + 40, before[1] + 65)
    events = lifetime(context)
    assert context.popupGlobal(point, owner=owner)
    pump()
    assert context._show_submenu('new', context._row_specs['new'])
    pump()
    submenu = context._submenus['new']
    child_hwnd = native.winId(submenu.tag)
    cloaks.clear()
    for x, y, w, h in ((280, 170, 1000, 700), (140, 100, 820, 600)):
        move(hwnd, x, y, w, h)
        owner_rect = item_screen_rect(dpg, owner)
        expected = at_point((owner_rect[0] + 40, owner_rect[1] + 65),
                            context._popup_size(), context._global_popup_bounds(owner_rect[:2]))
        actual = context.globalGeometry()
        assert abs(actual.x() - expected[0]) <= 1 and abs(actual.y() - expected[1]) <= 1
        child = submenu.globalGeometry()
        assert abs(child.x() - (actual.x() + actual.width() + context.SUBMENU_GAP)) <= 1
        assert abs(child.y() - actual.y()) <= 1
        assert native.winId(submenu.tag) == child_hwnd
        assert events == ['show'] and not cloaks
    context.hide()
    context.delete()
    pump(4)
    print('PASS: context menu and submenu follow their owner together', flush=True)

    terminal_menu = QModelessMenu([('copy', 'Copy', 'Ctrl+C')])
    owner_rect = item_screen_rect(dpg, view.primary_window_tag)
    terminal_menu.popup((owner_rect[0] + 60, owner_rect[1] + 80), owner=view.primary_window_tag)
    pump()
    before = terminal_menu._last_open_position
    move(hwnd, 240, 160, 900, 660)
    assert terminal_menu._last_open_position != before
    expected = terminal_menu._panel.clampPosition((
        item_screen_rect(dpg, view.primary_window_tag)[0] + terminal_menu._owner_offset[0],
        item_screen_rect(dpg, view.primary_window_tag)[1] + terminal_menu._owner_offset[1]))
    assert terminal_menu._last_open_position == expected.toTuple()
    terminal_menu.hide()
    terminal_menu.delete()
    pump(4)
    print('PASS: modeless terminal context follows its owner', flush=True)

    dialog = QtDialog(view, 'Popup tracking', width=440, height=280,
                      modal=False, footer=False)
    button = QToolButton('Menu', parent=dialog.content, width=150)
    dropdown = QMenu([{'label': 'Action', 'action': 'action'}])
    button.setMenu(dropdown)
    combo = QComboBox(['Item {}'.format(i) for i in range(20)],
                      parent=dialog.content, width=-1)
    dialog.show()
    pump(24)
    owner_hwnd = native.winId(dialog.tag)
    events = lifetime(dropdown)
    assert button.showMenu()
    pump()
    cloaks.clear()
    move(owner_hwnd, 230, 150, 570, 340)
    aligned(dropdown, item_screen_rect(dpg, button.tag))
    assert events == ['show'] and not cloaks
    # Anchor destruction must close the popup rather than leave it floating.
    button.delete()
    pump(6)
    assert not dropdown.isVisible()
    print('PASS: tool dropdown tracks its source; deleted anchors close cleanly', flush=True)
    assert combo.showPopup()
    pump()
    popup = combo._choice_popup
    events = lifetime(popup)
    selected = combo.currentIndex()
    cloaks.clear()
    for x, y, w, h in ((290, 190, 650, 380), (160, 110, 440, 280)):
        move(owner_hwnd, x, y, w, h)
        anchor = item_screen_rect(dpg, combo.tag)
        aligned(popup, anchor)
        assert popup._popup_size()[0] == round(anchor[2] - anchor[0])
        # Moving a popup beneath the desktop pointer can legitimately change
        # its hovered row; it must not commit a different combo selection.
        assert combo.currentIndex() == selected and not events and not cloaks
    combo.hidePopup()
    combo.setPopupParent(dialog.tag)
    assert combo.showPopup()
    pump()
    hosted = combo._choice_popup
    assert hosted._parent_window is None  # Native children must not occlude choices.
    events = lifetime(hosted)
    selected = combo.currentIndex()
    for x, y, w, h in ((260, 140, 640, 400), (170, 120, 460, 300)):
        move(owner_hwnd, x, y, w, h)
        anchor = item_screen_rect(dpg, combo.tag)
        aligned(hosted, anchor)
        assert combo.currentIndex() == selected and not events
    combo.hidePopup()
    dropdown.delete()
    dialog.destroy()
    pump(8)
    presentation._cloak = original_cloak
    view.request_shutdown()
    view._gui_runtime.destroy()
    print('PASS: root/dialog-hosted native combos track position/width and preserve selection', flush=True)


if __name__ == '__main__':
    main()
