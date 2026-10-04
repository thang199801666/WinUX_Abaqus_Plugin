from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from WinUx.components.server_notepad_tabs import _EditorTabStrip, _ToolTip


def document(path):
    return SimpleNamespace(path=path, dirty=False)


class TabReconciliationTests(unittest.TestCase):
    def fixture(self):
        strip = _EditorTabStrip.__new__(_EditorTabStrip)
        strip._items, strip._order = {}, ()
        strip._on_inner_configure = Mock()
        strip.ensure_visible = Mock()
        strip._update_doc = Mock()
        def create(doc, active=False):
            strip._items[doc.path] = {'cell': Mock(), 'doc': doc}
        strip._create_tab = Mock(side_effect=create)
        return strip

    def test_identical_documents_create_no_tabs_or_pack_calls(self):
        strip = self.fixture()
        docs = [document(str(n)) for n in range(100)]
        strip.rebuild(docs, '0')
        strip._create_tab.reset_mock()
        for item in strip._items.values():
            item['cell'].reset_mock()
        strip.rebuild(iter(docs), '1')
        strip._create_tab.assert_not_called()
        self.assertTrue(all(not item['cell'].method_calls for item in strip._items.values()))
        self.assertEqual(strip._update_doc.call_count, 100)
        strip.ensure_visible.assert_called_with('1')

    def test_add_remove_reorder_preserves_unmodified_cells(self):
        strip = self.fixture()
        a, b, c = map(document, ('a', 'b', 'c'))
        strip.rebuild([a, b])
        original_a = strip._items['a']['cell']
        original_b = strip._items['b']['cell']
        strip._create_tab.reset_mock()
        strip.rebuild([c, a])
        original_b.destroy.assert_called_once_with()
        original_a.destroy.assert_not_called()
        self.assertIs(strip._items['a']['cell'], original_a)
        strip._create_tab.assert_called_once_with(c, active=False)
        self.assertEqual(strip._order, ('c', 'a'))

    def test_replaced_document_recreates_callbacks_and_empty_removes_all(self):
        strip = self.fixture()
        original = document('a')
        strip.rebuild([original])
        cell = strip._items['a']['cell']
        replacement = document('a')
        strip.rebuild([replacement])
        cell.destroy.assert_called_once_with()
        self.assertIs(strip._items['a']['doc'], replacement)
        cell = strip._items['a']['cell']
        strip.rebuild([])
        cell.destroy.assert_called_once_with()
        self.assertEqual(strip._items, {})
        self.assertEqual(strip._order, ())

    def test_tooltip_destroy_cancels_timer_and_removes_window(self):
        widget = Mock()
        tip = _ToolTip(widget, 'Close')
        bound = dict((call.args[0], call.args[1]) for call in widget.bind.call_args_list)
        tip._after, tip._window = 'timer', Mock()
        window = tip._window
        bound['<Destroy>']()
        widget.after_cancel.assert_called_once_with('timer')
        window.destroy.assert_called_once_with()
        self.assertIsNone(tip._after)
        self.assertIsNone(tip._window)


class NativeTkTabTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:
            self.skipTest('Tk display unavailable: {}'.format(exc))
        self.owner = SimpleNamespace(
            _tab_title=lambda doc, **kwargs: doc.path + (' *' if doc.dirty else ''),
            _close_doc=Mock(), _select_doc=Mock(), _show_tab_context_menu=Mock(),
            _active_doc=lambda: None)
        self.strip = _EditorTabStrip(self.owner, self.root)

    def tearDown(self):
        self.root.destroy()

    def test_native_cells_retained_and_callbacks_rebound_for_replacement(self):
        docs = [document('file{}.inp'.format(n)) for n in range(12)]
        self.strip.rebuild(docs, docs[0].path)
        cells = {path: item['cell'] for path, item in self.strip._items.items()}
        with patch.object(tk, 'Frame', wraps=tk.Frame) as frames:
            for _ in range(20):
                self.strip.rebuild(docs, docs[1].path)
            frames.assert_not_called()
        self.assertEqual(cells, {path: item['cell'] for path, item in self.strip._items.items()})
        docs[1].dirty = True
        self.strip.update_doc(docs[1], docs[1].path)
        self.assertTrue(self.strip._items[docs[1].path]['label'].cget('text').endswith(' *'))
        replacement = document(docs[0].path)
        self.strip.rebuild([replacement] + docs[1:])
        self.assertFalse(cells[replacement.path].winfo_exists())
        self.assertEqual(self.strip.inner.pack_slaves(),
            [self.strip._items[doc.path]['cell'] for doc in [replacement] + docs[1:]])
        self.strip._items[replacement.path]['close'].invoke()
        self.owner._close_doc.assert_called_once_with(replacement)
        self.strip.rebuild([])
        self.assertEqual(self.strip.inner.winfo_children(), [])


if __name__ == '__main__':
    unittest.main()
