"""Watcher snapshots reconcile retained rows rather than clearing the canvas."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.ui.components.explorer_row_registry import ExplorerRowRegistryMixin


class Registry(ExplorerRowRegistryMixin):
    def __init__(self):
        self.items = [object(), object()]
        self._header_items = {"name": {}}
        self._body_canvas_widget = SimpleNamespace(exists=lambda: True)
        self._cell_values, self._cell_styles, self._item_icons = {}, {}, {}
        self._replace_row_registry([
            {"index": i, "texts": {"name": i + 10}, "content_changed": False}
            for i in range(2)])
        self._destroy_body_row = Mock()
        self.bindings = []

    def _visible_columns(self):
        return [{"key": "name"}]

    def _bind_body_row(self, row, index, preserve_geometry=False):
        self.bindings.append((row, index, preserve_geometry))
        row["index"] = index

    def _create_body_row(self, index):
        return {"index": index, "texts": {"name": index + 100}}


class IncrementalRowsTests(unittest.TestCase):
    def test_reorder_reuses_rows_by_identity_not_index(self):
        view = Registry()
        first, second = view._row_items
        self.assertTrue(view._row_registry_can_reconcile(["a", "b"], ["b", "a"]))
        changed = view._reconcile_body_rows(["a", "b"], ["b", "a"])
        self.assertEqual(view._row_items, [second, first])
        self.assertEqual(changed, [0, 1])
        self.assertEqual((first["index"], second["index"]), (1, 0))
        view._destroy_body_row.assert_not_called()

    def test_insert_delete_destroys_only_removed_entry(self):
        view = Registry()
        first, second = view._row_items
        view._reconcile_body_rows(["a", "b"], ["b", "c"])
        self.assertIs(view._row_registry[0], second)
        self.assertNotIn(first, view._row_items)
        view._destroy_body_row.assert_called_once_with(first)

    def test_unchanged_content_needs_no_layout(self):
        view = Registry()
        self.assertEqual(view._reconcile_body_rows(["a", "b"], ["a", "b"]), [])
        self.assertTrue(all(binding[2] for binding in view.bindings))

    def test_only_changed_metadata_row_needs_layout(self):
        view = Registry()
        view._row_items[1]["content_changed"] = True
        self.assertEqual(view._reconcile_body_rows(["a", "b"], ["a", "b"]), [1])

    def test_duplicate_identity_and_custom_cells_use_safe_fallback(self):
        view = Registry()
        self.assertFalse(view._row_registry_can_reconcile(["a", "a"], ["a", "b"]))
        view._cell_values = {(0, "name"): "custom"}
        self.assertFalse(view._row_registry_can_reconcile(["a", "b"], ["b", "a"]))


if __name__ == "__main__":
    unittest.main()
