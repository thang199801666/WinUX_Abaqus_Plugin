from __future__ import annotations

import statistics
import colorsys
from collections import Counter
from PIL import Image
from .models import ExtractionSettings


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def saturation(rgb: tuple[int, int, int]) -> int:
    return max(rgb) - min(rgb)


def color_distance_sq(a, b) -> int:
    return sum((a[i] - b[i]) ** 2 for i in range(3))


def sample_color(image: Image.Image, x: int, y: int, radius: int = 2) -> tuple[int, int, int]:
    pix = image.load()
    xs = range(max(0, x - radius), min(image.width, x + radius + 1))
    ys = range(max(0, y - radius), min(image.height, y + radius + 1))
    samples = [pix[xx, yy] for yy in ys for xx in xs]
    # Keep the clicked stroke's color: a thin curve is outnumbered by the
    # background in a square neighborhood, so an unconditional median is white.
    center = pix[max(0, min(image.width - 1, x)), max(0, min(image.height - 1, y))]
    samples = [rgb for rgb in samples if color_distance_sq(rgb, center) <= 55 ** 2] or [center]
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


def detect_plot_area(image: Image.Image) -> tuple[int, int, int, int] | None:
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
    threshold2 = 28 * 28
    rows = []
    for y in range(0, h, step_y):
        vals = [color_distance_sq(pix[x, y], bg) > threshold2 for x in range(0, w, step_x)]
        if sum(vals) / max(1, len(vals)) >= .25:
            rows.append(y)
    cols = []
    for x in range(0, w, step_x):
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
        vals = [luminance(pix[x, y]) < dark_thr for x in range(0, w, step_x)]
        score = sum(vals) / max(1, len(vals))
        if .12 <= score <= .92:
            hs.append(y)
    for x in range(0, w, step_x):
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


def detect_curve_colors(image: Image.Image, roi, minimum_saturation: int = 70, limit=6):
    """Rank distinct colored strokes by horizontal coverage, merging shade variants."""
    x0, y0, x1, y1 = roi
    pix = image.load()
    sx = max(1, (x1 - x0 + 1) // 500)
    sy = max(1, (y1 - y0 + 1) // 350)
    counts = Counter()
    sums: dict[tuple[int, int, int], list[int]] = {}
    coverage = {}
    for y in range(y0, y1 + 1, sy):
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
    colors = []
    for key in ranked:
        if len(coverage[key]) < max(3, min(15, (x1 - x0 + 1) // (20 * sx))):
            continue
        s = sums[key]
        rgb = tuple(round(s[i] / s[3]) for i in range(3))
        hue = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))[0]
        if any(min(abs(hue - colorsys.rgb_to_hsv(*(c / 255 for c in old))[0]),
                   1 - abs(hue - colorsys.rgb_to_hsv(*(c / 255 for c in old))[0])) < .045
               for old in colors):
            continue
        colors.append(rgb)
        if len(colors) >= limit:
            break
    return colors


def detect_curve_color(image: Image.Image, roi, minimum_saturation: int = 70) -> tuple[int, int, int] | None:
    colors = detect_curve_colors(image, roi, minimum_saturation, limit=1)
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


def _moving_average(points, window):
    if window <= 1 or len(points) < 3:
        return points
    if window % 2 == 0:
        window += 1
    half = window // 2
    ys = [p[1] for p in points]
    out = []
    for i, (x, _) in enumerate(points):
        lo, hi = max(0, i - half), min(len(points), i + half + 1)
        out.append((x, sum(ys[lo:hi]) / (hi - lo)))
    return out


def extract_curve(image: Image.Image, roi, curve_rgb, settings: ExtractionSettings) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = roi
    pix = image.load()
    tol2 = int(settings.tolerance) ** 2
    stride = max(1, int(settings.stride))
    min_hits = max(1, int(settings.min_hits))
    continuity = max(1, int(settings.continuity))
    max_gap = max(0, int(settings.max_gap_columns))
    columns = []
    for x in range(x0, x1 + 1, stride):
        hits = [y for y in range(y0, y1 + 1) if color_distance_sq(pix[x, y], curve_rgb) <= tol2]
        candidates = []
        for run in _runs(hits):
            if len(run) >= min_hits:
                candidates.append((float(statistics.median(run)), len(run)))
        columns.append((x, candidates))

    segments, raw, last_y, gap = [], [], None, 0
    for x, candidates in columns:
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
            for point in _moving_average(segment, max(1, int(settings.smoothing)))]
