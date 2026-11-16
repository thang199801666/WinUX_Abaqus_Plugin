"""Actual local bytes + fake SFTP: renamed copies must never overwrite targets."""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import shlex
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from WinUx.services.remote_transfer import RemoteTransferMixin


class SFTP:
    def __init__(self):
        self.files = {}
        self.modes = {}
        self.on_put = self.on_get = None
        self.posix_calls = self.rename_calls = 0
    def stat(self, path):
        return SimpleNamespace(st_size=len(self.files[path]), st_mtime=100,
                               st_mode=self.modes.get(path, stat.S_IFREG | 0o644))
    lstat = stat
    def put(self, source, target, callback, confirm=False):
        data = Path(source).read_bytes()
        self.files[target] = data
        callback(len(data), len(data))
        if self.on_put:
            self.on_put()
    def get(self, source, target, callback, **kwargs):
        data = self.files[source]
        Path(target).write_bytes(data)
        callback(len(data), len(data))
        if self.on_get:
            self.on_get()
    def remove(self, path):
        self.files.pop(path, None)
    def open(self, path, mode):
        assert mode == 'rb'
        return io.BytesIO(self.files[path])
    def rename(self, source, target):
        self.rename_calls += 1
        if target in self.files:
            raise FileExistsError(target)
        self.files[target] = self.files.pop(source)
    def posix_rename(self, source, target):
        self.posix_calls += 1
        self.files[target] = self.files.pop(source)


class Model(RemoteTransferMixin):
    def __init__(self):
        self.sftp = SFTP()
        self._exec_remote = Mock(side_effect=AssertionError('Unsafe fallback publication'))
    normalize = staticmethod(PurePosixPath)
    @contextmanager
    def _auxiliary_session(self):
        yield None, self.sftp
    def _remote_size(self, path, sftp_client=None):
        return self.sftp.stat(str(path)).st_size
    def is_dir(self, path, sftp_client=None):
        return stat.S_ISDIR(self.sftp.stat(str(path)).st_mode)


