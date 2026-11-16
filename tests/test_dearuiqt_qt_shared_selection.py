"""Qt-oriented two-way selection/current and shared list/table selection."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.QtCore import QItemSelectionModel, Qt
from DearUIQt.modelview import QtListView, QtDataGridView
from test_dearuiqt_selection_sync import Model, ListBackend, TableBackend


class SharedSelectionTests(unittest.TestCase):
    def setUp(self):
        for module, names in [('list', ('qt_list_view_theme', 'qt_item_row_theme', 'qt_check_list_row_theme')),
                              ('table', ('qt_item_view_theme', 'qt_item_row_theme', 'qt_item_text_theme'))]:
            for name in names:
                patcher = patch('DearUIQt.modelview.' + module + '.' + name, return_value=0)
                patcher.start()
                self.addCleanup(patcher.stop)
        self.model = Model(20, 3)
        self.addCleanup(self.model.delete)

    def view(self, grid=False):
        view = (QtDataGridView(backend=TableBackend(), columns=['A', 'B', 'C'], multiple=True)
                if grid else QtListView(backend=ListBackend(), multiple=True))
        self.addCleanup(view.delete)
        view.setModel(self.model)
        return view

    def shared(self, *views):
        selection = QItemSelectionModel(self.model)
        self.addCleanup(selection.delete)
        for view in views:
            view.setSelectionModel(selection)
        return selection

    def test_external_selection_updates_model_bound_list_without_feedback(self):
        view = self.view()
        selection = view.selectionModel()
        events = []
        selection.selectionChanged.connect(lambda *args: events.append(True))
        selection.select(self.model.index(7, 0), selection.Select)
        self.assertEqual(view.selected, {7})
        self.assertTrue(view.backend.items[view.items[7]]['value'])
        self.assertEqual(events, [True])
        self.assertFalse(view.hasFocus())

    def test_external_current_without_selection_preserves_existing_selection(self):
        view = self.view()
        selection = view.selectionModel()
        selection.select(self.model.index(3, 0), selection.Select)
        selection.setCurrentIndex(self.model.index(5, 0), selection.NoUpdate)
        self.assertEqual(view.selected, {3})
        self.assertEqual(view.current, 5)
        selection.clearCurrentIndex()
        self.assertIsNone(view.current)
        self.assertEqual(view.selected, {3})

    def test_view_set_current_index_changes_visual_and_selects_grid_row(self):
        view = self.view(grid=True)
        index = self.model.index(6, 2)
        view.setCurrentIndex(index)
        self.assertEqual(view.current, 6)
        self.assertEqual(view.currentIndex(), index)
        self.assertEqual(view.selected, {6})
        self.assertEqual(set(view.selectionModel().selectedIndexes()),
                         {self.model.index(6, column) for column in range(3)})

    def test_two_views_share_selection_and_current_from_either_direction(self):
        first, second = self.view(), self.view(grid=True)
        selection = self.shared(first, second)
        events = []
        selection.selectionChanged.connect(lambda *args: events.append(True))
        first.setCurrentKey(7)
        self.assertEqual(second.selected, {7})
        self.assertEqual(second.current, 7)
        self.assertEqual(len(events), 1)
        second.setCurrentKey(9)
        self.assertEqual(first.selected, {9})
        self.assertEqual(first.current, 9)
        self.assertEqual(len(events), 2)
        selection.select(self.model.index(11, 0), selection.Select)
        self.assertEqual(first.selected, {9, 11})
        self.assertEqual(second.selected, {9, 11})
        self.assertEqual(len(events), 3)

    def test_replaced_selection_model_is_disconnected_not_deleted(self):
        view = self.view()
        old = view.selectionModel()
        new = self.shared(view)
        old.select(self.model.index(2, 0), old.Select)
        self.assertFalse(view.selected)
        self.assertFalse(old._deleted)
        new.select(self.model.index(4, 0), new.Select)
        self.assertEqual(view.selected, {4})

    def test_mismatched_selection_model_is_rejected_without_retargeting(self):
        view = self.view()
        other = Model(2, 1)
        selection = QItemSelectionModel(other)
        self.addCleanup(other.delete)
        self.addCleanup(selection.delete)
        old = view.selectionModel()
        with self.assertRaises(ValueError):
            view.setSelectionModel(selection)
        self.assertIs(selection.model(), other)
        self.assertIs(view.selectionModel(), old)

    def test_late_connected_shared_model_reset_clears_both_views_silently(self):
        first, second = self.view(), self.view(grid=True)
        selection = self.shared(first, second)
        first.setCurrentKey(4)
        events = []
        selection.selectionChanged.connect(lambda *args: events.append('selection'))
        selection.currentChanged.connect(lambda *args: events.append('current'))
        self.model.beginResetModel()
        self.model.endResetModel()
        self.assertFalse(events)
        for view in (first, second):
            self.assertFalse(view.selected)
            self.assertIsNone(view.current)
            self.assertTrue(all(not view.backend.items[native].get('value', False)
                                for native in view.items.values()))

    def test_switching_one_view_model_leaves_shared_model_and_other_view_alone(self):
        first, second = self.view(), self.view()
        selection = self.shared(first, second)
        second.setCurrentKey(4)
        other = Model(2, 1)
        self.addCleanup(other.delete)
        first.setModel(other)
        self.assertIs(selection.model(), self.model)
        self.assertIs(second.selectionModel(), selection)
        self.assertEqual(second.selected, {4})
        self.assertFalse(first.selected)
        self.assertIsNone(first.current)
        self.assertIsNot(first.selectionModel(), selection)
        first.setModel(None)
        self.assertFalse(first.items)

    def test_deleted_view_releases_shared_signal_receiver(self):
        view = self.view()
        selection = self.shared(view)
        # Cleanup callbacks retain view, so verify signal disconnection directly.
        view.delete()
        self.assertFalse(any(connection.receiver is view for connection in selection.selectionChanged._slots))
        selection.select(self.model.index(3, 0), selection.Select)
        self.assertTrue(view._deleted)

    def test_external_grid_current_uses_stable_row_key_role(self):
        class StableModel(Model):
            def data(self, index, role=Qt.DisplayRole):
                return 'key ' + str(index.row()) if role == Qt.UserRole else super().data(index, role)
        model = StableModel(20, 3)
        self.addCleanup(model.delete)
        view = self.view(grid=True)
        view.setRowKeyRole(Qt.UserRole)
        view.setModel(model)
        selection = view.selectionModel()
        selection.setCurrentIndex(model.index(5, 2), selection.ClearAndSelect)
        self.assertEqual(view.current, 'key 5')
        self.assertEqual(view.selected, {'key 5'})
        self.assertEqual(selection.selectedRows(), [])  # One cell is not a full model row.
        self.assertEqual(len(selection.selectedIndexes()), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
