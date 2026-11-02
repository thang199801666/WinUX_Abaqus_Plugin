"""DearUIQt-only allocation/dispatch benchmark; no WinUx view or controller."""
import argparse
from collections import deque
import gc
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.dispatch import LatestCallQueue
from DearUIQt.widgets.widget import QWidget


class Backend:
    def does_item_exist(self, tag):
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--widgets', type=int, default=5000)
    parser.add_argument('--keys', type=int, default=30000)
    args = parser.parse_args()
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    backend = Backend()
    after = lambda *args: None
    widgets = [QWidget(index + 1, backend=backend, after=after) for index in range(args.widgets)]
    elapsed = time.perf_counter() - started
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print('WIDGETS count={} heap={:.2f}MiB peak={:.2f}MiB build={:.3f}s queues={}'.format(
        len(widgets), current / 2**20, peak / 2**20, elapsed,
        sum(widget._updates is not None for widget in widgets)), flush=True)

    scheduled, delivered = deque(), []
    queue = LatestCallQueue(lambda delay, callback: scheduled.append(callback))
    for index in range(args.keys):
        queue.post(index, delivered.append, index)
    started = time.perf_counter()
    turns = 0
    while scheduled:
        scheduled.popleft()()
        turns += 1
    elapsed = time.perf_counter() - started
    assert delivered == list(range(args.keys))
    print('DISPATCH keys={} delivery={:.4f}s turns={}'.format(args.keys, elapsed, turns), flush=True)


if __name__ == '__main__':
    main()
