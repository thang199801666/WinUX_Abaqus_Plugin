"""Backend-neutral Qt-style item model primitives.

The model layer intentionally lives in :mod:`DearUIQt.core`, matching Qt's
separation between QtCore models/indexes and QtWidgets views/delegates.  It has
no renderer imports and can therefore be used in services, tests and worker
code without loading DearPyGui.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag
import logging
import weakref

from .object import QObject, Signal, Qt


class QModelIndex:
    """Small immutable handle to one item exposed by a QAbstractItemModel."""

    __slots__ = ("_row", "_column", "_model", "_internal_pointer", "_internal_id")

    def __init__(self, row=-1, column=-1, model=None, internal_pointer=None, internal_id=0):
        if isinstance(row, QPersistentModelIndex):
            row = row.toModelIndex()
        if isinstance(row, QModelIndex):
            row, column, model, internal_pointer, internal_id = (
                row.row(), row.column(), row.model(), row.internalPointer(), row.internalId())
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
    """Model-registered handle, remapped by row/column transactions and layouts.

    Arbitrary moves still require explicit model remapping. The model registry
    is weak: retaining a model does not keep unused persistent handles alive.
    """

    def __init__(self, index=None):
        if isinstance(index, QPersistentModelIndex):
            index = index.toModelIndex()
        index = index if isinstance(index, QModelIndex) else QModelIndex()
        self._index = index
        if index.isValid():
            index.model()._persistent_indexes[id(self)] = self

    def _invalidate(self, *_args):
        model = self._index.model()
        if model is not None:
            model._persistent_indexes.pop(id(self), None)
        self._index = QModelIndex()

    def isValid(self):
        return self._index.isValid()

    def row(self):
        return self._index.row()

    def column(self):
        return self._index.column()

    def model(self):
        return self._index.model()

    def internalPointer(self):
        return self._index.internalPointer()

    def parent(self):
        return self._index.parent()

    def sibling(self, row, column):
        return self._index.sibling(row, column)

    def flags(self):
        return self._index.flags()

    def data(self, role=Qt.DisplayRole):
        return self.toModelIndex().data(role)

    def toModelIndex(self):
        return self._index

    def __eq__(self, other):
        if isinstance(other, QPersistentModelIndex):
            other = other.toModelIndex()
        return self._index == other

    def __hash__(self):
        return hash(self._index)

    def __bool__(self):
        return self.isValid()


class QAbstractItemModel(QObject):
    """Qt-compatible abstract interface for hierarchical item data."""

    class LayoutChangeHint(IntEnum):
        NoLayoutChangeHint = 0
        VerticalSortHint = 1
        HorizontalSortHint = 2

    NoLayoutChangeHint = LayoutChangeHint.NoLayoutChangeHint
    VerticalSortHint = LayoutChangeHint.VerticalSortHint
    HorizontalSortHint = LayoutChangeHint.HorizontalSortHint

    class CheckIndexOption(IntFlag):
        NoOption = 0
        IndexIsValid = 1
        DoNotUseParent = 2
        ParentIsInvalid = 4

    CheckIndexOptions = CheckIndexOption

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
        self.columnsAboutToBeMoved = Signal(self)
        self.columnsMoved = Signal(self)
        self._change_stack = []
        self._move_active = False
        self._reset_active = False
        self._persistent_indexes = weakref.WeakValueDictionary()
        self._structureFinished = Signal(self)
        self._resetInvalidated = Signal(self)

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
        self._invalidate_persistent_indexes()
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

    def checkIndex(self, index, options=CheckIndexOption.NoOption):
        if isinstance(index, QPersistentModelIndex):
            index = index.toModelIndex()
        if not isinstance(index, QModelIndex):
            raise TypeError('checkIndex requires QModelIndex or QPersistentModelIndex')
        options = int(options)
        flags = self.CheckIndexOption
        def fail(reason):
            logging.getLogger(__name__ + '.checkindex').warning('checkIndex: %s: %r', reason, index)
            return False
        if not index.isValid():
            return fail('expected a valid index') if options & flags.IndexIsValid else True
        if index.model() is not self:
            return fail('index belongs to a different model')
        if index.row() < 0 or index.column() < 0:
            return fail('negative row or column')
        if not options & flags.DoNotUseParent:
            parent = index.parent()
            if options & flags.ParentIsInvalid and parent.isValid():
                return fail('expected an invalid parent')
            if index.row() >= self.rowCount(parent):
                return fail('row is out of range')
            if index.column() >= self.columnCount(parent):
                return fail('column is out of range')
        return True

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

    def moveRows(self, sourceParent, sourceRow, count, destinationParent, destinationChild):
        return False  # Qt's base implementation does not mutate storage.

    def moveColumns(self, sourceParent, sourceColumn, count, destinationParent, destinationChild):
        return False

    def moveRow(self, sourceParent, sourceRow, destinationParent, destinationChild):
        return self.moveRows(sourceParent, sourceRow, 1, destinationParent, destinationChild)

    def moveColumn(self, sourceParent, sourceColumn, destinationParent, destinationChild):
        return self.moveColumns(sourceParent, sourceColumn, 1, destinationParent, destinationChild)

    # ---- reset/row/column transactions -----------------------------------------
    def persistentIndexList(self):
        return list(dict.fromkeys(value.toModelIndex() for value in self._persistent_indexes.values()))

    def changePersistentIndex(self, source, target):
        self.changePersistentIndexList([source], [target])

    def changePersistentIndexList(self, sources, targets):
        replacements = dict(zip(sources, targets))
        for persistent in list(self._persistent_indexes.values()):
            target = replacements.get(persistent.toModelIndex())
            if target is not None:
                if target.isValid() and target.model() is self:
                    persistent._index = target
                else:
                    persistent._invalidate()

    def _invalidate_persistent_indexes(self):
        for persistent in list(self._persistent_indexes.values()):
            persistent._invalidate()

    def _persistent_structure_snapshot(self, parent, first, last, rows, removing):
        changes = []
        for persistent in list(self._persistent_indexes.values()):
            index = persistent.toModelIndex()
            path = []
            affected = False
            while index.isValid():
                row, column = index.row(), index.column()
                ancestor = index.parent()
                if ancestor == parent:
                    section = row if rows else column
                    if removing and first <= section <= last:
                        path = None
                        affected = True
                        break
                    if section >= first:
                        delta = (last - first + 1) * (-1 if removing else 1)
                        row, column = (row + delta, column) if rows else (row, column + delta)
                        affected = True
                path.append((row, column))
                index = ancestor
            if affected:
                changes.append((weakref.ref(persistent), None if path is None else path[::-1]))
        return changes

    def _apply_persistent_structure(self, changes):
        for reference, path in changes:
            persistent = reference()
            if persistent is None or not persistent.isValid():
                continue
            if path is None:
                persistent._invalidate()
                continue
            index = QModelIndex()
            for row, column in path:
                index = self.index(row, column, index)
                if not index.isValid():
                    break
            if index.isValid():
                persistent._index = index
            else:
                persistent._invalidate()

    def beginResetModel(self):
        if self._reset_active or self._move_active or self._change_stack:
            raise RuntimeError('nested reset transactions are not supported')
        if self._deleted:
            raise RuntimeError('cannot reset a deleted model')
        self._reset_active = True
        try:
            self.modelAboutToBeReset.emit()
            self._change_stack.append(("reset",))
        except Exception:
            self._reset_active = False
            raise

    def endResetModel(self):
        if not self._change_stack or self._change_stack[-1][0] != "reset":
            raise RuntimeError("endResetModel without beginResetModel")
        self._change_stack.pop()
        self._invalidate_persistent_indexes()
        self._reset_active = False
        # Qt selection state is already invalid when modelReset observers run,
        # even if they connected before the selection model's reset slot.
        self._resetInvalidated.emit()
        self.modelReset.emit()

    def beginInsertRows(self, parent, first, last):
        self._check_reset_move_conflict()
        parent = parent if isinstance(parent, QModelIndex) else QModelIndex()
        first, last = int(first), int(last)
        self.rowsAboutToBeInserted.emit(parent, first, last)
        self._change_stack.append(("insert_rows", parent, first, last,
                                   self._persistent_structure_snapshot(parent, first, last, True, False)))

    def endInsertRows(self):
        if not self._change_stack or self._change_stack[-1][0] != "insert_rows":
            raise RuntimeError("endInsertRows without beginInsertRows")
        _kind, parent, first, last, changes = self._change_stack.pop()
        self._apply_persistent_structure(changes)
        self._structureFinished.emit()
        self.rowsInserted.emit(parent, first, last)

    def beginRemoveRows(self, parent, first, last):
        self._check_reset_move_conflict()
        parent = parent if isinstance(parent, QModelIndex) else QModelIndex()
        first, last = int(first), int(last)
        self.rowsAboutToBeRemoved.emit(parent, first, last)
        self._change_stack.append(("remove_rows", parent, first, last,
                                   self._persistent_structure_snapshot(parent, first, last, True, True)))

    def endRemoveRows(self):
        if not self._change_stack or self._change_stack[-1][0] != "remove_rows":
            raise RuntimeError("endRemoveRows without beginRemoveRows")
        _kind, parent, first, last, changes = self._change_stack.pop()
        self._apply_persistent_structure(changes)
        self._structureFinished.emit()
        self.rowsRemoved.emit(parent, first, last)

    def beginInsertColumns(self, parent, first, last):
        self._check_reset_move_conflict()
        parent = parent if isinstance(parent, QModelIndex) else QModelIndex()
        first, last = int(first), int(last)
        self.columnsAboutToBeInserted.emit(parent, first, last)
        self._change_stack.append(("insert_columns", parent, first, last,
                                   self._persistent_structure_snapshot(parent, first, last, False, False)))

    def endInsertColumns(self):
        if not self._change_stack or self._change_stack[-1][0] != "insert_columns":
            raise RuntimeError("endInsertColumns without beginInsertColumns")
        _kind, parent, first, last, changes = self._change_stack.pop()
        self._apply_persistent_structure(changes)
        self._structureFinished.emit()
        self.columnsInserted.emit(parent, first, last)

    def beginRemoveColumns(self, parent, first, last):
        self._check_reset_move_conflict()
        parent = parent if isinstance(parent, QModelIndex) else QModelIndex()
        first, last = int(first), int(last)
        self.columnsAboutToBeRemoved.emit(parent, first, last)
        self._change_stack.append(("remove_columns", parent, first, last,
                                   self._persistent_structure_snapshot(parent, first, last, False, True)))

    def endRemoveColumns(self):
        if not self._change_stack or self._change_stack[-1][0] != "remove_columns":
            raise RuntimeError("endRemoveColumns without beginRemoveColumns")
        _kind, parent, first, last, changes = self._change_stack.pop()
        self._apply_persistent_structure(changes)
        self._structureFinished.emit()
        self.columnsRemoved.emit(parent, first, last)

    @staticmethod
    def _index_path(index):
        path = []
        while index.isValid():
            path.append((index.row(), index.column()))
            index = index.parent()
        return tuple(reversed(path))

    def _index_from_path(self, path):
        index = QModelIndex()
        for row, column in path:
            index = self.index(row, column, index)
            if not index.isValid():
                break
        return index

    def _check_reset_move_conflict(self):
        if self._reset_active or self._move_active:
            raise RuntimeError('cannot nest structural changes inside reset/move transactions')

    def _begin_move(self, source, first, last, destination, child, rows):
        if self._move_active or self._reset_active or self._change_stack:
            raise RuntimeError('nested move transactions are not supported')
        if self._deleted:
            raise RuntimeError('cannot mutate a deleted model')
        if not isinstance(source, QModelIndex) or not isinstance(destination, QModelIndex):
            return False
        if any(parent.isValid() and parent.model() is not self for parent in (source, destination)):
            return False
        first, last, child = int(first), int(last), int(child)
        count_method = self.rowCount if rows else self.columnCount
        if first < 0 or last < first or last >= count_method(source) or not 0 <= child <= count_method(destination):
            return False
        if source == destination and first <= child <= last + 1:
            return False
        ancestor = destination
        while ancestor.isValid():
            section = ancestor.row() if rows else ancestor.column()
            if ancestor.parent() == source and first <= section <= last:
                return False  # Cannot move an item under itself/its descendant.
            ancestor = ancestor.parent()
        self._move_active = True
        try:
            signal = self.rowsAboutToBeMoved if rows else self.columnsAboutToBeMoved
            signal.emit(source, first, last, destination, child)
            source_path, destination_path = self._index_path(source), self._index_path(destination)
            count = last - first + 1
            axis = 0 if rows else 1

            def stationary(path):
                result = []
                for depth, coordinate in enumerate(path):
                    parent_path = path[:depth]
                    section = coordinate[axis]
                    shift = 0
                    if source_path == destination_path and parent_path == source_path:
                        if child < first and child <= section < first:
                            shift = count
                        elif child > last and last < section < child:
                            shift = -count
                    elif source_path != destination_path:
                        if parent_path == source_path and section > last:
                            shift -= count
                        if parent_path == destination_path and section >= child:
                            shift += count
                    row, column = coordinate
                    result.append((row + shift, column) if rows else (row, column + shift))
                return tuple(result)

            changes = []
            for persistent in list(self._persistent_indexes.values()):
                path = self._index_path(persistent.toModelIndex())
                depth = len(source_path)
                if (len(path) > depth and path[:depth] == source_path
                        and first <= path[depth][axis] <= last):
                    row, column = path[depth]
                    start = child - count if source_path == destination_path and child > last else child
                    section = start + path[depth][axis] - first
                    coordinate = (section, column) if rows else (row, section)
                    mapped = stationary(destination_path) + (coordinate,) + path[depth + 1:]
                else:
                    mapped = stationary(path)
                if mapped != path:
                    changes.append((weakref.ref(persistent), mapped))
            self._change_stack.append(('move_rows' if rows else 'move_columns', first, last, child,
                                       stationary(source_path), stationary(destination_path), changes))
        except Exception:
            self._move_active = False
            raise
        return True

    def _end_move(self, rows):
        kind = 'move_rows' if rows else 'move_columns'
        if not self._change_stack or self._change_stack[-1][0] != kind:
            raise RuntimeError('end move without matching begin move')
        _kind, first, last, child, source_path, destination_path, changes = self._change_stack.pop()
        try:
            self._apply_persistent_structure(changes)
            source, destination = self._index_from_path(source_path), self._index_from_path(destination_path)
        finally:
            self._move_active = False
        signal = self.rowsMoved if rows else self.columnsMoved
        signal.emit(source, first, last, destination, child)

    def beginMoveRows(self, sourceParent, sourceFirst, sourceLast, destinationParent, destinationChild):
        return self._begin_move(sourceParent, sourceFirst, sourceLast, destinationParent, destinationChild, True)

    def endMoveRows(self):
        self._end_move(True)

    def beginMoveColumns(self, sourceParent, sourceFirst, sourceLast, destinationParent, destinationChild):
        return self._begin_move(sourceParent, sourceFirst, sourceLast, destinationParent, destinationChild, False)

    def endMoveColumns(self):
        self._end_move(False)


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


@dataclass(frozen=True, init=False)
class QItemSelectionRange:
    _top_left: QModelIndex
    _bottom_right: QModelIndex

    def __init__(self, topLeft=None, bottomRight=None):
        if isinstance(topLeft, QItemSelectionRange):
            topLeft, bottomRight = topLeft.topLeft(), topLeft.bottomRight()
        topLeft = topLeft if isinstance(topLeft, QModelIndex) else QModelIndex()
        bottomRight = topLeft if bottomRight is None else bottomRight
        bottomRight = bottomRight if isinstance(bottomRight, QModelIndex) else QModelIndex()
        object.__setattr__(self, '_top_left', topLeft)
        object.__setattr__(self, '_bottom_right', bottomRight)

    def topLeft(self): return self._top_left
    def bottomRight(self): return self._bottom_right
    def top(self): return self._top_left.row()
    def bottom(self): return self._bottom_right.row()
    def left(self): return self._top_left.column()
    def right(self): return self._bottom_right.column()
    def parent(self): return self._top_left.parent()
    def model(self): return self._top_left.model()
    def width(self): return self.right() - self.left() + 1
    def height(self): return self.bottom() - self.top() + 1

    def isValid(self):
        # A singleton built from the very same immutable handle cannot have
        # mismatching models, parents or reversed coordinates. Do not cache
        # validity or treat merely equal/distinct corner handles this way.
        if self._top_left is self._bottom_right:
            return self._top_left.isValid()
        return (self._top_left.isValid() and self._bottom_right.isValid() and
                self.model() is self._bottom_right.model() and
                self.parent() == self._bottom_right.parent() and
                self.top() <= self.bottom() and self.left() <= self.right())

    def contains(self, index, column=None, parent=QModelIndex()):
        if column is not None:
            return (self.isValid() and parent == self.parent() and
                    self.top() <= int(index) <= self.bottom() and
                    self.left() <= int(column) <= self.right())
        if (not self.isValid() or not isinstance(index, QModelIndex)
                or not index.isValid() or index.model() is not self.model()
                or index.parent() != self.parent()):
            return False
        return (self.top() <= index.row() <= self.bottom() and
                self.left() <= index.column() <= self.right())

    def intersects(self, other):
        # Like Qt, reject model/geometry mismatches before the more expensive
        # parent and validity queries. No model calls for separated rectangles.
        return (isinstance(other, QItemSelectionRange) and self.model() is other.model()
                and self.top() <= other.bottom() and other.top() <= self.bottom()
                and self.left() <= other.right() and other.left() <= self.right()
                and self.parent() == other.parent() and self.isValid() and other.isValid())

    def intersected(self, other):
        if not self.intersects(other):
            return QItemSelectionRange()
        model, parent = self.model(), self.parent()
        return QItemSelectionRange(
            model.index(max(self.top(), other.top()), max(self.left(), other.left()), parent),
            model.index(min(self.bottom(), other.bottom()), min(self.right(), other.right()), parent))

    def isEmpty(self):
        return not any(_selectable(index) for index in self._indexes())

    def _indexes(self):
        if not self.isValid():
            return
        model, parent = self.model(), self.parent()
        for row in range(self.top(), self.bottom() + 1):
            for column in range(self.left(), self.right() + 1):
                index = model.index(row, column, parent)
                if index.isValid():
                    yield index

    def indexes(self):
        return [index for index in self._indexes() if _selectable(index)]


def _selectable(index):
    flags = index.flags()
    required = Qt.ItemIsSelectable | Qt.ItemIsEnabled
    return index.isValid() and flags & required == required


class QItemSelection(list):
    def __init__(self, topLeft=None, bottomRight=None):
        super().__init__()
        if isinstance(topLeft, QModelIndex):
            self.select(topLeft, topLeft if bottomRight is None else bottomRight)
        elif topLeft is not None:
            self.extend(topLeft)

    def select(self, topLeft, bottomRight):
        if (not topLeft.isValid() or not bottomRight.isValid()
                or topLeft.model() is not bottomRight.model()
                or topLeft.parent() != bottomRight.parent()):
            return
        if topLeft.row() <= bottomRight.row() and topLeft.column() <= bottomRight.column():
            # Qt keeps ordered corner handles, including their model identity.
            # Reindexing here is both unnecessary and wrong for custom handles
            # that differ from a fresh model.index() at the same coordinates.
            self.append(QItemSelectionRange(topLeft, bottomRight))
            return
        model, parent = topLeft.model(), topLeft.parent()
        self.append(QItemSelectionRange(
            model.index(min(topLeft.row(), bottomRight.row()), min(topLeft.column(), bottomRight.column()), parent),
            model.index(max(topLeft.row(), bottomRight.row()), max(topLeft.column(), bottomRight.column()), parent)))

    def contains(self, index):
        return any(selection_range.contains(index) for selection_range in self)

    def _indexes(self):
        for selection_range in self:
            yield from selection_range._indexes()

    def indexes(self):
        # Qt exposes each stored range here (overlapping ranges may repeat an
        # index); QItemSelectionModel normalizes coverage before applying it.
        return [index for index in self._indexes() if _selectable(index)]

    def merge(self, other, command):
        command = int(command)
        flags = QItemSelectionModel
        if not command & (flags.Select | flags.Deselect | flags.Toggle):
            return
        incoming = [area for area in other if area.isValid()]
        intersections = [area.intersected(old) for area in incoming for old in self if area.intersects(old)]
        for intersection in intersections:
            self[:] = [part for area in self for part in _subtract_selection_range(area, intersection)]
            if command & flags.Toggle:
                incoming = [part for area in incoming for part in _subtract_selection_range(area, intersection)]
        if not command & flags.Deselect:
            self.extend(incoming)


def _subtract_selection_range(area, cut):
    """Rectangular subtraction preserving Qt's top/bottom/left/right splits."""
    if not area.intersects(cut):
        return [area]
    cut = area.intersected(cut)
    model, parent = area.model(), area.parent()
    bounds = [(area.top(), area.left(), cut.top() - 1, area.right()),
              (cut.bottom() + 1, area.left(), area.bottom(), area.right()),
              (cut.top(), area.left(), cut.bottom(), cut.left() - 1),
              (cut.top(), cut.right() + 1, cut.bottom(), area.right())]
    return [QItemSelectionRange(model.index(top, left, parent), model.index(bottom, right, parent))
            for top, left, bottom, right in bounds if top <= bottom and left <= right]


