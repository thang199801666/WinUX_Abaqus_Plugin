from pathlib import PurePosixPath
from pathlib import Path

from WinUx.services.remote_jobs import RemoteJobsMixin


class _FakeRemoteJobs(RemoteJobsMixin):
    def __init__(self, responses, home='/home/thangnguyen', username='thangnguyen'):
        self.home = PurePosixPath(home)
        self.username = username
        self.responses = list(responses)
        self.commands = []

    def run_command(self, command):
        self.commands.append(command)
        return self.responses.pop(0) if self.responses else ''


def test_owner_temp_roots_prefer_selected_job_owner_home():
    fake = _FakeRemoteJobs([])
    roots = RemoteJobsMixin._job_temp_search_roots(fake, 'huyhuynh')
    assert roots[0] == PurePosixPath('/home/huyhuynh/Temp/huyhuynh')
    assert PurePosixPath('/home/huyhuynh/Temp') in roots


def test_exact_reported_path_is_found_from_job_owner_tree():
    expected = (
        '/home/huyhuynh/Temp/huyhuynh/'
        '31646.ohpcvn.simpsonmfg.com_29-20260030-1-1-1-1C'
    )
    fake = _FakeRemoteJobs([expected])
    result = RemoteJobsMixin._find_job_temp_folder_by_id.__wrapped__(
        fake, '31646', 'huyhuynh')
    assert result == expected
    assert "find '/home/huyhuynh/Temp/huyhuynh'" in fake.commands[0]
    assert '-maxdepth 2' in fake.commands[0]
    assert "-name '31646.*'" in fake.commands[0]


def test_owner_file_fallback_accepts_exact_id_folder_with_job_name_file():
    expected = (
        '/home/huyhuynh/Temp/huyhuynh/'
        '31646.ohpcvn.simpsonmfg.com_29-20260030-1-1-1-1C/'
        '29-20260030-1-1-1-1C.sta'
    )
    fake = _FakeRemoteJobs([expected])
    result = RemoteJobsMixin._find_job_file.__wrapped__(
        fake, '31646', '29-20260030-1-1-1-1C', '.sta', 'huyhuynh')
    assert result == expected
    assert "find '/home/huyhuynh/Temp/huyhuynh'" in fake.commands[0]


def test_check_job_controller_passes_selected_owner_to_status_lookup():
    source = (Path(__file__).resolve().parents[1] / 'WinUx' / 'controllers' /
              'job_actions.py').read_text(encoding='utf-8')
    assert 'read_job_status(job_id, name, owner)' in source
    assert 'find_job_temp_folder(job_id, name, owner)' in source


def test_owner_temp_roots_include_canonical_home_even_if_session_home_differs():
    fake = _FakeRemoteJobs([], home='/srv/users/thangnguyen')
    roots = RemoteJobsMixin._job_temp_search_roots(fake, 'huyhuynh')
    assert PurePosixPath('/home/huyhuynh/Temp/huyhuynh') in roots
    assert PurePosixPath('/home/huyhuynh/Temp') in roots
