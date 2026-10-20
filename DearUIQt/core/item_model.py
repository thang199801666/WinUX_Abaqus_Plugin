"""Backend-neutral Qt-style item model primitives.

The model layer intentionally lives in :mod:`DearUIQt.core`, matching Qt's
separation between QtCore models/indexes and QtWidgets views/delegates.  It has
no renderer imports and can therefore be used in services, tests and worker
code without loading DearPyGui.
"""
from __future__ import annotations

from dataclasses import dataclass

from .object import QObject, Signal, Qt


class QModelIndex:
    """Small immutable handle to one item exposed by a QAbstractItemModel."""

    __slots__ = ("_row", "_column", "_model", "_internal_pointer", "_internal_id")

    def __init__(self, row=-1, column=-1, model=None, internal_pointer=None, internal_id=0):
        self._row = int(row)
        self._column = int(column)
        self._model = model
        self._internal_pointer = internal_pointer
        self._internal_id = int(internal_id or 0)

    def row(self):
        return self._row

    def column(self):
        return self._column

    def model(self):
        return self._model

    def isValid(self):
        return self._model is not None and self._row >= 0 and self._column >= 0

    def internalPointer(self):
        return self._internal_pointer

    def internalId(self):
        return self._internal_id

    def parent(self):
        if not self.isValid():
            return QModelIndex()
        return self._model.parent(self)

    def sibling(self, row, column):
        if not self.isValid():
            return QModelIndex()
        return self._model.index(int(row), int(column), self.parent())

    def siblingAtRow(self, row):
        return self.sibling(row, self._column)

    def siblingAtColumn(self, column):
        return self.sibling(self._row, column)

    def data(self, role=Qt.DisplayRole):
        if not self.isValid():
            return None
        return self._model.data(self, role)

    def flags(self):
        if not self.isValid():
            return Qt.NoItemFlags
        return self._model.flags(self)

    def __bool__(self):
        return self.isValid()

    def __repr__(self):
        if not self.isValid():
            return "QModelIndex()"
        return "QModelIndex(row={}, column={}, model={!r})".format(
            self._row, self._column, self._model)

    def __eq__(self, other):
        if not isinstance(other, QModelIndex):
            return NotImplemented
        return (
            self._row == other._row and self._column == other._column and
            self._model is other._model and
            self._internal_pointer is other._internal_pointer and
            self._internal_id == other._internal_id
        )

    def __hash__(self):
        return hash((self._row, self._column, id(self._model),
                     id(self._internal_pointer), self._internal_id))


class QPersistentModelIndex:
    """Light persistent wrapper for models whose row/column identity is stable.

    DearUIQt does not yet remap persistent indexes across arbitrary row moves;
    the wrapper deliberately exposes the familiar API while invalidating itself
    on model reset.  Models with stable internal pointers can recreate indexes
    through ``toModelIndex`` after ordinary data changes.
    """

    def __init__(self, index=None):
        index = index if isinstance(index, QModelIndex) else QModelIndex()
        self._model = index.model()
        self._row = index.row()
        self._column = index.column()
        self._pointer = index.internalPointer()
        self._internal_id = index.internalId()
        self._valid = index.isValid()
        self._reset_connection = None
        if self._model is not None and hasattr(self._model, "modelReset"):
            self._reset_connection = self._model.modelReset.connect(self._invalidate)

    def _invalidate(self, *_args):
        self._valid = False

    def isValid(self):
        return bool(self._valid and self._model is not None)

    def row(self):
        if not self.isValid():
            return -1
        current = getattr(self._pointer, "row", None)
        if callable(current):
            try:
                return int(current())
            except Exception:
                pass
        return self._row

    def column(self):
        if not self.isValid():
            return -1
        current = getattr(self._pointer, "column", None)
        if callable(current):
            try:
                return int(current())
            except Exception:
                pass
        return self._column

    def model(self):
        return self._model if self.isValid() else None

    def internalPointer(self):
        return self._pointer if self.isValid() else None

    def data(self, role=Qt.DisplayRole):
        return self.toModelIndex().data(role)

    def toModelIndex(self):
        if not self.isValid():
            return QModelIndex()
        return self._model.createIndex(
            self.row(), self.column(), self._pointer, self._internal_id)

    def __bool__(self):
        return self.isValid()


