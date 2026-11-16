"""Accelerated/scalar parity, bounded masks, cancellation and detector inputs."""
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image, ImageDraw, ImageOps
from WinUx.plotdigitizer.core import DigitizerEngine, ExtractionSettings
from WinUx.plotdigitizer.core import extraction

NP = extraction.np


def chart():
    image = Image.new('RGB', (173, 131), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 7, 165, 120), outline=(35, 35, 35))
    for x in range(12, 160):
        if 65 <= x <= 74:
            continue
        y = 110 - x // 3
        draw.line((x, y - 2, x, y + 2), fill=(220, 45, 55))
    draw.line((12, 50, 155, 50), fill=(50, 75, 220), width=2)
    return image


class DetectorInputTests(unittest.TestCase):
    def test_invalid_regions_have_clear_errors(self):
        image = chart()
        for roi in ((-1, 0, 20, 20), (0, 0, 999, 20), (10, 0, 2, 20),
                    (0, 20, 10, 2), (0.5, 0, 10, 10), (0, 0, 10), None):
            with self.subTest(roi=roi):
                with self.assertRaises(ValueError):
                    extraction.extract_curve(image, roi, (220, 45, 55), ExtractionSettings())
                with self.assertRaises(ValueError):
                    extraction.detect_curve_colors(image, roi)

    def test_engine_normalizes_invalid_region_error(self):
        engine = DigitizerEngine()
        result = engine.compute_smart_detect(image=chart(), roi=(-1, 0, 20, 20), curve_rgb=(220, 45, 55))
        self.assertIsNotNone(result.error)
        self.assertEqual(result.extracted_pixels, [])

    def test_engine_converts_non_rgb_only_once_for_the_pipeline(self):
        image = chart().convert('RGBA')
        expected = DigitizerEngine().compute_smart_detect(image=image.convert('RGB'))
        with patch.object(image, 'convert', wraps=image.convert) as convert:
            observed = DigitizerEngine().compute_smart_detect(image=image)
        convert.assert_called_once_with('RGB')
        self.assertEqual(observed, expected)

    def test_non_rgb_modes_match_explicit_rgb_conversion(self):
        for mode in ('L', 'RGBA', 'P'):
            image = chart().convert(mode)
            rgb = image.convert('RGB')
            target = extraction.sample_color(image, 100, 77)
            roi = (8, 7, 165, 120)
            self.assertEqual(extraction.sample_color(image, 100, 77), extraction.sample_color(rgb, 100, 77))
            self.assertEqual(extraction.extract_curve(image, roi, target, ExtractionSettings()),
                             extraction.extract_curve(rgb, roi, target, ExtractionSettings()))
            self.assertEqual(extraction.detect_plot_area(image), extraction.detect_plot_area(rgb))

    def test_zero_palette_limit_and_empty_image(self):
        self.assertEqual(extraction.detect_curve_colors(chart(), (0, 0, 10, 10), limit=0), [])
        with self.assertRaises(ValueError):
            extraction.detect_plot_area(Image.new('RGB', (0, 0)))

    def test_smoothing_matches_legacy_window_averages(self):
        points = [(float(x), (x * 13 % 79) / 2) for x in range(300)]
        for requested in (1, 2, 3, 9, 41, 1000):
            window = requested + 1 if requested % 2 == 0 else requested
            half = window // 2
            expected = [(x, sum(p[1] for p in points[max(0, i - half):i + half + 1]) /
                         len(points[max(0, i - half):i + half + 1])) for i, (x, _) in enumerate(points)]
            self.assertEqual(extraction._moving_average(points, requested), expected)

    def test_full_curve_pipeline_still_works_without_numpy(self):
        with patch.object(extraction, 'np', None):
            result = DigitizerEngine().compute_smart_detect(
                image=chart(), roi=(8, 7, 165, 120), curve_rgb=(220, 45, 55))
        self.assertIsNone(result.error)
        self.assertEqual(result.curve_rgb, (220, 45, 55))
        self.assertGreater(len(result.extracted_pixels), 100)


