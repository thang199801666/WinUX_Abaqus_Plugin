"""Indexed list payloads and incremental selection, without WinUx or a GPU."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.modelview import QtListView, QtListItem, QListWidget, QListWidgetItem
from test_dearuiqt_layout_cache import Backend as BaseBackend


class Backend(BaseBackend):
    mvKey_LControl, mvKey_RControl, mvKey_LShift, mvKey_RShift = range(4)

    def __init__(self):
        super().__init__()
        self.writes = []
        self.fail_once = None

    add_child_window = add_selectable = add_checkbox = BaseBackend.add_group

    def get_item_children(self, tag, slot=1):
        return [key for key, value in self.items.items() if value.get('parent') == tag]

    def delete_item(self, tag):
        children = {}
        for key, options in self.items.items():
            children.setdefault(options.get('parent'), []).append(key)
        pending = [tag]
        while pending:
            current = pending.pop()
            pending.extend(children.get(current, ()))
            self.items.pop(current, None)

    def bind_item_theme(self, tag, theme):
        if self.fail_once == tag:
            self.fail_once = None
            raise RuntimeError('transient theme failure')

    def set_value(self, tag, value):
        self.items[tag]['value'] = value
        self.writes.append(tag)

    def focus_item(self, tag): pass
    def get_y_scroll(self, tag): return 0
    def set_y_scroll(self, tag, value): pass
    def is_key_down(self, key): return False
    def is_mouse_button_double_clicked(self, button): return False


def make_list(count=1000, **options):
    backend = Backend()
    listing = QtListView(backend=backend, items=[
        QtListItem(i, 'row ' + str(i), {'value': i}) for i in range(count)], **options)
    return backend, listing


class ListUpdateTests(unittest.TestCase):
    def setUp(self):
        self.patchers = [patch('DearUIQt.modelview.list.' + name, return_value=0)
                         for name in ('qt_list_view_theme', 'qt_item_row_theme', 'qt_check_list_row_theme')]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def create(self, count=1000, **options):
        backend, listing = make_list(count, **options)
        self.addCleanup(listing.delete)
        return backend, listing

    def test_selection_reconciles_only_old_and_new_rows(self):
        backend, listing = self.create()
        listing.setCurrentKey(900)
        backend.writes.clear()
        with patch.object(listing, '_value_for_key', wraps=listing._value_for_key) as lookup:
            listing.setCurrentKey(901)
            self.assertLessEqual(lookup.call_count, 2)
        self.assertEqual(set(backend.writes), {listing.items[900], listing.items[901]})
        backend.writes.clear()
        listing._sync_selection_visuals()
        self.assertEqual(backend.writes, [])

    def test_payload_refresh_append_trim_reorder_and_missing_keys(self):
        _, listing = self.create(4)
        listing.setCurrentKey(2)
        incoming = [replace(item, data={'new': item.key}) for item in listing._values]
        listing.setItems(incoming)
        self.assertIs(listing.itemForKey(2), incoming[2])
        self.assertEqual(listing.currentData(), {'new': 2})
        self.assertEqual(listing.currentText(), 'row 2')
        listing.setItems(incoming + [QtListItem(4, 'extra')])
        self.assertEqual(listing.itemForKey(4).text, 'extra')
        listing.setItems(listing._values[:-1])
        self.assertIsNone(listing.itemForKey(4))
        listing.setItems(list(reversed(incoming)))
        self.assertEqual(listing.itemForKey(2).key, 2)
        self.assertEqual(listing.current, 2)
        listing.setItems([])
        self.assertIsNone(listing.itemForKey(2))
        self.assertIsNone(listing.itemData('missing'))
        self.assertEqual(listing.currentText(), '')

    def test_enabled_refresh_and_transient_renderer_failure(self):
        backend, listing = self.create(4)
        listing.setCurrentKey(1)
        backend.fail_once = listing.items[2]
        listing.setCurrentKey(2)
        self.assertIn(2, listing._row_visual_retry)
        backend.writes.clear()
        listing._sync_selection_visuals()
        self.assertEqual(backend.writes, [listing.items[2]])
        self.assertFalse(listing._row_visual_retry)
        listing.setItems([replace(item, enabled=False) if item.key == 2 else item
                          for item in listing._values])
        self.assertTrue(listing._row_visual_state[2][1])

    def test_checkbox_updates_one_payload_without_replacing_list(self):
        backend, listing = self.create(4)
        listing.setItems([replace(item, checked=False) for item in listing._values])
        values = listing._values
        unchanged = listing.itemForKey(1)
        events = []
        listing.itemCheckChanged.connect(lambda key, checked: events.append((key, checked)))
        listing._check_clicked(listing.checkboxes[3], True, 3)
        self.assertIs(listing._values, values)
        self.assertIs(listing.itemForKey(1), unchanged)
        self.assertTrue(listing.itemForKey(3).checked)
        self.assertEqual(events, [(3, True)])
        listing._check_clicked(listing.checkboxes[3], True, 3)
        self.assertEqual(len(events), 1)

    def test_stale_and_disabled_clicks_are_ignored(self):
        _, listing = self.create(4)
        old = listing.items[2]
        listing.setItems(list(reversed(listing._values)))
        listing._clicked(old, True, 2)
        self.assertIsNone(listing.current)
        listing.setItems([replace(item, enabled=False) if item.key == 2 else item
                          for item in listing._values])
        listing._clicked(listing.items[2], True, 2)
        self.assertIsNone(listing.current)
        listing._clicked(listing.items[1], True, 1)
        self.assertEqual(listing.selected, {1})

    def test_double_click_falls_back_to_two_delivered_row_clicks(self):
        backend, listing = self.create(4)
        events = []
        listing.doubleClicked.connect(events.append)
        native = listing.items[2]
        with patch('DearUIQt.modelview.base.monotonic', side_effect=(10.0, 10.2)):
            listing._clicked(native, True, 2)
            self.assertEqual(events, [])
            listing._clicked(native, True, 2)
        self.assertEqual(events, [2])
        self.assertEqual(listing.current, 2)
        self.assertEqual(listing.selected, {2})

    def test_list_widget_item_double_clicked_uses_fallback(self):
        listing = QListWidget(backend=Backend())
        self.addCleanup(listing.delete)
        item = QListWidgetItem('regex("pattern")')
        listing.addItem(item)
        events = []
        listing.itemDoubleClicked.connect(events.append)
        native = listing.items[item.key]
        with patch('DearUIQt.modelview.base.monotonic', side_effect=(15.0, 15.15)):
            listing._clicked(native, True, item.key)
            listing._clicked(native, True, item.key)
        self.assertEqual(events, [item])

    def test_double_click_fallback_requires_same_row(self):
        backend, listing = self.create(4)
        events = []
        listing.doubleClicked.connect(events.append)
        with patch('DearUIQt.modelview.base.monotonic', side_effect=(20.0, 20.1, 20.2)):
            listing._clicked(listing.items[1], True, 1)
            listing._clicked(listing.items[2], True, 2)
            listing._clicked(listing.items[2], True, 2)
        self.assertEqual(events, [2])

    def test_list_widget_keeps_its_public_item_lookup_contract(self):
        listing = QListWidget(backend=Backend())
        self.addCleanup(listing.delete)
        item = QListWidgetItem('Settings')
        listing.addItem(item)
        listing.setCurrentRow(0)
        self.assertIs(listing.itemForKey(item.key), item)
        self.assertEqual(listing.currentText(), 'Settings')
        self.assertTrue(listing._value_for_key(item.key).enabled)

    def test_focus_change_preserves_hover_themes_and_extended_selection(self):
        backend, listing = self.create(4, multiple=True)
        listing.setCurrentKey(1)
        listing._state.select(3, ctrl=True)
        listing._sync_selection_visuals()
        self.assertEqual(listing.selected, {1, 3})
        backend.writes.clear()
        listing._set_view_focus(False)
        self.assertEqual(len(backend.writes), 4)
        self.assertTrue(all(not state[3] for state in listing._row_visual_state.values()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
