from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


DATASET_MARKER_STYLES = (
    "circle",
    "square",
    "triangle",
    "diamond",
    "plus",
    "cross",
    "star",
    "triangle_down",
)


def normalize_marker_style(style: str | None, default: str = "circle") -> str:
    candidate = str(style or "").strip().lower()
    return candidate if candidate in DATASET_MARKER_STYLES else default


def default_marker_style(index: int = 0) -> str:
    if not DATASET_MARKER_STYLES:
        return "circle"
    return DATASET_MARKER_STYLES[int(index) % len(DATASET_MARKER_STYLES)]


class AxisScale(str, Enum):
    LINEAR = "Linear"
    LOG10 = "Log10"
    LN = "Ln"
    DATETIME = "Date/Time"


@dataclass(slots=True)
class AxisAnchor:
    px: float
    py: float
    value: float


@dataclass(slots=True)
class DataPoint:
    px: float
    py: float
    x: Optional[float] = None
    y: Optional[float] = None
    source: str = "manual"


@dataclass(slots=True)
class ExtractionSettings:
    tolerance: int = 55
    min_hits: int = 1
    continuity: int = 28
    smoothing: int = 3
    stride: int = 1
    minimum_saturation: int = 70
    max_gap_columns: int = 25


@dataclass(slots=True)
class SmartDetectionResult:
    plot_rect: tuple[int, int, int, int] | None = None
    curve_rgb: Optional[tuple[int, int, int]] = None
    extracted_pixels: list[tuple[float, float]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass(slots=True)
class Dataset:
    name: str = "Serie-1"
    visible: bool = True
    locked: bool = False
    marker_style: str = "circle"
    curve_rgb: Optional[tuple[int, int, int]] = None
    extracted_pixels: list[tuple[float, float]] = field(default_factory=list)
    extracted_data: list[tuple[float, float]] = field(default_factory=list)
    manual_points: list[DataPoint] = field(default_factory=list)
    settings: ExtractionSettings = field(default_factory=ExtractionSettings)
    extracted_breaks: Optional[list[int]] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "visible": self.visible,
            "locked": self.locked,
            "marker_style": normalize_marker_style(self.marker_style),
            "curve_rgb": self.curve_rgb,
            "extracted_pixels": self.extracted_pixels,
            "extracted_breaks": self.extracted_breaks,
            "manual_points": [asdict(p) for p in self.manual_points],
            "settings": asdict(self.settings),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Dataset":
        return cls(
            name=data.get("name", "Serie-1"),
            visible=bool(data.get("visible", True)),
            locked=bool(data.get("locked", False)),
            marker_style=normalize_marker_style(data.get("marker_style")),
            curve_rgb=tuple(data["curve_rgb"]) if data.get("curve_rgb") else None,
            extracted_pixels=[tuple(p) for p in data.get("extracted_pixels", [])],
            extracted_breaks=list(data["extracted_breaks"]) if data.get("extracted_breaks") is not None else None,
            manual_points=[DataPoint(**p) for p in data.get("manual_points", [])],
            settings=ExtractionSettings(**data.get("settings", {})),
        )
