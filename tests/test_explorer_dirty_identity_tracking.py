"""Dirty identities should be resolved during model replacement/sorting."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.components.explorer.item_model import ExplorerItemModel, stable_item_identity
from WinUx.ui.components.explorer.list_model import ListViewItem


class ExplorerDirtyIdentityTrackingTests(unittest.TestCase):
    def test_dirty_identity_resolves_after_sort(self):
        model = ExplorerItemModel()
        model.items = [
            ListViewItem('b.inp', path='C:/b.inp'),
            ListViewItem('a.inp', path='C:/a.inp'),
            ListViewItem('c.inp', path='C:/c.inp'),
        ]
        incoming = [
            ListViewItem('c.inp', path='C:/c.inp'),
            ListViewItem('b.inp', path='C:/b.inp'),
            ListViewItem('a.inp', path='C:/a.inp'),
        ]
        dirty = {stable_item_identity(incoming[1])}

        state = model.replace(incoming, key='name', ascending=True,
                              changed_identities=dirty)

        self.assertEqual([item.name for item in model.items], ['a.inp', 'b.inp', 'c.inp'])
        self.assertEqual(state.changed, {1})

    def test_omitted_dirty_hints_preserve_legacy_empty_state(self):
        model = ExplorerItemModel()
        state = model.replace([ListViewItem('a.inp', path='C:/a.inp')])
        self.assertEqual(state.changed, set())


if __name__ == '__main__':
    unittest.main(verbosity=2)
