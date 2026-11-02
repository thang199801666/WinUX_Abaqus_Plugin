from __future__ import annotations

import math
import statistics
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from PIL import Image, ImageChops, ImageFilter

from ..models import AxisScale
from .axis_math import (
    _inverse_value, _linear_fit, _median_spacing, _nice_log_step, _nice_step,
    _robust_axis_values, _transform_value,
)
from .pixels import _bbox, _crop_mask, _mask_image, _point_lut
from .recognition import (
    _axis_line_score, _consensus_numeric_reading, _independent_word_candidates,
    _label_deskew_angle, _normalize_word_mask, _normalized_quick_word_score,
    _normalized_word_template_score, _observed_axis_scale, _ocr_numeric,
    _plot_background_luminance, _read_probe_word, _rotate_mask,
    _slot_oriented_masks, _word_alignment_score, _word_template_score,
    _x_label_masks, _x_label_masks_native, _y_label_masks, _y_label_masks_native,
)
from .shared import _GUIDE_BRIGHT_LUT, _GUIDE_CHROMA_LUT
from .source_ocr import (
    _check_tick_cancelled, _normalized_gray_word, _read_deoccluded_colored_word,
    _read_upscaled_source_word, _rotated_gray_score,
)
from .types import AxisTickDetection, TickReading

def _format_tick_value(value):
    if not math.isfinite(value):
        return ""
    if abs(value) < 1e-12:
        return "0"
    rounded = round(value)
    if abs(value - rounded) <= max(1e-10, abs(value) * 1e-10):
        return str(int(rounded))
    return ("{:.8f}".format(value)).rstrip("0").rstrip(".")


@lru_cache(maxsize=2048)
def _format_tick_value_variants(value):
    """Return common printed spellings for the same numeric tick value.

    The OCR model stores/calibrates a numeric value, not a typography choice.
    Engineering plots frequently print the same value as ``0.001``, ``1e-3``
    or ``10^-3``.  Sequence/raster verification should accept those equivalent
    spellings without changing the value exposed to calibration.
    """
    value = float(value)
    base = _format_tick_value(value)
    variants = [base] if base else []
    if not math.isfinite(value) or value == 0:
        return tuple(dict.fromkeys(variants))
    absolute = abs(value)
    # Thousands separators are common on published log axes.  Include a comma
    # spelling in raster verification so 100,000 is not forced to look like
    # decimal 100.000 after punctuation segmentation.
    rounded = round(value)
    if absolute >= 1000 and abs(value - rounded) <= max(1e-10, absolute * 1e-10):
        variants.append(f"{int(rounded):,}")
    exponent = int(math.floor(math.log10(absolute)))
    # Scientific notation is useful mainly when ordinary decimal labels become
    # long.  Keep the variant set bounded so sequence verification stays cheap.
    if exponent <= -2 or exponent >= 3:
        mantissa = value / (10.0 ** exponent)
        mantissa_text = ("{:.6g}".format(mantissa)).rstrip("0").rstrip(".")
        if mantissa_text in {"", "-"}:
            mantissa_text = "1" if value > 0 else "-1"
        exp_text = str(exponent)
        sign_exp_text = ("+" + exp_text) if exponent >= 0 else exp_text
        variants.extend((
            f"{mantissa_text}e{exp_text}",
            f"{mantissa_text}E{exp_text}",
            f"{mantissa_text}e{sign_exp_text}",
            f"{mantissa_text}E{sign_exp_text}",
        ))
        # Pure powers of ten are also commonly printed as 10^n.  Keep both
        # ASCII minus and Unicode minus because copied/vector chart text varies.
        if abs(abs(mantissa) - 1.0) <= 1e-8:
            prefix = "-" if mantissa < 0 else ""
            variants.extend((f"{prefix}10^{exp_text}",
                             f"{prefix}10^{exp_text.replace('-', '−')}"))
    return tuple(dict.fromkeys(variants))


def _normalized_value_template_score(observed, value):
    return min((_normalized_word_template_score(observed, text)
                for text in _format_tick_value_variants(float(value))), default=9.0)


def _value_template_score(mask, value):
    # Keep this wrapper at the mask-level so existing verification hooks/tests
    # that instrument ``_word_template_score`` continue to observe every pixel
    # check.  The normalized helper is used where the caller already owns the
    # normalized raster and avoiding repeated work matters.
    return min((_word_template_score(mask, text)
                for text in _format_tick_value_variants(float(value))), default=9.0)


def _nice_step_candidates():
    # Search common engineering magnitudes first.  Whole-sequence matching is
    # a fallback and must stay bounded; ordering around 10^0 means the first
    # candidates already cover values such as 0.8, 500 and 2000 without
    # exhausting every extreme exponent.
    exponents = [0]
    for distance in range(1, 10):
        if -distance >= -7:
            exponents.append(-distance)
        if distance <= 9:
            exponents.append(distance)
    values = []
    for exponent in exponents:
        scale = 10.0 ** exponent
        for mantissa in (1.0, 2.0, 2.5, 4.0, 5.0, 8.0):
            values.append(mantissa * scale)
    return tuple(values)


def _zero_anchored_template_detection(image, rect, axis, scale, lattice, *, slot_masks=None, fast_only=False):
    """Recognize a regular linear axis by matching the complete tick sequence.

    Many engineering charts include a zero major tick.  When tiny raster text
    defeats per-glyph OCR, testing a small family of conventional major steps
    lets the *whole axis* vote on values.  No zero is forced unless the rendered
    sequence matches the actual label images with a clear margin.
    """
    if scale != AxisScale.LINEAR or len(lattice) < 3:
        return None
    spacing = _median_spacing(lattice)
    if spacing is None or spacing <= 0:
        return None
    # Template matching is intentionally bounded.  On a dense image a noisy
    # lattice can contain dozens of slots; scoring every slot against every
    # zero/step hypothesis used to block the UI for seconds.  Use a stable set
    # of representative slots for ranking, then materialize the winning full
    # sequence afterwards.
    if len(lattice) <= 6:
        sample_indices = list(range(len(lattice)))
    else:
        sample_indices = sorted({
            int(round(index * (len(lattice) - 1) / 5.0)) for index in range(6)
        })
    provider = slot_masks or (lambda position: _slot_oriented_masks(image, rect, axis, position, spacing))
    sampled_masks = {index: provider(lattice[index]) for index in sample_indices}
    orientations = dict.fromkeys(angle for options in sampled_masks.values() for angle, _, _ in options)
    masks_by_orientation = {angle: [] for angle in orientations}
    for index in sample_indices:
        position = lattice[index]
        by_orientation = {degrees: (_normalize_word_mask(mask), bbox)
                          for degrees, mask, bbox
                          in sampled_masks[index]}
        for degrees in masks_by_orientation:
            masks_by_orientation[degrees].append((index, by_orientation.get(degrees)))

    if len(lattice) <= 8:
        zero_slots = list(range(len(lattice)))
    else:
        zero_slots = sorted({0, len(lattice) - 1, *[
            int(round(index * (len(lattice) - 1) / 7.0)) for index in range(8)
        ]})
    # Include 500 (the common 0..2000 axis step) and 0.8 before large
    # magnitudes.  The previous [:24] excluded 500 entirely.
    step_candidates = tuple(dict.fromkeys(
        mantissa * 10.0 ** exponent
        for exponent in (0, 1, 2, 3, -1, -2, 4, -3)
        for mantissa in (1.0, 2.0, 5.0, 2.5, 8.0)
    ))

    best = None
    second_score = None
    fast_accepted = False

    # Cold-path accelerator: even poor tiny-label OCR usually preserves enough
    # magnitude information for two slots to suggest a handful of plausible
    # zero/step hypotheses. Score only those complete sequences first.  The
    # actual acceptance is still image-template based; rough OCR merely narrows
    # the search and can never directly manufacture a value.
    quick_hypotheses = set()
    for degrees in masks_by_orientation:
        rough = []
        for index in sample_indices:
            original = next(((mask, bbox) for angle, mask, bbox in sampled_masks[index]
                             if angle == degrees), None)
            if original is None:
                continue
            reading = _ocr_numeric(original[0])
            if reading is None:
                continue
            text, value, confidence = reading
            if confidence < .54 or not math.isfinite(value) or abs(value) > 1e12:
                continue
            rough.append((index, float(value), confidence))
        for first in range(len(rough)):
            for second in range(first + 1, len(rough)):
                i, a, ca = rough[first]
                j, b, cb = rough[second]
                if i == j:
                    continue
                slope = (b - a) / (j - i)
                if abs(slope) < 1e-12:
                    continue
                raw_step = abs(slope)
                step = min(step_candidates, key=lambda candidate: abs(math.log(candidate / raw_step)))
                relative = abs(step - raw_step) / raw_step
                if relative > .32:
                    continue
                direction = 1.0 if slope > 0 else -1.0
                zero = ((i - a / (direction * step)) + (j - b / (direction * step))) / 2.0
                zero_slot = int(round(zero))
                if not 0 <= zero_slot < len(lattice) or abs(zero - zero_slot) > .58:
                    continue
                quick_hypotheses.add((degrees, zero_slot, direction, step))

    if quick_hypotheses:
        ranked_quick = []
        for degrees, zero_slot, direction, step in quick_hypotheses:
            indexed_slots = masks_by_orientation.get(degrees, ())
            total = 0.0
            used = 0
            sampled_info = []
            for index, slot in indexed_slots:
                value = direction * (index - zero_slot) * step
                if slot is None:
                    sampled_info.append((index, None))
                    continue
                observed, bbox = slot
                text = _format_tick_value(value)
                score = _normalized_word_template_score(observed, text)
                total += score
                used += 1
                sampled_info.append((index, (score, text, bbox)))
            if used >= 3:
                ranked_quick.append((total / used, degrees, zero_slot, direction, step, sampled_info))
        ranked_quick.sort(key=lambda item: item[0])
        if ranked_quick:
            best = ranked_quick[0]
            second_score = ranked_quick[1][0] if len(ranked_quick) > 1 else None
            quick_margin = (second_score - best[0]) if second_score is not None else 1.0
            # A moderately compressed screenshot can score around .39. Demand
            # a clear win before bypassing the exhaustive standard-step search.
            fast_accepted = best[0] <= .405 and quick_margin >= .022

    if fast_only and not fast_accepted:
        # The normal fast path above relies on rough per-word OCR to suggest a
        # zero/step model.  Moderately blurred engineering charts can defeat
        # that rough OCR even when the *complete printed Y sequence* is still a
        # very strong visual match (for example 4000/3500/.../500/0).  Do not
        # immediately give up in that case.  Search only the two endpoint-zero
        # models first, rank them with the two-face quick template bank, and
        # fully verify just the best few candidates.  This recovers the common
        # zero-at-bottom/zero-at-left chart without restoring the expensive
        # all-zero-slot exhaustive search that fast_only is meant to avoid.
        endpoint_quick = []
        endpoint_zero_slots = tuple(dict.fromkeys((0, len(lattice) - 1)))
        endpoint_rows = []
        for degrees, indexed_slots in masks_by_orientation.items():
            readable = sum(1 for _, item in indexed_slots if item is not None)
            if readable < 3:
                continue
            endpoint_rows.append((degrees, indexed_slots, {index: {} for index, _ in indexed_slots}))

        def rank_endpoint_steps(steps):
            for degrees, indexed_slots, quick_cache in endpoint_rows:
                for zero_slot in endpoint_zero_slots:
                    for direction in (-1.0, 1.0):
                        for step in steps:
                            total = 0.0
                            used = 0
                            for index, slot in indexed_slots:
                                if slot is None:
                                    continue
                                observed, _ = slot
                                text = _format_tick_value(direction * (index - zero_slot) * step)
                                cache = quick_cache[index]
                                if text not in cache:
                                    cache[text] = _normalized_quick_word_score(observed, text)
                                total += cache[text]
                                used += 1
                            if used >= 3:
                                endpoint_quick.append((total / used, degrees, zero_slot, direction, step))

        # Most desktop engineering charts use major steps from 1 through 8000.
        # Evaluate those first.  Only inspect sub-unit / very-large magnitudes
        # when that first bank does not already have a clear visual winner.
        # This avoids cold-rendering hundreds of font rasters for irrelevant
        # magnitudes on the common 0/500/.../4000 case.
        primary_steps = step_candidates[:20]
        rank_endpoint_steps(primary_steps)
        endpoint_quick.sort(key=lambda item: item[0])
        primary_margin = ((endpoint_quick[1][0] - endpoint_quick[0][0])
                          if len(endpoint_quick) > 1 else 1.0)
        primary_clear = bool(endpoint_quick and endpoint_quick[0][0] <= .44
                             and primary_margin >= .018)
        if not primary_clear and len(step_candidates) > len(primary_steps):
            rank_endpoint_steps(step_candidates[len(primary_steps):])
            endpoint_quick.sort(key=lambda item: item[0])

        if endpoint_quick:
            quick_margin = ((endpoint_quick[1][0] - endpoint_quick[0][0])
                            if len(endpoint_quick) > 1 else 1.0)
            # Only spend full-template work when the cheap raster evidence
            # already prefers one endpoint sequence by a meaningful margin.
            if endpoint_quick[0][0] <= .44 and quick_margin >= .018:
                verified = []
                verify_budget = 4 if quick_margin < .035 else 3
                for _, degrees, zero_slot, direction, step in endpoint_quick[:verify_budget]:
                    indexed_slots = masks_by_orientation.get(degrees, ())
                    total = 0.0
                    used = 0
                    sampled_info = []
                    for index, slot in indexed_slots:
                        value = direction * (index - zero_slot) * step
                        if slot is None:
                            sampled_info.append((index, None))
                            continue
                        observed, bbox = slot
                        text = _format_tick_value(value)
                        score = _normalized_word_template_score(observed, text)
                        total += score
                        used += 1
                        sampled_info.append((index, (score, text, bbox)))
                    if used >= 3:
                        verified.append((total / used, degrees, zero_slot, direction, step, sampled_info))
                verified.sort(key=lambda item: item[0])
                if verified:
                    candidate = verified[0]
                    candidate_second = verified[1][0] if len(verified) > 1 else None
                    candidate_margin = ((candidate_second - candidate[0])
                                        if candidate_second is not None else 1.0)
                    if (candidate[0] <= .42 and candidate_margin >= .012
                            and not (candidate[0] > .39 and candidate_margin < .025)):
                        best = candidate
                        second_score = candidate_second
                        fast_accepted = True

    if fast_only and not fast_accepted:
        return None
    for degrees, indexed_slots in (() if fast_accepted else masks_by_orientation.items()):
        readable = sum(1 for _, item in indexed_slots if item is not None)
        if readable < 3:
            continue
        score_cache = {index: {} for index, _ in indexed_slots}
        for zero_slot in zero_slots:
            for direction in (-1.0, 1.0):
                for step in step_candidates:
                    total = 0.0
                    used = 0
                    sampled_info = []
                    for index, slot in indexed_slots:
                        value = direction * (index - zero_slot) * step
                        if slot is None:
                            sampled_info.append((index, None))
                            continue
                        observed, bbox = slot
                        text = _format_tick_value(value)
                        cache = score_cache[index]
                        if text not in cache:
                            cache[text] = _normalized_word_template_score(observed, text)
                        score = cache[text]
                        total += score
                        used += 1
                        sampled_info.append((index, (score, text, bbox)))
                    if used < 3:
                        continue
                    average = total / used
                    candidate = (average, degrees, zero_slot, direction, step, sampled_info)
                    if best is None or average < best[0]:
                        if best is not None:
                            second_score = best[0] if second_score is None else min(second_score, best[0])
                        best = candidate
                    elif second_score is None or average < second_score:
                        second_score = average
        # Most scientific figures use horizontal tick labels. A clearly
        # separated, high-quality horizontal sequence needs no second/third
        # pass through thousands of rotated template comparisons.
        if (degrees == 0 and best is not None and best[1] == 0
                and best[0] < .28 and second_score is not None
                and second_score - best[0] >= .045):
            break
    if best is None:
        return None
    average, degrees, zero_slot, direction, step, sampled_info = best
    margin = (second_score - average) if second_score is not None else 1.0
    # Clean source images normally score < .30.  Permit moderately compressed
    # screenshots up to ~.46 only when the winning sequence is clearly better
    # than the next conventional axis sequence.
    if average > .42 or (axis == "y" and margin < .012) or (average > .39 and margin < .025):
        return None
    if slot_masks is not None and (average > .31 or margin < .018):
        return None  # Deskew must improve actual text, not invent a new scale.
    tick_readings = []
    sequence_texts = tuple(_format_tick_value(direction * (index - zero_slot) * step)
                           for index in range(len(lattice)))
    for index, position in enumerate(lattice):
        # Sampling bounds hypothesis ranking, not the number of measured
        # points returned. Verify every slot against the winning sequence.
        options = {angle: (mask, bbox) for angle, mask, bbox in
                   provider(position)}
        if degrees not in options:
            continue
        mask, bbox = options[degrees]
        position = lattice[index]
        value = direction * (index - zero_slot) * step
        text = _format_tick_value(value)
        score = _word_template_score(mask, text)
        if score > .42:
            continue
        if slot_masks is not None:
            # Whole-sequence averages can disguise repeated/ambiguous words as
            # an invented increasing scale. Each measured word must also prefer
            # its assigned value over the other values in the winning sequence.
            local_best = min(_word_template_score(mask, alternative) for alternative in sequence_texts)
            if score > local_best + .025:
                continue
        confidence = max(.28, min(.96, 1.0 - score * 1.15))
        tick_readings.append(TickReading(float(position), float(value), text, confidence, bbox))
    if len(tick_readings) < 3:
        return None
    if slot_masks is not None and (max(t.position for t in tick_readings) - min(t.position for t in tick_readings)
                                  < .60 * (max(lattice) - min(lattice))):
        return None
    confidence = max(.42, min(.96, 1.0 - average * 1.05 + min(.10, margin)))

    # The complete sequence was globally verified above. Preserve every major
    # lattice slot even when an individual tiny/occluded label cannot pass the
    # local template threshold. Such values are explicitly inferred (empty
    # bbox, low confidence, unread position), so UI/calibration can distinguish
    # them from independently measured OCR ticks while still showing the user
    # the reconstructed 0/500/... sequence.
    measured_positions = {tick.position for tick in tick_readings}
    unread = []
    for index, position in enumerate(lattice):
        position = float(position)
        if any(abs(position - observed) <= max(2.5, spacing * .16)
               for observed in measured_positions):
            continue
        value = direction * (index - zero_slot) * step
        tick_readings.append(TickReading(position, float(value), _format_tick_value(value),
                                         min(.32, confidence * .42), (0, 0, 0, 0)))
        unread.append(position)
    return AxisTickDetection(axis, tuple(sorted(tick_readings, key=lambda tick: tick.position)),
                             confidence, scale, tuple(sorted(unread)),
                             tuple(float(position) for position in lattice))


