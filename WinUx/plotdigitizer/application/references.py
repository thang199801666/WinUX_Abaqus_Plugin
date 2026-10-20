"""UI-agnostic reference-series conversion for Plot Digitizer."""
from __future__ import annotations


def dataset_xy_points(dataset):
    """Return calibrated XY points from one dataset in display order."""
    points = [[float(x), float(y)] for x, y in (dataset.extracted_data or [])]
    points.extend(
        [float(point.x), float(point.y)]
        for point in (dataset.manual_points or [])
        if point.x is not None and point.y is not None
    )
    return points


def unique_series_name(preferred, existing_names):
    base = str(preferred or "").strip() or "Digitized Curve"
    used = {str(name or "").strip().casefold() for name in existing_names}
    if base.casefold() not in used:
        return base
    index = 2
    while "{} ({})".format(base, index).casefold() in used:
        index += 1
    return "{} ({})".format(base, index)


def reference_candidate(dataset, existing_names=()):
    """Build a host-neutral reference payload from a calibrated dataset."""
    points = dataset_xy_points(dataset)
    if not points:
        raise ValueError("The active dataset has no calibrated X/Y data.")
    return {
        "name": unique_series_name(dataset.name, existing_names),
        "points": points,
        "enabled": True,
        "kind": "xy",
    }
