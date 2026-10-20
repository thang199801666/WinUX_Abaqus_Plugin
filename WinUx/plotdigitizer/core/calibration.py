from __future__ import annotations

import math
from dataclasses import dataclass
from .models import AxisAnchor, AxisScale


@dataclass
class Calibration:
    x1: AxisAnchor | None = None
    x2: AxisAnchor | None = None
    y1: AxisAnchor | None = None
    y2: AxisAnchor | None = None
    scale_x: AxisScale = AxisScale.LINEAR
    scale_y: AxisScale = AxisScale.LINEAR

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

    def clear_anchor(self, key: str) -> None:
        if key not in {"x1", "x2", "y1", "y2"}:
            raise KeyError(f"Unknown calibration anchor: {key}")
        setattr(self, key, None)

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
        return x, y

    def data_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        if not self.ready():
            raise ValueError("Axis calibration is incomplete.")
        assert self.x1 and self.x2 and self.y1 and self.y2

        def inverse(value, first, second, coordinate, scale):
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("Point values must be finite.")
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
        )
