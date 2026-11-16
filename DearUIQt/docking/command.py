"""Unified semantic command object for DearUIQt docking.

``QDockCommand`` is deliberately small and backend-neutral.  QMainWindow,
QDockTabGroupController and QDockTransition may execute the same command model
without sharing one physical executor.  The object records lifecycle state,
result/error diagnostics and optional undo metadata while legacy string/dict
APIs remain source compatible.
"""
from __future__ import annotations


class QDockCommand:
    Pending = "pending"
    Requested = "requested"
    Running = "running"
    Finished = "finished"
    Failed = "failed"
    Canceled = "canceled"

    def __init__(self, command, payload=None, *, source=None, metadata=None,
                 sequence=None):
        command = str(command or "").strip().lower()
        if not command:
            raise ValueError("dock command must not be empty")
        self._command = command
        self._payload = dict(payload or {})
        self._source = None if source is None else str(source)
        self._metadata = dict(metadata or {})
        self._sequence = sequence
        self._status = self.Pending
        self._result = None
        self._error = None
        self._undo = None

    @classmethod
    def coerce(cls, value, payload=None, *, source=None, metadata=None):
        if isinstance(value, cls):
            if payload:
                raise ValueError("payload must be embedded in an existing QDockCommand")
            return value
        return cls(value, payload, source=source, metadata=metadata)

    def command(self):
        return self._command

    type = command

    def payload(self):
        return dict(self._payload)

    def source(self):
        return self._source

    def metadata(self):
        return dict(self._metadata)

    def sequence(self):
        return self._sequence

    def status(self):
        return self._status

    state = status

    def result(self):
        return self._result

    def error(self):
        return self._error

    def isFinished(self):
        return self._status in (self.Finished, self.Failed, self.Canceled)

    def succeeded(self):
        return self._status == self.Finished

    def setUndoCommand(self, command, **payload):
        self._undo = QDockCommand(command, payload, source="undo")
        return self

    def undoCommand(self):
        return self._undo

    def canUndo(self):
        return self._undo is not None

    # Executor-facing lifecycle helpers.  They intentionally return self so a
    # command can be prepared inline without exposing mutable dictionaries.
    def _assign_sequence(self, sequence):
        self._sequence = int(sequence)
        return self

    def _requested(self):
        self._status = self.Requested
        self._error = None
        return self

    def _running(self):
        self._status = self.Running
        return self

    def _finished(self, result=None):
        self._status = self.Finished
        self._result = result
        self._error = None
        return self

    def _failed(self, error):
        self._status = self.Failed
        self._error = error
        return self

    def _canceled(self, reason=None):
        self._status = self.Canceled
        self._error = reason
        return self

    def snapshot(self):
        return {
            "id": self._sequence,
            "command": self._command,
            "type": self._command,
            "payload": dict(self._payload),
            "source": self._source,
            "metadata": dict(self._metadata),
            "status": self._status,
            "result": self._result,
            "error": self._error,
            "canUndo": self.canUndo(),
        }

    toDict = snapshot

    def __repr__(self):
        return "QDockCommand(command={!r}, status={!r}, sequence={!r})".format(
            self._command, self._status, self._sequence)
