"""Installed-only Abaqus release selection and resilient live Plot retries."""

import json
import shlex
import stat
import threading
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from WinUx.controllers.job_plot import JobPlotController
from WinUx.server_model import SSHServerModel
from WinUx.services.odb_history_live import build_remote_odb_history_live_script


def _model():
    model = SSHServerModel()
    model.host = 'cluster'
    model.username = 'tester'
    return model


def test_discovery_failure_does_not_probe_absent_abaqus_versions():
    model = _model()
    calls = []

    def exec_remote(_client, command, timeout=None):
        calls.append(command)
        if 'command -v' in command:
            return 1, '', 'login shell unavailable'
        pytest.fail('Expensive Abaqus Python must not run after failed discovery')

    model._exec_client = exec_remote
    for _ in range(2):
        with pytest.raises(RuntimeError, match='discovery failed'):
            model._resolve_abaqus_for_odb_on(
                object(), '/scratch/run.odb', ['abq2016', 'abq2026'])
    assert len(calls) == 2  # Failed results are not cached as installations.


def test_discovery_timeout_does_not_launch_all_fallback_releases():
    model = _model()
    calls = []

    def exec_remote(_client, command, timeout=None):
        calls.append(command)
        raise TimeoutError('login timeout')

    model._exec_client = exec_remote
    with pytest.raises(RuntimeError, match='Unable to detect installed'):
        model._resolve_abaqus_for_odb_on(object(), '/scratch/run.odb')
    assert len(calls) == 1
    assert 'command -v' in calls[0]


def test_installed_releases_only_and_stops_on_first_openable_file():
    model = _model()
    seen = []

    def exec_remote(_client, command, timeout=None):
        script = shlex.split(command)[-1]
        if 'command -v' in script:
            return 0, '\n'.join('__WINUX_ABAQUS_FOUND__' + item for item in (
                'abq2016', 'abq2023', 'abq2026', 'abq2025')), ''
        launcher = shlex.split(script)[0]
        seen.append(launcher)
        if launcher == 'abq2025':
            return 0, '__WINUX_ODB_RELEASE_OK__', ''
        return 3, '', 'ODB not compatible'

    model._exec_client = exec_remote
    assert model._resolve_abaqus_for_odb_on(
        object(), '/scratch/run.odb', ['abq2026', 'abq2025']) == 'abq2025'
    # Explicit old custom versions remain valid when installed; they do not
    # generate probes ahead of newer releases or after success.
    assert seen == ['abq2026', 'abq2025']


def test_legacy_installed_2016_2017_are_skipped_even_if_newest_fails():
    model = _model()
    probed = []

    def exec_remote(_client, command, timeout=None):
        script = shlex.split(command)[-1]
        if 'command -v' in script:
            return 0, '\n'.join('__WINUX_ABAQUS_FOUND__' + item for item in (
                'abq2016', 'abq2017', 'abq2025')), ''
        probed.append(shlex.split(script)[0])
        return 1, '', 'ODB is still being written'

    model._exec_client = exec_remote
    with pytest.raises(RuntimeError, match='Tried: abq2025'):
        model._resolve_abaqus_for_odb_on(
            object(), '/scratch/run.odb',
            ['abq2016', 'abq2017', 'abq2025'])
    assert probed == ['abq2025']


def test_cancel_skips_remaining_adapter_probes():
    model = _model()
    cancel = threading.Event()
    probed = []

    def exec_remote(_client, command, timeout=None):
        script = shlex.split(command)[-1]
        if 'command -v' in script:
            return 0, ('__WINUX_ABAQUS_FOUND__abq2026\n'
                       '__WINUX_ABAQUS_FOUND__abq2025'), ''
        probed.append(shlex.split(script)[0])
        cancel.set()
        return 1, '', 'unreadable'

    model._exec_client = exec_remote
    with pytest.raises(RuntimeError, match='cancelled'):
        model._resolve_abaqus_for_odb_on(
            object(), '/scratch/run.odb', cancel=cancel)
    assert probed == ['abq2026']