class RenamedTransfers(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_upload_keeps_original_name_and_reports_source_progress(self):
        source = self.root / 'model.inp'
        source.write_bytes(b'NEW INPUT')
        model, events = Model(), []
        model.sftp.files['/dest/model.inp'] = b'OLD INPUT'
        model.upload([source], '/dest', target_names={str(source): 'model-copy.inp'},
                     progress=lambda *args: events.append(args))
        self.assertEqual(model.sftp.files['/dest/model.inp'], b'OLD INPUT')
        self.assertEqual(model.sftp.files['/dest/model-copy.inp'], b'NEW INPUT')
        self.assertEqual(model.sftp.posix_calls, 0)
        self.assertEqual(model.sftp.rename_calls, 1)
        self.assertEqual({event[0] for event in events}, {'model.inp'})
        self.assertEqual(source.read_bytes(), b'NEW INPUT')

    def test_upload_target_appearing_during_transfer_is_not_overwritten(self):
        source = self.root / 'model.inp'
        source.write_bytes(b'NEW')
        model = Model()
        model.sftp.files['/dest/model.inp'] = b'OLD'
        model.sftp.on_put = lambda: model.sftp.files.update({'/dest/copy.inp': b'ANOTHER WRITER'})
        with self.assertRaises(FileExistsError):
            model.upload([source], '/dest', target_names={str(source): 'copy.inp'})
        self.assertEqual(model.sftp.files, {'/dest/model.inp': b'OLD', '/dest/copy.inp': b'ANOTHER WRITER'})
        self.assertEqual(model.sftp.posix_calls, 0)
        model._exec_remote.assert_not_called()

    def test_stream_upload_keeps_no_replace_contract(self):
        source = self.root / 'model.inp'
        source.write_bytes(b'STREAMED INPUT')
        for collision in (False, True):
            with self.subTest(collision=collision):
                model = Model()
                model.STREAM_FILE_THRESHOLD = 1
                model.HOT_DOWNLOAD_CHANNEL_TIMEOUT = 2
                model._shell_quote = lambda value: shlex.quote(str(value))
                class Channel:
                    def settimeout(self, value): pass
                    def exec_command(self, command):
                        self.target = shlex.split(command)[2]
                        model.sftp.files[self.target] = b''
                    def send(self, data):
                        model.sftp.files[self.target] += bytes(data)
                        return len(data)
                    def shutdown_write(self):
                        if collision:
                            model.sftp.files['/dest/copy.inp'] = b'ANOTHER WRITER'
                    def exit_status_ready(self): return True
                    def recv_exit_status(self): return 0
                    def recv_stderr_ready(self): return False
                    def close(self): pass
                model._open_stream_channel = lambda **kwargs: Channel()
                if collision:
                    with self.assertRaises(FileExistsError):
                        model.upload([source], '/dest', target_names={str(source): 'copy.inp'})
                    self.assertEqual(model.sftp.files['/dest/copy.inp'], b'ANOTHER WRITER')
                else:
                    model.upload([source], '/dest', target_names={str(source): 'copy.inp'})
                    self.assertEqual(model.sftp.files['/dest/copy.inp'], source.read_bytes())
                self.assertEqual(model.sftp.posix_calls, 0)
                self.assertEqual(list(model.sftp.files), ['/dest/copy.inp'])

    def test_download_keeps_original_and_user_sidecars_intact(self):
        model = Model()
        model.sftp.files['/source/model.inp'] = b'NEW INPUT'
        original = self.root / 'model.inp'
        original.write_bytes(b'OLD INPUT')
        sidecar = self.root / 'copy.inp.winux-part'
        sidecar.write_bytes(b'USER FILE')
        model.download([PurePosixPath('/source/model.inp')], self.root,
                       target_names={'/source/model.inp': 'copy.inp'})
        self.assertEqual(original.read_bytes(), b'OLD INPUT')
        self.assertEqual((self.root / 'copy.inp').read_bytes(), b'NEW INPUT')
        self.assertEqual(sidecar.read_bytes(), b'USER FILE')
        self.assertEqual({path.name for path in self.root.iterdir()}, {'model.inp', 'copy.inp', sidecar.name})

    def test_download_target_appearing_during_transfer_is_not_overwritten(self):
        model = Model()
        model.sftp.files['/source/model.inp'] = b'NEW INPUT'
        target = self.root / 'copy.inp'
        model.sftp.on_get = lambda: target.write_bytes(b'ANOTHER WRITER')
        with self.assertRaises(FileExistsError):
            model.download([PurePosixPath('/source/model.inp')], self.root,
                           target_names={'/source/model.inp': target.name})
        self.assertEqual(target.read_bytes(), b'ANOTHER WRITER')
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_no_replace_does_not_fall_back_on_unsupported_filesystem(self):
        model = Model()
        model.sftp.files['/source/a'] = b'DATA'
        with patch('WinUx.services.remote_transfer.os.link', side_effect=OSError('Hard links unavailable')):
            with self.assertRaisesRegex(OSError, 'Hard links unavailable'):
                model.download([PurePosixPath('/source/a')], self.root,
                               target_names={'/source/a': 'copy'})
        self.assertFalse(list(self.root.iterdir()))

    def test_invalid_maps_and_moves_fail_before_writing(self):
        source = self.root / 'model.inp'
        source.write_bytes(b'NEW')
        for names in ({str(source): '../outside'}, {str(source): 'CON'}, {'wrong-source': 'copy'}):
            with self.subTest(names=names), self.assertRaises(ValueError):
                Model().upload([source], '/dest', target_names=names)
        with self.assertRaises(ValueError):
            Model().upload([source], '/dest', move=True, target_names={str(source): 'copy'})
        folder = self.root / 'folder'
        folder.mkdir()
        with self.assertRaises(ValueError):
            Model().upload([folder], '/dest', target_names={str(folder): 'folder-copy'})

    def test_normal_replace_and_resumable_download_are_unchanged(self):
        source = self.root / 'model.inp'
        source.write_bytes(b'NEW')
        model = Model()
        model.sftp.files['/dest/model.inp'] = b'OLD'
        model.upload([source], '/dest')
        self.assertEqual(model.sftp.files['/dest/model.inp'], b'NEW')
        self.assertEqual(model.sftp.posix_calls, 1)
        model.sftp.files['/source/a'] = b'DOWNLOAD'
        target = self.root / 'a'
        target.write_bytes(b'OLD')
        model.download([PurePosixPath('/source/a')], self.root)
        self.assertEqual(target.read_bytes(), b'DOWNLOAD')
        self.assertFalse((self.root / 'a.winux-part').exists())

    def test_existing_normal_download_partial_still_resumes(self):
        model = Model()
        model.sftp.files['/source/a'] = b'DOWNLOAD'
        partial = self.root / 'a.winux-part'
        metadata = self.root / 'a.winux-part.json'
        partial.write_bytes(b'DOW')
        metadata.write_text(json.dumps({'remote_path': '/source/a', 'size': 8, 'mtime': 100}))
        counts = []
        model._download_file('/source/a', self.root / 'a', advance=counts.append)
        self.assertEqual((self.root / 'a').read_bytes(), b'DOWNLOAD')
        self.assertEqual(counts, [3, 5])
        self.assertFalse(partial.exists() or metadata.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
