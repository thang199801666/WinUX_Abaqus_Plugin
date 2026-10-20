"""Toolkit-independent splitter geometry and state.

This module is the portable splitter core.  It deliberately knows nothing about
application panes, Dear PyGui item tags, docking, jobs, plots, or dialogs. A renderer
can consume :class:`SplitterState` and :func:`split_extent` in any project.
"""
from __future__ import annotations

from dataclasses import dataclass


def clamp_ratio(value: float, minimum: float = 0.05, maximum: float = 0.95) -> float:
    """Clamp a splitter ratio to a safe inclusive range."""
    minimum = float(minimum)
    maximum = float(maximum)
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    return min(max(float(value), minimum), maximum)


@dataclass(frozen=True)
class SplitterSizes:
    """Resolved sizes for the two panes around one separator."""

    first: int
    second: int
    separator: int
    available: int

    @property
    def total(self) -> int:
        return self.first + self.separator + self.second

    def as_tuple(self) -> tuple[int, int]:
        return self.first, self.second



def split_extent(
    total_extent: int,
    ratio: float,
    *,
    separator_size: int = 4,
    min_first: int = 1,
    min_second: int = 1,
    min_ratio: float = 0.05,
    max_ratio: float = 0.95,
    constrained_min_fraction: float = 0.30,
    constrained_max_fraction: float = 0.70,
) -> SplitterSizes:
    """Resolve pane sizes while preserving useful bounds in tight spaces.

    If both requested minimum pane sizes fit, they are enforced exactly.  When
    the container is too small, the splitter falls back to fractional bounds so
    neither side collapses completely. This mirrors a conventional desktop splitter policy
    while remaining independent of any application layout.
    """
    separator = max(0, int(separator_size))
    available = max(2, int(total_extent) - separator)
    normalized = clamp_ratio(ratio, min_ratio, max_ratio)
    desired = int(round(available * normalized))

    first_minimum = max(1, int(min_first))
    second_minimum = max(1, int(min_second))
    if available >= first_minimum + second_minimum:
        lower = first_minimum
        upper = available - second_minimum
    else:
        lower_fraction = min(max(float(constrained_min_fraction), 0.0), 1.0)
        upper_fraction = min(max(float(constrained_max_fraction), 0.0), 1.0)
        if lower_fraction > upper_fraction:
            lower_fraction, upper_fraction = upper_fraction, lower_fraction
        lower = max(1, int(round(available * lower_fraction)))
        upper = max(lower, int(round(available * upper_fraction)))
        upper = min(available - 1, upper)
        lower = min(lower, upper)

    first = min(max(desired, lower), upper)
    second = max(1, available - first)
    return SplitterSizes(
        first=first,
        second=second,
        separator=separator,
        available=available,
    )


@dataclass
class SplitterState:
    """Reusable mutable state for a two-pane splitter.

    Renderers can persist one state object, call :meth:`drag_to` from pointer
    input, then call :meth:`sizes` whenever the host container changes size.
    """

    ratio: float = 0.5
    min_ratio: float = 0.05
    max_ratio: float = 0.95

    def __post_init__(self) -> None:
        self.ratio = clamp_ratio(self.ratio, self.min_ratio, self.max_ratio)

    def set_ratio(self, ratio: float) -> float:
        self.ratio = clamp_ratio(ratio, self.min_ratio, self.max_ratio)
        return self.ratio

    def drag_to(
        self,
        position: float,
        total_extent: float,
        *,
        separator_size: int = 0,
    ) -> float:
        """Update the ratio from a pointer position in host-local coordinates."""
        available = max(1.0, float(total_extent) - max(0, int(separator_size)))
        return self.set_ratio(float(position) / available)

    def sizes(
        self,
        total_extent: int,
        *,
        separator_size: int = 4,
        min_first: int = 1,
        min_second: int = 1,
        constrained_min_fraction: float = 0.30,
        constrained_max_fraction: float = 0.70,
    ) -> SplitterSizes:
        return split_extent(
            total_extent,
            self.ratio,
            separator_size=separator_size,
            min_first=min_first,
            min_second=min_second,
            min_ratio=self.min_ratio,
            max_ratio=self.max_ratio,
            constrained_min_fraction=constrained_min_fraction,
            constrained_max_fraction=constrained_max_fraction,
        )


__all__ = [
    "SplitterSizes",
    "SplitterState",
    "clamp_ratio",
    "split_extent",
]
