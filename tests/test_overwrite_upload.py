"""Regression checks for Local -> Server overwrite stability."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from WinUx.server_model import SSHServerModel


class _Stat:
    def __init__(self, size):
        self.st_size = size


class _FakeSFTP:
    def __init__(self):
        self.files = {}
        self.put_calls = []
        self.rename_calls = []
        self.remove_calls = []

    def put(self, local, remote, callback=None, confirm=False):
        data = Path(local).read_bytes()
        self.files[str(remote)] = data
        self.put_calls.append((str(local), str(remote), bool(confirm)))
        if callback is not None:
            callback(len(data), len(data))

    def stat(self, remote):
        return _Stat(len(self.files[str(remote)]))

    def posix_rename(self, source, target):
        source, target = str(source), str(target)
        self.rename_calls.append((source, target))
        self.files[target] = self.files.pop(source)

    def remove(self, remote):
        remote = str(remote)
        self.remove_calls.append(remote)
        self.files.pop(remote, None)


class AtomicOverwriteUploadTests(unittest.TestCase):
    def test_small_upload_never_puts_directly_into_existing_target(self):
        server = SSHServerModel()
        fake = _FakeSFTP()
        destination = "/remote/run"

        @contextmanager
        def auxiliary_session():
            yield object(), fake

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "model.inp"
            source.write_bytes(b"new input contents")
            final = destination + "/model.inp"
            fake.files[final] = b"old contents"

            with mock.patch.object(server, "_auxiliary_session", auxiliary_session):
                server.upload([source], destination)

        self.assertEqual(len(fake.put_calls), 1)
        uploaded_remote = fake.put_calls[0][1]
        self.assertNotEqual(uploaded_remote, final)
        self.assertIn(".model.inp.winux-upload-", uploaded_remote)
        self.assertEqual(fake.rename_calls, [(uploaded_remote, final)])
        self.assertEqual(fake.files[final], b"new input contents")
        self.assertNotIn(uploaded_remote, fake.files)

    def test_failed_publish_keeps_existing_target_untouched(self):
        server = SSHServerModel()
        fake = _FakeSFTP()
        destination = "/remote/run"

        @contextmanager
        def auxiliary_session():
            yield object(), fake

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "model.inp"
            source.write_bytes(b"new input contents")
            final = destination + "/model.inp"
            fake.files[final] = b"old contents"

            def fail_rename(source_name, target_name):
                raise OSError("rename extension unavailable")

            fake.posix_rename = fail_rename
            with mock.patch.object(server, "_auxiliary_session", auxiliary_session), \
                    mock.patch.object(
                        server, "_exec_client",
                        return_value=(1, "", "publish failed")):
                with self.assertRaisesRegex(RuntimeError, "publish failed"):
                    server.upload([source], destination)

        self.assertEqual(fake.files[final], b"old contents")
        self.assertFalse(any("winux-upload" in name for name in fake.files))


if __name__ == "__main__":
    unittest.main()