def _sequence_image_error(image, rect, axis, detection, spacing):
    """Measure how well *actual pixels* support a proposed numeric sequence.

    An unconstrained zero-anchored sequence can otherwise beat perfectly good
    OCR on axes that do not contain zero (e.g. Y = 10,20,30,40,50).  Compare
    candidates on identical slot crops instead of comparing synthetic OCR
    confidences, which are not calibrated against word-template confidence.
    """
    errors = []
    for tick in detection.ticks[:12]:
        if not tick.text or not math.isfinite(tick.value):
            continue
        alternatives = _slot_oriented_masks(image, rect, axis, tick.position, spacing)
        if not alternatives:
            continue
        # A real rotated label is allowed, but the *same* orientation must be
        # selected for the whole axis by the caller.
        scores = [_value_template_score(mask, tick.value) for _, mask, _ in alternatives]
        if scores:
            errors.append(min(scores))
    return statistics.median(errors) if len(errors) >= 3 else float("inf")


def _refine_tick_positions(image, rect, axis, labels):
    if len(labels) < 2:
        return labels
    positions = sorted(label[0] for label in labels)
    spacing = _median_spacing(positions)
    if spacing is None:
        return labels
    radius = max(7, min(34, int(round(spacing * .23))))
    left, top, right, bottom = map(int, rect)
    low, high = ((left - 2, right + 2) if axis == "x" else (top - 2, bottom + 2))
    background = _plot_background_luminance(image, rect)
    refined = []
    for estimate, mask, bbox in labels:
        start = max(low, int(round(estimate)) - radius)
        stop = min(high, int(round(estimate)) + radius)
        candidates = [(
            _axis_line_score(image, rect, axis, position, background), position
        ) for position in range(start, stop + 1)]
        best_score, best_position = max(candidates, default=(0.0, estimate))
        # A weak score means there is no visible grid/tick line; retain the text
        # center rather than snapping to random image content.
        position = float(best_position) if best_score >= .025 else float(estimate)
        refined.append((position, mask, bbox))
    return refined

def _build_axis_detection(axis, scale, raw):
    raw = sorted(raw, key=lambda item: item[0])
    provisional = tuple(TickReading(position, value, text, confidence, bbox)
                        for position, value, confidence, text, bbox in raw)
    actual_scale = _observed_axis_scale(provisional, scale)
    fit = _robust_axis_values(raw, actual_scale)
    # Automatic scale inference is deliberately conservative. If the selected
    # log model cannot build a valid robust fit, fall back to the requested
    # model rather than losing otherwise usable OCR readings.
    if fit is None and actual_scale != scale:
        actual_scale = scale
        fit = _robust_axis_values(raw, actual_scale)
    if fit is None:
        return AxisTickDetection(axis, (), 0.0, scale)
    fitted, confidence = fit
    ticks = tuple(TickReading(position, value, text, tick_confidence, bbox)
                  for position, value, tick_confidence, text, bbox in fitted)
    return AxisTickDetection(axis, ticks, confidence, actual_scale)


def _slot_probe_axis(image, rect, axis, scale, positions, *, cancelled=None):
    """Recover a regular axis by OCRing known tick slots independently.

    The fallback is deliberately two-stage.  First every slot gets only cheap
    glyph OCR.  Bicubic source enlargement is then spent on at most five
    representative unresolved tiny labels, enough to establish a verified
    linear transform without re-reading every failed slot.  Missing values are
    still completed only after the existing strong linearity/coverage guards.
    """
    positions = sorted(float(position) for position in positions)
    if not 3 <= len(positions) <= 18:
        return None
    spacing = _median_spacing(positions)
    if spacing is None or spacing < 3:
        return None
    raw = []
    pending = []
    for position in positions:
        _check_tick_cancelled(cancelled)
        options = _slot_oriented_masks(image, rect, axis, position, spacing)
        horizontal = next(((mask, bbox) for degrees, mask, bbox in options if degrees == 0), None)
        if horizontal is None:
            continue
        mask, bbox = horizontal
        reading = _read_probe_word(mask)
        if reading is not None and reading[2] >= .44:
            text, value, confidence = reading
            raw.append((position, value, confidence, text, bbox))
        else:
            pending.append((position, mask, bbox, reading))

    # Do not upscale all unread slots. Pick a spread across the axis; endpoints
    # are included only when needed, while interior labels usually avoid corner
    # contamination from the opposite axis.
    initial = _build_axis_detection(axis, scale, raw) if len(raw) >= 3 else None
    if initial is None or not initial.ready:
        tiny = [item for item in pending if len(item[1]) <= 11]
        budget = min(5, max(0, 5 - min(2, len(raw))))
        if tiny and budget:
            if len(tiny) <= budget:
                selected = tiny
            else:
                fractions = (.18, .35, .50, .65, .82)[:budget]
                indices = []
                for fraction in fractions:
                    index = round((len(tiny) - 1) * fraction)
                    if index not in indices:
                        indices.append(index)
                # Fill any duplicate-rounded quantiles from the centre outward.
                for index in sorted(range(len(tiny)), key=lambda i: abs(i - (len(tiny) - 1) / 2)):
                    if len(indices) >= budget:
                        break
                    if index not in indices:
                        indices.append(index)
                selected = [tiny[index] for index in sorted(indices[:budget])]
            for position, mask, bbox, previous in selected:
                _check_tick_cancelled(cancelled)
                enlarged = _read_upscaled_source_word(image, bbox)
                reading = _consensus_numeric_reading(
                    [candidate for candidate in (previous, enlarged) if candidate is not None])
                if reading is None or reading[2] < .44:
                    continue
                text, value, confidence = reading
                raw.append((position, value, confidence, text, bbox))

    if len(raw) < 3:
        return None
    # A slot may have been present in both the cheap and enlarged stages only
    # when a future caller supplies a weak-but-accepted probe; keep the strongest
    # reading per physical position deterministically.
    strongest = {}
    for item in raw:
        current = strongest.get(item[0])
        if current is None or item[2] > current[2]:
            strongest[item[0]] = item
    raw = [strongest[position] for position in sorted(strongest)]
    detected = _build_axis_detection(axis, scale, raw)
    if detected is None or not detected.ready:
        return None

    unread = set(float(position) for position in positions if not any(abs(position - r[0]) <= 2.5 for r in raw))
    repaired = []
    unchanged_positions = []
    for tick in detected.ticks:
        try:
            observed = float(tick.text)
        except (TypeError, ValueError):
            observed = float('nan')
        tolerance = max(1e-8, abs(tick.value) * .001)
        unchanged = math.isfinite(observed) and abs(observed - tick.value) <= tolerance
        if unchanged:
            repaired.append(tick)
            unchanged_positions.append(tick.position)
        else:
            unread.add(float(tick.position))
            repaired.append(TickReading(tick.position, tick.value, _format_tick_value(tick.value),
                                        min(.34, tick.confidence * .55), (0, 0, 0, 0)))
    minimum_unchanged = 3 if axis == 'y' else 2
    if len(unchanged_positions) < minimum_unchanged:
        return None
    coverage = max(unchanged_positions) - min(unchanged_positions)
    minimum_coverage = max(spacing * 2.0, (positions[-1] - positions[0]) * (.48 if axis == 'y' else .28))
    if coverage < minimum_coverage:
        return None

    candidate = AxisTickDetection(axis, tuple(sorted(repaired, key=lambda tick: tick.position)),
                                  detected.confidence, detected.scale, tuple(sorted(unread)), tuple(positions))
    if not candidate.ready:
        return None
    if candidate.scale == AxisScale.LINEAR and not _linear_completion_supported(candidate, positions):
        return None
    return _complete_lattice_ticks(candidate, positions, rect)


