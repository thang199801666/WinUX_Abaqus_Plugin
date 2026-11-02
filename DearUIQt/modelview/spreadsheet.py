"""Backend-independent spreadsheet selection and transactional clipboard commands.

Adapters own validation/persistence/undo. A write callback receives the entire
batch only after bounds and per-cell edit permissions have been checked.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass(frozen=True)
class CellRange:
    top: int
    left: int
    bottom: int
    right: int

    def __post_init__(self):
        if min(self.top, self.left) < 0 or self.bottom < self.top or self.right < self.left:
            raise ValueError("Invalid cell range")

    @classmethod
    def between(cls, anchor, extent=None):
        r1, c1 = map(int, anchor)
        r2, c2 = map(int, extent if extent is not None else anchor)
        return cls(min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))

    @property
    def bounds(self):
        return self.top, self.left, self.bottom, self.right

    def contains(self, position):
        row, column = position
        return self.top <= row <= self.bottom and self.left <= column <= self.right

    def cells(self):
        return ((row, column) for row in range(self.top, self.bottom + 1)
                for column in range(self.left, self.right + 1))


class SpreadsheetSelection:
    def __init__(self):
        self.anchor = self.current = None

    @property
    def selected_range(self):
        return CellRange.between(self.anchor, self.current) if self.anchor is not None else None

    def clear(self):
        self.anchor = self.current = None

    def select(self, anchor, extent=None, *, shape):
        anchor, extent = tuple(map(int, anchor)), tuple(map(int, extent or anchor))
        rows, columns = shape
        if any(not (0 <= row < rows and 0 <= col < columns) for row, col in (anchor, extent)):
            raise ValueError("Cell selection is outside the table")
        self.anchor, self.current = anchor, extent
        return self.selected_range

    def move(self, dr, dc, *, shape, extend=False, tab=False):
        rows, columns = shape
        if not rows or not columns:
            return None
        row, col = self.current or (0, 0)
        if tab:
            index = max(0, min(rows * columns - 1, row * columns + col + dc))
            target = divmod(index, columns)
        else:
            target = (max(0, min(rows - 1, row + dr)), max(0, min(columns - 1, col + dc)))
        return self.select(self.anchor if extend and self.anchor is not None else target,
                           target, shape=shape)


class SpreadsheetClipboard:
    MAX_CELLS = 1_000_000

    @staticmethod
    def dumps(rows):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        for row in rows:
            writer.writerow(["" if value is None else str(value) for value in row])
        return stream.getvalue()[:-1]  # No extra blank row when pasted into Excel.

    @classmethod
    def loads(cls, text, *, delimiter="\t"):
        text = str(text or "")
        if not text:
            return []
        try:
            rows = []
            count = 0
            for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True):
                values = row or [""]
                count += len(values)
                if count > cls.MAX_CELLS:
                    raise ValueError("Clipboard exceeds the spreadsheet cell limit")
                rows.append(values)
        except csv.Error as exc:
            raise ValueError("Invalid clipboard table: {}".format(exc)) from exc
        width = max((len(row) for row in rows), default=0)
        if width * len(rows) > cls.MAX_CELLS:
            raise ValueError("Clipboard exceeds the spreadsheet cell limit")
        return [row + [""] * (width - len(row)) for row in rows]


class SpreadsheetAdapter:
    """Callback adapter for arbitrary models, including lazy/remote datasets.

    ``write`` must commit the entire batch atomically, or raise without changes.
    No widget-only mutations are used for application-owned data.
    """
    def __init__(self, shape, read, *, write=None, editable=None):
        self._shape, self._read, self._write, self._editable = shape, read, write, editable

    @property
    def shape(self):
        return tuple(map(int, self._shape()))

    @property
    def read_only(self):
        return self._write is None

    def cell_text(self, row, column):
        value = self._read(row, column)
        return "" if value is None else str(value)

    def validate_changes(self, changes):
        if self.read_only:
            raise ValueError("This table is read-only")
        rows, columns = self.shape
        for row, column in changes:
            if not (0 <= row < rows and 0 <= column < columns):
                raise ValueError("Paste does not fit inside the table")
            if self._editable is not None and not self._editable(row, column):
                raise ValueError("The selected range contains a read-only cell")

    def write_cells(self, changes):
        self.validate_changes(changes)
        self._write(dict(changes))


class SpreadsheetController:
    def __init__(self, adapter, clipboard=None):
        self.adapter, self.clipboard = adapter, clipboard
        self.selection = SpreadsheetSelection()

    def select(self, anchor, extent=None):
        return self.selection.select(anchor, extent, shape=self.adapter.shape)

    def select_all(self):
        rows, columns = self.adapter.shape
        if not rows or not columns:
            self.selection.clear()
            return None
        return self.select((0, 0), (rows - 1, columns - 1))

    def copy_text(self, region=None):
        region = region or self.selection.selected_range
        if region is None:
            return ""
        rows, columns = self.adapter.shape
        if region.bottom >= rows or region.right >= columns:
            raise ValueError("The table changed; select the cells again")
        return SpreadsheetClipboard.dumps(
            [self.adapter.cell_text(row, col) for col in range(region.left, region.right + 1)]
            for row in range(region.top, region.bottom + 1))

    def copy(self):
        if self.selection.selected_range is None or self.clipboard is None:
            return False
        return bool(self.clipboard.setText(self.copy_text()))

    def clear(self):
        region = self.selection.selected_range
        if region is None:
            return False
        self.adapter.write_cells({position: "" for position in region.cells()})
        return True

    def cut(self):
        region = self.selection.selected_range
        if region is None:
            return False
        changes = {position: "" for position in region.cells()}
        self.adapter.validate_changes(changes)
        if not self.copy():
            return False  # A busy clipboard must never delete data.
        self.adapter.write_cells(changes)
        return True

    def paste_text(self, text):
        values = SpreadsheetClipboard.loads(text)
        if not values:
            return None
        region = self.selection.selected_range
        top, left = (region.top, region.left) if region is not None else (0, 0)
        if len(values) == len(values[0]) == 1 and region is not None:
            changes = {position: values[0][0] for position in region.cells()}
            result = region
        else:
            result = CellRange(top, left, top + len(values) - 1, left + len(values[0]) - 1)
            changes = {(top + row, left + col): value
                       for row, cells in enumerate(values) for col, value in enumerate(cells)}
        self.adapter.write_cells(changes)
        self.select((result.top, result.left), (result.bottom, result.right))
        return result

    def paste(self):
        return self.paste_text(self.clipboard.text()) if self.clipboard is not None else None
