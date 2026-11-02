"""Actual Job Manager combo choices: abaqus python tests/test_combo_popup_style.py."""
import os
import ctypes
from ctypes import wintypes
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.dialogs.qt_dialog import QtDialog
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.dialogs.reference_chart_form import RegexTesterDialog


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-combo-style-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            path = Path(profile) / 'Example.inp'
            path.write_text('*Heading\nPopup geometry test\n', encoding='utf-8')
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            dialog = view.show_job_manager([path], lambda *a: None, lambda *a: None)

            def pump(frames=12):
                for _ in range(frames):
                    view.update()
                    time.sleep(.015)

            try:
                pump()
                combo = dialog._control_wrappers[dialog.rows_by_path[path]['schedule']]
                combo.setCurrentIndex(1)
                pump(3)
                for parent in (dialog.tag, None):
                    combo.setPopupParent(parent)
                    assert combo.showPopup()
                    pump()
                    popup = combo._choice_popup
                    # Check painted item coordinates, not just the same
                    # reconstructed window geometry used by popup placement.
                    # Table cells/native caption offsets can disagree with it.
                    _, field_y = dpg.get_item_rect_min(combo._choice_field.button)
                    _, field_h = dpg.get_item_rect_size(combo._choice_field.button)
                    field_top, field_bottom = field_y - 1, field_y + field_h + 1
                    text_rects = [
                        (dpg.get_item_rect_min(parts['label'])[1],
                         dpg.get_item_rect_size(parts['label'])[1])
                        for parts in popup._items.values()]
                    assert (min(y for y, h in text_rects) >= field_bottom
                            or max(y + h for y, h in text_rects) <= field_top), (
                        'Dropdown covers the actual combobox', parent, field_top, field_bottom, text_rects)
                    config = dpg.get_item_configuration(popup.tag)
                    assert config['height'] == 3 * popup.ROW_HEIGHT + 2 * popup.WINDOW_PAD_Y
                    popup.selectRow(1)  # A real stationary mouse may hover a different row.
                    assert popup._active_action == '1'
                    for parts in popup._items.values():
                        left, top, right, bottom = popup._pointer_row_rect(parts['row'])
                        lx, ly = dpg.get_item_rect_min(parts['label'])
                        _, lh = dpg.get_item_rect_size(parts['label'])
                        assert bottom - top == 28
                        assert lx - left == popup.ROW_PAD_X + popup.LABEL_PAD
                        assert abs(ly + lh / 2 - (top + bottom) / 2) <= 1, (
                            'Dropdown text is not vertically centered', ly, lh, top, bottom)
                        assert top <= ly < ly + lh <= bottom
                    popup.navigate('down')
                    assert popup._active_action == '2'
                    popup.navigate('activate')
                    pump(3)
                    assert combo.currentText() == 'Run At'
                    assert not popup.isVisible()
                    combo.setCurrentIndex(1)
                    pump(3)
                print('PASS: real Job Manager dropdown, padded/centered 28px rows, '
                      'dialog/root anchors and keyboard selection', flush=True)
                dialog.destroy()
                dialog = RegexTesterDialog(view, r'U\d', 'U1\nU2')
                dialog.show()
                pump(25)
                combo = dialog.control_wrapper(dialog.match_view_selector)
                assert combo.showPopup()
                pump(15)
                popup = combo._choice_popup
                native = dialog._native_window_backend
                owner_hwnd = native.winId(dialog.tag)
                popup_hwnd = native.winId(popup.tag)
                assert popup_hwnd and popup_hwnd != owner_hwnd, 'Dropdown needs its own native surface above child editors'
                user = ctypes.windll.user32
                user.WindowFromPoint.argtypes = [wintypes.POINT]
                user.WindowFromPoint.restype = wintypes.HWND
                for parts in popup._items.values():
                    from DearUIQt.gui.placement import item_screen_rect
                    left, top, right, bottom = item_screen_rect(dpg, parts['label'])
                    point = wintypes.POINT(int((left + right) / 2), int((top + bottom) / 2))
                    hit = int(user.WindowFromPoint(point) or 0)
                    assert hit == popup_hwnd, ('Dropdown item is occluded by another HWND', hit, popup_hwnd)
                if '--screenshot' in sys.argv:
                    from PIL import ImageGrab
                    rect = wintypes.RECT()
                    user.GetWindowRect(wintypes.HWND(owner_hwnd), ctypes.byref(rect))
                    image = ImageGrab.grab()
                    scale = image.width / user.GetSystemMetrics(0)
                    destination = temp_root / 'combo-popup-over-editor.png'
                    image.crop(tuple(round(value * scale) for value in
                        (rect.left, rect.top, rect.right, rect.bottom))).save(destination)
                    print('SCREENSHOT', destination, flush=True)
                if '--pointer' in sys.argv:
                    cursor = wintypes.POINT()
                    user.GetCursorPos(ctypes.byref(cursor))
                    parts = popup._items['1']
                    left, top, right, bottom = item_screen_rect(dpg, parts['label'])
                    target = (int((left + right) / 2), int((top + bottom) / 2))
                    try:
                        user.SetCursorPos(*target)
                        pump(4)
                        user.mouse_event(0x0002, 0, 0, 0, 0)
                        pump(3)
                        user.mouse_event(0x0004, 0, 0, 0, 0)
                        pump(10)
                    finally:
                        user.mouse_event(0x0004, 0, 0, 0, 0)
                        user.SetCursorPos(cursor.x, cursor.y)
                else:
                    popup.selectRow(0)
                    popup.navigate('down')
                    popup.navigate('activate')
                pump(5)
                assert combo.currentText() == 'Selected only'
                assert dialog._match_information_view == 'Selected only'
                assert not popup.isVisible()
                print('PASS: both combo rows visible above native Rich Edit, selection and dismissal', flush=True)
                combo = dialog.control_wrapper(dialog.tools_selector)
                combo.setMaxVisibleItems(3)
                assert combo.showPopup()
                pump(12)
                popup = combo._choice_popup
                assert popup._parent_window is None
                popup.navigate('end')
                pump(3)
                assert popup._active_action == str(combo.count() - 1)
                assert dpg.get_y_scroll(popup.tag) > 0
                popup.navigate('home')
                pump(3)
                assert dpg.get_y_scroll(popup.tag) == 0
                popup.hide()
                assert not combo.popupVisible()
                assert dialog.control_wrapper(dialog.text_edit).text() == 'U1\nU2'
                print('PASS: shared dropdown scrolls through every item and preserves editor text', flush=True)
                dialog.destroy()
                pump(5)
                dialog = QtDialog(view, 'Editable combo regression', 440, 260, modal=True)
                tag = dialog.combo(['Alpha', 'Beta', 'Gamma'], editable=True,
                    default_value='Custom value', parent=dialog.content, width=220)
                dialog.show()
                pump(20)
                combo = dialog.control_wrapper(tag)
                changed = []
                combo.currentTextChanged.connect(changed.append)
                assert combo.showPopup()
                pump(10)
                popup = combo._choice_popup
                assert popup._parent_window is None
                popup.selectRow(1)
                popup.navigate('activate')
                pump(5)
                assert combo.currentText() == 'Beta' and changed == ['Beta']
                assert combo.showPopup()
                pump(10)
                popup_hwnd = dialog._native_window_backend.winId(combo._choice_popup.tag)
                dialog.destroy()
                dialog = None
                pump(12)
                assert not user.IsWindow(wintypes.HWND(popup_hwnd)), 'Closing owner leaked the combo popup HWND'
                print('PASS: editable combo selection emits once; owner close cleans up an open popup', flush=True)
            finally:
                if dialog is not None:
                    dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
