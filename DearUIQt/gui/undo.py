"""Qt-style undo command and stack primitives.

``QUndoStack`` supports two compatible modes:

* native command mode when constructed without a history backend; commands are
  pushed as ``QUndoCommand`` instances and the stack owns redo/undo ordering,
  command merging, macros and the clean index;
* retained-history adapter mode when constructed with a backend implementing
  ``canUndo/canRedo/undo/redo/clear`` and exposing ``changed``.  This preserves
  the checkpoint-backed dock-history contract introduced before M5v.

The separation lets WinUx migrate subsystems incrementally without forcing dock
history to abandon its safer saveState/restoreState checkpoints.
"""
from __future__ import annotations

from ..core.object import QObject, Signal, Qt
from .action import QAction


class QUndoCommand:
    """Backend-neutral QUndoCommand-compatible base class.

    Subclasses normally override :meth:`redo` and :meth:`undo`.  ``id`` and
    ``mergeWith`` may be overridden to coalesce adjacent edits.  Child commands
    are executed in insertion order on redo and reverse order on undo, matching
    Qt's composite-command model.
    """

    def __init__(self, text="", parent=None):
        self._text = str(text or "")
        self._action_text = ""
        self._obsolete = False
        self._parent = None
        self._children = []
        if parent is not None:
            parent._append_child(self)

    def _append_child(self, command):
        if not isinstance(command, QUndoCommand):
            raise TypeError("child command must be QUndoCommand")
        if command._parent is self:
            return
        if command._parent is not None:
            try:
                command._parent._children.remove(command)
            except ValueError:
                pass
        command._parent = self
        self._children.append(command)

    def text(self):
        return self._text

    def setText(self, text):
        self._text = str(text or "")

    def actionText(self):
        return self._action_text or self._text

    def setActionText(self, text):
        self._action_text = str(text or "")

    def id(self):
        return -1

    def mergeWith(self, other):
        return False

    def isObsolete(self):
        return bool(self._obsolete)

    def setObsolete(self, obsolete):
        self._obsolete = bool(obsolete)

    def childCount(self):
        return len(self._children)

    def child(self, index):
        try:
            return self._children[int(index)]
        except (IndexError, TypeError, ValueError):
            return None

    def parent(self):
        return self._parent

    def redo(self):
        for command in tuple(self._children):
            command.redo()

    def undo(self):
        for command in reversed(tuple(self._children)):
            command.undo()


class _MacroCommand(QUndoCommand):
    pass


