from __future__ import annotations

import statistics
import colorsys
import operator
from collections import Counter
from concurrent.futures import CancelledError
from PIL import Image
from .models import ExtractionSettings

try:
    import numpy as np
except Exception:  # Optional acceleration; the Python detector remains usable.
    np = None


# Pixel work is tiled: do not allocate float/int masks for a whole large image.
_PIXEL_TILE_SIZE = 262_144


def _rgb_image(image):
    if image.width <= 0 or image.height <= 0:
        raise ValueError('Image must contain pixels.')
    return image if image.mode == 'RGB' else image.convert('RGB')


def _checked_roi(image, roi):
    """Validate inclusive image coordinates before either implementation scans."""
    try:
        if len(roi) != 4:
            raise ValueError
        x0, y0, x1, y1 = (operator.index(value) for value in roi)
    except (TypeError, ValueError):
        raise ValueError('Plot region must contain four integer pixel coordinates.') from None
    if not (0 <= x0 <= x1 < image.width and 0 <= y0 <= y1 < image.height):
        raise ValueError('Plot region must be inside the image with ordered bounds.')
    return x0, y0, x1, y1


def _sampled_rgb(image, roi, step_x, step_y, cancelled):
    """Collect the exact legacy sampling grid without copying the full image."""
    x0, y0, x1, y1 = roi
    xs, ys = range(x0, x1 + 1, step_x), range(y0, y1 + 1, step_y)
    pixels = np.empty((len(ys), len(xs), 3), dtype=np.uint8)
    for row, y in enumerate(ys):
        _check_cancelled(cancelled)
        pixels[row] = np.asarray(image.crop((x0, y, x1 + 1, y + 1)))[0, ::step_x]
    return pixels


def _region_profiles(image, bg, step_x, step_y, cancelled):
    """One bounded sampled scan replaces four Python-level pixel passes."""
    pixels = _sampled_rgb(image, (0, 0, image.width - 1, image.height - 1),
                          step_x, step_y, cancelled)
    rows, columns = pixels.shape[:2]
    foreground_rows = np.zeros(rows, dtype=np.int64)
    foreground_cols = np.zeros(columns, dtype=np.int64)
    dark_rows = np.zeros(rows, dtype=np.int64)
    dark_cols = np.zeros(columns, dtype=np.int64)
    block_height = max(1, _PIXEL_TILE_SIZE // columns)
    for start in range(0, rows, block_height):
        _check_cancelled(cancelled)
        block = pixels[start:start + block_height].astype(np.int32)
        r, g, b = block[..., 0], block[..., 1], block[..., 2]
        dr, dg, db = r - bg[0], g - bg[1], b - bg[2]
        foreground = dr * dr + dg * dg + db * db > 28 * 28
        dark = .2126 * r + .7152 * g + .0722 * b < 185
        foreground_rows[start:start + len(block)] = foreground.sum(axis=1)
        foreground_cols += foreground.sum(axis=0)
        dark_rows[start:start + len(block)] = dark.sum(axis=1)
        dark_cols += dark.sum(axis=0)
    return (foreground_rows / columns, foreground_cols / rows,
            dark_rows / columns, dark_cols / rows)


def _color_match_mask(pixels, target, tolerance):
    """Vector equivalent of _color_matcher, including pastel/neutral rejection."""
    tr, tg, tb = target[:3]
    block = pixels.astype(np.int32)
    r, g, b = block[..., 0], block[..., 1], block[..., 2]
    dr, dg, db = r - tr, g - tg, b - tb
    mask = dr * dr + dg * dg + db * db <= int(tolerance) ** 2
    chroma = max(tr, tg, tb) - min(tr, tg, tb)
    if chroma < 12 or chroma / max(1, tr, tg, tb) < .06:
        return mask
    mask &= np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b) >= max(6, chroma * .25)
    if not mask.any():
        return mask
    # Only RGB/chroma matches need hue arithmetic. Match colorsys' float64
    # operations and channel tie ordering rather than rounding hue bins.
    matched = pixels[mask].astype(np.float64) / 255.0
    r, g, b = matched[:, 0], matched[:, 1], matched[:, 2]
    maximum = np.maximum(np.maximum(r, g), b)
    minimum = np.minimum(np.minimum(r, g), b)
    delta = maximum - minimum
    rc, gc, bc = (maximum - r) / delta, (maximum - g) / delta, (maximum - b) / delta
    hue = (np.where(r == maximum, bc - gc,
                    np.where(g == maximum, 2.0 + rc - bc, 4.0 + gc - rc)) / 6.0) % 1.0
    target_hue = colorsys.rgb_to_hsv(tr / 255, tg / 255, tb / 255)[0]
    difference = np.abs(hue - target_hue)
    mask[mask] = np.minimum(difference, 1 - difference) <= .075
    return mask