def test_live_monitor_restarts_after_remote_fatal_payload():
    model = _model()
    client, sftp, channel = MagicMock(), MagicMock(), MagicMock()
    sftp.stat.return_value = SimpleNamespace(st_mode=stat.S_IFREG)
    client.get_transport.return_value.is_active.return_value = True
    channel.recv_ready.side_effect = [True, False]
    channel.recv.return_value = (
        b'__WINUX_ODB_HISTORY_LIVE__' +
        json.dumps({'type': 'fatal', 'error': 'ODB temporarily unreadable'}).encode() +
        b'\n'
    )
    channel.recv_stderr_ready.return_value = False
    channel.exit_status_ready.return_value = False
    session = MagicMock()
    session.__enter__.return_value = (client, sftp)
    statuses = []
    with patch.object(model, '_auxiliary_session', return_value=session), \
         patch.object(model, '_resolve_abaqus_for_odb_on', return_value='abq2026'), \
         patch.object(model, '_cleanup_legacy_odb_helper_scripts'), \
         patch.object(model, '_write_remote_odb_temp_file',
                      return_value=PurePosixPath('/tmp/live-odb.py')), \
         patch.object(model, '_open_transport_session', return_value=channel):
        with pytest.raises(RuntimeError, match='temporarily unreadable'):
            model.stream_odb_history('/scratch/run.odb', threading.Event(),
                                     lambda: [], statuses.append)
    assert all(payload.get('type') != 'fatal' for payload in statuses)
    channel.close.assert_called_once()


def test_watch_loop_retries_failed_odb_then_recovers_to_live_without_error():
    class FastCancel:
        def __init__(self):
            self.stopped = False
            self.waits = []

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def wait(self, seconds):
            self.waits.append(seconds)
            return False

    cancel = FastCancel()
    statuses = []
    window = SimpleNamespace(
        set_status=lambda message: statuses.append(message),
        set_error=lambda message: pytest.fail('Should not show terminal Error'),
    )
    view = SimpleNamespace(
        get_job_plots=lambda job_id: window,
        after=lambda _delay, callback, *args: callback(*args),
    )
    attempts = []

    def stream_odb_history(path, event, selection_provider, on_payload, **kwargs):
        attempts.append(str(path))
        if len(attempts) < 3:
            raise RuntimeError('ODB is being written')
        on_payload({'type': 'status', 'state': 'live', 'message': 'ODB opened'})
        event.set()

    server = SimpleNamespace(connected=True, username='tester',
                             find_job_output_file=lambda *a, **kw: PurePosixPath('/scratch/run.odb'),
                             stream_odb_history=stream_odb_history)
    app = SimpleNamespace(_closing=False, view=view, server=server,
                          _inactivity_policy=Mock())
    controller = JobPlotController(app)
    controller.effective_adaptive_settings = lambda: dict(
        min_interval=1.0, max_interval=30.0, stable_samples_to_max=4,
        quiet_seconds_to_max=30.0, history_alpha=.35,
        prediction_fraction=.25, history_confidence_samples=3,
        catalog_changed_checks=5)
    with patch('WinUx.controllers.job_plot.log_exception'):
        controller.watch_loop('1', 'run', cancel)
    assert attempts == ['/scratch/run.odb'] * 3
    assert cancel.waits == [1.0, 2.0]
    assert any('retry 1' in message for message in statuses)
    assert statuses[-1] == 'ODB opened'


def test_remote_initial_open_retry_is_bounded_and_not_fatal():
    script = build_remote_odb_history_live_script()
    assert 'command = _read_command(min(5.0, policy.current))' in script
    assert '"ODB not ready; retrying: " + str(exc)' in script
    compile(script, 'remote_odb_live.py', 'exec')
