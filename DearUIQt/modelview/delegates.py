"""Backend-neutral item-delegate contracts.

Delegates bridge a :class:`QAbstractItemModel` to editor widgets.  Renderer
painting remains backend-owned, but editor creation/data transfer follows the
Qt model/view contract so applications no longer wire every editable cell by
hand.
"""
from __future__ import annotations

from ..core.object import QObject, Signal, QSize, Qt, QEvent


class QAbstractItemDelegate(QObject):
    NoHint = 0
    EditNextItem = 1
    EditPreviousItem = 2
    SubmitModelCache = 3
    RevertModelCache = 4

    def __init__(self, parent=None, *, after=None):
        super().__init__(parent, after=after)
        self.commitData = Signal(self)
        self.closeEditor = Signal(self)
        self.sizeHintChanged = Signal(self)

    def createEditor(self, parent, option, index):
        del parent, option, index
        return None

    def destroyEditor(self, editor, index):
        del index
        delete = getattr(editor, "delete", None)
        if callable(delete):
            delete()

    def setEditorData(self, editor, index):
        del editor, index
        return None

    def setModelData(self, editor, model, index):
        del editor, model, index
        return None

    def updateEditorGeometry(self, editor, option, index):
        del index
        if editor is None or option is None:
            return None
        rect = getattr(option, "rect", None)
        if callable(rect):
            rect = rect()
        set_geometry = getattr(editor, "setGeometry", None)
        if rect is not None and callable(set_geometry):
            set_geometry(rect)
        return None

    def editorEvent(self, event, model, option, index):
        del event, model, option, index
        return False

    def helpEvent(self, event, view, option, index):
        del event, view, option, index
        return False

    def sizeHint(self, option=None, index=None):
        del option, index
        return QSize(-1, -1)


class QStyledItemDelegate(QAbstractItemDelegate):
    """Default role-driven editor delegate.

    The DearUIQt renderer still paints ordinary cells itself.  Editing follows
    Qt's delegate pattern: editable indexes get a QLineEdit by default, the
    editor reads ``EditRole`` (falling back to ``DisplayRole``), and commit
    writes ``EditRole`` back to the model.
    """

    def __init__(self, parent=None, *, after=None):
        super().__init__(parent, after=after)
        self._editor_factory = None
        self._undo_stack = None
        self._edit_label = "Edit cell"

    def setUndoStack(self, stack, *, label="Edit cell"):
        self._undo_stack = stack
        self._edit_label = str(label or "Edit cell")
        return True

    def undoStack(self):
        return self._undo_stack

    def displayText(self, value, locale=None):
        del locale
        return "" if value is None else str(value)

    def itemEditorFactory(self):
        return self._editor_factory

    def setItemEditorFactory(self, factory):
        self._editor_factory = factory

    def createEditor(self, parent, option, index):
        del option
        if index is None or not getattr(index, "isValid", lambda: False)():
            return None
        if not (index.flags() & Qt.ItemIsEditable):
            return None
        factory = self._editor_factory
        if factory is not None:
            creator = getattr(factory, "createEditor", None)
            if callable(creator):
                editor = creator(index.data(Qt.EditRole), parent)
                if editor is not None:
                    return editor
        from ..widgets.editors import QLineEdit
        if isinstance(parent, tuple) and len(parent) == 2:
            native_parent, backend = parent
        else:
            native_parent, backend = parent, getattr(parent, "backend", None)
        return QLineEdit(parent=native_parent, backend=backend)

    def setEditorData(self, editor, index):
        if editor is None or index is None:
            return None
        value = index.data(Qt.EditRole)
        if value is None:
            value = index.data(Qt.DisplayRole)
        setter = getattr(editor, "setText", None)
        if callable(setter):
            setter("" if value is None else str(value))
            return value
        setter = getattr(editor, "setValue", None)
        if callable(setter):
            setter(value)
        return value

    def setModelData(self, editor, model, index):
        if editor is None or model is None or index is None:
            return False
        getter = getattr(editor, "text", None)
        if callable(getter):
            value = getter()
        else:
            getter = getattr(editor, "value", None)
            value = getter() if callable(getter) else None
        before = index.data(Qt.EditRole)
        if before is None:
            before = index.data(Qt.DisplayRole)
        changed = before != value
        if not bool(model.setData(index, value, Qt.EditRole)):
            return False
        stack = self._undo_stack
        push = getattr(stack, "push", None)
        if changed and callable(push):
            from ..gui.property_edit import QPropertyEditCommand
            # Capture the retained model/index pair, not the transient editor.
            command = QPropertyEditCommand(
                lambda new_value, _model=model, _index=index:
                    _model.setData(_index, new_value, Qt.EditRole),
                before, value, self._edit_label,
                merge_key=("model-cell", id(model), index.row(), index.column()),
            )
            push(command)
        return True

    def initStyleOption(self, option, index):
        if option is None or index is None:
            return option
        values = {
            "text": self.displayText(index.data(Qt.DisplayRole)),
            "decoration": index.data(Qt.DecorationRole),
            "toolTip": index.data(Qt.ToolTipRole),
            "background": index.data(Qt.BackgroundRole),
            "foreground": index.data(Qt.ForegroundRole),
            "checkState": index.data(Qt.CheckStateRole),
        }
        if isinstance(option, dict):
            option.update(values)
        else:
            for name, value in values.items():
                try:
                    setattr(option, name, value)
                except Exception:
                    pass
        return option