def _verified_y_detection(image, rect, detection, spacing, *, slot_masks=None):
    """Verify a numeric axis against pixels (also used for rotated X labels).

    In particular, a lattice-consistent *invented* numeric sequence is not
    evidence that its displayed tick text actually exists in the chart.
    """
    if detection is None or not detection.ready or len(detection.ticks) < 3:
        return None
    verified = []
    errors = []
    unchanged_count = 0
    for tick in detection.ticks:
        if not math.isfinite(tick.value):
            continue
        # Repaired OCR must be independently supported by original pixels.
        # Exact glyph OCR alone rejects small but readable Y tick labels.
        masks = (slot_masks(tick.position) if slot_masks is not None else
                 _slot_oriented_masks(image, rect, detection.axis, tick.position, spacing))
        if not masks:
            continue
        error = min(_value_template_score(mask, tick.value)
                    for _, mask, _ in masks)
        try:
            observed_value = float(tick.text)
        except (ValueError, TypeError):
            continue
        tolerance = max(1e-6, abs(tick.value) * 0.001)
        unchanged = abs(observed_value - tick.value) <= tolerance
        if error > (.32 if unchanged else .24):
            continue
        verified.append(tick)
        errors.append(error)
        unchanged_count += int(unchanged)
    # Require at least three pixel-supported values, two unchanged OCR reads,
    # and coverage of most of the axis. Two adjacent labels are insufficient.
    if len(verified) < 3 or unchanged_count < 2:
        return None
    positions = [tick.position for tick in verified]
    full = [tick.position for tick in detection.ticks]
    if max(positions) - min(positions) < .65 * (max(full) - min(full)):
        return None
    if len(errors) < 3 or statistics.median(errors) > .29:
        return None
    return AxisTickDetection(detection.axis, tuple(verified),
                             detection.confidence, detection.scale)


def _complete_lattice_ticks(detection, lattice, rect):
    """Fill grid-supported major tick slots after a validated calibration.

    Synthesized labels are always marked as inferred (empty bbox).  Linear
    axes interpolate in value-space; logarithmic axes interpolate in log-space.
    No completion is attempted for Date/Time or an unreliable model.
    """
    if (detection is None or not detection.ready or len(detection.ticks) < 3 or
            len(lattice) < 3 or detection.scale == AxisScale.DATETIME):
        return detection
    observed = sorted(detection.ticks, key=lambda t: t.position)
    spacing = _median_spacing(lattice)
    if not spacing or spacing < 3:
        return detection
    transformed = []
    for tick in observed:
        try:
            transformed.append((tick.position, _transform_value(tick.value, detection.scale)))
        except ValueError:
            return detection
    fit = _linear_fit(transformed)
    if fit is None:
        return detection
    slope, intercept = fit
    if abs(slope) < 1e-12:
        return detection
    transformed_step = abs(slope * spacing)
    if transformed_step < 1e-12:
        return detection
    residuals = [abs(slope * position + intercept - value)
                 for position, value in transformed]
    if max(residuals, default=float('inf')) > max(transformed_step * .095, 1e-8):
        return detection
    extrema = (observed[0].position - spacing * .2,
               observed[-1].position + spacing * .2)
    completed = list(observed)
    for pixel in sorted(lattice):
        pixel = float(pixel)
        if pixel < extrema[0] - spacing or pixel > extrema[1] + spacing:
            continue
        if any(abs(t.position - pixel) <= max(2.5, spacing * .16)
               for t in observed):
            continue
        transformed_value = slope * pixel + intercept
        if detection.scale == AxisScale.LINEAR:
            value = transformed_value
            # Preserve exact major linear tick numbers where the fitted step is
            # already very close to a conventional engineering increment.
            reference = max(observed, key=lambda t: t.confidence)
            major_step = _nice_step(slope * spacing)
            if abs(major_step) > 1e-12:
                snapped = reference.value + round((value - reference.value) / major_step) * major_step
                if abs(snapped - value) <= abs(major_step) * .08:
                    value = snapped
        else:
            # When the fitted spacing is already very close to a conventional
            # log major step, anchor the inference to one real measured tick.
            # This turns pixel-fit drift such as 10.0435 back into the printed
            # decade value 10 without inventing a base for unusual log grids.
            log_step = _nice_log_step(slope * spacing)
            reference = max(observed, key=lambda t: t.confidence)
            if abs(log_step - slope * spacing) <= max(abs(log_step), 1e-12) * .055:
                slot_delta = int(round((pixel - reference.position) / spacing))
                transformed_value = (_transform_value(reference.value, detection.scale)
                                     + slot_delta * log_step)
            value = _inverse_value(transformed_value, detection.scale)
        if not math.isfinite(value) or (detection.scale in (AxisScale.LOG10, AxisScale.LN) and value <= 0):
            continue
        completed.append(TickReading(pixel, float(value), _format_tick_value(value),
                                     min(.35, detection.confidence * .45), (0, 0, 0, 0)))
    return AxisTickDetection(detection.axis,
                             tuple(sorted(completed, key=lambda t: t.position)),
                             detection.confidence, detection.scale,
                             detection.unread_positions,
                             detection.mark_positions or tuple(float(p) for p in lattice))

def _fast_label_axis(image, rect, axis, scale, lattice):
    """Try actual printed labels before expensive lattice/template hypotheses.

    A rotated Y-axis title can produce fake numeric glyphs; the robust fit
    must be independently supported by at least three unchanged OCR texts.
    """
    labels = _x_label_masks(image, rect) if axis == 'x' else _y_label_masks(image, rect)
    if len(labels) < 3:
        return None
    labels = _refine_tick_positions(image, rect, axis, labels)
    raw = []
    for position, mask, bbox in labels:
        reading = _ocr_numeric(mask)
        if reading is not None:
            text, value, confidence = reading
            if confidence >= .30:
                raw.append((position, value, confidence, text, bbox))
    if len(raw) < 3:
        return None
    detected = _build_axis_detection(axis, scale, raw)
    if detected is None or not detected.ready:
        return None
    if axis == 'y' and scale == AxisScale.LINEAR:
        spacing = _median_spacing(lattice) or _median_spacing([r[0] for r in raw]) or 1.0
        detected = _verified_y_detection(image, rect, detected, spacing)
    if detected is None or not detected.ready:
        return None
    return _complete_lattice_ticks(detected, lattice, rect)


def _detect_axis_native(image, rect, axis, scale, lattice):
    # Prefer bounded real-text OCR. It avoids repeated whole-sequence template
    # comparisons, particularly on engineering charts with a readable Y column.
    if axis == 'y' and scale == AxisScale.LINEAR:
        quick = _fast_label_axis(image, rect, axis, scale, lattice)
        if quick is not None:
            return quick
    if len(lattice) >= 2:
        spacing = _median_spacing(lattice) or abs(lattice[-1] - lattice[0])
        # Bound processing on dense images; never enumerate thousands of
        # guessed numbers across every font, orientation and zero position.
        if len(lattice) > 18:
            return AxisTickDetection(axis, (), 0.0, scale)
        # A horizontal-first pass avoids 2/3 of expensive glyph OCR for the
        # usual charts. Rotated labels are a second pass only when needed.
        candidates = []
        for orientations in ((0,), (90, 270)):
            raw_by_orientation = {degree: [] for degree in orientations}
            for position in lattice:
                masks = _slot_oriented_masks(image, rect, axis, position, spacing)
                for degrees, mask, bbox in masks:
                    if degrees not in raw_by_orientation:
                        continue
                    reading = _ocr_numeric(mask)
                    if reading is None:
                        continue
                    text, value, confidence = reading
                    if degrees:
                        confidence *= .97
                    if confidence >= .16:
                        raw_by_orientation[degrees].append(
                            (float(position), value, confidence, text, bbox))
            for degrees, raw in raw_by_orientation.items():
                if len(raw) < 2:
                    continue
                detected = _build_axis_detection(axis, scale, raw)
                if scale == AxisScale.LINEAR and (axis == 'y' or len(lattice) >= 3):
                    detected = _verified_y_detection(image, rect, detected, spacing)
                if detected is not None and detected.ready:
                    candidates.append((len(detected.ticks), detected.confidence,
                                       1 if degrees == 0 else 0, detected))
            if candidates:
                return _complete_lattice_ticks(max(candidates, key=lambda x: x[:3])[3], lattice, rect)
        if axis == 'y':
            # On a small regular lattice a bounded template sequence can
            # recover 0/500/1000/1500/2000 when individual glyph OCR fails.
            # It must pass the independent image-score / margin checks in the
            # template detector. Never accept an unverified guessed sequence.
            if scale == AxisScale.LINEAR and 3 <= len(lattice) <= 8:
                fallback = _zero_anchored_template_detection(
                    image, rect, axis, scale, lattice)
                if fallback is not None and fallback.ready:
                    return _complete_lattice_ticks(fallback, lattice, rect)
            return AxisTickDetection(axis, (), 0.0, scale)
        # X keeps the existing zero-origin fallback for short regular axes.
        if 3 <= len(lattice) <= 8:
            fallback = _zero_anchored_template_detection(image, rect, axis, scale, lattice)
            if fallback is not None and fallback.ready:
                return _complete_lattice_ticks(fallback, lattice, rect)

    labels = _x_label_masks(image, rect) if axis == 'x' else _y_label_masks(image, rect)
    labels = _refine_tick_positions(image, rect, axis, labels)
    raw = []
    for position, mask, bbox in labels:
        reading = _ocr_numeric(mask)
        if reading is not None:
            text, value, confidence = reading
            if confidence >= .18:
                raw.append((position, value, confidence, text, bbox))
    detected = _build_axis_detection(axis, scale, raw)
    if axis == 'y' and scale == AxisScale.LINEAR:
        spacing = _median_spacing([item[0] for item in raw]) or 1.0
        return _complete_lattice_ticks(
            _verified_y_detection(image, rect, detected, spacing)
            or AxisTickDetection(axis, (), 0.0, scale), lattice, rect)
    return _complete_lattice_ticks(detected, lattice, rect)


def _recover_transformed_slots(detection, lattice, masks):
    """Read missing glyphs using an already verified transform as context.

    Unlike interpolated grid slots, these points retain an actual text bbox and
    must beat neighbouring numeric hypotheses on the original deskewed pixels.
    This handles connected digits, signs and tiny one-digit endpoint labels.
    """
    fit = _linear_fit([(t.position, _transform_value(t.value, detection.scale)) for t in detection.ticks])
    spacing = _median_spacing(lattice)
    if fit is None or not spacing:
        return detection
    slope, intercept = fit
    delta = slope * spacing
    observed = list(detection.ticks)
    reference = max(observed, key=lambda tick: tick.confidence)

    def value_at(position):
        if detection.scale == AxisScale.LINEAR:
            slot = round((position - reference.position) / spacing)
            return reference.value + slot * _nice_step(delta)
        return _inverse_value(slope * position + intercept, detection.scale)

    for position in lattice:
        if any(abs(t.position - position) <= max(2.5, spacing * .16) for t in observed):
            continue
        value = value_at(position)
        text = _format_tick_value(value)
        alternatives = [_format_tick_value(value_at(position + offset * spacing)) for offset in (-1, 1)]
        for _, mask, bbox in masks(position):
            score = _word_template_score(mask, text)
            nearest = min(_word_template_score(mask, other) for other in alternatives)
            if score <= .28 and score <= nearest + .02:
                observed.append(TickReading(float(position), float(value), text,
                                            min(.80, detection.confidence) * (1.0 - score), bbox))
                break
    return AxisTickDetection(detection.axis, tuple(sorted(observed, key=lambda t: t.position)),
                             detection.confidence, detection.scale)


