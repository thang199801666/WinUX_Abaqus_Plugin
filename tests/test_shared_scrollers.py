"""Shared scrollbar geometry/input/lifecycle on actual Settings surfaces."""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt import input_gate
from DearUIQt.backends.shared_scrollers import _overlays
from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-shared-scroll-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
            dialog = None
            backend = view._gui_runtime.backend

            def pump(count=12):
                for _ in range(count):
                    view.update()
                    time.sleep(.01)

            def verify_lane(overlay, axis):
                expected = overlay._last_axes[axis]['hit']
                item = overlay._hits[axis]
                state = backend.get_item_state(item)
                actual = (*state['rect_min'], *state['rect_max'])
                assert all(abs(a - b) <= 1 for a, b in zip(actual, expected)), (actual, expected)
                assert backend.get_item_parent(item) == overlay._lanes[axis][0]
                assert backend.get_item_configuration(overlay._parts[axis + '_thumb'])['show']

            try:
                view._gui_runtime.show()
                dialog = SettingsDialog(view)
                parent = backend.get_item_parent(dialog.page_host)
                size = backend.get_item_configuration(dialog.page_host)
                dialog.show()
                pump(30)
                entries = _overlays[id(backend)]
                assert view.left.listview.body_window not in entries, 'File List acquired two scrollbar skins'
                assert view.right.listview.body_window not in entries
                page = entries[dialog.page_host]
                assert backend.get_item_parent(dialog.page_host) == parent
                current = backend.get_item_configuration(dialog.page_host)
                assert (current['width'], current['height']) == (size['width'], size['height'])
                verify_lane(page, 'v')
                assert page._expansion['v'] == 0

                # Stable chrome away from the pointer needs neither native
                # writes nor expensive foreground scans. Release polling stays
                # live for a captured gesture.
                with patch.object(page, '_pointer', return_value=None), \
                        patch.object(page, '_left_button_down', return_value=False), \
                        patch.object(page, '_foreground_input_blocked', return_value=False) as gate:
                    page.update()
                    with patch.object(backend, 'configure_item', wraps=backend.configure_item) as configure:
                        for _ in range(10):
                            page.update()
                        configure.assert_not_called()
                    gate.assert_not_called()

                data = page._last_axes['v']
                lane = data['hit']
                point = ((lane[0] + lane[2]) / 2, (lane[1] + lane[3]) / 2)
                with patch.object(page, '_pointer', return_value=point), \
                        patch.object(page, '_foreground_input_blocked', return_value=True) as gate:
                    page.update()
                    gate.assert_called_once()
                    assert page._expansion['v'] == 0, 'Occluded lane acquired hover feedback'

                # Popup occlusion must also clear fading chrome immediately,
                # even after the pointer has left the scrollbar lane.
                page._expansion['v'] = .5
                with patch.object(page, '_pointer', return_value=None), \
                        patch.object(page, '_foreground_input_blocked', return_value=True) as gate:
                    page.update()
                    gate.assert_called_once()
                    assert page._expansion['v'] == 0

                # Exercise the real interaction/animation model with a
                # deterministic pointer, without touching the desktop mouse.
                state = {'down': False, 'point': None}
                backend.set_y_scroll(dialog.page_host, 0)
                pump()
                data = page._last_axes['v']
                left, top, right, bottom = data['end_cap']
                state['point'] = ((left + right) / 2, (top + bottom) / 2)
                with patch.object(page, '_pointer', side_effect=lambda: state['point']), \
                        patch.object(page, '_left_button_down', side_effect=lambda: state['down']), \
                        patch.object(page, '_foreground_input_blocked', return_value=False), \
                        patch.object(backend, 'is_item_hovered', return_value=True):
                    pump(18)
                    assert page._expansion['v'] == 1
                    assert backend.get_item_configuration(page._arrows['down'])['show']
                    state['down'] = True
                    pump(3)
                    state['down'] = False
                    pump(3)
                    assert backend.get_y_scroll(dialog.page_host) > 0, 'Shared arrow did not scroll'
                    assert not page._captured

                    data = page._last_axes['v']
                    state['point'] = ((data['hit'][0] + data['hit'][2]) / 2,
                                      data['thumb0'] + data['length'] / 2)
                    before = backend.get_y_scroll(dialog.page_host)
                    state['down'] = True
                    pump(2)
                    state['point'] = (state['point'][0], state['point'][1] + 30)
                    pump(3)
                    state['down'] = False
                    pump(3)
                    assert backend.get_y_scroll(dialog.page_host) > before, 'Shared thumb did not drag'
                    assert not page._captured

                # Native scrolling APIs and programmatic scroll continue to
                # drive the exact same viewport, not a duplicate scroll range.
                maximum = backend.get_y_scroll_max(dialog.page_host)
                backend.set_y_scroll(dialog.page_host, maximum)
                pump()
                assert abs(page._last_axes['v']['value'] - maximum) <= 1

                hwnd = NativeWindowBackend(backend).winId(dialog.tag)
                with patch.object(input_gate, 'native_background_input_blocked', return_value=True), \
                        patch.object(input_gate, '_native_surface_under_pointer', return_value=hwnd), \
                        patch.object(input_gate, 'protected_surface_under_pointer', return_value=None):
                    assert not page._foreground_input_blocked(), 'Modal blocked its own scrollbar'
                    with patch.object(input_gate, 'popup_input_is_blocked', return_value=True):
                        assert page._foreground_input_blocked()

                # A plain QListWidget uses the same skin once it overflows.
                listing = dialog.navigation_list
                listing.addItems(['Additional row {}'.format(i) for i in range(15)])
                pump()
                list_scroll = entries[listing.tag]
                verify_lane(list_scroll, 'v')

                # Add horizontal overflow after construction: the new hit
                # surface must remain inside its own lane, not the window body.
                backend.configure_item(dialog.page_host, horizontal_scrollbar=True)
                backend.add_text('Wide content ' * 70, parent=dialog.page_host)
                pump()
                verify_lane(page, 'h')
                verify_lane(page, 'v')

                assert input_gate.acquire_pointer_input(page._pointer_owner)
                page._captured = True
                page._gesture = {'axis': 'v', 'kind': 'drag', 'offset': 0}
                dialog.hide()
                pump()
                assert not page._captured
                assert input_gate._pointer_owner is not page._pointer_owner
                assert not backend.is_item_shown(page._lanes['v'][0])
                dialog.show()
                pump()
                assert entries[dialog.page_host] is page, 'Show created a duplicate scrollbar'
                dialog.destroy()
                dialog = None
                pump()
                assert not entries, 'Destroyed dialog retained scrollbar hit surfaces'
                print('PASS: shared Settings/list scrollbars, horizontal/vertical hit alignment, '
                      'native scroll ranges, own-modal input, popup blocking and capture cleanup', flush=True)
            finally:
                if dialog is not None:
                    dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
