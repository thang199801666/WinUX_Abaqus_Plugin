"""QListWidget/QListWidgetItem convenience layer over QListView."""
from __future__ import annotations

from itertools import count

from ..core.object import Qt, Signal
from .list import QListView
from .models import QtListItem


_ITEM_KEYS = count(1)


class QListWidgetItem:
    Type = 0
    UserType = 1000

    def __init__(self, text="", listwidget=None, type=Type):
        self._key = next(_ITEM_KEYS)
        self._text = str(text)
        self._type = int(type)
        self._data = {}
        self._enabled = True
        self._checked = None
        self._owner = None
        if listwidget is not None:
            listwidget.addItem(self)

    @property
    def key(self):
        return self._key

    def text(self):
        return self._text

    def setText(self, text):
        text = str(text)
        if text == self._text:
            return
        self._text = text
        if self._owner is not None:
            self._owner._item_changed(self)

    def type(self):
        return self._type

    def data(self, role=Qt.UserRole):
        return self._data.get(int(role))

    def setData(self, role, value):
        self._data[int(role)] = value
        if self._owner is not None:
            self._owner._item_changed(self)

    def setEnabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if self._owner is not None:
            self._owner._item_changed(self)

    def isEnabled(self):
        return bool(self._enabled)

    def checkState(self):
        if self._checked is None:
            return Qt.Unchecked
        return Qt.Checked if self._checked else Qt.Unchecked

    def setCheckState(self, state):
        checked = int(state) == int(Qt.Checked)
        if self._checked == checked:
            return
        self._checked = checked
        if self._owner is not None:
            self._owner._item_changed(self)