def _detect_transformed_axis(image, rect, axis, scale, lattice, plan):
    angle, masks = plan
    spacing = _median_spacing(lattice) or 1.0
    candidates = []
    for orientation in (angle, angle + 180):
        raw = []
        for position in lattice:
            for degrees, mask, bbox in masks(position):
                if degrees != orientation:
                    continue
                reading = _ocr_numeric(mask)
                if reading is not None:
                    text, value, confidence = reading
                    raw.append((position, value, confidence, text, bbox))
        detected = _build_axis_detection(axis, scale, raw)
        # Use a consistent reading direction for the whole axis when verifying
        # repaired glyphs. Mixing per-word upside-down guesses is not evidence.
        provider = lambda position, selected=orientation: [item for item in masks(position) if item[0] == selected]
        verified = _verified_y_detection(image, rect, detected, spacing, slot_masks=provider)
        if verified is not None:
            candidates.append(_recover_transformed_slots(verified, lattice, provider))
    if candidates:
        best = max(candidates, key=lambda item: (len(item.ticks), item.confidence))
        return _complete_lattice_ticks(best, lattice, rect)
    fallback = _zero_anchored_template_detection(
        image, rect, axis, scale, lattice, slot_masks=masks)
    return _complete_lattice_ticks(fallback, lattice, rect) if fallback is not None else None

