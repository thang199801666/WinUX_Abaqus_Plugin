"""Model-bound list dataChanged ranges avoid whole-model payload refreshes."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import Qt
from DearUIQt.gui import QStandardItem, QStandardItemModel
from DearUIQt.modelview import QtListView
from test_dearuiqt_list_updates import Backend as ListBackend


class Backend(ListBackend):
    def __init__(self):
        super().__init__()
        self.configurations = []

    def configure_item(self, tag, **options):
        super().configure_item(tag, **options)
        self.configurations.append((tag, options))


class ListDataUpdateTests(unittest.TestCase):
    def setUp(self):
        for name in ('qt_list_view_theme', 'qt_item_row_theme', 'qt_check_list_row_theme'):
            patcher = patch('DearUIQt.modelview.list.' + name, return_value=0)
            patcher.start()
            self.addCleanup(patcher.stop)

    def create(self, checked=False):
        model = QStandardItemModel()
        items = [QStandardItem('row ' + str(i)) for i in range(1000)]
        if checked:
            items[7].setCheckState(Qt.Unchecked)
        model.invisibleRootItem().appendRows(items)
        backend = Backend()
        view = QtListView(backend=backend)
        view.setModel(model)
        self.addCleanup(model.delete)
        self.addCleanup(view.delete)
        backend.writes.clear()
        backend.configurations.clear()
        return model, items, backend, view

    def test_single_label_reads_one_payload_preserving_native_ids_and_current(self):
        model, items, backend, view = self.create()
        view.setCurrentKey(700)
        native, values, untouched = dict(view.items), view._values, view._values[0]
        backend.configurations.clear()
        with patch.object(view, '_item_from_model_index', wraps=view._item_from_model_index) as read:
            items[700].setText('updated')
            self.assertEqual(read.call_count, 1)
        self.assertEqual(view.items, native)
        self.assertIs(view._values, values)
        self.assertIs(view._values[0], untouched)
        self.assertEqual(backend.configurations, [(native[700], {'label': '  updated'})])
        self.assertEqual(view.current, 700)
        self.assertEqual(view.currentText(), 'updated')
        self.assertEqual(view.selected, {700})

    def test_payload_only_change_has_no_native_writes(self):
        model, items, backend, view = self.create()
        payload = object()
        items[500].setData(payload, Qt.UserRole)
        self.assertIs(view.itemData(500), payload)
        self.assertFalse(backend.configurations)
        self.assertFalse(backend.writes)

    def test_enabled_change_updates_only_one_row_and_its_theme(self):
        model, items, backend, view = self.create()
        native = dict(view.items)
        items[500].setEnabled(False)
        self.assertEqual(backend.configurations, [(native[500], {'enabled': False})])
        self.assertEqual(backend.writes, [native[500]])
        self.assertTrue(view._row_visual_state[500][1])
        self.assertEqual(view.items, native)

    def test_existing_checkbox_value_and_enabled_change_are_local(self):
        model, items, backend, view = self.create(checked=True)
        native, checkbox = dict(view.items), view.checkboxes[7]
        items[7].setCheckState(Qt.Checked)
        self.assertEqual(backend.writes, [checkbox])
        self.assertTrue(view.itemForKey(7).checked)
        backend.configurations.clear()
        items[7].setEnabled(False)
        self.assertEqual(backend.configurations, [
            (native[7], {'enabled': False}), (checkbox, {'enabled': False})])
        self.assertEqual(view.items, native)

    def test_checkbox_presence_change_uses_structural_fallback(self):
        model, items, backend, view = self.create()
        view.setCurrentKey(3)
        old = view.items[3]
        with patch.object(view, 'setItems', wraps=view.setItems) as reset:
            items[7].setCheckState(Qt.Checked)
            reset.assert_called_once()
        self.assertIn(7, view.checkboxes)
        self.assertNotEqual(view.items[3], old)
        self.assertEqual(view.selected, {3})

    def test_multirow_range_and_noop_do_not_refresh_other_payloads(self):
        model, items, backend, view = self.create()
        for item in items[20:30]:
            item._data[Qt.DisplayRole] = 'updated ' + item.text()
        untouched = view._values[100]
        model.dataChanged.emit(items[20].index(), items[29].index(), [])
        self.assertEqual(len(backend.configurations), 10)
        self.assertIs(view._values[100], untouched)
        backend.configurations.clear()
        backend.writes.clear()
        model.dataChanged.emit(items[20].index(), items[29].index(), [])
        self.assertFalse(backend.configurations)
        self.assertFalse(backend.writes)

    def test_failed_native_update_reconciles_from_model(self):
        model, items, backend, view = self.create()
        original = backend.configure_item
        once = [True]
        def fail_once(tag, **options):
            if once[0]:
                once[0] = False
                raise RuntimeError('temporary native failure')
            original(tag, **options)
        with patch.object(backend, 'configure_item', side_effect=fail_once), \
                patch.object(view, 'setItems', wraps=view.setItems) as reset:
            items[12].setText('recovered')
            reset.assert_called_once()
        self.assertEqual(view.itemForKey(12).text, 'recovered')
        self.assertEqual(backend.items[view.items[12]]['label'], '  recovered')

    def test_nonzero_model_column_does_not_rebuild_list(self):
        model, items, backend, view = self.create()
        model.setItem(5, 1, QStandardItem('second column'))
        backend.configurations.clear()
        old = view._values
        model.item(5, 1).setText('not a displayed column')
        self.assertIs(view._values, old)
        self.assertFalse(backend.configurations)

    def test_custom_structural_renderer_keeps_its_set_items_hook(self):
        class CustomList(QtListView):
            resets = 0
            def setItems(self, items):
                self.resets += 1
                return super().setItems(items)
        model = QStandardItemModel()
        item = QStandardItem('before')
        model.appendRow(item)
        view = CustomList(backend=Backend())
        self.addCleanup(model.delete)
        self.addCleanup(view.delete)
        view.setModel(model)
        before = view.resets
        item.setText('after')
        self.assertEqual(view.resets, before + 1)
        self.assertEqual(view.itemForKey(0).text, 'after')


if __name__ == '__main__':
    unittest.main(verbosity=2)