class QListWidget(QListView):
    """Item-owned convenience view mirroring Qt's QListWidget surface."""

    def __init__(self, parent=None, *, width=-1, height=-1, visible_rows=None,
                 multiple=False, context_menu_requests=False, after=None, backend=None):
        self._widget_items = []
        self._items_by_key = {}
        self._item_widgets = {}
        super().__init__(
            parent, (), width=width, height=height, visible_rows=visible_rows,
            multiple=multiple, after=after, backend=backend,
            context_menu_requests=context_menu_requests,
        )
        self.currentItemChanged = Signal(self)
        self.itemClicked = Signal(self)
        self.itemDoubleClicked = Signal(self)
        self.itemActivated = Signal(self)
        self.itemChanged = Signal(self)
        self.itemSelectionChanged = Signal(self)
        self._last_current_key = None
        self.currentChanged.connect(self._emit_current_item_changed, receiver=self)
        self.activated.connect(self._emit_item_activated, receiver=self)
        self.doubleClicked.connect(self._emit_item_double_clicked, receiver=self)
        self.selectionChanged.connect(lambda _selection: self.itemSelectionChanged.emit(), receiver=self)

    def _as_model_item(self, item):
        return QtListItem(
            item.key,
            item.text(),
            item.data(Qt.UserRole),
            enabled=item.isEnabled(),
            checked=item._checked,
        )

    def _refresh(self, preferred_key=None):
        old_key = self.current
        super().setItems([self._as_model_item(item) for item in self._widget_items])
        target = preferred_key if preferred_key in self._items_by_key else old_key
        if target in self._items_by_key:
            self.setCurrentKey(target, select=True)
        return self

    def addItem(self, item):
        if not isinstance(item, QListWidgetItem):
            item = QListWidgetItem(str(item))
        if item._owner is not None and item._owner is not self:
            raise ValueError("QListWidgetItem already belongs to another QListWidget")
        if item._owner is self:
            return item
        item._owner = self
        self._widget_items.append(item)
        self._items_by_key[item.key] = item
        self._refresh()
        return item

    def addItems(self, labels):
        """Append an iterable of items with one native view reconciliation.

        Calling ``addItem`` for every label rebuilt all retained rows on each
        insertion (quadratic native work).  Keep the same item ownership and
        return values, but materialize the final list only once.  In particular,
        an item already owned by this view is not inserted twice.
        """
        results = []
        changed = False
        for label in labels:
            item = label if isinstance(label, QListWidgetItem) else QListWidgetItem(str(label))
            if item._owner is not None and item._owner is not self:
                raise ValueError("QListWidgetItem already belongs to another QListWidget")
            if item._owner is None:
                item._owner = self
                self._widget_items.append(item)
                self._items_by_key[item.key] = item
                changed = True
            results.append(item)
        if changed:
            self._refresh()
        return results

    def insertItem(self, row, item):
        if not isinstance(item, QListWidgetItem):
            item = QListWidgetItem(str(item))
        if item._owner is not None and item._owner is not self:
            raise ValueError("QListWidgetItem already belongs to another QListWidget")
        if item._owner is self:
            self._widget_items.remove(item)
        item._owner = self
        row = max(0, min(int(row), len(self._widget_items)))
        self._widget_items.insert(row, item)
        self._items_by_key[item.key] = item
        self._refresh(item.key)
        return item

    def takeItem(self, row):
        row = int(row)
        if not 0 <= row < len(self._widget_items):
            return None
        item = self._widget_items.pop(row)
        self._items_by_key.pop(item.key, None)
        item._owner = None
        self._refresh()
        return item

    def clear(self):
        self._item_widgets.clear()
        for item in self._widget_items:
            item._owner = None
        self._widget_items.clear()
        self._items_by_key.clear()
        super().setItems(())

    def count(self):
        return len(self._widget_items)

    def item(self, row):
        row = int(row)
        return self._widget_items[row] if 0 <= row < len(self._widget_items) else None

    def row(self, item):
        try:
            return self._widget_items.index(item)
        except ValueError:
            return -1

    def currentItem(self):
        return self._items_by_key.get(self.current)

    def currentRow(self):
        item = self.currentItem()
        return self.row(item) if item is not None else -1

    def setCurrentRow(self, row):
        item = self.item(row)
        if item is None:
            self.clearSelection()
            self.current = None
            return False
        return self.setCurrentKey(item.key, select=True)


    def itemForKey(self, key):
        return self._items_by_key.get(key)

    def setCurrentItem(self, item):
        if item is None:
            self.clearSelection()
            self.current = None
            return True
        if item._owner is not self:
            return False
        return self.setCurrentKey(item.key, select=True)

    def setItemWidget(self, item, widget):
        """Replace one row's native presentation with a QWidget editor.

        This intentionally mirrors QListWidget::setItemWidget for transient,
        retained editors.  The model item remains authoritative and selection
        state is preserved while the row's selectable is hidden.
        """
        from ..widgets.widget import QWidget
        if item is None or item._owner is not self:
            raise ValueError("item must belong to this QListWidget")
        if not isinstance(widget, QWidget):
            raise TypeError("item widget must be QWidget")
        old = self._item_widgets.get(item.key)
        if old is widget:
            return widget
        if old is not None:
            self.removeItemWidget(item)
        native = self.items.get(item.key)
        if native is not None:
            try:
                self.backend.configure_item(native, show=False)
            except Exception:
                pass
        # Reorder the editor to the model row when the backend supports it.
        try:
            row = self.row(item)
            next_native = None
            if row + 1 < len(self._widget_items):
                next_native = self.items.get(self._widget_items[row + 1].key)
            kwargs = {"parent": self.tag}
            if next_native is not None:
                kwargs["before"] = next_native
            self.backend.move_item(widget.tag, **kwargs)
        except Exception:
            pass
        self._item_widgets[item.key] = widget
        return widget

    def itemWidget(self, item):
        if item is None:
            return None
        return self._item_widgets.get(item.key)

    def removeItemWidget(self, item):
        if item is None:
            return None
        widget = self._item_widgets.pop(item.key, None)
        native = self.items.get(item.key)
        if native is not None:
            try:
                self.backend.configure_item(native, show=True)
            except Exception:
                pass
        return widget

    def selectedItems(self):
        return [item for item in self._widget_items if item.key in self.selected]

    def _item_changed(self, item):
        if item._owner is not self:
            return
        self._refresh(item.key if self.current == item.key else None)
        self.itemChanged.emit(item)

    def _emit_current_item_changed(self, key):
        previous = self._items_by_key.get(self._last_current_key)
        current = self._items_by_key.get(key)
        self._last_current_key = key
        self.currentItemChanged.emit(current, previous)

    def _emit_item_activated(self, key):
        item = self._items_by_key.get(key)
        if item is not None:
            self.itemActivated.emit(item)

    def _emit_item_double_clicked(self, key):
        item = self._items_by_key.get(key)
        if item is not None:
            self.itemDoubleClicked.emit(item)

    def _clicked(self, sender, value, key):
        super()._clicked(sender, value, key)
        item = self._items_by_key.get(key)
        if item is not None:
            self.itemClicked.emit(item)

    def delete(self):
        """Release item ownership and editor references with the native view."""
        if self._deleted:
            return
        for item in self._widget_items:
            item._owner = None
        self._widget_items.clear()
        self._items_by_key.clear()
        self._item_widgets.clear()
        super().delete()


__all__ = ["QListWidget", "QListWidgetItem"]
