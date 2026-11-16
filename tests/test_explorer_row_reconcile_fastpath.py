"""Stable-topology Explorer refreshes should avoid structural remapping."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.components.explorer.row_registry import ExplorerRowRegistryMixin as Registry


class ExplorerRowReconcileFastPathTests(unittest.TestCase):
    def test_unchanged_topology_rebinds_in_place_without_replacing_registry(self):
        rows = [dict(index=i, content_changed=False) for i in range(8)]
        host = SimpleNamespace(_row_items=rows)
        host._bind_body_row = Mock(side_effect=lambda row, index, preserve_geometry=False: row.update(
            content_changed=(index == 5)))
        host._replace_row_registry = Mock()
        host._create_body_row = Mock()
        host._destroy_body_row = Mock()
        topology = tuple(f'item-{i}' for i in range(8))

        changed = Registry._reconcile_body_rows(host, topology, topology)

        self.assertEqual(changed, [5])
        self.assertEqual(host._bind_body_row.call_count, 8)
        for index, row in enumerate(rows):
            host._bind_body_row.assert_any_call(row, index, preserve_geometry=True)
        host._replace_row_registry.assert_not_called()
        host._create_body_row.assert_not_called()
        host._destroy_body_row.assert_not_called()


    def test_known_changed_indices_bind_only_target_rows(self):
        rows = [dict(index=i, content_changed=False) for i in range(30000)]
        host = SimpleNamespace(_row_items=rows)
        host._bind_body_row = Mock(side_effect=lambda row, index, preserve_geometry=False: row.update(
            content_changed=True))
        topology = tuple(f'item-{i}' for i in range(len(rows)))

        changed = Registry._reconcile_body_rows(
            host, topology, topology, changed_indices={17777})

        self.assertEqual(changed, [17777])
        host._bind_body_row.assert_called_once_with(
            rows[17777], 17777, preserve_geometry=True)

    def test_empty_known_change_set_skips_all_rebinds(self):
        rows = [dict(index=i, content_changed=False) for i in range(32)]
        host = SimpleNamespace(_row_items=rows, _bind_body_row=Mock())
        topology = tuple(f'item-{i}' for i in range(len(rows)))

        changed = Registry._reconcile_body_rows(
            host, topology, topology, changed_indices=set())

        self.assertEqual(changed, [])
        host._bind_body_row.assert_not_called()

    def test_structural_change_keeps_general_reconciliation(self):
        old = ('a', 'b', 'c')
        new = ('c', 'a', 'd')
        rows = [dict(index=i, content_changed=False) for i in range(3)]
        host = SimpleNamespace(
            _row_items=rows,
            _row_registry={i: row for i, row in enumerate(rows)},
            _row_render_window_cache=None,
            _visual_selected_cache=set(),
            _visual_current_cache=0,
        )
        host._bind_body_row = Mock(side_effect=lambda row, index, preserve_geometry=False: row.update(index=index))
        created = dict(index=2, content_changed=False)
        host._create_body_row = Mock(return_value=created)
        host._destroy_body_row = Mock()
        def replace(new_rows):
            host._row_items = list(new_rows)
            host._row_registry = {row['index']: row for row in new_rows}
        host._replace_row_registry = Mock(side_effect=replace)

        changed = Registry._reconcile_body_rows(host, old, new)

        self.assertEqual(changed, [0, 1, 2])
        host._create_body_row.assert_called_once_with(2)
        host._destroy_body_row.assert_called_once_with(rows[1])
        host._replace_row_registry.assert_called_once()
        self.assertEqual(host._row_render_window_cache, (0, 1, 2))
        self.assertIsNone(host._visual_selected_cache)
        self.assertIsNone(host._visual_current_cache)


if __name__ == '__main__':
    unittest.main(verbosity=2)
