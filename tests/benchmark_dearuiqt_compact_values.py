"""Allocation benchmark for high-frequency DearUIQt retained/value helpers.

This benchmark measures Python heap only.  It is not total RSS/GPU memory and
it does not include renderer allocations.
"""
from pathlib import Path
import gc
import sys
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import QEvent, QSizePolicy, Signal
from DearUIQt.layouts.box import QLayoutItem


class _LegacySizePolicy:
    def __init__(self):
        self._horizontal = 5
        self._vertical = 5
        self._horizontal_stretch = 0
        self._vertical_stretch = 0
        self._retain_size_when_hidden = False


class _LegacySignal:
    def __init__(self):
        self._slots = ()
        self.owner = None


class _LegacyEvent:
    def __init__(self):
        self._type = 1000
        self.payload = {}
        self._accepted = True


class _LegacyLayoutItem:
    def __init__(self, value):
        self._value = value


def _heap(factory, count=100_000):
    gc.collect()
    tracemalloc.start()
    values = [factory() for _ in range(count)]
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del values
    gc.collect()
    return retained / (1024 * 1024), peak / (1024 * 1024)


def _report(name, before, current):
    reduction = (1.0 - current / before) * 100.0 if before else 0.0
    print('{} count=100000 legacy={:.2f}MiB current={:.2f}MiB reduction={:.1f}%'.format(
        name, before, current, reduction))


def main():
    legacy, _ = _heap(_LegacySizePolicy)
    current, _ = _heap(QSizePolicy)
    _report('QSizePolicy', legacy, current)

    legacy, _ = _heap(_LegacySignal)
    current, _ = _heap(Signal)
    _report('Signal', legacy, current)

    legacy, _ = _heap(_LegacyEvent)
    current, _ = _heap(lambda: QEvent(QEvent.User))
    _report('QEvent', legacy, current)

    token = object()
    legacy, _ = _heap(lambda: _LegacyLayoutItem(token))
    current, _ = _heap(lambda: QLayoutItem(token))
    _report('QLayoutItem', legacy, current)


if __name__ == '__main__':
    main()
