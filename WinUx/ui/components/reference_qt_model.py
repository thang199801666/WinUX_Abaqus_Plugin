"""Qt model adapter for the sparse Reference Chart worksheet.

The domain ``ReferenceTableModel`` stays independent of the UI toolkit.  This
read-through adapter exposes its rows using QAbstractTableModel roles/signals;
no XY data or QTableWidgetItem objects are copied when attaching a saved chart.
The current worksheet renderer remains item-based until native viewport
virtualization can be validated on Windows.
"""
from __future__ import annotations

from DearUIQt.core import QAbstractTableModel, QModelIndex, Qt


class ReferenceWorksheetQtModel(QAbstractTableModel):
    """Two editable X/Y columns backed by a sparse ``ReferenceTableModel``."""

    def __init__(self, worksheet, parent=None):
        super().__init__(parent=parent)
        self._worksheet = worksheet
        self._reported_rows = int(worksheet.row_count)

    @property
    def worksheet(self):
        return self._worksheet

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._reported_rows

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 2

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and int(section) in (0, 1):
            return ("X", "Y")[int(section)]
        if orientation == Qt.Vertical and 0 <= int(section) < self._reported_rows:
            return str(int(section) + 1)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if (not isinstance(index, QModelIndex) or not index.isValid() or
                index.model() is not self or not self.hasIndex(index.row(), index.column())):
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            return self._worksheet.cell_text(index.row(), index.column())
        return None

    def flags(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid() or index.model() is not self:
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def setData(self, index, value, role=Qt.EditRole):
        if (role != Qt.EditRole or not isinstance(index, QModelIndex) or
                not index.isValid() or index.model() is not self or
                not self.hasIndex(index.row(), index.column())):
            return False
        if not self._worksheet.set_cell_text(index.row(), index.column(), value):
            return False
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        return True

    def row_text(self, row):
        """Fast two-cell read path for time-sliced native row construction."""
        return self._worksheet.row_text(row)

    def synchronize_row_count(self):
        """Publish rows added or removed by paste/add-row operations.

        Domain edits may precede this call.  ``_reported_rows`` keeps the model
        count stable until Qt's begin/end change notifications are emitted.
        """
        updated = int(self._worksheet.row_count)
        previous = self._reported_rows
        if updated > previous:
            self.beginInsertRows(QModelIndex(), previous, updated - 1)
            self._reported_rows = updated
            self.endInsertRows()
        elif updated < previous:
            self.beginRemoveRows(QModelIndex(), updated, previous - 1)
            self._reported_rows = updated
            self.endRemoveRows()
        return updated != previous

    def notify_cells_changed(self, first_row, last_row, first_column=0, last_column=1):
        """Notify model-aware consumers without constructing a cell cache."""
        self.synchronize_row_count()
        first = max(0, int(first_row))
        last = min(self._reported_rows - 1, int(last_row))
        left, right = max(0, int(first_column)), min(1, int(last_column))
        if first > last or left > right:
            return False
        self.dataChanged.emit(self.index(first, left), self.index(last, right),
                              [Qt.DisplayRole, Qt.EditRole])
        return True

    def reset_worksheet(self, worksheet=None):
        """Reset indexes when selecting or replacing a different XY series."""
        self.beginResetModel()
        if worksheet is not None:
            self._worksheet = worksheet
        self._reported_rows = int(self._worksheet.row_count)
        self.endResetModel()
