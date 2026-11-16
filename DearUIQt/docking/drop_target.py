"""Reusable dock-guide hit testing and prospective drop geometry.

This module deliberately owns only renderer-independent docking semantics.  The
application supplies guide/site bounds and the preferred target extent; native
or DPG overlays remain responsible for painting the result.
"""
from __future__ import annotations

from .dock_widget import DockDropPreview


class QDockDropTargetResolver:
    """Resolve pointer samples against Qt-like four-way dock guides.

    ``resolve`` returns a semantic target dictionary compatible with
    :class:`QDockWindowLifecycle`.  ``previewRect`` computes the prospective
    rectangle for a side drop without knowing anything about WinUx panels.
    """

    Areas = ("left", "right", "top", "bottom")

    @classmethod
    def normalizeArea(cls, area, default=None):
        value = str(area or "").strip().lower()
        if value in cls.Areas:
            return value
        return default

    @staticmethod
    def contains(point, bounds, margin=0.0):
        if point is None or bounds is None:
            return False
        try:
            px, py = map(float, point)
            x, y, width, height = map(float, bounds)
            margin = max(0.0, float(margin))
        except Exception:
            return False
        return (x - margin <= px <= x + width + margin
                and y - margin <= py <= y + height + margin)

    @classmethod
    def resolve(cls, points, bounds, tolerance=6.0):
        """Return ``{'area': ..., 'scope': ...}`` for the first guide hit."""
        if bounds is None:
            return None
        if points is None:
            points = ()
        # A single ``(x, y)`` tuple is accepted as a convenience.
        try:
            if len(points) == 2 and all(isinstance(v, (int, float)) for v in points):
                points = (points,)
        except Exception:
            points = ()
        for point in points:
            area, scope = DockDropPreview.zone_hit(point, bounds, tolerance=tolerance)
            area = cls.normalizeArea(area)
            if area is not None:
                return {"area": area, "scope": str(scope or "inner").lower()}
        return None

    @classmethod
    def areaAt(cls, points, bounds, tolerance=6.0):
        target = cls.resolve(points, bounds, tolerance=tolerance)
        return None if target is None else target["area"]

    @classmethod
    def previewRect(cls, bounds, area, extent=None, max_fraction=0.5):
        """Return the prospective rectangle for a four-way side drop.

        ``extent`` is the desired width for left/right or height for top/bottom.
        When omitted, half of the corresponding dimension is used.  The extent
        is clamped to the site so invalid geometry can never escape the bounds.
        """
        area = cls.normalizeArea(area)
        if area is None or bounds is None:
            return None
        try:
            x, y, width, height = map(float, bounds)
        except Exception:
            return None
        if width <= 0.0 or height <= 0.0:
            return None
        axis = width if area in ("left", "right") else height
        try:
            fraction = min(1.0, max(0.0, float(max_fraction)))
        except Exception:
            fraction = 0.5
        maximum = axis if fraction <= 0.0 else max(1.0, axis * fraction)
        if extent is None:
            size = max(1.0, axis * 0.5)
        else:
            try:
                size = max(1.0, float(extent))
            except Exception:
                return None
        size = min(size, maximum, axis)
        if area == "left":
            return (x, y, size, height)
        if area == "right":
            return (x + width - size, y, size, height)
        if area == "top":
            return (x, y, width, size)
        return (x, y + height - size, width, size)
