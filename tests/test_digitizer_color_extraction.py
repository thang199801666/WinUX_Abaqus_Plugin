"""Chosen colored strokes must not match nearby neutral axes/frame pixels."""
from io import BytesIO
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image, ImageDraw
from WinUx.plotdigitizer.core import DigitizerEngine, ExtractionSettings
from WinUx.plotdigitizer.core.extraction import extract_curve, sample_color


GREEN = (143, 194, 142)


def chart(color=GREEN):
    image = Image.new('RGB', (220, 250), 'white')
    draw = ImageDraw.Draw(image)
    # The neutral antialiased edge is within default RGB tolerance of GREEN.
    # It starts before the curve and used to trap the continuity tracker.
    draw.line((0, 239, 219, 239), fill=(155, 155, 155))
    draw.line((0, 240, 219, 240), fill=(10, 10, 10), width=2)
    draw.line((4, 0, 4, 240), fill=(25, 25, 25), width=2)
    draw.line((0, 215, 219, 215), fill=(220, 60, 65))
    draw.line((0, 225, 219, 225), fill=(60, 75, 220))
    draw.line([(x, 200 - x // 2) for x in range(20, 201)], fill=color)
    return image


class ColorExtractionTests(unittest.TestCase):
    def assert_green_curve(self, points):
        self.assertGreaterEqual(len(points), 170)
        for x, y in points:
            self.assertTrue(20 <= x <= 200, (x, y))
            self.assertLessEqual(abs(y - (200 - int(x) // 2)), 1, (x, y))

    def test_pastel_green_ignores_black_axis_and_gray_edge(self):
        image = chart()
        self.assert_green_curve(extract_curve(image, (0, 0, 219, 249), GREEN, ExtractionSettings()))

    def test_high_tolerance_does_not_match_gray_white_red_or_blue(self):
        image = chart()
        settings = ExtractionSettings(tolerance=255)
        self.assert_green_curve(extract_curve(image, (0, 0, 219, 249), GREEN, settings))

    def test_pale_green_does_not_match_white_background(self):
        color = (220, 240, 220)
        self.assert_green_curve(extract_curve(chart(color), (0, 0, 219, 249), color, ExtractionSettings()))

    def test_dark_green_does_not_match_black_or_gray(self):
        color = (10, 50, 10)
        self.assert_green_curve(extract_curve(chart(color), (0, 0, 219, 249), color, ExtractionSettings()))

    def test_color_picker_does_not_average_thin_green_stroke_into_gray(self):
        image = Image.new('RGB', (9, 9), (155, 155, 155))
        image.putpixel((4, 4), GREEN)
        self.assertEqual(sample_color(image, 4, 4), GREEN)

    def test_rgb_tolerance_still_applies_with_matching_hue(self):
        image = Image.new('RGB', (30, 30), 'white')
        ImageDraw.Draw(image).line((0, 15, 29, 15), fill=(0, 100, 0))
        self.assertEqual(extract_curve(image, (0, 0, 29, 29), GREEN, ExtractionSettings(tolerance=20)), [])

    def test_red_hue_wraparound_is_supported(self):
        image = Image.new('RGB', (30, 30), 'white')
        ImageDraw.Draw(image).line((0, 15, 29, 15), fill=(220, 30, 20))
        points = extract_curve(image, (0, 0, 29, 29), (220, 20, 30), ExtractionSettings())
        self.assertEqual(len(points), 30)
        self.assertTrue(all(y == 15 for x, y in points))

    def test_black_stroke_still_extracts(self):
        image = Image.new('RGB', (30, 30), 'white')
        ImageDraw.Draw(image).line((0, 15, 29, 15), fill=(25, 25, 25))
        points = extract_curve(image, (0, 0, 29, 29), (25, 25, 25), ExtractionSettings())
        self.assertEqual(len(points), 30)
        self.assertTrue(all(y == 15 for x, y in points))

    def test_explicit_color_is_preserved_by_background_computation(self):
        engine = DigitizerEngine()
        image = chart()
        result = engine.compute_smart_detect(image=image, roi=(0, 0, 219, 249), curve_rgb=GREEN)
        self.assertIsNone(result.error)
        self.assertEqual(result.curve_rgb, GREEN)
        self.assert_green_curve(result.extracted_pixels)

    def test_crossings_do_not_switch_to_red_or_blue_curve(self):
        image = chart()
        draw = ImageDraw.Draw(image)
        draw.line((20, 130, 200, 160), fill=(220, 60, 65), width=2)
        draw.line((20, 175, 200, 165), fill=(60, 75, 220), width=2)
        self.assert_green_curve(extract_curve(
            image, (0, 0, 219, 249), GREEN, ExtractionSettings(tolerance=255)))

    def test_jpeg_stroke_and_gray_antialiased_axes(self):
        stream = BytesIO()
        chart().save(stream, format='JPEG', quality=85, subsampling=0)
        stream.seek(0)
        image = Image.open(stream).convert('RGB')
        target = sample_color(image, 100, 150)
        points = extract_curve(image, (0, 0, 219, 249), target, ExtractionSettings())
        self.assertGreaterEqual(len(points), 150)
        for x, y in points:
            self.assertTrue(18 <= x <= 202, (x, y))
            self.assertLessEqual(abs(y - (200 - int(x) // 2)), 2, (x, y))

    def test_absent_selected_color_reports_failure_instead_of_falling_back(self):
        image = Image.new('RGB', (100, 80), 'white')
        draw = ImageDraw.Draw(image)
        draw.line((0, 60, 99, 60), fill=(155, 155, 155))
        draw.line((0, 61, 99, 61), fill='black')
        draw.line((0, 30, 99, 30), fill=(220, 60, 65))
        result = DigitizerEngine().compute_smart_detect(
            image=image, roi=(0, 0, 99, 79), curve_rgb=GREEN)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.extracted_pixels, [])
        self.assertEqual(result.curve_rgb, GREEN)


if __name__ == '__main__':
    unittest.main()
