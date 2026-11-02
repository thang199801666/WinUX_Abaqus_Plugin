"""Geometry/resource guards for the Plot Digitizer Pick Color pencil cursor."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WinUx.platform.tool_cursor import ToolCursorHandles


class ColorPickerCursorTests(unittest.TestCase):
    def test_bundled_cursor_asset_exists_and_is_rgba(self):
        resource = ROOT / 'WinUx' / 'Resources' / 'PlotDigitizer_PickColorCursor.png'
        self.assertTrue(resource.is_file())
        from PIL import Image
        image = Image.open(resource).convert('RGBA')
        self.assertEqual(image.size, (512, 512))
        self.assertIsNotNone(image.getchannel('A').getbbox())
        small = image.resize((64, 64))
        colors = (small.get_flattened_data() if hasattr(small, 'get_flattened_data') else small.getdata())
        self.assertTrue(any(r > 180 and g > 120 and b < 80 and a > 0 for r, g, b, a in colors))
        self.assertTrue(any(r > 180 and g < 100 and b < 100 and a > 0 for r, g, b, a in colors))

    def test_artwork_uses_asset_with_transparent_precision_hotspot(self):
        image, hotspot = ToolCursorHandles.color_picker_artwork(32, 32)
        self.assertEqual(image.size, (32, 32))
        self.assertTrue(0 <= hotspot[0] < 32 and 0 <= hotspot[1] < 32)
        self.assertEqual(image.getpixel(hotspot)[3], 0)

        # The approved asset retains its characteristic yellow body, red eraser,
        # silver ferrule and dark graphite tip at cursor size.
        pixels = list(image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata())
        opaque = [p for p in pixels if p[3] > 32]
        self.assertGreater(len(opaque), 150)
        self.assertTrue(any(r > 180 and g > 110 and b < 90 for r, g, b, _a in opaque))
        self.assertTrue(any(r > 170 and g < 120 and b < 120 for r, g, b, _a in opaque))
        self.assertTrue(any(abs(r - g) < 30 and abs(g - b) < 30 and 120 < r < 245
                            for r, g, b, _a in opaque))
        self.assertLessEqual(hotspot[0], 3)
        self.assertGreaterEqual(hotspot[1], 27)

    def test_artwork_scales_with_system_cursor_metrics(self):
        image, hotspot = ToolCursorHandles.color_picker_artwork(48, 48)
        self.assertEqual(image.size, (48, 48))
        self.assertEqual(image.getpixel(hotspot)[3], 0)
        self.assertLessEqual(hotspot[0], 4)
        self.assertGreater(hotspot[1], 40)

    def test_native_path_uses_32bit_color_cursor_not_monochrome_only(self):
        source = (ROOT / 'WinUx' / 'platform' / 'tool_cursor.py').read_text(encoding='utf-8')
        self.assertIn("resource_path('PlotDigitizer_PickColorCursor.png'", source)
        self.assertIn('CreateIconIndirect', source)
        self.assertIn('premultiplied BGRA', source)
        self.assertIn('return self._rgba_cursor(image, hotspot) or self._image_cursor', source)

    def test_plot_digitizer_uses_dedicated_color_pick_mode(self):
        source = (ROOT / 'WinUx' / 'plotdigitizer' / 'ui' / 'dialog.py').read_text(encoding='utf-8')
        self.assertIn('"color_pick" if self._pick_mode == "curve" else', source)

    def test_legacy_pencil_mode_remains_declared_as_compatibility_alias(self):
        source = (ROOT / 'WinUx' / 'platform' / 'tool_cursor.py').read_text(encoding='utf-8')
        self.assertIn("mode = 'color_pick' if mode == 'pencil' else mode", source)
        self.assertIn('def _pencil_cursor', source)


if __name__ == '__main__':
    unittest.main()
