from __future__ import annotations

import math
import statistics

from PIL import Image

from ..models import AxisScale
from ..region_detection import align_region_to_axes
from .axis_math import _inverse_value, _transform_value
from .recognition import (
    _axis_edge_tick_candidates, _coherent_major_mark_subset, _consensus_numeric_reading,
    _independent_word_candidates, _label_deskew_angle, _line_peak_candidates,
    _major_axis_edge_subset, _merge_axis_mark_sources, _observed_axis_scale,
    _physical_tick_words, _read_fast_independent_word, _read_independent_word,
    _read_probe_word, _read_scientific_glyph_word, _read_scientific_word,
    _rotate_mask, _scientific_reading_beats, _word_contrast_masks,
)
from .sequences import (
    _augment_regular_positions_from_labels, _axis_completion_supported,
    _candidate_supported_linear_sequence, _colored_guide_occlusion_score,
    _complete_lattice_ticks, _complete_regular_mark_positions,
    _infer_occluded_linear_outliers, _infer_template_supported_linear_outliers,
    _infer_template_supported_log_outliers, _iso_datetime_sequence_detection,
    _label_driven_words, _log_decade_template_detection,
    _recover_occluded_axis_readings, _repair_ambiguous_linear_readings,
    _slot_probe_axis, _year_sequence_detection, _zero_anchored_template_detection,
)
from .shared import _SOURCE_OCR_CANCEL
from .source_ocr import (
    _check_tick_cancelled, _read_blurred_source_word, _read_rotated_source_word,
    _read_small_source_word, _read_upscaled_source_word,
)
from .types import AxisTickDetection, TickCalibrationDetection, TickReading

def _detect_axis(image, rect, axis, scale, *, cancelled=None, progress=None, fast_retry=False):
    token = _SOURCE_OCR_CANCEL.set(cancelled)
    try:
        return _detect_axis_impl(image, rect, axis, scale, cancelled=cancelled,
                                 progress=progress, fast_retry=fast_retry)
    finally:
        _SOURCE_OCR_CANCEL.reset(token)


