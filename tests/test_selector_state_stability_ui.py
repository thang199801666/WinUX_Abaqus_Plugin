"""Scroll/selection/late-callback regression on large rendered selectors.

abaqus python tests/test_selector_state_stability_ui.py
abaqus python tests/test_selector_state_stability_ui.py --floating local_file
abaqus python tests/test_selector_state_stability_ui.py --floating local_folder
Does not move/click the desktop pointer.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt.core import QEvent, QMouseEvent, QPoint, Qt
from DearUIQt.core.application import QApplication
from DearUIQt.gui import QCursor
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.local_file_form import LocalFileDialog
from WinUx.dialogs.local_folder_form import LocalFolderDialog
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    floating = '--floating' in sys.argv
    with tempfile.TemporaryDirectory(prefix='selector-stability-', dir=temp) as directory, \
            patch.dict(os.environ, {'APPDATA': directory}):
        root = Path(directory)
        for index in range(160):
            (root / ('folder_%03d' % index)).mkdir()
            (root / ('model_%03d.inp' % index)).write_text('test')
        runtime = view = dialog = None
        try:
            if floating:
                kind = sys.argv[-1]
                runtime = FloatingDialogRuntime(Mock(), iter(()), {
                    'kind': kind, 'title': 'Selector stability', 'visible': True,
                    'payload': {'initial': directory, 'multiple': True}, 'width': 780, 'height': 500})
                runtime.gui.createContext(manual_callbacks=True)
                runtime._publish_requested = runtime._commit_requested = True
                runtime._build()
                dialog = runtime.form

                def pump(count=12):
                    for _ in range(count):
                        runtime._drain_form_callbacks()
                        runtime.view.drain()
                        runtime.gui.renderFrame()
                        runtime.view.mark_presented()
                        time.sleep(.01)
            else:
                view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
                view._gui_runtime.show()

                def pump(count=12):
                    for _ in range(count):
                        view.update()
                        time.sleep(.01)

            classes = (None,) if floating else (LocalFolderDialog, LocalFileDialog)
            for cls in classes:
                started = time.perf_counter()
                if cls is not None:
                    dialog = cls(view, directory, lambda result: None, multiple=True)
                    dialog.show()
                pump(60)
                listing = dialog.listbox
                backend = listing.backend
                assert len(listing._values) >= 160
                for item in listing._values[:6]:
                    native = listing.items[item.key]
                    assert backend.get_item_rect_size(native)[0] > 32, 'Collapsed filename width'
                    assert backend.get_item_configuration(native)['label'] == item.text
                if floating:
                    # Geometry alone cannot detect a native 1 px clip retained
                    # after reparenting. Check that filename ink is painted well
                    # beyond the first glyph in the floating primary viewport.
                    from PIL import Image
                    screenshot = root / '.filename-render.png'
                    dpg.output_frame_buffer(str(screenshot))
                    pump(4)
                    frame = Image.open(screenshot).convert('RGB')
                    for item in listing._values[:4]:
                        native = listing.items[item.key]
                        x, y = map(round, backend.get_item_rect_min(native))
                        width, height = map(round, backend.get_item_rect_size(native))
                        ink = frame.crop((x + 12, y, x + min(width, 100), y + height))
                        assert sum(max(ink.getpixel((ix, iy))) < 140
                                   for iy in range(ink.height) for ix in range(ink.width)) > 10, (
                            item.text, 'Filename text not painted beyond its first glyph')
                assert listing._qt_pointer_registered == (QApplication.instance() is not None)
                assert not listing._visual_hit_bindings, 'Redundant per-cell handlers remain'
                table = listing._details_table.tag
                generation = listing._row_generation
                app = QApplication.instance()

                def hold_scroll(value, count=25):
                    listing.setVerticalScrollValue(value)
                    pump(3)
                    actual = dpg.get_y_scroll(table)
                    for _ in range(count):
                        pump(1)
                        assert abs(dpg.get_y_scroll(table) - actual) <= 1, (
                            'Scroll bounced', value, actual, dpg.get_y_scroll(table))
                        assert listing._row_generation == generation, 'Idle rebuilt the table'
                    assert dpg.get_y_scroll(listing.tag) == 0

                def click_visible():
                    bounds = listing.globalGeometry(clipped=True)
                    candidates = []
                    for item in listing._values:
                        state = dpg.get_item_state(listing.items[item.key])
                        y = state['rect_min'][1]
                        if state.get('visible') and bounds.top() + 45 < y < bounds.bottom() - 35:
                            candidates.append((item.key, y))
                    key, y = candidates[len(candidates) // 2]
                    point = QPoint(bounds.left() + 45, int(y + 6))
                    with patch.object(QCursor, 'pos', return_value=point), \
                            patch.object(backend, 'is_key_down', return_value=False):
                        if app is not None:
                            assert app.dispatchPointerEvent(QMouseEvent(
                                QEvent.MouseButtonPress, point, button=Qt.LeftButton, buttons=Qt.LeftButton))
                            app.dispatchPointerEvent(QMouseEvent(
                                QEvent.MouseButtonRelease, point, button=Qt.LeftButton, buttons=Qt.NoButton))
                        else:
                            listing._qt_bridge_click = None
                            assert listing._row_pointer_clicked(point=point)
                    assert listing.current == key and listing.selected == {key}
                    return key

                for value in (500, 1800, 700):
                    hold_scroll(value)
                    key = click_visible()
                    first = listing._values[0].key
                    # Rejected callbacks must not retarget the just-selected
                    # row, even after release or after the cursor moved.
                    listing._clicked(listing.items[first], True, first)
                    listing._visual_cell_clicked(None, None, first)
                    listing._row_pointer_clicked()
                    pump(20)
                    assert listing.current == key and listing.selected == {key}
                    assert dpg.get_y_scroll(table) >= value - 1

                # The same-mode rebuild schedules a fallback scroll restore.
                # A newer explicit scroll must win before that callback drains.
                listing.setItems(list(listing._values))
                table = listing._details_table.tag
                generation = listing._row_generation
                listing.setVerticalScrollValue(1500)
                pump()
                hold_scroll(1500)
                assert listing.current == key and listing.selected == {key}

                # A slow scan with an old pending selection must not override
                # a selection made while its worker was in flight.
                pending = []
                dialog._select_after_load = listing._values[0].key
                with patch.object(dialog, 'runAsync', side_effect=lambda worker, on_result: pending.append((worker, on_result))):
                    dialog._refresh()
                hold_scroll(900)
                key = click_visible()
                worker, completed = pending.pop()
                completed(worker())
                pump()
                assert listing.current == key and listing.selected == {key}, 'Late scan replaced selection'

                # Resize/reflow must keep both selected keys and must not
                # focus/scroll back to current (often the first row).
                dialog._change_view('List')
                pump()
                listing.setCurrentKey(listing._values[1].key)
                listing._qt_bridge_click = None
                with patch.object(backend, 'is_key_down', side_effect=lambda code: code == backend.mvKey_LControl):
                    listing._route_pointer_key(listing._values[3].key)
                chosen = set(listing.selected)
                assert len(chosen) == 2
                rows = max(1, listing._list_flow_rows - 1)
                columns = (len(listing._values) + rows - 1) // rows
                with patch.object(listing, '_mode_flow_shape', return_value=(rows, columns)), \
                        patch.object(backend, 'focus_item', wraps=backend.focus_item) as focus:
                    listing.requestListReflow()
                    pump(20)
                    assert listing.selected == chosen, 'Reflow collapsed multi-selection'
                    assert listing.current in chosen
                    assert not any(call.args and call.args[0] in listing.items.values()
                                   for call in focus.call_args_list), 'Reflow focused a row'
                # The standalone host has no QApplication. Mouse-up waiting
                # must still complete using renderer frames, not retry forever
                # with a constant frame number of zero.
                with patch.object(QCursor, 'buttons', return_value=Qt.NoButton), \
                        patch('ctypes.windll.user32.GetAsyncKeyState', return_value=0), \
                        patch.object(dialog, '_enter_key') as activate:
                    key = listing.current
                    dialog._queue_row_activation(key)
                    pump(20)
                    activate.assert_called_once_with(key)
                    assert dialog._pending_row_activation is None
                    assert not dialog._row_activation_scheduled
                name = kind if floating else cls.__name__
                print('PASS:', name, len(listing._values), 'rows; stable scroll, clicks, delayed callbacks, scan and reflow;',
                      round(time.perf_counter() - started, 2), 's', flush=True)
                if not floating:
                    dialog.destroy()
                    dialog = None
                    pump()
        finally:
            if runtime is not None:
                runtime.view._dispatcher.close()
                if runtime.native:
                    runtime.native.set_visible(False)
                    runtime.native.restore_close_handler()
                    runtime.native.close_activation_guard()
                runtime.gui.destroy()
            elif view is not None:
                if dialog is not None:
                    dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
