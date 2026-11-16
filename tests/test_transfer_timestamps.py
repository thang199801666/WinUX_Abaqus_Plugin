"""Timestamp policies, publication failure ordering and frozen UI preferences."""
import io
import os
from pathlib import Path, PurePosixPath
import shlex
import sys
import tarfile
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from test_recursive_transfer import Model, make_review
from WinUx.services.transfer_tree import scan_tree, TreeReader
from WinUx.services.transfer_timestamps import checked_mtime
from WinUx.preferences.general import GeneralPreferences
from WinUx.controllers.transfer import TransferController
from WinUx.controllers.clipboard_transfer import ClipboardTransferController


class TransferTimestamps(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / 'remote'
        self.remote.mkdir()
        (self.remote / 'dest').mkdir()
        self.model = Model(self.remote)
        self.source = self.root / 'a.inp'
        self.source.write_bytes(b'INPUT')
        os.utime(self.source, (100, 100.875))

    def test_upload_and_renamed_copy_preserve_seconds_before_publication(self):
        for renamed in (False, True):
            with self.subTest(renamed=renamed):
                options = {'target_names': {str(self.source): 'copy.inp'}} if renamed else {}
                self.model.upload([self.source], '/dest', preserve_timestamps=True, **options)
                target = self.remote / 'dest' / ('copy.inp' if renamed else 'a.inp')
                self.assertEqual(target.read_bytes(), b'INPUT')
                self.assertEqual(target.stat().st_mtime, 100)

    def test_upload_timestamp_failure_does_not_replace_or_remove_source(self):
        target = self.remote / 'dest' / 'a.inp'
        target.write_bytes(b'OLD')
        self.model.sftp.utime = Mock(side_effect=PermissionError('SETSTAT denied'))
        with self.assertRaisesRegex(RuntimeError, 'not published'):
            self.model.upload([self.source], '/dest', move=True, preserve_timestamps=True)
        self.assertEqual(target.read_bytes(), b'OLD')
        self.assertEqual(self.source.read_bytes(), b'INPUT')
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_stream_upload_sets_time_after_channel_close_before_rename(self):
        channel = self.channel()
        closed = [False]
        def start(command):
            channel.target = shlex.split(command)[2]
            self.model.sftp.path(channel.target).write_bytes(b'')
        def send(data):
            with self.model.sftp.path(channel.target).open('ab') as stream:
                stream.write(data)
            return len(data)
        channel.exec_command.side_effect = start
        channel.send = send
        channel.close = lambda: closed.__setitem__(0, True)
        setter = self.model.sftp.utime
        def set_time(path, times):
            self.assertTrue(closed[0])
            self.assertNotEqual(path, '/dest/a.inp')
            setter(path, times)
        self.model.sftp.utime = set_time
        self.model.STREAM_FILE_THRESHOLD = 1
        self.model.HOT_DOWNLOAD_CHANNEL_TIMEOUT = 2
        self.model._shell_quote = lambda value: shlex.quote(str(value))
        self.model._open_stream_channel = lambda **kwargs: channel
        self.model.upload([self.source], '/dest', preserve_timestamps=True)
        self.assertEqual((self.remote / 'dest' / 'a.inp').stat().st_mtime, 100)

    def test_cancel_during_timestamp_rpc_does_not_publish(self):
        event = threading.Event()
        def cancel(*args):
            event.set()
        self.model.sftp.utime = cancel
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.model.upload([self.source], '/dest', preserve_timestamps=True, cancel=event)
        self.assertFalse(list((self.remote / 'dest').iterdir()))

    def test_download_preserves_time_and_disabled_keeps_current_time(self):
        remote = self.remote / 'dest' / 'a.inp'
        remote.write_bytes(b'REMOTE')
        os.utime(remote, (100, 100))
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                self.model.download([PurePosixPath('/dest/a.inp')], self.root,
                                    preserve_timestamps=enabled)
                self.assertEqual(self.source.read_bytes(), b'REMOTE')
                self.assertAlmostEqual(self.source.stat().st_mtime, 100 if enabled else time.time(), delta=3)

    def test_renamed_download_timestamp_failure_cleans_private_scratch(self):
        (self.remote / 'dest' / 'a.inp').write_bytes(b'REMOTE')
        before = {path.name for path in self.root.iterdir()}
        with patch('WinUx.services.transfer_timestamps.os.utime', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(RuntimeError, 'not published'):
                self.model.download([PurePosixPath('/dest/a.inp')], self.root,
                    preserve_timestamps=True, target_names={'/dest/a.inp': 'copy.inp'})
        self.assertEqual(self.source.read_bytes(), b'INPUT')
        self.assertEqual({path.name for path in self.root.iterdir()}, before)

    def test_disabled_upload_does_not_require_utime_support(self):
        self.model.sftp.utime = Mock(side_effect=AssertionError('Unexpected timestamp write'))
        self.model.upload([self.source], '/dest', preserve_timestamps=False)
        self.model.sftp.utime.assert_not_called()

    def test_checked_times_reject_invalid_and_unrepresentable_sftp_values(self):
        for value in (None, 'bad', float('nan'), float('inf'), -1, 2 ** 32):
            with self.subTest(value=value), self.assertRaises(ValueError):
                checked_mtime(value, sftp=True)
        self.assertEqual(checked_mtime(100.99, sftp=True), 100)
        self.assertEqual(checked_mtime(0, sftp=True), 0)

    def test_reviewed_copy_can_skip_the_same_file_on_next_newer_only_pass(self):
        folder = self.root / 'project'
        folder.mkdir()
        source = folder / 'a.inp'
        source.write_bytes(b'INPUT')
        os.utime(source, (100, 100.875))
        original = make_review(self.model, [folder], '/dest')
        def scan():
            return scan_tree(original, TreeReader('local', self.model), TreeReader('server', self.model))
        decision = scan().choose('replace')
        self.model.upload(decision.sources, '/dest', tree_decision=decision, preserve_timestamps=True)
        self.assertEqual((self.remote / 'dest' / 'project' / 'a.inp').stat().st_mtime, 100)
        self.assertFalse(scan().choose('newer').sources)

    def test_fallback_folder_copies_propagate_file_timestamp_setting(self):
        folder = self.root / 'folder'
        folder.mkdir()
        (folder / 'a.inp').write_bytes(b'INPUT')
        os.utime(folder / 'a.inp', (100, 100))
        self.model._supports_remote_tar = lambda **kwargs: False
        self.model.upload([folder], '/dest', preserve_timestamps=True)
        self.assertEqual((self.remote / 'dest' / 'folder' / 'a.inp').stat().st_mtime, 100)
        target = self.root / 'download'
        self.model.download([PurePosixPath('/dest/folder')], target, preserve_timestamps=True)
        self.assertEqual((target / 'folder' / 'a.inp').stat().st_mtime, 100)

    def test_stream_download_sets_time_on_scratch_before_publication(self):
        (self.remote / 'dest' / 'a.inp').write_bytes(b'REMOTE')
        os.utime(self.remote / 'dest' / 'a.inp', (100, 100))
        self.model.STREAM_FILE_THRESHOLD = 1
        def receive(remote, partial, offset, total, **kwargs):
            data = self.model.sftp.path(remote).read_bytes()[offset:]
            with partial.open('ab' if offset else 'wb') as stream:
                stream.write(data)
            if kwargs.get('advance'):
                kwargs['advance'](len(data))
        self.model._download_file_stream = receive
        self.model.download([PurePosixPath('/dest/a.inp')], self.root, preserve_timestamps=True)
        self.assertEqual(self.source.read_bytes(), b'REMOTE')
        self.assertEqual(self.source.stat().st_mtime, 100)

    def test_preferences_default_save_and_unrelated_updates_preserve_choice(self):
        prefs = GeneralPreferences(root=str(self.root / 'profile'))
        self.assertTrue(prefs.load()['preserve_file_timestamps'])
        prefs.save(auto_login=False, preserve_file_timestamps=False)
        prefs.save_auto_login(True)
        self.assertFalse(prefs.load()['preserve_file_timestamps'])
        prefs.save(auto_login=True, preserve_file_timestamps=True)
        self.assertTrue(prefs.load()['preserve_file_timestamps'])

    def test_queued_normal_quick_and_clipboard_tasks_freeze_the_preference(self):
        for route in ('upload', 'download', 'quick', 'clipboard'):
            with self.subTest(route=route):
                pending = []
                dialog = Mock()
                view = SimpleNamespace(_preserve_file_timestamps=True, after=lambda delay, cb, *args: cb(*args),
                    show_transfer_progress=Mock(return_value=dialog), show_error=Mock())
                server = SimpleNamespace(host='host', _port=22, username='user', upload=Mock(), download=Mock())
                app = SimpleNamespace(view=view, server=server, _closing=False, _connection_generation=1,
                    _refresh_all=Mock(), _clipboard_generation=1, _clipboard_transfer_finished=Mock(),
                    _clipboard_transfer_failed=Mock(), _clipboard_item_names=lambda sources: [p.name for p in sources])
                app._submit_transfer = lambda name, worker, **kwargs: pending.append(worker)
                local = SimpleNamespace(panel_id='local', current_path=self.root, status=Mock())
                remote = SimpleNamespace(panel_id='server', current_path=PurePosixPath('/dest'), status=Mock())
                controller = TransferController(app)
                if route == 'quick':
                    controller.start_quick_transfer(local, remote, [self.source], '/dest', '.inp', 'Upload')
                elif route == 'clipboard':
                    ClipboardTransferController(app).start(remote, 'local', [self.source], False, True, 1)
                else:
                    left, right = (remote, local) if route == 'download' else (local, remote)
                    controller.start_drop_transfer(left, right, [self.source], right.current_path, True)
                view._preserve_file_timestamps = False
                pending.pop()()
                method = server.download if route == 'download' else server.upload
                self.assertTrue(method.call_args.kwargs['preserve_timestamps'])
                view.show_error.assert_not_called()

    def channel(self, data=b''):
        stream = io.BytesIO(data)
        return SimpleNamespace(settimeout=lambda value: None, exec_command=Mock(),
            send=lambda data: len(data), recv=lambda size: stream.read(size), shutdown_write=lambda: None,
            exit_status_ready=lambda: True, recv_exit_status=lambda: 0, recv_stderr_ready=lambda: False,
            close=lambda: None)

    def test_tar_upload_toggle_controls_server_touch_option(self):
        folder = self.root / 'folder'
        folder.mkdir()
        (folder / 'a').write_bytes(b'BYTES')
        self.model.HOT_DOWNLOAD_CHANNEL_TIMEOUT = 2
        self.model._shell_quote = lambda value: shlex.quote(str(value))
        for enabled in (True, False):
            channel = self.channel()
            self.model._open_stream_channel = lambda **kwargs: channel
            self.model._upload_directory_stream(folder, '/dest', preserve_timestamps=enabled)
            self.assertIn('tar -xpf' if enabled else 'tar -xmpf', channel.exec_command.call_args.args[0])

    def test_tar_download_toggle_controls_file_and_directory_times(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            directory = tarfile.TarInfo('folder')
            directory.type, directory.mode, directory.mtime = tarfile.DIRTYPE, 0o755, 100
            archive.addfile(directory)
            file = tarfile.TarInfo('folder/a.inp')
            file.mode, file.mtime, file.size = 0o644, 100, 5
            archive.addfile(file, io.BytesIO(b'INPUT'))
        self.model.HOT_DOWNLOAD_CHANNEL_TIMEOUT = 2
        self.model._shell_quote = lambda value: shlex.quote(str(value))
        for enabled in (True, False):
            destination = self.root / ('with-time' if enabled else 'without-time')
            channel = self.channel(buffer.getvalue())
            self.model._open_stream_channel = lambda **kwargs: channel
            self.model._download_directory_stream('/dest/folder', destination, preserve_timestamps=enabled)
            self.assertEqual((destination / 'folder' / 'a.inp').read_bytes(), b'INPUT')
            expected = 100 if enabled else time.time()
            self.assertAlmostEqual((destination / 'folder' / 'a.inp').stat().st_mtime, expected, delta=3)
            self.assertAlmostEqual((destination / 'folder').stat().st_mtime, expected, delta=3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
