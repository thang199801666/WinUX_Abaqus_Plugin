"""Remote account names: batching, NSS parsing, TTL and safe ID fallback."""
from pathlib import Path, PurePosixPath
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.services.remote_identity import RemoteIdentityNames
from WinUx.services.remote_filesystem import RemoteFilesystemMixin
from WinUx.ui.components.file_panel import FilePanel
from WinUx.ui.components.explorer_list_model import ListViewItem, file_detail_value
from WinUx.ui.components.explorer_item_model import ExplorerItemModel

OUTPUT = ('__WINUX_USERS__\nengineer:x:1004:1004:Engineer:/home/engineer:/bin/bash\n'
          '__WINUX_GROUPS__\nanalysis:x:1004:engineer\n')


class IdentityNames(unittest.TestCase):
    def test_batched_names_and_cache(self):
        resolver, lookup = RemoteIdentityNames(), Mock(return_value=OUTPUT)
        users, groups = resolver.resolve([1004] * 100, [1004] * 100, lookup)
        self.assertEqual(users, {1004: 'engineer'})
        self.assertEqual(groups, {1004: 'analysis'})
        self.assertIn('getent passwd 1004', lookup.call_args.args[0])
        self.assertIn('getent group 1004', lookup.call_args.args[0])
        resolver.resolve([1004], [1004], lookup)
        self.assertEqual(lookup.call_count, 1)

    def test_missing_and_failure_retry_after_ttl(self):
        resolver, lookup = RemoteIdentityNames(), Mock(side_effect=OSError('unavailable'))
        with patch('WinUx.services.remote_identity.time.monotonic', return_value=0):
            self.assertEqual(resolver.resolve([1004], [1004], lookup), ({1004: ''}, {1004: ''}))
        with patch('WinUx.services.remote_identity.time.monotonic', return_value=30):
            resolver.resolve([1004], [1004], lookup)
        self.assertEqual(lookup.call_count, 1)
        lookup.side_effect, lookup.return_value = None, OUTPUT
        with patch('WinUx.services.remote_identity.time.monotonic', return_value=61):
            self.assertEqual(resolver.resolve([1004], [1004], lookup)[0][1004], 'engineer')
        self.assertEqual(lookup.call_count, 2)

    def test_bound_and_untrusted_input(self):
        resolver, lookup = RemoteIdentityNames(), Mock(return_value='invalid output')
        resolver.resolve(range(2200), [], lookup)
        self.assertEqual(len(resolver._cache), 2048)
        self.assertEqual(lookup.call_count, 35)
        for call in lookup.call_args_list:
            args = call.args[0].split('getent passwd ')[1].split(' 2>')[0].split()
            self.assertLessEqual(len(args), 64)
        lookup.reset_mock()
        resolver.resolve(['1004; touch /tmp/not-allowed', -1, None], [], lookup)
        lookup.assert_not_called()

    def test_listing_conversion_sort_and_connection_scope(self):
        remote = RemoteFilesystemMixin()
        remote.client, remote.connected = object(), True
        remote._connection_lock, remote.normalize = threading.RLock(), PurePosixPath
        remote.sftp = Mock()
        remote.sftp.listdir_attr.return_value = [SimpleNamespace(
            filename='sample.inp', st_mode=0o100644, st_uid=1004, st_gid=1004,
            st_size=42, st_mtime=100, st_atime=200)]
        remote._lookup_identity_names = Mock(return_value=OUTPUT)
        source = remote.list_directory('/work')[0]
        row = FilePanel._convert(source)
        self.assertEqual(file_detail_value(row, 'owner'), 'engineer')
        self.assertEqual(file_detail_value(row, 'group'), 'analysis')
        self.assertEqual(row.data['uid'], 1004)
        remote.list_directory('/other')
        self.assertEqual(remote._lookup_identity_names.call_count, 1)
        remote.client = object()
        remote.list_directory('/other')
        self.assertEqual(remote._lookup_identity_names.call_count, 2)
        other = ListViewItem('a', data={'owner_name': 'zebra', 'uid': 2})
        unknown = ListViewItem('unknown', data={'uid': 1005})
        model = ExplorerItemModel()
        model.items = [other, row, unknown]
        model.sort('owner')
        self.assertEqual(model.items, [unknown, row, other])
        self.assertEqual(file_detail_value(unknown, 'owner'), '1005')


if __name__ == '__main__':
    unittest.main(verbosity=2)