def _column_candidates(image, roi, target, settings, cancelled):
    """Yield ordered run centers/widths, with bounded NumPy or Python storage."""
    x0, y0, x1, y1 = roi
    stride = max(1, int(settings.stride))
    min_hits = max(1, int(settings.min_hits))
    if np is None:
        pixels = image.load()
        matches = _color_matcher(target, settings.tolerance)
        for x in range(x0, x1 + 1, stride):
            _check_cancelled(cancelled)
            candidates, start = [], None
            for y in range(y0, y1 + 2):
                hit = y <= y1 and matches(pixels[x, y])
                if hit and start is None:
                    start = y
                elif not hit and start is not None:
                    if y - start >= min_hits:
                        candidates.append(((start + y - 1) / 2.0, y - start))
                    start = None
            yield x, candidates
        return
    height = y1 - y0 + 1
    columns = max(1, min(128, _PIXEL_TILE_SIZE // height) // stride)
    for start in range(x0, x1 + 1, columns * stride):
        _check_cancelled(cancelled)
        stop = min(x1, start + (columns - 1) * stride)
        pixels = np.asarray(image.crop((start, y0, stop + 1, y1 + 1)))[:, ::stride]
        mask = _color_match_mask(pixels, target, settings.tolerance)
        for column in range(mask.shape[1]):
            _check_cancelled(cancelled)
            edges = np.flatnonzero(np.diff(np.concatenate(([False], mask[:, column], [False]))))
            starts, ends = edges[::2], edges[1::2]
            candidates = [(float(y0 + (lo + hi - 1) / 2.0), int(hi - lo))
                          for lo, hi in zip(starts, ends) if hi - lo >= min_hits]
            yield start + column * stride, candidates


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def saturation(rgb: tuple[int, int, int]) -> int:
    return max(rgb) - min(rgb)


def color_distance_sq(a, b) -> int:
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return dr * dr + dg * dg + db * db


def _color_matcher(target, tolerance):
    """Match RGB tolerance without mistaking neutral edges for colored strokes.

    Pastel colors can lie within a small RGB radius of gray/white. A tracker
    will then happily follow a long axis/frame instead of the selected curve.
    Use the picked color's own chroma, not the auto-detection saturation limit
    (which would reject many intentionally selected light-colored curves).
    Neutral targets retain the existing RGB-only behavior for black/gray plots.
    """
    tr, tg, tb = target[:3]
    tolerance_sq = int(tolerance) ** 2
    chroma = max(tr, tg, tb) - min(tr, tg, tb)
    colored = chroma >= 12 and chroma / max(1, tr, tg, tb) >= .06
    target_hue = colorsys.rgb_to_hsv(tr / 255, tg / 255, tb / 255)[0] if colored else None
    minimum_chroma = max(6, chroma * .25)

    def matches(rgb):
        r, g, b = rgb[:3]
        dr, dg, db = r - tr, g - tg, b - tb
        if dr * dr + dg * dg + db * db > tolerance_sq:
            return False
        if target_hue is None:
            return True
        if max(r, g, b) - min(r, g, b) < minimum_chroma:
            return False
        hue = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0]
        difference = abs(hue - target_hue)
        return min(difference, 1 - difference) <= .075

    return matches


def sample_color(image: Image.Image, x: int, y: int, radius: int = 2) -> tuple[int, int, int]:
    image = _rgb_image(image)
    pix = image.load()
    xs = range(max(0, x - radius), min(image.width, x + radius + 1))
    ys = range(max(0, y - radius), min(image.height, y + radius + 1))
    samples = [pix[xx, yy] for yy in ys for xx in xs]
    # Keep the clicked stroke's color: a thin curve is outnumbered by the
    # background in a square neighborhood, so an unconditional median is white.
    center = pix[max(0, min(image.width - 1, x)), max(0, min(image.height - 1, y))]
    matches = _color_matcher(center, 55)
    samples = [rgb for rgb in samples if matches(rgb)] or [center]
    return tuple(int(statistics.median([c[i] for c in samples])) for i in range(3))


def _cluster_positions(values, gap):
    if not values:
        return []
    groups = [[values[0]]]
    for v in values[1:]:
        if v - groups[-1][-1] <= gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [int(round(sum(g) / len(g))) for g in groups]


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise CancelledError('Curve extraction cancelled.')


def _best_foreground_run(flags, max_gap=1):
    """Return the strongest nearly-continuous foreground run in one scanline.

    Plot frames are usually one-pixel raster lines, but antialiasing and image
    compression can punch tiny holes through them.  Allowing a one-pixel gap
    preserves those lines without joining separate glyphs into a fake axis.
    The return value is ``(start, end, span, density)``.
    """
    best = None
    start = last_hit = None
    gaps = hits = 0
    for index, hit in enumerate(flags):
        if hit:
            if start is None:
                start = index
                hits = 1
            else:
                hits += 1
            last_hit = index
            gaps = 0
            continue
        if start is None:
            continue
        gaps += 1
        if gaps <= max_gap:
            continue
        end = last_hit
        span = end - start + 1
        density = hits / max(1, span)
        candidate = (start, end, span, density)
        if best is None or span * density > best[2] * best[3]:
            best = candidate
        start = last_hit = None
        gaps = hits = 0
    if start is not None:
        end = last_hit
        span = end - start + 1
        density = hits / max(1, span)
        candidate = (start, end, span, density)
        if best is None or span * density > best[2] * best[3]:
            best = candidate
    return best


def _cluster_frame_segments(segments):
    """Collapse adjacent antialiased scanlines to one representative line."""
    if not segments:
        return []
    groups = [[segments[0]]]
    for segment in segments[1:]:
        if segment[0] - groups[-1][-1][0] <= 2:
            groups[-1].append(segment)
        else:
            groups.append([segment])
    # segment = (position, start, end, span, density).  Prefer the line with
    # the greatest supported span, then density, inside each antialias cluster.
    return [max(group, key=lambda item: (item[3] * item[4], item[3], item[4]))
            for group in groups]


def _detect_rectangular_plot_frame(image, bg, cancelled=None):
    """Find a large rectangular chart frame before text/profile fallbacks.

    Document-style charts often contain a title above the plot and a legend
    below it.  Global row/column density therefore expands the ROI around that
    text.  A real plot frame, by contrast, contains long horizontal and vertical
    strokes whose endpoints agree.  Search a bounded raster for those four
    mutually supporting edges.  If no closed frame exists, return ``None`` so
    the existing profile detector still handles open-axis charts.
    """
    _check_cancelled(cancelled)
    width, height = image.size
    scale = min(1.0, 900.0 / max(1, width), 700.0 / max(1, height))
    if scale < 1.0:
        sample_width = max(1, int(round(width * scale)))
        sample_height = max(1, int(round(height * scale)))
        sample = image.resize((sample_width, sample_height), Image.Resampling.LANCZOS)
    else:
        sample = image
        sample_width, sample_height = width, height

    # Keep this implementation independent from NumPy so accelerated and scalar
    # execution choose exactly the same plot rectangle.
    flattened = getattr(sample, 'get_flattened_data', None)
    pixels = list(flattened() if flattened is not None else sample.getdata())
    threshold_sq = 32 * 32
    foreground = [
        (rgb[0] - bg[0]) * (rgb[0] - bg[0])
        + (rgb[1] - bg[1]) * (rgb[1] - bg[1])
        + (rgb[2] - bg[2]) * (rgb[2] - bg[2]) > threshold_sq
        for rgb in pixels
    ]
    minimum_horizontal = max(30, int(sample_width * .20))
    minimum_vertical = max(25, int(sample_height * .20))

    horizontal = []
    for y in range(sample_height):
        _check_cancelled(cancelled)
        run = _best_foreground_run(
            foreground[y * sample_width:(y + 1) * sample_width], max_gap=1)
        if run is not None and run[2] >= minimum_horizontal and run[3] >= .82:
            horizontal.append((y,) + run)

    vertical = []
    for x in range(sample_width):
        _check_cancelled(cancelled)
        run = _best_foreground_run(foreground[x::sample_width], max_gap=1)
        if run is not None and run[2] >= minimum_vertical and run[3] >= .82:
            vertical.append((x,) + run)

    horizontal = _cluster_frame_segments(horizontal)
    vertical = _cluster_frame_segments(vertical)
    if len(horizontal) < 2 or len(vertical) < 2:
        return None

    tolerance = max(3, int(round(min(sample_width, sample_height) * .012)))
    best = None
    for left_index, left in enumerate(vertical):
        lx, left_top, left_bottom, _, left_density = left
        for right in vertical[left_index + 1:]:
            rx, right_top, right_bottom, _, right_density = right
            plot_width = rx - lx
            if plot_width < minimum_horizontal:
                continue
            overlap_top = max(left_top, right_top)
            overlap_bottom = min(left_bottom, right_bottom)
            if overlap_bottom - overlap_top + 1 < minimum_vertical:
                continue

            spanning = [line for line in horizontal
                        if line[1] <= lx + tolerance and line[2] >= rx - tolerance]
            for top_index, top in enumerate(spanning):
                ty = top[0]
                if not (overlap_top - tolerance <= ty <= overlap_bottom + tolerance):
                    continue
                for bottom in spanning[top_index + 1:]:
                    by = bottom[0]
                    plot_height = by - ty
                    if plot_height < minimum_vertical:
                        continue
                    if not (overlap_top - tolerance <= by <= overlap_bottom + tolerance):
                        continue
                    if (left_top > ty + tolerance or left_bottom < by - tolerance
                            or right_top > ty + tolerance or right_bottom < by - tolerance):
                        continue
                    area = plot_width * plot_height
                    support = top[4] + bottom[4] + left_density + right_density
                    score = area * support
                    if best is None or score > best[0]:
                        best = (score, (lx, ty, rx, by))

    if best is None:
        return None
    rect = best[1]
    if scale < 1.0:
        rect = tuple(int(round(value / scale)) for value in rect)
    left, top, right, bottom = rect
    return (max(0, min(width - 1, left)), max(0, min(height - 1, top)),
            max(0, min(width - 1, right)), max(0, min(height - 1, bottom)))


def detect_plot_area(image: Image.Image, *, cancelled=None) -> tuple[int, int, int, int] | None:
    _check_cancelled(cancelled)
    image = _rgb_image(image)
    w, h = image.size
    pix = image.load()
    step_x = max(1, w // 900)
    step_y = max(1, h // 700)
    r = max(2, min(w, h) // 100)
    corners = []
    for cx, cy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        for yy in range(max(0, cy - r), min(h, cy + r + 1), max(1, r // 3)):
            for xx in range(max(0, cx - r), min(w, cx + r + 1), max(1, r // 3)):
                corners.append(pix[xx, yy])
    bg = tuple(int(statistics.median([c[i] for c in corners])) for i in range(3))
    frame = _detect_rectangular_plot_frame(image, bg, cancelled)
    if frame is not None:
        return frame
    if np is not None:
        foreground_rows, foreground_cols, dark_rows, dark_cols = _region_profiles(
            image, bg, step_x, step_y, cancelled)
        _check_cancelled(cancelled)
        rows = [index * step_y for index in np.flatnonzero(foreground_rows >= .25)]
        cols = [index * step_x for index in np.flatnonzero(foreground_cols >= .25)]
        if rows and cols:
            top, bottom, left, right = int(min(rows)), int(max(rows)), int(min(cols)), int(max(cols))
            if right - left >= w * .25 and bottom - top >= h * .25:
                return left, top, right, bottom
        hs = [int(index * step_y) for index in np.flatnonzero((dark_rows >= .12) & (dark_rows <= .92))]
        vs = [int(index * step_x) for index in np.flatnonzero((dark_cols >= .12) & (dark_cols <= .92))]
        hl = _cluster_positions(hs, max(2, step_y * 2))
        vl = _cluster_positions(vs, max(2, step_x * 2))
        if len(hl) >= 2 and len(vl) >= 2:
            top, bottom, left, right = hl[0], hl[-1], vl[0], vl[-1]
            if right - left >= w * .2 and bottom - top >= h * .2:
                return left, top, right, bottom
        return None
    threshold2 = 28 * 28
    rows = []
    for y in range(0, h, step_y):
        _check_cancelled(cancelled)
        vals = [color_distance_sq(pix[x, y], bg) > threshold2 for x in range(0, w, step_x)]
        if sum(vals) / max(1, len(vals)) >= .25:
            rows.append(y)
    cols = []
    for x in range(0, w, step_x):
        _check_cancelled(cancelled)
        vals = [color_distance_sq(pix[x, y], bg) > threshold2 for y in range(0, h, step_y)]
        if sum(vals) / max(1, len(vals)) >= .25:
            cols.append(x)
    if rows and cols:
        top, bottom, left, right = min(rows), max(rows), min(cols), max(cols)
        if right - left >= w * .25 and bottom - top >= h * .25:
            return left, top, right, bottom

    dark_thr = 185
    hs, vs = [], []
    for y in range(0, h, step_y):
        _check_cancelled(cancelled)
        vals = [luminance(pix[x, y]) < dark_thr for x in range(0, w, step_x)]
        score = sum(vals) / max(1, len(vals))
        if .12 <= score <= .92:
            hs.append(y)
    for x in range(0, w, step_x):
        _check_cancelled(cancelled)
        vals = [luminance(pix[x, y]) < dark_thr for y in range(0, h, step_y)]
        score = sum(vals) / max(1, len(vals))
        if .12 <= score <= .92:
            vs.append(x)
    hl = _cluster_positions(sorted(hs), max(2, step_y * 2))
    vl = _cluster_positions(sorted(vs), max(2, step_x * 2))
    if len(hl) >= 2 and len(vl) >= 2:
        top, bottom, left, right = hl[0], hl[-1], vl[0], vl[-1]
        if right - left >= w * .2 and bottom - top >= h * .2:
            return left, top, right, bottom
    return None


def detect_curve_colors(image: Image.Image, roi, minimum_saturation: int = 70, limit=6, *, cancelled=None):
    """Rank distinct colored strokes by horizontal coverage, merging shade variants."""
    _check_cancelled(cancelled)
    image = _rgb_image(image)
    x0, y0, x1, y1 = _checked_roi(image, roi)
    if limit <= 0:
        return []
    pix = image.load()
    sx = max(1, (x1 - x0 + 1) // 500)
    sy = max(1, (y1 - y0 + 1) // 350)
    minimum_coverage = max(3, min(15, (x1 - x0 + 1) // (20 * sx)))
    if np is not None:
        pixels = _sampled_rgb(image, (x0, y0, x1, y1), sx, sy, cancelled)
        maximum = pixels.max(axis=2)
        eligible = (maximum - pixels.min(axis=2) >= minimum_saturation) & (maximum >= 80)
        _check_cancelled(cancelled)
        if not eligible.any():
            return []
        values = pixels[eligible]
        columns = np.nonzero(eligible)[1]
        quantized = values.astype(np.int32) // 16
        keys = (quantized[:, 0] << 8) | (quantized[:, 1] << 4) | quantized[:, 2]
        _keys, first, inverse, counts = np.unique(
            keys, return_index=True, return_inverse=True, return_counts=True)
        _check_cancelled(cancelled)
        sums = [np.bincount(inverse, weights=values[:, channel], minlength=len(counts))
                for channel in range(3)]
        # Coverage is distinct sampled X positions, not pixel count. Preserve
        # row-major first occurrence as the legacy stable-sort tie breaker.
        pairs = inverse.astype(np.int64) * pixels.shape[1] + columns
        coverage = np.bincount(np.unique(pairs) // pixels.shape[1], minlength=len(counts))
        _check_cancelled(cancelled)
        ranked = sorted(range(len(counts)), key=lambda index: (
            int(coverage[index]), int(counts[index]), -int(first[index])), reverse=True)
        candidates = ((int(coverage[index]),
                       tuple(round(float(sums[channel][index]) / int(counts[index])) for channel in range(3)))
                      for index in ranked)
        return _distinct_curve_colors(candidates, minimum_coverage, limit, cancelled)
    counts = Counter()
    sums: dict[tuple[int, int, int], list[int]] = {}
    coverage = {}
    for y in range(y0, y1 + 1, sy):
        _check_cancelled(cancelled)
        for x in range(x0, x1 + 1, sx):
            rgb = pix[x, y]
            if saturation(rgb) < minimum_saturation or max(rgb) < 80:
                continue
            key = tuple((c // 16) * 16 for c in rgb)
            counts[key] += 1
            coverage.setdefault(key, set()).add(x)
            sums.setdefault(key, [0, 0, 0, 0])
            s = sums[key]
            s[0] += rgb[0]; s[1] += rgb[1]; s[2] += rgb[2]; s[3] += 1
    if not counts:
        return []
    ranked = sorted(counts, key=lambda key: (len(coverage[key]), counts[key]), reverse=True)
    candidates = ((len(coverage[key]), tuple(round(sums[key][i] / sums[key][3]) for i in range(3)))
                  for key in ranked)
    return _distinct_curve_colors(candidates, minimum_coverage, limit, cancelled)


def _distinct_curve_colors(candidates, minimum_coverage, limit, cancelled):
    colors = []
    hues = []
    for coverage, rgb in candidates:
        _check_cancelled(cancelled)
        if coverage < minimum_coverage:
            continue
        hue = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))[0]
        if any(min(abs(hue - old), 1 - abs(hue - old)) < .045 for old in hues):
            continue
        colors.append(rgb)
        hues.append(hue)
        if len(colors) >= limit:
            break
    return colors


def detect_curve_color(image: Image.Image, roi, minimum_saturation: int = 70, *, cancelled=None) -> tuple[int, int, int] | None:
    options = {'cancelled': cancelled} if cancelled is not None else {}
    colors = detect_curve_colors(image, roi, minimum_saturation, limit=1, **options)
    return colors[0] if colors else None


def _runs(values):
    if not values:
        return []
    runs = [[values[0]]]
    for v in values[1:]:
        if v <= runs[-1][-1] + 1:
            runs[-1].append(v)
        else:
            runs.append([v])
    return runs


def _moving_average(points, window, *, cancelled=None):
    if window <= 1 or len(points) < 3:
        return points
    if window % 2 == 0:
        window += 1
    half = window // 2
    prefix = [0.0]
    for _, y in points:
        _check_cancelled(cancelled)
        prefix.append(prefix[-1] + y)
    out = []
    for i, (x, _) in enumerate(points):
        _check_cancelled(cancelled)
        lo, hi = max(0, i - half), min(len(points), i + half + 1)
        out.append((x, (prefix[hi] - prefix[lo]) / (hi - lo)))
    return out


def extract_curve(image: Image.Image, roi, curve_rgb, settings: ExtractionSettings, *, cancelled=None) -> list[tuple[float, float]]:
    _check_cancelled(cancelled)
    image = _rgb_image(image)
    roi = _checked_roi(image, roi)
    continuity = max(1, int(settings.continuity))
    max_gap = max(0, int(settings.max_gap_columns))
    segments, raw, last_y, gap = [], [], None, 0
    for x, candidates in _column_candidates(image, roi, curve_rgb, settings, cancelled):
        _check_cancelled(cancelled)
        if not candidates:
            gap += 1
            continue
        if last_y is None or gap > max_gap:
            if raw and gap > max_gap:
                segments.append(raw)
                raw = []
            y, _ = max(candidates, key=lambda c: c[1])
        else:
            y, _ = min(candidates, key=lambda c: (abs(c[0] - last_y), -c[1]))
            if abs(y - last_y) > continuity:
                gap += 1
                continue
        raw.append((float(x), float(y)))
        last_y, gap = y, 0
    segments.append(raw)
    if sum(len(segment) for segment in segments) < 2:
        return []
    return [point for segment in segments
            for point in _moving_average(segment, max(1, int(settings.smoothing)), cancelled=cancelled)]
