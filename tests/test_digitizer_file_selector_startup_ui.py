"""Open the image chooser before startup/first-present work has settled."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from DearUIQt.backends import dpg
from DearUIQt.core import QEvent, QMouseEvent, Qt


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=temp) as directory, \
            patch.dict(os.environ, {'APPDATA': directory}):
        for index in range(80):
            (Path(directory) / ('image_%03d.png' % index)).touch()
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        digitizer = None

        def pump(count):
            for _ in range(count):
                view.update()
                time.sleep(.01)

        try:
            view._gui_runtime.show()
            # No warm-up frames before opening nested native dialogs.
            digitizer = PlotDigitizerDialog(view)
            digitizer.show()
            digitizer._file_directory = directory
            digitizer._choose_open_image()
            chooser = digitizer._file_dialog.dialog
            listing = chooser.listbox
            deadline = time.monotonic() + 15
            while len(listing.items) < 80 and time.monotonic() < deadline:
                pump(1)
            assert len(listing.items) == 80
            pump(10)
            for item in listing._values[:4]:
                native = listing.items[item.key]
                assert dpg.get_item_rect_size(native)[0] > 32, 'Filename width collapsed during startup'
                assert dpg.get_item_configuration(native)['label'].startswith('image_'), (
                    item.text, dpg.get_item_configuration(native)['label'])
            for index in (2, 1, 3):
                key = listing._values[index].key
                x, y = dpg.get_item_rect_min(listing.items[key])
                chooser._initial_pointer_activity = False
                press = QMouseEvent(QEvent.MouseButtonPress, (x + 10, y + 5),
                                    button=Qt.LeftButton, buttons=Qt.LeftButton)
                assert chooser.event(press), (
                    chooser.isVisible(), listing.globalGeometry(clipped=True), (x, y),
                    listing._table_row_key_at(x + 10, y + 5))
                assert listing.current == key, (
                    'press hit', index, listing.current, (x, y),
                    listing._table_row_key_at(x + 10, y + 5))
                # A delayed first-present callback must not reassign keyboard
                # focus after this accepted pointer press, even after mouse-up.
                with patch.object(chooser, '_focus_initial') as focus:
                    assert chooser._apply_initial_focus_if_idle() is False
                    focus.assert_not_called()
                for _ in range(30):
                    pump(1)
                    assert listing.current == key, (index, listing.current)
                    assert listing.selected == {key}, listing.selected
                listing.setVerticalScrollValue(300)
                pump(3)
                scroll = listing.verticalScrollValue()
                assert scroll > 100, scroll
                for _ in range(30):
                    pump(1)
                    assert abs(listing.verticalScrollValue() - scroll) <= 1, (
                        scroll, listing.verticalScrollValue())
                listing.setVerticalScrollValue(0)
                pump(3)
            print('PASS immediate Digitizer -> Open image: selection and scroll remain stable')
        finally:
            if digitizer is not None:
                if digitizer._file_dialog is not None:
                    digitizer._file_dialog.close()
                digitizer.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
