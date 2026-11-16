"""Conflict policies, batched metadata and stale-copy safeguards; no SSH."""
import os
from pathlib import Path, PurePosixPath
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
from WinUx.controllers.transfer import TransferController
from WinUx.services.remote_filesystem import RemoteFilesystemMixin
from WinUx.services.transfer_conflicts import ConflictReview, TransferItemState, local_transfer_metadata


def file_state(modified=100, size=10, mode=stat.S_IFREG | 0o644):
    return TransferItemState(size, modified, mode)


class TransferConflicts(unittest.TestCase):
    def make_review(self):
        sources = tuple(Path(name) for name in ('newer', 'older', 'equal', 'near', 'folder', 'link', 'new'))
        left = {str(path): file_state() for path in sources}
        right = {str(path): file_state() for path in sources}
        left['newer'] = file_state(200)
        left['older'] = file_state(50)
        left['near'] = file_state(102)
        left['folder'] = file_state(200, mode=stat.S_IFDIR | 0o755)
        left['link'] = file_state(200, mode=stat.S_IFLNK | 0o777)
        right['new'] = None
        return ConflictReview(sources, left, right, PurePosixPath('/dest'), 'local', 'server', 1)

    def test_replace_skip_newer_and_nonconflicting_items(self):
        review = self.make_review()
        self.assertEqual(review.choose('replace').sources, review.sources)
        self.assertEqual([p.name for p in review.choose('skip').sources], ['new'])
        self.assertEqual([p.name for p in review.choose('newer').sources], ['newer', 'new'])
        self.assertEqual(len(review.rows()), 6)
        with self.assertRaises(ValueError):
            review.choose('rename')

    def test_size_change_does_not_mean_newer_and_target_links_are_skipped(self):
        review = self.make_review()
        review.source_states['equal'] = file_state(100, size=9999)
        review.target_states['newer'] = file_state(100, mode=stat.S_IFLNK | 0o777)
        review.source_states['older'] = file_state(float('nan'))
        review.source_states['equal'] = file_state(None)
        self.assertEqual([p.name for p in review.choose('newer').sources], ['new'])

    def test_missing_source_never_silently_succeeds(self):
        review = self.make_review()
        review.source_states['newer'] = None
        for policy in ('replace', 'skip', 'newer'):
            with self.assertRaises(FileNotFoundError):
                review.choose(policy)

    def test_revalidation_detects_new_destination_and_changed_source(self):
        review = self.make_review()
        left, right = dict(review.source_states), dict(review.target_states)
        review.validate(review.sources, left, right)
        right['new'] = file_state()
        with self.assertRaisesRegex(RuntimeError, 'changed after confirmation'):
            review.validate(review.sources, left, right)
        right = dict(review.target_states)
        left['newer'] = file_state(300)
        with self.assertRaises(RuntimeError):
            review.validate((Path('newer'),), left, right)
        # A skipped item changing must not block an unrelated chosen file.
        review.validate((Path('new'),), left, right)

    def test_local_snapshot_missing_and_nanosecond_stamp(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            path = Path(temporary) / 'source.inp'
            path.write_text('abc')
            states = local_transfer_metadata([path, path.with_name('missing')])
            self.assertEqual(states[str(path)].size, 3)
            self.assertTrue(states[str(path)].regular)
            self.assertIsNotNone(states[str(path)].stamp)
            self.assertIsNone(states[str(path.with_name('missing'))])

    def test_remote_snapshot_batches_parents_and_retains_link_type(self):
        attrs = SimpleNamespace(filename='a', st_mode=stat.S_IFLNK | 0o777, st_mtime=10, st_size=20)
        model = SimpleNamespace(_connection_lock=threading.RLock(), connected=True,
                                normalize=PurePosixPath, sftp=SimpleNamespace(listdir_attr=Mock(return_value=[attrs])))
        states = RemoteFilesystemMixin.transfer_metadata(model, [PurePosixPath('/one/a'),
            PurePosixPath('/one/missing'), PurePosixPath('/two/a')])
        self.assertEqual(model.sftp.listdir_attr.call_count, 2)
        self.assertEqual(states['/one/a'].kind, 'Link')
        self.assertIsNone(states['/one/missing'])

    def app(self, queued=False):
        remote = {'/dest/source.inp': file_state(100)}
        server = SimpleNamespace(normalize=PurePosixPath, host='host', username='user', _port=22,
            transfer_metadata=lambda paths: {str(path): remote.get(str(path)) for path in paths},
            upload=Mock(), download=Mock())
        view = SimpleNamespace(after=lambda delay, cb, *args: cb(*args), show_error=Mock(),
            confirm_action_checkbox_async=Mock(), confirm_transfer_conflicts_async=Mock(),
            show_transfer_progress=Mock(return_value=Mock()))
        pending = []
        app = SimpleNamespace(view=view, server=server, _closing=False, _connection_generation=1,
                              POST_MODAL_TRANSFER_DELAY_MS=1, _refresh_all=Mock())
        app._submit_background = lambda name, worker: worker()
        def submit(name, worker, **kwargs):
            if queued:
                pending.append(worker)
            else:
                worker()
            return SimpleNamespace(state='queued')
        app._submit_transfer = submit
        return app, remote, pending

    def test_quick_and_drop_use_review_choice_and_frozen_destination(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            source = Path(temporary) / 'source.inp'
            source.write_text('input')
            os.utime(source, (200, 200))
            for quick in (False, True):
                with self.subTest(quick=quick):
                    app, remote, pending = self.app()
                    controller = TransferController(app)
                    local = SimpleNamespace(panel_id='local', status=Mock())
                    server = SimpleNamespace(panel_id='server', status=Mock())
                    app.view.confirm_transfer_conflicts_async.side_effect = lambda review, cb, **_: cb(True, review.choose('newer'))
                    if quick:
                        controller.start_quick_transfer = Mock()
                        controller.quick_conflicts_ready(local, server, [source], '/dest', '.inp', 'Upload', ['source.inp'])
                        args = controller.start_quick_transfer.call_args.args
                        self.assertEqual(args[2], [source])
                        self.assertEqual(args[3], '/dest')
                        self.assertIsInstance(args[-1], ConflictReview)
                    else:
                        controller.start_drop_transfer = Mock()
                        controller.drop_conflicts_ready(local, server, [source], '/dest', True, ['source.inp'], Mock(), threading.Event())
                        args = controller.start_drop_transfer.call_args.args
                        self.assertEqual(args[2], [source])
                        self.assertIsInstance(args[-1], ConflictReview)
                    app.view.confirm_action_checkbox_async.assert_not_called()
                    app.view.show_error.assert_not_called()

    def test_changed_destination_or_connection_blocks_queued_upload(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            source = Path(temporary) / 'source.inp'
            source.write_text('input')
            for change in ('target', 'source', 'connection'):
                with self.subTest(change=change):
                    app, remote, pending = self.app(queued=True)
                    controller = TransferController(app)
                    left, right = controller._conflict_metadata('local', 'server', [source], '/dest')
                    review = ConflictReview((source,), left, right, '/dest', 'local', 'server', 1)
                    dialog = Mock()
                    controller.start_drop_transfer(SimpleNamespace(panel_id='local', status=Mock()),
                        SimpleNamespace(panel_id='server', status=Mock()), [source], '/dest', True,
                        dialog, threading.Event(), review)
                    if change == 'target':
                        remote['/dest/source.inp'] = file_state(500)
                    elif change == 'source':
                        source.write_text('changed input')
                    else:
                        app._connection_generation = 2
                    pending.pop()()
                    app.server.upload.assert_not_called()
                    self.assertTrue(dialog.fail.called)
                    app.view.show_error.assert_called_once()

    def test_connection_change_during_metadata_does_not_publish_dialog(self):
        app, _, _ = self.app()
        controller = TransferController(app)
        def snapshot(*args):
            app._connection_generation = 2
            return {}, {}
        controller._conflict_metadata = snapshot
        callback = Mock()
        controller._confirm_conflicts(['a'], callback, source_panel=SimpleNamespace(panel_id='local'),
            target_panel=SimpleNamespace(panel_id='server'), sources=[Path('a')], destination='/dest')
        callback.assert_called_once_with(False, False)
        app.view.confirm_transfer_conflicts_async.assert_not_called()

    def test_download_revalidates_local_destination_before_writing(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            destination = Path(temporary)
            target = destination / 'source.inp'
            source = PurePosixPath('/remote/source.inp')
            for changed in (False, True):
                with self.subTest(changed=changed):
                    target.write_text('old target')
                    app, remote, pending = self.app(queued=True)
                    remote[str(source)] = file_state(500)
                    controller = TransferController(app)
                    left, right = controller._conflict_metadata('server', 'local', [source], destination)
                    review = ConflictReview((source,), left, right, destination, 'server', 'local', 1)
                    dialog = Mock()
                    controller.start_drop_transfer(SimpleNamespace(panel_id='server', status=Mock()),
                        SimpleNamespace(panel_id='local', status=Mock()), [source], destination, True,
                        dialog, threading.Event(), review)
                    if changed:
                        target.write_text('another application changed the target')
                    pending.pop()()
                    if changed:
                        app.server.download.assert_not_called()
                        self.assertTrue(dialog.fail.called)
                    else:
                        app.server.download.assert_called_once()
                        dialog.complete.assert_called_once()

    def test_cancelled_metadata_review_never_opens_confirmation(self):
        app, _, _ = self.app()
        controller = TransferController(app)
        controller._conflict_metadata = Mock()
        event, callback = threading.Event(), Mock()
        event.set()
        controller._confirm_conflicts(['a'], callback, source_panel=SimpleNamespace(panel_id='local'),
            target_panel=SimpleNamespace(panel_id='server'), sources=[Path('a')], destination='/dest',
            cancel_event=event)
        callback.assert_called_once_with(False, False)
        controller._conflict_metadata.assert_not_called()
        app.view.confirm_transfer_conflicts_async.assert_not_called()

    def test_custom_choices_default_to_skip_and_keep_individual_renames(self):
        review = self.make_review()
        self.assertEqual([path.name for path in review.choose('custom').sources], ['new'])
        decision = review.choose('custom', {'newer': ('replace', None), 'older': ('rename', 'older-copy.inp')})
        self.assertEqual([path.name for path in decision.sources], ['newer', 'older', 'new'])
        self.assertEqual(decision.target_names, {'older': 'older-copy.inp'})
        left, right = dict(review.source_states), dict(review.target_states)
        right['older'] = None  # Validate the renamed target, not its old name.
        decision.validate(decision.sources, left, right)
        right['older'] = file_state()
        with self.assertRaises(RuntimeError):
            decision.validate(decision.sources, left, right)

    def test_rename_validation_rejects_paths_collisions_folders_and_links(self):
        review = self.make_review()
        for source, name in [('newer', '../outside'), ('newer', 'CON.txt'), ('newer', 'bad.'),
                             ('newer', 'older'), ('folder', 'folder-copy'), ('link', 'link-copy')]:
            with self.subTest(source=source, name=name), self.assertRaises(ValueError):
                review.choose('custom', {source: ('rename', name)})
        with self.assertRaises(ValueError):
            review.choose('custom', {'newer': ('rename', 'same'), 'older': ('rename', 'same')})
        # Local destinations use Windows-style case-insensitive collision checks.
        from dataclasses import replace
        local = replace(review, target_panel='local')
        with self.assertRaises(ValueError):
            local.choose('custom', {'newer': ('rename', 'copy'), 'older': ('rename', 'COPY')})

    def test_renamed_target_is_checked_when_queued_and_retry_cannot_lose_name(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            source = Path(temporary) / 'source.inp'
            source.write_text('input')
            for occupied in (False, True):
                with self.subTest(occupied=occupied):
                    app, remote, pending = self.app(queued=True)
                    controller = TransferController(app)
                    left, right = controller._conflict_metadata('local', 'server', [source], '/dest')
                    review = ConflictReview((source,), left, right, '/dest', 'local', 'server', 1)
                    decision = review.choose('custom', {str(source): ('rename', 'source-copy.inp')})
                    dialog = Mock()
                    controller.start_drop_transfer(SimpleNamespace(panel_id='local', status=Mock()),
                        SimpleNamespace(panel_id='server', status=Mock()), [source], '/dest', True,
                        dialog, threading.Event(), decision)
                    dialog.set_retry.assert_called_once_with(None)
                    if occupied:
                        remote['/dest/source-copy.inp'] = file_state()
                    pending.pop()()
                    if occupied:
                        app.server.upload.assert_not_called()
                        self.assertTrue(dialog.fail.called)
                    else:
                        self.assertEqual(app.server.upload.call_args.kwargs['target_names'],
                                         {str(source): 'source-copy.inp'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
