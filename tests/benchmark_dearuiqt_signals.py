"""Signal snapshot Python heap/dispatch benchmark; no GUI/FPS/RSS claims."""
import gc
from pathlib import Path
import sys
import threading
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.core import Signal
from DearUIQt.core.object import SignalConnection


class LegacySignal(Signal):
    def __init__(self):
        super().__init__()
        self._slots = []

    def emit(self, *args):
        if self.owner is not None and (self.owner._signals_blocked or self.owner._deleted):
            return
        for connection in tuple(self._slots):
            if not connection.active:
                continue
            auto_queue = (connection.queued is None and connection.receiver is not None and
                          threading.get_ident() != connection.receiver.threadId())
            if connection.queued or auto_queue:
                if getattr(connection.receiver, '_after', None) is None:
                    raise RuntimeError('cross-thread signal delivery requires a receiver scheduler')
                connection.receiver._after(0, connection.deliver, args)
            else:
                connection.deliver(args)


def heap(legacy, count=50000):
    gc.collect()
    tracemalloc.start()
    signals = [Signal() for _ in range(count)]
    if legacy:
        for signal in signals:
            signal._slots = []
    retained = tracemalloc.get_traced_memory()[0] / (1024 * 1024)
    tracemalloc.stop()
    assert len(signals) == count
    return retained


def dispatch(legacy, count=500000):
    signal = LegacySignal() if legacy else Signal()
    values = [0]
    def receive(value): values[0] += value
    if legacy:
        signal._slots.append(SignalConnection(signal, receive, None, False))
    else:
        signal.connect(receive, queued=False)
    start = time.perf_counter()
    for _ in range(count):
        signal.emit(1)
    elapsed = (time.perf_counter() - start) * 1000
    assert values[0] == count
    return elapsed


def main():
    before_heap, after_heap = heap(True), heap(False)
    before_dispatch, after_dispatch = dispatch(True), dispatch(False)
    print('50,000 unconnected signals, retained Python heap: %.2f -> %.2f MiB' %
          (before_heap, after_heap))
    print('500,000 one-slot direct emits: %.2f -> %.2f ms' % (before_dispatch, after_dispatch))
    print('Baseline reproduces list snapshots; not total application RAM or GUI latency.')


if __name__ == '__main__':
    main()
