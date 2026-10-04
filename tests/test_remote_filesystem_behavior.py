from contextlib import contextmanager
from pathlib import PurePosixPath

from WinUx.services.remote_filesystem import RemoteFilesystemMixin


class _DeleteHarness(RemoteFilesystemMixin):
    def __init__(self):
        self.sftp_token = object()
        self.removed = []

    @contextmanager
    def _transfer_sftp(self):
        yield self.sftp_token

    def exists(self, path, sftp_client=None):
        assert sftp_client is self.sftp_token
        return True

    def remove(self, path, sftp_client=None):
        assert sftp_client is self.sftp_token
        self.removed.append(PurePosixPath(path))


def test_recursive_delete_uses_dedicated_channel_without_control_lock_dependency():
    model = _DeleteHarness()
    deleted = model.delete(["/a", "/a/child", "/b"])
    assert deleted == [PurePosixPath("/a"), PurePosixPath("/b")]
    assert model.removed == deleted
