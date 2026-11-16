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


def _validate_polyline_points(points):
    coordinates = [tuple(map(float, point)) for point in points]
    if any(len(point) != 2 or not all(math.isfinite(value) for value in point)
           for point in coordinates):
        raise ValueError("Curve coordinates must be finite pixel pairs.")
    return coordinates


def polyline_cumulative_lengths(points):
    """Return monotonically increasing arc lengths for an ordered polyline."""
    coordinates = _validate_polyline_points(points)
    if not coordinates:
        return [], 0.0
    cumulative = [0.0]
    total = 0.0
    for first, last in zip(coordinates, coordinates[1:]):
        total += math.hypot(last[0] - first[0], last[1] - first[1])
        cumulative.append(total)
    return cumulative, total


def project_onto_polyline(point, points):
    """Return (distance, arc_position) for the closest location on a polyline.

    ``arc_position`` is measured along the supplied point order, so callers can
    merge samples without assuming that X or Y is monotonic.
    """
    point = tuple(map(float, point))
    if len(point) != 2 or not all(math.isfinite(value) for value in point):
        raise ValueError("Curve coordinates must be finite pixel pairs.")
    coordinates = _validate_polyline_points(points)
    if not coordinates:
        raise ValueError("Cannot project onto an empty curve.")
    cumulative, _total = polyline_cumulative_lengths(coordinates)
    if len(coordinates) == 1:
        return math.hypot(point[0] - coordinates[0][0], point[1] - coordinates[0][1]), 0.0

    best = None
    for index, (first, last) in enumerate(zip(coordinates, coordinates[1:])):
        dx, dy = last[0] - first[0], last[1] - first[1]
        length_sq = dx * dx + dy * dy
        if length_sq <= 0.0:
            t = 0.0
            px, py = first
        else:
            t = ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy) / length_sq
            t = max(0.0, min(1.0, t))
            px, py = first[0] + t * dx, first[1] + t * dy
        distance = math.hypot(point[0] - px, point[1] - py)
        segment_length = math.sqrt(length_sq)
        along = cumulative[index] + t * segment_length
        candidate = (distance, along)
        if best is None or candidate < best:
            best = candidate
    return best


def resample_polyline(points, count):
    """Place ``count`` samples uniformly by arc length on an ordered polyline.

    Every returned point lies on one of the original finite line segments.
    This intentionally avoids spline interpolation: splines can overshoot the
    digitized curve and create points that were never present on the image.
    """
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("Sample count must be a non-negative integer.")
    coordinates = _validate_polyline_points(points)
    if count == 0:
        return []
    if not coordinates:
        raise ValueError("Cannot resample an empty curve.")
    if count == 1:
        return [coordinates[0]]
    if len(coordinates) == 1:
        return [coordinates[0]] * count

    cumulative, total = polyline_cumulative_lengths(coordinates)
    if total <= 0.0:
        return [coordinates[0]] * count

    targets = [total * index / (count - 1) for index in range(count)]
    result = []
    segment = 0
    for target in targets:
        while segment + 1 < len(cumulative) - 1 and cumulative[segment + 1] < target:
            segment += 1
        start_length, end_length = cumulative[segment], cumulative[segment + 1]
        first, last = coordinates[segment], coordinates[segment + 1]
        if end_length <= start_length:
            result.append(first)
            continue
        ratio = (target - start_length) / (end_length - start_length)
        ratio = max(0.0, min(1.0, ratio))
        result.append((first[0] + (last[0] - first[0]) * ratio,
                       first[1] + (last[1] - first[1]) * ratio))
    # Preserve endpoints exactly rather than accumulating interpolation noise.
    result[0], result[-1] = coordinates[0], coordinates[-1]
    return result



def select_polyline_indices(points, count, *, required_indices=None):
    """Select ``count`` existing vertices while preserving polyline geometry.

    Endpoints and any explicit ``required_indices`` are always retained.  The
    remaining vertices are chosen with a largest-error recursive split (the
    same geometric idea as RDP), so high-curvature/corner regions receive
    samples before straight regions.  On equal-error straight spans, the
    widest span is split near its midpoint, producing an even distribution
    instead of clustering retained samples at one end.
    """
    import heapq

    coordinates = _validate_polyline_points(points)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("Sample count must be a non-negative integer.")
    if count > len(coordinates):
        raise ValueError("Selected sample count cannot exceed the source point count.")
    if not coordinates:
        return []
    required = set(required_indices or ())
    if any(not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(coordinates)
           for index in required):
        raise ValueError("Required sample index is out of range.")
    if len(coordinates) == 1:
        if count != 1:
            raise ValueError("A one-point curve requires one retained sample.")
        return [0]

    required.update((0, len(coordinates) - 1))
    if count < len(required):
        raise ValueError("Target sample count is too small for required curve anchors.")
    if count == len(coordinates):
        return list(range(len(coordinates)))

    selected = set(required)
    heap = []

    def push_span(first, last):
        if last - first < 2:
            return
        midpoint = (first + last) / 2.0
        best_index = None
        best_key = None
        for index in range(first + 1, last):
            distance = _segment_distance(coordinates[index], coordinates[first], coordinates[last])
            # Prefer the geometric error first.  For equal errors (especially
            # collinear data), prefer the vertex nearest the span midpoint.
            key = (distance, -abs(index - midpoint), -index)
            if best_key is None or key > best_key:
                best_key, best_index = key, index
        if best_index is not None:
            distance = best_key[0]
            heapq.heappush(heap, (-distance, -(last - first), first, last, best_index))

    anchors = sorted(selected)
    for first, last in zip(anchors, anchors[1:]):
        push_span(first, last)

    while len(selected) < count and heap:
        _neg_error, _neg_width, first, last, index = heapq.heappop(heap)
        if index in selected:
            continue
        selected.add(index)
        push_span(first, index)
        push_span(index, last)

    # Defensive fallback for degenerate/repeated-coordinate input.
    if len(selected) < count:
        for index in range(len(coordinates)):
            if index not in selected:
                selected.add(index)
                if len(selected) == count:
                    break
    return sorted(selected)
