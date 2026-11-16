"""Fast Check Job lookup and unchanged status rendering (mock SSH)."""
import sys
import unittest
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.server_model import SSHServerModel


class FastJobStatusTests(unittest.TestCase):
    def server(self, files='', content=''):
        server = SSHServerModel()
        server.home = PurePosixPath('/home/test')
        server.username = 'stale-login-user'
        calls = []

        def run(command):
            calls.append(command)
            if 'whoami' in command:
                return '__WINUX_USER__=test\n__WINUX_HOST__=host.cluster'
            if command.startswith('for _winux_root'):
                return files
            if command.startswith('cat '):
                return (content + '\n__WINUX_STATUS_CHECK_TIME__=23-Oct-2026 10:00:00').strip()
            raise AssertionError('Unexpected slow/fallback SSH call: ' + command)

        server.run_command = run
        return server, calls

    def test_missing_sta_returns_without_home_scan_or_reads(self):
        server, calls = self.server()
        self.assertEqual(server.read_job_status('123.host', 'model', 'test'),
                         'Job has not started yet (.sta file not found).')
        self.assertEqual(len(calls), 2)  # Live identity + one batched lookup.
        self.assertIn('-maxdepth 2', calls[1])
        self.assertIn("-name '*.sta'", calls[1])
        self.assertNotIn("find '/home/test'", calls[1])
        self.assertNotIn('sort ', calls[1])

    def test_wrong_owner_is_rejected_before_search(self):
        server, calls = self.server()
        with self.assertRaisesRegex(RuntimeError, 'belongs to other'):
            server.read_job_status('123.host', 'model', 'other')
        self.assertEqual(len(calls), 1)

    def test_exact_job_name_beats_newer_other_sta(self):
        folder = '/home/test/Temp/test/123.host.cluster_model'
        server, calls = self.server('10\t' + folder + '/model.sta\n99\t' + folder + '/helper.sta')
        path = server._find_job_status_file_fast('123.host', 'model', 'test', 'test', 'host.cluster')
        self.assertEqual(path, folder + '/model.sta')
        self.assertEqual(len(calls), 1)

    def test_latest_sta_fallback_within_validated_job_directory(self):
        folder = '/home/test/Temp/123.host.cluster_model'
        server, _ = self.server('1\t' + folder + '/old.sta\n2\t' + folder + '/renamed.sta')
        self.assertEqual(server._find_job_status_file_fast('123', 'model', 'test', 'test', 'host.cluster'),
                         folder + '/renamed.sta')

    def test_wrong_id_or_host_cannot_be_accepted(self):
        files = '\n'.join('100\t/home/test/Temp/' + directory + '/model.sta' for directory in
                          ('1123.host.cluster_model', '1234.host.cluster_model', '123.other.cluster_model'))
        server, calls = self.server(files)
        self.assertIn('not started yet', server.read_job_status('123', 'model', 'test'))
        self.assertEqual(len(calls), 2)

    def test_existing_sta_keeps_current_results_and_uses_three_calls(self):
        path = '/home/test/Temp/test/123.host.cluster_model/model.sta'
        samples = (
            'STEP 1 ORIGIN 0\nOutput Field Frame Number 2 of 20\n',
            'STEP 1 ORIGIN 0\nOutput Field Frame Number 20 of 20\nTHE ANALYSIS HAS COMPLETED SUCCESSFULLY\n',
            'THE ANALYSIS HAS TERMINATED\n',
            '',
        )
        for content in samples:
            with self.subTest(content=content):
                server, calls = self.server('1\t' + path, content)
                status = server._parse_abaqus_status(content)
                if status.get('state') in {'running', 'starting', 'preprocessing'}:
                    server._apply_check_time_runtime(status, '23-Oct-2026 10:00:00')
                self.assertEqual(server.read_job_status('123', 'model', 'test'),
                                 server._format_abaqus_status(status))
                self.assertEqual(len(calls), 3)
                self.assertIn('cat ' + server._shell_quote(path), calls[-1])
                self.assertIn("date '+%d-%b-%Y %H:%M:%S'", calls[-1])

    def test_legacy_job_id_directory_remains_supported(self):
        path = '/home/test/Temp/test/123_model/model.sta'
        server, _ = self.server('1\t' + path)
        self.assertEqual(server._find_job_status_file_fast('123', 'model', 'test', 'test', 'host.cluster'), path)

    def test_remote_errors_are_not_reported_as_missing_sta(self):
        server, _ = self.server()
        server.run_command = lambda command: (_ for _ in ()).throw(RuntimeError('SSH disconnected'))
        with self.assertRaisesRegex(RuntimeError, 'SSH disconnected'):
            server.read_job_status('123', 'model', 'test')


if __name__ == '__main__':
    unittest.main(verbosity=2)
