"""Standard-item sort/layout contracts for the oracle-verified primitive subset."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import Qt, QAbstractItemModel, QItemSelectionModel, QPersistentModelIndex
from DearUIQt.QtGui import QStandardItemModel, QStandardItem


class SortLayoutTests(unittest.TestCase):
    def model(self, texts):
        model = QStandardItemModel()
        for row, text in enumerate(texts):
            model.appendRow([QStandardItem(text), QStandardItem('id%d' % row)])
        self.addCleanup(model.delete)
        return model

    def test_default_item_has_invalid_data_distinct_from_explicit_empty_text(self):
        self.assertIsNone(QStandardItem().data(Qt.DisplayRole))
        self.assertEqual(QStandardItem('').data(Qt.DisplayRole), '')
        self.assertEqual(QStandardItem().text(), '')

    def test_string_sort_is_case_sensitive(self):
        model = self.model(['b', 'A', 'a', 'B'])
        model.sort(0)
        self.assertEqual([model.item(row).text() for row in range(4)], ['A', 'B', 'a', 'b'])

    def test_string_comparison_uses_utf16_code_units(self):
        model = self.model(['\ue000', '\U0001f600', 'a'])
        model.sort(0)
        self.assertEqual([model.item(row).text() for row in range(3)], ['a', '\U0001f600', '\ue000'])

    def test_numeric_sort_is_stable_in_both_directions(self):
        model = self.model(['', '', '', ''])
        for row, value in enumerate((2, 1, 2, 1)):
            model.item(row).setData(value, Qt.DisplayRole)
        model.sort(0)
        self.assertEqual([model.item(row, 1).text() for row in range(4)], ['id1', 'id3', 'id0', 'id2'])
        model.sort(0, Qt.DescendingOrder)
        self.assertEqual([model.item(row, 1).text() for row in range(4)], ['id0', 'id2', 'id1', 'id3'])

    def test_integer_comparison_converts_float_with_qt_rounding_not_truncation(self):
        integer, floating = QStandardItem(), QStandardItem()
        integer.setData(1, Qt.DisplayRole)
        floating.setData(1.6, Qt.DisplayRole)
        self.assertTrue(integer < floating)

    def test_missing_cells_stay_last_but_real_invalid_data_items_follow_comparator(self):
        model = QStandardItemModel(4, 2)
        self.addCleanup(model.delete)
        for row in range(4):
            model.setItem(row, 1, QStandardItem(str(row)))
        model.setItem(0, 0, QStandardItem('b'))
        model.setItem(2, 0, QStandardItem())
        model.setItem(3, 0, QStandardItem(''))
        model.index(1, 0)  # Querying an empty cell must not make it sortable.
        model.sort(0)
        self.assertEqual([model.item(row, 1).text() for row in range(4)], ['3', '0', '2', '1'])
        model.sort(0, Qt.DescendingOrder)
        self.assertEqual([model.item(row, 1).text() for row in range(4)], ['2', '0', '3', '1'])
        self.assertIsNone(model.item(3, 0))

    def test_model_sort_role_applies_to_attached_item_sort_children(self):
        model = self.model(['parent'])
        parent = model.item(0)
        for text, value in (('a', 20), ('z', 10)):
            child = QStandardItem(text)
            child.setData(value, Qt.UserRole)
            parent.appendRow(child)
        model.setSortRole(Qt.UserRole)
        parent.sortChildren(0)
        self.assertEqual([parent.child(row).text() for row in range(2)], ['z', 'a'])

    def test_sort_recurses_into_children_of_all_columns(self):
        model = self.model(['z', 'a'])
        for column in (0, 1):
            parent = model.item(0, column)
            parent.appendRow(QStandardItem('z'))
            parent.appendRow(QStandardItem('a'))
        model.sort(0)
        for column in (0, 1):
            parent = model.item(1, column)
            self.assertEqual([parent.child(row).text() for row in range(2)], ['a', 'z'])

    def test_custom_item_comparator_is_used(self):
        class Reverse(QStandardItem):
            def __lt__(self, other):
                return self.text() > other.text()
        model = QStandardItemModel()
        self.addCleanup(model.delete)
        for text in ('a', 'z', 'm'):
            model.appendRow(Reverse(text))
        model.sort(0)
        self.assertEqual([model.item(row).text() for row in range(3)], ['z', 'm', 'a'])

    def test_negative_or_empty_sort_is_silent_but_past_end_emits_layout(self):
        model = self.model(['a'])
        events = []
        model.layoutChanged.connect(lambda *args: events.append(args))
        model.sort(-1)
        self.assertEqual(events, [])
        model.sort(2)
        self.assertEqual(len(events), 1)
        empty = QStandardItemModel(0, 2)
        self.addCleanup(empty.delete)
        empty.layoutChanged.connect(lambda *args: events.append(args))
        empty.sort(0)
        self.assertEqual(len(events), 1)

    def test_layout_payload_has_scoped_hint_and_persistent_parent(self):
        model = self.model(['z', 'a'])
        parent = model.item(0)
        parent.appendRow(QStandardItem('child'))
        events = []
        model.layoutAboutToBeChanged.connect(lambda parents, hint: events.append((parents, hint)))
        model.layoutChanged.connect(lambda parents, hint: events.append((parents, hint)))
        parent.sortChildren(0)
        self.assertEqual(len(events), 2)
        for parents, hint in events:
            self.assertEqual(parents, [QPersistentModelIndex(parent.index())])
            self.assertEqual(hint, QAbstractItemModel.LayoutChangeHint.VerticalSortHint)

    def test_set_item_layout_payload_uses_no_hint_and_empty_parent_list(self):
        model = self.model(['a'])
        events = []
        model.layoutChanged.connect(lambda parents, hint: events.append((parents, hint)))
        model.setItem(0, 0, QStandardItem('b'))
        self.assertEqual(events, [([], QAbstractItemModel.NoLayoutChangeHint)])

    def test_recursive_sort_keeps_descendant_selection_and_persistent_identity(self):
        model = self.model(['z', 'a'])
        parent = model.item(0)
        parent.appendRow(QStandardItem('z'))
        parent.appendRow(QStandardItem('a'))
        persistent = QPersistentModelIndex(parent.child(0).index())
        selection = QItemSelectionModel(model)
        self.addCleanup(selection.delete)
        selection.setCurrentIndex(parent.child(0).index(), selection.ClearAndSelect)
        events = []
        selection.selectionChanged.connect(lambda *args: events.append(args))
        selection.currentChanged.connect(lambda *args: events.append(args))
        model.sort(0)
        self.assertEqual((persistent.parent().row(), persistent.row(), persistent.data()), (1, 1, 'z'))
        self.assertEqual(selection.currentIndex(), persistent.toModelIndex())
        self.assertEqual(selection.selectedIndexes(), [persistent.toModelIndex()])
        self.assertEqual(events, [])

    def test_detached_sort_uses_display_role(self):
        parent = QStandardItem()
        for text, value in (('b', 0), ('A', 99)):
            child = QStandardItem(text)
            child.setData(value, Qt.UserRole)
            parent.appendRow(child)
        parent.sortChildren(0)
        self.assertEqual([parent.child(row).text() for row in range(2)], ['A', 'b'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