class QAbstractItemModel(QObject):
    """Qt-compatible abstract interface for hierarchical item data."""

    def __init__(self, parent=None, *, after=None):
        # QObject historically exposes its owner as a ``parent`` attribute,
        # while Qt item models require a callable ``parent(index)`` method.
        # Preserve QObject ownership internally for models and free the public
        # name for the model API.  setParent/delete below temporarily bridge the
        # historical storage when QObject lifecycle code needs it.
        super().__init__(parent, after=after)
        self._object_parent = self.__dict__.pop("parent", None)
        self.dataChanged = Signal(self)
        self.headerDataChanged = Signal(self)
        self.layoutAboutToBeChanged = Signal(self)
        self.layoutChanged = Signal(self)
        self.modelAboutToBeReset = Signal(self)
        self.modelReset = Signal(self)
        self.rowsAboutToBeInserted = Signal(self)
        self.rowsInserted = Signal(self)
        self.rowsAboutToBeRemoved = Signal(self)
        self.rowsRemoved = Signal(self)
        self.rowsAboutToBeMoved = Signal(self)
        self.rowsMoved = Signal(self)
        self.columnsAboutToBeInserted = Signal(self)
        self.columnsInserted = Signal(self)
        self.columnsAboutToBeRemoved = Signal(self)
        self.columnsRemoved = Signal(self)
        self._change_stack = []

    def objectParent(self):
        """Return the QObject owner without colliding with parent(index)."""
        return self._object_parent

    def setParent(self, parent):
        # During QObject.__init__ the historical ``parent`` attribute still
        # exists and QObject.setParent can run unchanged.
        if "parent" in self.__dict__:
            return QObject.setParent(self, parent)
        self.__dict__["parent"] = getattr(self, "_object_parent", None)
        try:
            result = QObject.setParent(self, parent)
            self._object_parent = self.__dict__.get("parent")
            return result
        finally:
            self.__dict__.pop("parent", None)

    def moveToThread(self, thread):
        self.__dict__["parent"] = getattr(self, "_object_parent", None)
        try:
            result = QObject.moveToThread(self, thread)
            self._object_parent = self.__dict__.get("parent")
            return result
        finally:
            self.__dict__.pop("parent", None)

    def delete(self):
        if self._deleted:
            return
        self.__dict__["parent"] = getattr(self, "_object_parent", None)
        try:
            return QObject.delete(self)
        finally:
            self._object_parent = self.__dict__.get("parent")
            self.__dict__.pop("parent", None)

    # ---- required model surface -------------------------------------------------
    def index(self, row, column, parent=QModelIndex()):
        del row, column, parent
        return QModelIndex()

    def parent(self, index):
        del index
        return QModelIndex()

    def rowCount(self, parent=QModelIndex()):
        del parent
        return 0

    def columnCount(self, parent=QModelIndex()):
        del parent
        return 0

    def data(self, index, role=Qt.DisplayRole):
        del index, role
        return None

    def setData(self, index, value, role=Qt.EditRole):
        del index, value, role
        return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        del section, orientation, role
        return None

    def setHeaderData(self, section, orientation, value, role=Qt.EditRole):
        del section, orientation, value, role
        return False

    def flags(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

    # ---- convenience ------------------------------------------------------------
    def createIndex(self, row, column, internal_pointer=None, internal_id=0):
        return QModelIndex(row, column, self, internal_pointer, internal_id)

    def hasIndex(self, row, column, parent=QModelIndex()):
        row, column = int(row), int(column)
        if row < 0 or column < 0:
            return False
        return row < self.rowCount(parent) and column < self.columnCount(parent)

    def hasChildren(self, parent=QModelIndex()):
        return self.rowCount(parent) > 0 and self.columnCount(parent) > 0

    def sibling(self, row, column, index):
        if not isinstance(index, QModelIndex) or not index.isValid():
            return QModelIndex()
        return self.index(row, column, index.parent())

    def buddy(self, index):
        return index

    def itemData(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid():
            return {}
        values = {}
        for role in (Qt.DisplayRole, Qt.DecorationRole, Qt.EditRole,
                     Qt.ToolTipRole, Qt.StatusTipRole, Qt.WhatsThisRole,
                     Qt.FontRole, Qt.TextAlignmentRole, Qt.BackgroundRole,
                     Qt.ForegroundRole, Qt.CheckStateRole):
            value = self.data(index, role)
            if value is not None:
                values[role] = value
        return values

    def setItemData(self, index, roles):
        changed = False
        for role, value in dict(roles or {}).items():
            changed = bool(self.setData(index, value, int(role))) or changed
        return changed

    # ---- reset/row/column transactions -----------------------------------------
    def beginResetModel(self):
        self.modelAboutToBeReset.emit()
        self._change_stack.append(("reset",))

    def endResetModel(self):
        if not self._change_stack or self._change_stack.pop()[0] != "reset":
            raise RuntimeError("endResetModel without beginResetModel")
        self.modelReset.emit()

    def beginInsertRows(self, parent, first, last):
        parent = parent if isinstance(parent, QModelIndex) else QModelIndex()
        first, last = int(first), int(last)
        self.rowsAboutToBeInserted.emit(parent, first, last)
        self._change_stack.append(("insert_rows", parent, first, last))

    def endInsertRows(self):
        if not self._change_stack or self._change_stack[-1][0] != "insert_rows":
            raise RuntimeError("endInsertRows without beginInsertRows")
        _kind, parent, first, last = self._change_stack.pop()
        self.rowsInserted.emit(parent, first, last)

    def beginRemoveRows(self, parent, first, last):
        parent = parent if isinstance(parent, QModelIndex) else QModelIndex()
        first, last = int(first), int(last)
        self.rowsAboutToBeRemoved.emit(parent, first, last)
        self._change_stack.append(("remove_rows", parent, first, last))

    def endRemoveRows(self):
        if not self._change_stack or self._change_stack[-1][0] != "remove_rows":
            raise RuntimeError("endRemoveRows without beginRemoveRows")
        _kind, parent, first, last = self._change_stack.pop()
        self.rowsRemoved.emit(parent, first, last)

    def beginInsertColumns(self, parent, first, last):
        parent = parent if isinstance(parent, QModelIndex) else QModelIndex()
        first, last = int(first), int(last)
        self.columnsAboutToBeInserted.emit(parent, first, last)
        self._change_stack.append(("insert_columns", parent, first, last))

    def endInsertColumns(self):
        if not self._change_stack or self._change_stack[-1][0] != "insert_columns":
            raise RuntimeError("endInsertColumns without beginInsertColumns")
        _kind, parent, first, last = self._change_stack.pop()
        self.columnsInserted.emit(parent, first, last)

    def beginRemoveColumns(self, parent, first, last):
        parent = parent if isinstance(parent, QModelIndex) else QModelIndex()
        first, last = int(first), int(last)
        self.columnsAboutToBeRemoved.emit(parent, first, last)
        self._change_stack.append(("remove_columns", parent, first, last))

    def endRemoveColumns(self):
        if not self._change_stack or self._change_stack[-1][0] != "remove_columns":
            raise RuntimeError("endRemoveColumns without beginRemoveColumns")
        _kind, parent, first, last = self._change_stack.pop()
        self.columnsRemoved.emit(parent, first, last)


class QAbstractTableModel(QAbstractItemModel):
    """Flat table model base matching QtCore.QAbstractTableModel."""

    def index(self, row, column, parent=QModelIndex()):
        if isinstance(parent, QModelIndex) and parent.isValid():
            return QModelIndex()
        return self.createIndex(row, column) if self.hasIndex(row, column, parent) else QModelIndex()

    def parent(self, index):
        del index
        return QModelIndex()


class QAbstractListModel(QAbstractItemModel):
    """One-column flat model base matching QtCore.QAbstractListModel."""

    def index(self, row, column=0, parent=QModelIndex()):
        if int(column) != 0 or (isinstance(parent, QModelIndex) and parent.isValid()):
            return QModelIndex()
        return self.createIndex(row, 0) if self.hasIndex(row, 0, parent) else QModelIndex()

    def parent(self, index):
        del index
        return QModelIndex()

    def columnCount(self, parent=QModelIndex()):
        return 0 if isinstance(parent, QModelIndex) and parent.isValid() else 1


@dataclass(frozen=True)
class QItemSelectionRange:
    topLeft: QModelIndex
    bottomRight: QModelIndex

    def isValid(self):
        return (self.topLeft.isValid() and self.bottomRight.isValid() and
                self.topLeft.model() is self.bottomRight.model())

    def contains(self, index):
        if not self.isValid() or not index.isValid() or index.model() is not self.topLeft.model():
            return False
        return (self.topLeft.row() <= index.row() <= self.bottomRight.row() and
                self.topLeft.column() <= index.column() <= self.bottomRight.column())

    def indexes(self):
        if not self.isValid():
            return []
        model = self.topLeft.model()
        parent = self.topLeft.parent()
        return [model.index(row, column, parent)
                for row in range(self.topLeft.row(), self.bottomRight.row() + 1)
                for column in range(self.topLeft.column(), self.bottomRight.column() + 1)]


class QItemSelection(list):
    def select(self, topLeft, bottomRight):
        self.append(QItemSelectionRange(topLeft, bottomRight))

    def indexes(self):
        result = []
        for selection_range in self:
            result.extend(selection_range.indexes())
        return result


class QItemSelectionModel(QObject):
    """Backend-neutral current/selection state for any QAbstractItemModel."""

    NoUpdate = 0x0000
    Clear = 0x0001
    Select = 0x0002
    Deselect = 0x0004
    Toggle = 0x0008
    Current = 0x0010
    Rows = 0x0020
    Columns = 0x0040
    SelectCurrent = Select | Current
    ToggleCurrent = Toggle | Current
    ClearAndSelect = Clear | Select

    def __init__(self, model=None, parent=None, *, after=None):
        super().__init__(parent, after=after)
        self.currentChanged = Signal(self)
        self.currentRowChanged = Signal(self)
        self.currentColumnChanged = Signal(self)
        self.selectionChanged = Signal(self)
        self._model = model
        self._current = QModelIndex()
        self._selected = set()
        self._model_reset_connection = None
        self.setModel(model)

    def model(self):
        return self._model

    def setModel(self, model):
        if self._model_reset_connection is not None:
            self._model_reset_connection.disconnect()
            self._model_reset_connection = None
        self._model = model
        self._current = QModelIndex()
        self._selected.clear()
        if model is not None and hasattr(model, "modelReset"):
            self._model_reset_connection = model.modelReset.connect(self.clear)

    def currentIndex(self):
        return self._current

    def setCurrentIndex(self, index, command=NoUpdate):
        index = index if isinstance(index, QModelIndex) else QModelIndex()
        old = self._current
        self._current = index
        if command != self.NoUpdate:
            self.select(index, command)
        if old != index:
            self.currentChanged.emit(index, old)
            if old.row() != index.row():
                self.currentRowChanged.emit(index, old)
            if old.column() != index.column():
                self.currentColumnChanged.emit(index, old)

    def clear(self, *_args):
        old_selection = self.selection()
        old_current = self._current
        self._selected.clear()
        self._current = QModelIndex()
        if old_selection:
            self.selectionChanged.emit(QItemSelection(), old_selection)
        if old_current.isValid():
            self.currentChanged.emit(QModelIndex(), old_current)

    def clearSelection(self):
        if not self._selected:
            return
        old = self.selection()
        self._selected.clear()
        self.selectionChanged.emit(QItemSelection(), old)

    def hasSelection(self):
        return bool(self._selected)

    def isSelected(self, index):
        return index in self._selected

    def selectedIndexes(self):
        return sorted(self._selected, key=lambda index: (index.row(), index.column()))

    def selectedRows(self, column=0):
        rows = sorted({index.row() for index in self._selected})
        return [self._model.index(row, int(column)) for row in rows] if self._model else []

    def selectedColumns(self, row=0):
        columns = sorted({index.column() for index in self._selected})
        return [self._model.index(int(row), column) for column in columns] if self._model else []

    def selection(self):
        selection = QItemSelection()
        for index in self.selectedIndexes():
            selection.select(index, index)
        return selection

    def select(self, selection, command):
        if isinstance(selection, QModelIndex):
            indexes = [selection] if selection.isValid() else []
        elif isinstance(selection, QItemSelectionRange):
            indexes = selection.indexes()
        elif isinstance(selection, QItemSelection):
            indexes = selection.indexes()
        else:
            indexes = [index for index in (selection or ()) if isinstance(index, QModelIndex)]
        indexes = [index for index in indexes if index.isValid() and index.model() is self._model]
        command = int(command)
        before = set(self._selected)
        if command & self.Clear:
            self._selected.clear()
        if command & self.Rows and self._model is not None:
            expanded = []
            for index in indexes:
                expanded.extend(self._model.index(index.row(), column, index.parent())
                                for column in range(self._model.columnCount(index.parent())))
            indexes = expanded
        elif command & self.Columns and self._model is not None:
            expanded = []
            for index in indexes:
                expanded.extend(self._model.index(row, index.column(), index.parent())
                                for row in range(self._model.rowCount(index.parent())))
            indexes = expanded
        for index in indexes:
            if command & self.Toggle:
                if index in self._selected:
                    self._selected.remove(index)
                else:
                    self._selected.add(index)
            elif command & self.Deselect:
                self._selected.discard(index)
            elif command & self.Select:
                self._selected.add(index)
        if command & self.Current and indexes:
            self.setCurrentIndex(indexes[-1], self.NoUpdate)
        after = set(self._selected)
        if after != before:
            selected = QItemSelection()
            deselected = QItemSelection()
            for index in sorted(after - before, key=lambda value: (value.row(), value.column())):
                selected.select(index, index)
            for index in sorted(before - after, key=lambda value: (value.row(), value.column())):
                deselected.select(index, index)
            self.selectionChanged.emit(selected, deselected)


__all__ = [
    "QModelIndex", "QPersistentModelIndex", "QAbstractItemModel",
    "QAbstractTableModel", "QAbstractListModel", "QItemSelectionRange",
    "QItemSelection", "QItemSelectionModel",
]
