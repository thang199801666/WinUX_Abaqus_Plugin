"""Geometry and density regressions for the selector's symbolic icons."""
import unittest

import WinUx
from WinUx.dialogs.folder_browser_style import _qt_browser_symbol_image


class SelectorSymbolTests(unittest.TestCase):
    def test_symbols_keep_dense_masters_for_small_logical_slots(self):
        for name in ('folder', 'new_folder', 'back', 'forward', 'up',
                     'list', 'details', 'refresh', 'chevron'):
            with self.subTest(name=name):
                image = _qt_browser_symbol_image(name)
                self.assertEqual(image.size, (48, 48))
                self.assertEqual(image.mode, 'RGBA')
                self.assertIsNotNone(image.getchannel('A').getbbox())

    def test_folder_is_one_tab_not_two_stacked_folders(self):
        alpha = _qt_browser_symbol_image('folder').getchannel('A')
        # Nothing above the single tab at logical y=4.5, allowing a small
        # antialias fringe. The old doubled-tab glyph had strokes at y=2.
        self.assertIsNone(alpha.crop((0, 0, 48, 9)).getbbox())
        self.assertGreater(alpha.getpixel((8, 30)), 100)  # left outline
        self.assertEqual(alpha.getpixel((24, 30)), 0)  # transparent interior

    def test_disabled_state_preserves_the_symbol_silhouette(self):
        normal = _qt_browser_symbol_image('back')
        disabled = _qt_browser_symbol_image('back', disabled=True)
        self.assertEqual(normal.getchannel('A').tobytes(), disabled.getchannel('A').tobytes())
        self.assertNotEqual(normal.tobytes(), disabled.tobytes())


if __name__ == '__main__':
    unittest.main()
