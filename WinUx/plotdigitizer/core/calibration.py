from __future__ import annotations

import math
from dataclasses import dataclass, field
from .models import AxisAnchor, AxisScale


@dataclass
class Calibration:
    x1: AxisAnchor | None = None
    x2: AxisAnchor | None = None
    y1: AxisAnchor | None = None
    y2: AxisAnchor | None = None
    scale_x: AxisScale = AxisScale.LINEAR
    scale_y: AxisScale = AxisScale.LINEAR
    points_x: list[AxisAnchor] = field(default_factory=list)
    points_y: list[AxisAnchor] = field(default_factory=list)
    mapping_x: str = "fit"
    mapping_y: str = "fit"
    box_rect: tuple[float, float, float, float] | None = None
    snap_to_axes: bool = True

    def _sync_box_axis(self, axis):
        """Corner handles are a view of the mapping, never extra OCR samples."""
        left, top, right, bottom = self.box_rect
        # A drawn Box can miss the printed zero stroke by a few pixels. Snap
        # its origin to an OBSERVED zero, not to an extrapolated negative value.
        for name, coordinate, edge in ((('x', 'px', left), ('y', 'py', bottom))
                                       if self.snap_to_axes else ()):
            points = getattr(self, 'points_' + name)
            if getattr(self, 'scale_' + name) != AxisScale.LINEAR or len(points) < 2:
                continue
            positions = sorted(getattr(p, coordinate) for p in points)
            steps = [b - a for a, b in zip(positions, positions[1:]) if b > a]
            tolerance = max(4.0, min(6.0, min(steps) * .10)) if steps else 4.0
            zero = next((p for p in points if p.value == 0 and abs(getattr(p, coordinate) - edge) <= tolerance), None)
            if zero is not None:
                if name == 'x':
                    left = zero.px
                else:
                    bottom = zero.py
        self.box_rect = (left, top, right, bottom)
        # Refresh both axes: discovering Y=0 must move X1 to that same corner.
        for key, px, py in (('x1', left, bottom), ('x2', right, bottom),
                            ('y1', left, bottom), ('y2', left, top)):
            axis = key[0]
            if len(getattr(self, 'points_' + axis)) < 2:
                previous = getattr(self, key)
                if previous is not None:
                    setattr(self, key, AxisAnchor(px, py, previous.value))
                continue
            pixel = px if axis == 'x' else py
            value = self._piecewise(axis, pixel)
            if value is None:
                fit = self._fit(axis)
                if fit is None:
                    continue
                value = fit[0] * pixel + fit[1]
                if getattr(self, 'scale_' + axis) in (AxisScale.LOG10, AxisScale.LN):
                    value = math.exp(value)
            setattr(self, key, AxisAnchor(px, py, value))

    def _piecewise(self, axis, value, inverse=False):
        if getattr(self, "mapping_" + axis) != "ticks":
            return None
        points = self.axis_points(axis)
        if len(points) < 2:
            return None
        coordinate = "px" if axis == "x" else "py"
        scale = getattr(self, "scale_" + axis)
        logarithmic = scale in (AxisScale.LOG10, AxisScale.LN)
        samples = [(getattr(a, coordinate), math.log(a.value) if logarithmic else a.value)
                   for a in points]
        if inverse:
            if logarithmic:
                if value <= 0:
                    raise ValueError("Logarithmic point values must be > 0.")
                value = math.log(value)
            samples = [(v, p) for p, v in samples]
        samples.sort()
        index = next((i for i in range(len(samples) - 1) if value <= samples[i + 1][0]), len(samples) - 2)
        (p1, v1), (p2, v2) = samples[index:index + 2]
        result = v1 + (value - p1) * (v2 - v1) / (p2 - p1)
        return math.exp(result) if logarithmic and not inverse else result

    def axis_points(self, axis):
        if axis not in ("x", "y"):
            raise ValueError("Unknown calibration axis.")
        points = getattr(self, "points_" + axis)
        return list(points) if points else [a for a in
            (getattr(self, axis + "1"), getattr(self, axis + "2")) if a is not None]

    def _fit(self, axis):
        points = getattr(self, "points_" + axis)
        if len(points) < 2:
            return None
        coordinate = "px" if axis == "x" else "py"
        scale = getattr(self, "scale_" + axis)
        logarithmic = scale in (AxisScale.LOG10, AxisScale.LN)
        samples = [(getattr(a, coordinate), math.log(a.value)
                    if logarithmic else a.value) for a in points]
        mp = sum(p for p, _ in samples) / len(samples)
        mv = sum(v for _, v in samples) / len(samples)
        denominator = sum((p - mp) ** 2 for p, _ in samples)
        if denominator <= 1e-12:
            raise ValueError("Calibration points must span distinct pixels.")
        slope = sum((p - mp) * (v - mv) for p, v in samples) / denominator
        if abs(slope) < 1e-15:
            raise ValueError("Calibration points must span distinct values.")
        return slope, mv - slope * mp

    def set_axis_points(self, axis, points, *, sync_anchors=False):
        """Set measured ticks; optionally derive legacy endpoints for manual lists.

        Box corner handles stay on the Box; their values are evaluated from
        the measured mapping. They never become extra measured samples.
        """
        if axis not in ("x", "y"):
            raise ValueError("Unknown calibration axis.")
        key = "points_" + axis
        previous = (getattr(self, key), getattr(self, axis + "1"), getattr(self, axis + "2"))
        setattr(self, key, list(points))
        # Legacy endpoint anchors remain a compatibility view for old projects,
        # plot bounds and two-point tools. All transforms use the full list.
        if sync_anchors:
            if self.box_rect is not None and len(getattr(self, key)) >= 2:
                self._sync_box_axis(axis)
            else:
                ordered = sorted(getattr(self, key), key=lambda p: p.px if axis == "x" else -p.py)
                setattr(self, axis + "1", ordered[0] if ordered else None)
                setattr(self, axis + "2", ordered[-1] if len(ordered) >= 2 else None)
        try:
            self.validate()
        except ValueError:
            setattr(self, key, previous[0])
            setattr(self, axis + "1", previous[1])
            setattr(self, axis + "2", previous[2])
            raise
        if self.box_rect is not None:
            left, _, _, bottom = self.box_rect
            # Only move the perpendicular display coordinate. The observed
            # axis pixel/value stays untouched, including both zero readings.
            self.points_x = [AxisAnchor(p.px, bottom, p.value) for p in self.points_x]
            self.points_y = [AxisAnchor(left, p.py, p.value) for p in self.points_y]

    def ready(self) -> bool:
        if not all((self.x1, self.x2, self.y1, self.y2)):
            return False
        try:
            self.validate()
        except ValueError:
            return False
        return True

    def validate(self) -> None:
        """Validate even partially populated axes before committing UI edits."""
        if not isinstance(self.snap_to_axes, bool):
            raise ValueError('Snap to Axes must be a boolean.')
        for first, second, coordinate, scale in (
            (self.x1, self.x2, "px", self.scale_x),
            (self.y1, self.y2, "py", self.scale_y),
        ):
            for anchor in (first, second):
                if anchor is None:
                    continue
                if not all(math.isfinite(v) for v in (anchor.px, anchor.py, anchor.value)):
                    raise ValueError("Calibration coordinates and values must be finite.")
                if scale in (AxisScale.LOG10, AxisScale.LN) and anchor.value <= 0:
                    raise ValueError("Logarithmic calibration values must be > 0.")
            if first is not None and second is not None:
                if abs(getattr(second, coordinate) - getattr(first, coordinate)) < 1e-12:
                    raise ValueError("Calibration anchors cannot share the same pixel coordinate.")
                if first.value == second.value:
                    raise ValueError("Calibration anchors must have different axis values.")
        for axis in ("x", "y"):
            if getattr(self, "mapping_" + axis) not in ("fit", "ticks"):
                raise ValueError("Unknown calibration mapping.")
            coordinates = []
            for anchor in getattr(self, "points_" + axis):
                if not all(math.isfinite(v) for v in (anchor.px, anchor.py, anchor.value)):
                    raise ValueError("Calibration coordinates and values must be finite.")
                if getattr(self, "scale_" + axis) in (AxisScale.LOG10, AxisScale.LN) and anchor.value <= 0:
                    raise ValueError("Logarithmic calibration values must be > 0.")
                coordinates.append(anchor.px if axis == "x" else anchor.py)
            coordinates.sort()
            if any(abs(b - a) < 1e-12 for a, b in zip(coordinates, coordinates[1:])):
                raise ValueError("Calibration points cannot share the same axis pixel coordinate.")
            if getattr(self, "mapping_" + axis) == "ticks":
                ordered = sorted(self.axis_points(axis), key=lambda a: a.px if axis == "x" else a.py)
                differences = [b.value - a.value for a, b in zip(ordered, ordered[1:])]
                if differences and not (all(d > 0 for d in differences) or all(d < 0 for d in differences)):
                    raise ValueError("Tick values must be strictly monotonic.")
            else:
                self._fit(axis)

    def set_anchor(self, key: str, px: float, py: float, value: float) -> None:
        if key not in {"x1", "x2", "y1", "y2"}:
            raise KeyError(f"Unknown calibration anchor: {key}")
        previous = getattr(self, key)
        setattr(self, key, AxisAnchor(float(px), float(py), float(value)))
        try:
            self.validate()
        except ValueError:
            setattr(self, key, previous)
            raise
        # An explicit anchor edit replaces the automatic multi-point fit.
        getattr(self, "points_" + key[0]).clear()
        self.box_rect = None

    def clear_anchor(self, key: str) -> None:
        if key not in {"x1", "x2", "y1", "y2"}:
            raise KeyError(f"Unknown calibration anchor: {key}")
        setattr(self, key, None)
        getattr(self, "points_" + key[0]).clear()

    @staticmethod
    def _map(p: float, p1: float, v1: float, p2: float, v2: float, scale: AxisScale) -> float:
        if abs(p2 - p1) < 1e-12:
            raise ValueError("Calibration anchors cannot share the same pixel coordinate.")
        t = (p - p1) / (p2 - p1)
        if scale == AxisScale.LOG10:
            if v1 <= 0 or v2 <= 0:
                raise ValueError("Log10 calibration values must be > 0.")
            return 10 ** (math.log10(v1) + t * (math.log10(v2) - math.log10(v1)))
        if scale == AxisScale.LN:
            if v1 <= 0 or v2 <= 0:
                raise ValueError("Ln calibration values must be > 0.")
            return math.exp(math.log(v1) + t * (math.log(v2) - math.log(v1)))
        return v1 + t * (v2 - v1)

    def pixel_to_data(self, px: float, py: float) -> tuple[float, float]:
        if not self.ready():
            raise ValueError("Axis calibration is incomplete.")
        assert self.x1 and self.x2 and self.y1 and self.y2
        x = self._map(px, self.x1.px, self.x1.value, self.x2.px, self.x2.value, self.scale_x)
        y = self._map(py, self.y1.py, self.y1.value, self.y2.py, self.y2.value, self.scale_y)
        for axis, pixel in (("x", px), ("y", py)):
            mapped = self._piecewise(axis, pixel)
            fit = self._fit(axis) if mapped is None else None
            if mapped is not None:
                if axis == "x":
                    x = mapped
                else:
                    y = mapped
            if fit is not None:
                value = fit[0] * pixel + fit[1]
                if getattr(self, "scale_" + axis) in (AxisScale.LOG10, AxisScale.LN):
                    value = math.exp(value)
                if axis == "x":
                    x = value
                else:
                    y = value
        return x, y

    def data_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        if not self.ready():
            raise ValueError("Axis calibration is incomplete.")
        assert self.x1 and self.x2 and self.y1 and self.y2

        def inverse(value, first, second, coordinate, scale):
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("Point values must be finite.")
            mapped = self._piecewise("x" if coordinate == "px" else "y", value, inverse=True)
            if mapped is not None:
                return mapped
            fit = self._fit("x" if coordinate == "px" else "y")
            if fit is not None:
                if scale in (AxisScale.LOG10, AxisScale.LN):
                    if value <= 0:
                        raise ValueError("Logarithmic point values must be > 0.")
                    value = math.log(value)
                return (value - fit[1]) / fit[0]
            a, b = first.value, second.value
            if scale in (AxisScale.LOG10, AxisScale.LN):
                if value <= 0:
                    raise ValueError("Logarithmic point values must be > 0.")
                value, a, b = math.log(value), math.log(a), math.log(b)
            t = (value - a) / (b - a)
            return getattr(first, coordinate) + t * (getattr(second, coordinate) - getattr(first, coordinate))

        return (inverse(x, self.x1, self.x2, "px", self.scale_x),
                inverse(y, self.y1, self.y2, "py", self.scale_y))

    def to_dict(self) -> dict:
        def pack(a: AxisAnchor | None):
            return None if a is None else {"px": a.px, "py": a.py, "value": a.value}
        return {
            "x1": pack(self.x1), "x2": pack(self.x2),
            "y1": pack(self.y1), "y2": pack(self.y2),
            "scale_x": self.scale_x.value,
            "scale_y": self.scale_y.value,
            "points_x": [pack(a) for a in self.points_x],
            "points_y": [pack(a) for a in self.points_y],
            "mapping_x": self.mapping_x,
            "mapping_y": self.mapping_y,
            "box_rect": self.box_rect,
            "snap_to_axes": self.snap_to_axes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Calibration":
        def unpack(v):
            return AxisAnchor(**v) if v else None
        return cls(
            x1=unpack(data.get("x1")), x2=unpack(data.get("x2")),
            y1=unpack(data.get("y1")), y2=unpack(data.get("y2")),
            scale_x=AxisScale(data.get("scale_x", AxisScale.LINEAR.value)),
            scale_y=AxisScale(data.get("scale_y", AxisScale.LINEAR.value)),
            points_x=[AxisAnchor(**v) for v in data.get("points_x", [])],
            points_y=[AxisAnchor(**v) for v in data.get("points_y", [])],
            mapping_x=data.get("mapping_x", "fit"),
            mapping_y=data.get("mapping_y", "fit"),
            box_rect=tuple(data['box_rect']) if data.get('box_rect') else None,
            snap_to_axes=data.get('snap_to_axes', True),
        )
