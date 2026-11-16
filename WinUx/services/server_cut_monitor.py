"""One cancellable supervisor for Explorer's staged remote Cut operations."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import threading
import time

from DearUIQt.core import QObject, QThread, Signal, Qt


@dataclass
class _CutBatch:
    pairs: list
    connection: object
    deadline: float
    retry_at: float = 0.0
    failures: int = 0




class _ServerCutWorker(QObject):
    """QObject worker owning the staged remote-Cut supervisor loop."""

    def __init__(self, monitor, thread):
        super().__init__()
        self.finished = Signal(self)
        self._monitor = monitor
        self._thread = thread

    def run(self):
        try:
            self._monitor._run(self._thread)
        finally:
            self.finished.emit()


class ServerCutMonitor:
    """Commit only disappeared staged paths; back off failed server deletes.

    File existence checks are local. Idle batches cause no server queries.
    Every batch belongs to its original SSH generation; reconnect drops it
    instead of risking a delete in a replacement session.
    """

    def __init__(self, app, clock=None):
        self.app = app
        self._clock = clock or time.monotonic
        self._condition = threading.Condition()
        self._batches = {}
        self._sequence = 0
        self._closed = False
        self._thread = None
        self._worker = None

    def register(self, remote_paths, staged_paths):
        remote_paths, staged_paths = list(remote_paths), list(staged_paths)
        if len(remote_paths) != len(staged_paths):
            raise ValueError("remote and staged Cut paths must match")
        if not remote_paths:
            return None
        with self._condition:
            if self._closed or self.app._closing:
                return None
            self._sequence += 1
            token = self._sequence
            self._batches[token] = _CutBatch(
                list(zip(remote_paths, staged_paths)),
                getattr(self.app, "_connection_generation", None),
                self._clock() + 24 * 60 * 60)
            if self._thread is None:
                thread = QThread(name="winux-server-cut-monitor", daemon=True)
                worker = _ServerCutWorker(self, thread)
                worker.moveToThread(thread)
                thread.started.connect(worker.run, receiver=worker)
                worker.finished.connect(
                    thread.quit, connection_type=Qt.DirectConnection)
                thread.finished.connect(worker.deleteLater, receiver=worker)
                thread.finished.connect(thread.deleteLater)
                self._thread = thread
                self._worker = worker
                thread.start()
            self._condition.notify_all()
        return token

    def _current(self, batch):
        return (not self._closed and not self.app._closing and
                batch.connection == getattr(self.app, "_connection_generation", None))

    def _poll_once(self):
        now = self._clock()
        with self._condition:
            batches = tuple(self._batches.items())
        for token, batch in batches:
            if not self._current(batch) or now >= batch.deadline:
                with self._condition:
                    self._batches.pop(token, None)
                continue
            if now < batch.retry_at:
                continue
            ready = []
            for pair in batch.pairs:
                try:
                    if not pair[1].exists():
                        ready.append(pair)
                except OSError:
                    pass
            if not ready or not self.app.server.connected:
                continue
            committed, failed = 0, False
            for pair in ready:
                if not self._current(batch):
                    break
                server = self.app.server
                with getattr(server, "_connection_lock", nullcontext()):
                    if not self._current(batch):
                        break
                    try:
                        server.delete([pair[0]])
                    except Exception:
                        try:
                            if server.exists(pair[0]):
                                failed = True
                                continue
                        except Exception:
                            failed = True
                            continue
                batch.pairs.remove(pair)
                committed += 1
            if failed:
                batch.failures += 1
                batch.retry_at = self._clock() + min(30.0, 2.0 ** min(5, batch.failures - 1))
            else:
                batch.failures = 0
                batch.retry_at = 0.0
            if not batch.pairs:
                with self._condition:
                    self._batches.pop(token, None)
            if committed:
                self.app.view.after(0, self._announce, batch.connection, committed)

    def _announce(self, connection, count):
        if (not self.app._closing and
                connection == getattr(self.app, "_connection_generation", None)):
            self.app._server_cut_committed_to_explorer(count)

    def _run(self, thread):
        while True:
            with self._condition:
                while (not self._closed and not self._batches and
                       not thread.isInterruptionRequested()):
                    self._condition.wait()
                if self._closed or thread.isInterruptionRequested():
                    return
            self._poll_once()
            with self._condition:
                if self._closed or thread.isInterruptionRequested():
                    return
                self._condition.wait(0.5)

    def close(self):
        thread = None
        with self._condition:
            self._closed = True
            self._batches.clear()
            thread = self._thread
            self._condition.notify_all()
        if thread is not None:
            thread.requestInterruption()
