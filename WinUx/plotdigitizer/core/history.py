"""QUndoCommand-backed transactional edit history for Plot Digitizer state."""
from functools import wraps
import copy
import time

from DearUIQt import QUndoCommand, QUndoStack


class DigitizerStateCommand(QUndoCommand):
    """Snapshot command for one atomic Plot Digitizer edit.

    The mutation has already happened when the command is pushed, so the first
    ``redo()`` performed by ``QUndoStack.push`` is intentionally a no-op.
    Subsequent redo restores the captured after-state.
    """

    def __init__(self, engine, label, before, after, *, already_applied=True, merge_id=-1, merge_key=None, merge_window=0.0):
        super().__init__(str(label or "Edit"))
        self.engine = engine
        self.before_state = copy.deepcopy(before)
        self.after_state = copy.deepcopy(after)
        self._skip_first_redo = bool(already_applied)
        self._merge_id = int(merge_id)
        self._merge_key = copy.deepcopy(merge_key)
        self._merge_window = max(0.0, float(merge_window or 0.0))
        self._merge_stamp = time.monotonic()

    def redo(self):
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self.engine._restore(copy.deepcopy(self.after_state))

    def undo(self):
        self.engine._restore(copy.deepcopy(self.before_state))

    def id(self):
        return self._merge_id

    def mergeWith(self, other):
        if not isinstance(other, DigitizerStateCommand):
            return False
        if self.engine is not other.engine or self._merge_id < 0 or self._merge_id != other._merge_id:
            return False
        if self._merge_key != other._merge_key:
            return False
        # A merge must be a continuous edit of the exact state produced by the
        # preceding command.  This prevents coalescing across an intervening edit
        # even when a caller accidentally reuses the same merge key.
        if self.after_state != other.before_state:
            return False
        window = min(self._merge_window, other._merge_window)
        if window <= 0.0 or (other._merge_stamp - self._merge_stamp) > window:
            return False
        self.after_state = copy.deepcopy(other.after_state)
        self._merge_stamp = other._merge_stamp
        self.setText(other.text() or self.text())
        return True


class _HistoryListView:
    """Compatibility list view for legacy ``_undo_stack/_redo_stack`` users."""

    def __init__(self, engine, redo=False):
        self.engine = engine
        self.redo = bool(redo)

    def _items(self):
        stack = self.engine._undo_qstack
        commands = list(getattr(stack, "_commands", ()))
        index = int(stack.index())
        if self.redo:
            commands = list(reversed(commands[index:]))
            return [(command.text(), copy.deepcopy(command.after_state)) for command in commands]
        commands = commands[:index]
        return [(command.text(), copy.deepcopy(command.before_state)) for command in commands]

    def __len__(self):
        return len(self._items())

    def __bool__(self):
        return bool(len(self))

    def __iter__(self):
        return iter(self._items())

    def __getitem__(self, index):
        return self._items()[index]

    def clear(self):
        stack = self.engine._undo_qstack
        commands = list(getattr(stack, "_commands", ()))
        current = int(stack.index())
        if self.redo:
            del commands[current:]
        else:
            commands = commands[current:]
            current = 0
        stack._commands = commands
        stack._index = current
        stack._clean_index = min(getattr(stack, "_clean_index", 0), current)
        stack._publish_state(force=True)
        self.engine._emit("history_changed")

    def pop(self, index=-1):
        items = self._items()
        value = items[index]
        stack = self.engine._undo_qstack
        if self.redo:
            pending = list(getattr(stack, "_commands", ()))[stack.index():]
            actual = len(pending) - 1 - (index if index >= 0 else len(items) + index)
            del stack._commands[stack.index() + actual]
        else:
            applied = list(getattr(stack, "_commands", ()))[:stack.index()]
            actual = index if index >= 0 else len(applied) + index
            del stack._commands[actual]
            stack._index -= 1
        stack._publish_state(force=True)
        self.engine._emit("history_changed")
        return value



def install_history(engine):
    engine._undo_qstack = QUndoStack()
    engine._undo_qstack.setUndoLimit(engine.HISTORY_LIMIT)
    engine._undo_stack = _HistoryListView(engine, redo=False)
    engine._redo_stack = _HistoryListView(engine, redo=True)



def record_edit(engine, label, before, after, *, merge_id=-1, merge_key=None, merge_window=0.0):
    command = DigitizerStateCommand(engine, label, before, after, already_applied=True,
                                    merge_id=merge_id, merge_key=merge_key, merge_window=merge_window)
    engine._undo_qstack.push(command)
    engine.revision += 1
    engine._emit("history_changed")
    return command



def restore_history(engine, undo_entries, redo_entries, current_state):
    """Restore legacy PDG history entries into the QUndoStack command timeline."""
    commands = []
    undo_entries = list(undo_entries or [])
    redo_entries = list(redo_entries or [])

    # Applied commands: legacy entries store each command's before-state.
    for i, (label, before) in enumerate(undo_entries):
        if i + 1 < len(undo_entries):
            after = undo_entries[i + 1][1]
        else:
            after = current_state
        commands.append(DigitizerStateCommand(engine, label, before, after, already_applied=False))

    # Pending commands: legacy redo stack is LIFO, so reverse it to chronological order.
    prior = current_state
    for label, after in reversed(redo_entries):
        commands.append(DigitizerStateCommand(engine, label, prior, after, already_applied=False))
        prior = after

    stack = engine._undo_qstack
    stack._commands = commands[-engine.HISTORY_LIMIT:]
    applied = min(len(undo_entries), len(stack._commands))
    stack._index = applied
    stack._clean_index = -1
    stack._macro_stack = []
    stack._publish_state(force=True)



def recorded(label, *, merge_id=-1, merge_key=None, merge_window=0.0, merge_guard=None):
    def decorate(method):
        @wraps(method)
        def run(engine, *args, **kwargs):
            if engine._edit_depth:
                return method(engine, *args, **kwargs)
            before = engine._snapshot()
            engine._edit_depth += 1
            try:
                result = method(engine, *args, **kwargs)
            except Exception:
                if before != engine._snapshot():
                    engine._restore(before)
                raise
            finally:
                engine._edit_depth -= 1
            after = engine._snapshot()
            if before != after:
                key = merge_key
                if callable(key):
                    try:
                        key = key(engine, *args, **kwargs)
                    except Exception:
                        key = None
                if key is not None and callable(merge_guard):
                    try:
                        if not merge_guard(engine, before, after, *args, **kwargs):
                            key = None
                    except Exception:
                        key = None
                effective_id = int(merge_id) if key is not None else -1
                record_edit(engine, label, before, after, merge_id=effective_id,
                            merge_key=key, merge_window=merge_window)
            return result
        return run
    return decorate
