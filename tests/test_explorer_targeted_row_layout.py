"""Targeted Explorer row layout must scale with changed rows, not total rows."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.components.explorer_layout import ExplorerLayoutMixin as Layout

MODULE = 'WinUx.ui.components.explorer_layout'


class _Retained:
    configured = []

    def __init__(self, tag):
        self.tag = tag

    def exists(self):
        return True

    def configure(self, **kwargs):
        self.configured.append((self.tag, kwargs))


class ExplorerTargetedRowLayoutTests(unittest.TestCase):
    def setUp(self):
        _Retained.configured = []
        self.retained_patch = patch(MODULE + '.QRetainedItem', _Retained)
        self.retained_patch.start()
        self.addCleanup(self.retained_patch.stop)

    @staticmethod
    def _host(count=30000):
        items = [SimpleNamespace(name=f'item-{i}') for i in range(count)]
        rows = []
        registry = {}
        for i in range(count):
            row = {
                'index': i,
                'background': f'bg-{i}',
                'bottom': f'line-{i}',
                'texts': {'name': f'text-{i}'},
                'icon': None,
                'bounds': None,
                'pending_layout': False,
                'visual_text_color': (0, 0, 0, 255),
            }
            rows.append(row)
            registry[i] = row
        host = SimpleNamespace(
            body_canvas='canvas',
            items=items,
            _row_items=rows,
            _row_registry=registry,
            _fonts={'body': None},
            selected=set(),
            ROW_HEIGHT=22,
            ROW_SPACING=0,
            CELL_PADDING=6,
            _cell_styles={},
            _available_width=lambda: 900.0,
            _visible_columns=lambda: [dict(key='name', align='left', valign='middle')],
            _display_cell_value=Mock(side_effect=lambda item, key: item.name),
            _fit_text=Mock(side_effect=lambda text, width, font, size: text),
            _measure_text=Mock(return_value=(50.0, 15.0)),
            _update_selection_draws=Mock(),
            _update_hover_state=Mock(),
        )
        host._row_for_index = lambda index: host._row_registry.get(index)
        return host

    def test_one_changed_row_does_not_scan_all_materialized_rows(self):
        host = self._host()
        Layout._layout_materialized_rows(
            host,
            geometry={'name': (0.0, 500.0)},
            total_width=500.0,
            indices={17777},
        )
        self.assertEqual(host._display_cell_value.call_count, 1)
        self.assertEqual(host._fit_text.call_count, 1)
        self.assertEqual(host._measure_text.call_count, 1)
        touched = {tag for tag, _ in _Retained.configured}
        self.assertIn('bg-17777', touched)
        self.assertIn('line-17777', touched)
        self.assertIn('text-17777', touched)
        self.assertNotIn('bg-0', touched)
        host._update_selection_draws.assert_called_once_with(indices={17777})

    def test_target_indices_are_deduplicated_and_out_of_range_ignored(self):
        host = self._host(count=10)
        Layout._layout_materialized_rows(
            host,
            geometry={'name': (0.0, 500.0)},
            total_width=500.0,
            indices=[3, 3, -1, 99, None],
        )
        self.assertEqual(host._display_cell_value.call_count, 1)
        host._update_selection_draws.assert_called_once_with(indices={3})

    def test_full_layout_keeps_full_ordered_traversal(self):
        host = self._host(count=12)
        Layout._layout_materialized_rows(
            host,
            geometry={'name': (0.0, 500.0)},
            total_width=500.0,
        )
        self.assertEqual(host._display_cell_value.call_count, 12)
        host._update_selection_draws.assert_called_once_with(indices=set())


if __name__ == '__main__':
    unittest.main(verbosity=2)
