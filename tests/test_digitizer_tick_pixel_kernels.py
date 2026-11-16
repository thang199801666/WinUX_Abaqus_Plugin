"""Exact OCR primitive parity and bounded, mutation-safe component caches."""
import contextlib
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image
from WinUx.plotdigitizer.core import tick_detection as td


def reference_mask_image(mask):
    if not mask or not mask[0]:
        return Image.new('L', (1, 1), 0)
    return Image.frombytes('L', (len(mask[0]), len(mask)), b''.join(mask)).point(
        [0 if value == 0 else 255 for value in range(256)])


def reference_binary_mask(image):
    gray = image.convert('L')
    histogram = gray.histogram()[:256]
    mode = max(range(256), key=lambda value: histogram[value])
    otsu = td._otsu_threshold(gray)
    if mode >= 128:
        threshold = min(mode - 8, max(otsu, mode - 62))
        lookup = [int(value <= threshold) for value in range(256)]
    else:
        threshold = max(mode + 8, min(otsu, mode + 62))
        lookup = [int(value >= threshold) for value in range(256)]
    pixels = gray.point(lookup).tobytes()
    return [bytearray(pixels[y * gray.width:(y + 1) * gray.width]) for y in range(gray.height)]


def reference_normalized_mask(mask, width=20, height=28):
    box = td._bbox(mask)
    if box is None:
        return Image.new('1', (width, height), 0)
    cropped = reference_mask_image(td._crop_mask(mask, box))
    cw, ch = cropped.size
    scale = min((width - 2) / max(1, cw), (height - 2) / max(1, ch))
    rw, rh = max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))
    resized = cropped.resize((rw, rh), Image.Resampling.BILINEAR).point(
        lambda value: 255 if value >= 96 else 0)
    result = Image.new('1', (width, height), 0)
    result.paste(resized.convert('1'), ((width - rw) // 2, (height - rh) // 2))
    return result


def clear_ocr_caches():
    for value in vars(td).values():
        clear = getattr(value, 'cache_clear', None)
        if callable(clear):
            clear()


@contextlib.contextmanager
def reference_kernels():
    clear_ocr_caches()
    with patch.object(td, '_components', side_effect=td._components_uncached), \
            patch.object(td, '_point_lut', side_effect=lambda image, lookup: image.point(lookup)), \
            patch.object(td, '_column_sums', side_effect=lambda mask: [
                sum(mask[y][x] for y in range(len(mask))) for x in range(len(mask[0]))] if mask else []), \
            patch.object(td, '_mask_image', side_effect=reference_mask_image), \
            patch.object(td, '_binary_mask', side_effect=reference_binary_mask), \
            patch.object(td, '_normalized_mask', side_effect=reference_normalized_mask):
        yield
    clear_ocr_caches()


class TickPixelKernelTests(unittest.TestCase):
    def test_threshold_pixels_match_pillow_for_both_polarities_and_output_scales(self):
        image = Image.frombytes('L', (32, 8), bytes(range(256)))
        for threshold in (-1, 0, 48, 96, 128, 193, 225, 255, 256):
            for dark in (True, False):
                for peak in (1, 255):
                    lookup = [peak if (v <= threshold if dark else v >= threshold) else 0
                              for v in range(256)]
                    observed = td._point_lut(image, td._threshold_lut(threshold, dark=dark, peak=peak))
                    self.assertEqual(image.point(lookup).tobytes(), observed.tobytes())

    def test_non_l_images_keep_pillow_point_semantics(self):
        image = Image.new('1', (32, 8), 1)
        lookup = td._threshold_lut(96, dark=False, peak=255)
        observed = td._point_lut(image, lookup)
        expected = image.point(lookup)
        self.assertEqual(observed.mode, expected.mode)
        self.assertEqual(observed.tobytes(), expected.tobytes())

    def test_binary_and_normalized_masks_match_legacy_pixels(self):
        rng = random.Random(607)
        for width, height in ((1, 1), (13, 19), (60, 28)):
            for background in (0, 127, 255):
                image = Image.frombytes('L', (width, height), bytes(
                    background if rng.random() < .6 else rng.randrange(256)
                    for _ in range(width * height)))
                expected = reference_binary_mask(image)
                self.assertEqual(td._binary_mask(image), expected)
                self.assertEqual(td._mask_image(expected).tobytes(), reference_mask_image(expected).tobytes())
                self.assertEqual(td._normalized_mask(expected).tobytes(),
                                 reference_normalized_mask(expected).tobytes())

    def test_column_projections_preserve_exact_counts_even_for_tall_masks(self):
        rng = random.Random(701)
        for width, height in ((1, 1), (23, 17), (7, 512)):
            mask = [bytearray(rng.choice((0, 1, 255)) for _ in range(width)) for _ in range(height)]
            self.assertEqual(td._column_sums(mask), [
                sum(mask[y][x] for y in range(height)) for x in range(width)])
        self.assertEqual(td._column_sums([]), [])

    def test_component_cache_matches_uncached_scan(self):
        rng = random.Random(614)
        for width, height in ((1, 1), (19, 27), (80, 60)):
            for probability in (.05, .4, .95):
                mask = [bytearray(rng.choice((1, 255)) if rng.random() < probability else 0
                                  for _ in range(width)) for _ in range(height)]
                self.assertEqual(td._components(mask), td._components_uncached(mask))

    def test_component_cache_keys_dimensions_and_actual_pixels(self):
        td._cached_components.cache_clear()
        self.assertEqual(td._components([bytearray((1, 1, 1, 1))]), [(0, 0, 3, 0, 4)])
        self.assertEqual(td._components([bytearray((1, 1)), bytearray((1, 1))]), [(0, 0, 1, 1, 4)])
        mask = [bytearray((1, 0, 0))]
        td._components(mask)
        mask[0][2] = 1
        self.assertEqual(td._components(mask), [(0, 0, 0, 0, 1), (2, 0, 2, 0, 1)])
        self.assertEqual(td._components([[1, 0], [0, 255]]), [(0, 0, 1, 1, 2)])

    def test_cache_does_not_share_mutable_results_and_large_strips_bypass_it(self):
        td._cached_components.cache_clear()
        mask = [bytearray((1, 1, 0))]
        result = td._components(mask)
        result.clear()
        self.assertEqual(td._components(mask), [(0, 0, 1, 0, 2)])
        before = td._cached_components.cache_info()
        strip = [bytearray([0] * 9000) for _ in range(2)]
        strip[0][10] = 1
        self.assertEqual(td._components(strip), [(10, 0, 10, 0, 1)])
        self.assertEqual(td._cached_components.cache_info(), before)
        self.assertEqual(td._components([bytearray([1] * 32) for _ in range(32)]), [(0, 0, 31, 31, 1024)])
        self.assertEqual(td._cached_components.cache_info(), before)
        self.assertEqual(before.maxsize, 128)
        self.assertEqual(td._threshold_lut.cache_info().maxsize, 512)

    def test_full_linear_and_datetime_ocr_match_reference_kernels(self):
        from test_digitizer_tick_auto_calibration import make_chart
        from test_digitizer_tick_scale_detection import _rotated_iso_datetime_chart
        for image, rect in (make_chart(), _rotated_iso_datetime_chart()[:2]):
            clear_ocr_caches()
            observed = td.detect_calibration_ticks(image, rect)
            with reference_kernels():
                expected = td.detect_calibration_ticks(image, rect)
            self.assertEqual(observed, expected)


if __name__ == '__main__':
    unittest.main()
