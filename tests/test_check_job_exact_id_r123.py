from pathlib import PurePosixPath

from WinUx.services.remote_jobs import RemoteJobsMixin


class _FakeRemoteJobs(RemoteJobsMixin):
    def __init__(self, responses):
        self.home = PurePosixPath('/home/thang')
        self.username = 'thang'
        self.responses = list(responses)
        self.commands = []

    def run_command(self, command):
        self.commands.append(command)
        return self.responses.pop(0) if self.responses else ''


def test_exact_job_id_token_rejects_nearby_numeric_ids():
    assert RemoteJobsMixin._component_has_exact_job_id('31635.server_job', '31635')
    assert RemoteJobsMixin._component_has_exact_job_id('job-31635-run', '31635')
    assert not RemoteJobsMixin._component_has_exact_job_id('131635.server_job', '31635')
    assert not RemoteJobsMixin._component_has_exact_job_id('316350.server_job', '31635')


def test_job_file_match_requires_exact_id_in_directory_not_filename():
    assert RemoteJobsMixin._path_has_exact_job_id(
        '/home/thang/Temp/thang/31635.server_job/Model.sta', '31635')
    assert not RemoteJobsMixin._path_has_exact_job_id(
        '/home/thang/Temp/thang/316350.server_job/Model.sta', '31635')
    assert not RemoteJobsMixin._path_has_exact_job_id(
        '/home/thang/results/Model-31635.sta', '31635')


def test_find_job_file_skips_newer_wrong_job_id_and_returns_exact_job():
    fake = _FakeRemoteJobs([
        '\n'.join([
            '/home/thang/Temp/thang/316350.server_Model/Model.sta',
            '/home/thang/Temp/thang/131635.server_Model/Model.sta',
            '/home/thang/Temp/thang/31635.server_Model/Model.sta',
        ])
    ])
    result = RemoteJobsMixin._find_job_file.__wrapped__(
        fake, '31635', 'Model', '.sta')
    assert result == '/home/thang/Temp/thang/31635.server_Model/Model.sta'
    assert "-name '*Model*.sta'" in fake.commands[0]


def test_find_job_file_returns_empty_when_only_job_name_matches():
    fake = _FakeRemoteJobs([
        '\n'.join([
            '/home/thang/results/Model.sta',
            '/home/thang/Temp/thang/316350.server_Model/Model.sta',
        ])
    ])
    result = RemoteJobsMixin._find_job_file.__wrapped__(
        fake, '31635', 'Model', '.sta')
    assert result == ''


def test_temp_folder_lookup_rejects_wrong_numeric_id_even_if_shell_returns_it():
    fake = _FakeRemoteJobs([
        '/home/thang/Temp/thang/316350.server_Model',
        '/home/thang/Temp/31635.server_Model',
    ])
    result = RemoteJobsMixin._find_job_temp_folder_by_id.__wrapped__(fake, '31635')
    assert result == '/home/thang/Temp/31635.server_Model'
    assert len(fake.commands) == 2
    assert "-name '31635.*'" in fake.commands[0]
