"""M6h: shared QStyleOptionViewItem paint-state contract."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import DearUIQt
from DearUIQt.core import Qt
from DearUIQt.gui import QStandardItem, QStandardItemModel
from DearUIQt.modelview import QStyleOptionViewItem, QStyledItemDelegate, QTreeView
from test_dearuiqt_tree_data_updates import Backend


class StyleOptionViewItemTests(unittest.TestCase):
    def test_release_and_public_export(self):
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split('.'))), (1, 116, 0))
        self.assertIs(DearUIQt.QStyleOptionViewItem, QStyleOptionViewItem)

    def create_tree(self):
        backend = Backend()
        model = QStandardItemModel()
        item = QStandardItem('Alpha')
        model.appendRow(item)
        index = item.index()
        model.setData(index, 'tip', Qt.ToolTipRole)
        view = QTreeView(backend=backend)
        view.setModel(model)
        self.addCleanup(view.delete)
        self.addCleanup(model.delete)
        return view, model, index

    def test_option_contains_shared_selection_focus_current_state(self):
        view, _, index = self.create_tree()
        view.setCurrentIndex(index)
        view._set_view_focus(True)
        option = view.styleOptionForIndex(index)
        self.assertTrue(option.selected)
        self.assertTrue(option.current)
        self.assertTrue(option.focused)
        self.assertFalse(option.disabled)
        self.assertIs(option.index, index)
        self.assertIs(option.widget, view)

    def test_delegate_populates_role_data_on_same_option(self):
        view, _, index = self.create_tree()
        option = view.styleOptionForIndex(index, selected=True, hovered=True)
        self.assertEqual(option.text, 'Alpha')
        self.assertEqual(option.toolTip, 'tip')
        self.assertTrue(option.selected)
        self.assertTrue(option.hovered)
        self.assertEqual(option.stateTuple(), (True, False, False, False))
        self.assertEqual(option.paintStateTuple(), (True, False, False, False, True))

    def test_delegate_init_style_option_supports_object_contract(self):
        _, _, index = self.create_tree()
        delegate = QStyledItemDelegate()
        self.addCleanup(delegate.delete)
        option = QStyleOptionViewItem(selected=True, current=True)
        returned = delegate.initStyleOption(option, index)
        self.assertIs(returned, option)
        self.assertEqual(option.text, 'Alpha')
        self.assertTrue(option.selected)
        self.assertTrue(option.current)

    def test_option_copy_is_independent(self):
        option = QStyleOptionViewItem(selected=True, hovered=True, text='A')
        clone = option.copy()
        clone.text = 'B'
        clone.selected = False
        self.assertEqual(option.text, 'A')
        self.assertTrue(option.selected)
        self.assertTrue(option.hovered)


if __name__ == '__main__':
    unittest.main(verbosity=2)
