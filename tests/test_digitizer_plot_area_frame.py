"""Regression coverage for document-style framed chart-area detection."""
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from PIL import Image, ImageDraw
from WinUx.plotdigitizer.core import extraction, tick_detection as td


def document_chart():
    image = Image.new('RGB', (512, 387), 'white')
    draw = ImageDraw.Draw(image)
    # Dense page/title content above the chart used to pull the global profile
    # detector upward and make it return a document-sized rectangle.
    draw.text((20, 14), 'The graph below shows the proportion of the population aged 65 and over',
              fill=(25, 25, 25))
    draw.text((20, 28), 'between 1940 and 2040 in three different countries.', fill=(25, 25, 25))
    draw.text((140, 76), 'Proportion of population aged 65 and over', fill=(25, 25, 25))

    frame = (106, 97, 407, 274)
    left, top, right, bottom = frame
    draw.rectangle(frame, outline=(100, 100, 100))
    for y in (126, 156, 186, 216, 245):
        draw.line((left, y, right, y), fill=(150, 150, 150))
    # Curves deliberately cross the frame/grid but do not own the geometry.
    draw.line((left, 242, 166, 250, 226, 231, 286, 221, 347, 176, right, 114),
              fill=(25, 25, 25), width=2)
    draw.line((left, 229, 166, 214, 226, 191, 286, 196, 347, 157, right, 127),
              fill=(80, 80, 80), width=2)
    draw.line((left, 215, 166, 207, 226, 168, 286, 186, 347, 186, right, 98),
              fill=(40, 40, 40), width=2)

    for x, label in zip((106, 166, 226, 286, 347, 407),
                        ('1940', '1960', '1980', '2000', '2020', '2040')):
        draw.text((x - 10, 281), label, fill=(30, 30, 30))
    draw.text((246, 297), 'Year', fill=(30, 30, 30))

    # Detached legend below the plot must not become the chart bottom edge.
    draw.rectangle((214, 328, 303, 375), outline=(80, 80, 80))
    draw.line((220, 339, 249, 339), fill=(40, 40, 40))
    draw.text((258, 333), 'Japan', fill=(30, 30, 30))
    draw.line((220, 353, 249, 353), fill=(40, 40, 40))
    draw.text((258, 347), 'Sweden', fill=(30, 30, 30))
    draw.line((220, 367, 249, 367), fill=(40, 40, 40))
    draw.text((258, 361), 'USA', fill=(30, 30, 30))
    return image, frame


def open_axis_chart_with_outer_border():
    image = Image.new('RGB', (640, 480), 'white')
    draw = ImageDraw.Draw(image)
    # Decorative export border: this must never become the plot ROI.
    draw.rectangle((0, 0, 639, 479), outline=(0, 0, 0), width=2)
    frame = (145, 55, 590, 410)
    left, top, right, bottom = frame
    draw.line((left, top, left, bottom), fill=(95, 95, 95), width=4)
    draw.line((left, bottom, right, bottom), fill=(95, 95, 95), width=4)
    # Faint major grid lines and a colored curve imitate exported engineering charts.
    for y in (100, 145, 190, 235, 280, 325, 370):
        draw.line((left, y, right, y), fill=(215, 215, 215), width=1)
    for x in (205, 265, 325, 385, 445, 505, 565):
        draw.line((x, top, x, bottom), fill=(215, 215, 215), width=1)
    draw.line((left, 395, 230, 310, 320, 240, 420, 175, 520, 130, right, 110),
              fill=(255, 95, 95), width=3)
    return image, frame


class PlotAreaFrameTests(unittest.TestCase):
    def test_document_text_and_legend_do_not_expand_plot_frame(self):
        image, frame = document_chart()
        self.assertEqual(extraction.detect_plot_area(image), frame)

    def test_frame_detector_matches_with_and_without_numpy(self):
        image, frame = document_chart()
        accelerated = extraction.detect_plot_area(image)
        with mock.patch.object(extraction, 'np', None):
            scalar = extraction.detect_plot_area(image)
        self.assertEqual(accelerated, frame)
        self.assertEqual(scalar, frame)

    def test_open_axis_chart_ignores_decorative_outer_border(self):
        image, frame = open_axis_chart_with_outer_border()
        detected = extraction.detect_plot_area(image)
        self.assertIsNotNone(detected)
        self.assertLessEqual(abs(detected[0] - frame[0]), 3)
        self.assertLessEqual(abs(detected[1] - frame[1]), 3)
        self.assertLessEqual(abs(detected[2] - frame[2]), 3)
        self.assertLessEqual(abs(detected[3] - frame[3]), 3)

    def test_tiny_document_year_row_is_recognized_before_generic_ocr(self):
        image, frame = document_chart()
        result = td.detect_calibration_ticks(image, frame)
        self.assertTrue(result.x.ready)
        self.assertEqual(td.AxisScale.DATETIME, result.x.scale)
        self.assertEqual([1940, 1960, 1980, 2000, 2020, 2040],
                         [round(tick.value) for tick in result.x.ticks])
        self.assertTrue(all(tick.bbox != (0, 0, 0, 0) for tick in result.x.ticks))

    def test_tiny_year_fast_path_skips_generic_numeric_word_pass(self):
        image, frame = document_chart()
        with mock.patch.object(td, '_read_probe_word',
                               side_effect=AssertionError('generic numeric OCR ran before tiny-year row')):
            result = td._detect_axis(image, frame, 'x', td.AxisScale.LINEAR)
        self.assertTrue(result.ready)
        self.assertEqual(td.AxisScale.DATETIME, result.scale)
        self.assertEqual([1940, 1960, 1980, 2000, 2020, 2040],
                         [round(tick.value) for tick in result.ticks])


if __name__ == '__main__':
    unittest.main()
