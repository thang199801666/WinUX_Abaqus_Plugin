"""Regression for stretched, small serif/bold chart labels; Pillow-only OCR."""
import os
import sys
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'vendor'))

from PIL import Image, ImageFont
from WinUx.plotdigitizer.core import tick_detection as td
from test_digitizer_tick_auto_calibration import make_chart


class RasterFontDetectionTests(unittest.TestCase):
    def test_stretched_labels_read_all_ticks_without_enlarged_retry(self):
        font_dir = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
        fonts = [os.path.join(font_dir, name)
                 for name in ('times.ttf', 'timesbd.ttf', 'arialbd.ttf')]
        fonts = [path for path in fonts if os.path.isfile(path)]
        if not fonts:
            self.skipTest('Windows serif/bold regression fonts are unavailable')
        for path in fonts:
            for sy in (.5, .65):
                with self.subTest(font=os.path.basename(path), height_scale=sy):
                    with patch('test_digitizer_tick_auto_calibration._font',
                               side_effect=lambda size=16: ImageFont.truetype(path, size)):
                        image, rect = make_chart()
                    image = image.resize((816, round(500 * sy)), Image.Resampling.BICUBIC)
                    rect = tuple(round(value * (1.2 if i % 2 == 0 else sy))
                                 for i, value in enumerate(rect))
                    start = time.perf_counter()
                    with patch.object(td, '_retry_small_y_labels',
                                      side_effect=AssertionError('unnecessary expensive Y retry')):
                        detected = td.detect_calibration_ticks(image, rect)
                    elapsed = time.perf_counter() - start
                    print('\n{} y-scale={}: {:.3f}s'.format(os.path.basename(path), sy, elapsed))
                    self.assertTrue(detected.ready)
                    self.assertEqual([0, .8, 1.6, 2.4, 3.2],
                                     [round(t.value, 6) for t in detected.x.ticks])
                    expected_y = [2000, 1500, 1000, 500, 0]
                    positions = [rect[1] + (rect[3] - rect[1]) * i / 4 for i in range(5)]
                    # Every label must be read independently, including 5-6 px
                    # bold glyphs that require resampling-phase verification.
                    self.assertEqual(expected_y, [t.value for t in detected.y.ticks])
                    for tick in detected.y.ticks:
                        index = min(range(5), key=lambda i: abs(positions[i] - tick.position))
                        # Drawing floors fractional source rows before resize;
                        # the rounded Box edge can differ by another pixel.
                        self.assertAlmostEqual(positions[index], tick.position, delta=2)
                        self.assertEqual(expected_y[index], tick.value)
                    self.assertGreaterEqual(len(detected.y.ticks), 3)
                    self.assertEqual(set(detected.y.mark_positions),
                                     {t.position for t in detected.y.ticks} | set(detected.y.unread_positions))
                    self.assertFalse({t.position for t in detected.y.ticks} & set(detected.y.unread_positions))

    def test_word_scoring_does_not_expand_pixels_into_python_lists(self):
        observed = td._word_templates('1500')[0]
        with patch.object(td, '_flat_pixels', side_effect=AssertionError('Python pixel loop')):
            self.assertAlmostEqual(0, td._normalized_word_template_score(observed, '1500'))


if __name__ == '__main__':
    unittest.main()
