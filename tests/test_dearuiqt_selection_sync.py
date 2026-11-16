"""One-shot view/model selection snapshots, ordering and current invalidation."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import QAbstractTableModel, Qt
from DearUIQt.modelview import QtListView, QtDataGridView
from test_dearuiqt_list_updates import Backend as ListBackend
from test_dearuiqt_table_updates import Backend as TableBackend


class Model(QAbstractTableModel):
    def __init__(self, rows=1000, columns=1):
        super().__init__()
        self.rows, self.columns = rows, columns

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else self.rows

    def columnCount(self, parent=None):
        return self.columns

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return 'cell %d:%d' % (index.row(), index.column())
        return None


class NoScanList(list):
    def __iter__(self):
        raise AssertionError('selectedKeys must not iterate all model keys')


class SelectionSyncTests(unittest.TestCase):
    def setUp(self):
        for module, names in [('list', ('qt_list_view_theme', 'qt_item_row_theme', 'qt_check_list_row_theme')),
                              ('table', ('qt_item_view_theme', 'qt_item_row_theme', 'qt_item_text_theme'))]:
            for name in names:
                patcher = patch('DearUIQt.modelview.' + module + '.' + name, return_value=0)
                patcher.start()
                self.addCleanup(patcher.stop)

    def view(self, rows=1000, columns=1):
        model = Model(rows, columns)
        if columns == 1:
            view = QtListView(backend=ListBackend(), multiple=True)
        else:
            view = QtDataGridView(backend=TableBackend(), columns=['C'] * columns, multiple=True)
        self.addCleanup(view.delete)
        view.setModel(model)
        return view, model

    def record(self, view):
        events = []
        selection = view.selectionModel()
        selection.selectionChanged.connect(lambda added, removed: events.append((
            set(added.indexes()), set(removed.indexes()), set(selection.selectedIndexes()))))
        return events

    def test_select_all_sends_one_complete_snapshot_not_partial_events(self):
        view, model = self.view()
        events = self.record(view)
        view.selectAll()
        expected = {model.index(row, 0) for row in range(1000)}
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], (expected, set(), expected))
        view._sync_model_selection()
        self.assertEqual(len(events), 1, 'unchanged selection must not emit clear/reselect events')

    def test_switch_selection_reports_only_net_delta_and_final_state(self):
        view, model = self.view(10)
        view.selectAll()
        events = self.record(view)
        view.setCurrentKey(7)
        expected = {model.index(7, 0)}
        removed = {model.index(row, 0) for row in range(10) if row != 7}
        self.assertEqual(events, [(set(), removed, expected)])
        self.assertEqual(view.selectionModel().currentIndex(), model.index(7, 0))

    def test_clear_keeps_current_but_explicit_invalid_current_clears_model(self):
        view, model = self.view(10)
        view.setCurrentKey(4)
        events = self.record(view)
        view.clearSelection()
        self.assertEqual(events, [(set(), {model.index(4, 0)}, set())])
        self.assertEqual(view.selectionModel().currentIndex(), model.index(4, 0))
        view.current = None
        view._sync_model_selection()
        self.assertFalse(view.selectionModel().currentIndex().isValid())

    def test_selected_key_order_uses_index_without_full_scan(self):
        view, _ = self.view()
        view._state.keys = NoScanList(view._state.keys)
        view.selected = {999, 7, 500, 'removed'}
        self.assertEqual(view.selectedKeys(), [7, 500, 999])

    def test_grid_batches_all_columns_for_each_selected_row(self):
        view, model = self.view(50, 3)
        events = self.record(view)
        view.selectAll()
        expected = {model.index(row, column) for row in range(50) for column in range(3)}
        self.assertEqual(events, [(expected, set(), expected)])
        events.clear()
        view.setCurrentKey(12)
        selected = {model.index(12, column) for column in range(3)}
        self.assertEqual(events, [(set(), expected - selected, selected)])

    def test_unbound_view_never_touches_selection_model(self):
        view = QtListView(backend=ListBackend())
        self.addCleanup(view.delete)
        with patch.object(view.selectionModel(), 'select') as select:
            view._sync_model_selection()
        select.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
