"""Bounded, transactional edit history for digitizer state (not image buffers)."""
from functools import wraps


def recorded(label):
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
            if before != engine._snapshot():
                engine._undo_stack.append((label, before))
                del engine._undo_stack[:-engine.HISTORY_LIMIT]
                engine._redo_stack.clear()
                engine.revision += 1
                engine._emit("history_changed")
            return result
        return run
    return decorate
