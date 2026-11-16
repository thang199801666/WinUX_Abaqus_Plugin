"""Low-contrast labels and transparent overlays must retain raster evidence."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image, ImageDraw, ImageOps
from WinUx.plotdigitizer.core import tick_detection as td
from test_digitizer_tick_auto_calibration import make_chart
import test_digitizer_tick_ocr_fast_paths as fast


def overlay_line(image, x, alpha, width=2):
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).line((x, 0, x, image.height), fill=(0, 120, 215, alpha), width=width)
    return Image.alpha_composite(image.convert('RGBA'), layer).convert('RGB')


def faint_chart(floor):
    image, rect = make_chart()
    lookup = [round(floor + value * (255 - floor) / 255) for value in range(256)]
    for box in ((0, rect[3] + 3, image.width, image.height),
                (0, 0, rect[0] - 3, image.height)):
        image.paste(image.crop(box).convert('L').point(lookup).convert('RGB'), box)
    return image, rect


class FaintOccludedTickTests(unittest.TestCase):
    def test_very_faint_labels_on_both_axes_keep_measured_values(self):
        for floor in (235, 245):
            with self.subTest(floor=floor):
                image, rect = faint_chart(floor)
                result = td.detect_calibration_ticks(image, rect)
                self.assertTrue(result.ready, result)
                self.assertEqual([0, .8, 1.6, 2.4, 3.2], [round(t.value, 6) for t in result.x.ticks])
                self.assertEqual([2000, 1500, 1000, 500, 0], [t.value for t in result.y.ticks])
                self.assertTrue(all(t.bbox != (0, 0, 0, 0) for t in result.x.ticks + result.y.ticks))

    def test_very_faint_light_labels_on_dark_background(self):
        image, rect = faint_chart(245)
        result = td.detect_calibration_ticks(ImageOps.invert(image), rect)
        self.assertTrue(result.ready, result)
        self.assertEqual([0, .8, 1.6, 2.4, 3.2], [round(t.value, 6) for t in result.x.ticks])
        self.assertEqual([2000, 1500, 1000, 500, 0], [t.value for t in result.y.ticks])

    def test_one_pale_label_among_dark_neighbours_is_measured_not_inferred(self):
        image, rect = make_chart()
        lookup = [round(245 + value * 10 / 255) for value in range(256)]
        for box in ((345, 395, 375, 420), (62, 217, 105, 235)):
            image.paste(image.crop(box).convert('L').point(lookup).convert('RGB'), box)
        result = td.detect_calibration_ticks(image, rect)
        for axis, position, expected in ((result.x, 360, 1.6), (result.y, 225, 1000)):
            with self.subTest(axis=axis.axis):
                tick = min(axis.ticks, key=lambda tick: abs(tick.position - position))
                self.assertAlmostEqual(expected, tick.value)
                self.assertNotEqual((0, 0, 0, 0), tick.bbox)
                self.assertNotIn(tick.position, axis.unread_positions)

    def test_translucent_guides_restore_visible_neutral_ink_instead_of_erasing_it(self):
        base = Image.new('RGB', (40, 22), 'white')
        draw = ImageDraw.Draw(base)
        draw.rectangle((4, 4, 10, 14), outline=(40, 40, 40), width=2)
        draw.rectangle((14, 13, 15, 14), fill=(40, 40, 40))
        draw.line((20, 4, 27, 4, 27, 9, 20, 14, 27, 14), fill=(40, 40, 40), width=2)
        bbox = (4, 4, 28, 15)
        original = td._binary_mask(base.crop((bbox[0], bbox[1], bbox[2] + 1, bbox[3] + 1)))
        original = td._crop_mask(original, td._bbox(original))
        for alpha in (32, 64, 128, 192, 224):
            with self.subTest(alpha=alpha):
                image = overlay_line(base, 9, alpha)
                restored = td._deoccluded_colored_word_mask(image, bbox)
                self.assertEqual(original, restored)

    def test_low_chroma_guide_is_detected_but_colored_glyph_is_not_a_guide(self):
        image = Image.new('RGB', (40, 30), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((17, 9, 20, 20), fill=(200, 220, 235))
        bbox = (17, 9, 20, 20)
        self.assertEqual(0, td._colored_guide_occlusion_score(image, 'x', 19, bbox))
        image = overlay_line(image, 19, 32)
        self.assertGreater(td._colored_guide_occlusion_score(image, 'x', 19, bbox), .5)

    def test_partial_translucent_guides_recover_measured_decimal_ticks(self):
        base, rect = fast.OcrFastPathTests().dense_tiny_decimal_chart(12)
        position = rect[0] + (rect[2] - rect[0]) / 8
        for alpha in (32, 128, 192):
            with self.subTest(alpha=alpha):
                image = overlay_line(base, position - 2, alpha, width=2)
                result = td._detect_axis(image, rect, 'x', td.AxisScale.LINEAR)
                self.assertTrue(result.ready)
                tick = min(result.ticks, key=lambda tick: abs(tick.position - position))
                self.assertAlmostEqual(.2, tick.value)
                self.assertNotEqual((0, 0, 0, 0), tick.bbox)
                self.assertNotIn(tick.position, result.unread_positions)

    def test_opaque_missing_ink_is_not_promoted_to_measured_data(self):
        base, rect = fast.OcrFastPathTests().dense_tiny_decimal_chart(12)
        position = rect[0] + (rect[2] - rect[0]) / 8
        draw = ImageDraw.Draw(base)
        draw.rectangle((position - 12, rect[3] + 2, position + 12, rect[3] + 19),
                       fill=(0, 120, 215))
        result = td._detect_axis(base, rect, 'x', td.AxisScale.LINEAR)
        measured = [tick for tick in result.ticks
                    if abs(tick.position - position) < 8 and tick.bbox != (0, 0, 0, 0)]
        self.assertFalse(measured)

    def test_nonuniform_background_is_not_promoted_by_faint_mask(self):
        image = Image.frombytes('L', (32, 8), bytes(range(256)))
        self.assertIsNone(td._faint_label_mask(image))


if __name__ == '__main__':
    unittest.main()
