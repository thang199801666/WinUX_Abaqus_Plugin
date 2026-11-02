"""Optional file metadata, safe collection, sorting and refresh detection."""
from pathlib import Path, PurePosixPath
import os
import stat
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.models.items import FileItem
from WinUx.models.filesystem import FileSystemModel
from WinUx.services.remote_filesystem import RemoteFilesystemMixin
from WinUx.ui.components.file_panel import FilePanel
from WinUx.ui.components.explorer_list_model import (
    DEFAULT_COLUMNS, EXTRA_FILE_COLUMNS, ListViewItem, file_detail_value)
from WinUx.ui.components.explorer_item_model import ExplorerItemModel
from WinUx.ui.components.explorer_data_view import ExplorerDataViewMixin


class FileDetailColumns(unittest.TestCase):
    def test_default_visibility(self):
        self.assertEqual([c['key'] for c in DEFAULT_COLUMNS if c['visible']],
                         ['name', 'date', 'type', 'size'])
        self.assertEqual(len({c['key'] for c in DEFAULT_COLUMNS}), len(DEFAULT_COLUMNS))
        self.assertTrue(all(not c['visible'] for c in DEFAULT_COLUMNS[4:]))

    def test_remote_metadata_uses_one_existing_listing(self):
        remote = RemoteFilesystemMixin()
        remote.connected = True
        remote._connection_lock = threading.RLock()
        remote.normalize = PurePosixPath
        remote.sftp = Mock()
        remote.sftp.listdir_attr.return_value = [SimpleNamespace(
            filename='a.inp', st_mode=stat.S_IFREG | 0o4750, st_uid=0, st_gid=123,
            st_size=42, st_mtime=100, st_atime=200)]
        source = remote.list_directory('/work')[0]
        self.assertEqual(remote.sftp.mock_calls, [unittest.mock.call.listdir_attr('/work')])
        row = FilePanel._convert(source)
        self.assertEqual(file_detail_value(row, 'permissions'), '-rwsr-x--- (4750)')
        self.assertEqual(file_detail_value(row, 'owner'), '0')
        self.assertEqual(file_detail_value(row, 'group'), '123')
        self.assertEqual(file_detail_value(row, 'extension'), '.inp')
        self.assertEqual(file_detail_value(row, 'path'), '/work/a.inp')
        self.assertEqual(file_detail_value(row, 'created'), '')
        self.assertTrue(file_detail_value(row, 'accessed'))
        view = ExplorerDataViewMixin()
        view._cell_values = {}
        self.assertEqual(view._cell_text(row, 'accessed'), file_detail_value(row, 'accessed'))

    def test_local_metadata_and_windows_acl_not_fabricated(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as directory:
            path = Path(directory) / 'sample.txt'
            path.write_text('test')
            source = FileSystemModel().list_directory(Path(directory))[0]
            row = FilePanel._convert(source)
            self.assertTrue(file_detail_value(row, 'accessed'))
            self.assertEqual(file_detail_value(row, 'path'), str(path))
            if os.name == 'nt':
                self.assertEqual(file_detail_value(row, 'permissions'), '')
                self.assertEqual(file_detail_value(row, 'owner'), '')
                self.assertTrue(file_detail_value(row, 'created'))
                self.assertIsNotNone(source.attributes)
            direct = ListViewItem.from_path(str(path))
            self.assertEqual(file_detail_value(direct, 'created'), file_detail_value(row, 'created'))

    def test_attributes_unknown_parent_and_cache_invalidation(self):
        row = ListViewItem('file', data={'attributes': 3})
        self.assertEqual(file_detail_value(row, 'attributes'), 'Read-only, Hidden')
        row.data['attributes'] = 2
        row.refresh_display_cache()
        self.assertEqual(file_detail_value(row, 'attributes'), 'Hidden')
        for item in (ListViewItem('..', is_dir=True, data={'parent': True}), ListViewItem('missing')):
            for key in ('permissions', 'owner', 'group', 'created', 'accessed', 'attributes'):
                self.assertEqual(file_detail_value(item, key), '')
        self.assertEqual(file_detail_value(ListViewItem('dir.ext', is_dir=True), 'extension'), '')

    def test_numeric_sort_and_metadata_only_changes(self):
        model = ExplorerItemModel()
        a = ListViewItem('a', data={'uid': 100, 'mode': stat.S_IFREG | 0o644})
        b = ListViewItem('z', data={'uid': 2, 'mode': stat.S_IFREG | 0o600})
        parent = ListViewItem('..', is_dir=True, data={'parent': True})
        model.items = [a, parent, b]
        model.sort('owner')
        self.assertEqual(model.items, [parent, b, a])
        for key, _, _ in EXTRA_FILE_COLUMNS:
            model.sort(key)
            model.sort(key, False)
            self.assertIs(model.items[0], parent)
        old = FileItem('a', PurePosixPath('/a'), False, 1, 100, mode=0o100644)
        new = FileItem('a', PurePosixPath('/a'), False, 1, 100, mode=0o100600)
        self.assertNotEqual(FilePanel._item_signature(FilePanel._convert(old)), FilePanel._item_signature(new))


if __name__ == '__main__':
    unittest.main(verbosity=2)
