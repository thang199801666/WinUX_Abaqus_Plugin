"""Backend-independent responsive/adaptive ribbon allocation.

The layout engine contains no DearPyGui or application-specific knowledge.  It
can therefore be reused by every Ribbon display template and unit-tested without
a GUI context.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RibbonLayout:
    """Legacy visible/overflow layout result kept for API compatibility."""

    visible: tuple[str, ...]
    overflow: tuple[str, ...]
    required_width: int


@dataclass(frozen=True)
class RibbonGroupLayout:
    """Adaptive visual state selected for one group."""

    key: str
    state: str
    width: int

    @property
    def visible(self) -> bool:
        return self.state != "collapsed"


@dataclass(frozen=True)
class RibbonAdaptiveLayout:
    """Adaptive result containing the selected visual state of every group."""

    groups: tuple[RibbonGroupLayout, ...]
    required_width: int

    @property
    def visible(self) -> tuple[str, ...]:
        return tuple(group.key for group in self.groups if group.visible)

    @property
    def overflow(self) -> tuple[str, ...]:
        return tuple(group.key for group in self.groups if not group.visible)

    def state_for(self, key: str, default: str | None = None) -> str | None:
        key = str(key)
        for group in self.groups:
            if group.key == key:
                return group.state
        return default

    def width_for(self, key: str, default: int | None = None) -> int | None:
        key = str(key)
        for group in self.groups:
            if group.key == key:
                return group.width
        return default


class RibbonLayoutEngine:
    """Allocate ribbon groups without requiring a GUI backend.

    ``allocate`` preserves the original all-or-overflow behaviour.
    ``allocate_adaptive`` progressively reduces groups through
    ``large -> medium -> small -> collapsed`` before resorting to overflow.
    """

    def __init__(self, *, separator_width=7, gap=2, overflow_width=65, padding=10):
        self.separator_width = max(0, int(separator_width))
        self.gap = max(0, int(gap))
        self.overflow_width = max(1, int(overflow_width))
        self.padding = max(0, int(padding))

    def allocate(self, groups, available_width):
        """Allocate whole groups; ``groups`` is ``(key, measured_width)`` pairs."""
        items = [(str(key), max(1, int(width))) for key, width in groups]
        capacity = max(0, int(available_width) - self.padding)
        sizes = [width + self.separator_width + self.gap for _, width in items]
        total = sum(sizes)
        if total <= capacity:
            return RibbonLayout(tuple(key for key, _ in items), (), total)
        used = 0
        visible = []
        for i, (key, _) in enumerate(items):
            remaining = len(items) - i - 1
            # Always reserve room for the overflow button when anything collapses.
            required = sizes[i] + (self.overflow_width if remaining else 0)
            if used + required > capacity:
                break
            used += sizes[i]
            visible.append(key)
        collapsed = tuple(key for key, _ in items[len(visible):])
        return RibbonLayout(
            tuple(visible), collapsed,
            used + (self.overflow_width if collapsed else 0),
        )

    def allocate_adaptive(
        self,
        groups,
        available_width,
        *,
        medium_scale: float = 0.84,
        small_scale: float = 0.68,
        medium_min_width: int = 64,
        small_min_width: int = 48,
    ) -> RibbonAdaptiveLayout:
        """Progressively reduce groups until the ribbon fits.

        Reduction is deterministic and keeps application content out of the
        template layer.  Trailing groups reduce first, matching common desktop
        ribbon behaviour and preserving the left-most primary tools for longer.
        A complete pass to ``medium`` is made before any group becomes ``small``;
        overflow is used only after all visible groups have reached ``small``.
        """
        medium_scale = float(medium_scale)
        small_scale = float(small_scale)
        if not 0 < small_scale <= medium_scale <= 1.0:
            raise ValueError("adaptive scales must satisfy 0 < small <= medium <= 1")
        medium_min_width = max(1, int(medium_min_width))
        small_min_width = max(1, int(small_min_width))

        items = []
        for key, width in groups:
            natural = max(1, int(width))
            medium = min(natural, max(medium_min_width, int(round(natural * medium_scale))))
            small = min(medium, max(small_min_width, int(round(natural * small_scale))))
            items.append({
                "key": str(key),
                "large": natural,
                "medium": medium,
                "small": small,
                "state": "large",
            })

        capacity = max(0, int(available_width) - self.padding)

        def required_width() -> int:
            visible = [item for item in items if item["state"] != "collapsed"]
            used = sum(
                int(item[item["state"]]) + self.separator_width + self.gap
                for item in visible
            )
            if len(visible) != len(items):
                used += self.overflow_width
            return used

        def result() -> RibbonAdaptiveLayout:
            groups_out = tuple(
                RibbonGroupLayout(
                    item["key"], item["state"],
                    0 if item["state"] == "collapsed" else int(item[item["state"]]),
                )
                for item in items
            )
            return RibbonAdaptiveLayout(groups_out, required_width())

        if required_width() <= capacity:
            return result()

        # Keep the reduction visually balanced: all groups may reach medium
        # before any group is forced down to small.
        for target_state in ("medium", "small"):
            for item in reversed(items):
                if item["state"] == "collapsed":
                    continue
                item["state"] = target_state
                if required_width() <= capacity:
                    return result()

        # Only after all visible groups are at their smallest state do we move
        # whole groups into overflow, again starting from the trailing edge.
        for item in reversed(items):
            item["state"] = "collapsed"
            if required_width() <= capacity:
                return result()

        return result()


__all__ = [
    "RibbonLayout", "RibbonGroupLayout", "RibbonAdaptiveLayout", "RibbonLayoutEngine",
]