def _selection_ranges_from_indexes(indexes):
    """Rebuild rectangular coverage after a layout permutes individual cells."""
    rows = {}
    model = None
    for index in indexes:
        model = index.model()
        rows.setdefault((index.parent(), index.row()), []).append(index.column())
    result = QItemSelection()
    previous = {}
    for (parent, row), columns in sorted(rows.items(), key=lambda entry: entry[0][1]):
        columns.sort()
        runs = []
        for column in columns:
            if runs and column == runs[-1][1] + 1:
                runs[-1][1] = column
            else:
                runs.append([column, column])
        for left, right in runs:
            signature = parent, left, right
            position = previous.get(signature)
            if position is not None and result[position].bottom() == row - 1:
                result[position] = QItemSelectionRange(result[position].topLeft(), model.index(row, right, parent))
            else:
                previous[signature] = len(result)
                result.append(QItemSelectionRange(model.index(row, left, parent), model.index(row, right, parent)))
    return result


class QItemSelectionModel(QObject):
    """Backend-neutral current/selection state for any QAbstractItemModel."""

    class SelectionFlag(IntFlag):
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

    SelectionFlags = SelectionFlag
    NoUpdate = SelectionFlag.NoUpdate
    Clear = SelectionFlag.Clear
    Select = SelectionFlag.Select
    Deselect = SelectionFlag.Deselect
    Toggle = SelectionFlag.Toggle
    Current = SelectionFlag.Current
    Rows = SelectionFlag.Rows
    Columns = SelectionFlag.Columns
    SelectCurrent = SelectionFlag.SelectCurrent
    ToggleCurrent = SelectionFlag.ToggleCurrent
    ClearAndSelect = SelectionFlag.ClearAndSelect

    def __init__(self, model=None, parent=None, *, after=None):
        super().__init__(parent, after=after)
        self.currentChanged = Signal(self)
        self.currentRowChanged = Signal(self)
        self.currentColumnChanged = Signal(self)
        self.selectionChanged = Signal(self)
        self.modelChanged = Signal(self)
        self._model = None
        self._current = QModelIndex()
        self._selected = set()
        # Undo of the latest interactive selection relative to committed items.
        # Keeping only its delta avoids a full committed-set copy on each local
        # Select/Deselect edit, while Current can replace that interactive layer.
        self._interactive_added = set()
        self._interactive_removed = set()
        self._interactive_command = self.NoUpdate
        self._interactive_targets = ()
        self._model_reset_connection = None
        self._structure_connections = []
        self._committed_ranges = QItemSelection()
        self._live_ranges = QItemSelection()
        self._live_command = self.NoUpdate
        self._live_disjoint = False
        self._pending_structure = None
        # Internal notification: views need to repaint remapped coordinates even
        # when Qt intentionally emits no public current/selection delta signal.
        self._structureRemapped = Signal(self)
        self.setModel(model)

    def model(self):
        return self._model

    def setModel(self, model):
        if model is self._model:
            return
        if self._model_reset_connection is not None:
            self._model_reset_connection.disconnect()
            self._model_reset_connection = None
        for connection in self._structure_connections:
            connection.disconnect()
        self._structure_connections.clear()
        self._model = model
        self.reset()
        if model is not None and hasattr(model, "modelReset"):
            self._model_reset_connection = model.modelReset.connect(self.reset)
            for rows in (True, False):
                for removing, action in ((False, 'Inserted'), (True, 'Removed')):
                    about = getattr(model, ('rows' if rows else 'columns') + 'AboutToBe' + action)
                    completed = getattr(model, ('rows' if rows else 'columns') + action)
                    self._structure_connections.extend([
                        about.connect(lambda parent, first, last, rows=rows, removing=removing:
                                      self._structure_about(parent, first, last, rows, removing), receiver=self),
                        completed.connect(self._structure_after),
                    ])
            self._structure_connections.extend([
                model._resetInvalidated.connect(self.reset),
                model._structureFinished.connect(self._structure_after),
                model.layoutAboutToBeChanged.connect(self._layout_about),
                model.layoutChanged.connect(self._structure_after),
                model.rowsAboutToBeMoved.connect(self._layout_about),
                model.rowsMoved.connect(self._structure_after),
                model.columnsAboutToBeMoved.connect(self._layout_about),
                model.columnsMoved.connect(self._structure_after),
            ])
            if hasattr(model, '_itemAboutToBeTaken'):
                self._structure_connections.extend([
                    model._itemAboutToBeTaken.connect(self._item_about),
                    model._itemTaken.connect(self._structure_after),
                ])
        self.modelChanged.emit(model)

    def currentIndex(self):
        if self._pending_structure is not None and self._pending_structure['layout_indexes'] is not None:
            return self._pending_structure['handles'][self._pending_structure['current']].toModelIndex()
        return self._current

    def _selection_state(self):
        snapshot = self._pending_structure
        if snapshot is None or snapshot['layout_indexes'] is None:
            return self._selected
        # Before our layoutChanged slot runs, Qt exposes its original ranges
        # with persistent corners already remapped/invalidated by the model.
        # Only that slot rebuilds coverage from the saved individual cells.
        handles = snapshot['handles']
        groups = []
        for areas in snapshot['ranges']:
            groups.append(QItemSelection(QItemSelectionRange(handles[area.topLeft()].toModelIndex(),
                                                             handles[area.bottomRight()].toModelIndex())
                                         for area in areas if handles[area.topLeft()].isValid()
                                         and handles[area.bottomRight()].isValid()))
        groups[0].merge(groups[1], self._live_command)
        return set(groups[0]._indexes())

    def setCurrentIndex(self, index, command=NoUpdate):
        if self._model is None:
            return
        index = index if isinstance(index, QModelIndex) else QModelIndex()
        old = self._current
        self._current = index
        if command != self.NoUpdate:
            self.select(index, command)
        if old != index:
            self.currentChanged.emit(index, old)
            if old.row() != index.row() or old.parent() != index.parent():
                self.currentRowChanged.emit(index, old)
            if old.column() != index.column() or old.parent() != index.parent():
                self.currentColumnChanged.emit(index, old)
        self._refresh_structure_snapshot()

    def clear(self, *_args):
        self.clearSelection()
        self.clearCurrentIndex()

    def clearCurrentIndex(self):
        """Clear keyboard current independently of the selected items."""
        self.setCurrentIndex(QModelIndex(), self.NoUpdate)

    def reset(self, *_args):
        """Reset silently, including when the attached item model resets."""
        self._selected.clear()
        self._interactive_added.clear()
        self._interactive_removed.clear()
        self._interactive_command = self.NoUpdate
        self._interactive_targets = ()
        self._current = QModelIndex()
        self._committed_ranges.clear()
        self._live_ranges.clear()
        self._live_command = self.NoUpdate
        self._live_disjoint = False
        self._pending_structure = None

    def clearSelection(self):
        self._committed_ranges.clear()
        self._live_ranges.clear()
        self._live_command = self.NoUpdate
        self._live_disjoint = False
        self._interactive_added.clear()
        self._interactive_removed.clear()
        self._interactive_command = self.NoUpdate
        self._interactive_targets = ()
        if not self._selected:
            self._refresh_structure_snapshot()
            return
        old = self.selection()
        self._selected.clear()
        self.selectionChanged.emit(QItemSelection(), old)
        self._refresh_structure_snapshot()

    def _commit_live_ranges(self):
        if self._live_disjoint and self._pending_structure is None:
            # select() already proved every targeted cell absent from committed
            # coverage. Qt's merge would find no intersections and append these
            # exact ranges. Avoid rescanning all old ranges for each small add.
            self._committed_ranges.extend(area for area in self._live_ranges if area.isValid())
        else:
            self._committed_ranges.merge(self._live_ranges, self._live_command)
        self._live_ranges.clear()
        self._live_command = self.NoUpdate
        self._live_disjoint = False

    def _finalize_ranges(self):
        self._commit_live_ranges()
        self._interactive_added.clear()
        self._interactive_removed.clear()
        self._interactive_command = self.NoUpdate
        self._interactive_targets = ()

    def _capture_structure_state(self, layout=False, item_take=False):
        indexes = set(self._selected) | self._interactive_added | self._interactive_removed
        indexes.update(self._interactive_targets)
        indexes.add(self._current)
        ranges = (list(self._committed_ranges), list(self._live_ranges))
        range_indexes = [set(index for area in areas for index in area._indexes()) for areas in ranges] if layout else None
        if layout:
            for values in range_indexes:
                indexes.update(values)
        for areas in ranges:
            for area in areas:
                indexes.update((area.topLeft(), area.bottomRight()))
        return {'handles': {index: QPersistentModelIndex(index) for index in indexes},
                'selected': set(self._selected), 'added': set(self._interactive_added),
                'removed': set(self._interactive_removed), 'targets': tuple(self._interactive_targets),
                'current': self._current, 'ranges': ranges, 'layout_indexes': range_indexes, 'item_take': item_take}

    def _refresh_structure_snapshot(self):
        if self._pending_structure is not None:
            self._pending_structure = self._capture_structure_state(
                layout=self._pending_structure['layout_indexes'] is not None,
                item_take=self._pending_structure['item_take'])

    def _layout_about(self, *_args):
        self._pending_structure = self._capture_structure_state(layout=True)

    def _item_about(self):
        self._pending_structure = self._capture_structure_state(item_take=True)

    def _structure_about(self, parent, first, last, rows, removing):
        self._pending_structure = None
        if rows or not removing:
            self._finalize_ranges()
        current = self._current
        section = current.row() if rows else current.column()
        if removing and current.isValid() and current.parent() == parent and first <= section <= last:
            # Qt 6.8's column-removal fallback checks root columnCount(), even
            # for a nested parent with a wider table (runtime-oracle quirk).
            count = self._model.rowCount(parent) if rows else self._model.columnCount()
            replacement = first - 1 if first else last + 1 if last < count - 1 else -1
            index = (self._model.index(replacement, current.column(), parent) if rows else
                     self._model.index(current.row(), replacement, parent)) if replacement >= 0 else QModelIndex()
            self.setCurrentIndex(index, self.NoUpdate)

        if removing and not rows:
            # Qt deselects the removed columns directly; descendant ranges are
            # invalidated later with their persistent parent, without a delta.
            area = QItemSelection(self._model.index(0, first, parent),
                                  self._model.index(self._model.rowCount(parent) - 1, last, parent))
            self.select(area, self.Deselect)
            self._finalize_ranges()
        else:
            updated = QItemSelection()
            removed = set()
            shifted = False
            for area in self._committed_ranges:
                if area.parent() == parent:
                    start = area.top() if rows else area.left()
                    stop = area.bottom() if rows else area.right()
                    if removing:
                        cut = QItemSelectionRange(
                            self._model.index(first, area.left(), parent) if rows else self._model.index(area.top(), first, parent),
                            self._model.index(last, area.right(), parent) if rows else self._model.index(area.bottom(), last, parent))
                        removed.update(area.intersected(cut)._indexes())
                        updated.extend(_subtract_selection_range(area, cut))
                        shifted |= last < start
                    elif start < first <= stop:
                        # Split at the insertion point so inserted cells never
                        # become selected simply because range corners move.
                        updated.extend([
                            QItemSelectionRange(area.topLeft(),
                                self._model.index(first - 1, area.right(), parent) if rows else
                                self._model.index(area.bottom(), first - 1, parent)),
                            QItemSelectionRange(
                                self._model.index(first, area.left(), parent) if rows else
                                self._model.index(area.top(), first, parent), area.bottomRight())])
                    else:
                        updated.append(area)
                        shifted |= rows and start >= first
                else:
                    ancestor = area.parent()
                    while ancestor.isValid() and ancestor.parent() != parent:
                        ancestor = ancestor.parent()
                    section = ancestor.row() if rows else ancestor.column()
                    if removing and ancestor.isValid() and first <= section <= last:
                        removed.update(area._indexes())
                    else:
                        updated.append(area)
                        shifted |= removing and ancestor.isValid() and last < section
            self._committed_ranges = updated
            self._selected.difference_update(removed)
            if removed or shifted:
                deselected = QItemSelection([QItemSelectionRange(index) for index in removed])
                self.selectionChanged.emit(QItemSelection(), deselected)
        self._pending_structure = self._capture_structure_state()

    def _structure_after(self, *_args):
        snapshot = self._pending_structure
        if snapshot is None:
            return
        self._pending_structure = None
        handles = snapshot['handles']
        def mapped(index):
            return handles[index].toModelIndex()
        def mapped_set(indexes):
            return {mapped(index) for index in indexes if handles[index].isValid()}
        self._selected = mapped_set(snapshot['selected'])
        self._interactive_added = mapped_set(snapshot['added'])
        self._interactive_removed = mapped_set(snapshot['removed'])
        self._interactive_targets = tuple(mapped_set(snapshot['targets']))
        self._current = mapped(snapshot['current'])
        groups = []
        if snapshot['layout_indexes'] is not None:
            groups = [_selection_ranges_from_indexes(mapped_set(indexes)) for indexes in snapshot['layout_indexes']]
        else:
            for areas in snapshot['ranges']:
                groups.append(QItemSelection(QItemSelectionRange(mapped(area.topLeft()), mapped(area.bottomRight()))
                                             for area in areas if handles[area.topLeft()].isValid()
                                             and handles[area.bottomRight()].isValid()))
        self._committed_ranges, self._live_ranges = groups
        # Range reconstruction/invalidation can change geometry; never reuse a
        # pre-transaction proof. A later select() can prove disjointness again.
        self._live_disjoint = False
        if snapshot['item_take']:
            # Qt stores persistent range corners, not a persistent handle for
            # each selected cell. Taking an interior cell leaves its coverage;
            # invalidating either corner invalidates the whole stored range.
            effective = QItemSelection(self._committed_ranges)
            effective.merge(self._live_ranges, self._live_command)
            committed = set(self._committed_ranges._indexes())
            self._selected = set(effective._indexes())
            self._interactive_added = self._selected - committed
            self._interactive_removed = committed - self._selected
            self._interactive_targets = (tuple(self._live_ranges._indexes())
                                         if self._live_command & self.Deselect else ())
        self._structureRemapped.emit()

    def hasSelection(self):
        return any(_selectable(index) for index in self._selection_state())

    def isSelected(self, index):
        return index in self._selection_state() and _selectable(index)

    def selectedIndexes(self):
        return sorted((index for index in self._selection_state() if _selectable(index)),
                      key=lambda index: (index.row(), index.column()))

    def selectedRows(self, column=0):
        return self._selected_sections(int(column), rows=True)

    def selectedColumns(self, row=0):
        return self._selected_sections(int(row), rows=False)

    def _valid_parent(self, parent):
        return (self._model is not None and isinstance(parent, QModelIndex)
                and (not parent.isValid() or parent.model() is self._model))

    def _section_blocking_targets(self):
        return (self._interactive_targets if self._interactive_command & self.Deselect else
                self._interactive_removed if self._interactive_command & self.Toggle else ())

    def _section_selected(self, section, parent, rows, *, blocked_sections=None):
        if not self._valid_parent(parent):
            return False
        model = self._model
        sections = model.rowCount(parent) if rows else model.columnCount(parent)
        if not 0 <= section < sections:
            return False
        # Qt 6.8 treats a live Deselect touching this section, or a Toggle
        # removing committed coverage, as not fully selected even if that
        # affected cell is currently disabled/unselectable. Runtime oracle
        # coverage is important: eligible-cell membership alone misses this.
        if blocked_sections is not None:
            blocked = (parent, section) in blocked_sections
        else:
            blocked = any((index.row() if rows else index.column()) == section and index.parent() == parent
                          for index in self._section_blocking_targets())
        if blocked:
            return False
        count = model.columnCount(parent) if rows else model.rowCount(parent)
        eligible = False
        selected = self._selection_state()
        for offset in range(count):
            index = model.index(section, offset, parent) if rows else model.index(offset, section, parent)
            if _selectable(index):
                eligible = True
                if index not in selected:
                    return False
        return eligible

    def isRowSelected(self, row, parent=QModelIndex()):
        return self._section_selected(int(row), parent, True)

    def isColumnSelected(self, column, parent=QModelIndex()):
        return self._section_selected(int(column), parent, False)

    def _selected_sections(self, anchor, rows):
        if self._model is None:
            return []
        candidates = dict.fromkeys((index.parent(), index.row() if rows else index.column())
                                   for index in self.selectedIndexes())
        if not candidates:
            return []
        # Query-local only: live Deselect/Toggle blockers are identical for all
        # candidates. Index them once instead of rescanning every target per
        # section. Never retain this across calls, flags/Current/model changes.
        # Pending layout snapshots keep the original per-section query path.
        blocked_sections = (None if self._pending_structure is not None else
                            {(index.parent(), index.row() if rows else index.column())
                             for index in self._section_blocking_targets()})
        result = []
        for parent, section in candidates:
            if self._section_selected(section, parent, rows, blocked_sections=blocked_sections):
                result.append(self._model.index(section, anchor, parent) if rows else
                              self._model.index(anchor, section, parent))
        return result

    def rowIntersectsSelection(self, row, parent=QModelIndex()):
        return (self._valid_parent(parent) and any(index.row() == int(row) and index.parent() == parent
                                                 and _selectable(index) for index in self._selection_state()))

    def columnIntersectsSelection(self, column, parent=QModelIndex()):
        return (self._valid_parent(parent) and any(index.column() == int(column) and index.parent() == parent
                                                 and _selectable(index) for index in self._selection_state()))

    def selection(self):
        selection = QItemSelection()
        for index in sorted(self._selection_state(), key=lambda value: (value.row(), value.column())):
            selection.select(index, index)
        return selection

    def _merge_expanded_ranges(self, areas, command):
        """General Qt-compatible expansion, including rectangle intersections."""
        expanded = QItemSelection()
        for area in areas:
            parent = area.parent()
            if command & self.Rows:
                expanded.merge(QItemSelection(
                    self._model.index(area.top(), 0, parent),
                    self._model.index(area.bottom(), self._model.columnCount(parent) - 1, parent)), self.Select)
            if command & self.Columns:
                expanded.merge(QItemSelection(
                    self._model.index(0, area.left(), parent),
                    self._model.index(self._model.rowCount(parent) - 1, area.right(), parent)), self.Select)
        return expanded

    def _expand_selection_ranges(self, areas, command):
        rows, columns = bool(command & self.Rows), bool(command & self.Columns)
        if rows == columns or any((area.height() if rows else area.width()) != 1 for area in areas):
            return self._merge_expanded_ranges(areas, command)
        # Every expanded range is exactly one whole row/column. Intersections
        # are therefore identical (parent, section) keys, never partial cuts.
        # Qt merge replaces duplicate keys at the end; preserve that ordering.
        expanded, dimensions = {}, {}
        for area in areas:
            parent = area.parent()
            section = area.top() if rows else area.left()
            key = parent, section
            previous = expanded.pop(key, None)
            if previous is not None:
                expanded[key] = previous
                continue
            if parent not in dimensions:
                dimensions[parent] = self._model.columnCount(parent) if rows else self._model.rowCount(parent)
            count = dimensions[parent]
            if rows:
                value = QItemSelectionRange(self._model.index(section, 0, parent),
                                           self._model.index(section, count - 1, parent))
            else:
                value = QItemSelectionRange(self._model.index(0, section, parent),
                                           self._model.index(count - 1, section, parent))
            if value.isValid():
                expanded[key] = value
        return QItemSelection(expanded.values())

    def _expand_selection_indexes_full(self, indexes, command):
        expanded = []
        for index in indexes:
            parent = index.parent()
            if command & self.Rows:
                expanded.extend(self._model.index(index.row(), column, parent)
                                for column in range(self._model.columnCount(parent)))
            if command & self.Columns:
                expanded.extend(self._model.index(row, index.column(), parent)
                                for row in range(self._model.rowCount(parent)))
        return expanded

    def _expand_selection_indexes(self, indexes, command):
        rows, columns = bool(command & self.Rows), bool(command & self.Columns)
        if rows == columns:
            return self._expand_selection_indexes_full(indexes, command)
        # Membership is normalized later anyway. Expand each section once, in
        # first-occurrence order (unlike the metadata's last-occurrence order).
        sections = dict.fromkeys((index.parent(), index.row() if rows else index.column()) for index in indexes)
        expanded, dimensions = [], {}
        for parent, section in sections:
            if parent not in dimensions:
                dimensions[parent] = self._model.columnCount(parent) if rows else self._model.rowCount(parent)
            if rows:
                expanded.extend(self._model.index(section, column, parent) for column in range(dimensions[parent]))
            else:
                expanded.extend(self._model.index(row, section, parent) for row in range(dimensions[parent]))
        return expanded

    def _apply_selection_indexes(self, indexes, selects, deselect, toggle):
        # Targets have already been deduplicated. Compute the undo delta at the
        # mutation itself, without a touched-state dictionary and later passes.
        # Keep insertion/removal order: bulk set updates can change iteration
        # ties between equal coordinates under different parents.
        added, removed = set(), set()
        if deselect:
            for index in indexes:
                if index in self._selected:
                    removed.add(index)
                    self._selected.remove(index)
        elif toggle:
            for index in indexes:
                if index in self._selected:
                    self._selected.remove(index)
                    removed.add(index)
                else:
                    self._selected.add(index)
                    added.add(index)
        elif selects:
            for index in indexes:
                if index not in self._selected:
                    added.add(index)
                    self._selected.add(index)
        return added, removed

    def select(self, selection, command):
        command = int(command)
        if command == self.NoUpdate:
            return
        if self._model is None:
            return
        if isinstance(selection, QModelIndex):
            indexes = [selection] if selection.isValid() else []
            areas = QItemSelection([QItemSelectionRange(index) for index in indexes])
        elif isinstance(selection, QItemSelectionRange):
            indexes = list(selection._indexes())
            areas = QItemSelection([selection])
        elif isinstance(selection, QItemSelection):
            indexes = list(selection._indexes())
            areas = QItemSelection(selection)
        else:
            indexes = [index for index in (selection or ()) if isinstance(index, QModelIndex)]
            areas = QItemSelection([QItemSelectionRange(index) for index in indexes])
        indexes = [index for index in indexes if index.isValid() and index.model() is self._model]
        # Current replaces the previous interactive layer, not keyboard current.
        # A full old snapshot is needed to report that replacement or Clear;
        # ordinary edits still track only membership of touched indexes.
        before = set(self._selected) if command & (self.Clear | self.Current) else None
        toggle = bool(command & self.Toggle)
        deselect = bool(command & self.Deselect)
        selects = bool(command & self.Select)
        mutates = toggle or deselect or selects
        if command & self.Current and not command & self.Clear and not mutates:
            return  # Current alone leaves the existing interactive layer intact.
        areas = QItemSelection(area for area in areas if area.isValid() and area.model() is self._model)
        if command & (self.Rows | self.Columns):
            areas = self._expand_selection_ranges(areas, command)
        if command & self.Clear:
            self._committed_ranges.clear()
            self._live_ranges.clear()
            self._live_disjoint = False
        if not command & self.Current:
            self._commit_live_ranges()
        if mutates:
            self._live_ranges = areas
            self._live_command = command
        if command & self.Current and not command & self.Clear:
            self._selected.difference_update(self._interactive_added)
            self._selected.update(self._interactive_removed)
        if command & self.Clear:
            self._selected.clear()
        if command & (self.Rows | self.Columns):
            indexes = self._expand_selection_indexes(indexes, command)
        indexes = dict.fromkeys(index for index in indexes if index.isValid())
        interactive_added, interactive_removed = self._apply_selection_indexes(indexes, selects, deselect, toggle)
        # A non-Current call implicitly commits the preceding layer. These new
        # deltas describe only the latest operation, ready for a future Current.
        self._interactive_added = interactive_added
        self._interactive_removed = interactive_removed
        self._interactive_command = command if mutates else self.NoUpdate
        self._interactive_targets = tuple(indexes) if command & self.Deselect else ()
        self._live_disjoint = (self._pending_structure is None and selects and not toggle and not deselect
                               and len(interactive_added) == len(indexes))
        if before is None:
            added = interactive_added
            removed = interactive_removed
        else:
            added = self._selected - before
            removed = before - self._selected
        if added or removed:
            selected = QItemSelection()
            deselected = QItemSelection()
            for index in sorted(added, key=lambda value: (value.row(), value.column())):
                selected.select(index, index)
            for index in sorted(removed, key=lambda value: (value.row(), value.column())):
                deselected.select(index, index)
            self.selectionChanged.emit(selected, deselected)
        self._refresh_structure_snapshot()


__all__ = [
    "QModelIndex", "QPersistentModelIndex", "QAbstractItemModel",
    "QAbstractTableModel", "QAbstractListModel", "QItemSelectionRange",
    "QItemSelection", "QItemSelectionModel",
]
