"""Conservative geometric alignment of a selected region to its X/Y axes."""
from concurrent.futures import CancelledError
import math


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise CancelledError('Region alignment cancelled.')


def _axis_candidate(image, rect, vertical, radius, cancelled):
    left, top, right, bottom = rect
    edge = left if vertical else bottom
    extent = image.width if vertical else image.height
    low, high = max(0, edge - radius), min(extent - 1, edge + radius)
    start, end = (top + radius, bottom - radius) if vertical else (left + radius, right - radius)
    if end - start < 16:
        return None
    step = max(1, math.ceil((end - start + 1) / 900))
    samples = range(start, end + 1, step)
    box = (low, start, high + 1, end + 1) if vertical else (start, low, end + 1, high + 1)
    gray = image.crop(box).convert('L')
    histogram = gray.histogram()
    background = max(range(256), key=histogram.__getitem__)
    light = background >= 128
    pixels = image.load()
    candidates = []
    for position in range(low, high + 1):
        _check_cancelled(cancelled)
        ink = []
        for sample in samples:
            rgb = pixels[position, sample] if vertical else pixels[sample, position]
            # Colored curve strokes are not candidate axis lines.
            neutral = max(rgb) - min(rgb) <= 45
            value = sum(rgb) / 3
            ink.append(max(0, background - value if light else value - background) if neutral else 0)
        coverage = sum(value >= 48 for value in ink) / len(ink)
        quarters = [ink[i * len(ink) // 4:(i + 1) * len(ink) // 4] for i in range(4)]
        if coverage < .8 or any(sum(v >= 48 for v in part) / len(part) < .65 for part in quarters):
            continue
        candidates.append((position, sum(ink) / len(ink)))
    groups = []
    for position, strength in candidates:
        if not groups or position > groups[-1][-1][0] + 1:
            groups.append([])
        groups[-1].append((position, strength))
    peaks = []
    for group in groups:
        # A 2-5 px anti-aliased stroke must snap to its visual centre,
        # not its darkest edge. Weight the entire connected stroke rather
        # than choosing the highest pixel of its intensity profile.
        strengths = [max(0.0, value) for _, value in group]
        total = sum(strengths)
        if not total:
            continue
        centre = round(sum(position * value for (position, _), value
                           in zip(group, strengths)) / total)
        peaks.append((max(strengths), centre))
    # Prefer stronger strokes, but do not jump across a second equally
    # plausible parallel line (e.g. a plot frame versus an axis).
    peaks.sort(reverse=True)
    if not peaks or (len(peaks) > 1 and peaks[0][0] < peaks[1][0] * 2):
        return None
    return peaks[0][1]


def align_region_to_axes(image, rect, *, cancelled=None):
    """Snap only left/bottom to strong nearby neutral lines; preserve top/right.

    Search bounded strips rather than the whole chart, avoiding titles, outer
    frames and faint grid lines. Ambiguous or absent axes leave edges unchanged.
    No tick text, numerical sequences or assumed zero values are involved.
    """
    _check_cancelled(cancelled)
    if image is None or rect is None:
        return rect
    rect = tuple(int(round(value)) for value in rect)
    left, top, right, bottom = rect
    if right - left < 32 or bottom - top < 32:
        return rect
    image = image if image.mode == 'RGB' else image.convert('RGB')
    radius = min(48, max(10, round(min(right - left, bottom - top) * .08)))
    x = _axis_candidate(image, rect, True, radius, cancelled)
    y = _axis_candidate(image, rect, False, radius, cancelled)
    _check_cancelled(cancelled)
    aligned = (left if x is None else x, top, right, bottom if y is None else y)
    if aligned[2] - aligned[0] < 2 or aligned[3] - aligned[1] < 2:
        return rect
    return aligned
