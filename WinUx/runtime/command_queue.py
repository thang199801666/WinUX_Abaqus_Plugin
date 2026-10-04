"""Bounded FIFO commands with opt-in replacement of pending display state."""
from dataclasses import dataclass
import queue


@dataclass
class _Latest:
    key: object
    value: object


class LatestCommandQueue(queue.Queue):
    """Commands form barriers; state replacement never crosses a command."""

    def __init__(self, maxsize=0):
        self._latest = {}
        super().__init__(maxsize)

    def put_latest(self, key, value):
        with self.not_full:
            pending = self._latest.get(key)
            if pending is not None:
                pending.value = value
                return
            if self.maxsize > 0 and self._qsize() >= self.maxsize:
                raise queue.Full
            entry = _Latest(key, value)
            self._put(entry)
            self._latest[key] = entry
            self.unfinished_tasks += 1
            self.not_empty.notify()

    def _put(self, item):
        if not isinstance(item, _Latest):
            self._latest.clear()
        super()._put(item)

    def _get(self):
        item = super()._get()
        if isinstance(item, _Latest):
            if self._latest.get(item.key) is item:
                self._latest.pop(item.key)
            return item.value
        return item
