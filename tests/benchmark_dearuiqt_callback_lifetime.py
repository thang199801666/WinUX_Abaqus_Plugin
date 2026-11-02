"""Queued invokeMethod must not retain deleted QObject targets until a pump."""
import gc
from pathlib import Path
import sys
import tracemalloc
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import QObject, QMetaObject, Qt
from DearUIQt.runtime import StandaloneUiHost


class Target(QObject):
    def touch(self):
        raise AssertionError('Deleted target was invoked')


def main():
    for use_bound_method in (False, True):
        gc.collect()
        tracemalloc.start()
        host = StandaloneUiHost(backend=object())
        references = []
        for _ in range(1000):
            target = Target(after=host.after)
            target.payload = bytearray(8192)
            references.append(weakref.ref(target))
            QMetaObject.invokeMethod(target, target.touch if use_bound_method else 'touch', Qt.QueuedConnection)
            target.delete()
        del target
        gc.collect()
        retained, peak = tracemalloc.get_traced_memory()
        alive = sum(reference() is not None for reference in references)
        print('QUEUED {} deleted_targets_alive={} retained={:.2f}MiB peak={:.2f}MiB pending={}'.format(
            'bound' if use_bound_method else 'named', alive, retained / 2**20,
            peak / 2**20, host.dispatcher.pendingCount()), flush=True)
        while host.dispatcher.hasPendingEvents():
            host.pump(time_budget_ms=None)
        host.close()
        tracemalloc.stop()


if __name__ == '__main__':
    main()
