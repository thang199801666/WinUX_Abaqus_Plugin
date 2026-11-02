"""Physical selector input in its production floating host; run sequentially."""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
import time
from ctypes import wintypes
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from PIL import Image
from WinUx.dialogs.folder_browser_style import BrowserListPalette
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else 'local_folder'
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(cursor))
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='selector-floating-', dir=temp) as directory, \
            patch.dict(os.environ, {'APPDATA': directory}):
        root = Path(directory)
        for i in range(30):
            (root / ('folder_%02d' % i)).mkdir()
        (root / 'model.inp').write_text('test')
        runtime = FloatingDialogRuntime(Mock(), iter(()), {
            'kind': kind, 'title': 'Selector input regression', 'visible': True,
            'payload': {'initial': directory}, 'width': 780, 'height': 500,
        })
        runtime.gui.createContext(manual_callbacks=True)
        runtime._publish_requested = runtime._commit_requested = True

        def pump(count):
            for _ in range(count):
                runtime._drain_form_callbacks()
                runtime.view.drain()
                runtime.gui.renderFrame()
                runtime.view.mark_presented()
                time.sleep(.01)

        try:
            runtime._build()
            pump(40)
            listing = runtime.form.listbox
            thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
            current = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = user32.AttachThreadInput(current, thread, True)
            try:
                user32.SetForegroundWindow(wintypes.HWND(runtime.native.hwnd))
            finally:
                if attached:
                    user32.AttachThreadInput(current, thread, False)
            # Keep this isolated test surface above unrelated desktop windows.
            user32.SetWindowPos(wintypes.HWND(runtime.native.hwnd), wintypes.HWND(-1),
                                0, 0, 0, 0, 0x0013)
            pump(8)
            assert int(user32.GetForegroundWindow() or 0) == runtime.native.hwnd, (
                'Could not foreground floating host', runtime.native.hwnd, user32.GetForegroundWindow())
            changes = []
            listing.currentChanged.connect(lambda key: changes.append(key))

            def verify_background(row, expected, label):
                key = listing._values[row].key
                y = dpg.get_item_rect_min(listing.items[key])[1]
                screenshot = temp / ('selector_%s_row_%d.png' % (label, row + 1))
                dpg.output_frame_buffer(str(screenshot))
                pump(4)
                bounds = listing.globalGeometry(clipped=True)
                with Image.open(screenshot) as frame:
                    pixel = frame.convert('RGB').getpixel((bounds.right() - 30, int(y + 6)))
                assert pixel == expected[:3], (
                    label + ' background is on the wrong native row', row + 1, pixel,
                    expected[:3], screenshot)

            # Verify PAINTED hover, not just the model key: the custom header
            # occupies native row zero but is absent from logical data indices.
            for row in (2, 3):
                key = listing._values[row].key
                x, y = dpg.get_item_rect_min(listing.items[key])
                point = wintypes.POINT(int(x + 30), int(y + 6))
                user32.ClientToScreen(wintypes.HWND(runtime.native.hwnd), ctypes.byref(point))
                user32.SetCursorPos(point.x, point.y)
                pump(8)
                assert listing._hovered_row_key == key, (
                    row, listing._hovered_row_key, key, dpg.get_mouse_pos(local=False),
                    (x, y), (point.x, point.y), user32.GetForegroundWindow())
                verify_background(row, BrowserListPalette.HOVER, 'hover')
            for row in (0, 1, 7, 1, 0, 8):
                key = listing._values[row].key
                x, y = dpg.get_item_rect_min(listing.items[key])
                point = wintypes.POINT(int(x + 30), int(y + 6))
                user32.ClientToScreen(wintypes.HWND(runtime.native.hwnd), ctypes.byref(point))
                user32.SetCursorPos(point.x, point.y)
                pump(4)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                pump(3)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                pump(3)
                assert listing.current == key, (kind, row, listing.current, changes,
                    'rect', (x, y), 'screen', (point.x, point.y),
                    'mouse', dpg.get_mouse_pos(local=False),
                    'foreground', user32.GetForegroundWindow(), 'hwnd', runtime.native.hwnd,
                    'bounds', listing.globalGeometry(clipped=True))
                verify_background(row, (BrowserListPalette.SELECTED_HOVER
                    if listing._has_focus else BrowserListPalette.INACTIVE_HOVER), 'selected')
                generation = listing._row_generation
                for _ in range(35):
                    pump(1)
                    assert listing.selected == {key}, (kind, row, listing.selected, changes)
                    assert listing._row_generation == generation, 'Unrequested directory rebuild'
                    assert int(user32.GetForegroundWindow() or 0) == runtime.native.hwnd, 'Focus flicker'
            print('PASS:', kind, 'painted hover/selection match cursor rows, alternating selection, stable focus/model', flush=True)
        finally:
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            user32.SetCursorPos(cursor.x, cursor.y)
            runtime.view._dispatcher.close()
            if runtime.native:
                runtime.native.set_visible(False)
                runtime.native.restore_close_handler()
                runtime.native.close_activation_guard()
            runtime.gui.destroy()


if __name__ == '__main__':
    main()
