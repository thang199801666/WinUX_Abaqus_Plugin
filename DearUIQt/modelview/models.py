"""Backend-independent item-view data models and selection state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

@dataclass(frozen=True)
class QtGridColumn:
    key: str
    label: str
    width: float | None = None
    stretch: float = 1.0
    align: str = "left"
    sortable: bool = True


@dataclass(frozen=True)
class QtGridRow:
    """One stable row in :class:`QtDataGridView`.

    ``background`` is an optional RGBA tuple used for status/category tinting.
    ``data`` is intentionally opaque application metadata; the view never
    interprets it. This mirrors Qt's model roles without forcing callers
    to build a full ``QAbstractItemModel`` for simple flat grids.
    """

    key: Any
    values: Sequence[Any]
    data: Any = None
    enabled: bool = True
    background: Any = None


@dataclass(frozen=True)
class QtListItem:
    key: Any
    text: str
    data: Any = None
    enabled: bool = True
    checked: bool | None = None


class QtSelectionMode:
    SingleSelection = "single"
    ExtendedSelection = "extended"


class QtItemViewState:
    """Backend-independent current/anchor/selection state.

    The state mirrors the commonly used parts of ``QItemSelectionModel``. It is
    deliberately testable without a GUI backend.
    """

    def __init__(self, multiple=False):
        self.multiple = bool(multiple)
        self.keys: list[Any] = []
        # Keep stable first-occurrence indexes. With 100k+ rows, keyboard
        # movement/Shift selection must not linearly scan keys on every event.
        self._key_index: dict[Any, int] = {}
        self.selected: set[Any] = set()
        self.current: Any = None
        self.anchor: Any = None

    def replace(self, keys: Iterable[Any]):
        keys = list(keys)
        # Polling models may replace their row payload every frame without
        # changing row identity. Reuse the index for those refreshes; list
        # equality is cheaper than rebuilding a 100k-entry dictionary.
        if keys != self.keys:
            index = {}
            for position, key in enumerate(keys):
                index.setdefault(key, position)
            self._key_index = index
            self.keys = keys
        valid = self._key_index.keys()
        self.selected.intersection_update(valid)
        if self.current not in valid:
            self.current = keys[0] if keys else None
        if self.anchor not in valid:
            self.anchor = self.current
        return self

    def clear(self):
        self.selected.clear()

    def select(self, key, *, ctrl=False, shift=False, selected=True):
        if key not in self._key_index:
            return False
        old = set(self.selected)
        if not self.multiple:
            # Qt SingleSelection keeps the clicked row selected even when an
            # underlying toggle-style primitive reports its previous state.
            self.selected = {key}
        elif shift and self.anchor in self._key_index:
            first, last = sorted((self._key_index[self.anchor], self._key_index[key]))
            if not ctrl:
                self.selected.clear()
            self.selected.update(self.keys[first:last + 1])
        elif ctrl:
            if selected:
                self.selected.add(key)
            else:
                self.selected.discard(key)
        else:
            # A plain click in ExtendedSelection starts a new one-row
            # selection; only Ctrl-click toggles a row off.
            self.selected = {key}
        self.current = key
        if not shift:
            self.anchor = key
        return old != self.selected

    def select_all(self):
        if self.multiple:
            self.selected = set(self.keys)

    def move(self, delta=0, *, absolute=None, ctrl=False, shift=False):
        if not self.keys:
            return None, False
        old_selection = set(self.selected)
        old_current = self.current
        index = self._key_index.get(self.current, 0)
        if absolute is not None:
            next_index = max(0, min(len(self.keys) - 1, int(absolute)))
        else:
            next_index = max(0, min(len(self.keys) - 1, index + int(delta)))
        key = self.keys[next_index]
        self.current = key
        if shift and self.multiple:
            anchor_index = self._key_index.get(self.anchor, index)
            first, last = sorted((anchor_index, next_index))
            if not ctrl:
                self.selected.clear()
            self.selected.update(self.keys[first:last + 1])
        elif not ctrl:
            self.selected = {key}
            self.anchor = key
        return key, old_selection != self.selected or old_current != self.current

__all__ = [
    "QtGridColumn", "QtGridRow", "QtListItem", "QtSelectionMode", "QtItemViewState",
]
