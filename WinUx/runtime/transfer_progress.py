"""Coalesced per-file progress with an ordered, non-droppable terminal event."""
import threading
import time
from collections import OrderedDict


class TransferProgressDelivery:
    """Keep latest bytes per file, not an unbounded callback per network chunk.

    Files retain first-seen order. Finish/failure is delivered only after all
    earlier file samples, including across bounded UI batches. No extrapolated
    byte counts or background timer/render thread is used.
    """

    def __init__(self, after, progress, *, max_batch=32):
        self._after = after
        self._pending = OrderedDict()
        self._max_batch = max(1, int(max_batch))
        self._scheduled = False
        self._terminal = None
        self._progress = progress
        self._lock = threading.RLock()
        self._finishing = False
        self._closed = False

    def progress(self, name, done, total, overall_done, overall_total):
        with self._lock:
            if self._finishing or self._closed:
                return False
            self._pending[str(name)] = (name, done, total, overall_done, overall_total)
            schedule = not self._scheduled
            self._scheduled = True
        if schedule:
            self._schedule()
        return True

    def finish(self, callback, *args):
        with self._lock:
            if self._finishing or self._closed:
                return False
            self._finishing = True
            self._terminal = callback, args
            schedule = not self._scheduled
            self._scheduled = True
        if schedule:
            self._schedule()
        return True

    def _schedule(self):
        try:
            self._after(0, self._deliver)
        except Exception:
            self.close()
            raise

    def flush_progress(self, time_budget_ms=3):
        """Late UI-frame data flush; never run completion/modal callbacks here."""
        self._deliver(allow_terminal=False, time_budget_ms=time_budget_ms)

    def _deliver(self, allow_terminal=True, time_budget_ms=3):
        # Unlike independent visual keys, file transitions have FIFO meaning.
        # Pop the freshest first key at delivery time; skipping a replaced key
        # must not let later files or the terminal event overtake it.
        started, error = time.perf_counter(), None
        budget = max(0.0, float(time_budget_ms)) / 1000.0
        for processed in range(self._max_batch):
            if processed and time.perf_counter() - started >= budget:
                break
            with self._lock:
                if self._closed:
                    return
                terminal = None
                if self._pending:
                    _name, sample = self._pending.popitem(last=False)
                    progress = self._progress
                elif self._terminal is not None:
                    if not allow_terminal:
                        break
                    terminal, self._terminal = self._terminal, None
                else:
                    if allow_terminal:
                        self._scheduled = False
                    break
            if terminal is not None:
                try:
                    self._finish_ui(*terminal)
                except Exception as exc:
                    if error is None:
                        error = exc
                if error is not None:
                    raise error
                return
            try:
                progress(*sample)
            except Exception as exc:
                if error is None:
                    error = exc
        if allow_terminal:
            with self._lock:
                schedule = not self._closed and bool(self._pending or self._terminal is not None)
                self._scheduled = schedule
            if schedule:
                self._schedule()
        if error is not None:
            raise error

    def _finish_ui(self, callback, args):
        try:
            callback(*args)
        finally:
            self.close()

    def close(self):
        with self._lock:
            self._closed = True
            previous, self._progress = self._progress, None
            pending, self._pending = self._pending, OrderedDict()
            terminal, self._terminal = self._terminal, None
        pending.clear()
        del previous
        del terminal
