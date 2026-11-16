"""Check shared scrollbar paint in the selector's production floating host."""
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
from PIL import Image
from DearUIQt.backends.shared_scrollers import _overlays
from DearUIQt.backends.dearpygui_scroller import SharedScrollerPalette
from DearUIQt.modelview import QTreeWidgetItem
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='selector-scrollbar-', dir=temp) as directory:
        for index in range(80):
            (Path(directory) / ('folder_%02d' % index)).mkdir()
        kind = sys.argv[1] if len(sys.argv) > 1 else 'local_folder'
        runtime = FloatingDialogRuntime(Mock(), iter(()), {
            'kind': kind, 'title': 'Selector scrollbar test', 'visible': True,
            'payload': {'initial': directory}, 'width': 780, 'height': 500})
        runtime.gui.createContext(manual_callbacks=True)
        runtime._publish_requested = runtime._commit_requested = True
        try:
            runtime._build()
            with runtime.form._places_tree.batchUpdate():
                for index in range(12):
                    runtime.form._places_tree.addTopLevelItem(QTreeWidgetItem(['Extra place %02d' % index]))

            def pump(count=12):
                for _ in range(count):
                    runtime._drain_form_callbacks()
                    runtime.view.drain()
                    runtime.gui.renderFrame()
                    runtime.view.mark_presented()
                    time.sleep(.01)

            pump(60)
            form = runtime.form
            backend = runtime.gui.backend
            listing = form.listbox
            entries = _overlays.get(id(backend), {})

            def capture(label):
                screenshot = temp / ('selector_scrollbar_' + kind + '_' + label + '.png')
                backend.output_frame_buffer(str(screenshot))
                pump(4)
                with Image.open(screenshot) as frame:
                    return frame.convert('RGB')

            for name, target in (('places', form.places), ('files', listing._details_table.tag)):
                overlay = entries.get(target)
                assert overlay is not None, (name, 'did not register the app shared scroller')
                assert 'v' in overlay._last_axes
                lane = overlay._lanes['v'][0]
                assert backend.get_item_configuration(lane)['show']
                data = overlay._last_axes['v']
                left, top, right, bottom = data['hit']
                frame = capture(name + '_idle')
                pixel = frame.getpixel((round(left + 1), round(top + 5)))
                assert pixel == SharedScrollerPalette.MASK[:3], (name, 'native gutter remains visible', pixel)

                state = {'down': False}
                cap = data['end_cap']
                pointer = ((cap[0] + cap[2]) / 2, (cap[1] + cap[3]) / 2)
                with patch.object(overlay, '_pointer', return_value=pointer), \
                        patch.object(overlay, '_left_button_down', side_effect=lambda: state['down']), \
                        patch.object(overlay, '_foreground_input_blocked', return_value=False), \
                        patch.object(backend, 'is_item_hovered', return_value=True):
                    pump(18)
                    assert overlay._expansion['v'] == 1
                    assert backend.get_item_configuration(overlay._arrows['down'])['show']
                    capture(name + '_hover')
                    state['down'] = True
                    pump(3)
                    state['down'] = False
                    pump(3)
                    assert backend.get_y_scroll(target) > 0, (name, 'shared arrow did not scroll')
                backend.set_y_scroll(target, 0)
                pump(18)
                print('PASS:', kind, name, 'shared painted gutter, hover expansion, arrows and scrolling', flush=True)
        finally:
            runtime.view._dispatcher.close()
            if runtime.native:
                runtime.native.set_visible(False)
                runtime.native.restore_close_handler()
                runtime.native.close_activation_guard()
            runtime.gui.destroy()


if __name__ == '__main__':
    main()
