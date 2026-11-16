"""Visible review-only Sync Preview rows and conservative transfer routing."""
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import stat
import json
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.sync_preview import SyncPreviewController
from WinUx.dialogs.sync_preview_form import SyncPreviewDialog
from WinUx.models.items import FileItem


class SyncPreviewReviewTests(unittest.TestCase):
    def item(self, name='sample.inp', **changes):
        return replace(FileItem(name, PurePosixPath('/data') / name, False, 42, 100,
                                mode=stat.S_IFREG | 0o644), **changes)

    def rows(self, local, remote):
        return SyncPreviewController.build_rows(local, remote, Path('/local'), PurePosixPath('/remote'))

    def assert_review(self, row, status):
        self.assertEqual(row['status'], status)
        self.assertEqual(row['action'], 'Review')
        self.assertIs(row['transfer_allowed'], False)
        self.assertFalse(SyncPreviewDialog._can_transfer(row))

    def controller(self):
        dialog = SimpleNamespace(winfo_exists=lambda: True, set_status=Mock())
        app = SimpleNamespace(
            _ensure_server_online=Mock(return_value=True), _process_queued_drop=Mock(),
            server=SimpleNamespace(normalize=PurePosixPath),
            view=SimpleNamespace(sync_preview_dialog=dialog, show_message=Mock(),
                                 left=SimpleNamespace(current_path=Path('/local')),
                                 right=SimpleNamespace(current_path=PurePosixPath('/remote'))))
        return SyncPreviewController(app), app, dialog

    def test_file_folder_conflicts_are_visible_in_both_directions(self):
        file, folder = self.item(), self.item(is_dir=True, mode=stat.S_IFDIR | 0o755)
        for local, remote in ((file, folder), (folder, file)):
            rows = self.rows([local], [remote])
            self.assertEqual(len(rows), 1)
            self.assert_review(rows[0], 'File/folder conflict')

    def test_directories_are_not_silently_omitted_or_automatically_copied(self):
        folder = self.item('folder', is_dir=True, mode=stat.S_IFDIR | 0o755)
        for left, right in (([folder], []), ([], [folder]), ([folder], [folder])):
            row = self.rows(left, right)[0]
            self.assert_review(row, 'Directory not compared')
            side = 'local' if left else 'server'
            self.assertEqual(SyncPreviewDialog._side_text(row, side), 'Folder')

    def test_links_and_reparse_points_are_review_only(self):
        cases = (self.item(is_symlink=True), self.item(mode=stat.S_IFLNK | 0o777),
                 self.item(attributes=0x400), self.item(is_dir=True, is_symlink=True))
        for item in cases:
            row = self.rows([item], [self.item()])[0]
            self.assert_review(row, 'Link/special entry not compared')
            self.assertEqual(SyncPreviewDialog._side_text(row, 'local'), 'Link')

    def test_special_entries_are_not_treated_as_regular_files(self):
        row = self.rows([self.item(mode=stat.S_IFIFO | 0o600)], [])[0]
        self.assert_review(row, 'Link/special entry not compared')
        self.assertEqual(SyncPreviewDialog._side_text(row, 'local'), 'Special')

    def test_missing_invalid_or_nonfinite_metadata_requires_review(self):
        for changes in ({'size': None}, {'size': -1}, {'size': 'bad'}, {'modified': None},
                        {'modified': float('nan')}, {'modified': float('inf')}):
            row = self.rows([self.item(**changes)], [self.item()])[0]
            self.assert_review(row, 'Incomplete metadata')
            self.assertEqual(SyncPreviewDialog._side_text(row, 'local'), 'Unknown')

    def test_complete_regular_file_recommendations_and_tolerance_are_unchanged(self):
        file = self.item()
        self.assertEqual(self.rows([file], [replace(file, modified=102)]), [])
        for left, right, expected in (([file], [], 'Upload'), ([], [file], 'Download'),
                                      ([replace(file, modified=103)], [file], 'Upload'),
                                      ([file], [replace(file, modified=103)], 'Download')):
            row = self.rows(left, right)[0]
            self.assertEqual(row['action'], expected)
            self.assertTrue(SyncPreviewDialog._can_transfer(row))
        row = self.rows([file], [replace(file, size=43)])[0]
        self.assertEqual(row['action'], 'Review')
        self.assertFalse(row['transfer_allowed'])

    def test_epoch_zero_is_valid_metadata_not_missing(self):
        file = self.item(size=0, modified=0)
        self.assertEqual(self.rows([file], [file]), [])
        self.assertEqual(self.rows([file], [])[0]['action'], 'Upload')

    def test_remote_case_sensitive_names_remain_distinct_and_sorted(self):
        rows = self.rows([self.item('A.inp')], [self.item('a.inp')])
        self.assertEqual({(row['name'], row['action']) for row in rows}, {('A.inp', 'Upload'), ('a.inp', 'Download')})

    def test_review_flag_blocks_even_if_action_is_accidentally_changed(self):
        controller, app, dialog = self.controller()
        row = self.rows([self.item(is_symlink=True)], [])[0]
        row['action'] = 'Upload'
        controller.transfer_rows([row])
        app._ensure_server_online.assert_not_called()
        app._process_queued_drop.assert_not_called()
        self.assertIn('require review', dialog.set_status.call_args.args[0])

    def test_mixed_selection_routes_only_explicitly_transferable_rows(self):
        controller, app, _ = self.controller()
        rows = self.rows([self.item('good.inp'), self.item('folder', is_dir=True)], [])
        controller.transfer_rows(rows)
        app._process_queued_drop.assert_called_once_with(app.view.left, app.view.right,
                                                       PurePosixPath('/remote'), True, [Path('/local/good.inp')])

    def test_pending_scan_blocks_transfer_without_connecting(self):
        controller, app, _ = self.controller()
        controller._scan_pending = True
        controller.transfer_rows(self.rows([self.item()], []))
        app._ensure_server_online.assert_not_called()
        app._process_queued_drop.assert_not_called()

    def test_mixed_directions_remain_blocked(self):
        controller, app, _ = self.controller()
        controller.transfer_rows(self.rows([self.item('local.inp')], [self.item('remote.inp')]))
        app._process_queued_drop.assert_not_called()
        app.view.show_message.assert_called_once()

    def test_dialog_fallback_excludes_review_rows(self):
        dialog = SyncPreviewDialog.__new__(SyncPreviewDialog)
        dialog._scan_pending = False
        dialog._rows = self.rows([self.item('good.inp'), self.item('link', is_symlink=True)], [])
        dialog.table = SimpleNamespace(selected=set())
        dialog.request_transfer = Mock()
        dialog._transfer_selected()
        self.assertEqual([row['name'] for row in dialog.request_transfer.call_args.args[0]], ['good.inp'])

    def test_review_flags_survive_native_host_json_transport(self):
        rows = self.rows([self.item('link', is_symlink=True), self.item('unknown', modified=float('nan'))], [])
        transported = json.loads(json.dumps(rows, allow_nan=False))
        self.assertEqual(rows, transported)
        self.assertTrue(all(not SyncPreviewDialog._can_transfer(row) for row in transported))

    def test_stale_scan_results_remain_unpublishable(self):
        controller, app, dialog = self.controller()
        app._closing = False
        app._connection_generation = 3
        controller._connection_generation = 3
        controller._generation = 2
        app._sync_preview_ready = Mock()
        controller._scan_ready(1, [], Path('/local'), PurePosixPath('/remote'))
        app._sync_preview_ready.assert_not_called()
        app._connection_generation = 4
        controller._scan_ready(2, [], Path('/local'), PurePosixPath('/remote'))
        app._sync_preview_ready.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
