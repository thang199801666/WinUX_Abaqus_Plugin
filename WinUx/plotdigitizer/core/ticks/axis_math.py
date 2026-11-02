from __future__ import annotations

import math
import statistics

from ..models import AxisScale

def _median_spacing(positions):
    differences = sorted(b - a for a, b in zip(positions, positions[1:]) if b - a > 2)
    if not differences:
        return None
    if len(differences) <= 2:
        return float(statistics.median(differences))

    # OCR can produce several tiny pseudo-labels from a rotated Y-axis title.
    # Conversely, one missing tick creates a single double-width gap.  Using
    # the lower half (the old behaviour) strongly favored those tiny false
    # gaps.  Estimate the dominant adjacent spacing from the central band
    # around the raw median, which rejects both failure modes.
    center = float(statistics.median(differences))
    if center <= 0:
        return center
    central = [value for value in differences
               if center * .60 <= value <= center * 1.60]
    if len(central) >= 2:
        return float(statistics.median(central))
    return center


def _transform_value(value, scale):
    if scale in (AxisScale.LOG10, AxisScale.LN):
        if value <= 0:
            raise ValueError
        return math.log(value)
    return value


def _inverse_value(value, scale):
    if scale in (AxisScale.LOG10, AxisScale.LN):
        return math.exp(value)
    return value


def _nice_step(value):
    if not math.isfinite(value) or abs(value) < 1e-15:
        return value
    sign = -1.0 if value < 0 else 1.0
    absolute = abs(value)
    exponent = math.floor(math.log10(absolute))
    candidates = []
    for exp in range(exponent - 1, exponent + 2):
        scale = 10.0 ** exp
        for mantissa in (1.0, 2.0, 2.5, 4.0, 5.0, 8.0, 10.0):
            candidates.append(mantissa * scale)
    best = min(candidates, key=lambda candidate: abs(math.log(candidate / absolute)))
    # Do not force unusual real tick steps to a "nice" value unless the match
    # is already close; e.g. 0.8 is explicitly included and remains 0.8.
    if abs(best - absolute) / absolute <= .08:
        return sign * best
    return value


def _nice_log_step(value):
    """Snap a fitted log-space major step only when it is already very close.

    This removes small pixel/anti-aliasing drift from common decade, e-power
    and power-of-two major ticks without forcing unusual logarithmic grids onto
    a conventional base.
    """
    if not math.isfinite(value) or abs(value) < 1e-12:
        return value
    sign = -1.0 if value < 0 else 1.0
    absolute = abs(value)
    bases = (math.log(10.0), 1.0, math.log(2.0))
    multipliers = (.25, .5, 1.0, 2.0, 3.0)
    candidates = [base * multiplier for base in bases for multiplier in multipliers]
    best = min(candidates, key=lambda candidate: abs(candidate - absolute) / candidate)
    if abs(best - absolute) / max(best, absolute) <= .055:
        return sign * best
    return value


def _linear_fit(points):
    count = len(points)
    if count < 2:
        return None
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator <= 1e-12:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _robust_axis_values(raw, scale):
    # raw: [(pixel, recognized_value, confidence, text, bbox), ...]
    if len(raw) < 2:
        return None
    transformed = []
    for item in raw:
        try:
            transformed.append((item[0], _transform_value(item[1], scale), *item[2:]))
        except ValueError:
            continue
    if len(transformed) < 2:
        return None
    positions = [item[0] for item in transformed]
    spacing = _median_spacing(sorted(positions))
    if spacing is None:
        return None
    best = None
    for i in range(len(transformed)):
        for j in range(i + 1, len(transformed)):
            p1, v1 = transformed[i][0], transformed[i][1]
            p2, v2 = transformed[j][0], transformed[j][1]
            if abs(p2 - p1) < 2:
                continue
            slope = (v2 - v1) / (p2 - p1)
            if abs(slope) < 1e-15:
                continue
            intercept = v1 - slope * p1
            tick_delta = max(1e-9, abs(slope * spacing))
            inliers, normalized_error = [], 0.0
            for index, item in enumerate(transformed):
                prediction = slope * item[0] + intercept
                residual = abs(prediction - item[1])
                tolerance = max(tick_delta * .075, abs(prediction) * .025, 1e-7)
                if residual <= tolerance:
                    inliers.append(index)
                    normalized_error += residual / tolerance
            candidate = (len(inliers), -normalized_error, inliers, slope, intercept)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
    if best is None or best[0] < 2:
        return None
    inliers = best[2]
    fit = _linear_fit([(transformed[index][0], transformed[index][1]) for index in inliers])
    if fit is None:
        return None
    slope, intercept = fit

    # On linear axes, quantize a near-standard tick step and use the detected
    # pixel spacing to correct isolated OCR mistakes (3 vs 1, 0 vs 8, etc.).
    corrected = []
    if scale == AxisScale.LINEAR:
        step = _nice_step(slope * spacing)
        ordered_positions = sorted(item[0] for item in transformed)
        origin_pixel = ordered_positions[0]
        offsets = [transformed[index][1] - step * int(round((transformed[index][0] - origin_pixel) / spacing))
                   for index in inliers]
        offset = statistics.median(offsets)
        if abs(step) > 1e-12:
            snapped = round(offset / step) * step
            if abs(snapped - offset) <= abs(step) * .07:
                offset = snapped
        for item in transformed:
            index = int(round((item[0] - origin_pixel) / spacing))
            value = offset + step * index
            corrected.append((item, value, index))

        # Keep at most one OCR label per regular tick slot.  A rotated Y-axis
        # title can generate several pseudo-numbers between two real ticks; the
        # old code repaired their *values* but still retained their pixel
        # positions, and those extra points skewed the final edge fit.  Genuine
        # OCR mistakes at a real tick remain useful because their pixel position
        # lies on the regular tick lattice and their value can be repaired.
        inlier_set = set(inliers)
        by_slot = {}
        for raw_index, entry in enumerate(corrected):
            item, value, slot = entry
            expected_pixel = origin_pixel + spacing * slot
            residual = abs(item[0] - expected_pixel)
            is_inlier = raw_index in inlier_set
            if not is_inlier and residual > max(3.0, spacing * .12):
                continue
            rank = (1 if is_inlier else 0, -residual, item[2])
            current = by_slot.get(slot)
            if current is None or rank > current[0]:
                by_slot[slot] = (rank, raw_index, entry)
        corrected = [(raw_index, entry) for _, raw_index, entry in
                     sorted(by_slot.values(), key=lambda value: value[2][2])]
    else:
        corrected = [(index, (item, _inverse_value(slope * item[0] + intercept, scale), 0))
                     for index, item in enumerate(transformed)]
        inlier_set = set(inliers)

    result = []
    if scale == AxisScale.LINEAR:
        corrected_entries = corrected
    else:
        corrected_entries = corrected
    for raw_index, (item, value, _) in corrected_entries:
        confidence = item[2]
        if raw_index not in inlier_set:
            confidence *= .72
        result.append((item[0], float(value), confidence, item[3], item[4]))
    inlier_ratio = len(inliers) / len(transformed)
    ocr_confidence = sum(item[2] for item in transformed) / len(transformed)
    confidence = min(1.0, .56 * inlier_ratio + .44 * ocr_confidence)
    return result, confidence
