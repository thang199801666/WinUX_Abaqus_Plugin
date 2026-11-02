from __future__ import annotations

import math
from dataclasses import dataclass

from ..models import AxisScale

@dataclass(frozen=True)
class TickReading:
    position: float
    value: float
    text: str
    confidence: float
    bbox: tuple[int, int, int, int]


@dataclass(frozen=True)
class AxisTickDetection:
    axis: str
    ticks: tuple[TickReading, ...]
    confidence: float
    scale: AxisScale
    unread_positions: tuple[float, ...] = ()
    mark_positions: tuple[float, ...] = ()

    @property
    def ready(self) -> bool:
        values = [tick.value for tick in sorted(self.ticks, key=lambda tick: tick.position)]
        monotonic = (len(values) >= 2 and all(math.isfinite(value) for value in values) and
                     (all(b > a for a, b in zip(values, values[1:])) or
                      all(b < a for a, b in zip(values, values[1:]))))
        positive = self.scale not in (AxisScale.LOG10, AxisScale.LN) or all(value > 0 for value in values)
        return monotonic and positive and ((len(self.ticks) >= 3 and self.confidence >= .42)
                                           or (len(self.ticks) == 2 and self.confidence >= .72))


@dataclass(frozen=True)
class TickCalibrationDetection:
    x: AxisTickDetection
    y: AxisTickDetection
    aligned_rect: tuple[int, int, int, int] | None = None

    @property
    def ready(self) -> bool:
        return self.x.ready and self.y.ready
