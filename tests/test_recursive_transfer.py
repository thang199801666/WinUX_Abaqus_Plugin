"""Bounded recursive review + actual local byte copies via a filesystem-backed fake SFTP."""
from contextlib import contextmanager
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
from WinUx.services.remote_transfer import RemoteTransferMixin
from WinUx.services.remote_filesystem import RemoteFilesystemMixin
from WinUx.services.transfer_conflicts import ConflictReview, local_transfer_metadata
from WinUx.services.transfer_tree import TreeReader, TreeReview, ScanLimits, scan_tree
from WinUx.controllers.transfer import TransferController


class DiskSFTP:
    def __init__(self, root):
        self.root = Path(root)
        self.modes = {}
        self.on_put = self.on_get = None
        self.closed_lists = 0
    def path(self, path):
        path = PurePosixPath(path)
        if '..' in path.parts:
            raise AssertionError('Path traversal')
        return self.root.joinpath(*path.parts[1:])
    def lstat(self, path):
        info = self.path(path).lstat()
        return SimpleNamespace(st_size=info.st_size, st_mtime=int(info.st_mtime),
                               st_mode=self.modes.get(str(path), info.st_mode))
    stat = lstat
    def listdir_iter(self, folder, read_aheads=1):
        try:
            for path in sorted(self.path(folder).iterdir()):
                info = self.lstat(str(PurePosixPath(folder) / path.name))
                info.filename = path.name
                yield info
        finally:
            self.closed_lists += 1
    def listdir_attr(self, folder):
        return list(self.listdir_iter(folder))
    def mkdir(self, path):
        self.path(path).mkdir()
    def utime(self, path, times):
        os.utime(self.path(path), times)
    def put(self, source, target, callback, confirm=False):
        data = Path(source).read_bytes()
        self.path(target).write_bytes(data)
        callback(len(data), len(data))
        if self.on_put:
            self.on_put()
    def get(self, source, target, callback, **kwargs):
        data = self.path(source).read_bytes()
        Path(target).write_bytes(data)
        callback(len(data), len(data))
        if self.on_get:
            self.on_get()
    def posix_rename(self, source, target):
        os.replace(self.path(source), self.path(target))
    def rename(self, source, target):
        os.link(self.path(source), self.path(target))
        self.path(source).unlink()
    def remove(self, path):
        self.path(path).unlink()


class Model(RemoteTransferMixin, RemoteFilesystemMixin):
    def __init__(self, root):
        self.sftp = DiskSFTP(root)
        self.connected = True
        self._connection_lock = threading.RLock()
        self.host, self.username, self._port = 'test', 'test', 22
        self.open_sessions = self.closed_sessions = 0
    normalize = staticmethod(PurePosixPath)
    @contextmanager
    def _auxiliary_session(self):
        self.open_sessions += 1
        try:
            yield None, self.sftp
        finally:
            self.open_sessions -= 1
            self.closed_sessions += 1


def make_review(model, sources, destination, upload=True):
    source_side, target_side = ('local', 'server') if upload else ('server', 'local')
    left = (local_transfer_metadata(sources) if upload else model.transfer_metadata(sources))
    targets = [model.normalize(destination) / path.name if upload else Path(destination) / path.name for path in sources]
    right = model.transfer_metadata(targets) if upload else local_transfer_metadata(targets)
    return ConflictReview(tuple(sources), left, {str(s): right[str(t)] for s, t in zip(sources, targets)},
                          destination, source_side, target_side, 1)


