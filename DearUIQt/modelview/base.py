"""Shared retained selection/navigation behavior for item views."""
from __future__ import annotations

from time import monotonic

from ..core.object import Signal, Qt, QPoint, QRect
from ..core.input import QGlobalInputBinding
from ..gui.system import QCursor
from ..core.item_model import QItemSelectionModel, QModelIndex
from ..widgets.widget import QWidget
from .models import QtItemViewState, QtSelectionMode
from .delegates import QStyledItemDelegate, QItemEditorLifecycle, QAbstractItemDelegate
from .policy import QItemViewPolicyMixin

class _QtAbstractItemView(QItemViewPolicyMixin, QWidget):
    NoEditTriggers = 0x00
    CurrentChanged = 0x01
    DoubleClicked = 0x02
    SelectedClicked = 0x04
    EditKeyPressed = 0x08
    AnyKeyPressed = 0x10
    AllEditTriggers = CurrentChanged | DoubleClicked | SelectedClicked | EditKeyPressed | AnyKeyPressed

    MoveUp = 0
    MoveDown = 1
    MoveLeft = 2
    MoveRight = 3
    MoveHome = 4
    MoveEnd = 5
    MovePageUp = 6
    MovePageDown = 7
    MoveNext = 8
    MovePrevious = 9

    EnsureVisible = 0
    PositionAtTop = 1
    PositionAtBottom = 2
    PositionAtCenter = 3

    def __init__(self, tag, *, parent=None, after=None, backend=None, multiple=False):
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.selectionChanged = Signal(self)
        self.currentChanged = Signal(self)
        self.activated = Signal(self)
        self.doubleClicked = Signal(self)
        self.focusChanged = Signal(self)
        self._state = QtItemViewState(multiple=multiple)
        self.multiple = bool(multiple)
        self._focus_handler_registry = None
        self._model = None
        self._model_connections = []
        self._item_delegate = QStyledItemDelegate(self)
        self._row_delegates = {}
        self._column_delegates = {}
        self._selection_model = QItemSelectionModel(parent=self)
        self._selection_model.setCurrentRemovalFallbackEnabled(False)
        self._selection_model_connections = []
        self._selection_sync_depth = 0
        self._connect_selection_model()
        self._persistent_editors = {}
        self._index_widgets = {}
        self._editor_sessions = {}
        self._init_item_view_policy(multiple=multiple)
        # DearPyGui selectable callbacks are delivered on release. On some
        # hosts its transient ``is_mouse_button_double_clicked`` flag has
        # already cleared by then, so retain a tiny Qt-style click history as
        # a backend-independent fallback. This keeps QListView/QListWidget
        # ``doubleClicked`` deterministic without changing single-click
        # selection semantics.
        self._double_click_interval = 0.50
        self._last_row_click_key = None
        self._last_row_click_at = 0.0

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

    def _model_index_for_key(self, key):
        del key
        return QModelIndex()

    def _selection_model_command(self):
        return QItemSelectionModel.Select

    def _key_for_model_index(self, index):
        if (not isinstance(index, QModelIndex) or not index.isValid()
                or index.model() is not self._model or index.parent().isValid()):
            return None
        row_key = getattr(self, '_model_key_for_row', None)
        if callable(row_key):
            key = row_key(index.row())
        else:
            if index.column() != 0:
                return None
            key = index.row()
        return key if key in self._state._key_index else None

    def _connect_selection_model(self):
        for connection in self._selection_model_connections:
            connection.disconnect()
        self._selection_model_connections = [
            self._selection_model.selectionChanged.connect(self._model_selection_changed),
            self._selection_model.currentChanged.connect(self._model_current_changed),
            self._selection_model._structureRemapped.connect(self._model_structure_remapped),
        ]

    def _model_structure_remapped(self):
        self._pull_model_selection(emit=False)

    def _model_selection_changed(self, *_args):
        self._pull_model_selection(selection=True, current=False)

    def _model_current_changed(self, current=None, previous=None):
        self._pull_model_selection(selection=False, current=True)
        if (self._edit_triggers & self.CurrentChanged
                and isinstance(current, QModelIndex) and current.isValid()
                and (not isinstance(previous, QModelIndex) or current != previous)):
            self._edit_from_trigger(self.CurrentChanged, current)

    def _pull_model_selection(self, *, selection=True, current=True, emit=True):
        if self._deleted or self._selection_sync_depth:
            return
        old_selected, old_current = set(self.selected), self.current
        if selection:
            keys = {self._key_for_model_index(index) for index in self._selection_model.selectedIndexes()}
            keys.discard(None)
            self._state.selected = keys
        if current:
            self.current = self._key_for_model_index(self._selection_model.currentIndex())
            self.anchor = self.current
        self._sync_selection_visuals()
        if emit:
            if old_current != self.current:
                self.currentChanged.emit(self.current)
                text_signal = getattr(self, 'currentTextChanged', None)
                if text_signal is not None:
                    text_signal.emit(self.currentText())
            if old_selected != self.selected:
                self.selectionChanged.emit(set(self.selected))

    def _sync_model_selection(self):
        if self._model is None:
            return
        selection_model = self._selection_model
        command = self._selection_model_command()
        indexes = []
        for key in self.selectedKeys():
            index = self._model_index_for_key(key)
            if index is not None and index.isValid():
                indexes.append(index)
        # Replace the complete selection in one transaction. Clearing and then
        # selecting each key separately exposed partial selections to observers
        # and repeatedly copied/sorted the growing selection-model state.
        self._selection_sync_depth += 1
        try:
            selection_model.select(indexes, command | QItemSelectionModel.Clear)
            current = self._model_index_for_key(self.current)
            if current is None or not current.isValid():
                current = QModelIndex()
            selection_model.setCurrentIndex(current, QItemSelectionModel.NoUpdate)
        finally:
            self._selection_sync_depth -= 1

    def model(self):
        return self._model

    def setModel(self, model):
        self._require_ui()
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
        # A view switching models must not retarget a selection model shared
        # with other views. Qt replaces it; the previous object is not deleted.
        self._selection_model = QItemSelectionModel(model, parent=self)
        self._selection_model.setCurrentRemovalFallbackEnabled(False)
        self._connect_selection_model()
        self._state.selected.clear()
        self.current = self.anchor = None
        if model is not None:
            for name in ("modelReset", "dataChanged", "rowsInserted",
                          "rowsRemoved", "columnsInserted", "columnsRemoved", "rowsMoved", "columnsMoved",
                          "layoutChanged", "headerDataChanged", "_headerTaken"):
                signal = getattr(model, name, None)
                if signal is not None:
                    callback = self._model_reset if name == 'modelReset' else self._model_notification
                    self._model_connections.append(signal.connect(callback))
        self._model_changed()
        self._pull_model_selection(emit=False)
        return self

    def _model_reset(self, *_args):
        if self._deleted:
            return
        self._clear_index_editors()
        # A shared selection model may have connected its reset slot *after*
        # this view. Do not depend on modelReset connection ordering.
        self._selection_model.reset()
        self._state.selected.clear()
        self.current = self.anchor = None
        self._model_changed()
        # A structural table renderer may choose a first current row internally;
        # reset must leave the public current index invalid and selection empty.
        self._pull_model_selection(emit=False)

    def _model_notification(self, *args):
        self._model_changed(*args)
        if not (len(args) >= 2 and isinstance(args[0], QModelIndex) and isinstance(args[1], QModelIndex)):
            # Also pull after rebuilding native keys. A shared selection model
            # may remap either before or after this renderer's model slot.
            self._pull_model_selection(emit=False)

    def _model_changed(self, *_args):
        """Hook for concrete views to rebuild from an attached model."""
        return None

    def _clear_index_editors(self):
        for session in list(self._editor_sessions.values()):
            try:
                session.close(QAbstractItemDelegate.NoHint)
            except Exception:
                pass
        self._editor_sessions.clear()
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
        self._require_ui()
        if selection_model is None:
            selection_model = QItemSelectionModel(self._model, parent=self)
        if (not isinstance(selection_model, QItemSelectionModel) or selection_model._deleted
                or selection_model.model() is not self._model):
            raise ValueError('selection model must be live and use the view model')
        if selection_model is self._selection_model:
            return self
        self._selection_model = selection_model
        self._selection_model.setCurrentRemovalFallbackEnabled(False)
        self._connect_selection_model()
        self._pull_model_selection()
        return self

    def currentIndex(self):
        return self._selection_model.currentIndex()

    def setCurrentIndex(self, index):
        if not isinstance(index, QModelIndex):
            index = QModelIndex()
        if index.isValid() and index.model() is not self._model:
            return self
        self._selection_model.setCurrentIndex(index, self._selection_model_command() | QItemSelectionModel.Clear)
        return self

    def editTriggers(self):
        return int(self._edit_triggers)

    def setEditTriggers(self, triggers):
        self._edit_triggers = int(triggers) & int(self.AllEditTriggers)
        return self

    def _index_is_editable(self, index):
        if not isinstance(index, QModelIndex) or not index.isValid():
            return False
        try:
            flags = index.flags()
        except Exception:
            return False
        return bool((flags & Qt.ItemIsEditable) and (flags & Qt.ItemIsEnabled))

    def _edit_from_trigger(self, trigger, index=None):
        if not (self._edit_triggers & int(trigger)):
            return None
        if index is None:
            index = self.currentIndex()
        if not self._index_is_editable(index):
            return None
        return self.edit(index)

    def pageStep(self):
        return max(1, int(getattr(self, "_page_step", 10)))

    def setPageStep(self, rows):
        self._page_step = max(1, int(rows))
        return self

    def moveCursor(self, cursor_action, modifiers=Qt.NoModifier):
        """Return the target QModelIndex for one Qt-style cursor action.

        Concrete views may override this for tree expansion or visual layouts;
        selection mutation is intentionally handled by the caller.
        """
        del modifiers
        model = self._model
        current = self.currentIndex()
        if model is None:
            return QModelIndex()
        if not current.isValid():
            try:
                return model.index(0, 0, QModelIndex()) if model.rowCount(QModelIndex()) else QModelIndex()
            except Exception:
                return QModelIndex()
        parent = current.parent()
        try:
            rows = int(model.rowCount(parent))
            columns = int(model.columnCount(parent))
        except Exception:
            return QModelIndex()
        if rows <= 0 or columns <= 0:
            return QModelIndex()
        row, column = current.row(), current.column()
        action = int(cursor_action)
        if action == self.MoveUp:
            row -= 1
        elif action == self.MoveDown:
            row += 1
        elif action == self.MoveLeft:
            column -= 1
        elif action == self.MoveRight:
            column += 1
        elif action == self.MoveHome:
            column = 0
        elif action == self.MoveEnd:
            column = columns - 1
        elif action == self.MovePageUp:
            row -= self.pageStep()
        elif action == self.MovePageDown:
            row += self.pageStep()
        elif action in (self.MoveNext, self.MovePrevious):
            step = 1 if action == self.MoveNext else -1
            pos = row * columns + column + step
            if pos < 0 or pos >= rows * columns:
                return QModelIndex()
            row, column = divmod(pos, columns)
        else:
            return QModelIndex()
        row = max(0, min(rows - 1, row))
        column = max(0, min(columns - 1, column))
        try:
            target = model.index(row, column, parent)
        except Exception:
            return QModelIndex()
        return target if target is not None and target.isValid() else QModelIndex()

    def scrollTo(self, index, hint=EnsureVisible):
        """Best-effort scroll-to-current without changing native row focus."""
        if not isinstance(index, QModelIndex) or not index.isValid():
            return self
        try:
            key = self._key_for_model_index(index)
        except Exception:
            key = None
        if key is not None:
            native = getattr(self, 'items', {}).get(key)
            self._ensure_native_visible(native, hint=hint)
        return self

    def _cursor_action_for_key(self, key, *, shift=False):
        if key == Qt.Key_Up: return self.MoveUp
        if key == Qt.Key_Down: return self.MoveDown
        if key == Qt.Key_Left: return self.MoveLeft
        if key == Qt.Key_Right: return self.MoveRight
        if key == Qt.Key_Home: return self.MoveHome
        if key == Qt.Key_End: return self.MoveEnd
        if key == Qt.Key_PageUp: return self.MovePageUp
        if key == Qt.Key_PageDown: return self.MovePageDown
        if key == Qt.Key_Backtab or (key == Qt.Key_Tab and shift): return self.MovePrevious
        if key == Qt.Key_Tab: return self.MoveNext
        return None

    def _policy_sync_from_selection(self):
        self._pull_model_selection()

    def _policy_focus_current(self):
        self._focus_current()

    def _apply_model_cursor(self, target, *, ctrl=False, shift=False):
        return self._apply_policy_cursor(target, ctrl=ctrl, shift=shift)

    def _move_model_current(self, key, *, ctrl=False, shift=False):
        return self._move_policy_current(key, ctrl=ctrl, shift=shift)

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

    def _start_editor_lifecycle(self, editor, index, *, destroy_on_close=True):
        if editor is None or self._model is None:
            return None
        delegate = self.itemDelegate(index)
        if delegate is None:
            return None
        key = id(editor)

        def _close(editor_obj, editor_index, hint):
            self._editor_sessions.pop(key, None)
            if destroy_on_close:
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
        return session

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
        if rows <= 0 or columns <= 0:
            return False
        start = index.row() * columns + index.column()
        step = 1 if int(direction) >= 0 else -1
        pos = start + step
        limit = rows * columns
        while 0 <= pos < limit:
            row, column = divmod(pos, columns)
            try:
                candidate = model.index(row, column, parent)
            except Exception:
                candidate = QModelIndex()
            if candidate is not None and candidate.isValid() and (candidate.flags() & Qt.ItemIsEditable):
                self.setCurrentIndex(candidate)
                edit = getattr(self, "edit", None)
                if callable(edit):
                    edit(candidate)
                return True
            pos += step
        return False

    def edit(self, index):
        """Open one transient delegate editor with Qt-style lifecycle policy."""
        if index is None or not getattr(index, "isValid", lambda: False)():
            return None
        delegate = self.itemDelegate(index)
        if delegate is None:
            return None
        editor = delegate.createEditor(self._editor_parent_for_index(index), None, index)
        if editor is None:
            return None
        delegate.setEditorData(editor, index)
        self._start_editor_lifecycle(editor, index, destroy_on_close=True)
        return editor

    def commitEditor(self, editor, index=None, hint=QAbstractItemDelegate.NoHint):
        session = self.editorSession(editor)
        if session is not None and session.isActive():
            return bool(session.commit(hint))
        if index is None or self._model is None:
            return False
        delegate = self.itemDelegate(index)
        if delegate is None:
            return False
        committed = bool(delegate.setModelData(editor, self._model, index))
        if committed:
            delegate.commitData.emit(editor)
            delegate.closeEditor.emit(editor, hint)
        return committed

    def cancelEditor(self, editor):
        session = self.editorSession(editor)
        if session is None or not session.isActive():
            return False
        return bool(session.cancel(QAbstractItemDelegate.RevertModelCache))

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
        # Keep visible model order without scanning every unselected row.
        positions = self._state._key_index
        return sorted((key for key in self.selected if key in positions),
                      key=positions.__getitem__)

    def setCurrentKey(self, key, *, select=True, focus=True, ensure_visible=False):
        if key not in self._state._key_index:
            return False
        if focus:
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
        if focus and ensure_visible:
            self._focus_current()
        return True

    def navigate(self, key, ctrl=False, shift=False):
        b = self.backend
        from ..core.input import QGlobalInputBinding
        key = QGlobalInputBinding.qtKeyForNative(key, b)
        self._set_view_focus(True)
        if key == Qt.Key_F2:
            return bool(self._edit_from_trigger(self.EditKeyPressed))
        if key in (Qt.Key_Return, Qt.Key_Enter):
            return bool(self.activateCurrent())
        if self._model is not None and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                                               Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown,
                                               Qt.Key_Tab, Qt.Key_Backtab):
            return bool(self._move_model_current(key, ctrl=ctrl, shift=shift))
        if ctrl and key == Qt.Key_A and self.multiple:
            self.selectAll()
            return True
        if ctrl and key == Qt.Key_Space and self.current in self._state._key_index:
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
            return True
        if key == Qt.Key_Up:
            target, changed = self._state.move(-1, ctrl=ctrl, shift=shift)
        elif key == Qt.Key_Down:
            target, changed = self._state.move(1, ctrl=ctrl, shift=shift)
        elif key == Qt.Key_Home:
            target, changed = self._state.move(absolute=0, ctrl=ctrl, shift=shift)
        elif key == Qt.Key_End:
            target, changed = self._state.move(absolute=max(0, len(self._state.keys)-1), ctrl=ctrl, shift=shift)
        elif key == Qt.Key_PageUp:
            target, changed = self._state.move(-10, ctrl=ctrl, shift=shift)
        elif key == Qt.Key_PageDown:
            target, changed = self._state.move(10, ctrl=ctrl, shift=shift)
        else:
            return False
        if target is None:
            return False
        self._sync_selection_visuals()
        self._sync_model_selection()
        self._focus_current()
        self.currentChanged.emit(target)
        if changed:
            self.selectionChanged.emit(set(self.selected))
        if self._edit_triggers & self.CurrentChanged:
            self._edit_from_trigger(self.CurrentChanged, self.currentIndex())
        return True

    def activateCurrent(self):
        """QAbstractItemView-style keyboard activation, independent of rendering."""
        if self.current not in self._state.keys or not self.isEnabled():
            return False
        item = self.items.get(self.current)
        if item is not None and not self.backend.get_item_configuration(item).get("enabled", True):
            return False
        self.activated.emit(self.current)
        return True

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = int(event.modifiers())
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        handled = self.navigate(key, ctrl=ctrl, shift=shift)
        if not handled and (self._edit_triggers & self.AnyKeyPressed):
            text = event.text()
            if text and not ctrl:
                handled = self._edit_from_trigger(self.AnyKeyPressed) is not None
        if handled:
            event.accept()
            return
        super().keyPressEvent(event)

    def _row_clicked(self, sender, value, key):
        b = self.backend
        self._set_view_focus(True)
        ctrl = bool(b.is_key_down(b.mvKey_LControl) or b.is_key_down(b.mvKey_RControl))
        shift = bool(b.is_key_down(b.mvKey_LShift) or b.is_key_down(b.mvKey_RShift))
        old_current = self.current
        was_selected = key in self.selected
        changed = self._state.select(key, ctrl=ctrl, shift=shift, selected=bool(value))
        self._sync_selection_visuals()
        self._sync_model_selection()
        if old_current != self.current:
            self.currentChanged.emit(self.current)
        if changed:
            self.selectionChanged.emit(set(self.selected))
        if self._is_double_click(key):
            self.doubleClicked.emit(key)
            self.activated.emit(key)
            self._edit_from_trigger(self.DoubleClicked, self.currentIndex())
        elif was_selected:
            self._edit_from_trigger(self.SelectedClicked, self.currentIndex())

    def _is_double_click(self, key=None):
        """Return whether this delivered row click completes a double-click.

        Prefer the renderer's native double-click state when it is still
        available. DearPyGui can clear that transient state before a
        selectable's release callback, however, so pair two callbacks on the
        same stable row key inside the platform double-click window as a
        fallback. Reset the pair after a match to avoid a third rapid click
        producing a second activation.
        """
        native = False
        try:
            native = bool(self.backend.is_mouse_button_double_clicked(
                self.backend.mvMouseButton_Left))
        except Exception:
            native = False

        now = monotonic()
        previous_key = self._last_row_click_key
        previous_at = self._last_row_click_at
        paired = (
            key is not None
            and previous_key == key
            and 0.0 <= now - previous_at <= self._double_click_interval
        )
        if native or paired:
            self._last_row_click_key = None
            self._last_row_click_at = 0.0
            return True

        self._last_row_click_key = key
        self._last_row_click_at = now
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
        self._delete_item_view_policy()
        self._clear_index_editors()
        for connection in self._model_connections:
            try:
                connection.disconnect()
            except Exception:
                pass
        self._model_connections.clear()
        for connection in self._selection_model_connections:
            connection.disconnect()
        self._selection_model_connections.clear()
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
