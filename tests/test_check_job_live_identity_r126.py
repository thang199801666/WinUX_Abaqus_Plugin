import threading
from pathlib import PurePosixPath

import pytest

from WinUx.services.remote_jobs import RemoteJobsMixin


class _IdentityProbe(RemoteJobsMixin):
    def __init__(self, response):
        self.response = response
        self.commands = []

    def run_command(self, command):
        self.commands.append(command)
        return self.response


def test_current_remote_identity_queries_whoami_and_hostname_every_time():
    fake = _IdentityProbe(
        '__WINUX_USER__=huyhuynh\n__WINUX_HOST__=ohpcvn.simpsonmfg.com')
    first = RemoteJobsMixin.current_remote_identity.__wrapped__(fake)
    second = RemoteJobsMixin.current_remote_identity.__wrapped__(fake)
    assert first == ('huyhuynh', 'ohpcvn.simpsonmfg.com')
    assert second == first
    assert len(fake.commands) == 2
    assert all('whoami' in command for command in fake.commands)
    assert all('hostname -f' in command for command in fake.commands)


def test_scheduler_folder_identity_rejects_same_id_from_different_hostname():
    assert RemoteJobsMixin._component_matches_job_identity(
        '31646.ohpcvn.simpsonmfg.com_29-20260030-1-1-1-1C',
        '31646', 'ohpcvn.simpsonmfg.com')
    assert not RemoteJobsMixin._component_matches_job_identity(
        '31646.otherhost.simpsonmfg.com_29-20260030-1-1-1-1C',
        '31646', 'ohpcvn.simpsonmfg.com')
    assert RemoteJobsMixin._component_matches_job_identity(
        '31646_29-20260030-1-1-1-1C',
        '31646', 'ohpcvn.simpsonmfg.com')


class _ReadStatusProbe(RemoteJobsMixin):
    def __init__(self):
        self._connection_lock = threading.RLock()
        self.home = PurePosixPath('/home/stale-user')
        self.username = 'stale-user'
        self.identity_calls = 0
        self.folder_calls = []

    def current_remote_identity(self):
        self.identity_calls += 1
        hosts = ('ohpcvn.simpsonmfg.com', 'ohpcvn.simpsonmfg.com')
        return 'huyhuynh', hosts[self.identity_calls - 1]

    def _find_job_temp_folder_by_id(self, job_id, job_owner=None,
                                    current_username=None,
                                    current_hostname=None):
        self.folder_calls.append((job_id, job_owner, current_username,
                                  current_hostname))
        return ('/home/huyhuynh/Temp/huyhuynh/'
                '31646.ohpcvn.simpsonmfg.com_29-20260030-1-1-1-1C')

    def _find_latest_file(self, folder, filename_pattern, exclude_suffix=None):
        return str(PurePosixPath(folder) / '29-20260030-1-1-1-1C.sta')

    def run_command(self, command):
        if command.startswith("cat '"):
            return 'Output Field Frame Number 12, of 40,'
        if command.startswith("date '"):
            return '20-Oct-2026 08:00:00'
        raise AssertionError(command)


def test_each_check_job_refreshes_live_username_and_hostname():
    fake = _ReadStatusProbe()
    for _ in range(2):
        result = RemoteJobsMixin.read_job_status.__wrapped__(
            fake, '31646', '29-20260030-1-1-1-1C', 'huyhuynh')
        assert 'Status: Running' in result
        assert 'Current step: 1' in result
        assert 'Frame: 12/40' in result
    assert fake.identity_calls == 2
    assert fake.folder_calls == [
        ('31646', 'huyhuynh', 'huyhuynh', 'ohpcvn.simpsonmfg.com'),
        ('31646', 'huyhuynh', 'huyhuynh', 'ohpcvn.simpsonmfg.com'),
    ]


def test_check_job_rejects_stale_or_wrong_current_user():
    fake = _ReadStatusProbe()
    fake.current_remote_identity = lambda: ('another-user', 'ohpcvn.simpsonmfg.com')
    with pytest.raises(RuntimeError, match='current SSH user is another-user'):
        RemoteJobsMixin.read_job_status.__wrapped__(
            fake, '31646', '29-20260030-1-1-1-1C', 'huyhuynh')