class RecursiveTransfer(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.local = self.root / 'local'
        self.remote = self.root / 'remote'
        self.local.mkdir()
        self.remote.mkdir()
        (self.remote / 'dest').mkdir()
        self.model = Model(self.remote)

    def fixture(self):
        project = self.local / 'project'
        (project / 'one').mkdir(parents=True)
        (project / 'two').mkdir()
        (project / 'empty').mkdir()
        (project / 'one' / 'result.odb').write_bytes(b'ONE NEW')
        (project / 'two' / 'result.odb').write_bytes(b'TWO NEW')
        (project / 'new.inp').write_bytes(b'INPUT')
        target = self.remote / 'dest' / 'project'
        (target / 'one').mkdir(parents=True)
        (target / 'two').mkdir()
        (target / 'one' / 'result.odb').write_bytes(b'ONE OLD')
        (target / 'two' / 'result.odb').write_bytes(b'TWO OLD')
        (target / 'untouched.txt').write_bytes(b'KEEP')
        return project, target

    def scan(self, original, **kwargs):
        return scan_tree(original, TreeReader(original.source_panel, self.model),
                         TreeReader(original.target_panel, self.model), **kwargs)

    def test_scan_is_read_only_and_retains_structure_duplicate_names_and_empty_folders(self):
        project, target = self.fixture()
        before = {str(path.relative_to(self.remote)): path.read_bytes() for path in self.remote.rglob('*') if path.is_file()}
        review = self.scan(make_review(self.model, [project], '/dest'))
        self.assertIsInstance(review, TreeReview)
        self.assertEqual({review.display_name(path) for path in review.sources}, {
            'project/one/result.odb', 'project/two/result.odb', 'project/new.inp', 'project/empty/'})
        self.assertEqual(len(review.rows()), 2)
        self.assertFalse((target / 'empty').exists())
        self.assertEqual(before, {str(path.relative_to(self.remote)): path.read_bytes()
                                 for path in self.remote.rglob('*') if path.is_file()})

    def test_upload_selected_children_rename_and_preserve_unselected_files(self):
        project, target = self.fixture()
        review = self.scan(make_review(self.model, [project], '/dest'))
        one, two = project / 'one' / 'result.odb', project / 'two' / 'result.odb'
        decision = review.choose('custom', {str(one): ('replace', None), str(two): ('rename', 'copy.odb')})
        events = []
        self.model.upload(decision.sources, '/dest', tree_decision=decision, progress=lambda *args: events.append(args))
        self.assertEqual((target / 'one' / 'result.odb').read_bytes(), b'ONE NEW')
        self.assertEqual((target / 'two' / 'result.odb').read_bytes(), b'TWO OLD')
        self.assertEqual((target / 'two' / 'copy.odb').read_bytes(), b'TWO NEW')
        self.assertEqual((target / 'new.inp').read_bytes(), b'INPUT')
        self.assertEqual((target / 'untouched.txt').read_bytes(), b'KEEP')
        self.assertTrue((target / 'empty').is_dir())
        self.assertEqual({e[0] for e in events}, {review.display_name(path) for path in decision.sources})
        self.assertEqual(events[-1][3:], (19, 19))

    def test_skip_existing_merges_new_children_without_touching_conflicting_ones(self):
        project, target = self.fixture()
        review = self.scan(make_review(self.model, [project], '/dest'))
        decision = review.choose('skip')
        self.model.upload(decision.sources, '/dest', tree_decision=decision)
        self.assertEqual((target / 'one' / 'result.odb').read_bytes(), b'ONE OLD')
        self.assertEqual((target / 'two' / 'result.odb').read_bytes(), b'TWO OLD')
        self.assertEqual((target / 'new.inp').read_bytes(), b'INPUT')

    def test_newer_only_compares_each_child_not_the_folder_timestamp(self):
        project, target = self.fixture()
        os.utime(project / 'one' / 'result.odb', (200, 200))
        os.utime(project / 'two' / 'result.odb', (50, 50))
        os.utime(target / 'one' / 'result.odb', (100, 100))
        os.utime(target / 'two' / 'result.odb', (100, 100))
        review = self.scan(make_review(self.model, [project], '/dest'))
        decision = review.choose('newer')
        self.assertIn(project / 'one' / 'result.odb', decision.sources)
        self.assertNotIn(project / 'two' / 'result.odb', decision.sources)
        self.model.upload(decision.sources, '/dest', tree_decision=decision)
        self.assertEqual((target / 'one' / 'result.odb').read_bytes(), b'ONE NEW')
        self.assertEqual((target / 'two' / 'result.odb').read_bytes(), b'TWO OLD')

    def test_download_tree_uses_relative_paths_and_preserves_unrelated_files(self):
        project, target = self.fixture()
        destination = self.root / 'download'
        destination.mkdir()
        ((destination / 'project')).mkdir()
        (destination / 'project' / 'keep.txt').write_bytes(b'KEEP')
        original = make_review(self.model, [PurePosixPath('/dest/project')], destination, upload=False)
        review = self.scan(original)
        decision = review.choose('replace')
        self.model.download(decision.sources, destination, tree_decision=decision)
        self.assertEqual((destination / 'project' / 'one' / 'result.odb').read_bytes(), b'ONE OLD')
        self.assertEqual((destination / 'project' / 'two' / 'result.odb').read_bytes(), b'TWO OLD')
        self.assertEqual((destination / 'project' / 'keep.txt').read_bytes(), b'KEEP')
        self.assertFalse([path for path in destination.rglob('*') if 'winux-part' in path.name])

    def test_new_file_appearing_during_copy_is_not_overwritten(self):
        project, target = self.fixture()
        review = self.scan(make_review(self.model, [project], '/dest'))
        decision = review.choose('skip')
        self.model.sftp.on_put = lambda: (target / 'new.inp').write_bytes(b'OTHER WRITER')
        with self.assertRaisesRegex(RuntimeError, 'Destination changed'):
            self.model.upload(decision.sources, '/dest', tree_decision=decision)
        self.assertEqual((target / 'new.inp').read_bytes(), b'OTHER WRITER')

    def test_limits_cancel_and_unsupported_nodes_fail_before_any_write(self):
        project, target = self.fixture()
        original = make_review(self.model, [project], '/dest')
        for limits in (ScanLimits(entries=2), ScanLimits(depth=1), ScanLimits(seconds=1e-12)):
            with self.subTest(limits=limits), self.assertRaises((ValueError, TimeoutError)):
                self.scan(original, limits=limits)
        event = threading.Event()
        event.set()
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.scan(original, cancel=event)
        # Remote link metadata is synthetic so this needs no Windows symlink privilege.
        self.model.sftp.modes['/dest/project/one'] = stat.S_IFLNK | 0o777
        with self.assertRaisesRegex(ValueError, 'type conflict'):
            self.scan(original)
        self.assertFalse((target / 'new.inp').exists())
        self.assertEqual(self.model.open_sessions, 0)

    def test_remote_source_link_is_not_followed_and_scan_channel_is_released(self):
        project, target = self.fixture()
        destination = self.root / 'download'
        destination.mkdir()
        self.model.sftp.modes['/dest/project/one/result.odb'] = stat.S_IFLNK | 0o777
        original = make_review(self.model, [PurePosixPath('/dest/project')], destination, upload=False)
        with self.assertRaisesRegex(ValueError, 'not followed'):
            self.scan(original)
        self.assertEqual(self.model.open_sessions, 0)
        self.assertFalse(list(destination.iterdir()))

    def test_case_collisions_are_rejected_for_windows_destination(self):
        self.fixture()
        destination = self.root / 'download'
        destination.mkdir()
        listing = self.model.sftp.listdir_iter
        def case_collisions(folder, read_aheads=1):
            if folder == '/dest/project':
                for name in ('A.inp', 'a.inp'):
                    yield SimpleNamespace(filename=name, st_mode=stat.S_IFREG | 0o644, st_size=1, st_mtime=100)
            else:
                yield from listing(folder, read_aheads)
        self.model.sftp.listdir_iter = case_collisions
        original = make_review(self.model, [PurePosixPath('/dest/project')], destination, upload=False)
        with self.assertRaisesRegex(ValueError, 'collisions'):
            self.scan(original)
        self.assertFalse(list(destination.iterdir()))

    def test_generation_change_during_scan_aborts_without_writes(self):
        project, target = self.fixture()
        count = [0]
        def current():
            count[0] += 1
            return count[0] < 12
        with self.assertRaisesRegex(RuntimeError, 'connection changed'):
            self.scan(make_review(self.model, [project], '/dest'), current=current)
        self.assertEqual(self.model.open_sessions, 0)
        self.assertFalse((target / 'new.inp').exists())

    def test_fresh_scan_detects_added_source_and_queued_copy_aborts(self):
        project, target = self.fixture()
        review = self.scan(make_review(self.model, [project], '/dest'))
        decision = review.choose('replace')
        (project / 'unreviewed.inp').write_bytes(b'NOT APPROVED')
        self.assertFalse(review.same_snapshot(self.scan(review.original)))
        controller = TransferController(SimpleNamespace(server=self.model, _closing=False, _connection_generation=1))
        with self.assertRaisesRegex(RuntimeError, 'contents changed'):
            controller._validate_conflict_review(decision, decision.sources)
        self.assertFalse((target / 'unreviewed.inp').exists())

    def test_controller_keeps_relative_progress_and_disables_flat_retry(self):
        project, target = self.fixture()
        review = self.scan(make_review(self.model, [project], '/dest'))
        decision = review.choose('replace')
        self.assertIs(TransferController._review_context(decision), decision)
        self.assertEqual(TransferController._target_options(decision), {'tree_decision': decision})
        labels = TransferController._progress_names(decision.sources, decision)
        self.assertEqual(len(labels), len(set(labels)))
        controller = TransferController(SimpleNamespace())
        dialog = Mock()
        controller._attach_retry(dialog, None, None, decision.sources, '/dest', decision)
        dialog.set_retry.assert_called_once_with(None)

    def test_duplicate_basename_renames_are_valid_in_different_directories(self):
        project, target = self.fixture()
        review = self.scan(make_review(self.model, [project], '/dest'))
        one, two = project / 'one' / 'result.odb', project / 'two' / 'result.odb'
        decision = review.choose('custom', {str(one): ('rename', 'copy.odb'), str(two): ('rename', 'copy.odb')})
        self.assertEqual(len(decision.renames), 2)
        with self.assertRaises(ValueError):
            review.choose('custom', {str(one): ('rename', '../out')})

    def test_sftp_listing_generator_is_closed_when_cancelled(self):
        self.fixture()
        count = [0]
        def check():
            count[0] += 1
            if count[0] > 2:
                raise RuntimeError('cancelled')
        with self.assertRaises(RuntimeError):
            self.model.transfer_directory_metadata('/dest/project', check=check)
        self.assertEqual(self.model.sftp.closed_lists, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
