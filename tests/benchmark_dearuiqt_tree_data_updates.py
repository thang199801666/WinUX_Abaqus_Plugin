"""Python/fake-renderer tree data updates, not whole-app/GPU performance."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_tree_data_updates import Backend, QStandardItem, QStandardItemModel, QTreeView


class CountingBackend(Backend):
    def __init__(self):
        super().__init__()
        self.nodes = 0

    def add_selectable(self, **options):
        self.nodes += 1
        return self.add_group(**options)

    add_tree_node = add_selectable


class LegacyTree(QTreeView):
    def _model_changed(self, *args):
        # Previous dataChanged handling always rebuilt the entire model/tree.
        return super()._model_changed()


def sample(optimized):
    model = QStandardItemModel()
    parent = QStandardItem('parent')
    children = [QStandardItem('child ' + str(i)) for i in range(2000)]
    parent.appendRows(children)
    model.appendRow(parent)
    backend = CountingBackend()
    tree = (QTreeView if optimized else LegacyTree)(backend=backend)
    try:
        tree.setModel(model)
        backend.nodes = 0
        started = time.perf_counter()
        for i in range(100):
            children[1000].setText('update ' + str(i))
        elapsed = (time.perf_counter() - started) * 1000
        return elapsed, backend.nodes
    finally:
        tree.delete()
        model.delete()


def main():
    before, after = sample(False), sample(True)
    assert before[1] == 200100 and after[1] == 0
    print('2,001-node tree / 100 one-node label updates: %.2f -> %.2f ms' % (before[0], after[0]))
    print('New native node requests during updates: %d -> %d' % (before[1], after[1]))
    print('Fake renderer + Python model work; excludes GPU, real input and total memory.')


if __name__ == '__main__':
    main()
