"""Error-bounded simplification retaining original samples and segment ends."""
from __future__ import annotations

import math


def normalize_breaks(count, breaks):
    """None means legacy/unknown segments; [] means one known segment."""
    if breaks is None:
        return None
    if any(not isinstance(index, int) or isinstance(index, bool) or not 0 < index < count
           for index in breaks):
        raise ValueError("Invalid extracted segment boundaries.")
    return sorted(set(breaks))


def remap_breaks(breaks, retained):
    """Keep segment boundaries when samples are reduced or deleted."""
    if breaks is None:
        return None
    result, segment, previous = [], 0, None
    for position, index in enumerate(retained):
        while segment < len(breaks) and index >= breaks[segment]:
            segment += 1
        if position and segment != previous:
            result.append(position)
        previous = segment
    return result


def _segment_distance(point, first, last):
    dx, dy = last[0] - first[0], last[1] - first[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return math.hypot(point[0] - first[0], point[1] - first[1])
    if not math.isfinite(length):
        scale = max(abs(value) for pair in (point, first, last) for value in pair)
        return _segment_distance(*(tuple(value / scale for value in pair)
                                   for pair in (point, first, last))) * scale
    ux, uy = dx / length, dy / length
    projection = (point[0] - first[0]) * ux + (point[1] - first[1]) * uy
    if 0 <= projection <= length and dx * (point[1] - first[1]) == dy * (point[0] - first[0]):
        return 0.0
    projection = max(0.0, min(length, projection))
    return math.hypot(point[0] - (first[0] + projection * ux),
                      point[1] - (first[1] + projection * uy))


def simplify_indices(points, max_error=0.5, *, breaks=None, metric_points=None):
    """Iterative Ramer-Douglas-Peucker, in image-pixel coordinates.

    Returned indices remain in acquisition order. Distances are measured to
    finite line segments, preserving vertical paths, backtracking and loops.
    Each omitted sample stays within max_error of its replacement segment.
    """
    if isinstance(max_error, bool):
        raise ValueError("Maximum reduction error must be a finite, non-negative number.")
    try:
        max_error = float(max_error)
    except (TypeError, ValueError):
        raise ValueError("Maximum reduction error must be a finite, non-negative number.") from None
    if not math.isfinite(max_error) or max_error < 0:
        raise ValueError("Maximum reduction error must be a finite, non-negative number.")
    coordinates = [tuple(map(float, point)) for point in points]
    if any(len(point) != 2 or not all(math.isfinite(value) for value in point) for point in coordinates):
        raise ValueError("Sample coordinates must be finite pixel pairs.")
    metric = None if metric_points is None else [tuple(map(float, point)) for point in metric_points]
    if metric is not None and (len(metric) != len(coordinates) or any(
            len(point) != 2 or not all(math.isfinite(value) for value in point) for point in metric)):
        raise ValueError("Reduction geometry must match the samples and contain finite pairs.")
    boundaries = normalize_breaks(len(coordinates), breaks) or []
    if len(coordinates) <= 2:
        return list(range(len(coordinates)))
    keep = {0, len(coordinates) - 1}
    for boundary in boundaries:
        keep.update((boundary - 1, boundary))
    # Preserve real reversals even if a later endpoint encloses the whole
    # backtracking path. Ignore duplicate neighbors when finding turn vectors.
    for start, stop in zip([0, *boundaries], [*boundaries, len(coordinates)]):
        distinct = []
        for index in range(start, stop):
            if not distinct or coordinates[index] != coordinates[distinct[-1]]:
                distinct.append(index)
        for first, middle, last in zip(distinct, distinct[1:], distinct[2:]):
            for space in (coordinates,) if metric is None else (coordinates, metric):
                previous = (space[middle][0] - space[first][0], space[middle][1] - space[first][1])
                following = (space[last][0] - space[middle][0], space[last][1] - space[middle][1])
                dot = previous[0] * following[0] + previous[1] * following[1]
                cross = previous[0] * following[1] - previous[1] * following[0]
                if dot < 0 or (max_error == 0 and cross != 0):
                    keep.add(middle)
    anchors = sorted(keep)
    pending = list(zip(anchors, anchors[1:]))
    while pending:
        first, last = pending.pop()
        if last - first < 2:
            continue
        furthest, distance = first + 1, -1.0
        for index in range(first + 1, last):
            candidate = _segment_distance(coordinates[index], coordinates[first], coordinates[last])
            if metric is not None:
                candidate = max(candidate, _segment_distance(metric[index], metric[first], metric[last]))
            if candidate > distance:
                furthest, distance = index, candidate
        if distance > max_error:
            keep.add(furthest)
            pending.extend(((first, furthest), (furthest, last)))
    return sorted(keep)
