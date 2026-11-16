"""Compare the main file list's painted icon with its full Shell texture."""
import os
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image
from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.models.items import FileItem
from WinUx.view import WinUXView
from WinUx.platform.windows_icons import WindowsIconRegistry


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=temp) as directory, patch.dict(os.environ, {'APPDATA': directory}):
        view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
        try:
            view._gui_runtime.show()
            view.left.display(Path(directory), [
                FileItem('file_%02d.winux_unknown' % index,
                         Path(directory) / ('file_%02d.winux_unknown' % index), False, 10, 100)
                for index in range(8)])
            def pump(count=20):
                for _ in range(count):
                    view.update()
                    time.sleep(.01)
            pump()
            screenshot = temp / 'file_list_icon_render.png'
            dpg.output_frame_buffer(str(screenshot))
            pump(4)
            frame = Image.open(screenshot).convert('RGB')
            listing = view.left.listview
            row = listing._row_items[3]
            config = dpg.get_item_configuration(row['icon'])
            cx, cy = dpg.get_item_rect_min(listing.body_canvas)
            origin = wintypes.POINT()
            ctypes.windll.user32.ClientToScreen(
                wintypes.HWND(view._find_main_viewport_hwnd()), ctypes.byref(origin))
            cx -= origin.x
            cy -= origin.y
            x, y = config['pmin'][:2]
            rect = tuple(round(v) for v in (cx+x, cy+y, cx+config['pmax'][0], cy+config['pmax'][1]))
            painted = frame.crop(rect)
            texture = row['icon_texture']
            size = dpg.get_item_configuration(texture)
            pixels = bytes(round(float(value)*255) for value in dpg.get_value(texture))
            source = Image.frombytes('RGBA', (size['width'], size['height']), pixels)
            # Assert that the cached source itself retains the small Shell
            # icon's lower contour (the old image-list source was truncated).
            hicon = WindowsIconRegistry._file_type_hicon('.winux_unknown')
            try:
                direct = WindowsIconRegistry._hicon_to_image(hicon, 16)
                assert source.tobytes() == direct.tobytes(), 'Small icon differs from complete Shell source'
            finally:
                ctypes.windll.user32.DestroyIcon(hicon)
            background = frame.getpixel((rect[0] - 1, rect[1] + 8))
            expected = Image.new('RGBA', source.size, (*background, 255))
            expected.alpha_composite(source)
            expected = expected.convert('RGB')
            comparison = Image.new('RGB', (32, 16), 'white')
            comparison.paste(expected, (0, 0))
            comparison.paste(painted, (16, 0))
            comparison.resize((512, 256), Image.Resampling.NEAREST).save(temp / 'file_list_icon_compare.png')
            differences = [max(abs(a-b) for a,b in zip(expected.getpixel((x,y)), painted.getpixel((x,y))))
                           for y in range(16) for x in range(16)]
            assert max(differences) <= 3, (
                'Painted icon lost source pixels', max(differences), rect,
                temp / 'file_list_icon_compare.png')
            print('PASS: complete small Shell source and all 16x16 painted pixels; ',
                  temp / 'file_list_icon_compare.png', flush=True)
        finally:
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
