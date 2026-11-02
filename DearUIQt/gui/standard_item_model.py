"""Qt-style standard item model.

The implementation is backend-neutral and mirrors the useful subset of
``QStandardItem``/``QStandardItemModel`` for desktop form and model/view code.
It intentionally lives in :mod:`DearUIQt.gui`, matching QtGui ownership of the
standard item classes while relying only on :mod:`DearUIQt.core`.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from functools import cmp_to_key
import math

from ..core.item_model import QAbstractItemModel, QModelIndex
from ..core.object import Qt, Signal


_UNSET_TEXT = object()


class QStandardItem:
    UserType = 1000

    def __init__(self, text=_UNSET_TEXT, item_type=0):
        self._type = int(item_type)
        if text is _UNSET_TEXT:
            self._data = {}
        else:
            text = "" if text is None else str(text)
            self._data = {Qt.DisplayRole: text, Qt.EditRole: text}
        self._flags = Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled
        self._rows = []
        self._column_count = 0
        self._parent_item = None
        self._model = None
        self._row = -1
        self._column = -1

    # ---- identity / ownership -------------------------------------------------
    def type(self):
        return self._type

    def model(self):
        return self._model

    def parent(self):
        if self._model is not None and self._parent_item is self._model._root:
            return None  # The invisible root is not a public item parent in Qt.
        return self._parent_item

    def row(self):
        return self._row

    def column(self):
        return self._column

    def index(self):
        model = self._model
        return model.indexFromItem(self) if model is not None else QModelIndex()

    # ---- roles ----------------------------------------------------------------
    def data(self, role=Qt.UserRole + 1):
        return self._data.get(int(role))

    def setData(self, value, role=Qt.UserRole + 1):
        role = int(role)
        if role == Qt.EditRole:
            role = Qt.DisplayRole
        present = role in self._data
        old = self._data.get(role)
        if present and value is not None and type(old) is type(value) and old == value:
            return False
        if present and value is None:
            del self._data[role]
            if role == Qt.DisplayRole:
                self._data.pop(Qt.EditRole, None)
        else:
            # Display/Edit share the QVariant value, not just its text. Numeric
            # values and invalid (None) data must not be coerced into strings.
            self._data[role] = value
            if role == Qt.DisplayRole:
                self._data[Qt.EditRole] = value
        model = self._model
        if model is not None:
            model._item_data_changed(self, [role])
        return True

    def text(self):
        return "" if self._data.get(Qt.DisplayRole) is None else str(self._data.get(Qt.DisplayRole))

    def setText(self, text):
        return self.setData("" if text is None else str(text), Qt.DisplayRole)

    def __lt__(self, other):
        if not isinstance(other, QStandardItem):
            return NotImplemented
        role = self._model.sortRole() if self._model is not None else Qt.DisplayRole
        left, right = self.data(role), other.data(role)
        if left is None:
            return False
        if right is None:
            return True
        if isinstance(left, (int, float)) and not isinstance(left, bool):
            try:
                if isinstance(left, int) and isinstance(right, float):
                    converted = math.floor(right + 0.5) if right >= 0 else math.ceil(right - 0.5)
                else:
                    converted = int(right) if isinstance(left, int) else float(right)
            except (ValueError, TypeError, OverflowError):
                converted = 0
            return left < converted
        def text(value):
            if isinstance(value, bool):
                return 'true' if value else 'false'
            return str(value)
        # QString compares UTF-16 code units, case-sensitively by default.
        return text(left).encode('utf-16-be', 'surrogatepass') < text(right).encode('utf-16-be', 'surrogatepass')

    def icon(self):
        return self._data.get(Qt.DecorationRole)

    def setIcon(self, icon):
        return self.setData(icon, Qt.DecorationRole)

    def toolTip(self):
        return "" if self._data.get(Qt.ToolTipRole) is None else str(self._data.get(Qt.ToolTipRole))

    def setToolTip(self, text):
        return self.setData(text, Qt.ToolTipRole)

    def statusTip(self):
        return "" if self._data.get(Qt.StatusTipRole) is None else str(self._data.get(Qt.StatusTipRole))

    def setStatusTip(self, text):
        return self.setData(text, Qt.StatusTipRole)

    def checkState(self):
        value = self._data.get(Qt.CheckStateRole)
        return Qt.Unchecked if value is None else int(value)

    def setCheckState(self, state):
        return self.setData(int(state), Qt.CheckStateRole)

    # ---- flags ----------------------------------------------------------------
    def flags(self):
        return int(self._flags)

    def setFlags(self, flags):
        flags = int(flags)
        if flags == self._flags:
            return
        self._flags = flags
        if self._model is not None:
            self._model._item_data_changed(self, [])

    def isEnabled(self):
        return bool(self._flags & Qt.ItemIsEnabled)

    def setEnabled(self, enabled):
        self._set_flag(Qt.ItemIsEnabled, enabled)

    def isEditable(self):
        return bool(self._flags & Qt.ItemIsEditable)

    def setEditable(self, editable):
        self._set_flag(Qt.ItemIsEditable, editable)

    def isSelectable(self):
        return bool(self._flags & Qt.ItemIsSelectable)

    def setSelectable(self, selectable):
        self._set_flag(Qt.ItemIsSelectable, selectable)

    def isCheckable(self):
        return bool(self._flags & Qt.ItemIsUserCheckable)

    def setCheckable(self, checkable):
        self._set_flag(Qt.ItemIsUserCheckable, checkable)
        if checkable and Qt.CheckStateRole not in self._data:
            self._data[Qt.CheckStateRole] = Qt.Unchecked

    def _set_flag(self, flag, enabled):
        flags = self._flags | flag if enabled else self._flags & ~flag
        self.setFlags(flags)

    # ---- child table -----------------------------------------------------------
    def rowCount(self):
        return len(self._rows)

    def setRowCount(self, rows):
        self._check_structure()
        rows = int(rows)
        # Qt rejects negative item row counts rather than clearing children.
        if rows < 0:
            return
        current = self.rowCount()
        if rows > current:
            self._insert_rows(current, [[None] * self._column_count for _ in range(rows - current)])
        elif rows < current:
            self.removeRows(rows, current - rows)

    def columnCount(self):
        return self._column_count

    def hasChildren(self):
        return bool(self._rows)

    def child(self, row, column=0):
        item = self._child(row, column)
        return None if getattr(item, '_placeholder', False) else item

    def _child(self, row, column=0):
        row, column = int(row), int(column)
        if not (0 <= row < len(self._rows)):
            return None
        values = self._rows[row]
        return values[column] if 0 <= column < len(values) else None

    def _check_structure(self):
        if self._model is not None:
            self._model._check_structure()

    def _validate_children(self, rows):
        seen = set()
        ancestors = set()
        ancestor = self
        while ancestor is not None:
            ancestors.add(id(ancestor))
            ancestor = ancestor._parent_item
        for values in rows:
            for item in values:
                if item is None:
                    continue
                if id(item) in seen or id(item) in ancestors:
                    raise ValueError('standard item ownership cannot contain duplicates or cycles')
                if item._parent_item is not None or item._model is not None:
                    raise ValueError('standard item already belongs to a parent/model; take it first')
                seen.add(id(item))

    def _change(self, kind, first, last):
        if self._model is None:
            return nullcontext()
        return self._model._structure_change(kind, self._model.indexFromItem(self), first, last)

    def _set_columns(self, count):
        self._check_structure()
        old = self._column_count
        if count == old:
            return
        if count > old:
            self._insert_columns(old, count - old)
        else:
            self._remove_columns(count, old - count)

    def setColumnCount(self, count):
        self._set_columns(max(0, int(count)))

    def _insert_columns(self, column, count, items=()):
        self._check_structure()
        self._validate_children([[item] for item in items])
        with self._change('InsertColumns', column, column + count - 1):
            for row, values in enumerate(self._rows):
                values[column:column] = [None] * count
                if row < len(items):
                    values[column] = items[row]
            self._column_count += count
            self._reindex_children(0)

    def insertColumns(self, column, count):
        self._check_structure()
        column, count = int(column), int(count)
        if column < 0 or count <= 0:
            return
        if column > self.columnCount():
            count += column - self.columnCount()
            column = self.columnCount()
        self._insert_columns(column, count)

    def insertColumn(self, column, items):
        self._check_structure()
        column = int(column)
        if column < 0:
            return
        items = list(items)
        if any(item is not None and not isinstance(item, QStandardItem) for item in items):
            raise TypeError('column entries must be QStandardItem or None')
        self._validate_children([[item] for item in items])
        if len(items) > self.rowCount():
            self._insert_rows(self.rowCount(), [[None] * self.columnCount()
                                              for _ in range(len(items) - self.rowCount())])
        if column <= self.columnCount():
            self._insert_columns(column, 1, items)

    def appendColumn(self, items):
        self.insertColumn(self.columnCount(), items)

    def _remove_columns(self, column, count):
        self._check_structure()
        with self._change('RemoveColumns', column, column + count - 1):
            for values in self._rows:
                for item in values[column:column + count]:
                    if item is not None:
                        item._detach()
                del values[column:column + count]
            self._column_count -= count
            self._reindex_children(0)

    def removeColumns(self, column, count):
        self._check_structure()
        column, count = int(column), int(count)
        if column < 0 or count <= 0 or column + count > self.columnCount():
            return
        self._remove_columns(column, count)

    def removeColumn(self, column):
        self.removeColumns(column, 1)

    def takeColumn(self, column):
        self._check_structure()
        column = int(column)
        if not 0 <= column < self.columnCount():
            return []
        with self._change('RemoveColumns', column, column):
            result = [values.pop(column) for values in self._rows]
            for item in result:
                if item is not None:
                    item._detach()
            self._column_count -= 1
            self._reindex_children(0)
        return [None if getattr(item, '_placeholder', False) else item for item in result]

    def setChild(self, row, column, item):
        self._check_structure()
        row, column = int(row), int(column)
        if row < 0 or column < 0:
            raise IndexError("negative QStandardItem child index")
        if item is not None and not isinstance(item, QStandardItem):
            raise TypeError("child must be QStandardItem or None")
        if self.child(row, column) is item and row < self.rowCount() and column < self.columnCount():
            return item
        self._validate_children([[item]])
        if row >= self.rowCount():
            self._insert_rows(self.rowCount(), [[None] * self._column_count
                                              for _ in range(row + 1 - self.rowCount())])
        if column >= self._column_count:
            self._set_columns(column + 1)
        old = self._rows[row][column]
        if self.child(row, column) is item:
            return item
        if self._model is not None:
            self._model.layoutAboutToBeChanged.emit([], QAbstractItemModel.NoLayoutChangeHint)
        persistent = (self._model._persistent_subtree_indexes(old)
                      if self._model is not None and old is not None else [])
        if old is not None:
            old._detach()
        self._rows[row][column] = item
        if item is not None:
            item._adopt(self, row, column, self._model)
        if self._model is not None:
            index = self._model.index(row, column, self._model.indexFromItem(self))
            self._model.changePersistentIndexList(persistent, [
                index if item is not None and previous.internalPointer() is old else QModelIndex()
                for previous in persistent])
            self._model.layoutChanged.emit([], QAbstractItemModel.NoLayoutChangeHint)
            if item is not None:
                self._model.itemChanged.emit(item)
            self._model.dataChanged.emit(index, index, [])
        return item

    @staticmethod
    def _normalize_row(items):
        if isinstance(items, QStandardItem):
            return [items]
        row = list(items or ())
        if any(item is not None and not isinstance(item, QStandardItem) for item in row):
            raise TypeError("row entries must be QStandardItem or None")
        return row

    def appendRow(self, items):
        return self.insertRow(self.rowCount(), items)

    def insertRow(self, row, items):
        row = max(0, min(int(row), self.rowCount()))
        values = self._normalize_row(items)
        self._insert_rows(row, [values])
        return True

    def _insert_rows(self, row, rows):
        self._check_structure()
        self._validate_children(rows)
        columns = max(self._column_count, max(len(values) for values in rows))
        if columns > self._column_count:
            self._set_columns(columns)
        for values in rows:
            values.extend([None] * (self._column_count - len(values)))
        with self._change('InsertRows', row, row + len(rows) - 1):
            self._rows[row:row] = rows
            self._reindex_children(row)

    def appendRows(self, items):
        self.insertRows(self.rowCount(), items)

    def insertRows(self, row, items):
        rows = [self._normalize_row(item) for item in items]
        if not rows:
            return
        self._check_structure()
        self._validate_children(rows)
        row = int(row)
        if row < 0:
            # Preserve the legacy per-offset clamping for negative positions.
            for offset, values in enumerate(rows):
                self._insert_rows(max(0, min(row + offset, self.rowCount())), [values])
            return
        self._insert_rows(min(row, self.rowCount()), rows)

    def takeRow(self, row):
        self._check_structure()
        row = int(row)
        if not 0 <= row < self.rowCount():
            return []
        with self._change('RemoveRows', row, row):
            values = self._rows.pop(row)
            for item in values:
                if item is not None:
                    item._detach()
            self._reindex_children(row)
        return [None if getattr(item, '_placeholder', False) else item for item in values]

    def removeRow(self, row):
        return bool(self.takeRow(row))

    def removeRows(self, row, count):
        self._check_structure()
        count = max(0, int(count))
        if not count:
            return False
        row = int(row)
        if not 0 <= row < self.rowCount():
            return False
        stop = min(self.rowCount(), row + count)
        with self._change('RemoveRows', row, stop - 1):
            removed = self._rows[row:stop]
            del self._rows[row:stop]
            for values in removed:
                for item in values:
                    if item is not None:
                        item._detach()
            self._reindex_children(row)
        return any(removed)

    def takeChild(self, row, column=0):
        self._check_structure()
        row, column = int(row), int(column)
        item = self._child(row, column)
        if item is None or getattr(item, '_placeholder', False):
            return None
        model = self._model
        if model is not None:
            # Qt temporarily removes the child table with transactions, then
            # restores it on the detached item. Taking an item is not a layout.
            saved_rows, saved_columns = item._rows, item._column_count
            try:
                if saved_rows:
                    with item._change('RemoveRows', 0, len(saved_rows) - 1):
                        item._rows = []
                if saved_columns:
                    with item._change('RemoveColumns', 0, saved_columns - 1):
                        item._column_count = 0
            finally:
                item._rows, item._column_count = saved_rows, saved_columns
            model._itemAboutToBeTaken.emit()
            indexes = model._persistent_subtree_indexes(item)
            model.changePersistentIndexList(indexes, [QModelIndex()] * len(indexes))
        self._rows[row][column] = None
        item._detach()
        if model is not None:
            model._itemTaken.emit()
            index = model.index(row, column, model.indexFromItem(self))
            model.dataChanged.emit(index, index, [])
        return item

    def sortChildren(self, column, order=Qt.AscendingOrder):
        self._check_structure()
        column = int(column)
        if column < 0 or not self.rowCount():
            return
        model = self._model
        parents = []
        if self._model is not None:
            from ..core.item_model import QPersistentModelIndex
            parents = [QPersistentModelIndex(self.index())]
            model.layoutAboutToBeChanged.emit(parents, QAbstractItemModel.VerticalSortHint)
            persistent = model.persistentIndexList()
        self._sort_children(column, int(order) == getattr(Qt, 'DescendingOrder', 1))
        if model is not None:
            model._remap_item_indexes(persistent)
            model.layoutChanged.emit(parents, QAbstractItemModel.VerticalSortHint)

    def _sort_children(self, column, reverse):
        if column >= self.columnCount():
            return
        sortable, empty = [], []
        for values in self._rows:
            item = values[column]
            (empty if item is None or getattr(item, '_placeholder', False) else sortable).append(values)
        def compare(left, right):
            a, b = left[column], right[column]
            return -1 if a < b else 1 if b < a else 0
        sortable.sort(key=cmp_to_key(compare), reverse=reverse)
        self._rows[:] = sortable + empty
        # Ownership/model do not change in a sort. Repair local coordinates
        # before descending, without repeatedly re-adopting whole subtrees.
        for row, values in enumerate(self._rows):
            for col, item in enumerate(values):
                if item is not None:
                    item._row, item._column = row, col
        for values in self._rows:
            for item in values:
                if item is not None:
                    item._sort_children(column, reverse)

    def clone(self):
        clone = QStandardItem(self.text(), self._type)
        clone._data = dict(self._data)
        clone._flags = self._flags
        for row in self._rows:
            clone.appendRow([item.clone() if item is not None else QStandardItem("") for item in row])
        return clone

    def _adopt(self, parent, row, column, model):
        self._parent_item = parent
        self._row = int(row)
        self._column = int(column)
        self._set_model_recursive(model)

    def _detach(self):
        self._parent_item = None
        self._row = -1
        self._column = -1
        self._set_model_recursive(None)

    def _set_model_recursive(self, model):
        self._model = model
        for r, row in enumerate(self._rows):
            for c, item in enumerate(row):
                if item is not None:
                    item._adopt(self, r, c, model)

    def _reindex_children(self, start=0):
        for r in range(max(0, int(start)), len(self._rows)):
            for c, item in enumerate(self._rows[r]):
                if item is not None:
                    item._adopt(self, r, c, self._model)


class QStandardItemModel(QAbstractItemModel):
    def __init__(self, rows=0, columns=0, parent=None, *, after=None):
        super().__init__(parent=parent, after=after)
        self.itemChanged = Signal(self)
        self._itemAboutToBeTaken = Signal(self)
        self._itemTaken = Signal(self)
        self._headerTaken = Signal(self)
        self._root = QStandardItem()
        self._root._model = self
        self._headers = {Qt.Horizontal: [], Qt.Vertical: []}
        self._sort_role = Qt.DisplayRole
        self._structural_change_active = False
        self.setColumnCount(columns)
        self.setRowCount(rows)

    def invisibleRootItem(self):
        return self._root

    def _persistent_subtree_indexes(self, item):
        result = []
        for index in self.persistentIndexList():
            current = index.internalPointer()
            while current is not None:
                if current is item:
                    result.append(index)
                    break
                current = current._parent_item
        return result

    def _remap_item_indexes(self, indexes):
        self.changePersistentIndexList(indexes, [self.indexFromItem(index.internalPointer()) for index in indexes])

    def _check_structure(self):
        if self._deleted:
            raise RuntimeError('cannot mutate a deleted model')
        if self._structural_change_active or self._reset_active or self._move_active:
            raise RuntimeError('cannot mutate model structure during an active transaction notification')

    @contextmanager
    def _structure_change(self, kind, parent, first, last):
        self._check_structure()
        self._structural_change_active = True
        depth = len(self._change_stack)
        try:
            getattr(self, 'begin' + kind)(parent, first, last)
            yield
        except Exception:
            # About-to failures happen before mutation. For a private mutation
            # failure, do not leave a dangling transaction or claim completion.
            del self._change_stack[depth:]
            raise
        else:
            if not parent.isValid():
                orientation = Qt.Vertical if kind.endswith('Rows') else Qt.Horizontal
                headers = self._headers[orientation]
                if kind.startswith('Insert'):
                    headers[first:first] = [None] * (last - first + 1)
                else:
                    for item in headers[first:last + 1]:
                        if item is not None:
                            item._detach()
                    del headers[first:last + 1]
            # Completed observers may legally begin the next operation.
            self._structural_change_active = False
            getattr(self, 'end' + kind)()
        finally:
            self._structural_change_active = False

    def _parent_item(self, parent):
        if parent is not None and not isinstance(parent, QModelIndex):
            return None
        if isinstance(parent, QModelIndex) and parent.isValid():
            if parent.model() is not self:
                return None
            item = parent.internalPointer()
            return item if isinstance(item, QStandardItem) and item.model() is self else None
        return self._root

    def rowCount(self, parent=QModelIndex()):
        item = self._parent_item(parent)
        return 0 if item is None else item.rowCount()

    def columnCount(self, parent=QModelIndex()):
        item = self._parent_item(parent)
        return 0 if item is None else item.columnCount()

    def index(self, row, column, parent=QModelIndex()):
        row, column = int(row), int(column)
        item = self._parent_item(parent)
        if item is None or not (0 <= row < item.rowCount() and 0 <= column < item.columnCount()):
            return QModelIndex()
        child = item._child(row, column)
        if child is None:
            # Keep a stable private identity for an empty cell without exposing
            # an eagerly allocated public QStandardItem. Qt indexes empty cells
            # before itemFromIndex()/setData() materializes their item.
            child = QStandardItem()
            child._data.clear()
            child._placeholder = True
            item._rows[row][column] = child
            child._adopt(item, row, column, self)
        return self.createIndex(row, column, child)

    def parent(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid() or index.model() is not self:
            return QModelIndex()
        item = index.internalPointer()
        if not isinstance(item, QStandardItem) or item.model() is not self:
            return QModelIndex()
        parent = item.parent()
        if parent is None or parent is self._root:
            return QModelIndex()
        return self.createIndex(parent.row(), parent.column(), parent)

    def itemFromIndex(self, index):
        item = self._item_from_index(index)
        if item is not None:
            item._placeholder = False
        return item

    def _item_from_index(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid() or index.model() is not self:
            return None
        item = index.internalPointer()
        return item if isinstance(item, QStandardItem) and item.model() is self else None

    def indexFromItem(self, item):
        if (not isinstance(item, QStandardItem) or item.model() is not self
                or item is self._root or item._parent_item is None):
            return QModelIndex()
        return self.createIndex(item.row(), item.column(), item)

    def item(self, row, column=0):
        return self._root.child(row, column)

    def setItem(self, row, column, item=None):
        if item is None and isinstance(column, QStandardItem):
            item, column = column, 0
        return self._root.setChild(row, column, item)

    def takeItem(self, row, column=0):
        return self._root.takeChild(row, column)

    def appendRow(self, items):
        return self._root.appendRow(items)

    def insertRow(self, row, items):
        return self._root.insertRow(row, items)

    def takeRow(self, row):
        return self._root.takeRow(row)

    def removeRow(self, row, parent=QModelIndex()):
        return self.removeRows(row, 1, parent)

    def insertRows(self, row, count, parent=QModelIndex()):
        self._check_structure()
        row, count = int(row), int(count)
        item = self._parent_item(parent)
        if item is None or count <= 0 or not 0 <= row <= item.rowCount():
            return False
        item._placeholder = False
        item._insert_rows(row, [[None] * item.columnCount() for _ in range(count)])
        return True

    def removeRows(self, row, count, parent=QModelIndex()):
        self._check_structure()
        row, count = int(row), int(count)
        item = self._parent_item(parent)
        if item is None or count <= 0 or row < 0 or row + count > item.rowCount():
            return False
        item.removeRows(row, count)
        return True

    def insertColumns(self, column, count, parent=QModelIndex()):
        self._check_structure()
        column, count = int(column), int(count)
        item = self._parent_item(parent)
        if item is None or count <= 0 or not 0 <= column <= item.columnCount():
            return False
        item._placeholder = False
        item._insert_columns(column, count)
        return True

    def removeColumns(self, column, count, parent=QModelIndex()):
        self._check_structure()
        column, count = int(column), int(count)
        item = self._parent_item(parent)
        if item is None or count <= 0 or column < 0 or column + count > item.columnCount():
            return False
        item._remove_columns(column, count)
        return True

    def insertColumn(self, column, items_or_parent=QModelIndex()):
        if isinstance(items_or_parent, QModelIndex):
            return self.insertColumns(column, 1, items_or_parent)
        return self._root.insertColumn(column, items_or_parent)

    def appendColumn(self, items):
        return self._root.appendColumn(items)

    def removeColumn(self, column, parent=QModelIndex()):
        return self.removeColumns(column, 1, parent)

    def takeColumn(self, column):
        return self._root.takeColumn(column)

    def data(self, index, role=Qt.DisplayRole):
        item = self._item_from_index(index)
        return None if item is None else item.data(role)

    def setData(self, index, value, role=Qt.EditRole):
        item = self.itemFromIndex(index)
        if item is None:
            return False
        item.setData(value, role)
        return True

    def flags(self, index):
        item = self._item_from_index(index)
        return Qt.NoItemFlags if item is None else item.flags()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        section, orientation, role = int(section), int(orientation), int(role)
        values = self._headers.get(orientation, ())
        if not 0 <= section < len(values):
            return None
        item = values[section]
        return item.data(role) if item is not None else section + 1 if role == Qt.DisplayRole else None

    def setHeaderData(self, section, orientation, value, role=Qt.EditRole):
        if self._deleted:
            raise RuntimeError('cannot mutate a deleted model')
        section, orientation = int(section), int(orientation)
        values = self._headers.get(orientation, ())
        if not 0 <= section < len(values):
            return False
        item = values[section]
        if item is None:
            item = QStandardItem()
            item._data.clear()
            item._adopt(None, -1, -1, self)
            values[section] = item
        item.setData(value, role)
        return True

    def _header_item(self, section, orientation):
        section = int(section)
        values = self._headers[orientation]
        return values[section] if 0 <= section < len(values) else None

    def horizontalHeaderItem(self, column):
        return self._header_item(column, Qt.Horizontal)

    def verticalHeaderItem(self, row):
        return self._header_item(row, Qt.Vertical)

    def _set_header_item(self, section, orientation, item):
        self._check_structure()
        section = int(section)
        if section < 0:
            return
        if item is not None and not isinstance(item, QStandardItem):
            raise TypeError('header must be QStandardItem or None')
        if self._header_item(section, orientation) is item and section < len(self._headers[orientation]):
            return
        self._root._validate_children([[item]])
        if section >= len(self._headers[orientation]):
            if orientation == Qt.Horizontal:
                self.setColumnCount(section + 1)
            else:
                self.setRowCount(section + 1)
        values = self._headers[orientation]
        old = values[section]
        if old is item:
            return
        if old is not None:
            old._detach()
        values[section] = item
        if item is not None:
            item._adopt(None, -1, -1, self)
        self.headerDataChanged.emit(orientation, section, section)

    def setHorizontalHeaderItem(self, column, item):
        self._set_header_item(column, Qt.Horizontal, item)

    def setVerticalHeaderItem(self, row, item):
        self._set_header_item(row, Qt.Vertical, item)

    def _take_header_item(self, section, orientation):
        self._check_structure()
        section = int(section)
        item = self._header_item(section, orientation)
        if item is not None:
            self._headers[orientation][section] = None
            item._detach()
            self._headerTaken.emit()
        return item

    def takeHorizontalHeaderItem(self, column):
        return self._take_header_item(column, Qt.Horizontal)

    def takeVerticalHeaderItem(self, row):
        return self._take_header_item(row, Qt.Vertical)

    def setHorizontalHeaderLabels(self, labels):
        self._set_header_labels(labels, Qt.Horizontal)

    def setVerticalHeaderLabels(self, labels):
        self._set_header_labels(labels, Qt.Vertical)

    def _set_header_labels(self, labels, orientation):
        self._check_structure()
        labels = list(labels or ())
        if len(labels) > len(self._headers[orientation]):
            if orientation == Qt.Horizontal:
                self.setColumnCount(len(labels))
            else:
                self.setRowCount(len(labels))
        for section, text in enumerate(labels):
            item = self._header_item(section, orientation)
            if item is None:
                item = QStandardItem()
                item._data.clear()
                self._set_header_item(section, orientation, item)
            item.setText(text)

    def setRowCount(self, rows):
        rows = max(0, int(rows))
        current = self._root.rowCount()
        if current < rows:
            self.insertRows(current, rows - current)
        elif current > rows:
            self.removeRows(rows, current - rows)

    def setColumnCount(self, columns):
        columns = max(0, int(columns))
        self._root._set_columns(columns)

    def clear(self):
        self._check_structure()
        self.beginResetModel()
        for row in self._root._rows:
            for item in row:
                if item is not None:
                    item._detach()
        self._root._rows = []
        self._root._column_count = 0
        for values in self._headers.values():
            for item in values:
                if item is not None:
                    item._detach()
        self._headers = {Qt.Horizontal: [], Qt.Vertical: []}
        self.endResetModel()

    def findItems(self, text, flags=0, column=0):
        needle = str(text)
        case_sensitive = bool(flags & getattr(Qt, "MatchCaseSensitive", 0))
        exact = bool(flags & getattr(Qt, "MatchExactly", 0))
        result = []
        for row in range(self.rowCount()):
            item = self.item(row, column)
            if item is None:
                continue
            haystack = item.text()
            lhs, rhs = (haystack, needle) if case_sensitive else (haystack.casefold(), needle.casefold())
            if (lhs == rhs if exact else rhs in lhs):
                result.append(item)
        return result

    def sortRole(self):
        return self._sort_role

    def setSortRole(self, role):
        self._sort_role = int(role)

    def sort(self, column, order=Qt.AscendingOrder):
        self._check_structure()
        return self._root.sortChildren(column, order)

    def _item_data_changed(self, item, roles):
        if item._parent_item is None:
            for orientation, values in self._headers.items():
                for section, header in enumerate(values):
                    if header is item:
                        self.headerDataChanged.emit(orientation, section, section)
                        return
        index = self.indexFromItem(item)
        if not index.isValid():
            return
        self.itemChanged.emit(item)
        changed = list(roles or ())
        if Qt.DisplayRole in changed or Qt.EditRole in changed:
            changed = [Qt.DisplayRole, Qt.EditRole]
        self.dataChanged.emit(index, index, changed)


__all__ = ["QStandardItem", "QStandardItemModel"]
