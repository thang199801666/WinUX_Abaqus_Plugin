"""FilePanel refresh reuses rows/caches without losing incoming metadata."""
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.models.items import FileItem
from WinUx.ui.components.file_panel import FilePanel
from WinUx.ui.components.explorer_list_model import ListViewItem, EXTRA_FILE_COLUMNS, file_detail_value


class TemporaryRowPanel(FilePanel):
    """Reference: preceding temporary-row conversion and unconditional caching."""
    @staticmethod
    def _convert(item, existing=None):
        incoming = FilePanel._convert(item)
        if existing is None:
            return incoming
        for key in ('name', 'path', 'is_dir', 'size', 'mtime', 'item_type', 'extension'):
            setattr(existing, key, getattr(incoming, key))
        existing.data.update(incoming.data)
        existing.refresh_display_cache()
        return existing


def make_panel(kind, sources):
    panel = kind.__new__(kind)
    panel.current_path = PurePosixPath('/work')
    panel._source_items = [FilePanel._convert(source) for source in sources]
    panel._show_hidden_files = True
    panel._filter_query = ''
    panel.has_status = False
    panel._render_items = Mock()
    panel._consume_pending_created_rename = Mock()
    return panel


def fingerprint(row):
    return (row.name, row.path, row.is_dir, row.size, row.mtime, row.item_type, row.extension,
            row.cached_date_text, row.cached_size_text, row.cached_name_sort, row.cached_type_sort,
            dict(row.data), tuple(file_detail_value(row, key) for key, _, _ in EXTRA_FILE_COLUMNS))


class FilePanelRefreshTests(unittest.TestCase):
    def setUp(self):
        self.sources = [FileItem('file%d.inp' % row, PurePosixPath('/work/file%d.inp' % row),
                                 False, 1024 + row, 1700000000, uid=row, mode=0o100644)
                        for row in range(8)]

    def test_one_changed_file_only_formats_one_existing_row(self):
        panel = make_panel(FilePanel, self.sources)
        before = list(panel._source_items)
        incoming = [replace(source) for source in self.sources]
        incoming[-1] = replace(incoming[-1], size=4096)
        original = ListViewItem.refresh_display_cache
        with patch.object(ListViewItem, 'refresh_display_cache', autospec=True, side_effect=original) as refresh:
            with patch('WinUx.ui.components.file_panel.ListViewItem', wraps=ListViewItem) as create:
                panel.refresh_directory(panel.current_path, incoming)
        self.assertEqual(create.call_count, 0)
        self.assertEqual(refresh.call_count, 1)
        self.assertTrue(all(a is b for a, b in zip(before, panel._source_items)))
        self.assertTrue(all(row.data['source'] is source for row, source in zip(panel._source_items, incoming)))

    def test_unchanged_row_retains_detail_cache_and_custom_data(self):
        panel = make_panel(FilePanel, self.sources)
        row = panel._source_items[0]
        row.data['application_marker'] = object()
        file_detail_value(row, 'permissions')
        cache = row._detail_text
        incoming = [replace(source) for source in self.sources]
        incoming[-1] = replace(incoming[-1], modified=1700000010)
        panel.refresh_directory(panel.current_path, incoming)
        self.assertIs(row._detail_text, cache)
        self.assertIn('application_marker', row.data)
        self.assertIs(row.data['source'], incoming[0])

    def test_metadata_only_changes_invalidate_detail_cache(self):
        for field, value in (('mode', 0o100755), ('owner_name', 'new-owner'), ('accessed', 1700000020),
                             ('attributes', 2), ('is_symlink', True), ('is_hidden', True)):
            panel = make_panel(FilePanel, self.sources)
            row = panel._source_items[0]
            file_detail_value(row, 'permissions')
            incoming = [replace(source) for source in self.sources]
            incoming[0] = replace(incoming[0], **{field: value})
            panel.refresh_directory(panel.current_path, incoming)
            self.assertIsNone(row._detail_text, field)
            self.assertEqual(fingerprint(row), fingerprint(FilePanel._convert(incoming[0])))

    def test_conversion_matches_fresh_row_for_all_display_fields(self):
        existing = FilePanel._convert(self.sources[0])
        for source in (replace(self.sources[0], name='Renamed.odb', path=PurePosixPath('/work/Renamed.odb')),
                       replace(self.sources[0], is_dir=True),
                       replace(self.sources[0], size=0, modified=0),
                       SimpleNamespace(name='custom.xyz', path=PurePosixPath('/work/custom.xyz'),
                                       is_dir=False, size=None, modified=None, type_text='Custom Type')):
            actual = FilePanel._convert(source, existing=existing)
            self.assertIs(actual, existing)
            self.assertEqual(fingerprint(actual), fingerprint(FilePanel._convert(source)))

    def test_mixed_add_remove_reorder_matches_temporary_row_reference(self):
        panels = [make_panel(kind, self.sources) for kind in (FilePanel, TemporaryRowPanel)]
        incoming = [replace(self.sources[5], gid=42), self.sources[1],
                    FileItem('new.txt', PurePosixPath('/work/new.txt'), False, 0, 0)]
        for panel in panels:
            panel.refresh_directory(panel.current_path, incoming)
        self.assertEqual([fingerprint(row) for row in panels[0]._source_items],
                         [fingerprint(row) for row in panels[1]._source_items])
        self.assertEqual(panels[0]._render_items.call_args.kwargs, {'incremental': True})

    def test_identical_snapshot_keeps_existing_noop_behavior(self):
        panel = make_panel(FilePanel, self.sources)
        rows = panel._source_items
        panel.refresh_directory(panel.current_path, [replace(source) for source in reversed(self.sources)])
        self.assertIs(panel._source_items, rows)
        panel._render_items.assert_not_called()
        self.assertIs(rows[0].data['source'], self.sources[0])

    def test_stale_directory_does_not_convert_or_mutate_rows(self):
        panel = make_panel(FilePanel, self.sources)
        with patch.object(panel, '_convert', side_effect=AssertionError('stale refresh converted rows')):
            panel.refresh_directory(PurePosixPath('/other'), self.sources)
        panel._render_items.assert_not_called()

    def test_remote_case_sensitive_paths_remain_distinct(self):
        sources = [replace(self.sources[0], path=PurePosixPath('/work/A.inp')),
                   replace(self.sources[1], path=PurePosixPath('/work/a.inp'))]
        panel = make_panel(FilePanel, sources)
        a, b = panel._source_items
        panel.refresh_directory(panel.current_path, [replace(sources[1], size=999), sources[0]])
        self.assertIs(panel._source_items[0], b)
        self.assertIs(panel._source_items[1], a)

    def test_refresh_uses_loaded_metadata_without_filesystem_calls(self):
        panel = make_panel(FilePanel, self.sources)
        incoming = [replace(source, size=source.size + 1) for source in self.sources]
        with patch('os.stat', side_effect=AssertionError('refresh probed filesystem')):
            panel.refresh_directory(panel.current_path, incoming)
        self.assertEqual([row.size for row in panel._source_items], [source.size for source in incoming])


if __name__ == '__main__':
    unittest.main(verbosity=2)