def _complete_regular_mark_positions(positions, rect, axis):
    """Restore interior major-tick slots hidden by an overlay/curve.

    Geometry is inferred only when the *observed* strokes already form a very
    regular lattice.  This is intentionally stricter than numeric completion:
    nonuniform axes remain untouched, while a single doubled/tripled gap can
    recover a grid line hidden by a selection guide or plotted curve.
    """
    ordered = sorted(float(position) for position in positions)
    if len(ordered) < 4:
        return ordered
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b - a > 3]
    if len(gaps) < 3:
        return ordered

    # Find the dominant *small* gap cluster instead of using the raw median;
    # one hidden line creates a 2x gap and must not pull the estimate upward.
    best_cluster = []
    for seed in gaps:
        tolerance = max(2.0, seed * .075)
        cluster = [gap for gap in gaps if abs(gap - seed) <= tolerance]
        if len(cluster) > len(best_cluster):
            best_cluster = cluster
    minimum_support = max(3, math.ceil(len(gaps) * .60))
    if len(best_cluster) < minimum_support:
        return ordered
    spacing = statistics.median(best_cluster)
    if spacing < 7:
        return ordered

    # Every observed gap must be explainable by one, two or three regular
    # intervals. Otherwise this is a genuinely nonuniform geometry.
    multiples = []
    for gap in gaps:
        multiple = int(round(gap / spacing))
        if multiple < 1 or multiple > 3:
            return ordered
        if abs(gap - multiple * spacing) > max(2.5, spacing * .085):
            return ordered
        multiples.append(multiple)
    if not any(multiple > 1 for multiple in multiples):
        return ordered

    low, high = ((float(rect[0]), float(rect[2])) if axis == 'x'
                 else (float(rect[1]), float(rect[3])))
    completed = [ordered[0]]
    inserted = 0
    for first, second, multiple in zip(ordered, ordered[1:], multiples):
        if multiple > 1:
            local_spacing = (second - first) / multiple
            for step_index in range(1, multiple):
                candidate = first + local_spacing * step_index
                if low - 3 <= candidate <= high + 3:
                    completed.append(candidate)
                    inserted += 1
        completed.append(second)
    # A noisy chart should never manufacture a dense artificial lattice.
    if inserted > max(3, len(ordered) // 2):
        return ordered
    return sorted(completed)


def _colored_guide_occlusion_score(image, axis, position, bbox):
    """Return evidence that a colored guide/selection line crosses a label.

    Plot Digitizer guides are colored while chart text/grid strokes are usually
    neutral.  Chroma/brightness thresholding and the perpendicular projection
    run inside Pillow; the previous nested ``getpixel`` loops became noticeable
    on dense axes with many labels and several colored overlays.
    """
    if image is None or bbox == (0, 0, 0, 0):
        return 0.0
    rgb = image.convert('RGB') if image.mode != 'RGB' else image
    x0, y0, x1, y1 = map(int, bbox)
    center = int(round(position))
    if axis == 'x':
        x0, x1 = max(0, center - 3), min(rgb.width - 1, center + 3)
        y0, y1 = max(0, y0 - 3), min(rgb.height - 1, y1 + 3)
    else:
        x0, x1 = max(0, x0 - 3), min(rgb.width - 1, x1 + 3)
        y0, y1 = max(0, center - 3), min(rgb.height - 1, center + 3)
    if x1 < x0 or y1 < y0:
        return 0.0
    crop = rgb.crop((x0, y0, x1 + 1, y1 + 1))
    red, green, blue = crop.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    chroma = _point_lut(ImageChops.subtract(maximum, minimum), _GUIDE_CHROMA_LUT)
    bright = maximum.point(_GUIDE_BRIGHT_LUT)
    colored = ImageChops.multiply(chroma, bright)
    pixels = colored.load()
    # A guide must continue into the padding on both sides of the word.
    # Colored glyphs by themselves must not be classified as occlusion.
    if axis == 'x':
        projected = colored.resize((colored.width, 1), Image.Resampling.BOX).tobytes()
        supported = [value for x, value in enumerate(projected)
                     if any(pixels[x, y] for y in range(min(2, colored.height)))
                     and any(pixels[x, y] for y in range(max(0, colored.height - 2), colored.height))]
    else:
        projected = colored.resize((1, colored.height), Image.Resampling.BOX).tobytes()
        supported = [value for y, value in enumerate(projected)
                     if any(pixels[x, y] for x in range(min(2, colored.width)))
                     and any(pixels[x, y] for x in range(max(0, colored.width - 2), colored.width))]
    return max(supported, default=0) / 255.0


def _infer_occluded_linear_outliers(detection, image, positions):
    """Replace only guide-occluded OCR outliers with a marked inference.

    A robust line is fitted from the other measured ticks.  The predicted value
    may replace an OCR reading only when a colored guide actually crosses that
    label.  The replacement gets an empty bbox, so UI/calibration keeps it as
    ``~inferred`` and never treats it as a measured OCR control point.
    """
    if (detection is None or detection.scale != AxisScale.LINEAR or
            len(detection.ticks) < 4 or len(positions) < 4):
        return detection
    spacing = _median_spacing(positions)
    if spacing is None or spacing < 3:
        return detection
    ticks = list(sorted(detection.ticks, key=lambda tick: tick.position))
    best = None
    for i in range(len(ticks)):
        for j in range(i + 1, len(ticks)):
            first, second = ticks[i], ticks[j]
            delta = second.position - first.position
            if abs(delta) < 2:
                continue
            slope = (second.value - first.value) / delta
            step = abs(slope * spacing)
            if step < 1e-12:
                continue
            intercept = first.value - slope * first.position
            tolerance = max(step * .085, 1e-8)
            inliers = [index for index, tick in enumerate(ticks)
                       if abs(slope * tick.position + intercept - tick.value) <= tolerance]
            if len(inliers) < 3:
                continue
            error = sum(abs(slope * ticks[index].position + intercept - ticks[index].value)
                        / tolerance for index in inliers)
            coverage = (ticks[inliers[-1]].position - ticks[inliers[0]].position
                        if len(inliers) > 1 else 0.0)
            candidate = (len(inliers), coverage, -error, inliers)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
    if best is None or best[0] < max(3, len(ticks) - 2):
        return detection
    inliers = best[3]
    fit = _linear_fit([(ticks[index].position, ticks[index].value) for index in inliers])
    if fit is None:
        return detection
    slope, intercept = fit
    step = abs(slope * spacing)
    if step < 1e-12:
        return detection

    changed = False
    unread = set(float(position) for position in detection.unread_positions)
    inlier_set = set(inliers)
    for index, tick in enumerate(ticks):
        if index in inlier_set or tick.bbox == (0, 0, 0, 0):
            continue
        predicted = slope * tick.position + intercept
        if abs(predicted - tick.value) <= max(step * .14, abs(predicted) * .006, 1e-8):
            continue
        # Context alone is not enough. Require direct evidence that a colored
        # selection/guide stroke crossed this exact label.
        if _colored_guide_occlusion_score(image, detection.axis, tick.position, tick.bbox) < .34:
            continue
        major_step = _nice_step(slope * spacing)
        if abs(major_step) > 1e-12:
            reference = max((ticks[i] for i in inliers), key=lambda item: item.confidence)
            snapped = reference.value + round((predicted - reference.value) / major_step) * major_step
            if abs(snapped - predicted) <= abs(major_step) * .09:
                predicted = snapped
        ticks[index] = TickReading(tick.position, float(predicted), _format_tick_value(predicted),
                                   min(.32, detection.confidence * .42), (0, 0, 0, 0))
        unread.add(float(tick.position))
        changed = True
    if not changed:
        return detection
    measured = [tick.confidence for tick in ticks if tick.bbox != (0, 0, 0, 0)]
    confidence = statistics.median(measured) if measured else detection.confidence
    return AxisTickDetection(detection.axis, tuple(ticks), confidence, detection.scale,
                             tuple(sorted(unread)), detection.mark_positions)


def _recover_occluded_axis_readings(detection, image, words, positions, occluded_positions):
    """Recover guide/curve-covered labels only after clean ticks define a model.

    A de-occluded OCR reading is accepted only when it independently agrees
    with the transform established by measured, non-occluded ticks.  Therefore
    damaged pixels can fill a missing control point but can never steer scale,
    step, direction, or offset.
    """
    if (detection is None or not detection.ready or image is None
            or detection.scale == AxisScale.DATETIME or not occluded_positions):
        return detection
    measured = [tick for tick in sorted(detection.ticks, key=lambda tick: tick.position)
                if tick.bbox != (0, 0, 0, 0) and tick.position not in occluded_positions]
    if len(measured) < 3:
        return detection
    transformed = []
    for tick in measured:
        try:
            transformed.append((tick.position, _transform_value(tick.value, detection.scale)))
        except ValueError:
            return detection
    fit = _linear_fit(transformed)
    spacing = _median_spacing(positions)
    if fit is None or spacing is None or spacing < 3:
        return detection
    slope, intercept = fit
    transformed_step = abs(slope * spacing)
    if transformed_step < 1e-12:
        return detection
    # Clean measured ticks must already agree tightly with the model.
    residuals = [abs(slope * position + intercept - value) for position, value in transformed]
    if max(residuals, default=float('inf')) > max(transformed_step * .08, 1e-8):
        return detection

    ticks = list(detection.ticks)
    unread = set(float(position) for position in detection.unread_positions)
    changed = False
    for position in sorted(float(p) for p in occluded_positions):
        if any(abs(tick.position - position) <= max(2.5, spacing * .15)
               and tick.bbox != (0, 0, 0, 0) for tick in ticks):
            continue
        word = words.get(position)
        if word is None:
            continue
        mask, bbox = word
        recovered = _read_deoccluded_colored_word(image, bbox)
        if recovered is None:
            continue
        text, value, confidence = recovered
        try:
            transformed_value = _transform_value(value, detection.scale)
        except ValueError:
            continue
        predicted = slope * position + intercept
        # The cleaned word may be incomplete.  Require close agreement in the
        # axis' native transformed space before promoting it to measured data.
        if abs(transformed_value - predicted) > max(transformed_step * .16, 1e-8):
            continue
        ticks.append(TickReading(position, float(value), text,
                                 min(.72, max(.48, confidence)), bbox))
        unread.discard(position)
        changed = True
    if not changed:
        return detection
    ticks.sort(key=lambda tick: tick.position)
    measured_conf = [tick.confidence for tick in ticks if tick.bbox != (0, 0, 0, 0)]
    overall = statistics.median(measured_conf) if measured_conf else detection.confidence
    return AxisTickDetection(detection.axis, tuple(ticks), overall, detection.scale,
                             tuple(sorted(unread)), detection.mark_positions)


def _axis_completion_supported(detection, positions):
    """Require a strong measured model before reconstructing unread tick slots."""
    if (detection is None or not detection.ready or len(detection.ticks) < 3
            or len(positions) < 3 or detection.scale == AxisScale.DATETIME):
        return False
    observed = [tick for tick in sorted(detection.ticks, key=lambda tick: tick.position)
                if tick.bbox != (0, 0, 0, 0)]
    if len(observed) < 3:
        return False
    spacing = _median_spacing(positions)
    if spacing is None or spacing < 3:
        return False
    transformed = []
    for tick in observed:
        try:
            transformed.append((tick.position, _transform_value(tick.value, detection.scale)))
        except ValueError:
            return False
    fit = _linear_fit(transformed)
    if fit is None:
        return False
    slope, intercept = fit
    step = abs(slope * spacing)
    if step < 1e-12:
        return False
    residuals = [abs(slope * position + intercept - value)
                 for position, value in transformed]
    return max(residuals, default=float('inf')) <= max(step * .075, 1e-8)


def _linear_completion_supported(detection, positions):
    """Backward-compatible private helper for callers/tests expecting the old name."""
    return (detection is not None and detection.scale == AxisScale.LINEAR
            and _axis_completion_supported(detection, positions))

def _infer_template_supported_linear_outliers(detection, words, positions):
    """Demote a tiny OCR outlier when context *and its own pixels* agree.

    Some 6-10 px labels lose a stroke after screenshot scaling (notably ``1``
    becoming ``3``).  The glyph beam may then never emit the correct numeric
    candidate, so candidate-only repair cannot recover it.  This helper first
    fits a line from at least four other measured ticks, then compares the
    predicted full-word template against the outlier's original raster.  A
    value is accepted only when the predicted template is an absolute good
    match and beats the currently read text by a clear margin.  Because context
    was needed to discover the value, the repaired tick is marked inferred with
    an empty bbox; it is never claimed as an independent OCR control point.
    """
    if (detection is None or detection.scale != AxisScale.LINEAR
            or len(detection.ticks) < 5 or len(positions) < 5):
        return detection
    spacing = _median_spacing(positions)
    if spacing is None or spacing < 3:
        return detection
    ticks = list(sorted(detection.ticks, key=lambda tick: tick.position))
    best = None
    for i in range(len(ticks)):
        for j in range(i + 1, len(ticks)):
            first, second = ticks[i], ticks[j]
            delta = second.position - first.position
            if abs(delta) < 2:
                continue
            slope = (second.value - first.value) / delta
            step = abs(slope * spacing)
            if step < 1e-12:
                continue
            intercept = first.value - slope * first.position
            tolerance = max(step * .075, 1e-8)
            inliers = [index for index, tick in enumerate(ticks)
                       if abs(slope * tick.position + intercept - tick.value) <= tolerance]
            if len(inliers) < 4:
                continue
            coverage = ticks[inliers[-1]].position - ticks[inliers[0]].position
            error = sum(abs(slope * ticks[index].position + intercept - ticks[index].value) / tolerance
                        for index in inliers)
            candidate = (len(inliers), coverage, -error, inliers)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
    if best is None or best[0] < max(4, len(ticks) - 2):
        return detection
    inliers = best[3]
    if best[1] < (positions[-1] - positions[0]) * .48:
        return detection
    fit = _linear_fit([(ticks[index].position, ticks[index].value) for index in inliers])
    if fit is None:
        return detection
    slope, intercept = fit
    step = abs(slope * spacing)
    if step < 1e-12:
        return detection
    inlier_set = set(inliers)
    outliers = [index for index in range(len(ticks)) if index not in inlier_set]
    if not outliers or len(outliers) > 2:
        return detection

    changed = False
    unread = set(float(position) for position in detection.unread_positions)
    reference = max((ticks[index] for index in inliers), key=lambda tick: tick.confidence)
    major_step = _nice_step(slope * spacing)
    for index in outliers:
        tick = ticks[index]
        word = words.get(tick.position)
        if word is None or tick.bbox == (0, 0, 0, 0):
            continue
        mask, _ = word
        predicted = slope * tick.position + intercept
        if abs(major_step) > 1e-12:
            snapped = reference.value + round((predicted - reference.value) / major_step) * major_step
            if abs(snapped - predicted) <= abs(major_step) * .08:
                predicted = snapped
        if not math.isfinite(predicted):
            continue
        observed = _normalize_word_mask(mask)
        if observed is None:
            continue
        proposed_text = _format_tick_value(predicted)
        proposed_score = _normalized_value_template_score(observed, predicted)
        current_score = _normalized_word_template_score(observed, tick.text)
        # Absolute evidence plus a meaningful win over the current OCR.  A
        # stricter margin on larger labels keeps deliberately irregular axes
        # from being coerced into a linear sequence.
        height = len(mask)
        score_limit = .205 if height <= 11 else .175
        margin = .055 if height <= 11 else .075
        if proposed_score > score_limit or proposed_score + margin > current_score:
            continue
        confidence = min(.36, max(.22, (1.0 - proposed_score) * .38))
        ticks[index] = TickReading(tick.position, float(predicted), proposed_text, confidence, (0, 0, 0, 0))
        unread.add(float(tick.position))
        changed = True
    if not changed:
        return detection
    measured = [tick.confidence for tick in ticks if tick.bbox != (0, 0, 0, 0)]
    confidence = statistics.median(measured) if measured else detection.confidence
    return AxisTickDetection(detection.axis, tuple(ticks), confidence, detection.scale,
                             tuple(sorted(unread)), detection.mark_positions)


def _infer_template_supported_log_outliers(detection, words, positions):
    """Repair one logarithmic OCR outlier using its own raster evidence.

    Context proposes a value only after all other measured ticks form a strong
    log-space line.  The proposed full-word template must then beat the current
    OCR on that exact label.  A repaired value is marked inferred (empty bbox),
    so it cannot vote again on scale classification.
    """
    if (detection is None or detection.scale not in (AxisScale.LOG10, AxisScale.LN)
            or len(detection.ticks) < 5 or len(positions) < 5):
        return detection
    ticks = list(sorted(detection.ticks, key=lambda tick: tick.position))
    valid = [index for index, tick in enumerate(ticks)
             if tick.value > 0 and math.isfinite(tick.value) and tick.bbox != (0, 0, 0, 0)]
    if len(valid) < 5:
        return detection

    best = None
    for omitted in valid:
        subset = [index for index in valid if index != omitted]
        samples = [(ticks[index].position, math.log(ticks[index].value)) for index in subset]
        fit = _linear_fit(samples)
        if fit is None:
            continue
        slope, intercept = fit
        transformed = [value for _, value in samples]
        span = max(transformed) - min(transformed)
        if span <= 1e-12:
            continue
        residuals = [abs(slope * ticks[index].position + intercept - math.log(ticks[index].value)) / span
                     for index in subset]
        rmse = math.sqrt(sum(error * error for error in residuals) / len(residuals))
        maximum = max(residuals, default=1.0)
        coverage = ticks[subset[-1]].position - ticks[subset[0]].position
        candidate = (rmse, maximum, -coverage, omitted, fit)
        if best is None or candidate[:3] < best[:3]:
            best = candidate
    if best is None or best[0] > .018 or best[1] > .032:
        return detection

    omitted, fit = best[3], best[4]
    tick = ticks[omitted]
    word = words.get(tick.position)
    if word is None:
        return detection
    slope, intercept = fit
    predicted = math.exp(slope * tick.position + intercept)
    if not math.isfinite(predicted) or predicted <= 0:
        return detection
    # Do not "repair" a value already close to the model; this path is for a
    # true OCR outlier, not harmless font/template jitter.
    log_residual = abs(math.log(tick.value) - math.log(predicted))
    model_step = abs(slope * (_median_spacing(positions) or 1.0))
    if log_residual <= max(model_step * .08, .02):
        return detection

    mask, _ = word
    observed = _normalize_word_mask(mask)
    if observed is None:
        return detection
    proposed_text = _format_tick_value(predicted)
    proposed_score = _normalized_value_template_score(observed, predicted)
    current_score = _normalized_word_template_score(observed, tick.text)
    height = len(mask)
    score_limit = .22 if height <= 11 else .19
    margin = .05 if height <= 11 else .07
    if proposed_score > score_limit or proposed_score + margin > current_score:
        return detection

    unread = set(float(position) for position in detection.unread_positions)
    confidence = min(.36, max(.22, (1.0 - proposed_score) * .38))
    ticks[omitted] = TickReading(tick.position, float(predicted), proposed_text,
                                 confidence, (0, 0, 0, 0))
    unread.add(float(tick.position))
    measured = [item.confidence for item in ticks if item.bbox != (0, 0, 0, 0)]
    overall = statistics.median(measured) if measured else detection.confidence
    return AxisTickDetection(detection.axis, tuple(ticks), overall, detection.scale,
                             tuple(sorted(unread)), detection.mark_positions)



def _repair_ambiguous_linear_readings(detection, words, positions):
    """Use axis context only to choose between OCR candidates from the same pixels.

    A compressed glyph can make two values almost equally plausible (notably
    5/6).  Build a robust line from the other observed ticks and, for at most
    two outliers, accept an alternative only when that exact numeric candidate
    was independently produced from the outlier's own raster.  This differs
    from interpolation: no candidate in the image means no repair.
    """
    if (detection is None or detection.scale != AxisScale.LINEAR or len(detection.ticks) < 4
            or len(positions) < 4):
        return detection
    spacing = _median_spacing(positions)
    if spacing is None or spacing < 3:
        return detection
    ticks = list(sorted(detection.ticks, key=lambda tick: tick.position))
    best = None
    for i in range(len(ticks)):
        for j in range(i + 1, len(ticks)):
            first, second = ticks[i], ticks[j]
            if abs(second.position - first.position) < 2:
                continue
            slope = (second.value - first.value) / (second.position - first.position)
            step = abs(slope * spacing)
            if step < 1e-12:
                continue
            intercept = first.value - slope * first.position
            tolerance = max(step * .085, 1e-8)
            inliers = [index for index, tick in enumerate(ticks)
                       if abs(slope * tick.position + intercept - tick.value) <= tolerance]
            error = sum(abs(slope * ticks[index].position + intercept - ticks[index].value) / tolerance
                        for index in inliers)
            candidate = (len(inliers), -error, inliers)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
    if best is None or best[0] < max(3, len(ticks) - 2):
        return detection
    inliers = best[2]
    fit = _linear_fit([(ticks[index].position, ticks[index].value) for index in inliers])
    if fit is None:
        return detection
    slope, intercept = fit
    step = abs(slope * spacing)
    if step < 1e-12:
        return detection
    outliers = [index for index in range(len(ticks)) if index not in set(inliers)]
    if not outliers or len(outliers) > 2:
        return detection

    changed = False
    for index in outliers:
        tick = ticks[index]
        word = words.get(tick.position)
        if word is None:
            continue
        mask, bbox = word
        predicted = slope * tick.position + intercept
        tolerance = max(step * .12, abs(predicted) * .006, 1e-8)
        candidates = _independent_word_candidates(mask)
        best_error = min((error for _, _, error in candidates), default=1.0)
        native = _ocr_numeric(mask)
        native_support = native is not None and abs(native[1] - predicted) <= tolerance
        if native_support:
            # Give the native segmentation the same visual-candidate status;
            # it still must agree with the robust context below. A visually
            # confident but context-impossible native read (e.g. 9.6 for 0.6)
            # must not lower the glyph-error baseline and suppress the real
            # independent candidate.
            candidates.append((native[0], native[1], max(0.0, (1.0 - native[2]) * .45)))
        if not candidates:
            continue
        matching = [(error, text, value) for text, value, error in candidates
                    if abs(value - predicted) <= tolerance and error <= best_error + .075]
        if not matching:
            continue
        error, text, value = min(matching, key=lambda item: (abs(item[2] - predicted), item[0]))
        observed = _normalize_word_mask(mask)
        proposed_score = _normalized_word_template_score(observed, text) + .10 * error
        current_score = _normalized_word_template_score(observed, tick.text)
        # Context can break a close visual tie, but cannot override clear image
        # evidence for the originally read value. For a partly hidden glyph, a
        # second independent signal from native connected-glyph OCR is enough
        # to widen the tie window slightly (e.g. a clipped 1 that resembles 3).
        visual_margin = .09 if native_support and native[2] >= .65 else .025
        if proposed_score > current_score + visual_margin:
            continue
        confidence = min(tick.confidence, max(.48, 1.0 - proposed_score * 1.8))
        ticks[index] = TickReading(tick.position, float(value), text, confidence, bbox)
        changed = True
    if not changed:
        return detection
    confidence = statistics.median(tick.confidence for tick in ticks)
    return AxisTickDetection(detection.axis, tuple(ticks), confidence, detection.scale,
                             detection.unread_positions, detection.mark_positions)



def _label_driven_words(image, rect, axis, lattice=None):
    """Return tick positions directly from a coherent row/column of labels.

    Some charts (notably year/date X axes) draw no vertical major grid lines at
    all.  In that case geometry must come from the printed labels themselves.
    When physical marks exist, associate labels with those measured coordinates
    (including shared centre/end alignment on rotated X text). Only axes with
    no usable marks fall back to label geometry. No numeric sequence is used
    to relocate a tick.
    """
    labels = _x_label_masks(image, rect) if axis == 'x' else _y_label_masks(image, rect)
    if lattice is not None and len(lattice) >= 3 and 3 <= len(labels) < len(lattice):
        # A single pale label must not disappear just because its neighbours
        # are dark enough for the normal threshold. Retry the bounded strip
        # only when measured marks reveal missing labels, keeping clean masks.
        faint = (_x_label_masks_native(image, rect, faint=True) if axis == 'x'
                 else _y_label_masks_native(image, rect, faint=True))
        if len(faint) > len(labels):
            median_height = statistics.median(box[3] - box[1] + 1 for _, _, box in labels)
            merged = []
            for candidate in faint:
                center, _, _ = candidate
                nearest = min(labels, key=lambda item: abs(item[0] - center))
                distance = abs(nearest[0] - center)
                height = nearest[2][3] - nearest[2][1] + 1
                merged.append(nearest if distance <= max(4, median_height * .2)
                              and height >= median_height * .7 else candidate)
            labels = merged
    if len(labels) < 3:
        return (), {}
    heights = [bbox[3] - bbox[1] + 1 for _, _, bbox in labels]
    median_height = statistics.median(heights)
    filtered = []
    for item, height in zip(labels, heights):
        center, mask, bbox = item
        width = bbox[2] - bbox[0] + 1
        # UI guide fragments/corner annotations are typically much shorter than
        # the repeated tick-label row. Keep genuine narrow labels such as 1/0.
        if height < max(4, median_height * .62):
            continue
        if axis == 'x' and width < 2:
            continue
        filtered.append(item)
    if len(filtered) < 3:
        filtered = labels
    # Prefer supplied mark geometry. Without it, do not hunt for nearby curve
    # segments just to move a label centre onto some darker pixel column.
    refined = filtered
    if axis == 'x' and lattice is not None and len(lattice) >= 3:
        observed = sorted(set(float(value) for value in lattice))
        spacing = _median_spacing(observed) or 0.0
        if spacing >= 3:
            # Rotated labels may be centred OR end-aligned to their ticks.
            # Select one shared alignment from geometry, never from date/value
            # sequences. Then use only actual observed stroke coordinates.
            angle = _label_deskew_angle([(mask, bbox) for _, mask, bbox in filtered])
            anchors = ('center', 'right', 'left') if abs(angle) >= 12 else ('center',)
            mappings = []
            for anchor in anchors:
                snapped = {}
                for center, mask, bbox in filtered:
                    location = center if anchor == 'center' else bbox[2 if anchor == 'right' else 0]
                    position = min(observed, key=lambda value: abs(value - location))
                    distance = abs(position - location)
                    if distance > max(5.0, spacing * .48):
                        continue
                    current = snapped.get(position)
                    if current is None or distance < current[0]:
                        snapped[position] = (distance, mask, bbox)
                if len(snapped) >= 3:
                    mappings.append((-len(snapped), statistics.median(item[0] for item in snapped.values()),
                                     anchors.index(anchor), snapped))
            if mappings:
                snapped = min(mappings, key=lambda item: item[:3])[3]
                words = {position: (mask, bbox) for position, (_, mask, bbox) in snapped.items()}
                return tuple(sorted(words)), words
    if axis == 'y' and lattice is not None and len(lattice) >= 3:
        observed = sorted(float(value) for value in lattice)
        spacing = _median_spacing(observed) or 0.0
        snapped = {}
        for center, mask, bbox in filtered:
            index = bisect_left(observed, center)
            neighbours = observed[max(0, index - 1):min(len(observed), index + 2)]
            if not neighbours:
                continue
            position = min(neighbours, key=lambda value: abs(value - center))
            if spacing and abs(position - center) > max(5.0, spacing * .48):
                position = float(center)
            rank = abs(position - center)
            current = snapped.get(float(position))
            if current is None or rank < current[0]:
                snapped[float(position)] = (rank, mask, bbox)
        if len(snapped) >= 3:
            words = {position: (mask, bbox) for position, (_, mask, bbox) in snapped.items()}
            return tuple(sorted(words)), words
    elif axis == 'y':
        refined = _refine_tick_positions(image, rect, axis, filtered)
    words = {float(position): (mask, bbox) for position, mask, bbox in refined}
    return tuple(sorted(words)), words



def _augment_regular_positions_from_labels(image, rect, axis, positions):
    """Add only label-backed slots that extend/fill an already regular lattice."""
    positions = sorted(float(p) for p in positions)
    if len(positions) < 3:
        return positions
    spacing = _median_spacing(positions)
    if spacing is None or spacing < 4:
        return positions
    labels = _x_label_masks(image, rect) if axis == 'x' else _y_label_masks(image, rect)
    if not labels:
        return positions
    heights = [bbox[3] - bbox[1] + 1 for _, _, bbox in labels]
    median_height = statistics.median(heights)
    origin = positions[0]
    result = list(positions)
    for center, mask, bbox in labels:
        height = bbox[3] - bbox[1] + 1
        if height < max(4, median_height * .60):
            continue
        if min(abs(center - p) for p in result) <= spacing * .28:
            continue
        slot = round((center - origin) / spacing)
        expected = origin + slot * spacing
        if abs(center - expected) > spacing * .18:
            continue
        low, high = (rect[0], rect[2]) if axis == 'x' else (rect[1], rect[3])
        if low - spacing * .20 <= center <= high + spacing * .20:
            result.append(float(center))
    return sorted(result)



def _upright_sequence_words(words):
    """Deskew label words to one shared near-horizontal orientation."""
    if not words:
        return {}
    angle = _label_deskew_angle(list(words.values()))
    upright = {}
    for position, (mask, bbox) in words.items():
        local = angle
        try:
            ink = _mask_image(mask)
            local = max(range(angle - 3, angle + 4),
                        key=lambda value: _word_alignment_score(ink, value))
        except Exception:
            pass
        rotated = _rotate_mask(mask, local) if local else mask
        bounds = _bbox(rotated)
        if bounds is not None:
            rotated = _crop_mask(rotated, bounds)
        upright[position] = (rotated, bbox)
    return upright


def _iso_date_part_candidates(mask, start_fraction, end_fraction, *, digits, minimum, maximum):
    """Return plausible zero-padded numeric candidates for one ISO-date field."""
    if not mask or not mask[0]:
        return []
    width = len(mask[0])
    height = len(mask)
    left = max(0, min(width - 1, int(round(width * start_fraction))))
    right = max(left, min(width - 1, int(round(width * end_fraction)) - 1))
    region = _crop_mask(mask, (left, 0, right, height - 1))
    bounds = _bbox(region)
    if bounds is not None:
        region = _crop_mask(region, bounds)
    raw = sorted(_independent_word_candidates(region, width_multiplier=1.0), key=lambda item: item[2])
    results = {}
    for text, value, error in raw[:12]:
        digits_text = ''.join(ch for ch in text if ch.isdigit())
        if not digits_text:
            rounded = int(round(value))
            digits_text = str(abs(rounded))
        if len(digits_text) > digits:
            digits_text = digits_text[:digits]
        if len(digits_text) < digits:
            digits_text = digits_text.zfill(digits)
        try:
            number = int(digits_text)
        except ValueError:
            continue
        if not minimum <= number <= maximum:
            continue
        candidate = f"{number:0{digits}d}"
        score = error + .012 * abs(len(''.join(ch for ch in text if ch.isdigit())) - digits)
        if candidate not in results or score < results[candidate][1]:
            results[candidate] = (number, score)
    return [(text, value, score) for text, (value, score) in sorted(results.items(), key=lambda item: item[1][1])[:4]]


def _iso_date_word_candidates(mask):
    """Read plausible YYYY-MM-DD words from one label raster only."""
    if not mask or not mask[0]:
        return []
    bounds = _bbox(mask)
    if bounds is not None:
        mask = _crop_mask(mask, bounds)
    height = len(mask)
    width = len(mask[0]) if height else 0
    if height < 8 or width < max(24, height * 3.2):
        return []
    year_options = _iso_date_part_candidates(mask, 0.00, 0.48, digits=4, minimum=1900, maximum=2100)
    month_options = _iso_date_part_candidates(mask, 0.50, 0.76, digits=2, minimum=1, maximum=12)
    day_options = _iso_date_part_candidates(mask, 0.78, 1.00, digits=2, minimum=1, maximum=31)
    if not year_options or not month_options or not day_options:
        return []
    candidates = []
    for y_text, year, y_error in year_options[:4]:
        for m_text, month, m_error in month_options[:4]:
            for d_text, day_value, d_error in day_options[:4]:
                try:
                    value = datetime(year, month, day_value, tzinfo=timezone.utc).timestamp()
                except ValueError:
                    continue
                text = f"{year:04d}-{month:02d}-{day_value:02d}"
                candidates.append((text, value, (y_error + m_error + d_error) / 3.0))
    dedup = {}
    for text, value, error in candidates:
        if text not in dedup or error < dedup[text][1]:
            dedup[text] = (value, error)
    return [(text, value, error) for text, (value, error) in sorted(dedup.items(), key=lambda item: item[1][1])[:8]]


def _iso_datetime_sequence_detection(words, positions, image=None):
    """Recognize an ISO-date X axis such as 2020-01-21, 2020-01-23, ...."""
    ordered = sorted(float(p) for p in positions if p in words)
    if not 4 <= len(ordered) <= 20:
        return None
    upright_words = _upright_sequence_words({p: words[p] for p in ordered})
    source_angle = _label_deskew_angle([words[p] for p in ordered]) if image is not None else 0
    candidate_sets = []
    normalized = []
    for p in ordered:
        mask, _bbox_word = upright_words[p]
        observed = _normalize_word_mask(mask)
        normalized.append(observed)
        candidate_sets.append(_iso_date_word_candidates(mask))
    if sum(bool(items) for items in candidate_sets) < 3 or sum(item is not None for item in normalized) < 4:
        return None

    common_steps = (1, 2, 3, 5, 7, 10, 14, 15, 30, 31, 60, 90, 180, 365, 730)
    hypotheses = set()
    for index, options in enumerate(candidate_sets):
        for text, value, _error in options[:3]:
            start_date = datetime.fromtimestamp(value, tz=timezone.utc).date()
            for step in common_steps:
                begin = start_date - timedelta(days=index * step)
                end = begin + timedelta(days=(len(ordered) - 1) * step)
                if 1900 <= begin.year <= 2100 and 1900 <= end.year <= 2100:
                    hypotheses.add((begin.toordinal(), step))
    for first in range(len(ordered) - 1):
        for second in range(first + 1, min(len(ordered), first + 6)):
            slots = second - first
            for _ta, va, _ea in candidate_sets[first][:3]:
                da = datetime.fromtimestamp(va, tz=timezone.utc).date()
                for _tb, vb, _eb in candidate_sets[second][:3]:
                    db = datetime.fromtimestamp(vb, tz=timezone.utc).date()
                    raw_step = (db - da).days / slots
                    step = int(round(raw_step))
                    if step <= 0 or step > 3660 or abs(raw_step - step) > .18:
                        continue
                    begin = da - timedelta(days=first * step)
                    end = begin + timedelta(days=(len(ordered) - 1) * step)
                    if 1900 <= begin.year <= 2100 and 1900 <= end.year <= 2100:
                        hypotheses.add((begin.toordinal(), step))
    if not hypotheses:
        return None

    evidence = []
    for start_ordinal, step in hypotheses:
        exact = 0
        visual_error = 0.0
        for index in range(len(ordered)):
            current = date.fromordinal(start_ordinal + index * step).isoformat()
            options = [(error, text) for text, _value, error in candidate_sets[index] if text == current]
            if options:
                exact += 1
                visual_error += min(error for error, _text in options)
        if exact >= 2:
            evidence.append((-exact, visual_error, start_ordinal, step))
    if not evidence:
        return None
    evidence.sort()
    best_exact = -evidence[0][0]
    shortlist = [item for item in evidence if -item[0] >= best_exact - 1][:10]

    # Rank the bounded sequence hypotheses with the two-face quick template
    # bank first, then spend the full five-face verification only on the best
    # few. Rotated ISO labels used to render hundreds of full date strings on
    # cold start even though candidate evidence had already narrowed the model.
    quick_ranked = []
    for neg_exact, visual_error, start_ordinal, step in shortlist:
        exact = -neg_exact
        scores = []
        for index, observed in enumerate(normalized):
            if observed is None:
                continue
            text = date.fromordinal(start_ordinal + index * step).isoformat()
            scores.append(_normalized_quick_word_score(observed, text))
        if len(scores) < 4:
            continue
        ordered_scores = sorted(scores)
        keep = max(4, math.ceil(len(scores) * .75))
        robust = sum(ordered_scores[:keep]) / keep
        mean = sum(scores) / len(scores)
        quick_ranked.append((robust + .20 * mean - .008 * exact,
                             neg_exact, visual_error, start_ordinal, step))
    if not quick_ranked:
        return None
    quick_ranked.sort()

    ranked = []
    # A decisive quick-model margin means the two-face bank already agrees on
    # the calendar progression. Full-font verification of four alternative
    # sequences adds no useful evidence in that case; keep more alternatives
    # only when the quick ranking is genuinely ambiguous.
    sequence_limit = 2
    if len(quick_ranked) > 1 and quick_ranked[1][0] - quick_ranked[0][0] < .020:
        sequence_limit = 4
    for _quick_score, neg_exact, visual_error, start_ordinal, step in quick_ranked[:sequence_limit]:
        exact = -neg_exact
        scores = []
        for index, observed in enumerate(normalized):
            if observed is None:
                continue
            text = date.fromordinal(start_ordinal + index * step).isoformat()
            scores.append(_normalized_word_template_score(observed, text))
        if len(scores) < 4:
            continue
        ordered_scores = sorted(scores)
        keep = max(4, math.ceil(len(scores) * .75))
        robust = sum(ordered_scores[:keep]) / keep
        mean = sum(scores) / len(scores)
        ranked.append((robust + .20 * mean - .008 * exact, robust, mean, -exact, visual_error, start_ordinal, step))
    if not ranked:
        return None
    ranked.sort()
    winner = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    _, robust, mean, neg_exact, _visual_error, start_ordinal, step = winner
    exact = -neg_exact
    if exact < 3 or robust > .34 or mean > .37:
        return None
    if runner is not None and runner[0] - winner[0] < .010:
        return None

    # The regular sequence above is a *prior*, not permission to overwrite the
    # printed calendar text. Real charts can use hand-authored/calendar bucket
    # labels whose spacing changes at a month boundary (for example
    # Jan-31 -> Feb-01 -> Feb-03). Re-read a small date window around each
    # predicted slot and choose a monotonic path whose raster evidence wins.
    # This keeps the geometry prior while preserving the actual labels.
    nominal_step = max(1, abs(int(step)))
    window = max(3, min(10, int(round(nominal_step * .25))))
    slot_options = []
    for index, observed in enumerate(normalized):
        predicted = start_ordinal + index * step
        ordinals = set(range(predicted - window, predicted + window + 1))
        for text, value, _error in candidate_sets[index]:
            try:
                ordinals.add(datetime.fromtimestamp(value, tz=timezone.utc).date().toordinal())
            except (OverflowError, OSError, ValueError):
                pass
        quick_options = []
        if observed is not None:
            for ordinal in ordinals:
                try:
                    current = date.fromordinal(ordinal)
                except ValueError:
                    continue
                if not 1900 <= current.year <= 2100:
                    continue
                text = current.isoformat()
                score = _normalized_quick_word_score(observed, text)
                quick_options.append((score, ordinal, text))
        quick_options.sort()
        # Deskewing a binary raster aliases tiny terminal digits. Verify the
        # entire bounded calendar window against the original grayscale before
        # pruning, so a correct day cannot disappear in the binary shortlist.
        source_options = []
        if image is not None and source_angle % 90:
            bbox = words[ordered[index]][1]
            # Binary boxes omit antialias fringes, and an endpoint may have
            # been clipped by the axis search strip. Include the source fringe.
            pad = max(3, min(12, len(upright_words[ordered[index]][0])))
            source_box = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                          min(image.width, bbox[2] + 1 + pad),
                          min(image.height, bbox[3] + 1 + pad))
            gray = image.crop(source_box).convert('L')
            neighbours = [abs(ordered[index] - ordered[other])
                          for other in (index - 1, index + 1) if 0 <= other < len(ordered)]
            if neighbours and min(neighbours) < bbox[2] - bbox[0] + 1 + 2 * pad:
                # Adjacent rotated dates can overlap in bounding-box space.
                # Keep the original grayscale only near this word's isolated
                # ink, otherwise a neighbouring day dominates verification.
                support = Image.new('L', gray.size, 0)
                support.paste(_mask_image(words[ordered[index]][0]),
                              (bbox[0] - source_box[0], bbox[1] - source_box[1]))
                support = support.filter(ImageFilter.MaxFilter(5))
                histogram = gray.histogram()
                backdrop = max(range(256), key=lambda value: histogram[value])
                isolated = Image.new('L', gray.size, backdrop)
                isolated.paste(gray, mask=support)
                gray = isolated
            source = _normalized_gray_word(gray)
            if source is not None:
                height = len(upright_words[ordered[index]][0])
                source_options = [(4.0 * _rotated_gray_score(source, text, height, source_angle),
                                   ordinal, text) for _, ordinal, text in quick_options]
        # Preserve the regular prior and direct per-word date candidates even
        # if their quick two-face score is slightly worse; only the selected
        # shortlist is evaluated with the expensive full template bank.
        # When the two-face bank has a strong per-slot winner, verify only a
        # small optical shortlist plus the sequence/direct-read priors.  Keep
        # the wider legacy shortlist when the margin is weak or the best score
        # is poor so uncommon fonts still get the full multi-face rescue.
        strong_quick = (len(quick_options) >= 2 and quick_options[0][0] <= .28
                        and quick_options[1][0] - quick_options[0][0] >= .025)
        base_count = 3 if strong_quick else 5
        hard_limit = 5 if strong_quick else 8
        chosen = quick_options[:base_count]
        preserve = {predicted}
        for text, value, _error in candidate_sets[index]:
            try:
                preserve.add(datetime.fromtimestamp(value, tz=timezone.utc).date().toordinal())
            except (OverflowError, OSError, ValueError):
                pass
        present = {ordinal for _, ordinal, _ in chosen}
        for item in quick_options[base_count:]:
            if item[1] in preserve and item[1] not in present:
                chosen.append(item)
                present.add(item[1])
            if len(chosen) >= hard_limit:
                break
        if source_options and min(item[0] for item in source_options) <= .34:
            options = source_options
        else:
            options = [(_normalized_word_template_score(observed, text), ordinal, text)
                       for _quick, ordinal, text in chosen]
        day_mask = upright_words[ordered[index]][0]
        if len(day_mask) <= 11:
            # A tiny full-date score is dominated by its shared year/month.
            # Preserve a decisive independent day-field reading (not a regular
            # calendar step), e.g. the narrow final '1' in February 01.
            days = _iso_date_part_candidates(day_mask, .78, 1.0,
                                            digits=2, minimum=1, maximum=31)
            if len(days) >= 2 and days[0][2] <= .24 and days[1][2] - days[0][2] >= .018:
                penalty = min(.08, 2 * (days[1][2] - days[0][2]))
                options = [(score + (penalty if text[-2:] != days[0][0] else 0), ordinal, text)
                           for score, ordinal, text in options]
        options.sort()
        # Keep enough alternatives to survive a clipped endpoint, but avoid a
        # combinatorial path search. Always retain the regular prior too.
        kept = options[:6]
        if not any(ordinal == predicted for _, ordinal, _ in kept):
            prior = next((item for item in options if item[1] == predicted), None)
            if prior is not None:
                kept.append(prior)
        slot_options.append(kept)

    selected_dates = None
    if all(slot_options):
        states = [(score, ordinal, [item]) for item in slot_options[0]
                  for score, ordinal, _text in (item,)]
        for index in range(1, len(slot_options)):
            next_states = []
            for score, ordinal, text in slot_options[index]:
                best_state = None
                for previous_cost, previous_ordinal, path in states:
                    delta = ordinal - previous_ordinal
                    if delta <= 0:
                        continue
                    relative = abs(delta - nominal_step) / max(1.0, nominal_step)
                    transition = .008 * min(4.0, relative)
                    # Very large jumps are possible for monthly/yearly charts,
                    # but should require stronger optical evidence.
                    if delta > max(nominal_step * 4, nominal_step + 31):
                        transition += .03
                    candidate = (previous_cost + score + transition, ordinal, path + [(score, ordinal, text)])
                    if best_state is None or candidate[0] < best_state[0]:
                        best_state = candidate
                if best_state is not None:
                    next_states.append(best_state)
            if not next_states:
                states = []
                break
            next_states.sort(key=lambda item: item[0])
            states = next_states[:12]
        if states:
            selected_dates = min(states, key=lambda item: item[0])[2]

    ticks = []
    measured_conf = []
    for index, p in enumerate(ordered):
        if selected_dates is not None:
            score, ordinal, text = selected_dates[index]
        else:
            ordinal = start_ordinal + index * step
            text = date.fromordinal(ordinal).isoformat()
            observed = normalized[index]
            score = _normalized_word_template_score(observed, text) if observed is not None else 1.0
        current = date.fromordinal(ordinal)
        value = datetime(current.year, current.month, current.day, tzinfo=timezone.utc).timestamp()
        confidence = max(.44, min(.92, 1.0 - 1.45 * score))
        ticks.append(TickReading(p, float(value), text, confidence, upright_words[p][1]))
        measured_conf.append(confidence)
    confidence = statistics.median(measured_conf) if measured_conf else .0
    result = AxisTickDetection('x', tuple(ticks), confidence, AxisScale.DATETIME, (), tuple(ordered))
    return result if result.ready else None


