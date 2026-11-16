"""Qt-like style option for item-view painting state."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QStyleOptionViewItem:
    """Normalized item-view paint state shared by views and delegates.

    The object intentionally stays backend-neutral.  Renderers translate these
    semantic flags into DearPyGui themes, while custom delegates can inspect the
    same state without re-deriving selection/focus/current rules.
    """

    text: str = ""
    decoration: object = None
    toolTip: object = None
    background: object = None
    foreground: object = None
    checkState: object = None
    selected: bool = False
    current: bool = False
    focused: bool = False
    disabled: bool = False
    hovered: bool = False
    index: object = None
    widget: object = None
    rect: object = None

    @property
    def active(self):
        return bool(self.focused)

    @property
    def enabled(self):
        return not bool(self.disabled)

    def stateTuple(self):
        # Compatibility tuple retained from M6g. Hover is a paint-only state
        # and does not change retained selection/focus semantics.
        return (
            bool(self.selected), bool(self.disabled), bool(self.current),
            bool(self.focused),
        )

    def paintStateTuple(self):
        return self.stateTuple() + (bool(self.hovered),)

    def copy(self):
        return QStyleOptionViewItem(**self.__dict__)


__all__ = ["QStyleOptionViewItem"]
