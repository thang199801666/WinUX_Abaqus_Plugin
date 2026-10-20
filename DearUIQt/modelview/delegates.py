"""Backend-neutral item-delegate contracts.

Delegates bridge a :class:`QAbstractItemModel` to editor widgets.  Renderer
painting remains backend-owned, but editor creation/data transfer follows the
Qt model/view contract so applications no longer wire every editable cell by
hand.
"""
from __future__ import annotations

from ..core.object import QObject, Signal, QSize, Qt


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
        return bool(model.setData(index, value, Qt.EditRole))

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


__all__ = ["QAbstractItemDelegate", "QStyledItemDelegate"]