def _year_sequence_detection(words, positions):
    """Recognize a regular four-digit calendar-year label row from raster evidence."""
    ordered = sorted(float(p) for p in positions if p in words)
    if not 4 <= len(ordered) <= 16:
        return None
    spacing = _median_spacing(ordered)
    if spacing is None or spacing < 3:
        return None
    candidate_sets = []
    normalized = []
    for p in ordered:
        mask, bbox = words[p]
        observed = _normalize_word_mask(mask)
        normalized.append(observed)
        raw = sorted(_independent_word_candidates(mask), key=lambda item: item[2])
        years = [(text, int(round(value)), error) for text, value, error in raw[:16]
                 if text.isdigit() and len(text) == 4 and 1500 <= value <= 2500]
        candidate_sets.append(years)
    if sum(bool(items) for items in candidate_sets) < 4 or sum(o is not None for o in normalized) < 4:
        return None

    hypotheses = set()
    for i in range(len(ordered) - 1):
        for j in range(i + 1, len(ordered)):
            slots = j - i
            for _, va, _ in candidate_sets[i][:10]:
                for _, vb, _ in candidate_sets[j][:10]:
                    raw_step = (vb - va) / slots
                    if not .5 <= abs(raw_step) <= 100:
                        continue
                    step = int(round(raw_step))
                    if step == 0 or abs(raw_step - step) > .18:
                        continue
                    start = int(round(va - i * step))
                    end = start + (len(ordered) - 1) * step
                    if min(start, end) < 1500 or max(start, end) > 2500:
                        continue
                    hypotheses.add((start, step))
    if not hypotheses:
        return None

    # Candidate evidence is cheap and already comes from each label's own
    # pixels. Use it to prune hundreds of year sequences before rendering any
    # whole-word font templates. This keeps cold-start bounded.
    evidence = []
    for start, step in hypotheses:
        exact = 0
        visual_error = 0.0
        for index, value in enumerate(start + i * step for i in range(len(ordered))):
            options = [(error, text) for text, candidate, error in candidate_sets[index]
                       if candidate == value]
            if options:
                exact += 1
                visual_error += min(options)[0]
        if exact >= 3:
            evidence.append((-exact, visual_error, start, step))
    if not evidence:
        return None
    evidence.sort()
    best_exact = -evidence[0][0]
    shortlist = [item for item in evidence if -item[0] >= best_exact - 1][:8]

    ranked = []
    for neg_exact, visual_error, start, step in shortlist:
        exact = -neg_exact
        scores = []
        for index, observed in enumerate(normalized):
            if observed is None:
                continue
            value = start + index * step
            scores.append(_normalized_word_template_score(observed, str(value)))
        if len(scores) < 4:
            continue
        ordered_scores = sorted(scores)
        keep = max(4, math.ceil(len(scores) * .75))
        robust = sum(ordered_scores[:keep]) / keep
        mean = sum(scores) / len(scores)
        ranked.append((robust + .22 * mean - .008 * exact,
                       robust, mean, -exact, visual_error, start, step))
    if not ranked:
        return None
    ranked.sort()
    winner = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    _, robust, mean, neg_exact, _, start, step = winner
    exact = -neg_exact
    if exact < 4 or robust > .255 or mean > .285:
        return None
    if runner is not None and runner[0] - winner[0] < .012:
        return None

    ticks = []
    unread = []
    measured_conf = []
    for index, p in enumerate(ordered):
        value = start + index * step
        options = [(error, text) for text, candidate, error in candidate_sets[index]
                   if candidate == value]
        if options:
            error, text = min(options)
            confidence = max(.44, min(.90, 1.0 - 1.55 * error))
            ticks.append(TickReading(p, float(value), text, confidence, words[p][1]))
            measured_conf.append(confidence)
        else:
            ticks.append(TickReading(p, float(value), str(value), .28, (0, 0, 0, 0)))
            unread.append(p)
    confidence = statistics.median(measured_conf) if measured_conf else .0
    # A coherent four-digit calendar-year row is a Date/Time axis, not merely
    # an arbitrary numeric linear axis.  Values remain numeric years internally
    # so existing calibration math can interpolate them linearly.
    result = AxisTickDetection('x', tuple(ticks), confidence, AxisScale.DATETIME,
                               tuple(unread), tuple(ordered))
    return result if result.ready else None


