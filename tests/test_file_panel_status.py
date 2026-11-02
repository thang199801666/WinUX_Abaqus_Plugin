"""Status counts without repeated scans or stale relative-mask caching."""
from dataclasses import replace
from pathlib import PurePosixPath
import unittest
from unittest.mock import patch
from benchmark_file_panel_status import FilePanel, FileItem, RefilterStatusPanel, status_panel


class FilePanelStatusTests(unittest.TestCase):
    def setUp(self):
        self.sources = [FileItem('job%d.inp' % row, PurePosixPath('/work/job%d.inp' % row),
                                 False, 2048, 1700000000, is_hidden=row == 0) for row in range(6)]
        self.sources[1] = replace(self.sources[1], name='.hidden.inp')

    def test_status_histories_match_reference_across_filters_and_visibility(self):
        for query in ('', '  ', 'job', '*.inp', '*.inp>1K', '*.odb', '|job2.inp'):
            for hidden in (False, True):
                panels = [status_panel(kind, self.sources, query, hidden) for kind in (FilePanel, RefilterStatusPanel)]
                for panel in panels:
                    panel._selection_changed()
                self.assertEqual(panels[0].status.values, panels[1].status.values, (query, hidden))
                self.assertEqual(panels[0].selected_status.values, panels[1].selected_status.values)

    def test_unfiltered_status_only_checks_hidden_flags_once_per_row(self):
        panel = status_panel(FilePanel, self.sources)
        with patch.object(panel, '_is_hidden_item', wraps=panel._is_hidden_item) as hidden:
            with patch.object(panel, '_filtered_items', side_effect=AssertionError('unnecessary filtering')):
                panel._selection_changed()
        self.assertEqual(hidden.call_count, len(self.sources))
        self.assertEqual(panel.status.values, ['Local | 4 items'])

    def test_active_mask_uses_one_visibility_snapshot(self):
        panel = status_panel(FilePanel, self.sources, '*.inp')
        with patch.object(panel, '_is_hidden_item', wraps=panel._is_hidden_item) as hidden:
            panel._selection_changed()
        self.assertEqual(hidden.call_count, len(self.sources))
        self.assertEqual(panel.status.values, ['Local | 4 of 4 items'])

    def test_show_hidden_unfiltered_status_does_not_iterate_rows(self):
        class NoIteration(list):
            def __iter__(self):
                raise AssertionError('unfiltered total iterated rows')
        panel = status_panel(FilePanel, self.sources, show_hidden=True)
        panel._source_items = NoIteration(panel._source_items)
        panel._selection_changed()
        self.assertEqual(panel.status.values, ['Local | 6 items'])

    def test_provided_filtered_rows_are_counted_without_matching_again(self):
        panel = status_panel(FilePanel, self.sources, '*.inp')
        with patch('WinUx.ui.components.file_panel.compile_file_filter', side_effect=AssertionError('refiltered')):
            panel._update_item_status(panel._source_items[:2])
        self.assertEqual(panel.status.values, ['Local | 2 of 4 items'])

    def test_relative_date_mask_is_reevaluated_on_each_query(self):
        panel = status_panel(FilePanel, self.sources, '*.inp>1H', show_hidden=True)
        with patch('WinUx.services.file_masks.time.time', return_value=1700003550):
            panel._selection_changed()
        with patch('WinUx.services.file_masks.time.time', return_value=1700003650):
            panel._selection_changed()
        self.assertEqual(panel.status.values, ['Local | 6 of 6 items', 'Local | 0 of 6 items'])

    def test_static_mask_does_not_read_clock(self):
        panel = status_panel(FilePanel, self.sources, '*.inp')
        with patch('WinUx.services.file_masks.time.time', side_effect=AssertionError('static mask clock')):
            panel._selection_changed()
        self.assertEqual(panel.status.values, ['Local | 4 of 4 items'])

    def test_hidden_metadata_and_setting_changes_are_not_cached(self):
        panel = status_panel(FilePanel, self.sources)
        panel._selection_changed()
        panel._source_items[2].data['is_hidden'] = True
        panel._selection_changed()
        panel._show_hidden_files = True
        panel._selection_changed()
        self.assertEqual(panel.status.values, ['Local | 4 items', 'Local | 3 items', 'Local | 6 items'])

    def test_empty_listing_prefix_and_selected_count_are_preserved(self):
        panel = status_panel(FilePanel, [], '*.inp')
        panel.status_prefix = ''
        panel.selected_transfer_paths = lambda: []
        panel._selection_changed()
        self.assertEqual(panel.status.values, ['0 of 0 items'])
        self.assertEqual(panel.selected_status.values, ['0 selected'])

    def test_disabled_status_returns_before_accessing_listing(self):
        panel = FilePanel.__new__(FilePanel)
        panel.has_status = False
        panel._update_item_status()
        panel._selection_changed()

    def test_status_updates_do_not_probe_filesystem_or_render(self):
        panel = status_panel(FilePanel, self.sources, '*.inp')
        with patch('os.stat', side_effect=AssertionError('status probed filesystem')):
            panel._selection_changed()
        panel._render_items.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
