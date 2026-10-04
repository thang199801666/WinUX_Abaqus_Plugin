"""Bounded text storage with monotonic cursors."""

from __future__ import annotations

from collections import deque


class BoundedTextBuffer:
    """Keep the newest text while preserving stable read cursors.

    The class deliberately does not own a lock. Its caller can coordinate the
    buffer with an existing condition variable without nested-lock ordering.
    """

    CHUNK_SIZE = 4096

    def __init__(self, max_chars=1_000_000):
        self.max_chars = max(1, int(max_chars))
        self._chunks = deque()
        self._length = 0
        self._snapshot = ""
        self._start_offset = 0

    def clear(self):
        self._start_offset += self._length
        self._chunks.clear()
        self._length = 0
        self._snapshot = ""

    def append(self, value):
        value = str(value or "")
        if not value:
            return self.cursor()
        # Appending SSH chunks must not copy the entire retained transcript.
        # Bound chunk size as well as transcript size: tiny reads should not
        # allocate one deque node per character, and trimming a large read
        # should not copy a megabyte on every subsequent append.
        position = 0
        if self._chunks and len(self._chunks[-1]) < self.CHUNK_SIZE:
            position = min(len(value), self.CHUNK_SIZE - len(self._chunks[-1]))
            self._chunks[-1] += value[:position]
        self._chunks.extend(
            value[start:start + self.CHUNK_SIZE]
            for start in range(position, len(value), self.CHUNK_SIZE)
        )
        self._length += len(value)
        self._snapshot = None
        overflow = self._length - self.max_chars
        if overflow > 0:
            self._start_offset += overflow
            self._length -= overflow
            while overflow:
                first = self._chunks.popleft()
                if len(first) > overflow:
                    self._chunks.appendleft(first[overflow:])
                    break
                overflow -= len(first)
        return self.cursor()

    def cursor(self):
        return self._start_offset + self._length

    def read_since(self, cursor):
        index = max(0, int(cursor) - self._start_offset)
        if index >= self._length:
            return ""
        if index == 0:
            return self.snapshot()
        # Job completion checks typically need only the newest few chunks.
        remaining = self._length - index
        pieces = []
        for chunk in reversed(self._chunks):
            if len(chunk) >= remaining:
                pieces.append(chunk[-remaining:])
                break
            pieces.append(chunk)
            remaining -= len(chunk)
        return "".join(reversed(pieces))

    def snapshot(self):
        if self._snapshot is None:
            self._snapshot = "".join(self._chunks)
        return self._snapshot

    def __len__(self):
        return self._length
