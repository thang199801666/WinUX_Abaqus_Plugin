"""Compare guarded one-off callbacks with one reusable trailing-edge timer."""
import gc
from pathlib import Path
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import QObject, QTimer, QDebouncer
from DearUIQt.runtime import StandaloneUiHost


def measure(debounced):
    gc.collect()
    tracemalloc.start()
    host = StandaloneUiHost(backend=object())
    parent = QObject(after=host.after)
    received, generation = [], [0]
    started = time.perf_counter()
    if debounced:
        action = QDebouncer(received.append, 60000, parent)
        for index in range(2000):
            action.trigger(index)
    else:
        for index in range(2000):
            generation[0] = index
            QTimer.singleShot(60000, lambda index=index: received.append(index)
                              if index == generation[0] else None, context=parent)
    elapsed = time.perf_counter() - started
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    print('{} updates=2000 retained={:.2f}MiB peak={:.2f}MiB schedule={:.4f}s deadlines={}'.format(
        'DEBOUNCER' if debounced else 'GUARDED_SHOTS', current / 2**20,
        peak / 2**20, elapsed, host.dispatcher.pendingCount()), flush=True)
    parent.delete()
    host.close()
    tracemalloc.stop()


if __name__ == '__main__':
    measure(False)
    measure(True)
