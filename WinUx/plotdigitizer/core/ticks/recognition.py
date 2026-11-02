from __future__ import annotations

import math
import statistics
from bisect import bisect_left
from functools import lru_cache
from operator import mul

from PIL import Image, ImageChops, ImageDraw, ImageStat

from ..models import AxisScale
from .axis_math import _linear_fit, _median_spacing
from .pixels import (
    _bbox, _binary_mask, _classify_digit, _column_sums, _components, _crop_mask,
    _dilate_binary_square, _glyph_score, _glyph_templates, _mask_image,
    _numeric_glyph_boxes, _point_lut, _projection_bands, _template_font_indexes,
    _template_fonts, _threshold_lut,
)
from .shared import _LINE_STRENGTH_LUT, _NEUTRAL_CHROMA_LUT, _NUMERIC_CHARS

def _numeric_text_hypotheses(text):
    """Return plausible numeric interpretations of segmented punctuation.

    Tiny chart punctuation is deliberately classified geometrically before any
    font/template pass.  A printed comma therefore often reaches this stage as
    ``.``.  Keep both decimal and thousands-grouping hypotheses when the glyph
    grouping permits it; the whole-word raster/template score decides later.
    Multiple 3-digit groups are unambiguously thousands separators.
    """
    text = str(text or '').strip()
    if not text or text in {'-', '.', '-.'}:
        return ()
    results = []
    # Ordinary decimal/integer interpretation.
    if text.count('.') <= 1:
        try:
            value = float(text)
        except ValueError:
            pass
        else:
            if math.isfinite(value):
                results.append((text, float(value)))

    sign = ''
    body = text
    if body[:1] in '+-':
        sign, body = body[0], body[1:]
    groups = body.split('.')
    grouped = None
    if (len(groups) >= 2 and 1 <= len(groups[0]) <= 3
            and all(group.isdigit() for group in groups)):
        if all(len(group) == 3 for group in groups[1:]):
            grouped = groups
        elif (len(groups) == 2 and len(groups[1]) >= 3
              and len(groups[1]) % 3 == 0):
            # A faint comma can disappear completely between two 3-digit
            # groups: ``10,000,000`` may segment as ``10.000000``. Keep the
            # grouped interpretation as an alternate raster hypothesis.
            grouped = [groups[0]] + [groups[1][i:i + 3]
                                      for i in range(0, len(groups[1]), 3)]
    if grouped is not None:
        digits = ''.join(grouped)
        try:
            value = float((sign or '') + digits)
        except ValueError:
            value = float('nan')
        if math.isfinite(value):
            rendered = (sign or '') + ','.join(grouped)
            if not any(_same_numeric_value(value, existing[1]) and rendered == existing[0]
                       for existing in results):
                results.append((rendered, value))
    return tuple(results)


def _ocr_numeric(mask):
    box = _bbox(mask)
    if box is None:
        return None
    height = box[3] - box[1] + 1
    chars, confidences = [], []
    for x0, y0, x1, y1, kind in _numeric_glyph_boxes(mask):
        glyph = _crop_mask(mask, (x0, y0, x1, y1))
        gh, gw = len(glyph), len(glyph[0])
        if kind == "punct":
            center_y = (y0 + y1) / 2 / max(1, len(mask))
            if center_y >= .55:
                chars.append("."); confidences.append(.96)
            elif gw >= gh * 1.4:
                chars.append("-"); confidences.append(.90)
            continue
        char, confidence = _classify_digit(glyph)
        chars.append(char); confidences.append(confidence)
    text = "".join(chars)
    hypotheses = _numeric_text_hypotheses(text)
    if not hypotheses:
        return None
    # Native glyph OCR has no whole-word punctuation renderer, so retain the
    # ordinary decimal interpretation when it exists.  Multiple grouped
    # separators have only one sensible numeric interpretation.  The richer
    # independent-word path keeps both alternatives and resolves them visually.
    selected_text, value = hypotheses[0]
    if text.count('.') >= 2:
        grouped = next(((candidate_text, candidate_value) for candidate_text, candidate_value in hypotheses
                        if ',' in candidate_text), None)
        if grouped is not None:
            selected_text, value = grouped
    confidence = sum(confidences) / max(1, len(confidences))
    return selected_text, value, confidence


def _faint_label_mask(image):
    """Bounded retry for uniform-background labels only a few levels from it."""
    gray = image.convert('L')
    histogram = gray.histogram()
    background = max(range(256), key=lambda value: histogram[value])
    if histogram[background] < gray.width * gray.height * .55:
        return None  # Do not promote arbitrary texture/gradients into text.
    if 30 < background < 225:
        return None
    light = background >= 128
    threshold = background - 3 if light else background + 3
    pixels = gray.tobytes().translate(_threshold_lut(threshold, dark=light))
    return [bytearray(pixels[y * gray.width:(y + 1) * gray.width]) for y in range(gray.height)]


def _x_label_masks(image, rect):
    labels = _x_label_masks_native(image, rect)
    if len(labels) >= 3:
        return labels
    faint = _x_label_masks_native(image, rect, faint=True)
    return faint if len(faint) >= max(3, len(labels) + 1) else labels