def _detect_axis_impl(image, rect, axis, scale, *, cancelled=None, progress=None, fast_retry=False):
    # Only observed strokes are candidates. Nonlinear tick distributions and
    # unusual endpoint labels remain legitimate observations. A conservative
    # completion step is allowed only after a strongly linear set of measured
    # labels has already passed verification; inferred entries stay marked as
    # non-OCR (empty bbox) and never replace measured calibration points.
    # A mouse-drawn Box may sit a few pixels inside the outermost grid stroke.
    # Search a small margin for *observed* endpoint strokes; never invent one.
    _check_tick_cancelled(cancelled)
    left, top, right, bottom = rect
    search_rect = ((max(0, left - 4), top, min(image.width - 1, right + 4), bottom)
                   if axis == 'x' else
                   (left, max(0, top - 4), right, min(image.height - 1, bottom + 4)))
    line_candidates = _line_peak_candidates(image, search_rect, axis)
    edge_candidates = _major_axis_edge_subset(_axis_edge_tick_candidates(image, rect, axis))
    # Three or more edge-contact marks form a stronger geometry source than
    # arbitrary long strokes elsewhere in the plot.  Fuse both so clipped
    # endpoints from either source survive while direct axis marks dominate
    # their local coordinate.
    candidates = _merge_axis_mark_sources(line_candidates, edge_candidates)
    # Label geometry is direct evidence and also protects legitimate irregular
    # marks from the regular-lattice outlier filter.  This label view is reused
    # below, so moving it ahead of geometry consensus does not add another OCR
    # scan to the normal path.
    label_positions = ()
    label_words = {}
    if ((axis == 'x' and scale in (AxisScale.LINEAR, AxisScale.DATETIME)) or
            (axis == 'y' and scale in (AxisScale.LINEAR, AxisScale.LOG10))):
        raw_positions = [position for position, _ in candidates]
        label_positions, label_words = _label_driven_words(
            image, rect, axis, raw_positions)
    candidates = _coherent_major_mark_subset(candidates, label_positions)
    positions = [position for position, _ in candidates]
    # A colored Smart Region/selection guide can cover a neutral grid line so
    # completely that the neutral-line detector no longer sees that major tick.
    # Recover only strict interior lattice gaps; nonuniform axes are untouched.
    positions = _complete_regular_mark_positions(positions, rect, axis)
    if axis == 'y' and len(positions) >= 3:
        positions = _augment_regular_positions_from_labels(image, rect, axis, positions)
    _check_tick_cancelled(cancelled)
    words = _physical_tick_words(image, rect, axis, positions)
    # Published charts often omit vertical X grid lines entirely (year/date
    # axes are a common example). When stroke geometry yields fewer than three
    # usable words, take geometry from the coherent printed label row itself.
    # Values are still read independently by the normal OCR pipeline below.
    if axis == 'x':
        # Short axis ticks themselves can survive the scan-rule remover and be
        # associated as 1x4 pseudo-words.  Count only text-shaped objects when
        # deciding whether physical geometry produced usable labels; otherwise
        # fall back to the coherent label row just as on grid-less charts.
        textlike_words = sum(1 for _mask, bbox in words.values()
                             if bbox[3] - bbox[1] + 1 >= 6
                             and bbox[2] - bbox[0] + 1 >= 3)
        if len(positions) < 3 or textlike_words < 3:
            label_positions, label_words = _label_driven_words(image, rect, axis, positions)
            if len(label_positions) >= 3:
                positions, words = list(label_positions), label_words
        for position, word in label_words.items():
            near = min(positions, key=lambda value: abs(value - position), default=None)
            if near is None or abs(near - position) > 2.5:
                continue
            current = words.get(near)
            if (current is None or current[1][2] - current[1][0] + 1 < 3
                    or current[1][3] - current[1][1] + 1 < 6):
                words[near] = word
    # Keep an independent label-row view even when line-peak geometry found
    # several candidates.  Curve segments can masquerade as X tick strokes on
    # charts without vertical grid lines; likewise long comma-formatted Y labels
    # may fail the merged-word path while their own row masks remain clean.
    if (((axis == 'x' and scale in (AxisScale.LINEAR, AxisScale.DATETIME)) or
            (axis == 'y' and scale in (AxisScale.LINEAR, AxisScale.LOG10)))
            and not label_words):
        label_positions, label_words = _label_driven_words(
            image, rect, axis, positions)

    if axis == 'y' and len(label_positions) >= 3:
        # Some scientific/publication charts draw neither horizontal grid lines
        # nor visible short Y tick marks.  In that layout the repeated numeric
        # label column is the only geometry source.  Its vertical centres are
        # still direct observations, and _y_label_masks already rejects the
        # distant rotated axis title by right-edge alignment. Prefer that
        # coherent label geometry only for near-horizontal labels; strongly
        # rotated labels need the full merged-word deskew pipeline below.
        label_angle = _label_deskew_angle(list(label_words.values()))
        if abs(label_angle) <= 12:
            textlike_words = sum(1 for _mask, bbox in words.values()
                                 if bbox[3] - bbox[1] + 1 >= 5
                                 and bbox[2] - bbox[0] + 1 >= 2)
            physical_heights = [bbox[3] - bbox[1] + 1 for _mask, bbox in words.values()
                                if bbox[3] >= bbox[1]]
            label_heights = [bbox[3] - bbox[1] + 1 for _mask, bbox in label_words.values()
                             if bbox[3] >= bbox[1]]
            contaminated_words = (physical_heights and label_heights and
                                  statistics.median(physical_heights) >=
                                  statistics.median(label_heights) * 1.55)
            if (len(positions) < 3 or textlike_words < 3
                    or len(label_positions) >= textlike_words + 2
                    or contaminated_words):
                positions, words = list(label_positions), label_words
            else:
                # Dilation can leave a detached leading '1' outside the merged
                # physical word. Prefer the complete aligned label when it
                # contains that word, without replacing taller/rotated text.
                for position, word in label_words.items():
                    if position not in words:
                        if position in positions:
                            words[position] = word
                        continue
                    _, full = word
                    _, current = words[position]
                    if (full[0] < current[0] and full[2] >= current[2]
                            and abs(full[1] - current[1]) <= 2
                            and abs(full[3] - current[3]) <= 2):
                        words[position] = word

    if label_words:
        # Rotated ISO-date rows are a semantic case that generic numeric OCR
        # handles very expensively: every label otherwise goes through
        # rotate/font/scientific fallbacks before the DateTime model is tried
        # near the end of this function.  When the whole X label row has a
        # clear shared slant, verify the strict ISO sequence first.  The
        # sequence detector still checks each label raster and returns only a
        # ready DateTime axis, so this is an ordering optimization rather than
        # a heuristic relabeling shortcut.
        if axis == 'x' and len(label_positions) >= 4:
            label_angle = _label_deskew_angle(list(label_words.values()))
            if abs(label_angle) >= 8:
                date_sequence = _iso_datetime_sequence_detection(label_words, label_positions, image)
                if date_sequence is not None and date_sequence.ready:
                    return date_sequence

        from ..axis_labels import independent_formatted_axis
        formatted = independent_formatted_axis(image, rect, axis, scale, words, label_words, cancelled)
        if formatted is not None:
            # Formatted LOG10 recovery may read a coherent comma-separated
            # column while rejecting one clipped endpoint.  Before returning,
            # compare it with the independent decade-template model, which can
            # safely restore that endpoint only when the complete power-of-ten
            # sequence is supported by the actual label rasters.
            if axis == 'y' and formatted.scale == AxisScale.LOG10 and len(label_positions) >= 5:
                formatted_measured = sum(t.bbox != (0, 0, 0, 0) for t in formatted.ticks)
                # A fully measured formatted column already contains direct
                # raster evidence for every major tick. Re-rendering an entire
                # power-of-ten template family cannot add information; reserve
                # that expensive verifier for clipped/ambiguous endpoints.
                if (formatted_measured >= len(label_positions)
                        and formatted.confidence >= .68):
                    return formatted
                decade = _log_decade_template_detection(axis, label_words, label_positions)
                if decade is not None and decade.ready:
                    decade_measured = sum(t.bbox != (0, 0, 0, 0) for t in decade.ticks)
                    if (decade_measured > formatted_measured or
                            (decade_measured == formatted_measured and
                             decade.confidence >= formatted.confidence - .04)):
                        return decade
            return formatted

    if not words:
        # Before falling back to generic slot probing, try the semantic axis
        # models on the label row itself.  This lets year/date X axes and
        # comma-formatted decade Y axes succeed without any usable line peaks.
        if axis == 'x' and len(label_positions) >= 4:
            date_sequence = _iso_datetime_sequence_detection(label_words, label_positions, image)
            if date_sequence is not None and date_sequence.ready:
                return date_sequence
            year = _year_sequence_detection(label_words, label_positions)
            if year is not None and year.ready:
                return year
        if axis == 'y' and len(label_positions) >= 5:
            decade = _log_decade_template_detection(axis, label_words, label_positions)
            if decade is not None and decade.ready:
                return decade
        fallback = _slot_probe_axis(image, rect, axis, scale, positions, cancelled=cancelled)
        if fallback is not None:
            return fallback
        return AxisTickDetection(axis, (), 0.0, scale, tuple(positions), tuple(positions))

    # Common Y charts have a regular 5-12 slot lattice and a zero endpoint, but
    # tiny/compressed labels can make every per-word OCR pass expensive before
    # eventually falling back to the same whole-axis sequence model.  Probe
    # only three representative words first.  If none provides usable glyph
    # evidence, run the already strict image-verified zero-sequence rescue now.
    # A non-zero/log axis is unaffected unless its complete raster sequence
    # genuinely matches a zero-anchored linear model with the required margin.
    if (axis == 'y' and scale == AxisScale.LINEAR and 5 <= len(positions) <= 12 and len(words) >= 3
            and abs(_label_deskew_angle(list(words.values()))) <= 4):
        ordered_probe = sorted(words)
        probe_indices = sorted({int(round((len(ordered_probe) - 1) * fraction))
                                for fraction in (.20, .50, .80)})
        probe_readings = []
        for index in probe_indices:
            reading = _read_probe_word(words[ordered_probe[index]][0])
            if reading is not None and reading[2] >= .55:
                probe_readings.append(reading)
        if not probe_readings:
            # Binary glyph failure is not a complete OCR miss: compressed
            # serif text can still be read from its own grayscale raster.
            # Let that evidence run before an axis-wide sequence can mistake
            # stretched 1500 for 15000 (or 2000 for 4000).
            for index in probe_indices:
                mask, bbox = words[ordered_probe[index]]
                if len(mask) <= 10 and len(mask[0]) / max(1, len(mask)) >= 3:
                    reading = _read_small_source_word(image, bbox, mask)
                    if reading is not None and reading[2] >= .62:
                        probe_readings.append(reading)
                        break
        if not probe_readings:
            quick_sequence = _zero_anchored_template_detection(
                image, rect, axis, scale, positions, fast_only=True)
            if quick_sequence is not None and quick_sequence.ready:
                return _complete_lattice_ticks(quick_sequence, positions, rect)

    # Colored Smart Region/selection guides can pass straight through a printed
    # label. Do not let that synthetic stroke steer global deskew, and do not
    # claim its damaged raster as a measured OCR value. The physical slot stays
    # available for conservative linear completion later.
    occluded_positions = {
        position for position, (_, bbox) in words.items()
        if _colored_guide_occlusion_score(image, axis, position, bbox) >= .34
    }
    angle_words = [word for position, word in words.items() if position not in occluded_positions]
    angle = estimated_angle = _label_deskew_angle(angle_words or list(words.values()))
    if abs(angle) <= 4:
        angle = estimated_angle = 0
    slight = ()
    if angle == 0 and estimated_angle and statistics.median(len(mask) for mask, _ in words.values()) >= 10:
        # Near-horizontal projection is biased by tall digits. Keep the cheap
        # 0-degree pass first, but try the measured small angle before upside down.
        slight = (estimated_angle, estimated_angle + (3 if estimated_angle > 0 else -3))
    # Keep 180-degree support, but the relaxed successful-pass break below
    # prevents normal horizontal charts from paying for it once enough labels
    # are already read. This preserves upside-down charts without restoring the
    # previous worst-case cost on ordinary tiny labels.
    orientations = ((angle,) if fast_retry else
                    tuple(dict.fromkeys((angle, *slight, angle + 180, 0, 180))))
    # Escalate ordinary template matching on representative words. Compressed
    # words below get their own local grayscale verification, including endpoints;
    # sampling only the middle word silently dropped unread endpoint labels.
    ordered_positions = sorted(words)
    if len(ordered_positions) <= 3:
        heavy_positions = set(ordered_positions)
    else:
        sample_indices = {round((len(ordered_positions) - 1) * fraction)
                          for fraction in (.20, .50, .80)}
        heavy_positions = {ordered_positions[index] for index in sample_indices}
    results = []
    for pass_index, orientation in enumerate(orientations):
        _check_tick_cancelled(cancelled)
        ticks, unread = [], [p for p in positions if p not in words]
        font_hint = None
        for word_index, (position, (mask, bbox)) in enumerate(sorted(words.items())):
            _check_tick_cancelled(cancelled)
            if position in occluded_positions:
                # Do not let a damaged label steer the axis model.  It may be
                # recovered later, after clean ticks establish the transform.
                if position not in unread:
                    unread.append(position)
                continue
            if progress is not None:
                # Reserve room for local orientation retries; no time estimate
                # or numeric tick values are used to manufacture progress.
                start = 1.0 - .2 ** pass_index
                progress(start + (1.0 - start) * .8 * word_index / len(words),
                         '{} labels: {}/{} (pass {})'.format(axis.upper(), word_index, len(words), pass_index + 1))
            choices = []
            primary_reading = None
            scientific_primary = None
            if orientation % 360:
                # A 180-degree retry can process every word cheaply because
                # it is a lossless binary flip. True oblique/vertical labels
                # still use source-gray rotation and its stricter verification.
                if orientation % 360 == 180:
                    # 180 degrees is a lossless flip: rotating the already
                    # segmented binary word avoids the expensive grayscale
                    # source/template renderer while preserving punctuation.
                    rotated = _rotate_mask(mask, 180)
                    reading = _read_fast_independent_word(rotated)
                else:
                    reading = _read_rotated_source_word(image, bbox, orientation)
                if reading is not None:
                    choices.append(reading)
            else:
                # First use glyph-only evidence: no whole-word font rendering.
                # Only representative labels are escalated to the exact fast
                # template reader if the probe is missing/weak.
                scientific_primary = (_read_scientific_glyph_word(mask)
                                      if mask and len(mask[0]) / max(1.0, len(mask)) >= 1.75
                                      else None)
                if scientific_primary is not None and scientific_primary[2] >= .58:
                    reading = primary_reading = scientific_primary
                else:
                    # The glyph/segmentation probe is usually enough for clean
                    # 10-20 px chart labels and avoids whole-word multi-font
                    # rendering on every tick. Escalate only ambiguous probes;
                    # the exact reader remains the authority for hard glyphs.
                    probe = _read_probe_word(mask)
                    reading = primary_reading = probe
                    if (not fast_retry and len(mask) >= 12
                            and (probe is None or probe[2] < .78)):
                        exact = _read_independent_word(mask)
                        if exact is not None:
                            reading = primary_reading = exact
                if reading is not None:
                    choices.append(reading)
                if (not fast_retry and position in heavy_positions and len(mask) < 12
                        and (not choices or choices[0][2] < .62)):
                    exact = _read_fast_independent_word(mask)
                    if exact is not None:
                        choices.append(exact)
            if orientation % 360 == 0 and (not choices or choices[0][2] < .6):
                # Most difficult production screenshots have perfectly
                # horizontal labels but only 6-10 source pixels of glyph
                # height. Upscale that one source word first: it is far cheaper
                # than the multi-font phase raster fallback and often recovers
                # a missing decimal/digit directly.
                if len(mask) <= 11:
                    enlarged = _read_upscaled_source_word(image, bbox)
                    if enlarged is not None and enlarged[2] >= .58:
                        choices.append(enlarged)
                # Screenshot/downscale blur can erase a decimal point or turn
                # a 6-8 px glyph into another digit.  If the native probe failed,
                # always allow the bounded grayscale retry.  A weak tiny probe
                # may also be challenged, but only when the grayscale reading is
                # materially more confident, so clean labels keep the fast path.
                if not fast_retry and (not choices or
                        (len(mask) <= 8 and max(choice[2] for choice in choices) < .72)):
                    blurred = _read_blurred_source_word(image, bbox)
                    if blurred is not None:
                        current = max((choice[2] for choice in choices), default=0.0)
                        if not choices or blurred[2] >= current + .075:
                            choices.append(blurred)
                # A clear enlarged reading is already based on the grayscale
                # source; do not immediately re-run four threshold variants.
                if not choices or max(choice[2] for choice in choices) < .64:
                    seen_masks = {(len(mask), len(mask[0]) if mask else 0,
                                   b"".join(mask))}
                    for contrast in _word_contrast_masks(image, mask, bbox):
                        _check_tick_cancelled(cancelled)
                        signature = (len(contrast), len(contrast[0]) if contrast else 0,
                                     b"".join(contrast))
                        if signature in seen_masks:
                            continue
                        seen_masks.add(signature)
                        oriented = _rotate_mask(contrast, orientation) if orientation % 360 else contrast
                        reading = _read_probe_word(oriented)
                        if (reading is None and not fast_retry and position in heavy_positions):
                            reading = (_read_fast_independent_word(oriented)
                                       if len(oriented) <= 15 else _read_independent_word(oriented))
                        if reading is not None:
                            choices.append(reading)
                # Keep every independent image hypothesis until the end of the
                # word.  A consensus of several moderate threshold/source
                # readings is more reliable than one over-confident mask.
                provisional = _consensus_numeric_reading(choices)
            else:
                provisional = _consensus_numeric_reading(choices)
            # A faint decimal can disappear in grayscale downsampling. Once a
            # contrast mask reads that point clearly, don't erase it by choosing
            # a visually similar integer (e.g. printed 2.4 must not become 24).
            clear_decimal = provisional is not None and '.' in provisional[0] and provisional[2] >= .6
            source_reading = None
            if (not fast_retry and orientation % 360 == 0
                    and len(mask) <= 10 and (provisional is None or
                    (len(mask) <= 8 and (provisional[2] < .85 or primary_reading is None)))
                    and (not clear_decimal or 'e' in provisional[0].lower())):
                _check_tick_cancelled(cancelled)
                reading = _read_small_source_word(image, bbox, mask, font_hint=font_hint, with_profile=True)
                if reading is not None:
                    source_reading = reading[:3]
                    choices.append(reading[:3])
                    # Reuse only visual font appearance, never another tick's
                    # value/step. Short zero glyphs are too ambiguous for this.
                    if len(mask) >= 7 and reading[3] is not None and reading[2] >= .75 and sum(c.isdigit() for c in reading[0]) >= 3:
                        font_hint = reading[3]
            # Threshold variants are correlated, not independent votes. A
            # verified grayscale/raster fit must not be outvoted by several
            # copies of the same compression artefact (printed 500 -> 600).
            selected = source_reading or _consensus_numeric_reading(choices)
            year_like = False
            if axis == 'x' and orientation % 360 == 0:
                raw_candidates = _independent_word_candidates(mask)
                if raw_candidates:
                    best_error = min(item[2] for item in raw_candidates)
                    year_like = any(text.isdigit() and len(text) == 4 and 1500 <= value <= 2500
                                    and error <= best_error + .085
                                    for text, value, error in raw_candidates)
            scientific_possible = (scientific_primary is not None or
                                   (selected is None and mask and
                                    len(mask[0]) / max(1.0, len(mask)) >= 1.75))
            if (orientation % 360 == 0
                    and scientific_possible
                    and (selected is None or selected[2] < .78)
                    and not year_like
                    and not (selected is not None and ('e' in selected[0].lower()))):
                scientific = _read_scientific_word(mask, selected)
                if _scientific_reading_beats(mask, scientific, selected):
                    selected = scientific
            if selected is None:
                unread.append(position)
                continue
            text, value, confidence = selected
            ticks.append(TickReading(position, value, text, confidence, bbox))
        _check_tick_cancelled(cancelled)
        confidence = statistics.median(t.confidence for t in ticks) if ticks else 0.0
        actual_scale = _observed_axis_scale(ticks, scale)
        detected = AxisTickDetection(axis, tuple(ticks), confidence, actual_scale, tuple(unread), tuple(positions))
        if orientation % 360 == 180 and len(detected.ticks) >= 4:
            # Binary 180-degree OCR is fast but a single 6/8 ambiguity can
            # survive.  Let the existing linear-context verifier choose only
            # among candidates produced by that same rotated raster.
            rotated_words = {position: (_rotate_mask(mask, 180), bbox)
                             for position, (mask, bbox) in words.items()}
            detected = _repair_ambiguous_linear_readings(detected, rotated_words, positions)
        results.append(detected)
        # A common engineering-chart failure mode is a perfectly regular Y
        # lattice whose tiny/blurred labels produce *no* usable glyph reading
        # in the normal horizontal pass.  Continuing through 180/deskew/font
        # retries is expensive and still contributes no evidence.  In that
        # exact complete-miss case, try the already image-verified bounded
        # zero-origin sequence immediately.  Clear non-zero axes are safe: they
        # produce real readings in this first pass and never enter this shortcut.
        if (pass_index == 0 and axis == 'y' and scale == AxisScale.LINEAR
                and not detected.ticks and 5 <= len(positions) <= 12):
            quick_sequence = _zero_anchored_template_detection(
                image, rect, axis, scale, positions, fast_only=True)
            if quick_sequence is not None and quick_sequence.ready:
                return _complete_lattice_ticks(quick_sequence, positions, rect)
        if detected.ready and len(ticks) >= max(3, math.ceil(len(words) * .55)):
            # Do not re-read a mostly legible axis upside down just because one
            # or several words are clipped/occluded. Geometry-supported missing
            # slots are completed below after validating the observed linear fit.
            break
    if progress is not None:
        progress(1.0, '{} labels checked'.format(axis.upper()))
    best = max(results, key=lambda result: (result.ready, len(result.ticks), result.confidence))
    best = _repair_ambiguous_linear_readings(best, words, positions)
    best = _infer_template_supported_linear_outliers(best, words, positions)
    best = _infer_template_supported_log_outliers(best, words, positions)
    # If a colored guide crossed one label and caused a confident-but-wrong OCR
    # read, context may demote only that occluded outlier to an inferred value.
    best = _infer_occluded_linear_outliers(best, image, positions)
    # A fully/partly hidden label gets one more chance only *after* clean ticks
    # have defined the axis transform.  This prevents damaged text from steering
    # the model while still recovering a real measured control point when its
    # remaining pixels agree with the established sequence.
    best = _recover_occluded_axis_readings(best, image, words, positions, occluded_positions)
    # If at least three independently read values already define a reliable
    # linear axis, restore only the *observed grid/tick positions* that were
    # unread (for example labels partly hidden by a marker). Synthesized values
    # retain empty bboxes and low confidence, so they are never claimed as OCR.
    if _axis_completion_supported(best, positions):
        best = _complete_lattice_ticks(best, positions, rect)
    measured = sum(tick.bbox != (0, 0, 0, 0) for tick in best.ticks)
    # Semantic axis-type candidates are allowed to replace a *ready but partial*
    # generic numeric OCR result.  This is essential for plots where curve
    # segments look like X ticks: four junk numeric reads must not block an
    # eight-label year row from being recognized as Date/Time.
    if axis == 'x':
        date_sequence = None
        if len(label_positions) >= 4:
            date_sequence = _iso_datetime_sequence_detection(label_words, label_positions, image)
        if date_sequence is None and not best.ready and len(words) >= 4:
            date_sequence = _iso_datetime_sequence_detection(words, positions, image)
        if date_sequence is not None and date_sequence.ready:
            date_measured = sum(tick.bbox != (0, 0, 0, 0) for tick in date_sequence.ticks)
            best_measured = sum(tick.bbox != (0, 0, 0, 0) for tick in best.ticks)
            if date_measured >= 4 and (best.scale != AxisScale.DATETIME or
                    date_measured >= max(4, best_measured)):
                best = date_sequence
                measured = date_measured
        year = None
        if len(label_positions) >= 4:
            year = _year_sequence_detection(label_words, label_positions)
        if year is None and not best.ready and len(words) >= 4:
            year = _year_sequence_detection(words, positions)
        if year is not None and year.ready:
            year_measured = sum(tick.bbox != (0, 0, 0, 0) for tick in year.ticks)
            best_measured = sum(tick.bbox != (0, 0, 0, 0) for tick in best.ticks)
            # A verified year row carries stronger semantic evidence than a
            # generic partial numeric fit. Prefer it whenever it has at least
            # four measured labels and does not materially reduce coverage.
            if year_measured >= 4 and (best.scale != AxisScale.DATETIME or
                    year_measured >= max(4, best_measured)):
                best = year
                measured = year_measured
        if not best.ready and len(words) >= 4:
            sequence = _candidate_supported_linear_sequence(words, positions)
            if sequence is not None and sequence.ready:
                best = sequence
                measured = sum(tick.bbox != (0, 0, 0, 0) for tick in best.ticks)

    # Y decade recognition gets an independent label-driven attempt even if a
    # few generic OCR values happened to form a monotonic linear sequence.
    # Comma-formatted labels such as 1,000,000,000 are much more reliable as a
    # complete power-of-ten column than as isolated decimal-looking words.
    decade = None
    # A ready linear axis is already strong evidence.  Only challenge it with a
    # long decade column (six or more independently observed label slots); five
    # ordinary linear labels such as 0/500/.../2000 are too easy to mimic with
    # powers of ten at tiny raster sizes.  If the generic axis is not ready, a
    # five-label decade candidate is still a useful rescue path.
    minimum_decade_labels = 6 if best.ready and best.scale != AxisScale.LOG10 else 5
    # A logarithmic axis cannot contain zero or a negative measured tick. Once
    # a ready linear Y axis has direct non-positive raster evidence, running the
    # expensive decade-template challenger is both redundant and incapable of
    # producing a valid replacement. This is especially common on DateTime X +
    # large linear Y charts.
    measured_nonpositive = (best.ready and best.scale == AxisScale.LINEAR and
                            any(tick.bbox != (0, 0, 0, 0) and tick.value <= 0
                                for tick in best.ticks))
    if (axis == 'y' and not measured_nonpositive
            and len(label_positions) >= minimum_decade_labels):
        decade = _log_decade_template_detection(axis, label_words, label_positions)
    if (axis == 'y' and decade is None and not best.ready
            and len(positions) >= 5 and len(words) >= 4):
        decade = _log_decade_template_detection(axis, words, positions)
    if decade is not None and decade.ready:
        decade_measured = sum(tick.bbox != (0, 0, 0, 0) for tick in decade.ticks)
        best_measured = sum(tick.bbox != (0, 0, 0, 0) for tick in best.ticks)
        if (not best.ready or best.scale == AxisScale.LOG10 or
                (len(label_positions) >= 6 and decade_measured >= max(5, best_measured + 1))):
            best = decade
            measured = decade_measured
    if (not best.ready and axis == 'y' and scale == AxisScale.LINEAR
            and 5 <= len(positions) <= 12):
        sequence = _zero_anchored_template_detection(
            image, rect, axis, scale, positions, fast_only=True)
        if sequence is not None and sequence.ready:
            best = _complete_lattice_ticks(sequence, positions, rect)
            measured = sum(tick.bbox != (0, 0, 0, 0) for tick in best.ticks)
    if not best.ready or measured < 2:
        fallback = _slot_probe_axis(image, rect, axis, scale, positions, cancelled=cancelled)
        if fallback is not None:
            fallback_measured = sum(tick.bbox != (0, 0, 0, 0) for tick in fallback.ticks)
            if (not best.ready or fallback_measured > measured or
                    (fallback_measured == measured and fallback.confidence > best.confidence)):
                best = fallback
    return best


