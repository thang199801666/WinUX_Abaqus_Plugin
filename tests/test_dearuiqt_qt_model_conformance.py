"""checkIndex contracts, bounded invariants and seeded structural model audits."""
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel
from DearUIQt.QtGui import QStandardItemModel, QStandardItem
from model_conformance import assert_model_consistent
from qt_move_matrix_fixture import make_matrix_model
from test_dearuiqt_qt_moves import MovingTree, Node


class CountingModel(QAbstractItemModel):
    def __init__(self):
        super().__init__()
        self.parent_calls = 0

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 2

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 2

    def index(self, row, column, parent=QModelIndex()):
        return self.createIndex(row, column) if not parent.isValid() and 0 <= row < 2 and 0 <= column < 2 else QModelIndex()

    def parent(self, index):
        self.parent_calls += 1
        return QModelIndex()


class ModelConformanceTests(unittest.TestCase):
    def setUp(self):
        self.model = CountingModel()
        self.addCleanup(self.model.delete)
        self.flags = QAbstractItemModel.CheckIndexOption

    def audit(self, model, **kwargs):
        return assert_model_consistent(model, QModelIndex(), **kwargs)

    def test_invalid_index_is_accepted_unless_index_is_valid_option_is_set(self):
        self.assertTrue(self.model.checkIndex(QModelIndex()))
        with self.assertLogs('DearUIQt.core.item_model.checkindex', level='WARNING'):
            self.assertFalse(self.model.checkIndex(QModelIndex(), self.flags.IndexIsValid))

    def test_do_not_use_parent_skips_parent_and_bounds_checks(self):
        index = self.model.createIndex(99, 0)
        self.assertTrue(self.model.checkIndex(index, self.flags.DoNotUseParent))
        self.assertEqual(self.model.parent_calls, 0)
        with self.assertLogs('DearUIQt.core.item_model.checkindex', level='WARNING'):
            self.assertFalse(self.model.checkIndex(index))
        self.assertEqual(self.model.parent_calls, 1)

    def test_foreign_model_is_rejected_even_when_parent_checks_are_disabled(self):
        other = CountingModel()
        self.addCleanup(other.delete)
        with self.assertLogs('DearUIQt.core.item_model.checkindex', level='WARNING'):
            self.assertFalse(self.model.checkIndex(other.index(0, 0), self.flags.DoNotUseParent))
        self.assertEqual(self.model.parent_calls, 0)

    def test_parent_is_invalid_option_and_do_not_use_parent_precedence(self):
        standard = QStandardItemModel()
        self.addCleanup(standard.delete)
        parent = QStandardItem('parent')
        parent.appendRow(QStandardItem('child'))
        standard.appendRow(parent)
        child = parent.child(0).index()
        with self.assertLogs('DearUIQt.core.item_model.checkindex', level='WARNING'):
            self.assertFalse(standard.checkIndex(child, self.flags.ParentIsInvalid))
        self.assertTrue(standard.checkIndex(child, self.flags.ParentIsInvalid | self.flags.DoNotUseParent))

    def test_persistent_conversion_and_input_type_validation(self):
        persistent = QPersistentModelIndex(self.model.index(1, 1))
        self.assertTrue(self.model.checkIndex(persistent, self.flags.IndexIsValid))
        self.assertIs(self.model.CheckIndexOptions, self.flags)
        with self.assertRaises(TypeError):
            self.model.checkIndex(None)

    def test_check_index_does_not_claim_to_validate_internal_pointer_identity(self):
        fabricated = self.model.createIndex(0, 0, object())
        self.assertTrue(self.model.checkIndex(fabricated))
        self.assertNotEqual(fabricated, self.model.index(0, 0))

    def test_seeded_standard_item_mutations_preserve_invariants_and_handles(self):
        model = QStandardItemModel()
        self.addCleanup(model.delete)
        for row in range(4):
            model.appendRow([QStandardItem('%d:%d' % (row, col)) for col in range(3)])
        watched = [[model.item(row, col), QPersistentModelIndex(model.index(row, col)), True]
                   for row in range(4) for col in range(3)]
        selection = QItemSelectionModel(model)
        self.addCleanup(selection.delete)
        selection.setCurrentIndex(model.index(1, 1), selection.ClearAndSelect)
        pool = []
        rng = random.Random(68101)
        for step in range(100):
            operation = rng.choice(('insert-row', 'remove-row', 'insert-col', 'remove-col', 'set', 'take', 'sort', 'clear'))
            rows, columns = model.rowCount(), model.columnCount()
            if operation == 'insert-row' and rows < 8:
                model.insertRows(rng.randrange(rows + 1), 1)
            elif operation == 'remove-row' and rows:
                model.removeRows(rng.randrange(rows), 1)
            elif operation == 'insert-col' and columns < 6:
                model.insertColumns(rng.randrange(columns + 1), 1)
            elif operation == 'remove-col' and columns:
                model.removeColumns(rng.randrange(columns), 1)
            elif operation == 'set':
                row, column = rng.randrange(max(1, rows)), rng.randrange(max(1, columns))
                previous = model.index(row, column)
                replaced = [entry for entry in watched if entry[2] and entry[1] == previous]
                item = pool.pop() if pool else QStandardItem('new%d' % step)
                model.setItem(row, column, item)
                # Standard-item replacement preserves the cell's persistent
                # handle, but that handle now references the replacement item.
                for entry in replaced:
                    entry[0] = item
            elif operation == 'take' and rows and columns:
                item = model.takeItem(rng.randrange(rows), rng.randrange(columns))
                if item is not None:
                    pool.append(item)
            elif operation == 'sort':
                model.sort(0)
            elif operation == 'clear':
                model.clear()
            if step % 10 == 0:
                # Reacquire fresh handles after clear/repopulate so the later
                # audit is not merely checking the original invalid handles.
                item = next((model.item(row, col) for row in range(model.rowCount())
                             for col in range(model.columnCount()) if model.item(row, col) is not None), None)
                if item is not None:
                    watched.append([item, QPersistentModelIndex(item.index()), True])
                    selection.setCurrentIndex(item.index(), selection.ClearAndSelect)
            with self.subTest(step=step, operation=operation):
                self.audit(model)
                self.assertTrue(model.checkIndex(selection.currentIndex()))
                for index in selection.selectedIndexes():
                    self.assertTrue(model.checkIndex(index, self.flags.IndexIsValid))
                for entry in watched:
                    item, persistent, alive = entry
                    if item.model() is not model:
                        entry[2] = alive = False
                    self.assertEqual(persistent.isValid(), alive)
                    if alive:
                        self.assertEqual(persistent.toModelIndex(), item.index())

    def test_hierarchical_column_move_fixture_remains_consistent(self):
        model = make_matrix_model(QAbstractItemModel, QModelIndex)()
        self.addCleanup(model.delete)
        persistent = QPersistentModelIndex(model.indexForCell(model.grandchild))
        rng = random.Random(68102)
        for step in range(100):
            source, target = (model.a, model.b) if rng.randrange(2) else (model.b, model.a)
            if not model.columnCount(model.indexForCell(source)):
                source, target = target, source
            source_index, target_index = model.indexForCell(source), model.indexForCell(target)
            first = rng.randrange(model.columnCount(source_index))
            target_column = rng.randrange(model.columnCount(target_index) + 1)
            self.assertTrue(model.moveColumn(source_index, first, target_index, target_column))
            with self.subTest(step=step):
                self.audit(model)
                self.assertEqual(persistent.toModelIndex(), model.indexForCell(model.grandchild))

    def test_hierarchical_row_moves_remain_consistent(self):
        model = MovingTree()
        self.addCleanup(model.delete)
        a, b = Node('A', model.root), Node('B', model.root)
        for parent in (a, b):
            for number in range(3):
                Node(parent.text + str(number), parent)
        grand = Node('grand', a.children[0])
        persistent = QPersistentModelIndex(model.indexForNode(grand))
        rng = random.Random(68103)
        for step in range(100):
            source, target = (a, b) if rng.randrange(2) else (b, a)
            if not source.children:
                source, target = target, source
            self.assertTrue(model.moveRow(model.indexForNode(source), rng.randrange(len(source.children)),
                                          model.indexForNode(target), rng.randrange(len(target.children) + 1)))
            with self.subTest(step=step):
                self.audit(model)
                self.assertEqual(persistent.toModelIndex(), model.indexForNode(grand))

    def test_invariant_helper_rejects_broken_parent_round_trip(self):
        class Broken(CountingModel):
            def rowCount(self, parent=QModelIndex()):
                return 1
            def columnCount(self, parent=QModelIndex()):
                return 1
            def index(self, row, column, parent=QModelIndex()):
                return self.createIndex(row, column) if row == 0 and column == 0 else QModelIndex()
        model = Broken()
        self.addCleanup(model.delete)
        with self.assertRaisesRegex(AssertionError, 'round trip'):
            self.audit(model)

    def test_invariant_helper_rejects_wrong_coordinates(self):
        class Broken(CountingModel):
            def index(self, row, column, parent=QModelIndex()):
                return self.createIndex(0, column) if self.hasIndex(row, column, parent) else QModelIndex()
        model = Broken()
        self.addCleanup(model.delete)
        with self.assertRaisesRegex(AssertionError, 'coordinates'):
            self.audit(model)

    def test_invariant_helper_has_bounded_node_budget(self):
        with self.assertRaisesRegex(AssertionError, 'node budget'):
            self.audit(self.model, max_nodes=3)

    def test_invariant_helper_rejects_negative_counts(self):
        class Broken(CountingModel):
            def rowCount(self, parent=QModelIndex()):
                return -1
        model = Broken()
        self.addCleanup(model.delete)
        with self.assertRaisesRegex(AssertionError, 'rowCount'):
            self.audit(model)


if __name__ == '__main__':
    unittest.main(verbosity=2)