class QUndoStack(QObject):
    """QUndoStack-compatible command stack or retained-history facade."""

    def __init__(self, history=None, parent=None):
        super().__init__(parent=parent)
        self.canUndoChanged = Signal(self)
        self.canRedoChanged = Signal(self)
        self.undoTextChanged = Signal(self)
        self.redoTextChanged = Signal(self)
        self.indexChanged = Signal(self)
        self.cleanChanged = Signal(self)
        self._history = None
        self._history_connection = None
        self._last_state = None

        # Native-command mode state.
        self._commands = []
        self._index = 0
        self._clean_index = 0
        self._undo_limit = 0
        self._macro_stack = []

        if history is not None:
            self.setHistory(history)
        else:
            self._publish_state(force=True)

    # ------------------------------------------------------------------
    # Retained-history adapter mode
    def history(self):
        return self._history

    def setHistory(self, history):
        if history is self._history:
            return False
        if self._history_connection is not None:
            try:
                self._history_connection.disconnect()
            except Exception:
                pass
            self._history_connection = None
        self._history = history
        changed = getattr(history, "changed", None) if history is not None else None
        connect = getattr(changed, "connect", None)
        if callable(connect):
            self._history_connection = connect(self._history_changed, receiver=self)
        self._last_state = None
        self._publish_state(force=True)
        return True

    def _uses_history(self):
        return self._history is not None

    # ------------------------------------------------------------------
    # Native command mode
    def push(self, command):
        if self._uses_history():
            raise RuntimeError("push() is unavailable while a retained history backend is attached")
        if not isinstance(command, QUndoCommand):
            raise TypeError("command must be QUndoCommand")

        # Qt executes redo when a command is pushed.
        command.redo()
        if command.isObsolete():
            self._publish_state()
            return False

        target = self._macro_stack[-1]._children if self._macro_stack else self._commands
        if not self._macro_stack and self._index < len(self._commands):
            del self._commands[self._index:]
            if self._clean_index > self._index:
                self._clean_index = -1
            target = self._commands

        if self._try_merge(target, command):
            self._publish_state()
            return True

        if self._macro_stack:
            self._macro_stack[-1]._append_child(command)
        else:
            self._commands.append(command)
            self._index = len(self._commands)
            self._enforce_undo_limit()
        self._publish_state()
        return True

    def _try_merge(self, target, command):
        if not target:
            return False
        previous = target[-1]
        try:
            command_id = int(command.id())
            previous_id = int(previous.id())
        except Exception:
            return False
        if command_id < 0 or command_id != previous_id:
            return False
        try:
            merged = bool(previous.mergeWith(command))
        except Exception:
            merged = False
        if merged and previous.isObsolete():
            target.pop()
            if not self._macro_stack:
                self._index = len(self._commands)
        return merged

    def beginMacro(self, text):
        if self._uses_history():
            raise RuntimeError("macros are unavailable while a retained history backend is attached")
        macro = _MacroCommand(text)
        self._macro_stack.append(macro)
        return True

    def endMacro(self):
        if self._uses_history():
            raise RuntimeError("macros are unavailable while a retained history backend is attached")
        if not self._macro_stack:
            return False
        macro = self._macro_stack.pop()
        if macro.childCount() == 0:
            self._publish_state()
            return True
        if self._macro_stack:
            self._macro_stack[-1]._append_child(macro)
        else:
            if self._index < len(self._commands):
                del self._commands[self._index:]
                if self._clean_index > self._index:
                    self._clean_index = -1
            self._commands.append(macro)
            self._index = len(self._commands)
            self._enforce_undo_limit()
        self._publish_state()
        return True

    def command(self, index):
        if self._uses_history():
            return None
        try:
            return self._commands[int(index)]
        except (IndexError, TypeError, ValueError):
            return None

    def text(self, index):
        command = self.command(index)
        return command.text() if command is not None else ""

    def setUndoLimit(self, limit):
        if self._uses_history():
            return False
        self._undo_limit = max(0, int(limit))
        self._enforce_undo_limit()
        self._publish_state()
        return True

    def undoLimit(self):
        return int(self._undo_limit)

    def setClean(self):
        if self._uses_history():
            method = getattr(self._history, "setClean", None)
            if callable(method):
                result = method()
                self._publish_state()
                return bool(result) if result is not None else True
            return False
        self._clean_index = self._index
        self._publish_state()
        return True

    def cleanIndex(self):
        if self._uses_history():
            method = getattr(self._history, "cleanIndex", None)
            if callable(method):
                try:
                    return int(method())
                except Exception:
                    pass
            return 0 if self.isClean() else -1
        return int(self._clean_index)

    def _enforce_undo_limit(self):
        limit = int(self._undo_limit)
        if limit <= 0 or len(self._commands) <= limit:
            return
        remove = len(self._commands) - limit
        del self._commands[:remove]
        self._index = max(0, self._index - remove)
        if self._clean_index >= 0:
            self._clean_index -= remove
            if self._clean_index < 0:
                self._clean_index = -1

    # ------------------------------------------------------------------
    # Common public API
    def canUndo(self):
        if self._uses_history():
            method = getattr(self._history, "canUndo", None)
            return bool(method()) if callable(method) else False
        return self._index > 0 and not self._macro_stack

    def canRedo(self):
        if self._uses_history():
            method = getattr(self._history, "canRedo", None)
            return bool(method()) if callable(method) else False
        return self._index < len(self._commands) and not self._macro_stack

    def undo(self):
        if self._uses_history():
            method = getattr(self._history, "undo", None)
            if not callable(method):
                return False
            return bool(method())
        if not self.canUndo():
            return False
        command = self._commands[self._index - 1]
        command.undo()
        self._index -= 1
        self._publish_state()
        return True

    def redo(self):
        if self._uses_history():
            method = getattr(self._history, "redo", None)
            if not callable(method):
                return False
            return bool(method())
        if not self.canRedo():
            return False
        command = self._commands[self._index]
        command.redo()
        self._index += 1
        self._publish_state()
        return True

    def clear(self):
        if self._uses_history():
            method = getattr(self._history, "clear", None)
            return bool(method()) if callable(method) else False
        if not self._commands and self._index == 0:
            return False
        self._commands[:] = []
        self._index = 0
        self._clean_index = 0
        self._macro_stack[:] = []
        self._publish_state()
        return True

    def count(self):
        if self._uses_history():
            snapshot = self._history_snapshot()
            return int(snapshot.get("undoCount", 0)) + int(snapshot.get("redoCount", 0))
        return len(self._commands)

    def index(self):
        if self._uses_history():
            return int(self._history_snapshot().get("undoCount", 0))
        return int(self._index)

    def isClean(self):
        if self._uses_history():
            method = getattr(self._history, "isClean", None)
            if callable(method):
                return bool(method())
            return self.index() == 0
        return self._clean_index >= 0 and self._index == self._clean_index

    def undoText(self):
        if self._uses_history():
            method = getattr(self._history, "undoText", None)
            if callable(method):
                return str(method() or "")
            return ""
        if not self.canUndo():
            return ""
        return str(self._commands[self._index - 1].actionText() or "")

    def redoText(self):
        if self._uses_history():
            method = getattr(self._history, "redoText", None)
            if callable(method):
                return str(method() or "")
            return ""
        if not self.canRedo():
            return ""
        return str(self._commands[self._index].actionText() or "")

    def createUndoAction(self, parent=None, prefix="Undo"):
        action = QAction(str(prefix), parent=parent)
        action.setShortcut("Ctrl+Z")
        action.setShortcutContext(Qt.WindowShortcut)
        action.triggered.connect(lambda *_args: self.undo(), receiver=self)
        self._bind_action(action, undo=True, prefix=str(prefix))
        self._install_action(parent, action)
        return action

    def createRedoAction(self, parent=None, prefix="Redo"):
        action = QAction(str(prefix), parent=parent)
        action.setShortcut("Ctrl+Shift+Z")
        action.setShortcutContext(Qt.WindowShortcut)
        action.triggered.connect(lambda *_args: self.redo(), receiver=self)
        self._bind_action(action, undo=False, prefix=str(prefix))
        self._install_action(parent, action)
        return action

    def _install_action(self, parent, action):
        adder = getattr(parent, "addAction", None)
        if callable(adder):
            try:
                adder(action)
            except Exception:
                pass

    def _bind_action(self, action, *, undo, prefix):
        def sync(*_args):
            if getattr(action, "_deleted", False):
                return
            available = self.canUndo() if undo else self.canRedo()
            text = self.undoText() if undo else self.redoText()
            action.setEnabled(available)
            action.setText(prefix + (" " + text if text else ""))

        self.canUndoChanged.connect(sync, receiver=action)
        self.canRedoChanged.connect(sync, receiver=action)
        self.undoTextChanged.connect(sync, receiver=action)
        self.redoTextChanged.connect(sync, receiver=action)
        sync()

    def _history_snapshot(self):
        snapshot = getattr(self._history, "snapshot", None)
        if callable(snapshot):
            try:
                value = snapshot()
                if isinstance(value, dict):
                    return value
            except Exception:
                pass
        return {}

    def _state(self):
        return {
            "canUndo": self.canUndo(),
            "canRedo": self.canRedo(),
            "undoText": self.undoText(),
            "redoText": self.redoText(),
            "index": self.index(),
            "clean": self.isClean(),
        }

    def _history_changed(self, *_args):
        self._publish_state()

    def _publish_state(self, force=False):
        state = self._state()
        previous = self._last_state or {}
        self._last_state = state
        if force or state["canUndo"] != previous.get("canUndo"):
            self.canUndoChanged.emit(state["canUndo"])
        if force or state["canRedo"] != previous.get("canRedo"):
            self.canRedoChanged.emit(state["canRedo"])
        if force or state["undoText"] != previous.get("undoText"):
            self.undoTextChanged.emit(state["undoText"])
        if force or state["redoText"] != previous.get("redoText"):
            self.redoTextChanged.emit(state["redoText"])
        if force or state["index"] != previous.get("index"):
            self.indexChanged.emit(state["index"])
        if force or state["clean"] != previous.get("clean"):
            self.cleanChanged.emit(state["clean"])

    def delete(self):
        if self._history_connection is not None:
            try:
                self._history_connection.disconnect()
            except Exception:
                pass
            self._history_connection = None
        super().delete()


__all__ = ["QUndoCommand", "QUndoStack"]
