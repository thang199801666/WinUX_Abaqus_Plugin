"""Local raster verification must distinguish decimals from real integers."""
from pathlib import Path
import sys
import unittest
from concurrent.futures import CancelledError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image, ImageDraw, ImageFilter
from test_digitizer_tick_auto_calibration import make_chart, _font
from WinUx.plotdigitizer.core import tick_detection as td


def blurred_chart(labels):
    image, rect = make_chart()
    draw = ImageDraw.Draw(image)
    draw.rectangle((rect[0] - 20, rect[3] + 5, rect[2] + 30, rect[3] + 28), fill='white')
    font = _font()
    for index, text in enumerate(labels):
        x = rect[0] + (rect[2] - rect[0]) * index / (len(labels) - 1)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((x - (box[2] - box[0]) / 2, rect[3] + 7), text, font=font, fill=(100, 100, 100))
    image = image.resize((374, 275), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(.7))
    return image, tuple(round(value * .55) for value in rect)


class BlurredRasterReadingTests(unittest.TestCase):
    def test_blurred_decimals_are_read_independently_from_the_source(self):
        image, rect = blurred_chart(('0', '0.8', '1.6', '2.4', '3.2'))
        positions = [position for position, _ in td._axis_edge_tick_candidates(image, rect, 'x')]
        words = td._physical_tick_words(image, rect, 'x', positions)
        readings = [td._read_small_source_word(image, bbox, mask)
                    for _position, (mask, bbox) in sorted(words.items())]
        self.assertTrue(all(reading is not None for reading in readings), readings)
        self.assertEqual([0, .8, 1.6, 2.4, 3.2], [reading[1] for reading in readings])

    def test_real_integers_do_not_gain_guessed_decimal_points(self):
        image, rect = blurred_chart(('0', '8', '16', '24', '32'))
        detection = td._detect_axis(image, rect, 'x', td.AxisScale.LINEAR)
        self.assertTrue(detection.ready, detection)
        self.assertEqual([0, 8, 16, 24, 32], [tick.value for tick in detection.ticks])
        self.assertTrue(all('.' not in tick.text for tick in detection.ticks))

    def test_blur_template_search_polls_background_cancellation(self):
        image, rect = blurred_chart(('0', '0.8', '1.6', '2.4', '3.2'))
        gray = image.crop((259, 218, 275, 229)).convert('L')
        observed = td._normalized_gray_word(gray)
        calls = []
        def cancelled():
            calls.append(True)
            return len(calls) >= 3
        token = td._SOURCE_OCR_CANCEL.set(cancelled)
        try:
            with self.assertRaises(CancelledError):
                td._blurred_source_fit(observed, '2.4', 9)
        finally:
            td._SOURCE_OCR_CANCEL.reset(token)
        self.assertEqual(3, len(calls))
        self.assertIsNone(td._SOURCE_OCR_CANCEL.get())


if __name__ == '__main__':
    unittest.main()