def _x_label_masks_native(image, rect, *, faint=False):
    left, top, right, bottom = map(int, rect)
    plot_width, plot_height = right - left, bottom - top
    if bottom >= image.height - 2:
        return []
    # Rotated ISO-date labels can project much farther below the plot than a
    # short horizontal year row. Keep the default strip compact on ordinary
    # charts, but allow a taller search band when the image has room.
    depth = min(image.height - bottom - 1, max(32, min(150, int(plot_height * .30))))
    # A rotated endpoint label may extend half a word beyond its tick. Keep
    # enough source pixels to read it without clipping the year prefix.
    pad = max(20, min(85, plot_width // 8))
    x0, x1 = max(0, left - pad), min(image.width - 1, right + pad)
    y0, y1 = bottom + 2, min(image.height - 1, bottom + depth)
    crop = image.crop((x0, y0, x1 + 1, y1 + 1))
    mask = _faint_label_mask(crop) if faint else _binary_mask(crop)
    if mask is None:
        return []
    row_counts = [sum(row) for row in mask]
    bands = _projection_bands(row_counts, minimum=2, merge_gap=1)
    # Slanted date labels often occupy a 40-90 px tall diagonal band.
    bands = [(a, b) for a, b in bands if 4 <= b - a + 1 <= 110]
    if not bands:
        return []

    # A y-axis bottom label can protrude a few pixels below the box and appear
    # before the actual X tick row.  Evaluate all nearby text rows and choose
    # the one containing several numeric-looking groups spread across X.  The
    # later axis title normally forms only one wide group.
    best_labels = []
    best_score = None
    for row0, row1 in bands:
        text_mask = _crop_mask(mask, (0, row0, len(mask[0]) - 1, row1))
        col_counts = _column_sums(text_mask)
        runs = _projection_bands(col_counts, minimum=1, merge_gap=0)
        if not runs:
            continue
        # Taller bands usually correspond to rotated labels, whose glyph runs
        # are separated by larger horizontal gaps after projection.
        join_gap = max(3, int((row1 - row0 + 1) * (.92 if (row1 - row0 + 1) > 38 else .68)))
        groups = [[runs[0]]]
        for run in runs[1:]:
            gap = run[0] - groups[-1][-1][1] - 1
            if gap <= join_gap:
                groups[-1].append(run)
            else:
                groups.append([run])
        labels = []
        for group in groups:
            gx0, gx1 = group[0][0], group[-1][1]
            if gx1 - gx0 < 1:
                continue
            label = _crop_mask(mask, (gx0, row0, gx1, row1))
            tight = _bbox(label)
            if tight is None:
                continue
            label = _crop_mask(label, tight)
            abs_box = (x0 + gx0 + tight[0], y0 + row0 + tight[1],
                       x0 + gx0 + tight[2], y0 + row0 + tight[3])
            center = (abs_box[0] + abs_box[2]) / 2.0
            if left - pad <= center <= right + pad:
                labels.append((center, label, abs_box))
        if not labels:
            continue
        centers = [label[0] for label in labels]
        span = max(centers) - min(centers) if len(centers) >= 2 else 0.0
        score = (len(labels), span / max(1.0, plot_width), -row0)
        if best_score is None or score > best_score:
            best_score = score
            best_labels = labels

    if len(best_labels) >= 3:
        return best_labels

    # Rotated/slanted date labels do not always form one compact horizontal
    # row band.  Fall back to whole-strip word grouping by dilating nearby
    # glyphs into label-sized connected components.
    merged = _dilate_binary_square(_mask_image(mask), 4)
    pixels = merged.tobytes()
    groups = _components([bytearray(pixels[y * merged.width:(y + 1) * merged.width])
                          for y in range(merged.height)])
    labels = []
    for gx0, gy0, gx1, gy1, area in groups:
        if area < 18:
            continue
        label = _isolated_word_group(mask, merged, (gx0, gy0, gx1, gy1), area)
        tight = _bbox(label)
        if tight is None:
            continue
        label = _crop_mask(label, tight)
        abs_box = (x0 + gx0 + tight[0], y0 + gy0 + tight[1],
                   x0 + gx0 + tight[2], y0 + gy0 + tight[3])
        width, height = abs_box[2] - abs_box[0] + 1, abs_box[3] - abs_box[1] + 1
        if height < 8 or height > 110 or width < 12 or width > 220:
            continue
        center = (abs_box[0] + abs_box[2]) / 2.0
        if left - pad <= center <= right + pad:
            labels.append((center, label, abs_box))
    if len(labels) >= 3:
        heights = [item[2][3] - item[2][1] + 1 for item in labels]
        median_height = statistics.median(heights)
        labels = [item for item in labels
                  if abs((item[2][3] - item[2][1] + 1) - median_height) <= max(8, median_height * .45)]
        return sorted(labels, key=lambda item: item[0])
    return best_labels


def _y_label_masks(image, rect):
    labels = _y_label_masks_native(image, rect)
    if len(labels) >= 3:
        return labels
    faint = _y_label_masks_native(image, rect, faint=True)
    return faint if len(faint) >= max(3, len(labels) + 1) else labels


def _y_label_masks_native(image, rect, *, faint=False):
    left, top, right, bottom = map(int, rect)
    plot_width, plot_height = right - left, bottom - top
    if left <= 2:
        return []
    depth = min(left, max(34, min(128, int(plot_width * .18))))
    pad_y = max(6, min(18, int(plot_height * .025)))
    x0, x1 = max(0, left - depth), left - 2
    y0, y1 = max(0, top - pad_y), min(image.height - 1, bottom + pad_y)
    crop = image.crop((x0, y0, x1 + 1, y1 + 1))
    # A Box a few pixels inside the plot includes the physical vertical axis.
    # Remove that full-height rule before it joins every numeric row together.
    mask = _faint_label_mask(crop) if faint else _binary_mask(crop)
    if mask is None:
        return []
    mask = _remove_long_rules(mask)
    row_counts = [sum(row) for row in mask]
    bands = _projection_bands(row_counts, minimum=2, merge_gap=1)
    labels = []
    for row0, row1 in bands:
        # A single comma's descender can occupy only one pixel per row. Keep
        # those adjacent rows even though the band seed requires two pixels.
        while row0 > 0 and row_counts[row0 - 1]:
            row0 -= 1
        while row1 + 1 < len(row_counts) and row_counts[row1 + 1]:
            row1 += 1
        height = row1 - row0 + 1
        if not 4 <= height <= 38:
            continue
        band = _crop_mask(mask, (0, row0, len(mask[0]) - 1, row1))

        # Y-axis tick text is right-aligned next to the plot edge, while the
        # rotated axis title can intersect the *same horizontal row* farther
        # left.  Cropping the whole row therefore lets title glyphs contaminate
        # numeric OCR (for example, ``1000`` + part of ``Load``).  Split the
        # row into horizontal text groups first and keep only the rightmost
        # group nearest the Y axis.
        col_counts = _column_sums(band)
        runs = _projection_bands(col_counts, minimum=1, merge_gap=0)
        if not runs:
            continue
        join_gap = max(2, int(height * .48))
        groups = [[runs[0]]]
        for run in runs[1:]:
            gap = run[0] - groups[-1][-1][1] - 1
            if gap <= join_gap:
                groups[-1].append(run)
            else:
                groups.append([run])
        # Numeric labels are the rightmost text object before the axis.  This
        # also handles negative/decimal labels whose sign/dot is a disconnected
        # component, because nearby runs were joined above.
        # Short horizontal tick strokes lie closer to the axis than the text.
        # They are not a label column, even when they share the numeric band.
        text_groups = []
        for candidate in groups:
            bounds = _bbox(_crop_mask(band, (candidate[0][0], 0,
                                            candidate[-1][1], len(band) - 1)))
            if bounds is not None and bounds[3] - bounds[1] + 1 >= 4:
                text_groups.append(candidate)
        if not text_groups:
            continue
        group = max(text_groups, key=lambda item: item[-1][1])
        gx0, gx1 = group[0][0], group[-1][1]
        if gx1 < len(band[0]) * .38 or gx1 - gx0 < 1:
            continue
        numeric_band = _crop_mask(band, (gx0, 0, gx1, len(band) - 1))
        tight = _bbox(numeric_band)
        if tight is None:
            continue
        label = _crop_mask(numeric_band, tight)
        abs_box = (x0 + gx0 + tight[0], y0 + row0 + tight[1],
                   x0 + gx0 + tight[2], y0 + row0 + tight[3])
        center = (abs_box[1] + abs_box[3]) / 2.0
        if top - pad_y <= center <= bottom + pad_y:
            labels.append((center, label, abs_box))

    if len(labels) >= 2:
        # Y tick labels are normally right-aligned against the same axis edge.
        # Rotated axis-title fragments can form their own short horizontal
        # bands and occasionally look numeric (``l`` -> 1/4, ``o`` -> 0).
        # Reject groups whose right edge is materially farther from the plot
        # than the main label column.  This is deliberately a Y-only rule; X
        # labels are centered under ticks and do not share a common right edge.
        right_edges = [item[2][2] for item in labels]
        expected_right = max(right_edges)
        heights = [item[2][3] - item[2][1] + 1 for item in labels]
        tolerance = max(8.0, min(16.0, statistics.median(heights) * 1.10))
        aligned = [item for item in labels if expected_right - item[2][2] <= tolerance]
        if len(aligned) >= 2:
            labels = aligned
    return labels

def _rgb_luminance(rgb):
    r, g, b = rgb[:3]
    return .2126 * r + .7152 * g + .0722 * b


def _plot_background_luminance(image, rect):
    left, top, right, bottom = map(int, rect)
    samples = []
    step_x = max(1, (right - left) // 24)
    step_y = max(1, (bottom - top) // 18)
    pixels = image.load()
    maximum_x, maximum_y = image.width - 1, image.height - 1
    for y in range(top + 2, bottom, step_y):
        yy = max(0, min(maximum_y, y))
        for x in range(left + 2, right, step_x):
            xx = max(0, min(maximum_x, x))
            samples.append(_rgb_luminance(pixels[xx, yy]))
    return statistics.median(samples) if samples else 255.0


def _axis_line_score(image, rect, axis, position, background):
    left, top, right, bottom = map(int, rect)
    score = 0.0
    count = 0
    if axis == "x":
        x = max(0, min(image.width - 1, int(round(position))))
        step = max(1, (bottom - top) // 260)
        coordinates = ((x, y) for y in range(top + 1, bottom, step))
    else:
        y = max(0, min(image.height - 1, int(round(position))))
        step = max(1, (right - left) // 320)
        coordinates = ((x, y) for x in range(left + 1, right, step))
    for x, y in coordinates:
        rgb = image.getpixel((x, y))
        chroma = max(rgb[:3]) - min(rgb[:3])
        # Grid/axis strokes are normally neutral.  Ignoring saturated pixels
        # prevents a colored data curve from attracting the tick position.
        if chroma <= 24:
            contrast = abs(_rgb_luminance(rgb) - background)
            if contrast >= 4:
                score += min(1.0, contrast / 26.0)
        count += 1
    return score / max(1, count)


def _remove_long_rules(mask):
    """Remove axis/grid strokes that pass through a numeric label crop.

    Projection counts are computed by BOX-resizing a 0/255 mask in Pillow
    rather than summing every row/column in Python. The same conservative
    88% thresholds are retained so ordinary digit ``1`` strokes survive.
    """
    if not mask or not mask[0]:
        return mask
    height, width = len(mask), len(mask[0])
    out = [bytearray(row) for row in mask]
    image = _mask_image(mask)

    if height >= 10:
        minimum = max(8, int(height * .88))
        cutoff = 255.0 * minimum / height
        columns = image.resize((width, 1), Image.Resampling.BOX).tobytes()
        for x, value in enumerate(columns):
            # BOX projection is quantized to one byte; half a level preserves
            # the old integer count boundary.
            if value + .51 >= cutoff:
                for xx in range(max(0, x - 1), min(width, x + 2)):
                    for y in range(height):
                        out[y][xx] = 0

    if width >= 14:
        minimum = max(12, int(width * .88))
        cutoff = 255.0 * minimum / width
        rows = image.resize((1, height), Image.Resampling.BOX).tobytes()
        blank = bytearray(width)
        for y, value in enumerate(rows):
            if value + .51 >= cutoff:
                for yy in range(max(0, y - 1), min(height, y + 2)):
                    out[yy] = bytearray(blank)
    return out


def _axis_edge_tick_candidates(image, rect, axis, *, _faint=False):
    """Detect short tick/grid strokes where they cross the physical axis edge.

    Full-length grid lines are useful but not required by many publication
    charts.  A short tick mark is stronger geometric evidence because it must
    actually touch the axis.  Scan only a tiny strip around the left/bottom
    spine and require a connected perpendicular stroke through the spine; this
    avoids treating arbitrary curve segments or nearby label ink as ticks.
    """
    left, top, right, bottom = map(int, rect)
    if right <= left or bottom <= top:
        return []
    if axis == 'y':
        x0, x1 = max(0, left - 10), min(image.width - 1, left + 6)
        y0, y1 = max(0, top - 3), min(image.height - 1, bottom + 3)
        if x1 <= x0 or y1 <= y0:
            return []
        mask = _binary_mask(image.crop((x0, y0, x1 + 1, y1 + 1)))
        spine = left - x0
        active = []
        strengths = {}
        for row_index, row in enumerate(mask):
            # A horizontal tick/grid stroke must reach the Y spine and extend
            # at least three pixels to either side.  The vertical spine alone
            # contributes one pixel and therefore never becomes a candidate.
            lo = max(0, spine - 10)
            hi = min(len(row) - 1, spine + 6)
            runs = _projection_bands(row[lo:hi + 1], minimum=1, merge_gap=0)
            best = 0
            for a, b in runs:
                a += lo; b += lo
                if a <= spine + 1 and b >= spine - 1:
                    outward = max(0, spine - a)
                    inward = max(0, b - spine)
                    if max(outward, inward) >= 3:
                        best = max(best, b - a + 1)
            if best:
                active.append(row_index)
                strengths[row_index] = best
        bands = _projection_bands([1 if i in strengths else 0 for i in range(len(mask))],
                                  minimum=1, merge_gap=1)
        result = []
        for a, b in bands:
            if b - a + 1 > 5:
                continue
            weighted = [(i, strengths.get(i, 0)) for i in range(a, b + 1)]
            total = sum(weight for _, weight in weighted) or 1
            center = sum(i * weight for i, weight in weighted) / total + y0
            result.append((float(center), float(max(weight for _, weight in weighted))))
        return result

    x0, x1 = max(0, left - 3), min(image.width - 1, right + 3)
    y0, y1 = max(0, bottom - 5), min(image.height - 1, bottom + 9)
    if x1 <= x0 or y1 <= y0:
        return []
    crop = image.crop((x0, y0, x1 + 1, y1 + 1))
    mask = _binary_mask(crop)
    if _faint:
        # OCR's normal threshold deliberately suppresses pale gray ink. Axis
        # marks can be only 10-20 luminance levels below a white background.
        # Use that extra evidence only in this tiny edge-contact strip, and
        # only for neutral pixels (not colored curve fragments).
        gray = crop.convert('L')
        histogram = gray.histogram()
        background = max(range(256), key=lambda value: histogram[value])
        if background < 240:
            return []
        rgb = crop.convert('RGB').load()
        pixels = gray.load()
        for y, row in enumerate(mask):
            for x in range(len(row)):
                color = rgb[x, y]
                if max(color) - min(color) <= 24 and pixels[x, y] <= background - 8:
                    row[x] = 1
    spine = bottom - y0
    height = len(mask)
    width = len(mask[0]) if height else 0
    if _faint and not any(sum(mask[y]) >= width * .55
                          for y in range(max(0, spine - 2), min(height, spine + 3))):
        return []  # Weak label strokes alone are not evidence of an axis spine.
    strengths = {}
    for x in range(width):
        column = [mask[y][x] for y in range(height)]
        lo = max(0, spine - 5)
        hi = min(height - 1, spine + 9)
        runs = _projection_bands(column[lo:hi + 1], minimum=1, merge_gap=0)
        best = 0
        for a, b in runs:
            a += lo; b += lo
            if a <= spine + 1 and b >= spine - 1:
                above = max(0, spine - a)
                below = max(0, b - spine)
                if max(above, below) >= 3:
                    best = max(best, b - a + 1)
        if best:
            strengths[x] = best
    bands = _projection_bands([1 if i in strengths else 0 for i in range(width)],
                              minimum=1, merge_gap=1)
    result = []
    for a, b in bands:
        if b - a + 1 > 5:
            continue
        weighted = [(i, strengths.get(i, 0)) for i in range(a, b + 1)]
        total = sum(weight for _, weight in weighted) or 1
        center = sum(i * weight for i, weight in weighted) / total + x0
        result.append((float(center), float(max(weight for _, weight in weighted))))
    if len(result) < 3 and not _faint:
        faint = _axis_edge_tick_candidates(image, rect, axis, _faint=True)
        if len(faint) >= 3:
            return faint
    return result


def _major_axis_edge_subset(candidates):
    """Prefer visibly longer major ticks when an axis has minor tick marks.

    Tick length is direct raster evidence.  If one short-stroke strength clearly
    dominates and at least three longer strokes exist, the longer set is the
    calibration lattice; otherwise preserve every candidate.  This avoids
    interpreting log-axis minor ticks as major numeric slots while leaving
    equal-length tick styles untouched.
    """
    candidates = list(candidates)
    if len(candidates) < 5:
        return candidates
    rounded = [int(round(strength)) for _, strength in candidates]
    counts = {}
    for strength in rounded:
        counts[strength] = counts.get(strength, 0) + 1
    base_strength, base_count = max(counts.items(), key=lambda item: (item[1], -item[0]))
    # Require a real minor-tick population, not one weaker antialiased endpoint.
    if base_count < max(2, math.ceil(len(candidates) * .35)):
        return candidates
    major = [(position, strength) for position, strength in candidates
             if strength >= base_strength + 1.5]
    if 3 <= len(major) <= len(candidates) * .72:
        return major
    return candidates


def _coherent_major_mark_subset(candidates, protected_positions=()):
    """Drop isolated axis-contact strokes when a strong major lattice exists.

    A neutral/black data curve can touch the physical axis and look exactly
    like one short tick mark.  Never prune merely from strength: fit candidate
    positions to a regular lattice and remove outliers only when at least 70%
    of five-or-more observed marks agree over most of the observed span.
    Nonuniform axes therefore pass through unchanged.
    """
    candidates = sorted((float(position), float(strength))
                        for position, strength in candidates)
    count = len(candidates)
    if count < 5:
        return candidates
    positions = [position for position, _ in candidates]
    span = positions[-1] - positions[0]
    if span < 24:
        return candidates

    hypotheses = set()
    for first, second in zip(positions, positions[1:]):
        gap = second - first
        if gap <= 3:
            continue
        for multiple in (1, 2, 3):
            spacing = gap / multiple
            if spacing >= 7:
                hypotheses.add(round(spacing, 4))
    if not hypotheses:
        return candidates

    minimum_inliers = max(4, math.ceil(count * .70))
    best = None
    for spacing in hypotheses:
        tolerance = max(2.5, spacing * .075)
        # Any true mark may serve as the lattice origin; integer slot residuals
        # are translation invariant, so trying observed origins is sufficient.
        for origin in positions:
            inliers = []
            inlier_slots = []
            residual_sum = 0.0
            strength_sum = 0.0
            for index, (position, strength) in enumerate(candidates):
                slot = round((position - origin) / spacing)
                residual = abs(position - (origin + slot * spacing))
                if residual <= tolerance:
                    inliers.append(index)
                    inlier_slots.append(int(slot))
                    residual_sum += residual
                    strength_sum += strength
            if len(inliers) < minimum_inliers:
                continue
            coverage = positions[inliers[-1]] - positions[inliers[0]]
            if coverage < span * .68:
                continue
            slot_span = max(inlier_slots) - min(inlier_slots) + 1
            density = len(set(inlier_slots)) / max(1, slot_span)
            # Reject tiny submultiples that happen to fit every observed mark
            # while leaving most lattice slots empty (e.g. 18 px fitting a
            # genuine 72 px major grid plus one curve crossing).
            if density < .60:
                continue
            quality = (len(inliers) * density, len(inliers), coverage / span,
                       density, strength_sum, -residual_sum)
            if best is None or quality > best[0]:
                best = (quality, inliers)
    if best is None:
        return candidates
    inlier_set = set(best[1])
    # Direct text geometry outranks the regular-lattice prior.  A legitimate
    # irregular DateTime/manual tick may sit between otherwise regular marks;
    # if a real label is observed at that coordinate it must never be pruned.
    protected = tuple(float(value) for value in protected_positions)
    if protected:
        spacing_hint = None
        selected_positions = [positions[index] for index in inlier_set]
        if len(selected_positions) >= 2:
            spacing_hint = _median_spacing(sorted(selected_positions))
        protect_tolerance = max(4.0, (spacing_hint or 20.0) * .16)
        for index, position in enumerate(positions):
            if index in inlier_set:
                continue
            if any(abs(position - label_position) <= protect_tolerance
                   for label_position in protected):
                inlier_set.add(index)
    # Be conservative: only discard a small minority. If several observations
    # disagree, the geometry is probably genuinely nonuniform or contaminated.
    if count - len(inlier_set) > max(2, count // 4):
        return candidates
    return [candidate for index, candidate in enumerate(candidates) if index in inlier_set]


def _merge_axis_mark_sources(primary, edge, tolerance=3.0):
    """Fuse full-line and edge-tick geometry without duplicating one stroke."""
    if not primary:
        return list(edge)
    if not edge:
        return list(primary)
    merged = list(primary)
    for position, strength in edge:
        nearest = min(range(len(merged)), key=lambda i: abs(merged[i][0] - position))
        if abs(merged[nearest][0] - position) <= tolerance:
            old_position, old_strength = merged[nearest]
            # Edge-contact evidence is spatially precise; use its coordinate
            # when it is at least moderately strong, while retaining the best
            # confidence/strength score from either source.
            selected = position if strength >= 3 else old_position
            merged[nearest] = (float(selected), max(float(old_strength), float(strength)))
        else:
            merged.append((float(position), float(strength)))
    return sorted(merged)


def _line_peak_candidates(image, rect, axis):
    """Return strong neutral horizontal/vertical line candidates in the box.

    All per-pixel chroma/contrast work and perpendicular projection are kept
    inside Pillow.  The previous implementation executed Python for every
    pixel in the projection strip, which dominated detection latency on large
    charts.  Saturated data curves are still masked out before projection.
    """
    left, top, right, bottom = map(int, rect)
    if right <= left or bottom <= top:
        return []
    background = _plot_background_luminance(image, rect)
    crop = image.crop((left, top, right + 1, bottom + 1)).convert("RGB")
    if axis == "x":
        target_height = min(128, crop.height)
        strip = crop if target_height == crop.height else crop.resize(
            (crop.width, target_height), Image.Resampling.BOX)
    else:
        target_width = min(160, crop.width)
        strip = crop if target_width == crop.width else crop.resize(
            (target_width, crop.height), Image.Resampling.BOX)

    red, green, blue = strip.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    chroma = ImageChops.subtract(maximum, minimum)
    neutral = chroma.point(_NEUTRAL_CHROMA_LUT)

    gray = strip.convert("L")
    backdrop = Image.new("L", gray.size, int(round(background)))
    contrast = ImageChops.difference(gray, backdrop).point(_LINE_STRENGTH_LUT)
    strength = ImageChops.multiply(contrast, neutral)

    if axis == "x":
        projected = strength.resize((strength.width, 1), Image.Resampling.BOX).tobytes()
        scores = [(left + index, value / 255.0) for index, value in enumerate(projected)]
    else:
        projected = strength.resize((1, strength.height), Image.Resampling.BOX).tobytes()
        scores = [(top + index, value / 255.0) for index, value in enumerate(projected)]

    values = [score for _, score in scores]
    if not values:
        return []
    baseline = statistics.median(values)
    maximum_score = max(values)
    if maximum_score <= max(.018, baseline + .006):
        return []
    threshold = max(.018, baseline + (maximum_score - baseline) * .16)
    active = [(position, score) for position, score in scores if score >= threshold]
    if not active:
        return []
    groups = [[active[0]]]
    for item in active[1:]:
        if item[0] - groups[-1][-1][0] <= 2:
            groups[-1].append(item)
        else:
            groups.append([item])
    peaks = []
    for group in groups:
        peak = max(group, key=lambda item: item[1])
        if len(group) == 1:
            center = float(peak[0])
        else:
            # A thick/anti-aliased grid stroke can occupy several columns or
            # rows. Use its contrast-weighted center rather than whichever edge
            # happens to contain the darkest pixel.
            weights = [max(1e-6, score - baseline) for _, score in group]
            center = sum(position * weight for (position, _), weight in zip(group, weights)) / sum(weights)
        peaks.append((center, float(peak[1])))
    if len(peaks) > 40:
        peaks = sorted(sorted(peaks, key=lambda item: item[1], reverse=True)[:40],
                       key=lambda item: item[0])
    return peaks


def _regular_grid_lattice(image, rect, axis):
    """Detect a regular major-tick lattice from grid/axis strokes first.

    The old detector estimated tick *positions* from OCR label centers.  That
    is fragile on Y axes because long labels and rotated titles shift text
    centers.  Here geometry is authoritative: find neutral grid lines inside
    the user box, fit the strongest regular lattice, and let OCR supply only
    the values attached to those known positions.
    """
    peaks = _line_peak_candidates(image, rect, axis)
    if len(peaks) < 2:
        return []
    left, top, right, bottom = map(float, rect)
    low, high = ((left, right) if axis == "x" else (top, bottom))
    span = max(1.0, high - low)
    max_steps = 14
    candidates = []
    for i in range(len(peaks)):
        for j in range(i + 1, len(peaks)):
            distance = peaks[j][0] - peaks[i][0]
            if distance <= 3:
                continue
            for steps in range(1, max_steps + 1):
                spacing = distance / steps
                if spacing < max(8.0, span / 40.0) or spacing > span * .72:
                    continue
                candidates.append((spacing, peaks[i][0]))
    best = None
    for spacing, origin in candidates:
        tolerance = max(2.2, spacing * .045)
        slots = {}
        for position, score in peaks:
            slot = int(round((position - origin) / spacing))
            expected = origin + slot * spacing
            residual = abs(position - expected)
            if residual > tolerance:
                continue
            rank = (score, -residual)
            current = slots.get(slot)
            if current is None or rank > current[0]:
                slots[slot] = (rank, position, score)
        if len(slots) < 2:
            continue
        ordered_slots = sorted(slots)
        coverage = slots[ordered_slots[-1]][1] - slots[ordered_slots[0]][1]
        slot_span = max(1, ordered_slots[-1] - ordered_slots[0] + 1)
        density = len(slots) / slot_span
        # Prefer models explaining many physical grid lines *without inventing
        # many missing intermediate slots*.  The previous tie-break could pick
        # a tiny submultiple (e.g. 1/6 of the real X major spacing), generating
        # 20+ fake tick slots and then triggering expensive OCR.
        score_sum = sum(item[2] for item in slots.values())
        quality = (len(slots) * density, len(slots), coverage / span, score_sum)
        if best is None or quality > best[0]:
            best = (quality, spacing, origin, slots)
    if best is None:
        return []
    _, spacing, origin, slots = best
    ordered_slots = sorted(slots)
    first_slot, last_slot = ordered_slots[0], ordered_slots[-1]
    # If the fitted lattice reaches an edge, extend by one missing slot to that
    # edge.  This recovers a major tick hidden by a curve or clipped label.
    edge_tolerance = max(4.0, spacing * .10)
    first_pos = origin + first_slot * spacing
    last_pos = origin + last_slot * spacing
    while first_pos - spacing >= low - edge_tolerance:
        first_slot -= 1
        first_pos -= spacing
    while last_pos + spacing <= high + edge_tolerance:
        last_slot += 1
        last_pos += spacing
    positions = []
    for slot in range(first_slot, last_slot + 1):
        expected = origin + slot * spacing
        if expected < low - edge_tolerance or expected > high + edge_tolerance:
            continue
        if abs(expected - low) <= edge_tolerance:
            expected = low
        elif abs(expected - high) <= edge_tolerance:
            expected = high
        nearest = min(peaks, key=lambda item: abs(item[0] - expected))
        if abs(nearest[0] - expected) <= max(2.5, spacing * .055):
            expected = nearest[0]
        positions.append(float(expected))
    # Remove accidental duplicates caused by snapping both an expected slot and
    # a boundary to the same physical line.
    unique = []
    for value in sorted(positions):
        if not unique or abs(value - unique[-1]) > 2.0:
            unique.append(value)
    return unique if len(unique) >= 2 else []


def _nearest_axis_text_mask(crop: Image.Image, axis: str):
    """Extract the text object nearest the axis from one tick-sized crop."""
    mask = _remove_long_rules(_binary_mask(crop))
    if not mask or not mask[0] or _bbox(mask) is None:
        return None, None
    height, width = len(mask), len(mask[0])
    if axis == "y":
        projection = _column_sums(mask)
        runs = _projection_bands(projection, minimum=1, merge_gap=0)
        if not runs:
            return None, None
        # Join character runs into words, then select the right-most word next
        # to the Y axis.  This works for horizontal labels; a rotated numeric
        # label normally forms one narrow run and is selected the same way.
        gap_limit = max(3, int(height * .30))
        groups = [[runs[0]]]
        for run in runs[1:]:
            if run[0] - groups[-1][-1][1] - 1 <= gap_limit:
                groups[-1].append(run)
            else:
                groups.append([run])
        group = max(groups, key=lambda item: item[-1][1])
        x0, x1 = group[0][0], group[-1][1]
        sub = _crop_mask(mask, (x0, 0, x1, height - 1))
        tight = _bbox(sub)
        if tight is None:
            return None, None
        box = (x0 + tight[0], tight[1], x0 + tight[2], tight[3])
    else:
        projection = [sum(row) for row in mask]
        runs = _projection_bands(projection, minimum=1, merge_gap=0)
        if not runs:
            return None, None
        gap_limit = max(3, int(width * .035))
        groups = [[runs[0]]]
        for run in runs[1:]:
            if run[0] - groups[-1][-1][1] - 1 <= gap_limit:
                groups[-1].append(run)
            else:
                groups.append([run])
        # X tick labels are the first text object below the plot.  A later axis
        # title is deliberately ignored.
        group = min(groups, key=lambda item: item[0][0])
        y0, y1 = group[0][0], group[-1][1]
        sub = _crop_mask(mask, (0, y0, width - 1, y1))
        tight = _bbox(sub)
        if tight is None:
            return None, None
        box = (tight[0], y0 + tight[1], tight[2], y0 + tight[3])
    return _crop_mask(mask, box), box


def _rotate_mask(mask, degrees):
    image = _mask_image(mask)
    rotated = image.rotate(degrees, expand=True, fillcolor=0,
                           resample=Image.Resampling.BICUBIC if degrees % 90 else Image.Resampling.NEAREST)
    pixels = rotated.tobytes().translate(_threshold_lut(96, dark=False))
    return [bytearray(pixels[y * rotated.width:(y + 1) * rotated.width])
            for y in range(rotated.height)]


def _expanded_slot_label(image, rect, axis, position, spacing, *, minimum_y=None, maximum_x=None):
    """Read a full word even when angled, offset, or centred on a plot edge.

    Physical grid lines remain authoritative for tick positions; a shifted text
    centre must never move the calibration point itself.
    """
    left, top, right, bottom = map(int, rect)
    half = max(14, min(96, int(spacing * .47)))
    if axis == 'y':
        depth = max(64, min(220, int((right - left) * .30)))
        box = (max(0, left - depth), max(0, int(position) - half),
               max(0, left - 2), min(image.height - 1, int(position) + half))
        if maximum_x is not None:
            box = (box[0], box[1], min(box[2], int(maximum_x)), box[3])
    else:
        depth = max(64, min(180, int((bottom - top) * .30)))
        box = (max(0, int(position) - half), min(image.height - 1, bottom + 2),
               min(image.width - 1, int(position) + half), min(image.height - 1, bottom + depth))
        if minimum_y is not None:
            box = (box[0], max(box[1], int(minimum_y)), box[2], box[3])
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    crop = image.crop((box[0], box[1], box[2] + 1, box[3] + 1))
    mask, local = _nearest_axis_text_mask(crop, axis)
    if mask is None:
        return None
    bbox = (box[0] + local[0], box[1] + local[1], box[0] + local[2], box[1] + local[3])
    return mask, bbox


def _word_alignment_score(ink, angle):
    rotated = ink.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=0)
    box = _point_lut(rotated, _threshold_lut(96, dark=False, peak=255)).getbbox()
    if box is None:
        return -100.0
    return math.log((box[2] - box[0]) / max(1, box[3] - box[1]))


def _principal_word_angle(ink):
    """Return long-axis angle and anisotropy from binary word moments."""
    width, height = ink.size
    pixels = ink.tobytes()
    count = sx = sy = sxx = syy = sxy = 0.0
    for y in range(height):
        row = pixels[y * width:(y + 1) * width]
        for x, value in enumerate(row):
            if not value:
                continue
            count += 1.0
            sx += x; sy += y; sxx += x * x; syy += y * y; sxy += x * y
    if count < 4:
        return 0.0, 0.0
    mx, my = sx / count, sy / count
    xx = sxx / count - mx * mx
    yy = syy / count - my * my
    xy = sxy / count - mx * my
    radius = math.hypot((xx - yy) * .5, xy)
    total = (xx + yy) * .5
    if total <= 1e-9:
        return 0.0, 0.0
    angle = .5 * math.degrees(math.atan2(2.0 * xy, xx - yy))
    return angle, max(0.0, min(1.0, radius / total))


def _normalise_word_angle(angle):
    return (float(angle) + 90.0) % 180.0 - 90.0


def _label_deskew_angle(labels):
    """Estimate axis text angle from the consensus of all usable words.

    Endpoint/corner crops can be much larger than real tick labels and used to
    dominate a top-3 heuristic.  Compute a PCA angle per word, select the
    densest angular cluster on the 180-degree circle, then refine only around
    that cluster.  Horizontal charts therefore stay near 0 degrees while true
    +/-15, +/-35, +/-60 and vertical labels keep their actual orientation.
    """
    observations = []
    usable_heights = [len(mask) for mask, _ in labels if mask and mask[0]]
    median_height = statistics.median(usable_heights) if usable_heights else 0
    compact = [(len(mask[0]), len(mask)) for mask, _ in labels if mask and mask[0]
               and len(mask) <= 18 and len(mask[0]) <= 18]
    if len(compact) >= max(3, math.ceil(len(usable_heights) * .70)):
        # Several tiny one-character labels do not contain enough baseline
        # information for PCA: the shape of '1' itself looks vertical.  In the
        # absence of a longer word, horizontal is the conservative orientation.
        return 0
    for mask, _ in labels:
        if not mask or not mask[0]:
            continue
        height, width = len(mask), len(mask[0])
        # A corner crop can absorb an axis line/title and become 2-3x taller
        # than every real tick word.  It must not steer the global orientation.
        if median_height and height > max(median_height * 1.65, median_height + 8):
            continue
        ink = _mask_image(mask)
        angle, anisotropy = _principal_word_angle(ink)
        if anisotropy < .12:
            continue
        mass = max(1.0, ImageStat.Stat(ink).sum[0] / 255.0)
        observations.append((_normalise_word_angle(angle), anisotropy * math.sqrt(mass), ink))
    if not observations:
        return 0

    def angular_distance(a, b):
        delta = abs(_normalise_word_angle(a - b))
        return min(delta, 180.0 - delta)

    # Find the densest local orientation. Real tick labels normally agree;
    # merged corner fragments become isolated outliers.
    best_center = max(
        observations,
        key=lambda item: sum(weight for angle, weight, _ in observations
                             if angular_distance(angle, item[0]) <= 12.0)
    )[0]
    cluster = [(angle, weight, ink) for angle, weight, ink in observations
               if angular_distance(angle, best_center) <= 12.0]
    if not cluster:
        cluster = observations

    vx = vy = 0.0
    for angle, weight, _ in cluster:
        radians = math.radians(angle * 2.0)
        vx += math.cos(radians) * weight
        vy += math.sin(radians) * weight
    seed = 0.0 if abs(vx) + abs(vy) < 1e-9 else .5 * math.degrees(math.atan2(vy, vx))
    seed = _normalise_word_angle(seed)
    if abs(seed) <= 3.0:
        return 0

    # Refine using the most informative cluster members only.
    refine = [ink for _, _, ink in sorted(cluster, key=lambda item: item[1], reverse=True)[:3]]
    centre = int(round(seed))
    candidates = [_normalise_word_angle(centre + offset) for offset in range(-4, 5)]
    angle = max(candidates, key=lambda value: statistics.median(_word_alignment_score(ink, value)
                                                                 for ink in refine))
    return int(round(_normalise_word_angle(angle)))

def _transformed_label_plan(image, rect, axis, lattice):
    if not 3 <= len(lattice) <= 18:
        return None
    spacing = _median_spacing(lattice)
    if not spacing:
        return None
    labels = {position: label for position in lattice
              if (label := _expanded_slot_label(image, rect, axis, position, spacing)) is not None}
    if len(labels) < 3:
        return None
    if axis == 'x':
        # The bottom Y label can protrude below the plot and precede the first
        # X word. Use the other X words to reject that *left-of-axis* fragment,
        # without globally clipping legitimate long/angled endpoint labels.
        row = statistics.median(bbox[1] for _, bbox in labels.values())
        for position, (_, bbox) in tuple(labels.items()):
            if bbox[2] < rect[0] and bbox[1] < row - 5:
                replacement = _expanded_slot_label(image, rect, axis, position, spacing, minimum_y=row - 3)
                if replacement is not None:
                    labels[position] = replacement
    else:
        # Conversely, a wide bottom-Y crop can absorb the first X word. Only
        # trim a corner crop that protrudes into the axis gap beyond the common
        # right-aligned Y column; do not clip long vertical Y words globally.
        column = statistics.median(bbox[2] for _, bbox in labels.values())
        for position, (_, bbox) in tuple(labels.items()):
            if bbox[2] >= rect[0] - 4 and bbox[2] > column + 5 and bbox[3] > rect[3] + 8:
                replacement = _expanded_slot_label(image, rect, axis, position, spacing, maximum_x=column + 3)
                if replacement is not None:
                    labels[position] = replacement
    angle = _label_deskew_angle(list(labels.values()))
    cache = {}

    def masks(position):
        if position not in cache:
            item = labels.get(position)
            if item is None:
                cache[position] = []
            else:
                mask, bbox = item
                ink = _mask_image(mask)
                # Permit a few degrees of label-to-label baseline jitter without
                # multiplying OCR/template searches by a large angle sweep.
                local = max(range(angle - 3, angle + 4),
                            key=lambda value: _word_alignment_score(ink, value))
                upright = _rotate_mask(mask, local)
                tight = _bbox(upright)
                if tight is not None:
                    upright = _crop_mask(upright, tight)
                cache[position] = [(angle, upright, bbox),
                                   (angle + 180, _rotate_mask(upright, 180), bbox)]
        return cache[position]

    return angle, masks


def _slot_oriented_masks(image, rect, axis, position, spacing):
    """Return one tick label as 0/90/270-degree numeric-reading masks."""
    left, top, right, bottom = map(int, rect)
    plot_width, plot_height = right - left, bottom - top
    half = max(10, min(30, int(round(spacing * .28))))
    if axis == "y":
        depth = min(left, max(42, min(160, int(plot_width * .24))))
        # Do not let the bottom Y-label crop absorb the first row of X labels
        # (or vice versa at the top).  A small overshoot still preserves glyph
        # descenders when the tick label is centred exactly on the box edge.
        box = (max(0, left - depth), max(0, top - 6, int(round(position)) - half),
               max(0, left - 2), min(image.height - 1, bottom + 6,
                                     int(round(position)) + half))
    else:
        depth = min(image.height - bottom - 1, max(30, min(130, int(plot_height * .24))))
        box = (max(0, int(round(position)) - half), min(image.height - 1, bottom + 2),
               min(image.width - 1, int(round(position)) + half),
               min(image.height - 1, bottom + depth))
    if box[2] <= box[0] or box[3] <= box[1]:
        return []
    crop = image.crop((box[0], box[1], box[2] + 1, box[3] + 1))
    mask, local_box = _nearest_axis_text_mask(crop, axis)
    if mask is None or local_box is None:
        return []
    abs_box = (box[0] + local_box[0], box[1] + local_box[1],
               box[0] + local_box[2], box[1] + local_box[3])
    result = []
    for degrees in (0, 90, 270):
        oriented = mask if degrees == 0 else _rotate_mask(mask, degrees)
        result.append((degrees, oriented, abs_box))
    return result


def _slot_numeric_candidates(image, rect, axis, position, spacing):
    """OCR one known tick slot in horizontal and vertical text orientations."""
    candidates = []
    for degrees, oriented, abs_box in _slot_oriented_masks(
            image, rect, axis, position, spacing):
        reading = _ocr_numeric(oriented)
        if reading is None:
            continue
        text, value, confidence = reading
        # Penalize rotated interpretations slightly; when the label is truly
        # vertical their OCR confidence still wins across the complete axis.
        if degrees:
            confidence *= .97
        candidates.append((degrees, text, value, confidence, abs_box))
    return candidates


def _normalize_word_mask(mask, height=28):
    box = _bbox(mask)
    if box is None:
        return None
    image = _mask_image(_crop_mask(mask, box)).convert("L")
    width, source_height = image.size
    if width <= 0 or source_height <= 0:
        return None
    target_width = max(1, int(round(width * height / source_height)))
    return image.resize((target_width, height), Image.Resampling.BILINEAR)


_WORD_TEMPLATE_LUT = _threshold_lut(193, peak=255)


@lru_cache(maxsize=8192)
def _template_text_bbox(index: int, text: str):
    """Cache immutable FreeType text bounds for template composition."""
    fonts = _template_fonts()
    if not 0 <= index < len(fonts):
        return None
    try:
        return tuple(fonts[index].getbbox(text))
    except Exception:
        return None


@lru_cache(maxsize=16384)
def _template_prefix_advance(index: int, prefix: str):
    """Cache exact FreeType prefix advance used by composed word templates."""
    fonts = _template_fonts()
    if not 0 <= index < len(fonts):
        return None
    try:
        return float(fonts[index].getlength(prefix))
    except Exception:
        return None


@lru_cache(maxsize=256)
def _binary_template_glyph(index: int, char: str):
    """Return one thresholded glyph plus its font-space bbox.

    Numeric labels repeatedly render the same dozen glyphs in many different
    values.  Caching per-glyph rasters avoids thousands of cold FreeType word
    renders while preserving the exact binary shape used by the old renderer.
    """
    fonts = _template_fonts()
    if not 0 <= index < len(fonts):
        return None
    font = fonts[index]
    try:
        box = _template_text_bbox(index, char)
        if box is None:
            return None
        width, height = max(1, box[2] - box[0]), max(1, box[3] - box[1])
        image = Image.new("L", (width, height), 255)
        ImageDraw.Draw(image).text((-box[0], -box[1]), char, font=font, fill=0)
        return box, _point_lut(image, _WORD_TEMPLATE_LUT)
    except Exception:
        return None


def _composed_numeric_word(index: int, text: str, *, allow_hyphen=False):
    """Compose a numeric word from cached glyphs when layout is stable.

    Digits and decimal/grouping/scientific punctuation in the supported fonts
    are tabular enough that the composed thresholded raster is pixel-identical
    to direct rendering.  A minus/hyphen is deliberately excluded because a
    few fonts apply pair-specific kerning around it; those labels keep the
    exact legacy FreeType path.
    """
    if not text or ('-' in text and not allow_hyphen):
        return None
    fonts = _template_fonts()
    if not 0 <= index < len(fonts):
        return None
    try:
        placements = []
        prefix = ''
        for char in text:
            glyph = _binary_template_glyph(index, char)
            if glyph is None:
                return None
            char_box, char_ink = glyph
            # Exact prefix advances preserve FreeType kerning. The union of
            # positioned glyph boxes is the ink-space word bbox, so composed
            # numeric/date templates do not need a separate full-word
            # ``font.getbbox(text)`` call at all.
            advance = _template_prefix_advance(index, prefix)
            if advance is None:
                return None
            placements.append((advance, char_box, char_ink))
            prefix += char
        if not placements:
            return None
        left = min(advance + box[0] for advance, box, _ in placements)
        top = min(box[1] for _, box, _ in placements)
        right = max(advance + box[2] for advance, box, _ in placements)
        bottom = max(box[3] for _, box, _ in placements)
        width = max(1, int(math.ceil(right - left)))
        height = max(1, int(math.ceil(bottom - top)))
        ink = Image.new("L", (width, height), 0)
        for advance, char_box, char_ink in placements:
            x = int(round(advance + char_box[0] - left))
            y = int(round(char_box[1] - top))
            ink.paste(255, (x, y), char_ink)
        bounds = ink.getbbox()
        return ink.crop(bounds) if bounds is not None else None
    except Exception:
        return None


def _render_binary_word(index: int, text: str):
    """Render one thresholded template, preferring the glyph cache path."""
    # ISO dates use two literal hyphens between tabular digit groups. Across
    # the supported template-font bank, composing these cached glyphs with the
    # exact prefix advance is pixel-identical to direct FreeType rendering.
    # Keep arbitrary signed numeric strings on the conservative legacy path.
    iso_date = (len(text) == 10 and text[4] == '-' and text[7] == '-' and
                (text[:4] + text[5:7] + text[8:]).isdigit())
    composed = _composed_numeric_word(index, text, allow_hyphen=iso_date)
    if composed is not None:
        return composed
    fonts = _template_fonts()
    if not 0 <= index < len(fonts):
        return None
    font = fonts[index]
    try:
        box = _template_text_bbox(index, text)
        if box is None:
            return None
        image = Image.new("L", (max(12, box[2] - box[0] + 10),
                                max(16, box[3] - box[1] + 10)), 255)
        ImageDraw.Draw(image).text((5 - box[0], 5 - box[1]), text, font=font, fill=0)
        ink = _point_lut(image, _WORD_TEMPLATE_LUT)
        bounds = ink.getbbox()
        return ink.crop(bounds) if bounds is not None else None
    except Exception:
        return None


@lru_cache(maxsize=4096)
def _word_templates(text: str):
    templates = []
    # Engineering charts also use bold/serif labels. Sans-only templates reject
    # these particularly often after a screenshot has been stretched.
    fonts = _template_fonts()
    for index in (0, 1, 5, 6, 7):
        if index >= len(fonts):
            continue
        ink = _render_binary_word(index, text)
        if ink is not None:
            templates.append(ink.resize(
                (max(1, int(round(ink.width * 28 / ink.height))), 28),
                Image.Resampling.BILINEAR))
    return tuple(templates)


@lru_cache(maxsize=4096)
def _quick_word_templates(text: str):
    """Two-face template bank used to rank bounded OCR hypotheses cheaply."""
    templates = []
    fonts = _template_fonts()
    for index in _template_font_indexes()[:2]:
        if index >= len(fonts):
            continue
        ink = _composed_numeric_word(index, text, allow_hyphen=True)
        if ink is None:
            ink = _render_binary_word(index, text)
        if ink is not None:
            templates.append(ink.resize(
                (max(1, int(round(ink.width * 28 / ink.height))), 28),
                Image.Resampling.BILINEAR))
    return tuple(templates)


def _normalized_quick_word_score(observed, text: str):
    if observed is None:
        return 9.0
    best = 9.0
    observed_aspect = observed.width / max(1.0, observed.height)
    for template in _quick_word_templates(text):
        template_aspect = template.width / max(1.0, template.height)
        aspect_penalty = .12 * max(0.0, abs(math.log(max(1e-3, observed_aspect)
                                                    / max(1e-3, template_aspect)))
                                   - math.log(1.6))
        resized = template.resize(observed.size, Image.Resampling.BILINEAR)
        best = min(best, _gray_difference(observed, resized) + aspect_penalty)
    return best


def _normalized_word_template_score(observed, text: str):
    if observed is None:
        return 9.0
    best = 9.0
    observed_aspect = observed.width / max(1.0, observed.height)
    for template in _word_templates(text):
        template_aspect = template.width / max(1.0, template.height)
        # Resizing a chart need not preserve its aspect ratio. Compare glyph
        # shapes after affine resizing, with a soft penalty outside a modest
        # distortion range rather than rejecting the entire Y sequence.
        aspect_penalty = .12 * max(0.0, abs(math.log(max(1e-3, observed_aspect)
                                                    / max(1e-3, template_aspect)))
                                   - math.log(1.6))
        resized = template.resize(observed.size, Image.Resampling.BILINEAR)
        # Pillow computes differences in C. A Python loop here used millions of
        # operations per failed axis and was repeated on the enlarged Y retry.
        mismatch = _gray_difference(observed, resized)
        best = min(best, mismatch + aspect_penalty)
    return best


def _gray_difference(first, second):
    difference = ImageChops.difference(first, second)
    # Sum the L histogram in C-backed iterators instead of ImageStat's Python
    # loop. Keep the exact mean, not a rounded 1-pixel resize.
    total = sum(map(mul, range(256), difference.histogram()))
    return total / (difference.width * difference.height) / 255.0


def _word_template_score(mask, text: str):
    """Compare an entire numeric label to rendered font templates."""
    return _normalized_word_template_score(_normalize_word_mask(mask), text)


def _same_numeric_value(first, second):
    """Return True when two OCR hypotheses represent the same number.

    Threshold/contrast retries frequently produce textual variants such as
    ``1``/``1.0`` or tiny floating round-off differences.  Consensus should
    combine those readings rather than treating them as competing labels.
    """
    if not (math.isfinite(first) and math.isfinite(second)):
        return False
    return abs(first - second) <= max(1e-10, abs(first) * 1e-8, abs(second) * 1e-8)


def _consensus_numeric_reading(readings):
    """Choose one numeric OCR reading from independent image hypotheses.

    The previous detector selected the single largest confidence.  On tiny
    labels one aggressive threshold can then beat three moderate but mutually
    consistent readings (for example ``1.2`` becoming ``3.2``).  Cluster equal
    numeric values and reward repeatability across native, enlarged and local
    contrast masks.  A lone strong reading still wins when there is no real
    consensus, so normal clean labels keep their existing behavior.
    """
    usable = [(str(text), float(value), float(confidence))
              for text, value, confidence in readings
              if math.isfinite(value) and math.isfinite(confidence)]
    if not usable:
        return None
    groups = []
    for reading in usable:
        for group in groups:
            if _same_numeric_value(reading[1], group[0][1]):
                group.append(reading)
                break
        else:
            groups.append([reading])

    ranked = []
    for group in groups:
        votes = len(group)
        max_conf = max(item[2] for item in group)
        mean_conf = sum(item[2] for item in group) / votes
        # Squared confidence prevents many very weak masks from overwhelming a
        # clean native read; the repeat bonus rewards stability across genuinely
        # different threshold/source hypotheses.
        strength = sum(item[2] * item[2] for item in group) + .16 * max(0, votes - 1)
        # Preserve the most visually explicit representation when equal values
        # occur as 1 and 1.0, provided its confidence is close to the best.
        near_best = [item for item in group if item[2] >= max_conf - .06]
        chosen = max(near_best, key=lambda item: (len(item[0]), item[2]))
        ranked.append((strength, votes, mean_conf, max_conf, chosen, group))
    ranked.sort(key=lambda item: item[:4], reverse=True)
    winner = ranked[0]
    strength, votes, mean_conf, max_conf, chosen, _ = winner

    # When two distinct values remain almost tied, expose that uncertainty in
    # confidence rather than promoting the first arbitrary threshold result.
    ambiguity = 0.0
    if len(ranked) > 1:
        runner = ranked[1]
        margin = strength - runner[0]
        scale = max(strength, runner[0], 1e-6)
        relative_margin = margin / scale
        if relative_margin < .14:
            ambiguity = (.14 - relative_margin) * 1.8
    consensus_bonus = min(.10, .035 * max(0, votes - 1))
    confidence = min(.98, .68 * max_conf + .32 * mean_conf + consensus_bonus)
    confidence = max(.0, confidence - ambiguity)
    return chosen[0], chosen[1], confidence


def _read_scientific_glyph_word(mask):
    """Fast glyph-level reader for labels such as ``1e-3`` or ``2.5E6``."""
    bounds = _bbox(mask)
    if bounds is None:
        return None
    tight = _crop_mask(mask, bounds)
    height = len(tight)
    if height < 5:
        return None
    components = sorted(_components(tight), key=lambda item: (item[0], item[1]))
    if not 3 <= len(components) <= 10:
        return None

    classified = []
    e_candidates = []
    for index, (x0, y0, x1, y1, area) in enumerate(components):
        gh, gw = y1 - y0 + 1, x1 - x0 + 1
        glyph = _crop_mask(tight, (x0, y0, x1, y1))
        tiny = gh <= max(2, height * .35)
        if tiny:
            classified.append((index, 'tiny', None, None, glyph, (x0, y0, x1, y1)))
            continue
        # Cheap prefilter: ordinary digits score poorly against e/E.  Avoid the
        # ten-digit classifier entirely unless this component first looks like
        # a plausible exponent marker.
        e_ranked = sorted((_glyph_score(glyph, char), char) for char in 'eE')
        e_score, e_char = e_ranked[0]
        if e_score <= .22:
            digit_ranked = sorted((_glyph_score(glyph, char), char) for char in _NUMERIC_CHARS)
            digit_score, digit = digit_ranked[0]
            if digit_score - e_score >= .042:
                e_candidates.append((e_score, index, e_char, digit_score))
            classified.append((index, 'full', (digit, digit_score), (e_char, e_score),
                               glyph, (x0, y0, x1, y1)))
        else:
            classified.append((index, 'full', None, (e_char, e_score),
                               glyph, (x0, y0, x1, y1)))
    if not e_candidates:
        return None
    e_candidates.sort()
    e_score, e_index, e_char, digit_score = e_candidates[0]
    if len(e_candidates) > 1 and e_candidates[1][0] - e_score < .035:
        return None

    mantissa = []
    exponent = []
    errors = [e_score]
    seen_e = False
    for index, kind, digit_info, _, glyph, box in classified:
        if index == e_index:
            seen_e = True
            continue
        x0, y0, x1, y1 = box
        gh, gw = y1 - y0 + 1, x1 - x0 + 1
        target = exponent if seen_e else mantissa
        if kind == 'tiny':
            if seen_e:
                # A detached horizontal component immediately after e/E is an
                # exponent sign.  Tiny exponent decimal points are invalid.
                if not exponent and gw >= max(2, gh * 1.4):
                    exponent.append('-')
                    errors.append(.08)
                else:
                    return None
            else:
                center_y = (y0 + y1) / 2 / max(1, height)
                if not mantissa and gw >= max(2, gh * 1.4):
                    mantissa.append('-')
                    errors.append(.08)
                elif mantissa and center_y >= .50 and '.' not in mantissa:
                    mantissa.append('.')
                    errors.append(.06)
                else:
                    return None
            continue

        if digit_info is None:
            digit_ranked = sorted((_glyph_score(glyph, char), char) for char in _NUMERIC_CHARS)
            score, digit = digit_ranked[0]
        else:
            digit, score = digit_info
        if seen_e and not exponent:
            # Support a connected '+'/'-' sign when it is visibly a better
            # match than a digit.  Most minus signs are handled as tiny above.
            sign_ranked = sorted((_glyph_score(glyph, sign), sign) for sign in '+-')
            sign_score, sign = sign_ranked[0]
            if sign_score <= .24 and sign_score + .045 < score:
                exponent.append(sign)
                errors.append(sign_score)
                continue
        if score > .34:
            return None
        target.append(digit)
        errors.append(score)

    mantissa_text = ''.join(mantissa)
    exponent_text = ''.join(exponent)
    if (not mantissa_text or mantissa_text in {'-', '.', '-.'}
            or not exponent_text or exponent_text in {'+', '-'}):
        return None
    try:
        mantissa_value = float(mantissa_text)
        exponent_value = int(exponent_text)
    except ValueError:
        return None
    if abs(exponent_value) > 99:
        return None
    try:
        value = mantissa_value * (10.0 ** exponent_value)
    except OverflowError:
        return None
    if not math.isfinite(value):
        return None
    text = f"{mantissa_text}{e_char}{exponent_text}"
    mean_error = sum(errors) / max(1, len(errors))
    confidence = max(.52, min(.96, 1.0 - 1.55 * mean_error))
    return text, float(value), confidence


def _read_scientific_word(mask, ordinary=None):
    """Recognize compact ``mantissa e exponent`` labels from whole-word pixels.

    The digit-only glyph parser naturally turns ``1e-3`` into shapes such as
    ``10.3``.  Run this bounded whole-word matcher only on wide, uncertain
    labels.  It never uses neighbouring tick values, so a scientific reading is
    still independent image evidence and may safely participate in scale fit.
    """
    glyph_reading = _read_scientific_glyph_word(mask)
    if glyph_reading is not None and glyph_reading[2] >= .58:
        return glyph_reading
    bounds = _bbox(mask)
    if bounds is None:
        return None
    tight = _crop_mask(mask, bounds)
    height = len(tight)
    width = len(tight[0]) if tight else 0
    if height < 5 or width / max(1.0, height) < 1.75:
        return None
    if ordinary is None:
        ordinary = _ocr_numeric(tight)
    if ordinary is not None and ordinary[2] >= .88:
        # A clean ordinary number is much more likely to be exactly that; this
        # also prevents expensive scientific matching on 1500/2000/etc.
        return None

    mantissas = {1.0, 2.0, 5.0}
    raw_text = ordinary[0] if ordinary is not None else ""
    leading = next((char for char in raw_text if char.isdigit() and char != '0'), None)
    if leading is not None:
        mantissas.add(float(leading))
    digits = ''.join(char for char in raw_text[:3] if char.isdigit())
    if len(digits) >= 2 and digits[0] != '0' and digits[1] != '0':
        mantissas.add(int(digits[:2]) / 10.0)

    exponents = set()
    # A false decimal produced from the exponent sign is useful evidence:
    # 1e-3 commonly becomes 10.3 in digit-only OCR.  Include larger exponents
    # near that observed suffix without searching an unbounded range.
    if '.' in raw_text:
        tail = ''.join(char for char in raw_text.rsplit('.', 1)[-1] if char.isdigit())
        if tail:
            magnitude = min(12, int(tail[:2]))
            for delta in (-1, 0, 1):
                if magnitude + delta >= 0:
                    exponents.add(magnitude + delta)
                    exponents.add(-(magnitude + delta))
            exponents.add(0)
    if not exponents:
        # e/E often becomes a digit while its exponent survives as the last
        # glyph (1e6 -> something like 166). Probe around that suffix plus the
        # most common small exponents rather than scanning -12..12 blindly.
        trailing = ''.join(char for char in raw_text[-2:] if char.isdigit())
        exponents.update((-2, -1, 0, 1, 2))
        if trailing:
            magnitude = min(12, int(trailing[-1]))
            for delta in (-1, 0, 1):
                if magnitude + delta >= 0:
                    exponents.add(magnitude + delta)
                    exponents.add(-(magnitude + delta))

    observed = _normalize_word_mask(tight)
    if observed is None:
        return None
    candidates = []
    for mantissa in sorted(mantissas):
        mantissa_text = "{:.6g}".format(mantissa)
        for exponent in sorted(exponents):
            value = mantissa * (10.0 ** exponent)
            if not math.isfinite(value):
                continue
            forms = [f"{mantissa_text}e{exponent}"]
            if abs(mantissa - 1.0) <= 1e-12:
                forms.extend((f"10^{exponent}", f"10^{str(exponent).replace('-', '−')}"))
            candidates.append((mantissa_text, exponent, value, tuple(forms)))

    def rank_forms(score_fn, pool, extra_upper=False):
        ranked = []
        for mantissa_text, exponent, value, forms in pool:
            texts = forms + ((f"{mantissa_text}E{exponent}",) if extra_upper else ())
            score, text = min((score_fn(observed, text), text)
                              for text in texts)
            ranked.append((score, text, value))
        ranked.sort(key=lambda item: item[0])
        return ranked

    quick = rank_forms(_normalized_quick_word_score, candidates, False)
    if not quick:
        return None
    best_score, best_text, best_value = quick[0]
    second_score = next((score for score, _, value in quick[1:]
                         if not _same_numeric_value(value, best_value)), 9.0)
    # A very clear two-font match needs no larger font bank. Otherwise refine
    # only the best few *numeric values*, not the entire scientific family.
    if not (best_score <= .155 and second_score - best_score >= .026):
        shortlist_values = []
        for _, _, value in quick:
            if not any(_same_numeric_value(value, existing) for existing in shortlist_values):
                shortlist_values.append(value)
            if len(shortlist_values) >= 6:
                break
        shortlist = [candidate for candidate in candidates
                     if any(_same_numeric_value(candidate[2], value) for value in shortlist_values)]
        ranked = rank_forms(_normalized_word_template_score, shortlist, True)
        if not ranked:
            return None
        best_score, best_text, best_value = ranked[0]
        second_score = next((score for score, _, value in ranked[1:]
                             if not _same_numeric_value(value, best_value)), 9.0)
    if best_score > .19 or second_score - best_score < .022:
        return None
    confidence = max(.48, min(.94, 1.0 - 1.65 * best_score + min(.06, second_score - best_score)))
    return best_text, float(best_value), confidence


def _scientific_reading_beats(mask, scientific, ordinary):
    if scientific is None:
        return False
    if ordinary is None:
        return True
    if _same_numeric_value(scientific[1], ordinary[1]):
        return scientific[2] >= ordinary[2]
    observed = _normalize_word_mask(mask)
    if observed is None:
        return False
    scientific_score = _normalized_word_template_score(observed, scientific[0])
    ordinary_score = _normalized_word_template_score(observed, ordinary[0])
    # Require a decisive whole-word visual win.  This prevents context or the
    # scientific candidate family from relabelling a legitimate ordinary tick.
    return scientific_score <= .19 and scientific_score + .04 <= ordinary_score


@lru_cache(maxsize=2048)
def _independent_digit_scores(width, height, pixels):
    """Rank glyph shapes without assuming values or spacing on another tick."""
    observed = Image.frombytes('L', (width, height), pixels)
    scores = []
    resized_by_size = {}
    for char in _NUMERIC_CHARS:
        best = 1.0
        for reference in _tight_glyph_templates(char):
            if reference.size not in resized_by_size:
                resized_by_size[reference.size] = observed.resize(reference.size, Image.Resampling.BILINEAR)
            resized = resized_by_size[reference.size]
            score = _gray_difference(resized, reference)
            best = min(best, score)
        scores.append((best, char))
    return tuple(sorted(scores)[:4])


@lru_cache(maxsize=10)
def _tight_glyph_templates(char):
    return tuple(template.crop(template.getbbox()).convert('L') for template, _ in _glyph_templates(char)
                 if template.getbbox() is not None)


def _independent_word_candidates(mask, *, cut_prior=False, width_multiplier=1.0):
    bounds = _bbox(mask)
    if bounds is None:
        return []
    mask = _crop_mask(mask, bounds)
    # Threshold and font-hint retries often revisit the exact same word pixels.
    # Share segmentation/beam work, never an adjacent label's numeric value.
    return list(_cached_word_candidates(len(mask[0]), len(mask), b''.join(mask),
                                        cut_prior, width_multiplier))


@lru_cache(maxsize=1024)
def _cached_word_candidates(width, height, pixels, cut_prior, width_multiplier):
    mask = [bytearray(pixels[y * width:(y + 1) * width]) for y in range(height)]
    components = _components(mask)
    if height <= 8:
        widths = sorted(x1 - x0 + 1 for x0, y0, x1, y1, area in components
                        if y1 - y0 + 1 >= height * .60
                        and height * .4 <= x1 - x0 + 1 < height * 1.8)
    else:
        widths = sorted(x1 - x0 + 1 for x0, y0, x1, y1, area in components
                        if y1 - y0 + 1 >= height * .60
                        and height * .32 <= x1 - x0 + 1 <= height * 1.10)
    # Connected antialiased groups such as ``000`` are common in comma-
    # formatted labels.  When no standalone normal-width digit is available,
    # a 0.72*height fallback under-counts a three-digit group as two.  Printed
    # numeric glyphs at these raster sizes are typically ~0.58-0.66*height.
    # Use that range as the fallback, while retaining measured widths when at
    # least two independent digit components exist.
    if height <= 8:
        typical_width = (statistics.median(widths[:max(1, (len(widths) + 1) // 2)])
                         if widths else height * .72)
    else:
        typical_width = (statistics.median(widths[:max(1, (len(widths) + 1) // 2)])
                         if len(widths) >= 2 else height * .62)
        typical_width = max(typical_width, height * .58)
    boxes = []
    for x0, y0, x1, y1, area in components:
        gh, gw = y1 - y0 + 1, x1 - x0 + 1
        if gh <= max(2, height * .35):
            if (y0 + y1) / 2 >= height * .65 and gw <= height * .65:
                # Detached serif/antialias pixels under a digit are not decimal
                # points. A genuine point occupies the gap BETWEEN glyphs.
                overlaps_digit = any(a <= x1 and c >= x0 and d - b + 1 >= height * .6
                                     for a, b, c, d, _ in components)
                if not overlaps_digit:
                    boxes.append((x0, y0, x1, y1, '.'))
            elif gw >= gh * 1.5 and gw >= height * .28:
                if height <= 8:
                    boxes.append((x0, y0, x1, y1, '-'))
                # A numeric minus is a leading sign. Thin horizontal remnants
                # at the right edge are tick/grid strokes, not a trailing '-'.
                elif x0 <= max(3, int(round(height * .80))):
                    boxes.append((x0, y0, x1, y1, '-'))
                elif x1 >= width - 1 - max(3, int(round(height * .55))):
                    continue
                else:
                    return ()
            elif area > 1:
                # A one-pixel tick/grid remnant or Smart-Region guide can sit
                # just beyond the last digit.  It is not punctuation and must
                # not invalidate an otherwise clean numeric word.  Ignore only
                # edge fragments; an interior unknown component still rejects
                # the word to avoid silently dropping real glyph information.
                main = [(a, b, c, d) for a, b, c, d, ar in components
                        if d - b + 1 >= height * .60]
                nearest = min((min(abs(x1 - a), abs(c - x0)) for a, b, c, d in main),
                              default=0)
                edge_margin = max(3, int(round(height * .55)))
                at_edge = x0 <= edge_margin or x1 >= width - 1 - edge_margin
                if height > 8 and at_edge and nearest >= max(2, height * .18):
                    continue
                return ()
            continue
        # Ignore a short narrow component isolated at the extreme right/left;
        # this is commonly a clipped tick/grid/selection stroke. Real exponent
        # glyphs are not discarded here because they normally sit next to e/E
        # rather than beyond a full-digit gap at the word edge.
        if height > 8 and gh < height * .60 and gw <= height * .35:
            edge_margin = max(3, int(round(height * .55)))
            at_edge = x0 <= edge_margin or x1 >= width - 1 - edge_margin
            main = [(a, b, c, d) for a, b, c, d, ar in components
                    if d - b + 1 >= height * .60]
            nearest = min((min(abs(x1 - a), abs(c - x0)) for a, b, c, d in main),
                          default=0)
            if at_edge and nearest >= max(2, height * .18):
                continue
        # A stretched single 4/0 is not two digits. Split only genuinely joined
        # wide components, using widths measured in this word, not an axis step.
        if gw > height * 1.2 and gw > typical_width * 1.65:
            count = max(2, min(8, round(gw / max(1, typical_width * width_multiplier))))
            sub = _crop_mask(mask, (x0, y0, x1, y1))
            projection = _column_sums(sub)
            cuts = [0]
            for index in range(1, count):
                target = round(gw * index / count)
                radius = max(1, round(gw / count * .22))
                low, high = max(cuts[-1] + 1, target - radius), min(gw - 1, target + radius)
                # Anti-aliased slanted digits often touch along a low row. A
                # pure minimum can cut two pixels into an 8/0; retain the
                # measured glyph-width prior within this word, not an axis step.
                cuts.append(min(range(low, high + 1),
                                key=lambda x: projection[x] + (abs(x - target) * height * .15 if cut_prior else 0))
                            if low <= high else target)
            cuts.append(gw)
            boxes.extend((x0 + a, y0, x0 + b - 1, y1, '') for a, b in zip(cuts, cuts[1:]) if b > a)
        else:
            boxes.append((x0, y0, x1, y1, ''))
    beam = [(0.0, '')]
    digits = 0
    for x0, y0, x1, y1, punctuation in sorted(boxes):
        if punctuation:
            beam = [(score, text + punctuation) for score, text in beam]
            continue
        glyph = _mask_image(_crop_mask(mask, (x0, y0, x1, y1)))
        choices = _independent_digit_scores(glyph.width, glyph.height, glyph.tobytes())
        beam = sorted((score + error, text + char) for score, text in beam for error, char in choices)[:16]
        digits += 1
    candidates = []
    if digits:
        for error, text in beam:
            if '-' in text[1:] or len(text) > 24:
                continue
            for rendered, value in _numeric_text_hypotheses(text):
                if math.isfinite(value):
                    candidates.append((rendered, value, error / digits))
    # De-duplicate identical rendered/value hypotheses while preserving beam
    # order.  This keeps the punctuation ambiguity bounded on long comma labels.
    unique = []
    seen = set()
    for item in candidates:
        key = (item[0], round(float(item[1]), 12))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return tuple(unique)


@lru_cache(maxsize=4096)
def _small_word_templates(text, height):
    templates = []
    size = max(8, min(30, round(height / .72)))
    for index, font in enumerate(_template_fonts()):
        if index not in (0, 1, 5, 6, 7):
            continue
        for points in ((size - 1, size, size + 1) if index < 2 else (size,)):
            variant = _sized_template_font(index, points)
            box = variant.getbbox(text)
            image = Image.new('L', (max(1, box[2] - box[0] + 4), max(1, box[3] - box[1] + 4)), 255)
            ImageDraw.Draw(image).text((2 - box[0], 2 - box[1]), text, fill=0, font=variant)
            for threshold in (128, 193):
                ink = _point_lut(image, _threshold_lut(threshold, peak=255))
                bounds = ink.getbbox()
                if bounds is not None:
                    templates.append(ink.crop(bounds))
    return tuple(templates)


@lru_cache(maxsize=256)
def _sized_template_font(index, size):
    font = _template_fonts()[index]
    return font.font_variant(size=size) if hasattr(font, 'font_variant') else font


def _small_word_score(observed, text, height):
    best = 1.0
    aspect = observed.width / max(1, observed.height)
    for template in _small_word_templates(text, height):
        penalty = .12 * max(0, abs(math.log(aspect / (template.width / template.height))) - math.log(1.6))
        resized = template.resize(observed.size, Image.Resampling.BILINEAR)
        error = _gray_difference(observed, resized)
        best = min(best, error + penalty)
    return best


def _read_independent_word(mask):
    """Read one printed number; no axis model or neighbouring values are inputs."""
    bounds = _bbox(mask)
    if bounds is None:
        return None
    tight = _crop_mask(mask, bounds)
    return _cached_independent_word(len(tight[0]), len(tight), b''.join(tight))


def _read_probe_word(mask):
    """Very cheap first-pass numeric OCR with no whole-word font rendering.

    Cache the tight raster because the same slot can be visited by the physical
    word pass, slot recovery and a bounded retry.  This removes duplicate glyph
    segmentation/classification without sharing any value between different
    pixels or tick positions.
    """
    bounds = _bbox(mask)
    if bounds is None:
        return None
    tight = _crop_mask(mask, bounds)
    return _cached_probe_word(len(tight[0]), len(tight), b''.join(tight))


@lru_cache(maxsize=2048)
def _cached_probe_word(width, height, pixels):
    mask = [bytearray(pixels[y * width:(y + 1) * width]) for y in range(height)]
    candidates = _independent_word_candidates(mask)
    native = _ocr_numeric(mask)
    if candidates:
        candidates.sort(key=lambda item: item[2])
        best_text, best_value, best_error = candidates[0]
        second_error = next((error for text, value, error in candidates[1:]
                             if value != best_value), 1.0)
        if native is not None:
            native_match = next((item for item in candidates
                                 if abs(item[1] - native[1]) <= max(1e-12, abs(native[1]) * 1e-12)), None)
            if (native_match is not None and native[2] >= .68
                    and native_match[2] <= best_error + .035):
                confidence = max(.45, min(.92, native[2] * .90))
                return native[0], native[1], confidence
        if best_error <= .245 and second_error - best_error >= .022:
            confidence = max(.44, min(.90, 1.0 - 1.65 * best_error))
            return best_text, best_value, confidence
    # Single connected digits are common around zero/one and do not always
    # produce a useful beam. Native OCR is safe enough only for one digit.
    if native is not None and native[2] >= .68:
        text = native[0].strip()
        if len(text) == 1 and text.isdigit():
            return text, native[1], min(.88, native[2] * .92)
    return None


def _read_fast_independent_word(mask):
    """Independent OCR without the expensive secondary small-font renderer.

    Used only for an already bicubic-enlarged source word. At that point the
    normalized full-word templates are sufficient for a fast hypothesis check;
    invoking ``_small_word_score`` would render thousands of redundant font
    rasters and defeat the purpose of the enlargement fast-path.
    """
    bounds = _bbox(mask)
    if bounds is None:
        return None
    tight = _crop_mask(mask, bounds)
    return _cached_fast_independent_word(len(tight[0]), len(tight), b''.join(tight))


@lru_cache(maxsize=1024)
def _cached_fast_independent_word(width, height, pixels):
    mask = [bytearray(pixels[y * width:(y + 1) * width]) for y in range(height)]
    candidates = _independent_word_candidates(mask)
    native = _ocr_numeric(mask)
    if native is not None and native[2] >= .70 and not any(text == native[0] for text, _, _ in candidates):
        candidates.append((native[0], native[1], min((e for _, _, e in candidates), default=.25)))
    if not candidates:
        return None
    best_glyph = min(error for _, _, error in candidates)
    # Font rendering is the dominant cold-start cost.  The per-glyph beam is
    # already ordered by visual evidence, so only the best few hypotheses need
    # an exact whole-word template comparison.  Keeping the native reading in
    # the shortlist preserves punctuation/connected-digit recovery.
    candidates = [item for item in candidates if item[2] <= best_glyph + .035]
    candidates.sort(key=lambda item: item[2])
    if native is not None:
        native_items = [item for item in candidates if item[0] == native[0]]
        shortlist = candidates[:4]
        if native_items and native_items[0] not in shortlist:
            shortlist[-1:] = native_items[:1]
        candidates = shortlist
    else:
        candidates = candidates[:4]
    observed = _normalize_word_mask(mask)
    # Rank all beam candidates with the two-face bank first.  Full five-face
    # rendering is the dominant cold-start cost and is only useful for the few
    # hypotheses whose glyph evidence is already competitive.
    quick = sorted((_normalized_quick_word_score(observed, text) + .10 * glyph_error,
                    text, value, glyph_error)
                   for text, value, glyph_error in candidates)
    refine_count = 2
    if len(quick) > 2 and quick[1][0] - quick[0][0] < .018:
        refine_count = 3
    ranked = sorted((_normalized_word_template_score(observed, text) + .10 * glyph_error,
                     text, value)
                    for _, text, value, glyph_error in quick[:refine_count])
    score, text, value = ranked[0]
    second = next((error for error, _, other in ranked[1:] if other != value), 1.0)
    if score > .32 or (score > .16 and second - score < .010):
        return None
    confidence = max(0.0, min(.98, 1.0 - 1.7 * score))
    return text, value, confidence


@lru_cache(maxsize=1024)
def _cached_independent_word(width, height, pixels):
    mask = [bytearray(pixels[y * width:(y + 1) * width]) for y in range(height)]
    candidates = _independent_word_candidates(mask)
    native = _ocr_numeric(mask)
    if native is not None and native[2] >= .70 and not any(text == native[0] for text, _, _ in candidates):
        candidates.append((native[0], native[1], min((e for _, _, e in candidates), default=.25)))
    if not candidates:
        return None
    best_glyph = min(error for _, _, error in candidates)
    candidates = [item for item in candidates if item[2] <= best_glyph + .035]
    candidates.sort(key=lambda item: item[2])
    if native is not None:
        native_items = [item for item in candidates if item[0] == native[0]]
        shortlist = candidates[:5]
        if native_items and native_items[0] not in shortlist:
            shortlist[-1:] = native_items[:1]
        candidates = shortlist
    else:
        candidates = candidates[:5]
    observed = _normalize_word_mask(mask)
    bounds = _bbox(mask)
    height = bounds[3] - bounds[1] + 1

    # Rank the complete beam with the two-face bank, then spend the full
    # five-face + size-specific renderer only on visually competitive words.
    # This keeps unusual fonts available without cold-rendering every rejected
    # numeric hypothesis.
    quick = sorted((_normalized_quick_word_score(observed, text) + .10 * glyph_error,
                    text, value, glyph_error)
                   for text, value, glyph_error in candidates)
    full_count = min(len(quick), 3 if len(quick) > 1 and quick[1][0] - quick[0][0] < .028 else 2)
    coarse = []
    for quick_score, text, value, glyph_error in quick[:full_count]:
        full_score = _normalized_word_template_score(observed, text) + .10 * glyph_error
        coarse.append((min(quick_score, full_score), text, value, glyph_error))
    coarse.sort()
    refine = coarse[:2] if height >= 9 else coarse[:1]
    ranked = []
    refine_texts = {item[1] for item in refine}
    for coarse_score, text, value, glyph_error in coarse:
        score = coarse_score
        if height >= 9 and text in refine_texts:
            score = min(coarse_score, _small_word_score(observed, text, height) + .10 * glyph_error)
        ranked.append((score, text, value))
    ranked.sort()
    score, text, value = ranked[0]
    second = next((error for error, _, other in ranked[1:] if other != value), 1.0)
    if score > .32 or (score > .16 and second - score < .010):
        return None
    confidence = max(0.0, min(.98, 1.0 - 1.7 * score))
    return text, value, confidence

def _remove_plot_scan_rules(mask, rect, axis):
    """Remove plot-sized rules even when they do not span the whole OCR strip.

    Pillow projections first identify only rows/columns that could possibly
    contain a plot-sized stroke. Exact contiguous-run checks then run on that
    small candidate set, preserving the previous behavior without scanning the
    entire OCR strip twice in Python.
    """
    if not mask or not mask[0]:
        return mask
    out = [bytearray(row) for row in mask]
    height, width = len(mask), len(mask[0])
    image = _mask_image(mask)

    def candidate_indices(vertical, minimum):
        if vertical:
            projection = image.resize((width, 1), Image.Resampling.BOX).tobytes()
            extent = height
        else:
            projection = image.resize((1, height), Image.Resampling.BOX).tobytes()
            extent = width
        # Be deliberately permissive by one source pixel; the exact contiguous
        # run check below remains authoritative.
        cutoff = 255.0 * max(1.0, minimum - 1.0) / max(1, extent)
        return [index for index, value in enumerate(projection) if value + 1 >= cutoff]

    for vertical, minimum in ((False, max(40, (rect[2] - rect[0]) * .5)),
                              (True, max(40, (rect[3] - rect[1]) * .5))):
        for index in candidate_indices(vertical, minimum):
            row = ([mask[y][index] for y in range(height)] if vertical else mask[index])
            start = None
            for end in range(len(row) + 1):
                if end < len(row) and row[end]:
                    if start is None:
                        start = end
                elif start is not None:
                    if end - start >= minimum:
                        if not vertical and axis == 'x' and index <= 12:
                            for y in range(min(height, index + 2)):
                                out[y] = bytearray(width)
                        if vertical and axis == 'y' and index >= width - 13:
                            for row_out in out:
                                row_out[max(0, index - 1):] = bytearray(width - max(0, index - 1))
                        for cross in range(max(0, index - 1),
                                           min(width if vertical else height, index + 2)):
                            if vertical:
                                for y in range(start, end):
                                    out[y][cross] = 0
                            else:
                                out[cross][start:end] = bytearray(end - start)
                    start = None
    return out


def _x_tick_label_band(mask, box, rect):
    """Keep the first text band below X, before dilation can join its title.

    Use ink geometry only. Several short labels can otherwise connect to the
    axis title, forming one wide word and hiding perfectly legible ticks.
    """
    lo, hi = max(0, int(rect[0] - box[0])), min(len(mask[0]), int(rect[2] - box[0]) + 1)
    minimum = max(3, int((hi - lo) * .008))
    rows = [y for y, row in enumerate(mask) if sum(row[lo:hi]) >= minimum]
    if not rows:
        return mask
    bands = [[rows[0]]]
    for y in rows[1:]:
        # Keep gaps between vertically rotated characters within the word band.
        if y - bands[-1][-1] <= 5:
            bands[-1].append(y)
        else:
            bands.append([y])
    first = bands[0]
    if len(bands) < 2 or first[-1] - first[0] < 3:
        return mask
    height = first[-1] - first[0] + 1
    first_mask = [row[lo:hi] for row in mask[first[0]:first[-1] + 1]]
    bodies = [part for part in _components(first_mask) if part[4] >= 3]
    if bodies and all(part[2] - part[0] + 1 <= 2 for part in bodies):
        return mask  # A row of short axis marks, not the printed label row.
    if height > 12 or bands[1][0] - first[0] < height * 2:
        return mask  # Subsequent bands can be characters of a vertical label.
    top, bottom = max(0, first[0] - 2), min(len(mask), first[-1] + 3)
    return [row if top <= y < bottom else bytearray(len(row)) for y, row in enumerate(mask)]


def _isolated_word_group(mask, merged, bounds, area):
    """Exclude a neighbouring slanted word inside a dilation bounding box."""
    x0, y0, x1, y1 = bounds
    cropped = _crop_mask(mask, bounds)
    region = merged.crop((x0, y0, x1 + 1, y1 + 1))
    while True:
        seed = region.tobytes().find(b'\xff')
        if seed < 0:
            return cropped
        trial = region.copy()
        ImageDraw.floodfill(trial, (seed % region.width, seed // region.width), 128)
        membership = trial.tobytes()
        selected = Image.frombytes('L', region.size, membership.translate(
            bytes(255 if value == 128 else 0 for value in range(256))))
        if (membership.count(b'\x80') == area
                and selected.getbbox() == (0, 0, region.width, region.height)):
            break
        # A neighbouring component may enter the rectangle before this word's
        # first pixel. Never assume the top-left foreground belongs to it.
        region.paste(0, mask=selected)
    for y, row in enumerate(cropped):
        for x in range(len(row)):
            if membership[y * region.width + x] != 128:
                row[x] = 0
    return cropped


def _physical_tick_words(image, rect, axis, positions):
    """Associate real text objects with real grid/tick strokes, not a lattice."""
    left, top, right, bottom = map(int, rect)
    if axis == 'x':
        pad = max(20, min(85, (right - left) // 8))
        box = (max(0, left - pad), min(image.height, bottom + 2),
               min(image.width, right + pad + 1), min(image.height, bottom + 150))
    else:
        # Numeric Y labels live close to the axis. Keeping this strip bounded
        # avoids feeding a distant rotated axis-title/annotation through the
        # word merger and OCR while still leaving ample room for scientific
        # notation and high-DPI labels.
        depth = max(70, min(170, round((right - left) * .30)))
        # Include the physical axis even if the Box's left edge is slightly
        # inside/outside it. The rule remover clips that stroke, not the label's
        # final digit (which can sit only 3 px from the true axis).
        box = (max(0, left - depth), max(0, top - 70), min(image.width, left + 5), min(image.height, bottom + 71))
    if box[2] <= box[0] or box[3] <= box[1] or not positions:
        return {}
    mask = _remove_plot_scan_rules(_remove_long_rules(_binary_mask(image.crop(box))), rect, axis)
    if axis == 'x':
        mask = _x_tick_label_band(mask, box, rect)
    ink = _mask_image(mask)
    # A detached decimal or narrow leading 1 may sit 7-8 px from the next
    # glyph at high DPI or after rotation. Keep it in the same word; the
    # separate X text-band filter above prevents joining the nearby title.
    radius = 4
    if axis == 'x':
        glyph_heights = [d - b + 1 for a, b, c, d, area in _components(mask)
                         if area >= 20 and d - b >= 5]
        if glyph_heights:
            radius = max(4, min(8, round(statistics.median(glyph_heights) * .30)))
    if axis == 'y':
        glyph_heights = [d - b + 1 for a, b, c, d, area in _components(mask)
                         if area >= 8 and d - b >= 3]
        if glyph_heights and statistics.median(glyph_heights) <= 10:
            # Small bottom Y labels must not weld to the first X label below
            # them. High-DPI glyphs still need the wider gap allowance.
            radius = 3
    merged = _dilate_binary_square(ink, radius)
    pixels = merged.tobytes()
    groups = _components([bytearray(pixels[y * merged.width:(y + 1) * merged.width]) for y in range(merged.height)])
    spacing = _median_spacing(positions) or 30
    sorted_positions = sorted(positions)
    by_tick = {}
    for x0, y0, x1, y1, area in groups:
        cropped = _crop_mask(mask, (x0, y0, x1, y1))
        if radius > 4 or (axis == 'x' and y1 - y0 >= 38):
            # The expanded bounding rectangles of two slanted words overlap.
            # Retain only ink belonging to this dilation component, not stray
            # pixels from its neighbour that happen to lie in the rectangle.
            cropped = _isolated_word_group(mask, merged, (x0, y0, x1, y1), area)
        # At the lower-left corner an X zero can join the Y zero after
        # dilation. Remove only fragments protruding into the other axis.
        for a, b, c, d, _ in _components(cropped):
            gx, gy = box[0] + x0, box[1] + y0
            stray = ((axis == 'x' and gx + c < left - 2 and gy + d < bottom + 8) or
                     (axis == 'y' and gy + b > bottom + 3 and gx + a >= left - 6))
            if stray:
                for row in cropped[b:d + 1]:
                    row[a:c + 1] = bytearray(c - a + 1)
        tight = _bbox(cropped)
        if tight is None:
            continue
        bbox = (box[0] + x0 + tight[0], box[1] + y0 + tight[1],
                box[0] + x0 + tight[2], box[1] + y0 + tight[3])
        width, height = bbox[2] - bbox[0] + 1, bbox[3] - bbox[1] + 1
        if height < 4 or width > 200 or height > 150:
            continue
        if axis == 'y' and width > max(70, height * 8):
            # A rotated Y title or an application annotation can be merged
            # with a tiny numeric row after dilation. Real numeric tick labels
            # (including signs/decimals/scientific notation) are far narrower
            # at these raster heights. Rejecting the merged object here avoids
            # sending a 100+ px pseudo-word through every OCR fallback.
            continue
        if axis == 'y':
            # Tick numbers are right-aligned close to the physical Y axis even
            # when the glyphs themselves are vertical.  A rotated axis title is
            # often inside the same broad OCR strip but its *right edge* sits
            # far to the left. Reject those fragments before deskew/OCR.
            edge_gap = left - bbox[2]
            maximum_edge_gap = max(24, min(56, round((right - left) * .11)))
            if width <= height * 1.5:
                # Some charts left-align the entire Y label column. Its lone
                # zero is farther from the axis than the final digit of 64000,
                # but is still printed evidence, not a missing origin to infer.
                maximum_edge_gap = max(maximum_edge_gap, 56)
            if edge_gap > maximum_edge_gap:
                continue
        if width <= 3 and height >= 24:
            continue  # Short visible fragment of an outer chart frame, not text.
        centre = (bbox[0] + bbox[2]) / 2 if axis == 'x' else (bbox[1] + bbox[3]) / 2
        # Binary search avoids scanning every physical tick for every text region.
        index = bisect_left(sorted_positions, centre)
        if index == 0:
            position = sorted_positions[0]
        elif index == len(sorted_positions):
            position = sorted_positions[-1]
        else:
            before, after = sorted_positions[index - 1:index + 1]
            position = before if centre - before <= after - centre else after
        offset = abs(position - centre)
        if offset > max(7, spacing * .58):
            continue
        distance = ((bbox[1] - bottom) / max(8, height) * .35 if axis == 'x' else
                    (left - bbox[2]) / max(20, width) * .08)
        rank = offset / max(8, spacing) + distance
        if width <= 3 and height >= 8:
            rank += .8  # Prefer a full label over a thin outer-frame fragment.
        entry = (rank, _crop_mask(cropped, tight), bbox)
        if position not in by_tick or rank < by_tick[position][0]:
            by_tick[position] = entry
    return {position: (mask, bbox) for position, (_, mask, bbox) in by_tick.items()}


def _word_contrast_masks(image, mask, bbox):
    """Additional local contrast only; never construct a number from neighbours."""
    # The caller already evaluated the original mask. Do not OCR it twice.
    tight = image.crop((bbox[0], bbox[1], bbox[2] + 1, bbox[3] + 1)).convert('L')
    histogram = tight.histogram()
    background = max(range(256), key=lambda v: histogram[v])
    ink = tight.point([int(value <= 225) if background >= 128 else int(value >= 30) for value in range(256)])
    pixels = ink.tobytes()
    yield [bytearray(pixels[y * ink.width:(y + 1) * ink.width]) for y in range(ink.height)]
    # Expand vertically to recover faint glyph tops, but don't grow towards
    # the plot: even two pixels of axis ink can look like another digit.
    gray = image.crop((max(0, bbox[0] - 1), max(0, bbox[1] - 2),
                       bbox[2] + 1, min(image.height, bbox[3] + 3))).convert('L')
    hist = gray.histogram()
    light = max(range(256), key=lambda value: hist[value]) >= 128
    for threshold in ((193, 215, 225) if light else (62, 40, 30)):
        ink = gray.point([int(value <= threshold) if light else int(value >= threshold) for value in range(256)])
        pixels = ink.tobytes()
        yield [bytearray(pixels[y * ink.width:(y + 1) * ink.width]) for y in range(ink.height)]


def _scale_model_error(ticks, logarithmic=False):
    """Return a robust normalized fit error for one axis model.

    Scale classification must be based on independently measured labels, never
    on values reconstructed from the tick lattice.  One weak OCR outlier may be
    discarded when at least four measured labels are available; this keeps a
    single damaged digit from changing the chart scale.
    """
    measured = [tick for tick in ticks
                if tick.bbox != (0, 0, 0, 0) and math.isfinite(tick.value)
                and tick.confidence >= .42 and (not logarithmic or tick.value > 0)]
    if len(measured) < 3:
        return None
    measured.sort(key=lambda tick: tick.position)
    # Scale decisions need useful dynamic range.  Very short positive ranges
    # can be fitted almost equally well in linear and logarithmic space.
    transformed = [(tick.position, math.log(tick.value) if logarithmic else tick.value)
                   for tick in measured]
    if max(value for _, value in transformed) - min(value for _, value in transformed) <= 1e-12:
        return None

    subsets = [tuple(range(len(transformed)))]
    if len(transformed) >= 4:
        subsets.extend(tuple(index for index in range(len(transformed)) if index != omitted)
                       for omitted, tick in enumerate(measured) if tick.confidence < .62)
    if len(transformed) >= 6:
        # Two damaged tiny labels must not veto a scale that is independently
        # established by the rest of the axis.  Only low-confidence measured
        # ticks are eligible for this stronger robustness step; never cherry
        # pick two clean labels merely to make a logarithmic hypothesis fit.
        weak = [index for index, tick in enumerate(measured) if tick.confidence < .62]
        for first in range(len(weak)):
            for second in range(first + 1, len(weak)):
                omitted = {weak[first], weak[second]}
                subsets.append(tuple(index for index in range(len(transformed))
                                     if index not in omitted))
    best = None
    for subset in subsets:
        if len(subset) < 3:
            continue
        samples = [transformed[index] for index in subset]
        fit = _linear_fit(samples)
        if fit is None:
            continue
        slope, intercept = fit
        values = [value for _, value in samples]
        span = max(values) - min(values)
        if span <= 1e-12:
            continue
        residuals = [abs(slope * position + intercept - value) / span
                     for position, value in samples]
        rmse = math.sqrt(sum(error * error for error in residuals) / len(residuals))
        maximum = max(residuals, default=1.0)
        # Removing one sample is allowed only as a bounded robustness measure;
        # the small penalty makes a clean all-sample fit win whenever possible.
        omitted = len(transformed) - len(subset)
        score = rmse + .012 * omitted
        candidate = (score, maximum, -len(subset), fit, tuple(subset))
        if best is None or candidate[:3] < best[:3]:
            best = candidate
    return best


def _logarithmic_scale_kind(ticks, fit):
    """Choose a display name for a verified logarithmic geometry.

    ln/log10 produce identical pixel mappings; their base is identifiable only
    when the printed major ticks themselves expose a characteristic ratio.
    Decade-like labels therefore select Log10, e-like labels select Ln, and an
    otherwise logarithmic axis uses Log10 as the generic UI representation.
    """
    measured = sorted((tick for tick in ticks
                       if tick.bbox != (0, 0, 0, 0) and tick.value > 0
                       and tick.confidence >= .42), key=lambda tick: tick.position)
    if len(measured) < 3 or fit is None:
        return AxisScale.LOG10
    slopes = []
    for first, second in zip(measured, measured[1:]):
        delta = second.position - first.position
        if abs(delta) < 2:
            continue
        slopes.append(abs((math.log(second.value) - math.log(first.value)) / delta))
    spacing = _median_spacing([tick.position for tick in measured])
    if not slopes or not spacing:
        return AxisScale.LOG10
    ratio_log = statistics.median(slopes) * spacing
    if ratio_log <= 1e-9:
        return AxisScale.LOG10
    # Compare against integer powers because a chart may label every second or
    # third major decade/exponent rather than every adjacent one.
    d10 = min(abs(ratio_log - power * math.log(10.0)) / (power * math.log(10.0))
              for power in (1, 2, 3))
    de = min(abs(ratio_log - power) / power for power in (1, 2, 3, 4))
    if de <= .08 and de + .025 < d10:
        return AxisScale.LN
    return AxisScale.LOG10


def _observed_axis_scale(ticks, requested):
    """Classify a verified axis as linear or logarithmic from measured ticks.

    The caller's explicit non-linear choice is always respected.  Automatic
    classification runs only from a Linear request and only when the logarithmic
    model wins by a large margin; ambiguous short ranges remain Linear.
    """
    if requested != AxisScale.LINEAR:
        return requested
    measured = [tick for tick in ticks if tick.bbox != (0, 0, 0, 0)
                and math.isfinite(tick.value) and tick.confidence >= .42]
    # Explicit notation is stronger evidence than a geometric base convention.
    # Only accept text whose parsed value agrees with the measured reading;
    # this does not add optical support for formats the word reader cannot read.
    from ..axis_labels import parse_axis_label
    notation = []
    for tick in measured:
        try:
            value, kind = parse_axis_label(tick.text)
        except (ValueError, OverflowError):
            continue
        if kind is not None and _same_numeric_value(value, tick.value):
            notation.append(kind)
    if len(notation) == len(measured) and len(notation) >= 2:
        kinds = set(notation)
        if kinds == {'datetime'}:
            return AxisScale.DATETIME
        if kinds == {'log10'}:
            return AxisScale.LOG10
        if kinds <= {'ln', 'exp'}:
            return AxisScale.LN
    if len(measured) < 4 or any(tick.value <= 0 for tick in measured):
        return requested
    values = [tick.value for tick in measured]
    dynamic_ratio = max(values) / min(values)
    if dynamic_ratio < 3.5:
        return requested
    linear = _scale_model_error(measured, logarithmic=False)
    logarithmic = _scale_model_error(measured, logarithmic=True)
    if linear is None or logarithmic is None:
        return requested
    linear_error, linear_max = linear[0], linear[1]
    log_error, log_max = logarithmic[0], logarithmic[1]
    log_omitted = len(measured) + logarithmic[2]  # field 2 stores -subset length
    # A two-outlier fit is accepted only when both discarded labels are weak.
    # Its .024 omission penalty is intentionally above the normal .018 limit;
    # raise that limit narrowly for this explicitly low-confidence case.
    log_limit = .026 if log_omitted == 2 else .018
    # Require both an absolutely good log fit and a decisive improvement over
    # linear.  This protects ordinary positive linear axes such as 100..500.
    if (log_error <= log_limit and log_max <= .032
            and linear_error >= max(.035, log_error * 2.8)):
        return _logarithmic_scale_kind(measured, logarithmic[3])
    return requested
