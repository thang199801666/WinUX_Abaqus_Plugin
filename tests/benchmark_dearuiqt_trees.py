"""Isolated tree bulk-build work; not full GUI/FPS or application memory."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_tree_batches import Backend, QTreeWidget, QTreeWidgetItem


def sample(count, bulk):
    backend = Backend()
    tree = QTreeWidget(backend=backend)
    items = [QTreeWidgetItem('node ' + str(i)) for i in range(count)]
    start_rows = backend.materialized_rows
    started = time.perf_counter()
    try:
        if bulk:
            tree.addTopLevelItems(items)
        else:
            for item in items:
                tree.addTopLevelItem(item)
        elapsed = (time.perf_counter() - started) * 1000
        return elapsed, backend.materialized_rows - start_rows
    finally:
        tree.delete()


def main():
    count = 250
    before, before_rows = sample(count, False)
    after, after_rows = sample(count, True)
    assert before_rows == count * (count + 1) // 2
    assert after_rows == count
    print('%d top-level items, fake renderer: %.2f -> %.2f ms' % (count, before, after))
    print('Native row materializations: %d -> %d' % (before_rows, after_rows))
    print('Timing includes fake-backend bookkeeping; row counts are the deterministic metric.')


if __name__ == '__main__':
    main()
