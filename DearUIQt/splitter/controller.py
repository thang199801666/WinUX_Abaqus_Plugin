"""Toolkit-independent splitter interaction controller.

The controller owns drag state and geometry policy but deliberately has no
knowledge of Dear PyGui, application panes, native windows, or docking. A renderer
only needs to supply pointer positions and the current container extent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import model as _splitter_model

SplitterSizes = _splitter_model.SplitterSizes
SplitterState = _splitter_model.SplitterState


class SplitterAxis(str, Enum):
    """Axis along which the two panes are laid out."""

    X = "x"
    Y = "y"


@dataclass(frozen=True)
class SplitterPolicy:
    """Reusable sizing and hit-target policy for one splitter."""

    separator_size: int = 4
    min_first: int = 1
    min_second: int = 1
    hit_padding: int = 6
    constrained_min_fraction: float = 0.30
    constrained_max_fraction: float = 0.70

    def __post_init__(self) -> None:
        object.__setattr__(self, "separator_size", max(0, int(self.separator_size)))
        object.__setattr__(self, "min_first", max(1, int(self.min_first)))
        object.__setattr__(self, "min_second", max(1, int(self.min_second)))
        object.__setattr__(self, "hit_padding", max(0, int(self.hit_padding)))


@dataclass
class SplitterController:
    """Backend-neutral drag controller for a two-pane splitter.

    ``begin_drag`` can preserve the exact pointer-to-divider offset, preventing
    the divider from jumping when a user grabs near either edge of a wide hit
    target. ``update_drag`` then updates :class:`SplitterState` directly.
    """

    axis: SplitterAxis | str = SplitterAxis.X
    state: SplitterState = field(default_factory=SplitterState)
    policy: SplitterPolicy = field(default_factory=SplitterPolicy)
    dragging: bool = False
    _drag_offset: float = 0.0

    def __post_init__(self) -> None:
        self.axis = SplitterAxis(self.axis)

    @property
    def ratio(self) -> float:
        return self.state.ratio

    def set_ratio(self, ratio: float) -> float:
        return self.state.set_ratio(ratio)

    def sizes(self, total_extent: int) -> SplitterSizes:
        p = self.policy
        return self.state.sizes(
            total_extent,
            separator_size=p.separator_size,
            min_first=p.min_first,
            min_second=p.min_second,
            constrained_min_fraction=p.constrained_min_fraction,
            constrained_max_fraction=p.constrained_max_fraction,
        )

    def divider_position(self, total_extent: int) -> int:
        """Return the first pixel occupied by the separator."""
        return self.sizes(total_extent).first

    def hit_test(
        self,
        pointer_position: float,
        total_extent: int,
        *,
        padding: int | None = None,
    ) -> bool:
        """Test a one-dimensional pointer coordinate against the divider."""
        p = self.policy
        pad = p.hit_padding if padding is None else max(0, int(padding))
        start = float(self.divider_position(total_extent))
        end = start + float(p.separator_size)
        pointer = float(pointer_position)
        return (start - pad) <= pointer <= (end + pad)

    def begin_drag(
        self,
        pointer_position: float,
        total_extent: int,
        *,
        preserve_pointer_offset: bool = True,
    ) -> bool:
        """Begin a drag and remember where inside the separator it was grabbed."""
        divider = float(self.divider_position(total_extent))
        self._drag_offset = (
            float(pointer_position) - divider if preserve_pointer_offset else 0.0
        )
        self.dragging = True
        return True

    def update_drag(self, pointer_position: float, total_extent: int) -> float:
        """Update the ratio from the current pointer coordinate."""
        if not self.dragging:
            return self.state.ratio
        position = float(pointer_position) - self._drag_offset
        return self.state.drag_to(
            position,
            total_extent,
            separator_size=self.policy.separator_size,
        )

    def end_drag(self) -> bool:
        """Finish the active drag and report whether one was active."""
        was_dragging = self.dragging
        self.dragging = False
        self._drag_offset = 0.0
        return was_dragging

    def cancel_drag(self) -> bool:
        return self.end_drag()


__all__ = [
    "SplitterAxis",
    "SplitterPolicy",
    "SplitterController",
]
