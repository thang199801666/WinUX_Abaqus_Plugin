"""Qt-style box containers preserving Dear ImGui's native layout behavior."""
from .controls import QWidget


class QBoxLayout(QWidget):
    def __init__(self, *, horizontal=False, spacing=7, parent=None, after=None, backend=None):
        backend, options = self._construction(parent, backend)
        tag = backend.add_group(horizontal=bool(horizontal), horizontal_spacing=spacing, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)


class QHBoxLayout(QBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(horizontal=True, **kwargs)


class QVBoxLayout(QBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(horizontal=False, **kwargs)


class QGridLayout(QWidget):
    """Retained table cells; row/column spans are intentionally unsupported."""

    def __init__(self, columns=2, *, column_widths=None, parent=None, after=None, backend=None):
        if not isinstance(columns, int) or isinstance(columns, bool) or columns < 1:
            raise ValueError("grid columns must be a positive integer")
        widths = (None,) * columns if column_widths is None else tuple(column_widths)
        if len(widths) != columns or any(width is not None and (
                not isinstance(width, (int, float)) or isinstance(width, bool) or
                width <= 0 or width != width or width == float('inf')) for width in widths):
            raise ValueError("column widths must match the grid and be positive or None")
        backend, options = self._construction(parent, backend)
        tag = backend.add_table(header_row=False, width=-1,
            policy=backend.mvTable_SizingStretchProp, pad_outerX=False,
            borders_innerH=False, borders_outerH=False,
            borders_innerV=False, borders_outerV=False, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.columns = columns
        self._rows, self._cells = [], {}
        try:
            for width in widths:
                if width is None:
                    backend.add_table_column(parent=tag, width_stretch=True)
                else:
                    backend.add_table_column(parent=tag, width_fixed=True, init_width_or_weight=width)
        except Exception:
            self.delete()
            raise

    def cell(self, row, column):
        """Return an owned box container suitable as a child widget parent."""
        self._require_ui()
        if self._deleted:
            raise RuntimeError("cannot access a deleted grid")
        if (not isinstance(row, int) or isinstance(row, bool) or row < 0 or
                not isinstance(column, int) or isinstance(column, bool) or
                not 0 <= column < self.columns):
            raise ValueError("invalid grid position")
        while len(self._rows) <= row:
            index = len(self._rows)
            native_row = self.backend.add_table_row(parent=self.tag)
            cells = []
            try:
                for _ in range(self.columns):
                    cell = QVBoxLayout(spacing=0, parent=native_row, after=self._after, backend=self.backend)
                    cell.setParent(self)
                    cells.append(cell)
            except Exception:
                for cell in cells:
                    cell.delete()
                self.backend.delete_item(native_row)
                raise
            self._rows.append(native_row)
            self._cells.update(((index, col), cell) for col, cell in enumerate(cells))
        return self._cells[row, column]

    def addWidget(self, widget, row, column):
        self._require_ui()
        if not isinstance(widget, QWidget) or widget._deleted:
            raise ValueError("grid requires a live QWidget")
        widget._require_ui()
        if widget.backend is not self.backend:
            raise ValueError("grid and widget must use the same backend")
        ancestor = self
        while ancestor is not None:
            if ancestor is widget:
                raise ValueError("grid placement cannot contain an ownership cycle")
            ancestor = ancestor.parent
        cell = self.cell(row, column)
        if widget.parent is not cell:
            self.backend.move_item(widget.tag, parent=cell.tag)
            widget.setParent(cell)
        return widget

    def delete(self):
        try:
            super().delete()
        finally:
            # A rejected worker-thread deletion must not mutate the UI caches.
            if self._deleted:
                self._rows.clear()
                self._cells.clear()