@unittest.skipIf(NP is None, 'NumPy is optional')
class DetectorAccelerationTests(unittest.TestCase):
    def compare(self, operation, *args, **kwargs):
        with patch.object(extraction, 'np', None):
            scalar = operation(*args, **kwargs)
        with patch.object(extraction, 'np', NP):
            accelerated = operation(*args, **kwargs)
        self.assertEqual(accelerated, scalar)
        return accelerated

    def test_color_mask_exactly_matches_scalar_rgb_hue_rules(self):
        rng = random.Random(614)
        colors = [(r, g, b) for r in range(0, 256, 17)
                  for g in range(0, 256, 17) for b in range(0, 256, 17)]
        colors += [tuple(rng.randrange(256) for _ in range(3)) for _ in range(1000)]
        pixels = NP.array(colors, dtype=NP.uint8).reshape((-1, 1, 3))
        for target in ((255, 20, 30), (143, 194, 142), (220, 240, 220), (10, 50, 10),
                       (25, 25, 25), (255, 255, 255), (0, 0, 0), (255, 153, 0)):
            for tolerance in (0, 20, 55, 255, 442):
                matches = extraction._color_matcher(target, tolerance)
                expected = [matches(rgb) for rgb in colors]
                observed = extraction._color_match_mask(pixels, target, tolerance).ravel().tolist()
                self.assertEqual(observed, expected, (target, tolerance))

    def test_run_centers_stride_gaps_and_smoothing_match(self):
        image = chart()
        base = ExtractionSettings()
        for stride in (1, 3, 23):
            for min_hits in (1, 2, 4):
                for smoothing in (1, 3, 8):
                    cfg = replace(base, stride=stride, min_hits=min_hits,
                                  smoothing=smoothing, max_gap_columns=2)
                    self.compare(extraction.extract_curve, image, (9, 8, 163, 119), (220, 45, 55), cfg)

    def test_region_profiles_preserve_light_dark_and_resized_detection(self):
        for image in (chart(), ImageOps.invert(chart()), chart().resize((903, 705)),
                      Image.new('RGB', (97, 83), 'white'), Image.new('RGB', (97, 83), 'black')):
            self.compare(extraction.detect_plot_area, image)

    def test_sample_grid_is_identical_to_pixel_access(self):
        image = chart()
        roi = (3, 5, 160, 118)
        observed = extraction._sampled_rgb(image, roi, 7, 9, None).tolist()
        expected = [[list(image.getpixel((x, y))) for x in range(3, 161, 7)] for y in range(5, 119, 9)]
        self.assertEqual(observed, expected)

    def test_palette_preserves_coverage_and_stable_tie_order(self):
        image = Image.new('RGB', (80, 60), 'white')
        draw = ImageDraw.Draw(image)
        for row, color in ((10, (230, 30, 40)), (20, (40, 50, 230)), (30, (40, 180, 60))):
            draw.line((5, row, 70, row), fill=color)
        # Same coverage/count: red must win because it appears first, not
        # because its quantized RGB key sorts before another color.
        colors = self.compare(extraction.detect_curve_colors, image, (0, 0, 79, 59))
        self.assertEqual(colors[0], (230, 30, 40))
        for limit in (1, 2, 6):
            self.compare(extraction.detect_curve_colors, image, (3, 2, 75, 50), limit=limit)

    def test_palette_matches_scalar_on_noisy_and_quantized_images(self):
        rng = random.Random(732)
        image = Image.new('RGB', (97, 83))
        image.putdata([tuple(rng.randrange(256) for _ in range(3)) for _ in range(97 * 83)])
        for saturation in (0, 70, 255):
            self.compare(extraction.detect_curve_colors, image, (2, 3, 94, 80), saturation)
        self.compare(extraction.detect_curve_colors, chart().resize((903, 705)), (0, 0, 902, 704))

    def test_small_tiles_do_not_change_endpoints_or_allocate_whole_roi(self):
        image = chart()
        cfg = ExtractionSettings(stride=3)
        with patch.object(extraction, '_PIXEL_TILE_SIZE', 600), \
                patch.object(extraction, '_color_match_mask', wraps=extraction._color_match_mask) as masks:
            self.compare(extraction.extract_curve, image, (9, 8, 163, 119), (220, 45, 55), cfg)
            self.assertGreater(masks.call_count, 1)
            for call in masks.call_args_list:
                height, width = call.args[0].shape[:2]
                self.assertLessEqual(height * width, 600)

    def test_cancellation_after_mask_computation_is_not_swallowed(self):
        cancelled = [False]
        original = extraction._color_match_mask

        def mask(*args):
            result = original(*args)
            cancelled[0] = True
            return result

        with patch.object(extraction, '_color_match_mask', side_effect=mask):
            with self.assertRaises(CancelledError):
                extraction.extract_curve(chart(), (0, 0, 172, 130), (220, 45, 55),
                                         ExtractionSettings(), cancelled=lambda: cancelled[0])

    def test_region_cancellation_during_sampling(self):
        calls = [0]

        def cancelled():
            calls[0] += 1
            return calls[0] >= 8

        with self.assertRaises(CancelledError):
            extraction.detect_plot_area(chart(), cancelled=cancelled)
        self.assertEqual(calls[0], 8)

    def test_palette_cancellation_after_grouping_discards_partial_result(self):
        cancelled = [False]
        unique = NP.unique

        def grouping(*args, **kwargs):
            result = unique(*args, **kwargs)
            cancelled[0] = True
            return result

        with patch.object(NP, 'unique', side_effect=grouping):
            with self.assertRaises(CancelledError):
                extraction.detect_curve_colors(chart(), (0, 0, 172, 130),
                                               cancelled=lambda: cancelled[0])


if __name__ == '__main__':
    unittest.main()
