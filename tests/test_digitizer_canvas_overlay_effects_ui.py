"""Check rendered hover/pressed pixels in the actual Plot Digitizer viewport."""
import os
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image, ImageChops
from DearUIQt.backends import dpg
from DearUIQt.core import QPoint, Qt
from WinUx.plotdigitizer import standalone


def main():
    original = standalone.PlotDigitizerDialog
    errors, finished = [], []
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='overlay-render-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        def build(view, *args, **kwargs):
            dialog = original(view, *args, **kwargs)
            position = [QPoint(-100, -100)]
            buttons = [Qt.NoButton]
            patches = [patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', side_effect=lambda **_: position[0]),
                       patch('WinUx.plotdigitizer.ui.dialog.QCursor.buttons', side_effect=lambda **_: buttons[0])]
            for item in patches:
                item.start()
            frames = {}
            sequence = [(enabled, key, state) for enabled in (False, True)
                        for key in dialog._canvas_view_buttons
                        for state in ('idle', 'hover', 'pressed', 'released')]
            active = [False]

            def stop(error=None):
                if error is not None:
                    traceback.print_exception(type(error), error, error.__traceback__)
                    errors.append(repr(error))
                for item in reversed(patches):
                    item.stop()
                dialog.destroy()

            def step(index=0):
                try:
                    if index == len(sequence):
                        finished.append(index)
                        stop()
                        return
                    enabled, key, state = sequence[index]
                    if enabled and not active[0]:
                        active[0] = True
                        dialog.engine.apply_image(Image.new('RGB', (800, 500), 'white'), 'overlay.png')
                        dialog._load_texture(dialog.engine.image)
                    button = dialog.control_wrapper(dialog._canvas_view_buttons[key])
                    position[0] = button.globalGeometry().center() if state in ('hover', 'pressed') else QPoint(-100, -100)
                    buttons[0] = Qt.LeftButton if state == 'pressed' else Qt.NoButton
                    dialog._update_canvas_view_tool_states()
                    view.after(100, capture, index)
                except Exception as exc:
                    stop(exc)

            def capture(index):
                try:
                    path = str(Path(profile) / ('frame-{}.png'.format(index)))
                    dpg.output_frame_buffer(path)
                    view.after(100, verify, index, path)
                except Exception as exc:
                    stop(exc)

            def verify(index, path):
                try:
                    enabled, key, state = sequence[index]
                    with Image.open(path) as image:
                        frames[enabled, key, state] = image.convert('RGB')
                    if state == 'released':
                        idle, hover, pressed, released = [frames[enabled, key, name]
                                                          for name in ('idle', 'hover', 'pressed', 'released')]
                        hover_box = ImageChops.difference(idle, hover).getbbox()
                        press_box = ImageChops.difference(hover, pressed).getbbox()
                        assert hover_box, (enabled, key, 'hover has no rendered effect')
                        assert press_box, (enabled, key, 'press has no rendered effect')
                        assert hover_box[2] - hover_box[0] <= 32 and hover_box[3] - hover_box[1] <= 32, hover_box
                        assert ImageChops.difference(idle, released).getbbox() is None, (enabled, key, 'stuck highlight')
                        for name in ('idle', 'hover', 'pressed', 'released'):
                            del frames[enabled, key, name]
                    step(index + 1)
                except Exception as exc:
                    stop(exc)

            view.after(500, step)
            return dialog

        with patch.object(standalone, 'PlotDigitizerDialog', side_effect=build):
            result = standalone.main([])
    assert result == 0 and finished == [32] and not errors, (result, finished, errors)
    print('PASS actual viewport pixels: all four icons visibly hover/press/release, '
          'with and without an image; transparent idle background and unchanged geometry')


if __name__ == '__main__':
    main()
