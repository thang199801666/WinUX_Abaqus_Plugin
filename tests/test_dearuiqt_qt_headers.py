"""Qt header data/item structural contracts and DearUIQt ownership safeguards."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import Qt
from DearUIQt.QtGui import QStandardItemModel, QStandardItem


class HeaderLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel(3, 3)
        self.addCleanup(self.model.delete)

    def labels(self, orientation):
        count = self.model.columnCount() if orientation == Qt.Horizontal else self.model.rowCount()
        return [self.model.headerData(section, orientation) for section in range(count)]

    def test_default_headers_are_one_based_display_only_without_items(self):
        self.assertEqual(self.labels(Qt.Horizontal), [1, 2, 3])
        self.assertIsNone(self.model.headerData(0, Qt.Horizontal, Qt.EditRole))
        self.assertIsNone(self.model.horizontalHeaderItem(0))
        for section in (-1, 3):
            self.assertIsNone(self.model.headerData(section, Qt.Vertical))
            self.assertFalse(self.model.setHeaderData(section, Qt.Vertical, 'invalid'))

    def test_set_header_data_materializes_item_and_noop_succeeds_silently(self):
        events = []
        self.model.headerDataChanged.connect(lambda *args: events.append(args))
        self.assertTrue(self.model.setHeaderData(1, Qt.Horizontal, 'B'))
        self.assertEqual(self.model.horizontalHeaderItem(1).text(), 'B')
        self.assertTrue(self.model.setHeaderData(1, Qt.Horizontal, 'B'))
        self.assertEqual(events, [(Qt.Horizontal, 1, 1)])

    def test_header_roles_preserve_numeric_none_and_custom_values(self):
        self.model.setHeaderData(0, Qt.Horizontal, 'payload', Qt.UserRole)
        self.assertIsNone(self.model.headerData(0, Qt.Horizontal))
        self.assertEqual(self.model.headerData(0, Qt.Horizontal, Qt.UserRole), 'payload')
        self.model.setHeaderData(1, Qt.Horizontal, 42)
        self.assertEqual(self.model.headerData(1, Qt.Horizontal), 42)
        self.assertIsInstance(self.model.headerData(1, Qt.Horizontal, Qt.EditRole), int)
        self.model.setHeaderData(1, Qt.Horizontal, None)
        self.assertIsNone(self.model.headerData(1, Qt.Horizontal))
        self.assertIsNone(self.model.headerData(1, Qt.Horizontal, Qt.EditRole))

    def test_header_item_edit_emits_header_signal_not_body_item_or_data(self):
        item = QStandardItem('header')
        self.model.setHorizontalHeaderItem(1, item)
        events = []
        self.model.headerDataChanged.connect(lambda *args: events.append('header'))
        self.model.itemChanged.connect(lambda *args: events.append('item'))
        self.model.dataChanged.connect(lambda *args: events.append('data'))
        item.setText('edited')
        self.assertEqual(events, ['header'])
        self.assertIs(item.model(), self.model)
        self.assertIsNone(item.parent())
        self.assertEqual((item.row(), item.column()), (-1, -1))
        self.assertFalse(item.index().isValid())
        self.assertIsNone(item.index().model())

    def test_labels_expand_both_axes_preserve_tail_and_empty_is_noop(self):
        self.model.setHorizontalHeaderLabels(['A', 'B', 'C'])
        self.model.setHorizontalHeaderLabels(['X'])
        self.model.setHorizontalHeaderLabels([])
        self.assertEqual(self.labels(Qt.Horizontal), ['X', 'B', 'C'])
        self.model.setVerticalHeaderLabels(['r0', 'r1', 'r2', 'r3'])
        self.assertEqual(self.model.rowCount(), 4)
        self.assertEqual(self.labels(Qt.Vertical), ['r0', 'r1', 'r2', 'r3'])

    def test_column_transactions_shift_headers_before_completed_observers(self):
        self.model.setHorizontalHeaderLabels(['A', 'B', 'C'])
        events = []
        self.model.columnsAboutToBeInserted.connect(lambda *args: events.append(self.labels(Qt.Horizontal)))
        self.model.columnsInserted.connect(lambda *args: events.append(self.labels(Qt.Horizontal)))
        self.model.insertColumns(1, 1)
        self.assertEqual(events, [['A', 'B', 'C'], ['A', 2, 'B', 'C']])
        self.model.removeColumns(0, 2)
        self.assertEqual(self.labels(Qt.Horizontal), ['B', 'C'])

    def test_row_transactions_and_body_take_remove_corresponding_header(self):
        self.model.setVerticalHeaderLabels(['A', 'B', 'C'])
        self.model.insertRows(1, 1)
        self.assertEqual(self.labels(Qt.Vertical), ['A', 2, 'B', 'C'])
        self.model.takeRow(2)
        self.assertEqual(self.labels(Qt.Vertical), ['A', 2, 'C'])
        self.model.setHorizontalHeaderLabels(['X', 'Y', 'Z'])
        self.model.takeColumn(1)
        self.assertEqual(self.labels(Qt.Horizontal), ['X', 'Z'])

    def test_take_header_is_silent_detaches_and_can_reinsert_other_axis(self):
        item = QStandardItem('header')
        self.model.setHorizontalHeaderItem(1, item)
        events = []
        self.model.headerDataChanged.connect(lambda *args: events.append(args))
        self.assertIs(self.model.takeHorizontalHeaderItem(1), item)
        self.assertEqual(events, [])
        self.assertIsNone(item.model())
        self.assertEqual(self.model.headerData(1, Qt.Horizontal), 2)
        self.model.setVerticalHeaderItem(0, item)
        self.assertEqual(self.model.headerData(0, Qt.Vertical), 'header')

    def test_nested_transactions_do_not_shift_root_headers(self):
        self.model.setHorizontalHeaderLabels(['A', 'B', 'C'])
        self.model.setVerticalHeaderLabels(['X', 'Y', 'Z'])
        parent = self.model.itemFromIndex(self.model.index(0, 0))
        parent.appendRow(QStandardItem('child'))
        self.model.insertColumns(0, 2, parent.index())
        self.model.insertRows(0, 2, parent.index())
        self.assertEqual(self.labels(Qt.Horizontal), ['A', 'B', 'C'])
        self.assertEqual(self.labels(Qt.Vertical), ['X', 'Y', 'Z'])

    def test_owned_header_cannot_be_stolen_by_body_or_other_header(self):
        item = QStandardItem('header')
        self.model.setHorizontalHeaderItem(1, item)
        with self.assertRaises(ValueError):
            self.model.setVerticalHeaderItem(7, item)
        with self.assertRaises(ValueError):
            self.model.setItem(0, 0, item)
        self.assertEqual(self.model.rowCount(), 3)
        self.assertIs(self.model.horizontalHeaderItem(1), item)

    def test_replacement_removal_and_clear_release_retained_python_headers(self):
        # DearUIQt's Python-object lifetime policy differs from Shiboken deletion:
        # retained replaced/removed items are detached, not destroyed wrappers.
        item = QStandardItem('old')
        self.model.setHorizontalHeaderItem(0, item)
        self.model.setHorizontalHeaderItem(0, QStandardItem('new'))
        self.assertIsNone(item.model())
        retained = self.model.horizontalHeaderItem(0)
        self.model.removeColumn(0)
        self.assertIsNone(retained.model())
        vertical = QStandardItem('vertical')
        self.model.setVerticalHeaderItem(0, vertical)
        self.model.clear()
        self.assertIsNone(vertical.model())
        self.assertIsNone(self.model.horizontalHeaderItem(0))

    def test_body_display_edit_roles_preserve_variant_values_too(self):
        index = self.model.index(0, 0)
        self.model.setData(index, 42)
        self.assertEqual(index.data(Qt.DisplayRole), 42)
        self.assertEqual(index.data(Qt.EditRole), 42)
        self.model.setData(index, None)
        self.assertIsNone(index.data(Qt.DisplayRole))
        self.assertIsNone(index.data(Qt.EditRole))

    def test_header_data_edit_is_allowed_inside_structural_about_to(self):
        self.model.columnsAboutToBeInserted.connect(
            lambda *args: self.model.setHeaderData(1, Qt.Horizontal, 'edited-before-shift'))
        self.model.insertColumns(0, 1)
        self.assertEqual(self.model.headerData(2, Qt.Horizontal), 'edited-before-shift')


if __name__ == '__main__':
    unittest.main(verbosity=2)
