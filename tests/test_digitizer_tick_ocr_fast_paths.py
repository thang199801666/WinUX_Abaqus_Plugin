"""Focused independent-OCR accuracy and bounded-cache regressions."""
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat
from test_digitizer_tick_auto_calibration import make_chart, _font
from test_digitizer_tick_orientations import make_oriented_chart
from WinUx.plotdigitizer.core import tick_detection as td


class OcrFastPathTests(unittest.TestCase):

    def dense_tiny_decimal_chart(self, font_size=12):
        image = Image.new('RGB', (700, 520), 'white')
        draw = ImageDraw.Draw(image)
        font = _font(font_size)
        rect = (190, 70, 600, 430)
        left, top, right, bottom = rect
        for index, value in enumerate(i * .2 for i in range(9)):
            x = left + (right - left) * index / 8
            draw.line((x, top, x, bottom), fill=(225, 225, 225))
            text = ('{:.1f}'.format(value)).rstrip('0').rstrip('.')
            bbox = draw.textbbox((0, 0), text, font=font)
            draw.text((x - (bbox[2] - bbox[0]) / 2, bottom + 4), text,
                      font=font, fill=(105, 105, 105))
        for index, value in enumerate(i * 500 for i in range(9)):
            y = bottom - (bottom - top) * index / 8
            draw.line((left, y, right, y), fill=(225, 225, 225))
            text = str(value)
            bbox = draw.textbbox((0, 0), text, font=font)
            draw.text((left - (bbox[2] - bbox[0]) - 5,
                       y - (bbox[3] - bbox[1]) / 2 - 1), text,
                      font=font, fill=(105, 105, 105))
        draw.rectangle(rect, outline=(60, 60, 60), width=2)
        return image, rect

    def test_tiny_horizontal_decimal_axis_uses_context_without_upside_down_pass(self):
        image, rect = self.dense_tiny_decimal_chart(12)
        with patch.object(td, '_read_rotated_source_word',
                          side_effect=AssertionError('horizontal axis used rotated fallback')):
            result = td._detect_axis(image, rect, 'x', td.AxisScale.LINEAR)
        self.assertTrue(result.ready)
        self.assertEqual([round(i * .2, 6) for i in range(9)],
                         [round(t.value, 6) for t in result.ticks])

    def test_slot_centered_fallback_recovers_x_when_word_grouping_fails(self):
        image, rect = self.dense_tiny_decimal_chart(12)
        with patch.object(td, '_physical_tick_words', return_value={}):
            result = td._detect_axis(image, rect, 'x', td.AxisScale.LINEAR)
        self.assertTrue(result.ready)
        self.assertEqual([round(i * .2, 6) for i in range(9)],
                         [round(t.value, 6) for t in result.ticks])
        self.assertGreaterEqual(sum(t.bbox != (0, 0, 0, 0) for t in result.ticks), 3)

    def test_colored_guide_can_hide_grid_and_label_without_losing_tick_slot(self):
        image, rect = self.dense_tiny_decimal_chart(12)
        left, top, right, bottom = rect
        hidden_x = left + (right - left) / 8
        # Smart Region/selection overlays are saturated; this stroke completely
        # covers the neutral grid line and crosses the printed 0.2 label.
        ImageDraw.Draw(image).line((hidden_x, 0, hidden_x, image.height),
                                   fill=(0, 120, 215), width=2)
        result = td._detect_axis(image, rect, 'x', td.AxisScale.LINEAR)
        self.assertTrue(result.ready)
        self.assertEqual([round(i * .2, 6) for i in range(9)],
                         [round(t.value, 6) for t in result.ticks])
        inferred = min(result.ticks, key=lambda tick: abs(tick.position - hidden_x))
        self.assertAlmostEqual(.2, inferred.value, places=6)
        self.assertEqual((0, 0, 0, 0), inferred.bbox)
        self.assertIn(inferred.position, result.unread_positions)
        self.assertEqual(9, len(result.mark_positions))

    def test_partial_colored_occlusion_is_cleaned_after_axis_model_is_known(self):
        image, rect = self.dense_tiny_decimal_chart(12)
        left, top, right, bottom = rect
        target_x = left + (right - left) / 8
        # Cross the 0.2 label with a saturated one-pixel guide, but leave enough
        # neutral glyph evidence for post-model de-occlusion to verify it.
        ImageDraw.Draw(image).line((target_x - 2, 0, target_x - 2, image.height),
                                   fill=(0, 120, 215), width=1)
        result = td._detect_axis(image, rect, 'x', td.AxisScale.LINEAR)
        self.assertTrue(result.ready)
        self.assertEqual([round(i * .2, 6) for i in range(9)],
                         [round(t.value, 6) for t in result.ticks])
        recovered = min(result.ticks, key=lambda tick: abs(tick.position - target_x))
        self.assertAlmostEqual(.2, recovered.value, places=6)
        self.assertNotEqual((0, 0, 0, 0), recovered.bbox)
        self.assertNotIn(recovered.position, result.unread_positions)

    def test_deocclusion_preserves_neutral_pixels_next_to_thin_guide(self):
        image = Image.new('RGB', (15, 15), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 3, 10, 11), outline=(40, 40, 40))
        draw.line((8, 0, 8, 14), fill=(0, 120, 215))
        mask = td._deoccluded_colored_word_mask(image, (4, 3, 10, 11))
        self.assertIsNotNone(mask)
        self.assertEqual(1, mask[0][3])  # Neutral ink immediately left of guide.
        self.assertEqual(0, mask[0][4])  # Guide itself is erased.
        self.assertEqual(1, mask[0][5])  # Neutral ink immediately right of guide.

    def test_y_label_band_keeps_single_comma_descender(self):
        from test_digitizer_tick_scale_detection import _year_comma_log_chart_realistic
        from WinUx.plotdigitizer.core.axis_labels import read_joined_numeric_label
        image, rect, _years, expected = _year_comma_log_chart_realistic()
        _positions, words = td._label_driven_words(image, rect, 'y')
        readings = [read_joined_numeric_label(mask)
                    for _position, (mask, _bbox) in sorted(words.items())]
        self.assertTrue(all(reading is not None for reading in readings))
        self.assertEqual(list(expected), [reading[1] for reading in readings])

    def test_downscaled_blurred_chart_recovers_decimal_ticks(self):
        image, rect = make_chart()
        scale = .55
        image = image.resize((round(image.width * scale), round(image.height * scale)),
                             Image.Resampling.BILINEAR)
        image = image.filter(ImageFilter.GaussianBlur(.7))
        rect = tuple(round(value * scale) for value in rect)
        result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.ready, result)
        self.assertEqual([0, .8, 1.6, 2.4, 3.2],
                         [round(t.value, 6) for t in result.x.ticks])
        self.assertEqual([2000, 1500, 1000, 500, 0],
                         [round(t.value) for t in result.y.ticks])

    def test_nonuniform_geometry_does_not_get_regular_gap_inventions(self):
        positions = [100.0, 145.0, 215.0, 268.0, 350.0]
        self.assertEqual(positions,
                         td._complete_regular_mark_positions(positions, (100, 20, 350, 200), 'x'))

    def test_occluded_linear_tick_is_inferred_but_remains_marked_unread(self):
        image, rect = self.dense_tiny_decimal_chart(12)
        # Remove the printed "1" at the sixth major tick while leaving its
        # vertical grid stroke intact.
        ImageDraw.Draw(image).rectangle((438, 431, 455, 449), fill='white')
        result = td._detect_axis(image, rect, 'x', td.AxisScale.LINEAR)
        inferred = min(result.ticks, key=lambda tick: abs(tick.position - 446))
        self.assertTrue(result.ready)
        self.assertAlmostEqual(1.0, inferred.value, places=6)
        self.assertEqual((0, 0, 0, 0), inferred.bbox)
        self.assertIn(inferred.position, result.unread_positions)
        self.assertIn(inferred.position, result.mark_positions)

    def test_c_backed_mask_geometry_preserves_bbox_and_pixels(self):
        mask = [bytearray((0, 0, 1, 0, 0)),
                bytearray((0, 1, 1, 1, 0)),
                bytearray((0, 0, 1, 0, 0))]
        image = td._mask_image(mask)
        self.assertEqual((5, 3), image.size)
        self.assertEqual(bytes((0, 0, 255, 0, 0,
                                0, 255, 255, 255, 0,
                                0, 0, 255, 0, 0)), image.tobytes())
        self.assertEqual((1, 0, 3, 2), td._bbox(mask))

    def test_thick_neutral_grid_strokes_are_reported_at_their_centers(self):
        image = Image.new('RGB', (220, 180), 'white')
        draw = ImageDraw.Draw(image)
        rect = (20, 20, 200, 150)
        for x in (50, 110, 170):
            draw.line((x, rect[1], x, rect[3]), fill=(90, 90, 90), width=5)
        for y in (35, 85, 135):
            draw.line((rect[0], y, rect[2], y), fill=(110, 110, 110), width=5)
        # Saturated curve fragments must not pull the neutral line center.
        draw.line((25, 145, 195, 25), fill=(0, 120, 255), width=3)
        xs = [position for position, _ in td._line_peak_candidates(image, rect, 'x')]
        ys = [position for position, _ in td._line_peak_candidates(image, rect, 'y')]
        for expected in (50, 110, 170):
            self.assertLess(min(abs(position - expected) for position in xs), .55)
        for expected in (35, 85, 135):
            self.assertLess(min(abs(position - expected) for position in ys), .55)

    def test_y_label_driven_words_reuse_observed_lattice_without_pixel_rescan(self):
        image, rect = make_chart()
        positions = [position for position, _ in td._line_peak_candidates(image, rect, 'y')]
        self.assertGreaterEqual(len(positions), 3)
        with patch.object(td, '_refine_tick_positions',
                          side_effect=AssertionError('existing Y lattice was rescanned')):
            label_positions, words = td._label_driven_words(image, rect, 'y', positions)
        self.assertGreaterEqual(len(label_positions), 3)
        self.assertEqual(set(label_positions), set(words))
        spacing = td._median_spacing(sorted(positions))
        for position in label_positions:
            self.assertLessEqual(min(abs(position - expected) for expected in positions),
                                 max(5.0, spacing * .48))

    def test_rotated_iso_datetime_semantic_fast_path_skips_generic_rotated_ocr(self):
        from test_digitizer_tick_scale_detection import _rotated_iso_datetime_chart
        image, rect, x_dates, _y_values = _rotated_iso_datetime_chart()
        with patch.object(td, '_read_rotated_source_word',
                          side_effect=AssertionError('generic rotated numeric OCR ran before DateTime')):
            result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.x.ready)
        self.assertEqual(td.AxisScale.DATETIME, result.x.scale)
        self.assertEqual([value.isoformat() for value in x_dates],
                         [tick.text for tick in result.x.ticks])

    def test_ready_linear_y_with_zero_skips_log_decade_challenger(self):
        from test_digitizer_tick_scale_detection import _rotated_iso_datetime_chart
        image, rect, _x_dates, y_values = _rotated_iso_datetime_chart()
        with patch.object(td, '_log_decade_template_detection',
                          side_effect=AssertionError('zero-containing linear Y challenged as log')):
            result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.y.ready)
        self.assertEqual(td.AxisScale.LINEAR, result.y.scale)
        self.assertEqual(list(reversed(y_values)), [round(tick.value) for tick in result.y.ticks])

    def test_iso_date_composed_templates_match_direct_freetype_pixels(self):
        for text in ('2020-01-21', '2020-01-31', '2020-02-01', '1997-12-31'):
            for index, font in enumerate(td._template_fonts()):
                with self.subTest(text=text, font=index):
                    box = font.getbbox(text)
                    image = Image.new('L', (max(12, box[2] - box[0] + 10),
                                            max(16, box[3] - box[1] + 10)), 255)
                    ImageDraw.Draw(image).text((5 - box[0], 5 - box[1]), text, font=font, fill=0)
                    ink = image.point(td._WORD_TEMPLATE_LUT)
                    bounds = ink.getbbox()
                    direct = ink.crop(bounds) if bounds is not None else None
                    composed = td._composed_numeric_word(index, text, allow_hyphen=True)
                    self.assertIsNotNone(direct)
                    self.assertIsNotNone(composed)
                    self.assertEqual(direct.size, composed.size)
                    self.assertEqual(direct.tobytes(), composed.tobytes())

    def test_fully_measured_formatted_log_axis_skips_decade_rerender(self):
        from test_digitizer_tick_scale_detection import _year_comma_log_chart_realistic
        image, rect, _years, y_values = _year_comma_log_chart_realistic()
        with patch.object(td, '_log_decade_template_detection',
                          side_effect=AssertionError('complete formatted axis rerendered')):
            result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.y.ready)
        self.assertEqual(td.AxisScale.LOG10, result.y.scale)
        self.assertEqual(list(y_values), [round(tick.value) for tick in result.y.ticks])

    def test_word_candidate_cache_shares_only_identical_pixels_and_options(self):
        image = Image.new('L', (40, 24), 255)
        ImageDraw.Draw(image).text((3, 0), '2.4', font=_font(17), fill=0)
        mask = td._binary_mask(image)
        td._cached_word_candidates.cache_clear()
        first = td._independent_word_candidates(mask)
        self.assertTrue(first)
        first.append(('invalid', -123, 0))
        second = td._independent_word_candidates(mask)
        self.assertNotIn(('invalid', -123, 0), second)
        self.assertEqual(1, td._cached_word_candidates.cache_info().hits)
        td._independent_word_candidates(mask, width_multiplier=1.5)
        td._independent_word_candidates(mask, cut_prior=True)
        other = [bytearray(row) for row in mask]
        other[10][10] = 1 - other[10][10]
        td._independent_word_candidates(other)
        self.assertEqual(4, td._cached_word_candidates.cache_info().misses)
        self.assertLessEqual(td._cached_word_candidates.cache_info().maxsize, 1024)

    def test_fast_gray_difference_preserves_exact_pillow_scores(self):
        for size in ((1, 1), (7, 9), (41, 28)):
            count = size[0] * size[1]
            first = Image.frombytes('L', size, bytes((i * 37 + 13) % 256 for i in range(count)))
            for shift in (0, 1, 127, 255):
                second = Image.frombytes('L', size, bytes((i * 19 + shift) % 256 for i in range(count)))
                expected = ImageStat.Stat(ImageChops.difference(first, second)).mean[0] / 255.0
                self.assertEqual(expected, td._gray_difference(first, second))
            self.assertEqual(0, td._gray_difference(first, first))

    def test_native_digit_normalizes_once_and_reuses_pixel_cache(self):
        image = Image.new('L', (24, 24), 255)
        ImageDraw.Draw(image).text((3, 0), '6', font=_font(17), fill=0)
        mask = td._binary_mask(image)
        for char in '0123456789':
            td._glyph_templates(char)
        td._cached_classify_digit.cache_clear()
        with patch.object(td, '_normalized_mask', wraps=td._normalized_mask) as normalize:
            first = td._classify_digit(mask)
            self.assertEqual(1, normalize.call_count)
            self.assertEqual(first, td._classify_digit(mask))
            self.assertEqual(1, normalize.call_count)
        self.assertEqual('6', first[0])

    def test_font_face_is_reused_across_different_word_templates(self):
        self.assertIs(td._sized_template_font(0, 16), td._sized_template_font(0, 16))
        self.assertLessEqual(td._sized_template_font.cache_info().maxsize, 256)
        self.assertLessEqual(td._cached_rotated_source_word.cache_info().maxsize, 512)

    def test_hinted_phase_renders_only_requested_face_and_reuses_fallback_rasters(self):
        td._small_source_font_rasters.cache_clear()
        with patch.object(td, '_sized_template_font', wraps=td._sized_template_font) as font:
            hinted = td._small_source_rasters('12000', 5)
            self.assertEqual([(5, size) for size in (14, 16, 18)],
                             [call.args for call in font.call_args_list])
            all_fonts = td._small_source_rasters('12000')
            self.assertEqual(15, font.call_count)
            self.assertEqual(15, len(all_fonts))
            self.assertEqual(hinted, tuple(r for r in all_fonts if r[0] == 5))
            self.assertIs(hinted[0][1], td._small_source_rasters('12000', 5)[0][1])
            self.assertEqual(15, font.call_count)
        observed = td._normalized_gray_word(hinted[0][1], light=True)
        result = td._phase_raster_fit(observed, 35, 7, '12000', font_hint=5)
        with patch.object(td, '_small_source_rasters', return_value=tuple(r for r in all_fonts if r[0] == 5)):
            self.assertEqual(result, td._phase_raster_fit(observed, 35, 7, '12000', font_hint=5))
        self.assertEqual(5, result[1])
        self.assertLessEqual(td._small_source_font_rasters.cache_info().maxsize, 512)

    def test_rejected_font_hint_still_retries_all_faces(self):
        image = Image.new('L', (20, 12), 255)
        mask = [bytearray([1, 1]) for _ in range(7)]
        expected = ('2.4', 2.4, .9, 0)
        with patch.object(td, '_cached_small_source_word', side_effect=[None, expected]) as read:
            self.assertEqual(expected[:3], td._read_small_source_word(image, (2, 2, 4, 4), mask, font_hint=5))
            self.assertEqual([5, None], [call.args[-1] for call in read.call_args_list])

    def raster_chart(self, font_name, sy):
        path = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / font_name
        if not path.is_file():
            self.skipTest('Regression font unavailable: ' + font_name)
        with patch('test_digitizer_tick_auto_calibration._font',
                   side_effect=lambda size=16: ImageFont.truetype(str(path), size)):
            image, rect = make_chart()
        image = image.resize((816, round(500 * sy)), Image.Resampling.BICUBIC)
        rect = tuple(round(value * (1.2 if i % 2 == 0 else sy)) for i, value in enumerate(rect))
        return image, rect

    def test_compressed_serif_labels_do_not_need_enlarged_axis_retry(self):
        for sy in (.5, .65):
            with self.subTest(height_scale=sy):
                image, rect = self.raster_chart('times.ttf', sy)
                with patch.object(td, '_retry_small_y_labels', side_effect=AssertionError('whole-axis retry')):
                    result = td.detect_calibration_ticks(image, rect)
                self.assertTrue(result.ready)
                self.assertEqual([2000, 1500, 1000, 500, 0], [t.value for t in result.y.ticks])

    def test_compressed_bold_five_is_not_six(self):
        image, rect = self.raster_chart('arialbd.ttf', .65)
        result = td.detect_calibration_ticks(image, rect)
        self.assertEqual([2000, 1500, 1000, 500, 0], [t.value for t in result.y.ticks])

    def test_compression_phase_does_not_erase_two_or_close_five(self):
        for font, sy in (('timesbd.ttf', .5), ('timesbd.ttf', .65), ('arialbd.ttf', .5)):
            with self.subTest(font=font, scale=sy):
                image, rect = self.raster_chart(font, sy)
                with patch.object(td, '_robust_axis_values', side_effect=AssertionError('sequence repair')), \
                     patch.object(td, '_retry_small_y_labels', side_effect=AssertionError('whole-axis enlargement')):
                    result = td.detect_calibration_ticks(image, rect)
                self.assertEqual([2000, 1500, 1000, 500, 0], [t.value for t in result.y.ticks])
                self.assertFalse(result.y.unread_positions)

    def test_grayscale_cache_is_keyed_by_image_pixels_not_tick_position(self):
        image, rect = self.raster_chart('arialbd.ttf', .65)
        positions = [p for p, _ in td._line_peak_candidates(image, rect, 'y')]
        words = td._physical_tick_words(image, rect, 'y', positions)
        mask, bbox = words[min(positions)]
        td._cached_small_source_word.cache_clear()
        result = td._read_small_source_word(image, bbox, mask)
        self.assertEqual(result, td._read_small_source_word(image, bbox, mask))
        self.assertEqual(1, td._cached_small_source_word.cache_info().hits)
        other = image.copy()
        ImageDraw.Draw(other).rectangle((bbox[0], bbox[1], bbox[2], bbox[3]), fill='white')
        td._read_small_source_word(other, bbox, mask)
        self.assertEqual(2, td._cached_small_source_word.cache_info().misses)

    def test_run_length_components_preserve_diagonal_connectivity_and_area(self):
        mask = [bytearray((255, 0, 0, 0, 0, 0)),
                bytearray((0, 255, 0, 0, 255, 255)),
                bytearray((0, 0, 255, 0, 0, 255)),
                bytearray((0, 0, 0, 0, 0, 0))]
        self.assertEqual([(0, 0, 2, 2, 3), (4, 1, 5, 2, 3)], td._components(mask))

    def test_double_scale_chart_keeps_all_tick_words_without_axis_retry(self):
        image, rect = make_chart()
        image = image.resize((image.width * 2, image.height * 2), Image.Resampling.BICUBIC)
        rect = tuple(value * 2 for value in rect)
        with patch.object(td, '_retry_small_y_labels',
                          side_effect=AssertionError('unexpected whole-axis retry')):
            result = td.detect_calibration_ticks(image, rect)
        self.assertTrue(result.ready)
        self.assertEqual([0, .8, 1.6, 2.4, 3.2], [round(t.value, 6) for t in result.x.ticks])
        self.assertEqual([2000, 1500, 1000, 500, 0], [round(t.value) for t in result.y.ticks])

    def test_high_dpi_words_keep_detached_leading_digits(self):
        image, rect = make_chart()
        image = image.resize((image.width * 2, image.height * 2), Image.Resampling.BICUBIC)
        rect = tuple(value * 2 for value in rect)
        positions = sorted(p for p, _ in td._line_peak_candidates(image, rect, 'y'))
        words = td._physical_tick_words(image, rect, 'y', positions)
        self.assertEqual(5, len(words))
        self.assertEqual([2000, 1500, 1000, 500, 0],
                         [td._read_independent_word(words[p][0])[1] for p in positions])

    def test_compressed_words_are_read_individually_in_shuffled_order(self):
        # This test never supplies a neighbouring label or an axis fit to OCR.
        for font, sy in (('times.ttf', .65), ('timesbd.ttf', .5), ('arialbd.ttf', .65)):
            with self.subTest(font=font, scale=sy):
                image, rect = self.raster_chart(font, sy)
                positions = sorted(p for p, _ in td._line_peak_candidates(image, rect, 'y'))
                words = td._physical_tick_words(image, rect, 'y', positions)
                before = image.tobytes()
                for index in (3, 0, 4, 1, 2):
                    mask, bbox = words[positions[index]]
                    result = td._read_small_source_word(image, bbox, mask)
                    self.assertIsNotNone(result)
                    self.assertEqual((2000, 1500, 1000, 500, 0)[index], result[1])
                self.assertEqual(before, image.tobytes())

    def test_rotated_six_is_verified_without_neighbouring_values(self):
        image, rect, _, _ = make_oriented_chart(75, -75)
        positions = [p for p, _ in td._line_peak_candidates(image, rect, 'y')]
        words = td._physical_tick_words(image, rect, 'y', positions)
        _, bbox = words[220.0]
        angle = td._label_deskew_angle(list(words.values()))
        reading = td._read_rotated_source_word(image, bbox, angle)
        self.assertIsNotNone(reading)
        self.assertEqual(56000, reading[1])


    def test_y_retry_is_reserved_for_genuinely_tiny_or_complete_miss(self):
        normal = td.AxisTickDetection(
            'y',
            (td.TickReading(100.0, 2000.0, '2000', .55, (10, 10, 40, 18)),
             td.TickReading(200.0, 900.0, '900', .55, (10, 20, 34, 28))),
            .55, td.AxisScale.LINEAR, mark_positions=(100, 150, 200, 250))
        tiny = td.AxisTickDetection(
            'y',
            (td.TickReading(100.0, 2000.0, '2000', .55, (10, 10, 40, 16)),
             td.TickReading(200.0, 900.0, '900', .55, (10, 20, 34, 26))),
            .55, td.AxisScale.LINEAR, mark_positions=(100, 150, 200, 250))
        empty = td.AxisTickDetection('y', (), 0.0, td.AxisScale.LINEAR)
        self.assertFalse(td._small_y_retry_is_worthwhile(normal))
        self.assertTrue(td._small_y_retry_is_worthwhile(tiny))
        self.assertTrue(td._small_y_retry_is_worthwhile(empty))

    def test_near_vertical_decimal_does_not_lose_six(self):
        image, rect, values, _ = make_oriented_chart(75, -75)
        result = td._detect_axis(image, rect, 'x', td.AxisScale.LINEAR)
        self.assertEqual(values, [t.value for t in result.ticks])

    def test_fast_zero_sequence_keeps_occluded_tick_as_inferred(self):
        image, rect = make_chart()
        positions = [p for p, _ in td._line_peak_candidates(image, rect, 'y')]
        # Hide one printed 500 label while preserving the grid/tick geometry.
        ImageDraw.Draw(image).rectangle((55, 298, 102, 316), fill='white')
        result = td._zero_anchored_template_detection(
            image, rect, 'y', td.AxisScale.LINEAR, positions, fast_only=True)
        self.assertIsNotNone(result)
        self.assertTrue(result.ready)
        self.assertEqual([2000, 1500, 1000, 500, 0], [round(t.value) for t in result.ticks])
        inferred = min(result.ticks, key=lambda tick: abs(tick.position - 307))
        self.assertEqual((0, 0, 0, 0), inferred.bbox)
        self.assertIn(inferred.position, result.unread_positions)

    def test_fast_zero_sequence_recovers_endpoint_scale_when_rough_ocr_is_unusable(self):
        # Regression for blurred engineering screenshots: the grid lattice is
        # clear and the complete 4000..0 label column matches visually, while
        # independent glyph OCR returns no usable magnitude hints.  fast_only
        # must still try the bounded endpoint-zero template rescue instead of
        # abandoning Y detection.
        lattice = [100.0 + 50.0 * index for index in range(9)]
        expected = [str(value) for value in range(4000, -1, -500)]
        token_by_position = {position: index for index, position in enumerate(lattice)}

        def slot_masks(position):
            index = token_by_position[position]
            return [(0, index, (10, index * 10, 40, index * 10 + 8))]

        def score(observed, text):
            return .10 if text == expected[int(observed)] else .58

        with patch.object(td, '_normalize_word_mask', side_effect=lambda mask: mask), \
                patch.object(td, '_ocr_numeric', return_value=None), \
                patch.object(td, '_normalized_quick_word_score', side_effect=score), \
                patch.object(td, '_normalized_word_template_score', side_effect=score), \
                patch.object(td, '_word_template_score', side_effect=score):
            result = td._zero_anchored_template_detection(
                Image.new('RGB', (640, 560), 'white'),
                (150, 100, 600, 500), 'y', td.AxisScale.LINEAR, lattice,
                slot_masks=slot_masks, fast_only=True)

        self.assertIsNotNone(result)
        self.assertTrue(result.ready)
        self.assertEqual([4000, 3500, 3000, 2500, 2000, 1500, 1000, 500, 0],
                         [round(tick.value) for tick in result.ticks])

    def test_context_template_can_demote_tiny_linear_ocr_outlier(self):
        positions = [100.0 + 50.0 * index for index in range(8)]
        values = [0.0, .2, .4, .6, .8, 1.0, 3.2, 1.4]
        ticks = tuple(td.TickReading(position, value, str(value), .72, (1, 1, 8, 9))
                      for position, value in zip(positions, values))
        detection = td.AxisTickDetection('x', ticks, .72, td.AxisScale.LINEAR,
                                         mark_positions=tuple(positions))
        mask = [bytearray((0, 1, 1, 0)), bytearray((1, 1, 1, 1)),
                bytearray((0, 1, 1, 0)), bytearray((0, 1, 0, 0))]
        words = {position: (mask, (1, 1, 8, 9)) for position in positions}
        def score(_observed, text):
            if text == '1.2':
                return .14
            if text == '3.2':
                return .30
            return .50
        with patch.object(td, '_normalized_word_template_score', side_effect=score):
            repaired = td._infer_template_supported_linear_outliers(
                detection, words, positions)
        target = repaired.ticks[6]
        self.assertAlmostEqual(1.2, target.value, places=6)
        self.assertEqual((0, 0, 0, 0), target.bbox)
        self.assertIn(target.position, repaired.unread_positions)


if __name__ == '__main__':
    unittest.main()
