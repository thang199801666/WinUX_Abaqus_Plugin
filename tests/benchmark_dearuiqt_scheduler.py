"""Standalone library scheduler: cancelled timer retention and due-work delivery."""
import gc
from pathlib import Path
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.runtime import StandaloneUiHost


def main():
    gc.collect()
    tracemalloc.start()
    host = StandaloneUiHost(backend=object())
    noop = lambda: None
    started = time.perf_counter()
    for _ in range(10000):
        token = host.after(60000, noop)
        assert host.after_cancel(token)
    elapsed = time.perf_counter() - started
    gc.collect()
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print('CANCEL timers=10000 retained={:.2f}KiB peak={:.2f}KiB time={:.4f}s'.format(
        retained / 1024, peak / 1024, elapsed), flush=True)

    host = StandaloneUiHost(backend=object())
    delivered = []
    for index in range(30000):
        host.after(0, delivered.append, index)
    started = time.perf_counter()
    turns = 0
    while len(delivered) < 30000:
        host.pump(max_callbacks=256, time_budget_ms=None)
        turns += 1
    elapsed = time.perf_counter() - started
    assert delivered == list(range(30000))
    print('DELIVERY callbacks=30000 time={:.4f}s turns={}'.format(elapsed, turns), flush=True)


if __name__ == '__main__':
    main()
