"""Model-bound list payload reads/work; no native rendering or GPU timing."""
from pathlib import Path
import sys
import time
from contextlib import ExitStack
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_list_data_updates import Backend, QStandardItemModel, QStandardItem, QtListView


class CountingModel(QStandardItemModel):
    reads = 0
    def data(self, index, role):
        self.reads += 1
        return super().data(index, role)


class FullRefreshList(QtListView):
    def _model_changed(self, *args):
        return super()._model_changed()


def sample(optimized):
    model = CountingModel()
    items = [QStandardItem('row ' + str(i)) for i in range(3000)]
    model.invisibleRootItem().appendRows(items)
    view = (QtListView if optimized else FullRefreshList)(backend=Backend())
    try:
        view.setModel(model)
        model.reads = 0
        started = time.perf_counter()
        for i in range(100):
            items[1500].setText('updated ' + str(i))
        return (time.perf_counter() - started) * 1000, model.reads
    finally:
        view.delete()
        model.delete()


def main():
    with ExitStack() as stack:
        for name in ('qt_list_view_theme', 'qt_item_row_theme', 'qt_check_list_row_theme'):
            stack.enter_context(patch('DearUIQt.modelview.list.' + name, return_value=0))
        before, after = sample(False), sample(True)
    assert before[1] == 900000 and after[1] == 300
    print('3,000-row list / 100 single-row label changes: %.2f -> %.2f ms' % (before[0], after[0]))
    print('Model data reads: %d -> %d' % (before[1], after[1]))
    print('Baseline forces the full-list refresh path; Python/fake-backend work, not GUI FPS or total RAM.')


if __name__ == '__main__':
    main()
