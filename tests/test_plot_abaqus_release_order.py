"""Plots must probe the newest available Abaqus release before older ones."""
from pathlib import PurePosixPath
import shlex
import stat
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from WinUx.server_model import SSHServerModel


class PlotAbaqusReleaseOrderTests(unittest.TestCase):
    def setUp(self):
        self.model = SSHServerModel()
        self.model.host = "cluster"
        self.model.username = "tester"
        self.installed = ["abaqus", "abq2023", "abq2025", "abq2026"]
        self.compatible = "abq2025"
        self.probes = []
        self.discovery_calls = 0
        self.model._exec_client = Mock(side_effect=self.exec_remote)

    def exec_remote(self, client, command, timeout=None):
        script = shlex.split(command)[-1]
        if "command -v" in script:
            self.discovery_calls += 1
            return 0, "\n".join("__WINUX_ABAQUS_FOUND__" + name
                                for name in self.installed), ""
        candidate = shlex.split(script)[0]
        self.probes.append(candidate)
        if candidate == self.compatible:
            return 0, "__WINUX_ODB_RELEASE_OK__", ""
        return 3, "", "ODB release mismatch"

    def resolve(self, path="/scratch/jobs/job.odb", commands=None):
        return self.model._resolve_abaqus_for_odb_on(
            object(), path, commands or ["abaqus", "abq2023", "abq2025", "abq2026"],
            newest_first=True)

    def test_old_default_and_unsorted_discovery_cannot_outrank_latest(self):
        self.assertEqual(self.resolve(), "abq2025")
        self.assertEqual(self.probes, ["abq2026", "abq2025"])
        for call in self.model._exec_client.call_args_list:
            if " python -c " in call.args[1]:
                self.assertIn("readOnly=True", call.args[1])
                self.assertNotIn("upgradeOdb(", call.args[1])

    def test_all_older_cache_hints_cannot_outrank_latest(self):
        identity = ("cluster", "tester")
        self.model._odb_abaqus_command_cache[identity + ("/scratch/jobs/job.odb",)] = "abq2023"
        self.model._odb_abaqus_directory_hint_cache[identity + ("/scratch/jobs",)] = "abq2023"
        self.model._odb_abaqus_host_hint_cache[identity] = "abq2023"
        self.assertEqual(self.resolve(), "abq2025")
        self.assertEqual(self.probes, ["abq2026", "abq2025"])

    def test_reopening_same_odb_rechecks_latest_and_reuses_discovery(self):
        self.assertEqual(self.resolve(), "abq2025")
        self.probes.clear()
        self.compatible = "abq2026"
        self.assertEqual(self.resolve(), "abq2026")
        self.assertEqual(self.probes, ["abq2026"])
        self.assertEqual(self.discovery_calls, 1)

    def test_next_job_still_starts_with_latest_after_older_job_succeeded(self):
        self.assertEqual(self.resolve(), "abq2025")
        self.probes.clear()
        self.assertEqual(self.resolve("/scratch/other/job.odb"), "abq2025")
        self.assertEqual(self.probes, ["abq2026", "abq2025"])

    def test_missing_versions_are_skipped_and_abaqus_alias_is_last(self):
        self.installed = ["abaqus", "abq2023", "abq2025"]
        self.compatible = "abaqus"
        self.assertEqual(self.resolve(), "abaqus")
        self.assertEqual(self.probes, ["abq2025", "abq2023", "abaqus"])

    def test_newer_configured_releases_and_hotfixes_are_sorted_numerically(self):
        self.installed = ["abaqus", "abq2027", "abq2026hf2", "abq2026hf10", "abq2026"]
        self.compatible = "abq2026"
        self.assertEqual(self.resolve(commands=self.installed), "abq2026")
        self.assertEqual(self.probes, ["abq2027", "abq2026hf10", "abq2026hf2", "abq2026"])

    def test_custom_launcher_paths_are_kept_after_versioned_releases(self):
        self.installed = ["abaqus", "site-abaqus", "/opt/abaqus/abq2027", "abq2026"]
        self.compatible = "site-abaqus"
        self.assertEqual(self.resolve(commands=self.installed), "site-abaqus")
        self.assertEqual(self.probes, ["/opt/abaqus/abq2027", "abq2026", "site-abaqus"])

    def test_probe_exception_falls_back_to_next_release(self):
        original = self.exec_remote

        def fail_latest(client, command, timeout=None):
            if "abq2026 python" in command:
                self.probes.append("abq2026")
                raise RuntimeError("Probe timed out")
            return original(client, command, timeout)

        self.model._exec_client.side_effect = fail_latest
        self.assertEqual(self.resolve(), "abq2025")
        self.assertEqual(self.probes, ["abq2026", "abq2025"])

    def test_all_failures_report_the_order_used(self):
        self.compatible = None
        with self.assertRaisesRegex(RuntimeError, "Tried: abq2026, abq2025, abq2023, abaqus"):
            self.resolve()
        self.assertEqual(self.probes, ["abq2026", "abq2025", "abq2023", "abaqus"])

    def test_live_plots_launches_monitor_using_newest_compatible_release(self):
        client, sftp, channel = MagicMock(), MagicMock(), MagicMock()
        sftp.stat.return_value = SimpleNamespace(st_mode=stat.S_IFREG)
        sftp.listdir.return_value = []
        sftp.normalize.return_value = "/home/tester"
        channel.recv_ready.return_value = False
        channel.recv_stderr_ready.return_value = False
        channel.exit_status_ready.return_value = True
        channel.recv_exit_status.return_value = 0
        session = MagicMock()
        session.__enter__.return_value = (client, sftp)
        payloads = []
        with patch.object(self.model, "_auxiliary_session", return_value=session), \
                patch.object(self.model, "_write_remote_odb_temp_file",
                             return_value=PurePosixPath("/tmp/live-odb.py")), \
                patch.object(self.model, "_open_transport_session", return_value=channel):
            self.model.stream_odb_history(
                "/scratch/jobs/job.odb", threading.Event(), lambda: [], payloads.append,
                abaqus_commands=["abaqus", "abq2023", "abq2025", "abq2026"])
        self.assertEqual(self.probes, ["abq2026", "abq2025"])
        self.assertIn("abq2025 python", channel.exec_command.call_args.args[0])
        opening = next(payload for payload in payloads if payload.get("state") == "opening")
        self.assertEqual(opening["abaqusCommand"], "abq2025")
        channel.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
