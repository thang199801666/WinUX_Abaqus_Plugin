"""In-memory transfer row lookup/coalescing, not SSH or whole-app FPS."""
from collections import deque
import itertools
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from WinUx.dialogs.logic.transfer import TransferTaskHandle
from WinUx.runtime.transfer_progress import TransferProgressDelivery


class Center:
    def __init__(self):
        self._row_to_task, self._ids = {}, itertools.count(1)
    def _next_row_id(self):
        return next(self._ids)
    def post(self, *args):
        pass


def main():
    task = TransferTaskHandle(Center(), 'Upload', threading.Event(), ['file{:05d}'.format(i) for i in range(5000)])
    names = [task.rows[(i * 17) % 5000].name for i in range(2000)]
    start = time.perf_counter()
    for name in names:
        matches = [row for row in task.rows if row.name == name]
        assert matches
    old_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    for name in names:
        assert task._row_for_name(name).name == name
    new_ms = (time.perf_counter() - start) * 1000
    queue, samples = deque(), []
    delivery = TransferProgressDelivery(lambda delay, cb: queue.append(cb), lambda *args: samples.append(args))
    start = time.perf_counter()
    for i in range(30000):
        delivery.progress('large.odb', i, 30000, i, 30000)
    post_ms = (time.perf_counter() - start) * 1000
    wakes = len(queue)
    delivery.finish(lambda: None)
    while queue:
        queue.popleft()()
    assert len(samples) == 1 and samples[0][1] == 29999
    print('Isolated 5,000-row/2,000-lookups: scan {:.2f}ms; indexed {:.2f}ms'.format(old_ms, new_ms))
    print('30,000 progress samples posted in {:.2f}ms; {} UI wake, {} latest sample delivered; terminal retained'.format(post_ms, wakes, len(samples)))


if __name__ == '__main__':
    main()
