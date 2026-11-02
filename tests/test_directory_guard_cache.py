"""Ancestor chains are cached, but every metadata check remains fresh."""
from dataclasses import replace
from pathlib import Path, PurePosixPath
import stat
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from WinUx.services.transfer_conflicts import TransferItemState
from WinUx.services.transfer_tree_copy import DirectoryChecks


class DirectoryGuardCache(unittest.TestCase):
    def checks(self):
        expected = {path: TransferItemState(0, 0, stat.S_IFDIR | 0o755, identity=(1, index))
                    for index, path in enumerate(('/', '/tree', '/tree/deep'))}
        current = dict(expected)
        state = Mock(side_effect=lambda path, local: current[path])
        cancelled = Mock()
        return DirectoryChecks(expected, local=True, state=state, cancelled=cancelled), current, state, cancelled

    def test_shared_parent_reuses_one_chain_but_repeats_all_stat_calls(self):
        checks, current, state, cancelled = self.checks()
        for index in range(20):
            checks.check(PurePosixPath('/tree/deep/file{}.inp'.format(index)))
        self.assertEqual(len(checks._chains), 1)
        self.assertEqual(state.call_count, 60)
        self.assertEqual(cancelled.call_count, 60)

    def test_link_and_identity_changes_are_detected_with_warm_cache(self):
        for link in (False, True):
            with self.subTest(link=link):
                checks, current, state, cancelled = self.checks()
                path = PurePosixPath('/tree/deep/a')
                checks.check(path)
                current['/tree/deep'] = replace(current['/tree/deep'],
                    mode=stat.S_IFLNK | 0o777 if link else stat.S_IFDIR | 0o755,
                    identity=(2, 99))
                with self.assertRaisesRegex(RuntimeError, 'ancestor changed'):
                    checks.check(path)
                self.assertGreater(state.call_count, 3)

    def test_registration_invalidates_chains_and_guards_new_folder(self):
        checks, current, state, cancelled = self.checks()
        path = PurePosixPath('/tree/new/a')
        checks.check(path)
        current['/tree/new'] = TransferItemState(0, 0, stat.S_IFDIR | 0o755, identity=(1, 9))
        checks.register(PurePosixPath('/tree/new'), current['/tree/new'])
        self.assertFalse(checks._chains)
        checks.check(path)
        self.assertIn(('/tree/new', True), [call.args for call in state.call_args_list])

    def test_reparse_point_is_not_trusted_even_with_same_directory_mode_and_identity(self):
        checks, current, state, cancelled = self.checks()
        path = PurePosixPath('/tree/deep/a')
        checks.check(path)
        current['/tree/deep'] = replace(current['/tree/deep'], reparse=True)
        with self.assertRaises(RuntimeError):
            checks.check(path)

    def test_cache_is_bounded_and_cancel_still_precedes_io(self):
        checks, current, state, cancelled = self.checks()
        for index in range(300):
            checks.check(PurePosixPath('/tree/dir{}/a'.format(index)))
        self.assertLessEqual(len(checks._chains), checks.MAX_CHAINS)
        path = PurePosixPath('/tree/dir299/a')
        previous = state.call_count
        cancelled.side_effect = RuntimeError('cancelled')
        with self.assertRaises(RuntimeError):
            checks.check(path)
        self.assertEqual(state.call_count, previous)


if __name__ == '__main__':
    unittest.main(verbosity=2)
