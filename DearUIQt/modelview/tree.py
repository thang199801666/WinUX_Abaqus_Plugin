"""Small retained tree-view model and QTreeView-style wrapper."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..core.object import Signal, Qt
from ..core.item_model import QModelIndex, QItemSelectionModel
from ..widgets.widget import QWidget
from .delegates import QStyledItemDelegate, QItemEditorLifecycle, QAbstractItemDelegate
from .policy import QItemViewPolicyMixin
from .themes import qt_item_row_theme


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


class QTreeView(QItemViewPolicyMixin, QWidget):
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
        self.doubleClicked = Signal()
        self.expanded = Signal()
        self.collapsed = Signal()
        tag = backend.add_child_window(
            width=int(width), height=int(height), border=False, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        for signal in (self.currentChanged, self.activated, self.doubleClicked, self.expanded, self.collapsed):
            signal.owner = self
        self._roots = []
        self._native_by_key = {}
        self._item_by_key = {}
        self._current_key = None
        self._handler_registries = []
        self._selection_handler_by_key = {}
        self._toggle_handler_by_key = {}
        self._model = None
        self._model_connections = []
        self._index_by_key = {}
        self._key_role = None
        self._item_delegate = QStyledItemDelegate(self)
        self._selection_model = QItemSelectionModel(parent=self)
        self._selection_model.setCurrentRemovalFallbackEnabled(False)
        self._updating_from_model = False
        self._editor_sessions = {}
        self._init_item_view_policy(multiple=False)
        self._visual_state_by_key = {}
        self._visual_retry_keys = set()
        self.setItems(items)
        from ..backends.shared_scrollers import register_scroll_surface
        register_scroll_surface(backend, tag)

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

    def _key_for_index(self, index, path=None):
        if self._key_role is not None:
            value = index.data(self._key_role)
            if value is not None:
                try:
                    hash(value)
                    return value
                except TypeError:
                    pass
        pointer = index.internalPointer()
        if pointer is not None:
            return ("model", id(pointer))
        if path is None:
            path = []
            current = index
            while current.isValid():
                path.append(current.row())
                current = current.parent()
            path.reverse()
        return ("model-path", tuple(path))

    def _update_model_data(self, top_left, bottom_right):
        """Apply one same-parent dataChanged range without rebuilding nodes."""
        model = self._model
        if (model is None or not top_left.isValid() or not bottom_right.isValid()
                or top_left.model() is not model or bottom_right.model() is not model
                or top_left.parent() != bottom_right.parent()
                or top_left.row() > bottom_right.row()
                or top_left.column() > bottom_right.column()):
            return False
        if top_left.column() > 0:
            return True  # This view renders only column zero.
        parent = top_left.parent()
        updates = []
        for row in range(top_left.row(), bottom_right.row() + 1):
            index = model.index(row, 0, parent)
            if not index.isValid():
                return False
            key = self._key_for_index(index)
            item = self._item_by_key.get(key)
            if item is None or self._index_by_key.get(key) != index:
                return False  # Key/identity changes need structural rendering.
            value = index.data(Qt.DisplayRole)
            updates.append((key, item, index, "" if value is None else str(value),
                            index.data(Qt.UserRole), bool(index.flags() & Qt.ItemIsEnabled)))
        for key, item, index, text, data, enabled in updates:
            options = {}
            if item.text != text:
                options['label'] = text
            if not item.children and item.enabled != enabled:
                options['enabled'] = enabled
            if options:
                try:
                    self.backend.configure_item(self._native_by_key[key], **options)
                except Exception:
                    return False  # Rebuild from the authoritative model below.
            item.text, item.data, item.enabled = text, data, enabled
            self._index_by_key[key] = index
        return True

    def _model_changed(self, *_args):
        if self._deleted:
            return self
        if (len(_args) >= 2 and isinstance(_args[0], QModelIndex)
                and isinstance(_args[1], QModelIndex)
                and self._update_model_data(_args[0], _args[1])):
            return self
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
        self._editor_sessions = {}
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
        previous = self.currentIndex()
        changed = self.setCurrentKey(key)
        self._selection_model.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect)
        if changed and (self.editTriggers() & self.CurrentChanged):
            self._edit_from_trigger(self.CurrentChanged, index)
        return changed


    def _visible_keys(self):
        """Return keys in visual tree order, honoring expanded ancestors."""
        result = []

        def visit(item):
            result.append(item.key)
            if item.children and item.expanded:
                for child in item.children:
                    visit(child)

        for root in self._roots:
            visit(root)
        return result

    def visibleIndexes(self):
        if self._model is None:
            return []
        result = []
        for key in self._visible_keys():
            index = self._index_by_key.get(key, QModelIndex())
            if index.isValid():
                result.append(index)
        return result

    def _key_for_known_index(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid():
            return None
        for key, value in self._index_by_key.items():
            if value == index:
                return key
        return None

    def moveCursor(self, cursor_action, modifiers=Qt.NoModifier):
        """Return the Qt-style tree navigation target.

        Up/Down/Page/Home/End operate on visible tree order. Left collapses an
        expanded branch first, otherwise moves to the parent. Right expands a
        collapsed branch first, otherwise moves to its first child. Expansion
        itself intentionally leaves the current index unchanged, matching the
        keyboard semantics users expect from QTreeView.
        """
        del modifiers
        model = self._model
        if model is None:
            return QModelIndex()
        visible = self.visibleIndexes()
        if not visible:
            return QModelIndex()
        current = self.currentIndex()
        if not current.isValid():
            return visible[0]
        key = self._key_for_known_index(current)
        item = self._item_by_key.get(key)
        action = int(cursor_action)

        if action == self.MoveLeft:
            if item is not None and item.children and item.expanded:
                self.collapse(key)
                return current
            parent = current.parent()
            return parent if parent.isValid() else current

        if action == self.MoveRight:
            if item is not None and item.children:
                if not item.expanded:
                    self.expand(key)
                    return current
                child_key = item.children[0].key
                child = self._index_by_key.get(child_key, QModelIndex())
                if child.isValid():
                    return child
            return current

        try:
            position = visible.index(current)
        except ValueError:
            # A current index hidden by a collapsed ancestor should recover to
            # the nearest visible ancestor rather than walking raw model rows.
            parent = current.parent()
            while parent.isValid():
                if parent in visible:
                    position = visible.index(parent)
                    current = parent
                    break
                parent = parent.parent()
            else:
                position = 0

        if action in (self.MoveUp, self.MovePrevious):
            position -= 1
        elif action in (self.MoveDown, self.MoveNext):
            position += 1
        elif action == self.MoveHome:
            position = 0
        elif action == self.MoveEnd:
            position = len(visible) - 1
        elif action == self.MovePageUp:
            position -= self.pageStep()
        elif action == self.MovePageDown:
            position += self.pageStep()
        else:
            return QModelIndex()
        position = max(0, min(len(visible) - 1, position))
        return visible[position]

    def scrollTo(self, index, hint=QItemViewPolicyMixin.EnsureVisible):
        key = self._key_for_known_index(index)
        native = self._native_by_key.get(key)
        self._ensure_native_visible(native, hint=hint)
        return self


    def _sync_selection_visuals(self):
        """Reconcile tree native rows from shared item-view visual state."""
        current_key = self._current_key
        selected_keys = set()
        try:
            for index in self._selection_model.selectedIndexes():
                key = self._key_for_known_index(index)
                if key is not None:
                    selected_keys.add(key)
        except Exception:
            if current_key is not None:
                selected_keys.add(current_key)
        if not selected_keys and current_key is not None:
            selected_keys.add(current_key)
        for key, native in tuple(self._native_by_key.items()):
            item = self._item_by_key.get(key)
            if item is None:
                continue
            index = self._index_by_key.get(key, QModelIndex())
            option = self.styleOptionForIndex(
                index, selected=key in selected_keys, disabled=not bool(item.enabled),
                current=key == current_key)
            state = option.stateTuple()
            if self._visual_state_by_key.get(key) == state and key not in self._visual_retry_keys:
                continue
            self._visual_state_by_key[key] = state
            try:
                # Selectable leaves accept a retained selected value. Branches
                # are native tree nodes; theme binding still supplies active/
                # inactive/current palette roles where supported by the backend.
                if not item.children:
                    self.backend.set_value(native, option.selected)
                self.backend.bind_item_theme(native, qt_item_row_theme(self.backend, option))
            except Exception:
                self._visual_retry_keys.add(key)
            else:
                self._visual_retry_keys.discard(key)
        return self

    def _focus_current(self):
        native = self._native_by_key.get(self._current_key)
        if native is not None:
            self._ensure_native_visible(native, hint=self.EnsureVisible)

    def _policy_sync_from_selection(self):
        index = self._selection_model.currentIndex()
        key = self._key_for_known_index(index)
        if key is not None and key != self._current_key:
            self._current_key = key
            self.currentChanged.emit(key)
        self._sync_selection_visuals()

    def _policy_current_changed(self, current, previous):
        if current != previous and (self.editTriggers() & self.CurrentChanged):
            self._edit_from_trigger(self.CurrentChanged, current)

    def _policy_focus_current(self):
        try:
            self.setFocus()
        except Exception:
            pass

    def navigate(self, key, ctrl=False, shift=False):
        if key == Qt.Key_F2:
            return bool(self._edit_from_trigger(self.EditKeyPressed))
        if key in (Qt.Key_Return, Qt.Key_Enter):
            current = self.currentKey()
            if current is None:
                return False
            self.activated.emit(current)
            return True
        return bool(self._move_policy_current(key, ctrl=ctrl, shift=shift))

    def keyPressEvent(self, event):
        modifiers = int(event.modifiers())
        handled = self.navigate(
            event.key(),
            ctrl=bool(modifiers & Qt.ControlModifier),
            shift=bool(modifiers & Qt.ShiftModifier),
        )
        if not handled and (self.editTriggers() & self.AnyKeyPressed):
            text = event.text()
            if text and not (modifiers & Qt.ControlModifier):
                handled = self._edit_from_trigger(self.AnyKeyPressed) is not None
        if handled:
            event.accept()
            return
        super().keyPressEvent(event)

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
            key = id(editor)
            def _close(editor_obj, editor_index, hint):
                self._editor_sessions.pop(key, None)
                try:
                    delegate.destroyEditor(editor_obj, editor_index)
                except Exception:
                    delete = getattr(editor_obj, "delete", None)
                    if callable(delete):
                        delete()
            session = QItemEditorLifecycle(
                delegate, editor, self._model, index, parent=self,
                close_callback=_close, navigate_callback=self._navigate_after_editor)
            self._editor_sessions[key] = session
        return editor

    def commitEditor(self, editor, index):
        if self._model is None or self._item_delegate is None:
            return False
        session = self._editor_sessions.get(id(editor))
        if session is not None and session.isActive():
            return bool(session.commit())
        committed = bool(self._item_delegate.setModelData(editor, self._model, index))
        if committed:
            self._item_delegate.commitData.emit(editor)
            self._item_delegate.closeEditor.emit(editor, self._item_delegate.NoHint)
        return committed

    def editorSession(self, editor):
        return self._editor_sessions.get(id(editor))

    def _navigate_after_editor(self, direction, index):
        model = self._model
        if model is None or index is None or not index.isValid():
            return False
        parent = index.parent()
        try:
            rows = int(model.rowCount(parent))
            columns = int(model.columnCount(parent))
        except Exception:
            return False
        step = 1 if int(direction) >= 0 else -1
        pos = index.row() * max(1, columns) + index.column() + step
        limit = rows * max(1, columns)
        while 0 <= pos < limit:
            row, column = divmod(pos, max(1, columns))
            candidate = model.index(row, column, parent)
            if candidate.isValid() and (candidate.flags() & Qt.ItemIsEditable):
                self.setCurrentIndex(candidate)
                self.edit(candidate)
                return True
            pos += step
        return False

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
        self._sync_selection_visuals()
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
        self._selection_handler_by_key.clear()
        self._toggle_handler_by_key.clear()
        self._native_by_key.clear()
        self._item_by_key.clear()
        self._visual_state_by_key.clear()
        self._visual_retry_keys.clear()
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
                    user_data=item.key,
                )
                self._native_by_key[item.key] = native
                # A tree node already paints the complete expander + text row.
                # Bind a passive click handler to that native item instead of
                # nesting a second selectable (which would duplicate the label).
                try:
                    registry = self.backend.add_item_handler_registry()
                    self._handler_registries.append(registry)
                    handler = self.backend.add_item_clicked_handler(
                        parent=registry,
                        callback=self._selected,
                        user_data=item.key,
                    )
                    toggle_handler = self.backend.add_item_toggled_open_handler(
                        parent=registry, callback=self._node_toggled, user_data=item.key,
                        two_way=True)
                    self.backend.bind_item_handler_registry(native, registry)
                    self._selection_handler_by_key[item.key] = handler
                    self._toggle_handler_by_key[item.key] = toggle_handler
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
        self._sync_selection_visuals()

    def _selected(self, sender, app_data=None, user_data=None):
        key = user_data
        if (self._deleted or sender not in (self._native_by_key.get(key),
                                            self._selection_handler_by_key.get(key))):
            return
        item = self._item_by_key.get(key)
        if item is None or not item.enabled:
            return
        changed = self._current_key != key
        was_selected = not changed
        self._current_key = key
        if changed:
            self.currentChanged.emit(key)
        self._sync_selection_visuals()
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
            self.doubleClicked.emit(key)
            self.activated.emit(key)
            self._edit_from_trigger(self.DoubleClicked, self.currentIndex())
        elif was_selected:
            self._edit_from_trigger(self.SelectedClicked, self.currentIndex())

    def _node_toggled(self, sender, app_data=None, user_data=None):
        key = user_data
        native = self._native_by_key.get(key)
        if self._deleted or sender not in (native, self._toggle_handler_by_key.get(key)):
            return
        item = self._item_by_key.get(key)
        if item is None:
            return
        try:
            opened = bool(self.backend.get_value(native))
        except Exception:
            opened = bool(app_data) if isinstance(app_data, bool) else not item.expanded
        if opened == item.expanded:
            return
        item.expanded = opened
        (self.expanded if opened else self.collapsed).emit(key)

    def delete(self):
        self._delete_item_view_policy()
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
        self._selection_handler_by_key.clear()
        self._toggle_handler_by_key.clear()
        super().delete()


__all__ = ["QTreeItem", "QTreeView"]
