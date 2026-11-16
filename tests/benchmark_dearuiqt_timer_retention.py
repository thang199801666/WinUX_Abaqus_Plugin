"""Stopped-timer Python retention on a host with no cancellation API."""
import gc
from pathlib import Path
import sys
import tracemalloc
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_timer_retention import Host, QTimer


class BoundTickTimer(QTimer):
    def _schedule(self, generation):
        # Previous scheduler transport: the queued bound method owns the timer
        # even after stop() when no host cancellation API exists.
        self._scheduled_handle = self._after(max(1, self._interval), self._tick, generation)


def sample(timer_type, count=3000):
    gc.collect()
    host, references = Host(), []
    tracemalloc.start()
    for _ in range(count):
        timer = timer_type(after=host.after)
        payload = bytearray(1024)
        timer.timeout.connect(lambda captured=payload: captured)
        references.append(weakref.ref(timer))
        timer.start(60000)
        timer.stop()
        del timer, payload
    gc.collect()
    retained = tracemalloc.get_traced_memory()[0] / (1024 * 1024)
    alive = sum(reference() is not None for reference in references)
    tracemalloc.stop()
    assert len(host.pending) == count
    host.pending.clear()
    gc.collect()
    return retained, alive


def main():
    before, before_alive = sample(BoundTickTimer)
    after, after_alive = sample(QTimer)
    assert before_alive == 3000 and after_alive == 0
    print('3,000 stopped timers / 1 KiB captured payload each, no-cancel host:')
    print('Retained Python heap: %.2f -> %.2f MiB' % (before, after))
    print('Timers retained solely by pending scheduler callbacks: %d -> %d' % (before_alive, after_alive))
    print('Pending callback shells remain queued; not total app RSS, native memory or GUI latency.')


if __name__ == '__main__':
    main()
