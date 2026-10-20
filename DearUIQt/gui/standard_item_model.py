"""Qt-style standard item model.

The implementation is backend-neutral and mirrors the useful subset of
``QStandardItem``/``QStandardItemModel`` for desktop form and model/view code.
It intentionally lives in :mod:`DearUIQt.gui`, matching QtGui ownership of the
standard item classes while relying only on :mod:`DearUIQt.core`.
"""
from __future__ import annotations

from ..core.item_model import QAbstractItemModel, QModelIndex
from ..core.object import Qt, Signal


class QStandardItem:
    UserType = 1000

    def __init__(self, text="", item_type=0):
        self._type = int(item_type)
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
        if role == Qt.DisplayRole:
            value = "" if value is None else str(value)
            self._data[Qt.EditRole] = value
        elif role == Qt.EditRole:
            self._data[Qt.DisplayRole] = "" if value is None else str(value)
        old = self._data.get(role, object())
        if old == value:
            return False
        self._data[role] = value
        model = self._model
        if model is not None:
            model._item_data_changed(self, [role])
        return True

    def text(self):
        return "" if self._data.get(Qt.DisplayRole) is None else str(self._data.get(Qt.DisplayRole))

    def setText(self, text):
        return self.setData(text, Qt.DisplayRole)

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

    def columnCount(self):
        return self._column_count

    def hasChildren(self):
        return bool(self._rows)

    def child(self, row, column=0):
        row, column = int(row), int(column)
        if not (0 <= row < len(self._rows)):
            return None
        values = self._rows[row]
        return values[column] if 0 <= column < len(values) else None

    def setChild(self, row, column, item):
        row, column = int(row), int(column)
        if row < 0 or column < 0:
            raise IndexError("negative QStandardItem child index")
        if item is not None and not isinstance(item, QStandardItem):
            raise TypeError("child must be QStandardItem or None")
        while len(self._rows) <= row:
            self._rows.append([None] * max(1, self._column_count))
        if column >= self._column_count:
            new_count = column + 1
            for values in self._rows:
                values.extend([None] * (new_count - len(values)))
            self._column_count = new_count
        old = self._rows[row][column]
        if old is item:
            return item
        if old is not None:
            old._detach()
        self._rows[row][column] = item
        if item is not None:
            item._adopt(self, row, column, self._model)
        if self._model is not None:
            self._model.layoutChanged.emit()
        return item

    @staticmethod
    def _normalize_row(items):
        if isinstance(items, QStandardItem):
            return [items]
        row = list(items or ())
        if any(not isinstance(item, QStandardItem) for item in row):
            raise TypeError("row entries must be QStandardItem")
        return row

    def appendRow(self, items):
        return self.insertRow(self.rowCount(), items)

    def insertRow(self, row, items):
        row = max(0, min(int(row), self.rowCount()))
        values = self._normalize_row(items)
        columns = max(self._column_count, len(values), 1)
        if columns > self._column_count:
            for existing in self._rows:
                existing.extend([None] * (columns - len(existing)))
            self._column_count = columns
        values.extend([None] * (self._column_count - len(values)))
        self._rows.insert(row, values)
        self._reindex_children(row)
        if self._model is not None:
            parent_index = self._model.indexFromItem(self)
            self._model.rowsInserted.emit(parent_index, row, row)
        return True

    def appendRows(self, items):
        for item in items:
            self.appendRow(item)

    def insertRows(self, row, items):
        for offset, item in enumerate(items):
            self.insertRow(int(row) + offset, item)

    def takeRow(self, row):
        row = int(row)
        if not 0 <= row < self.rowCount():
            return []
        values = self._rows.pop(row)
        for item in values:
            if item is not None:
                item._detach()
        self._reindex_children(row)
        if self._model is not None:
            parent_index = self._model.indexFromItem(self)
            self._model.rowsRemoved.emit(parent_index, row, row)
        return values

    def removeRow(self, row):
        return bool(self.takeRow(row))

    def removeRows(self, row, count):
        removed = False
        for _ in range(max(0, int(count))):
            removed = bool(self.takeRow(row)) or removed
        return removed

    def takeChild(self, row, column=0):
        row, column = int(row), int(column)
        item = self.child(row, column)
        if item is None:
            return None
        self._rows[row][column] = None
        item._detach()
        if self._model is not None:
            self._model.layoutChanged.emit()
        return item

    def sortChildren(self, column, order=Qt.AscendingOrder):
        column = int(column)
        reverse = int(order) == getattr(Qt, "DescendingOrder", 1)
        def key(values):
            item = values[column] if 0 <= column < len(values) else None
            value = None if item is None else item.data(Qt.DisplayRole)
            if isinstance(value, (int, float)):
                return (0, float(value))
            return (1, "" if value is None else str(value).casefold())
        self._rows.sort(key=key, reverse=reverse)
        self._reindex_children(0)
        if self._model is not None:
            self._model.layoutChanged.emit()

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
        self._root = QStandardItem()
        self._root._model = self
        self._headers = {Qt.Horizontal: [], Qt.Vertical: []}
        self._sort_role = Qt.DisplayRole
        self.setColumnCount(columns)
        self.setRowCount(rows)

    def invisibleRootItem(self):
        return self._root

    def _parent_item(self, parent):
        if isinstance(parent, QModelIndex) and parent.isValid():
            item = parent.internalPointer()
            return item if isinstance(item, QStandardItem) else None
        return self._root

    def rowCount(self, parent=QModelIndex()):
        item = self._parent_item(parent)
        return 0 if item is None else item.rowCount()

    def columnCount(self, parent=QModelIndex()):
        item = self._parent_item(parent)
        return 0 if item is None else item.columnCount()

    def index(self, row, column, parent=QModelIndex()):
        item = self._parent_item(parent)
        if item is None:
            return QModelIndex()
        child = item.child(row, column)
        return self.createIndex(row, column, child) if child is not None else QModelIndex()

    def parent(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid():
            return QModelIndex()
        item = index.internalPointer()
        if not isinstance(item, QStandardItem):
            return QModelIndex()
        parent = item.parent()
        if parent is None or parent is self._root:
            return QModelIndex()
        return self.createIndex(parent.row(), parent.column(), parent)

    def itemFromIndex(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid() or index.model() is not self:
            return None
        item = index.internalPointer()
        return item if isinstance(item, QStandardItem) else None

    def indexFromItem(self, item):
        if not isinstance(item, QStandardItem) or item.model() is not self or item is self._root:
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
        item = self._parent_item(parent)
        return False if item is None else item.removeRow(row)

    def data(self, index, role=Qt.DisplayRole):
        item = self.itemFromIndex(index)
        return None if item is None else item.data(role)

    def setData(self, index, value, role=Qt.EditRole):
        item = self.itemFromIndex(index)
        return False if item is None else item.setData(value, role)

    def flags(self, index):
        item = self.itemFromIndex(index)
        return Qt.NoItemFlags if item is None else item.flags()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        values = self._headers.setdefault(int(orientation), [])
        section = int(section)
        return values[section] if 0 <= section < len(values) else None

    def setHeaderData(self, section, orientation, value, role=Qt.EditRole):
        if role not in (Qt.DisplayRole, Qt.EditRole):
            return False
        section = int(section)
        values = self._headers.setdefault(int(orientation), [])
        while len(values) <= section:
            values.append(None)
        if values[section] == value:
            return False
        values[section] = value
        self.headerDataChanged.emit(int(orientation), section, section)
        return True

    def setHorizontalHeaderLabels(self, labels):
        labels = list(labels or ())
        self._headers[Qt.Horizontal] = [str(value) for value in labels]
        if labels:
            self.setColumnCount(max(self.columnCount(), len(labels)))
        self.headerDataChanged.emit(Qt.Horizontal, 0, max(0, len(labels) - 1))

    def setVerticalHeaderLabels(self, labels):
        labels = list(labels or ())
        self._headers[Qt.Vertical] = [str(value) for value in labels]
        self.headerDataChanged.emit(Qt.Vertical, 0, max(0, len(labels) - 1))

    def setRowCount(self, rows):
        rows = max(0, int(rows))
        while self._root.rowCount() < rows:
            self._root.appendRow([QStandardItem() for _ in range(max(1, self.columnCount()))])
        while self._root.rowCount() > rows:
            self._root.takeRow(self._root.rowCount() - 1)

    def setColumnCount(self, columns):
        columns = max(0, int(columns))
        if columns <= self._root._column_count:
            self._root._column_count = columns
            for row in self._root._rows:
                for item in row[columns:]:
                    if item is not None:
                        item._detach()
                del row[columns:]
            return
        old = self._root._column_count
        self._root._column_count = columns
        for row in self._root._rows:
            row.extend([None] * (columns - len(row)))
        if columns > old:
            self.columnsInserted.emit(QModelIndex(), old, columns - 1)

    def clear(self):
        self.beginResetModel()
        for row in self._root._rows:
            for item in row:
                if item is not None:
                    item._detach()
        self._root._rows = []
        self._root._column_count = 0
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
        column = int(column)
        reverse = int(order) == getattr(Qt, "DescendingOrder", 1)
        role = self._sort_role
        def key(row):
            item = row[column] if 0 <= column < len(row) else None
            value = None if item is None else item.data(role)
            if isinstance(value, (int, float)):
                return (0, float(value))
            return (1, "" if value is None else str(value).casefold())
        self.layoutAboutToBeChanged.emit()
        self._root._rows.sort(key=key, reverse=reverse)
        self._root._reindex_children(0)
        self.layoutChanged.emit()

    def _item_data_changed(self, item, roles):
        index = self.indexFromItem(item)
        if not index.isValid():
            return
        self.dataChanged.emit(index, index, list(roles or ()))
        self.itemChanged.emit(item)


__all__ = ["QStandardItem", "QStandardItemModel"]
