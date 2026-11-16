"""Checkpoint-backed dock command history for :class:`QMainWindow`.

M5t intentionally uses full retained-layout checkpoints instead of hand-written
inverse operations.  A history entry stores the runtime dock registry together
with QMainWindow.saveState() before and after a successful semantic command.
Undo/redo restore those checkpoints through a caller supplied restorer.
"""
from __future__ import annotations

from ..core.object import QObject, Signal


class QDockCommandHistory(QObject):
    """Bounded undo/redo history for semantic dock commands.

    ``checkpoint_provider`` must return an opaque checkpoint that can later be
    passed to ``checkpoint_restorer``.  The history never interprets layout
    state, which keeps it reusable and backend-neutral.
    """

    def __init__(self, checkpoint_provider, checkpoint_restorer, *, limit=64,
                 parent=None):
        if not callable(checkpoint_provider):
            raise TypeError("checkpoint provider must be callable")
        if not callable(checkpoint_restorer):
            raise TypeError("checkpoint restorer must be callable")
        super().__init__(parent=parent)
        self._checkpoint_provider = checkpoint_provider
        self._checkpoint_restorer = checkpoint_restorer
        self._limit = max(1, int(limit))
        self._undo = []
        self._redo = []
        self._restoring = False
        self.changed = Signal(self)
        self.recorded = Signal(self)
        self.undone = Signal(self)
        self.redone = Signal(self)
        self.failed = Signal(self)

    def limit(self):
        return self._limit

    def setLimit(self, limit):
        self._limit = max(1, int(limit))
        if len(self._undo) > self._limit:
            del self._undo[:-self._limit]
        if len(self._redo) > self._limit:
            del self._redo[:-self._limit]
        self.changed.emit(self.snapshot())

    def isRestoring(self):
        return bool(self._restoring)

    def canUndo(self):
        return bool(self._undo) and not self._restoring

    def canRedo(self):
        return bool(self._redo) and not self._restoring

    def undoCommand(self):
        return self._undo[-1]["command"] if self._undo else None

    def redoCommand(self):
        return self._redo[-1]["command"] if self._redo else None

    @staticmethod
    def commandText(command):
        if command is None:
            return ""
        metadata = getattr(command, "metadata", None)
        if callable(metadata):
            try:
                values = metadata() or {}
                for key in ("text", "label", "actionText", "title"):
                    value = values.get(key)
                    if value:
                        return str(value)
            except Exception:
                pass
        getter = getattr(command, "command", None)
        if callable(getter):
            try:
                command = getter()
            except Exception:
                pass
        if isinstance(command, dict):
            command = command.get("command") or command.get("type") or ""
        command = str(command or "").strip()
        labels = {
            "add": "Add Dock",
            "remove": "Remove Dock",
            "restore": "Restore Dock Layout",
            "tabify": "Tabify Dock",
            "split": "Split Dock",
            "float": "Float Dock",
            "dock": "Dock",
            "activate": "Activate Tab",
            "move": "Move Tab",
            "detach": "Detach Tab",
            "cancel": "Cancel Dock Operation",
        }
        return labels.get(command.lower(), command.replace("_", " ").strip().title())

    def undoText(self):
        return self.commandText(self.undoCommand())

    def redoText(self):
        return self.commandText(self.redoCommand())

    def clear(self):
        if not self._undo and not self._redo:
            return False
        self._undo[:] = []
        self._redo[:] = []
        self.changed.emit(self.snapshot())
        return True

    def capture(self):
        return self._checkpoint_provider()

    def record(self, command, before, after):
        if self._restoring or before is None or after is None:
            return False
        if self._equivalent(before, after):
            return False
        if self._undo:
            last = self._undo[-1]
            if self._equivalent(last.get("before"), before) and self._equivalent(last.get("after"), after):
                return False
        entry = {"command": command, "before": before, "after": after}
        self._undo.append(entry)
        if len(self._undo) > self._limit:
            del self._undo[:-self._limit]
        self._redo[:] = []
        self.recorded.emit(command, self._entry_snapshot(entry))
        self.changed.emit(self.snapshot())
        return True

    def trackTransition(self, transition):
        """Record one QDockTransition only after its committed signal fires."""
        if transition is None or getattr(transition, "_qt_history_tracked", False):
            return False
        before = self.capture()
        setattr(transition, "_qt_history_tracked", True)

        def committed(*_args):
            if self._restoring:
                return
            command_getter = getattr(transition, "commandObject", None)
            command = command_getter() if callable(command_getter) else transition
            self.record(command, before, self.capture())

        transition.committed.connect(committed)
        return True

    def undo(self):
        if not self.canUndo():
            return False
        entry = self._undo[-1]
        if not self._restore(entry["before"], "undo", entry):
            return False
        self._undo.pop()
        self._redo.append(entry)
        self.undone.emit(entry["command"], self._entry_snapshot(entry))
        self.changed.emit(self.snapshot())
        return True

    def redo(self):
        if not self.canRedo():
            return False
        entry = self._redo[-1]
        if not self._restore(entry["after"], "redo", entry):
            return False
        self._redo.pop()
        self._undo.append(entry)
        self.redone.emit(entry["command"], self._entry_snapshot(entry))
        self.changed.emit(self.snapshot())
        return True

    def _restore(self, checkpoint, direction, entry):
        self._restoring = True
        try:
            result = bool(self._checkpoint_restorer(checkpoint))
            if not result:
                self.failed.emit(direction, entry["command"], None)
            return result
        except Exception as exc:
            self.failed.emit(direction, entry["command"], exc)
            return False
        finally:
            self._restoring = False

    @staticmethod
    def _equivalent(first, second):
        try:
            return first == second
        except Exception:
            return False

    @staticmethod
    def _command_snapshot(command):
        snapshot = getattr(command, "snapshot", None)
        if callable(snapshot):
            try:
                return snapshot()
            except Exception:
                pass
        return command

    def _entry_snapshot(self, entry):
        return {
            "command": self._command_snapshot(entry.get("command")),
            "before": entry.get("before"),
            "after": entry.get("after"),
        }

    def snapshot(self):
        return {
            "limit": self._limit,
            "undoCount": len(self._undo),
            "redoCount": len(self._redo),
            "canUndo": self.canUndo(),
            "canRedo": self.canRedo(),
            "undoText": self.undoText(),
            "redoText": self.redoText(),
            "restoring": self._restoring,
            "undo": [self._command_snapshot(item["command"]) for item in self._undo],
            "redo": [self._command_snapshot(item["command"]) for item in self._redo],
        }

    diagnostics = snapshot