class QItemEditorLifecycle(QObject):
    """Qt-style delegate editor lifecycle controller.

    The controller owns the transient edit session rather than the renderer.
    It translates editor events into the canonical delegate sequence::

        createEditor -> setEditorData -> commitData -> setModelData -> closeEditor

    Escape cancels without touching the model, while Tab/Backtab commit and
    request navigation to the adjacent editable index.  Views may provide a
    ``close_callback`` and ``navigate_callback`` to bridge renderer-specific
    editor teardown/navigation without duplicating lifecycle policy.
    """

    def __init__(self, delegate, editor, model, index, *, parent=None,
                 close_callback=None, navigate_callback=None):
        super().__init__(parent)
        self.started = Signal(self)
        self.committed = Signal(self)
        self.canceled = Signal(self)
        self.closed = Signal(self)
        self.navigationRequested = Signal(self)
        self._delegate = delegate
        self._editor = editor
        self._model = model
        self._index = index
        self._close_callback = close_callback
        self._navigate_callback = navigate_callback
        self._active = True
        self._closing = False
        self._result = None
        self._connections = []
        install = getattr(editor, "installEventFilter", None)
        if callable(install):
            install(self)
        self._bind_editor_signals(editor)
        self.started.emit(editor, index)


    def _bind_editor_signals(self, editor):
        finished = getattr(editor, "editingFinished", None)
        if finished is not None:
            try:
                self._connections.append(finished.connect(
                    lambda *_: self.commit(QAbstractItemDelegate.NoHint), receiver=self))
            except Exception:
                pass
        escape = getattr(editor, "escapePressed", None)
        if escape is not None:
            try:
                self._connections.append(escape.connect(
                    lambda *_: self.cancel(QAbstractItemDelegate.RevertModelCache), receiver=self))
            except Exception:
                pass
        navigation = getattr(editor, "navigationRequested", None)
        if navigation is not None:
            try:
                self._connections.append(navigation.connect(
                    self._native_navigation_requested, receiver=self))
            except Exception:
                pass

    def _native_navigation_requested(self, direction, *_args):
        hint = (QAbstractItemDelegate.EditPreviousItem
                if int(direction) < 0 else QAbstractItemDelegate.EditNextItem)
        return self.commit(hint)

    def editor(self):
        return self._editor

    def index(self):
        return self._index

    def isActive(self):
        return bool(self._active)

    def result(self):
        return self._result

    def commit(self, hint=QAbstractItemDelegate.NoHint):
        if not self._active or self._closing:
            return False
        self._closing = True
        try:
            delegate = self._delegate
            if delegate is None or self._model is None:
                return False
            ok = bool(delegate.setModelData(self._editor, self._model, self._index))
            if not ok:
                return False
            delegate.commitData.emit(self._editor)
            self._result = "committed"
            self.committed.emit(self._editor, self._index)
            self._finish(hint)
            return True
        finally:
            self._closing = False

    def cancel(self, hint=QAbstractItemDelegate.RevertModelCache):
        if not self._active or self._closing:
            return False
        self._closing = True
        try:
            # Restore the editor from the retained model so a persistent editor
            # cannot keep a canceled draft in its native buffer.
            delegate = self._delegate
            if delegate is not None:
                try:
                    delegate.setEditorData(self._editor, self._index)
                except Exception:
                    pass
            self._result = "canceled"
            self.canceled.emit(self._editor, self._index)
            self._finish(hint)
            return True
        finally:
            self._closing = False

    def close(self, hint=QAbstractItemDelegate.NoHint):
        if not self._active:
            return False
        self._result = self._result or "closed"
        self._finish(hint)
        return True

    def _finish(self, hint):
        if not self._active:
            return
        self._active = False
        editor = self._editor
        remove = getattr(editor, "removeEventFilter", None)
        if callable(remove):
            try:
                remove(self)
            except Exception:
                pass
        for connection in list(self._connections):
            try:
                connection.disconnect()
            except Exception:
                pass
        self._connections.clear()
        delegate = self._delegate
        if delegate is not None:
            delegate.closeEditor.emit(editor, hint)
        callback = self._close_callback
        if callable(callback):
            callback(editor, self._index, hint)
        self.closed.emit(editor, self._index, hint)
        if hint in (QAbstractItemDelegate.EditNextItem, QAbstractItemDelegate.EditPreviousItem):
            direction = 1 if hint == QAbstractItemDelegate.EditNextItem else -1
            self.navigationRequested.emit(direction, self._index)
            navigate = self._navigate_callback
            if callable(navigate):
                navigate(direction, self._index)

    def eventFilter(self, watched, event):
        if watched is not self._editor or not self._active:
            return False
        event_type = event.type()
        if event_type == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self.commit(QAbstractItemDelegate.NoHint)
                event.accept()
                return True
            if key == Qt.Key_Tab:
                self.commit(QAbstractItemDelegate.EditNextItem)
                event.accept()
                return True
            if key == Qt.Key_Backtab:
                self.commit(QAbstractItemDelegate.EditPreviousItem)
                event.accept()
                return True
            if key == Qt.Key_Escape:
                self.cancel(QAbstractItemDelegate.RevertModelCache)
                event.accept()
                return True
        elif event_type == QEvent.FocusOut:
            self.commit(QAbstractItemDelegate.NoHint)
            return False
        return False


__all__ = ["QAbstractItemDelegate", "QStyledItemDelegate", "QItemEditorLifecycle"]