def _retry_small_y_labels(image, rect, scale, *, cancelled=None, progress=None):
    """Second-chance OCR for tiny source labels; runs ONLY after Y fails.

    Scale a narrow Y-label/plot strip rather than the full image.  The native
    detector stays the fast path; all returned coordinates map to source pixels.
    Values are read independently; this retry does not infer missing labels.
    """
    _check_tick_cancelled(cancelled)
    if scale == AxisScale.DATETIME:
        return None
    left, top, right, bottom = map(int, rect)
    if left < 8 or bottom - top < 45:
        return None
    margin = min(left, max(45, min(140, int((right - left) * .23))))
    x0 = max(0, left - margin)
    # Y retry needs enough plot width to confirm horizontal grid/tick strokes,
    # not one third of an arbitrarily large engineering image. Cap the plot
    # probe so bicubic enlargement stays bounded on 2K/4K screenshots.
    plot_probe = min(220, max(100, (right - left) // 3))
    x1 = min(image.width, left + plot_probe)
    y0 = max(0, top - 20)
    y1 = min(image.height, bottom + 21)
    if x1 - x0 < 30 or y1 - y0 < 45:
        return None
    # Keep this retry bounded, including on very large engineering images.
    if (x1 - x0) * (y1 - y0) > 1_200_000:
        return None
    scale_factor = 2
    crop = image.crop((x0, y0, x1, y1))
    scaled = crop.resize((crop.width * scale_factor,
                          crop.height * scale_factor), Image.Resampling.BICUBIC)
    local_rect = tuple(int(round(v * scale_factor)) for v in
                       (left - x0, top - y0, min(right, x1 - 2) - x0, bottom - y0))
    if local_rect[2] <= local_rect[0] + 25:
        return None
    options = {'cancelled': cancelled} if cancelled is not None else {}
    if progress is not None:
        options['progress'] = progress
    # The image is already enlarged here; use the bounded retry path rather
    # than recursively paying the full multi-orientation/small-font pipeline.
    options['fast_retry'] = True
    result = _detect_axis(scaled, local_rect, 'y', scale, **options)
    if not result.ready:
        return None
    ticks = tuple(TickReading(t.position / scale_factor + y0,
                              t.value, t.text, t.confidence,
                              (int(t.bbox[0] / scale_factor) + x0,
                               int(t.bbox[1] / scale_factor) + y0,
                               int(t.bbox[2] / scale_factor) + x0,
                               int(t.bbox[3] / scale_factor) + y0)
                              if t.bbox != (0, 0, 0, 0) else t.bbox)
                  for t in result.ticks)
    return AxisTickDetection('y', ticks, result.confidence, result.scale,
                             tuple(p / scale_factor + y0 for p in result.unread_positions),
                             tuple(p / scale_factor + y0 for p in result.mark_positions))


def _small_y_retry_is_worthwhile(detection):
    """Retry only when the failed Y reading actually looks resolution-limited.

    The old rule retried every non-ready Y axis.  A cluttered/occluded axis can
    have perfectly normal 9-16 px labels yet fail semantic validation; enlarging
    and re-running the entire OCR pipeline then adds seconds without recovering
    information.  Keep enlargement for genuinely tiny measured glyphs or for a
    complete miss where no word survived the first pass.
    """
    if detection.ready:
        return False
    # A complete miss still gets one bounded enlarged retry. This also keeps
    # the cancellation/progress contract used by background calibration.
    if not detection.ticks:
        return True
    if len(detection.mark_positions) < 3:
        return False
    heights = [tick.bbox[3] - tick.bbox[1] + 1 for tick in detection.ticks
               if tick.bbox != (0, 0, 0, 0)]
    if not heights:
        return not detection.ticks
    return statistics.median(heights) <= 8


def _retry_small_x_labels(image, rect, scale, *, cancelled=None, progress=None):
    """Second-chance OCR for tiny X labels on document/publication charts.

    Crop a shallow strip covering the lower part of the plot and the label row,
    enlarge it, then re-run the normal X detector.  This is bounded and only
    used when the original pass looks resolution-limited.
    """
    _check_tick_cancelled(cancelled)
    if scale == AxisScale.LOG10:
        return None
    left, top, right, bottom = map(int, rect)
    if right - left < 45 or bottom < 8:
        return None
    width = right - left
    height = bottom - top
    x_pad = min(24, max(8, width // 30))
    plot_probe = min(180, max(65, height // 3))
    label_margin = min(max(0, image.height - 1 - bottom), max(48, min(110, int(height * .30))))
    x0 = max(0, left - x_pad)
    x1 = min(image.width, right + x_pad + 1)
    y0 = max(0, bottom - plot_probe)
    y1 = min(image.height, bottom + label_margin + 1)
    if x1 - x0 < 45 or y1 - y0 < 35:
        return None
    if (x1 - x0) * (y1 - y0) > 1_400_000:
        return None
    scale_factor = 3 if height <= 230 else 2
    crop = image.crop((x0, y0, x1, y1))
    scaled = crop.resize((crop.width * scale_factor,
                          crop.height * scale_factor), Image.Resampling.BICUBIC)
    local_rect = tuple(int(round(v * scale_factor)) for v in
                       (left - x0, top - y0, right - x0, min(bottom, y1 - 2) - y0))
    if local_rect[2] <= local_rect[0] + 25 or local_rect[3] <= local_rect[1] + 18:
        return None
    options = {'cancelled': cancelled} if cancelled is not None else {}
    if progress is not None:
        options['progress'] = progress
    result = _detect_axis(scaled, local_rect, 'x', scale, **options)
    if not result.ticks:
        return None
    ticks = tuple(TickReading(t.position / scale_factor + x0,
                              t.value, t.text, t.confidence,
                              (int(t.bbox[0] / scale_factor) + x0,
                               int(t.bbox[1] / scale_factor) + y0,
                               int(t.bbox[2] / scale_factor) + x0,
                               int(t.bbox[3] / scale_factor) + y0)
                              if t.bbox != (0, 0, 0, 0) else t.bbox)
                  for t in result.ticks)
    return AxisTickDetection('x', ticks, result.confidence, result.scale,
                             tuple(p / scale_factor + x0 for p in result.unread_positions),
                             tuple(p / scale_factor + x0 for p in result.mark_positions))


def _small_x_retry_is_worthwhile(detection):
    """Retry X only for tiny/partial label rows where enlargement can help."""
    if detection.ready:
        return False
    if len(detection.mark_positions) < 4:
        return False
    if not detection.ticks:
        return True
    heights = [tick.bbox[3] - tick.bbox[1] + 1 for tick in detection.ticks
               if tick.bbox != (0, 0, 0, 0)]
    if not heights:
        return True
    measured = sum(tick.bbox != (0, 0, 0, 0) for tick in detection.ticks)
    return statistics.median(heights) <= 10 or measured <= 2


def detect_calibration_ticks(image: Image.Image, rect, scale_x=AxisScale.LINEAR,
                             scale_y=AxisScale.LINEAR, *, cancelled=None, progress=None,
                             align_axes=False, region_aligned=None) -> TickCalibrationDetection:
    """Detect numeric X/Y tick labels immediately outside a user-drawn plot box.

    Each printed number is read independently. High-confidence measured ticks
    can classify Linear versus logarithmic geometry; inferred/occluded ticks are
    excluded from that scale decision. The image is never modified.
    """
    _check_tick_cancelled(cancelled)
    last_progress = 0.0
    def report(value, message):
        nonlocal last_progress
        _check_tick_cancelled(cancelled)
        if progress is not None:
            last_progress = max(last_progress, min(1.0, value))
            progress(last_progress, message)

    report(0.0, 'Aligning region to horizontal and vertical axes' if align_axes else 'Finding X tick labels')
    if image is None or rect is None:
        empty_x = AxisTickDetection("x", (), 0.0, scale_x)
        empty_y = AxisTickDetection("y", (), 0.0, scale_y)
        report(1.0, 'No image or plot area')
        return TickCalibrationDetection(empty_x, empty_y)
    options = {'cancelled': cancelled} if cancelled is not None else {}
    aligned_rect = None
    if align_axes:
        rect = aligned_rect = align_region_to_axes(image, rect, cancelled=cancelled)
        _check_tick_cancelled(cancelled)
        if region_aligned is not None:
            region_aligned(rect)
        report(.05, 'Region checked; finding X tick labels')
    x_options = dict(options)
    if progress is not None:
        x_options['progress'] = lambda value, message: report((.05 + .4 * value) if align_axes else .45 * value, message)
    x = _detect_axis(image, rect, "x", scale_x, **x_options)
    _check_tick_cancelled(cancelled)
    if _small_x_retry_is_worthwhile(x):
        report(.45, 'Retrying genuinely small X labels')
        retry_options = dict(options)
        if progress is not None:
            retry_options['progress'] = lambda value, message: report(.45 + .08 * value, message)
        retry = _retry_small_x_labels(image, rect, scale_x, **retry_options)
        if retry is not None:
            retry_measured = sum(t.bbox != (0, 0, 0, 0) for t in retry.ticks)
            current_measured = sum(t.bbox != (0, 0, 0, 0) for t in x.ticks)
            if (retry.ready or (not x.ready and retry_measured > current_measured) or
                    (retry_measured == current_measured and retry.confidence > x.confidence + .02)):
                x = retry
    report(.53, 'Finding Y tick labels')
    y_options = dict(options)
    if progress is not None:
        y_options['progress'] = lambda value, message: report(.53 + .37 * value, message)
    y = _detect_axis(image, rect, "y", scale_y, **y_options)
    _check_tick_cancelled(cancelled)
    if _small_y_retry_is_worthwhile(y):
        report(.9, 'Retrying genuinely small Y labels')
        retry_options = dict(options)
        if progress is not None:
            retry_options['progress'] = lambda value, message: report(.90 + .09 * value, message)
        retry = _retry_small_y_labels(image, rect, scale_y, **retry_options)
        if retry is not None and retry.ready:
            y = retry
    report(1.0, 'Tick detection complete')
    return TickCalibrationDetection(x, y, aligned_rect)


def estimate_axis_value_at(detection: AxisTickDetection, position: float) -> float:
    """Map a coordinate using its adjacent read ticks, without value snapping."""
    if not detection.ready:
        raise ValueError("Axis tick detection is not reliable enough.")
    ticks = sorted(detection.ticks, key=lambda tick: tick.position)

    index = next((i for i in range(len(ticks) - 1) if position <= ticks[i + 1].position), len(ticks) - 2)
    first, second = ticks[index:index + 2]
    fraction = (float(position) - first.position) / (second.position - first.position)
    a, b = (_transform_value(tick.value, detection.scale) for tick in (first, second))
    return float(_inverse_value(a + fraction * (b - a), detection.scale))
