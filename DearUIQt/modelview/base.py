"""Shared retained selection/navigation behavior for item views."""
from __future__ import annotations

from ..core.object import Signal, Qt, QPoint, QRect
from ..core.input import QGlobalInputBinding
from ..gui.system import QCursor
from ..core.item_model import QItemSelectionModel, QModelIndex
from ..widgets.widget import QWidget
from .models import QtItemViewState, QtSelectionMode
from .delegates import QStyledItemDelegate

class _QtAbstractItemView(QWidget):
    def __init__(self, tag, *, parent=None, after=None, backend=None, multiple=False):
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.selectionChanged = Signal(self)
        self.currentChanged = Signal(self)
        self.activated = Signal(self)
        self.doubleClicked = Signal(self)
        self.focusChanged = Signal(self)
        self._state = QtItemViewState(multiple=multiple)
        self.multiple = bool(multiple)
        self._has_focus = False
        self._focus_handler_registry = None
        self._focus_input_binding = None
        self._model = None
        self._model_connections = []
        self._item_delegate = QStyledItemDelegate(self)
        self._row_delegates = {}
        self._column_delegates = {}
        self._selection_model = QItemSelectionModel(parent=self)
        self._persistent_editors = {}
        self._index_widgets = {}
        self._install_focus_tracking()

    def _install_focus_tracking(self):
        """Track focus at the view level, as QAbstractItemView does.

        Dear ImGui focuses the row/selectable, not the table/child container.
        A lightweight global mouse handler therefore translates pointer focus
        into one retained view-level flag.  It is used only for active vs
        inactive selection rendering and never captures the pointer.
        """
        try:
            self._focus_input_binding = (
                QGlobalInputBinding(backend=self.backend, parent=self)
                .onMouseClick(Qt.LeftButton, self._focus_mouse_down)
                .activate()
            )
        except Exception:
            self._focus_input_binding = None

    def _focus_mouse_down(self, *_args):
        try:
            point = QCursor.pos(backend=self.backend)
        except Exception:
            point = None
        focused = bool(point is not None and self._point_in_view(point))
        self._set_view_focus(focused)

    def _point_in_view(self, point):
        try:
            return self.containsGlobalPoint(point, clipped=True)
        except Exception:
            return False

    def verticalScrollValue(self):
        """Return the retained vertical scroll offset in renderer pixels."""
        try:
            return float(self.backend.get_y_scroll(self.tag))
        except Exception:
            return 0.0

    def setVerticalScrollValue(self, value):
        """Set the vertical scroll offset and return ``self`` for chaining."""
        try:
            self.backend.set_y_scroll(self.tag, max(0.0, float(value)))
        except Exception:
            pass
        return self

    def horizontalScrollValue(self):
        """Return the retained horizontal scroll offset in renderer pixels."""
        try:
            return float(self.backend.get_x_scroll(self.tag))
        except Exception:
            return 0.0

    def setHorizontalScrollValue(self, value):
        """Set the horizontal scroll offset and return ``self`` for chaining."""
        try:
            self.backend.set_x_scroll(self.tag, max(0.0, float(value)))
        except Exception:
            pass
        return self

    def scrollBy(self, dx=0.0, dy=0.0):
        """Scroll by pixel deltas using the backend-neutral item-view API."""
        if float(dx):
            self.setHorizontalScrollValue(self.horizontalScrollValue() + float(dx))
        if float(dy):
            self.setVerticalScrollValue(self.verticalScrollValue() + float(dy))
        return self

    def _set_view_focus(self, focused):
        focused = bool(focused)
        if self._has_focus == focused:
            return False
        self._has_focus = focused
        self._sync_selection_visuals()
        self.focusChanged.emit(focused)
        return True

    def hasFocus(self):
        return bool(self._has_focus)

    def setFocus(self):
        self._set_view_focus(True)
        self._focus_current()
        return self

    def _model_index_for_key(self, key):
        del key
        return QModelIndex()

    def _selection_model_command(self):
        return QItemSelectionModel.Select

    def _sync_model_selection(self):
        if self._model is None:
            return
        selection_model = self._selection_model
        selection_model.clearSelection()
        command = self._selection_model_command()
        for key in self.selectedKeys():
            index = self._model_index_for_key(key)
            if index is not None and index.isValid():
                selection_model.select(index, command)
        current = self._model_index_for_key(self.current)
        if current is not None and current.isValid():
            selection_model.setCurrentIndex(current, QItemSelectionModel.NoUpdate)

    def model(self):
        return self._model

    def setModel(self, model):
        if model is self._model:
            return self
        self._clear_index_editors()
        for connection in self._model_connections:
            try:
                connection.disconnect()
            except Exception:
                pass
        self._model_connections.clear()
        self._model = model
        self._selection_model.setModel(model)
        if model is not None:
            for name in ("modelReset", "dataChanged", "rowsInserted",
                         "rowsRemoved", "columnsInserted", "columnsRemoved",
                         "layoutChanged", "headerDataChanged"):
                signal = getattr(model, name, None)
                if signal is not None:
                    self._model_connections.append(signal.connect(self._model_changed))
        self._model_changed()
        return self

    def _model_changed(self, *_args):
        """Hook for concrete views to rebuild from an attached model."""
        return None

    def _clear_index_editors(self):
        for editor in list(self._persistent_editors.values()):
            try:
                editor.delete()
            except Exception:
                pass
        self._persistent_editors.clear()
        for widget in list(self._index_widgets.values()):
            try:
                widget.delete()
            except Exception:
                pass
        self._index_widgets.clear()

    def selectionModel(self):
        return self._selection_model

    def setSelectionModel(self, selection_model):
        if selection_model is None:
            selection_model = QItemSelectionModel(self._model, parent=self)
        if selection_model.model() is not self._model:
            selection_model.setModel(self._model)
        self._selection_model = selection_model
        return self

    def currentIndex(self):
        return self._selection_model.currentIndex()

    def setCurrentIndex(self, index):
        if not isinstance(index, QModelIndex):
            index = QModelIndex()
        self._selection_model.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect)
        return self

    def itemDelegate(self, index=None):
        if isinstance(index, QModelIndex) and index.isValid():
            return (self._row_delegates.get(index.row()) or
                    self._column_delegates.get(index.column()) or
                    self._item_delegate)
        return self._item_delegate

    def setItemDelegate(self, delegate):
        self._item_delegate = delegate if delegate is not None else QStyledItemDelegate(self)
        return self

    def setItemDelegateForRow(self, row, delegate):
        row = int(row)
        if delegate is None:
            self._row_delegates.pop(row, None)
        else:
            self._row_delegates[row] = delegate
        return self

    def itemDelegateForRow(self, row):
        return self._row_delegates.get(int(row))

    def setItemDelegateForColumn(self, column, delegate):
        column = int(column)
        if delegate is None:
            self._column_delegates.pop(column, None)
        else:
            self._column_delegates[column] = delegate
        return self

    def itemDelegateForColumn(self, column):
        return self._column_delegates.get(int(column))

    # ---- editor / index-widget lifecycle ---------------------------------------
    @staticmethod
    def _index_key(index):
        if not isinstance(index, QModelIndex) or not index.isValid():
            return None
        parent = index.parent()
        parent_pointer = parent.internalPointer() if parent.isValid() else None
        return (id(index.model()), id(parent_pointer), index.row(), index.column())

    def _editor_parent_for_index(self, index):
        del index
        return self

    def _native_item_for_index(self, index):
        del index
        return None

    def _set_native_index_item_visible(self, index, visible):
        native = self._native_item_for_index(index)
        if native is None:
            return
        try:
            self.backend.configure_item(native, show=bool(visible))
        except Exception:
            pass

    def openPersistentEditor(self, index):
        key = self._index_key(index)
        if key is None:
            return None
        existing = self._persistent_editors.get(key)
        if existing is not None and not getattr(existing, "_deleted", False):
            return existing
        delegate = self.itemDelegate(index)
        if delegate is None:
            return None
        editor = delegate.createEditor(self._editor_parent_for_index(index), None, index)
        if editor is None:
            return None
        delegate.setEditorData(editor, index)
        self._persistent_editors[key] = editor
        self._set_native_index_item_visible(index, False)
        return editor

    def closePersistentEditor(self, index, *, commit=True):
        key = self._index_key(index)
        editor = self._persistent_editors.pop(key, None) if key is not None else None
        if editor is None:
            return False
        delegate = self.itemDelegate(index)
        if commit and delegate is not None and self._model is not None:
            if delegate.setModelData(editor, self._model, index):
                delegate.commitData.emit(editor)
        if delegate is not None:
            delegate.destroyEditor(editor, index)
        else:
            delete = getattr(editor, "delete", None)
            if callable(delete):
                delete()
        self._set_native_index_item_visible(index, True)
        return True

    def isPersistentEditorOpen(self, index):
        key = self._index_key(index)
        editor = self._persistent_editors.get(key) if key is not None else None
        return bool(editor is not None and not getattr(editor, "_deleted", False))

    def setIndexWidget(self, index, widget):
        key = self._index_key(index)
        if key is None:
            return False
        old = self._index_widgets.pop(key, None)
        if old is not None and old is not widget:
            delete = getattr(old, "delete", None)
            if callable(delete):
                delete()
        if widget is None:
            self._set_native_index_item_visible(index, True)
            return True
        from ..widgets.widget import QWidget
        if not isinstance(widget, QWidget):
            raise TypeError("index widget must be QWidget or None")
        parent = self._editor_parent_for_index(index)
        if isinstance(parent, tuple) and len(parent) == 2:
            native_parent = parent[0]
        else:
            native_parent = getattr(parent, "tag", parent)
        try:
            self.backend.move_item(widget._layout_tag(), parent=native_parent)
        except Exception:
            pass
        self._index_widgets[key] = widget
        self._set_native_index_item_visible(index, False)
        return True

    def indexWidget(self, index):
        key = self._index_key(index)
        return self._index_widgets.get(key) if key is not None else None

    def selectionMode(self):
        return (QtSelectionMode.ExtendedSelection
                if self.multiple else QtSelectionMode.SingleSelection)

    def setSelectionMode(self, mode):
        multiple = str(mode) == QtSelectionMode.ExtendedSelection
        if self.multiple == multiple:
            return self
        self.multiple = multiple
        self._state.multiple = multiple
        if not multiple and len(self.selected) > 1:
            keep = self.current if self.current in self.selected else next(iter(self.selected), None)
            self._state.selected = ({keep} if keep is not None else set())
            self._sync_selection_visuals()
            self.selectionChanged.emit(set(self.selected))
        return self

    def currentKey(self):
        return self.current

    @property
    def selected(self):
        # Compatibility with the historic QtTable API.  Callers intentionally
        # mutate this set in a few result dialogs, so expose the real set.
        return self._state.selected

    @selected.setter
    def selected(self, values):
        self._state.selected = set(values or ())
        self._sync_selection_visuals()

    @property
    def current(self):
        return self._state.current

    @current.setter
    def current(self, value):
        self._state.current = value

    @property
    def anchor(self):
        return self._state.anchor

    @anchor.setter
    def anchor(self, value):
        self._state.anchor = value

    def clearSelection(self):
        if not self.selected:
            return
        self.selected.clear()
        self._sync_selection_visuals()
        self._sync_model_selection()
        self.selectionChanged.emit(set())

    clear_selection = clearSelection

    def selectAll(self):
        self._set_view_focus(True)
        before = set(self.selected)
        self._state.select_all()
        if self.selected != before:
            self._sync_selection_visuals()
            self._sync_model_selection()
            self.selectionChanged.emit(set(self.selected))

    def selectedKeys(self):
        return [key for key in self._state.keys if key in self.selected]

    def setCurrentKey(self, key, *, select=True):
        if key not in self._state._key_index:
            return False
        self._set_view_focus(True)
        old_current = self.current
        changed = self._state.select(key, selected=True) if select else False
        self.current = key
        current_changed = old_current != key
        if current_changed:
            self.currentChanged.emit(key)
        if changed or current_changed:
            self._sync_selection_visuals()
        if changed:
            self.selectionChanged.emit(set(self.selected))
        self._sync_model_selection()
        self._focus_current()
        return True

    def navigate(self, key, ctrl=False, shift=False):
        b = self.backend
        self._set_view_focus(True)
        if ctrl and key == b.mvKey_A and self.multiple:
            self.selectAll()
            return
        if ctrl and key == b.mvKey_Spacebar and self.current in self._state._key_index:
            old = set(self.selected)
            if self.current in self.selected:
                self.selected.discard(self.current)
            else:
                if not self.multiple:
                    self.selected.clear()
                self.selected.add(self.current)
            if old != self.selected:
                self._sync_selection_visuals()
                self._sync_model_selection()
                self.selectionChanged.emit(set(self.selected))
            return
        if key == b.mvKey_Up:
            target, changed = self._state.move(-1, ctrl=ctrl, shift=shift)
        elif key == b.mvKey_Down:
            target, changed = self._state.move(1, ctrl=ctrl, shift=shift)
        elif key == b.mvKey_Home:
            target, changed = self._state.move(absolute=0, ctrl=ctrl, shift=shift)
        elif key == b.mvKey_End:
            target, changed = self._state.move(absolute=max(0, len(self._state.keys)-1), ctrl=ctrl, shift=shift)
        elif key == b.mvKey_Prior:
            target, changed = self._state.move(-10, ctrl=ctrl, shift=shift)
        elif key == b.mvKey_Next:
            target, changed = self._state.move(10, ctrl=ctrl, shift=shift)
        else:
            return
        if target is None:
            return
        self._sync_selection_visuals()
        self._sync_model_selection()
        self._focus_current()
        self.currentChanged.emit(target)
        if changed:
            self.selectionChanged.emit(set(self.selected))

    def activateCurrent(self):
        """QAbstractItemView-style keyboard activation, independent of rendering."""
        if self.current not in self._state.keys or not self.isEnabled():
            return False
        item = self.items.get(self.current)
        if item is not None and not self.backend.get_item_configuration(item).get("enabled", True):
            return False
        self.activated.emit(self.current)
        return True

    def _row_clicked(self, sender, value, key):
        b = self.backend
        self._set_view_focus(True)
        ctrl = bool(b.is_key_down(b.mvKey_LControl) or b.is_key_down(b.mvKey_RControl))
        shift = bool(b.is_key_down(b.mvKey_LShift) or b.is_key_down(b.mvKey_RShift))
        old_current = self.current
        changed = self._state.select(key, ctrl=ctrl, shift=shift, selected=bool(value))
        self._sync_selection_visuals()
        self._sync_model_selection()
        if old_current != self.current:
            self.currentChanged.emit(self.current)
        if changed:
            self.selectionChanged.emit(set(self.selected))
        if self._is_double_click():
            self.doubleClicked.emit(key)
            self.activated.emit(key)

    def _is_double_click(self):
        try:
            return bool(self.backend.is_mouse_button_double_clicked(self.backend.mvMouseButton_Left))
        except Exception:
            return False

    def _sync_selection_visuals(self):
        raise NotImplementedError

    def _focus_current(self):
        raise NotImplementedError

    def delete(self):
        if self._deleted:
            return
        # Remove the global input registry before the native view disappears.
        # QObject's recursive deletion also owns this binding, but releasing
        # it here removes any queued backend click callbacks from the renderer
        # as early as possible during modal/dock teardown.
        binding = self._focus_input_binding
        self._focus_input_binding = None
        if binding is not None:
            try:
                binding.delete()
            except Exception:
                pass
        self._clear_index_editors()
        for connection in self._model_connections:
            try:
                connection.disconnect()
            except Exception:
                pass
        self._model_connections.clear()
        registry = self._focus_handler_registry
        self._focus_handler_registry = None
        if registry is not None:
            try:
                if self.backend.does_item_exist(registry):
                    self.backend.delete_item(registry)
            except Exception:
                pass
        super().delete()



__all__ = ["_QtAbstractItemView"]


QAbstractItemView = _QtAbstractItemView

__all__ = ["QAbstractItemView"]
