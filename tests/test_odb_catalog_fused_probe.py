from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import stat
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from WinUx.services.odb.remote import RemoteODBMixin


class _Attr:
    st_mode = stat.S_IFREG | 0o644
    st_size = 12345


class _Sftp:
    def stat(self, _path):
        return _Attr()
    def remove(self, _path):
        pass


class _Server(RemoteODBMixin):
    host = "host"
    username = "user"
    ODB_CHECK_TIMEOUT_SECONDS = 10
    ABAQUS_DISCOVERY_CACHE_SECONDS = 60
    _odb_abaqus_command_cache_lock = __import__('threading').RLock()
    _odb_abaqus_command_cache = {}
    _odb_abaqus_directory_hint_cache = {}
    _odb_abaqus_host_hint_cache = {}
    _abaqus_available_command_cache = {}

    def __init__(self):
        self.client = object()
        self.sftp = _Sftp()
        self.exec_calls = []
        self.resolve_calls = 0

    def normalize(self, value):
        return PurePosixPath(str(value))

    @contextmanager
    def _auxiliary_session(self):
        yield self.client, self.sftp

    def _cleanup_legacy_odb_helper_scripts(self, _sftp):
        pass

    def _write_remote_odb_temp_file(self, _sftp, filename, _payload):
        return PurePosixPath('/tmp') / filename

    def _abaqus_candidate_commands(self, _values=None):
        return ['abq2026', 'abq2025']

    def _available_abaqus_candidates_on(self, _client, candidates):
        return list(candidates)

    def _resolve_abaqus_for_odb_on(self, *_args, **_kwargs):
        self.resolve_calls += 1
        raise AssertionError('catalog must not run separate compatibility resolver')

    def _login_shell_command(self, command):
        return command

    def _shell_quote(self, value):
        return "'{}'".format(str(value))

    def _exec_client(self, _client, command, timeout=None):
        self.exec_calls.append(command)
        payload = (
            '__WINUX_ODB_EXTRACT_JSON_BEGIN__\n'
            '{"schemaVersion":1,"mode":"catalog","historyOutputs":[],"error":null}\n'
            '__WINUX_ODB_EXTRACT_JSON_END__\n'
        )
        return 0, payload, ''


class FusedCatalogProbeTests(unittest.TestCase):
    def test_catalog_uses_real_catalog_as_compatibility_probe(self):
        server = _Server()
        result = server.list_odb_history_outputs('/remote/sample.odb')
        self.assertEqual(server.resolve_calls, 0)
        self.assertEqual(len(server.exec_calls), 1)
        self.assertIn('abq2026 python', server.exec_calls[0])
        self.assertTrue(result['fusedCompatibilityProbe'])
        self.assertEqual(result['abaqusCommand'], 'abq2026')

    def test_catalog_falls_back_to_next_launcher_without_extra_probe(self):
        server = _Server()
        calls = {"n": 0}
        def run(_client, command, timeout=None):
            server.exec_calls.append(command)
            calls["n"] += 1
            if calls["n"] == 1:
                payload = (
                    '__WINUX_ODB_EXTRACT_JSON_BEGIN__\n'
                    '{"error":"ODB created by incompatible release"}\n'
                    '__WINUX_ODB_EXTRACT_JSON_END__\n'
                )
                return 0, payload, ''
            payload = (
                '__WINUX_ODB_EXTRACT_JSON_BEGIN__\n'
                '{"schemaVersion":1,"mode":"catalog","historyOutputs":[],"error":null}\n'
                '__WINUX_ODB_EXTRACT_JSON_END__\n'
            )
            return 0, payload, ''
        server._exec_client = run
        result = server.list_odb_history_outputs('/remote/sample.odb')
        self.assertEqual(server.resolve_calls, 0)
        self.assertEqual(len(server.exec_calls), 2)
        self.assertIn('abq2026 python', server.exec_calls[0])
        self.assertIn('abq2025 python', server.exec_calls[1])
        self.assertEqual(result['abaqusCommand'], 'abq2025')

    def test_cached_compatible_launcher_generic_open_failure_waits_when_file_is_active(self):
        server = _Server()
        identity = (server.host, server.username)
        cache_key = identity + ('/remote/sample.odb',)
        server._odb_abaqus_command_cache[cache_key] = 'abq2026'
        calls = {'n': 0}
        def run(_client, command, timeout=None):
            server.exec_calls.append(command)
            calls['n'] += 1
            if calls['n'] == 1:
                payload = (
                    '__WINUX_ODB_EXTRACT_JSON_BEGIN__\n'
                    '{"error":"Unable to open database"}\n'
                    '__WINUX_ODB_EXTRACT_JSON_END__\n'
                )
                return 0, payload, ''
            payload = (
                '__WINUX_ODB_EXTRACT_JSON_BEGIN__\n'
                '{"schemaVersion":1,"mode":"catalog","historyOutputs":[],"error":null}\n'
                '__WINUX_ODB_EXTRACT_JSON_END__\n'
            )
            return 0, payload, ''
        server._exec_client = run
        server._remote_odb_processing_hint = lambda _sftp, _path: True
        waited = []
        server._wait_for_remote_odb_ready = lambda _sftp, _path, timeout=None: waited.append(True) or True
        result = server.list_odb_history_outputs('/remote/sample.odb')
        self.assertEqual(len(server.exec_calls), 2)
        self.assertTrue(waited)
        self.assertEqual(result['abaqusCommand'], 'abq2026')
        self.assertTrue(result['waitedForOdbUpdate'])

    def test_version_mismatch_never_waits_even_when_file_is_active(self):
        server = _Server()
        identity = (server.host, server.username)
        cache_key = identity + ('/remote/sample.odb',)
        server._odb_abaqus_command_cache[cache_key] = 'abq2026'
        calls = {'n': 0}
        def run(_client, command, timeout=None):
            server.exec_calls.append(command)
            calls['n'] += 1
            if calls['n'] == 1:
                payload = (
                    '__WINUX_ODB_EXTRACT_JSON_BEGIN__\n'
                    '{"error":"The database is from a more recent release of Abaqus; upgrade is required"}\n'
                    '__WINUX_ODB_EXTRACT_JSON_END__\n'
                )
                return 0, payload, ''
            payload = (
                '__WINUX_ODB_EXTRACT_JSON_BEGIN__\n'
                '{"schemaVersion":1,"mode":"catalog","historyOutputs":[],"error":null}\n'
                '__WINUX_ODB_EXTRACT_JSON_END__\n'
            )
            return 0, payload, ''
        server._exec_client = run
        server._remote_odb_processing_hint = lambda _sftp, _path: True
        server._wait_for_remote_odb_ready = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('must not wait'))
        result = server.list_odb_history_outputs('/remote/sample.odb')
        self.assertEqual(len(server.exec_calls), 2)
        self.assertIn('abq2025 python', server.exec_calls[1])
        self.assertEqual(result['abaqusCommand'], 'abq2025')

if __name__ == '__main__':
    unittest.main(verbosity=2)
