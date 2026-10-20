"""Small retained tree-view model and QTreeView-style wrapper."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..core.object import Signal, Qt
from ..core.item_model import QModelIndex, QItemSelectionModel
from ..widgets.widget import QWidget
from .delegates import QStyledItemDelegate


@dataclass
class QTreeItem:
    text: str
    key: Any = None
    data: Any = None
    children: list["QTreeItem"] = field(default_factory=list)
    enabled: bool = True
    expanded: bool = False

    def __post_init__(self):
        self.text = str(self.text)
        if self.key is None:
            self.key = self.text
        self.children = list(self.children or ())

    def addChild(self, item):
        if not isinstance(item, QTreeItem):
            raise TypeError("tree child must be QTreeItem")
        self.children.append(item)
        return item

    def child(self, index):
        index = int(index)
        return self.children[index] if 0 <= index < len(self.children) else None

    def childCount(self):
        return len(self.children)


class QTreeView(QWidget):
    """Simple single-selection tree using native Dear ImGui tree nodes.

    It deliberately keeps the model compact rather than emulating the complete
    QAbstractItemModel API. Applications can attach arbitrary metadata to each
    :class:`QTreeItem` and use stable ``key`` values for selection/activation.
    """

    def __init__(self, items: Iterable[QTreeItem] = (), *, parent=None, after=None,
                 backend=None, width=-1, height=-1):
        backend, options = self._construction(parent, backend)
        self.currentChanged = Signal()
        self.activated = Signal()
        self.expanded = Signal()
        self.collapsed = Signal()
        tag = backend.add_child_window(
            width=int(width), height=int(height), border=False, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        for signal in (self.currentChanged, self.activated, self.expanded, self.collapsed):
            signal.owner = self
        self._roots = []
        self._native_by_key = {}
        self._item_by_key = {}
        self._current_key = None
        self._handler_registries = []
        self._model = None
        self._model_connections = []
        self._index_by_key = {}
        self._key_role = None
        self._item_delegate = QStyledItemDelegate(self)
        self._selection_model = QItemSelectionModel(parent=self)
        self._updating_from_model = False
        self.setItems(items)

    def setItems(self, items):
        if self._model is not None and not self._updating_from_model:
            self.setModel(None)
        roots = list(items or ())
        if any(not isinstance(item, QTreeItem) for item in roots):
            raise TypeError("tree model requires QTreeItem roots")
        self._roots = roots
        self._rebuild()

    def model(self):
        return self._model

    def setModel(self, model):
        if model is self._model:
            return self
        for connection in self._model_connections:
            try:
                connection.disconnect()
            except Exception:
                pass
        self._model_connections.clear()
        self._model = model
        self._selection_model.setModel(model)
        if model is not None:
            for name in ("modelReset", "dataChanged", "rowsInserted", "rowsRemoved",
                         "columnsInserted", "columnsRemoved", "layoutChanged"):
                signal = getattr(model, name, None)
                if signal is not None:
                    self._model_connections.append(signal.connect(self._model_changed))
        self._model_changed()
        return self

    def setKeyRole(self, role):
        self._key_role = None if role is None else int(role)
        if self._model is not None:
            self._model_changed()
        return self

    def keyRole(self):
        return self._key_role

    def _key_for_index(self, index, path):
        if self._key_role is not None:
            value = index.data(self._key_role)
            if value is not None:
                try:
                    hash(value)
                    return value
                except TypeError:
                    pass
        pointer = index.internalPointer()
        return ("model", id(pointer)) if pointer is not None else ("model-path", tuple(path))

    def _model_changed(self, *_args):
        model = self._model
        self._index_by_key.clear()
        if model is None:
            if self._updating_from_model:
                return self
            return self

        def build(parent=QModelIndex(), path=()):
            values = []
            for row in range(int(model.rowCount(parent))):
                index = model.index(row, 0, parent)
                if not index.isValid():
                    continue
                key = self._key_for_index(index, path + (row,))
                item = QTreeItem(
                    "" if index.data(Qt.DisplayRole) is None else str(index.data(Qt.DisplayRole)),
                    key=key, data=index.data(Qt.UserRole),
                    enabled=bool(index.flags() & Qt.ItemIsEnabled),
                )
                self._index_by_key[key] = index
                item.children = build(index, path + (row,))
                values.append(item)
            return values

        self._updating_from_model = True
        try:
            self.setItems(build())
        finally:
            self._updating_from_model = False
        return self

    def selectionModel(self):
        return self._selection_model

    def currentIndex(self):
        if self._model is None:
            return QModelIndex()
        return self._index_by_key.get(self._current_key, QModelIndex())

    def setCurrentIndex(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid() or index.model() is not self._model:
            return False
        key = next((key for key, value in self._index_by_key.items() if value == index), None)
        if key is None:
            return False
        changed = self.setCurrentKey(key)
        self._selection_model.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect)
        return changed

    def itemDelegate(self):
        return self._item_delegate

    def setItemDelegate(self, delegate):
        self._item_delegate = delegate if delegate is not None else QStyledItemDelegate(self)
        return self

    def edit(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid():
            return None
        delegate = self._item_delegate
        editor = delegate.createEditor(self, None, index) if delegate is not None else None
        if editor is not None:
            delegate.setEditorData(editor, index)
        return editor

    def commitEditor(self, editor, index):
        if self._model is None or self._item_delegate is None:
            return False
        committed = bool(self._item_delegate.setModelData(editor, self._model, index))
        if committed:
            self._item_delegate.commitData.emit(editor)
        return committed

    def items(self):
        return list(self._roots)

    def clear(self):
        self.setItems(())

    def currentKey(self):
        return self._current_key

    def currentItem(self):
        return self._item_by_key.get(self._current_key)

    def setCurrentKey(self, key):
        if key not in self._item_by_key:
            return False
        if self._current_key != key:
            self._current_key = key
            self.currentChanged.emit(key)
        if self._model is not None:
            index = self._index_by_key.get(key, QModelIndex())
            self._selection_model.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect)
        return True

    def setCurrentItem(self, item):
        return False if item is None else self.setCurrentKey(item.key)

    def expand(self, key):
        item = self._item_by_key.get(key)
        if item is None:
            return False
        if not item.expanded:
            item.expanded = True
            self._configure_open(key, True)
            self.expanded.emit(key)
        return True

    def collapse(self, key):
        item = self._item_by_key.get(key)
        if item is None:
            return False
        if item.expanded:
            item.expanded = False
            self._configure_open(key, False)
            self.collapsed.emit(key)
        return True

    def isExpanded(self, key):
        item = self._item_by_key.get(key)
        return bool(item is not None and item.expanded)

    def expandAll(self):
        for key, item in tuple(self._item_by_key.items()):
            if item.children:
                self.expand(key)

    def collapseAll(self):
        for key, item in tuple(self._item_by_key.items()):
            if item.children:
                self.collapse(key)

    def _configure_open(self, key, opened):
        native = self._native_by_key.get(key)
        if native is not None:
            try:
                self.backend.set_value(native, bool(opened))
            except Exception:
                try:
                    self.backend.configure_item(native, default_open=bool(opened))
                except Exception:
                    pass

    def _rebuild(self):
        self._require_ui()
        try:
            self.backend.delete_item(self.tag, children_only=True)
        except Exception:
            pass
        for registry in self._handler_registries:
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass
        self._handler_registries.clear()
        self._native_by_key.clear()
        self._item_by_key.clear()
        seen = set()

        def add(item, parent):
            if item.key in seen:
                raise ValueError("tree item keys must be unique")
            seen.add(item.key)
            self._item_by_key[item.key] = item
            if item.children:
                native = self.backend.add_tree_node(
                    label=item.text,
                    parent=parent,
                    default_open=bool(item.expanded),
                    callback=self._node_toggled,
                    user_data=item.key,
                )
                self._native_by_key[item.key] = native
                # A tree node already paints the complete expander + text row.
                # Bind a passive click handler to that native item instead of
                # nesting a second selectable (which would duplicate the label).
                try:
                    registry = self.backend.add_item_handler_registry()
                    self.backend.add_item_clicked_handler(
                        parent=registry,
                        callback=self._selected,
                        user_data=item.key,
                    )
                    self.backend.bind_item_handler_registry(native, registry)
                    self._handler_registries.append(registry)
                except Exception:
                    pass
                for child in item.children:
                    add(child, native)
            else:
                native = self.backend.add_selectable(
                    label=item.text,
                    parent=parent,
                    enabled=bool(item.enabled),
                    callback=self._selected,
                    user_data=item.key,
                )
                self._native_by_key[item.key] = native

        for root in self._roots:
            add(root, self.tag)
        if self._current_key not in self._item_by_key:
            self._current_key = None

    def _selected(self, sender, app_data=None, user_data=None):
        key = user_data
        item = self._item_by_key.get(key)
        if item is None or not item.enabled:
            return
        changed = self._current_key != key
        self._current_key = key
        if changed:
            self.currentChanged.emit(key)
        if self._model is not None:
            index = self._index_by_key.get(key, QModelIndex())
            self._selection_model.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect)
        double = False
        try:
            double = bool(self.backend.is_mouse_button_double_clicked(
                self.backend.mvMouseButton_Left))
        except Exception:
            pass
        if double:
            self.activated.emit(key)

    def _node_toggled(self, sender, app_data=None, user_data=None):
        key = user_data
        item = self._item_by_key.get(key)
        if item is None:
            return
        try:
            opened = bool(self.backend.get_value(sender))
        except Exception:
            opened = bool(app_data) if isinstance(app_data, bool) else not item.expanded
        if opened == item.expanded:
            return
        item.expanded = opened
        (self.expanded if opened else self.collapsed).emit(key)

    def delete(self):
        for connection in self._model_connections:
            try:
                connection.disconnect()
            except Exception:
                pass
        self._model_connections.clear()
        for registry in self._handler_registries:
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass
        self._handler_registries.clear()
        super().delete()


__all__ = ["QTreeItem", "QTreeView"]