def _candidate_supported_linear_sequence(words, positions):
    """Recover a linear axis by combining per-word candidates and full-raster fit.

    Candidate beams create bounded line hypotheses; the best few hypotheses are
    then re-ranked by whole-word template evidence across *all* labels.  This is
    especially effective for four-digit year axes where one digit is ambiguous
    in isolation but the complete 1981/1985/... sequence is visually decisive.
    """
    ordered = sorted(float(p) for p in positions if p in words)
    if len(ordered) < 4 or len(ordered) > 16:
        return None
    spacing = _median_spacing(ordered)
    if spacing is None or spacing < 3:
        return None
    candidates = {}
    normalized = {}
    for p in ordered:
        mask, bbox = words[p]
        observed = _normalize_word_mask(mask)
        if observed is not None:
            normalized[p] = observed
        raw = sorted(_independent_word_candidates(mask), key=lambda item: item[2])
        if not raw:
            continue
        best_error = raw[0][2]
        filtered = [(text, float(value), float(error)) for text, value, error in raw[:16]
                    if math.isfinite(value) and error <= best_error + .085]
        if filtered:
            candidates[p] = filtered
    if len(candidates) < 4 or len(normalized) < 4:
        return None
    cpositions = sorted(candidates)
    full_span = ordered[-1] - ordered[0]
    models = []
    for ia in range(len(cpositions) - 1):
        pa = cpositions[ia]
        for ib in range(ia + 1, len(cpositions)):
            pb = cpositions[ib]
            if pb - pa < spacing * 1.5:
                continue
            for ta, va, ea in candidates[pa][:10]:
                for tb, vb, eb in candidates[pb][:10]:
                    slope = (vb - va) / (pb - pa)
                    if abs(slope) < 1e-12:
                        continue
                    intercept = va - slope * pa
                    step = abs(slope * spacing)
                    if step < 1e-9:
                        continue
                    matches = []
                    residual_sum = 0.0
                    visual_sum = 0.0
                    for p in cpositions:
                        predicted = slope * p + intercept
                        tolerance = max(step * .12, abs(predicted) * .0015, .20)
                        options = [(abs(value - predicted), error, text, value)
                                   for text, value, error in candidates[p]
                                   if abs(value - predicted) <= tolerance]
                        if not options:
                            continue
                        residual, error, text, value = min(options, key=lambda item: (item[0], item[1]))
                        matches.append((p, text, value, error))
                        residual_sum += residual / tolerance
                        visual_sum += error
                    if len(matches) < 4:
                        continue
                    coverage = matches[-1][0] - matches[0][0]
                    if coverage < full_span * .50:
                        continue
                    prelim = (len(matches), coverage, -residual_sum, -visual_sum)
                    models.append((prelim, matches, slope, intercept))
    if not models:
        return None
    models.sort(key=lambda item: item[0], reverse=True)
    # Keep diverse top hypotheses; many candidate pairs describe effectively the
    # same line. Quantization avoids spending template work on duplicates.
    shortlist = []
    seen = set()
    for model in models:
        _, matches, slope, intercept = model
        step = slope * spacing
        nice = _nice_step(step)
        if abs(nice - step) <= max(abs(step), 1e-9) * .10:
            step = nice
        reference = min(matches, key=lambda item: item[3])
        ref_p, _, ref_value, _ = reference
        key = (round(step, 6), round(ref_value - round((ref_p - ordered[0]) / spacing) * step, 4))
        if key in seen:
            continue
        seen.add(key)
        shortlist.append((model, step, reference))
        if len(shortlist) >= 28:
            break

    ranked = []
    for model, step, reference in shortlist:
        _, matches, slope, intercept = model
        ref_p, ref_text, ref_value, ref_error = reference
        sequence = []
        scores = []
        for p in ordered:
            slot = int(round((p - ref_p) / spacing))
            predicted = ref_value + slot * step
            # If geometry is slightly nonuniform, use the line prediction unless
            # it is already close to the regular-slot value.
            line_value = slope * p + intercept
            if abs(line_value - predicted) > max(abs(step) * .14, abs(predicted) * .002):
                predicted = line_value
            rounded = round(predicted)
            if abs(predicted - rounded) <= max(.08, abs(step) * .03):
                predicted = float(rounded)
            observed = normalized.get(p)
            if observed is None:
                continue
            score = _normalized_value_template_score(observed, predicted)
            scores.append(score)
            sequence.append((p, predicted, score))
        if len(scores) < 4:
            continue
        ordered_scores = sorted(scores)
        keep = max(4, math.ceil(len(scores) * .75))
        robust = sum(ordered_scores[:keep]) / keep
        mean = sum(scores) / len(scores)
        ranked.append((robust + .22 * mean, robust, mean, sequence, model, step))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    winner = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    if winner[1] > .255 or winner[2] > .285:
        return None
    if runner is not None and runner[0] - winner[0] < .012:
        return None

    _, _, _, sequence, model, step = winner
    _, matches, slope, intercept = model
    match_by_p = {p: (text, value, error) for p, text, value, error in matches}
    ticks = []
    unread = []
    measured_conf = []
    for p, predicted, score in sequence:
        matched = match_by_p.get(p)
        if matched is not None:
            text, value, error = matched
            tolerance = max(abs(step) * .12, abs(predicted) * .0015, .20)
            if abs(value - predicted) <= tolerance:
                confidence = max(.44, min(.90, 1.0 - 1.55 * error))
                ticks.append(TickReading(p, float(value), text, confidence, words[p][1]))
                measured_conf.append(confidence)
                continue
        ticks.append(TickReading(p, float(predicted), _format_tick_value(predicted), .28, (0, 0, 0, 0)))
        unread.append(p)
    confidence = statistics.median(measured_conf) if measured_conf else .0
    result = AxisTickDetection('x', tuple(ticks), confidence, AxisScale.LINEAR,
                               tuple(unread), tuple(ordered))
    return result if result.ready and len(measured_conf) >= 4 else None


