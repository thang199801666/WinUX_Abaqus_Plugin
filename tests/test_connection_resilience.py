import threading
import unittest
from unittest import mock

from WinUx import server_model as server_model_module
from WinUx.server_model import SSHServerModel
from WinUx.controller import WinUXController


class _FakeRefusingClient:
    def load_system_host_keys(self):
        pass

    def set_missing_host_key_policy(self, _policy):
        pass

    def connect(self, **_kwargs):
        raise ConnectionRefusedError(111, "Connection refused")

    def close(self):
        pass


class _FakeParamiko:
    class RejectPolicy:
        pass

    class SSHClient:
        def __new__(cls):
            return _FakeRefusingClient()


class _FakeSFTPChannel:
    def __init__(self, active=True, closed=False):
        self.active = active
        self.closed = closed


class _FakeSFTP:
    def __init__(self, channel):
        self._channel = channel

    def get_channel(self):
        return self._channel


class _FakeTransport:
    def __init__(self, active=True, authenticated=True):
        self._active = active
        self._authenticated = authenticated

    def is_active(self):
        return self._active

    def is_authenticated(self):
        return self._authenticated


class _FakeClient:
    def __init__(self, transport):
        self._transport = transport

    def get_transport(self):
        return self._transport


class ConnectionResilienceTests(unittest.TestCase):
    def test_failed_reconnect_preserves_password_for_next_attempt(self):
        server = SSHServerModel()
        server.host = "server.example"
        server.username = "user"
        server._port = 22
        server._password = "secret"

        with mock.patch.object(
                server_model_module, "prepare_ssh_runtime",
                return_value=_FakeParamiko):
            with self.assertRaises(ConnectionRefusedError):
                server.reconnect()

        self.assertEqual(server._password, "secret")

    def test_password_login_does_not_probe_agent_or_local_keys(self):
        options = SSHServerModel._ssh_auth_discovery_options("secret")
        self.assertFalse(options["look_for_keys"])
        self.assertFalse(options["allow_agent"])
        key_only = SSHServerModel._ssh_auth_discovery_options(None)
        self.assertTrue(key_only["look_for_keys"])
        self.assertTrue(key_only["allow_agent"])

    def test_connected_requires_live_sftp_channel(self):
        server = SSHServerModel()
        server.client = _FakeClient(_FakeTransport())
        server.sftp = _FakeSFTP(_FakeSFTPChannel(active=True, closed=False))
        server.shell = mock.Mock(closed=False, active=True)
        self.assertTrue(server.connected)
        server.sftp = _FakeSFTP(_FakeSFTPChannel(active=False, closed=True))
        self.assertFalse(server.connected)

    def test_reconnect_is_not_started_for_healthy_control_session(self):
        controller = object.__new__(WinUXController)
        controller._closing = False
        controller._reconnect_lock = threading.Lock()
        controller._reconnect_active = False
        controller.server = mock.Mock()
        controller.server.connected = True
        controller._submit_background = mock.Mock()

        controller._start_reconnect()

        controller._submit_background.assert_not_called()
        controller.server.reconnect.assert_not_called()

    def test_reconnect_queue_rejection_releases_latch_and_schedules_retry(self):
        controller = object.__new__(WinUXController)
        controller._closing = False
        controller._reconnect_lock = threading.Lock()
        controller._reconnect_active = False
        controller._connection_generation = 7
        controller._connection_online = threading.Event()
        controller.server = mock.Mock()
        controller.server.connected = False
        controller.view = mock.Mock()
        controller._submit_background = mock.Mock(
            return_value=mock.Mock(state="rejected"))

        controller._start_reconnect()

        self.assertFalse(controller._reconnect_active)
        controller.view.after.assert_called_once_with(
            500, controller._start_reconnect)

    def test_auxiliary_work_reuses_the_control_transport(self):
        server = SSHServerModel()
        transport = _FakeTransport()
        server.client = _FakeClient(transport)
        shared_sftp = mock.Mock()
        with mock.patch.object(
                server, "_open_shared_sftp_channel",
                return_value=shared_sftp) as open_sftp:
            with server._auxiliary_session() as (client, sftp):
                self.assertIs(client.get_transport(), transport)
                self.assertIs(sftp, shared_sftp)
        open_sftp.assert_called_once_with(transport)
        shared_sftp.close.assert_called_once()

    def test_reconnect_repairs_sftp_without_new_tcp_login(self):
        server = SSHServerModel()
        transport = _FakeTransport()
        server.client = _FakeClient(transport)
        server.sftp = _FakeSFTP(_FakeSFTPChannel(active=False, closed=True))
        server.shell = mock.Mock(closed=False, active=True)
        server.host = "server.example"
        server.username = "user"
        repaired = mock.Mock()
        repaired.get_channel.return_value = _FakeSFTPChannel()
        repaired.normalize.return_value = "/home/user"
        with mock.patch.object(
                server, "_open_shared_sftp_channel",
                return_value=repaired), mock.patch.object(
                server, "connect") as full_connect:
            home = server.reconnect()
        self.assertEqual(str(home), "/home/user")
        self.assertIs(server.sftp, repaired)
        full_connect.assert_not_called()

    def test_overdue_schedule_is_catch_up_not_expired(self):
        from datetime import datetime, timedelta
        from pathlib import Path as LocalPath

        controller = object.__new__(WinUXController)
        controller._job_run_lock = threading.Lock()
        controller._job_run_tasks = {}
        controller._job_delete_lock = threading.Lock()
        controller._job_delete_tasks = {}
        controller._schedule_wakeup = threading.Event()
        controller._remove_shared_schedule = mock.Mock()
        entry = {
            "schedule_id": "run|job-key",
            "kind": "run",
            "path": str(LocalPath("/scratch/job.inp")),
            "job": {"path": "/scratch/job.inp"},
            "job_name": "job",
            "owner": "user",
            "mode": "Run At",
            "target": (datetime.now() - timedelta(minutes=5)).isoformat(),
        }
        controller._install_shared_schedules([entry])
        task = controller._job_run_tasks["job-key"]
        self.assertTrue(task["catch_up"])
        self.assertLessEqual(task["retry_at"], datetime.now())
        controller._remove_shared_schedule.assert_not_called()

    def test_due_schedule_waits_for_connection_instead_of_being_removed(self):
        from datetime import datetime, timedelta

        controller = object.__new__(WinUXController)
        controller._closing = False
        controller._job_run_lock = threading.Lock()
        controller._job_run_tasks = {}
        controller._connection_online = threading.Event()
        controller._schedule_wakeup = threading.Event()
        controller._start_reconnect = mock.Mock()
        controller._remove_shared_schedule = mock.Mock()
        controller._record_schedule_status = mock.Mock()
        controller._schedule_status_message = mock.Mock()
        controller.server = mock.Mock()
        controller.server.connected = False
        controller.view = mock.Mock()
        controller.view.after.side_effect = lambda _delay, callback, *args: callback(*args)
        task = {
            "key": "job-key",
            "schedule_id": "run|job-key",
            "job": {"path": "/scratch/job.inp"},
            "job_name": "job",
            "mode": "Run At",
            "target": datetime.now() - timedelta(seconds=10),
            "cancel": threading.Event(),
        }
        controller._job_run_tasks["job-key"] = task
        controller._execute_scheduled_run(task)
        self.assertIs(controller._job_run_tasks["job-key"], task)
        self.assertTrue(task["catch_up"])
        controller._start_reconnect.assert_called_once()
        controller._remove_shared_schedule.assert_not_called()


if __name__ == "__main__":
    unittest.main()
