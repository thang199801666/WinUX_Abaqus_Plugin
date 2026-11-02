"""Core model bulk insertion work; excludes native views/rendering."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_standard_item_rows import QStandardItem, QStandardItemModel


def sample(bulk):
    model = QStandardItemModel(0, 1)
    root = model.invisibleRootItem()
    root.appendRows([QStandardItem('seed ' + str(i)) for i in range(3000)])
    additions = [QStandardItem('extra ' + str(i)) for i in range(1000)]
    notifications, visits = [0], [0]
    def inserted(*args): notifications[0] += 1
    model.rowsInserted.connect(inserted)
    reindex = root._reindex_children
    def tracked(start=0):
        visits[0] += len(root._rows) - start
        reindex(start)
    root._reindex_children = tracked
    started = time.perf_counter()
    try:
        if bulk:
            root.insertRows(0, additions)
        else:
            # Previous bulk API inserted/reindexed/emitted once per row.
            for offset, item in enumerate(additions):
                root.insertRow(offset, item)
        elapsed = (time.perf_counter() - started) * 1000
        assert model.rowCount() == 4000
        assert all(model.item(i) is item for i, item in enumerate(additions))
        return elapsed, notifications[0], visits[0]
    finally:
        model.delete()


def main():
    before, after = sample(False), sample(True)
    assert before[1:] == (1000, 3001000)
    assert after[1:] == (1, 4000)
    print('Insert 1,000 rows before 3,000 existing rows: %.2f -> %.2f ms' % (before[0], after[0]))
    print('rowsInserted notifications: %d -> %d' % (before[1], after[1]))
    print('Rows visited by index repair: %d -> %d' % (before[2], after[2]))
    print('Backend-neutral Python model work only; not native rendering/FPS or whole-app RAM.')


if __name__ == '__main__':
    main()