def _log_decade_template_detection(axis, words, positions):
    """Recognize a regular power-of-ten major axis from the whole label column.

    Cheap numeric beams first propose exponent sequences; whole-word template
    rendering is spent only on that short list. If no numeric evidence survives,
    fall back to ±1-decade sequences rather than scanning every base/step pair.
    """
    positions = sorted(float(p) for p in positions)
    if len(positions) < 5 or len(words) < 4:
        return None
    spacing = _median_spacing(positions)
    if spacing is None or spacing < 3:
        return None
    diffs = [b - a for a, b in zip(positions, positions[1:])]
    if diffs and max(abs(d - spacing) for d in diffs) > spacing * .20:
        return None
    observations = {}
    exponent_candidates = {}
    for index, p in enumerate(positions):
        word = words.get(p)
        if word is None:
            continue
        observed = _normalize_word_mask(word[0])
        if observed is None:
            continue
        observations[p] = observed
        raw = sorted(_independent_word_candidates(word[0]), key=lambda item: item[2])[:16]
        exps = {}
        for text, value, error in raw:
            if not math.isfinite(value) or value <= 0:
                continue
            exponent = int(round(math.log10(value)))
            if not -18 <= exponent <= 18:
                continue
            ratio_error = abs(math.log10(value) - exponent)
            if ratio_error > .17:
                continue
            score = float(error) + ratio_error * .45
            exps[exponent] = min(exps.get(exponent, 9.0), score)
        if exps:
            exponent_candidates[index] = exps
    if len(observations) < 4:
        return None

    hypotheses = set()
    indexes = sorted(exponent_candidates)
    for a_index in range(len(indexes)):
        ia = indexes[a_index]
        for b_index in range(a_index + 1, len(indexes)):
            ib = indexes[b_index]
            slots = ib - ia
            if slots <= 0:
                continue
            for ea in exponent_candidates[ia]:
                for eb in exponent_candidates[ib]:
                    raw_step = (eb - ea) / slots
                    step = int(round(raw_step))
                    if step == 0 or abs(step) > 3 or abs(raw_step - step) > .12:
                        continue
                    start_exp = ea - ia * step
                    if -18 <= start_exp <= 18:
                        hypotheses.add((start_exp, step))
    # One readable decade is enough to propose the common ±1 direction; a
    # second/third label and the global raster score must still verify it.
    for index, exps in exponent_candidates.items():
        for exponent in exps:
            for step in (-1, 1):
                start_exp = exponent - index * step
                if -18 <= start_exp <= 18:
                    hypotheses.add((start_exp, step))
    if not hypotheses:
        hypotheses = {(start_exp, step) for step in (-1, 1)
                      for start_exp in range(-12, 16)}

    # Cheap exponent-candidate agreement prunes the proposal set before font
    # rendering. Retain a few alternatives because one OCR beam can be wrong.
    evidence = []
    for start_exp, step_exp in hypotheses:
        matches = 0
        error = 0.0
        for index, exps in exponent_candidates.items():
            expected = start_exp + index * step_exp
            if expected in exps:
                matches += 1
                error += exps[expected]
        evidence.append((-matches, error, start_exp, step_exp))
    evidence.sort()
    best_matches = -evidence[0][0] if evidence else 0
    shortlist = [item for item in evidence if -item[0] >= max(0, best_matches - 1)][:12]

    ranked = []
    for neg_matches, candidate_error, start_exp, step_exp in shortlist:
        scores = []
        for index, p in enumerate(positions):
            observed = observations.get(p)
            if observed is None:
                continue
            exponent = start_exp + index * step_exp
            if exponent < -18 or exponent > 18:
                scores = []
                break
            scores.append(_normalized_value_template_score(observed, 10.0 ** exponent))
        if len(scores) < 4:
            continue
        ordered_scores = sorted(scores)
        keep = max(4, math.ceil(len(ordered_scores) * .70))
        robust = sum(ordered_scores[:keep]) / keep
        mean = sum(scores) / len(scores)
        matches = -neg_matches
        ranked.append((robust + .25 * mean - .006 * matches,
                       robust, mean, start_exp, step_exp, scores))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    winner = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    if winner[1] > .31 or winner[2] > .36:
        return None
    if runner is not None and runner[0] - winner[0] < .020:
        return None
    _, robust, mean, start_exp, step_exp, _ = winner
    ticks = []
    measured_conf = []
    unread = []
    for index, p in enumerate(positions):
        value = 10.0 ** (start_exp + index * step_exp)
        word = words.get(p)
        if word is not None:
            score = _normalized_value_template_score(observations[p], value)
            if score <= .34:
                confidence = max(.44, min(.88, 1.0 - 1.55 * score))
                ticks.append(TickReading(p, value, _format_tick_value(value), confidence, word[1]))
                measured_conf.append(confidence)
                continue
        ticks.append(TickReading(p, value, _format_tick_value(value), .27, (0, 0, 0, 0)))
        unread.append(p)
    confidence = statistics.median(measured_conf) if measured_conf else .0
    result = AxisTickDetection(axis, tuple(ticks), confidence, AxisScale.LOG10,
                               tuple(unread), tuple(positions))
    return result if result.ready and len(measured_conf) >= 3 else None
