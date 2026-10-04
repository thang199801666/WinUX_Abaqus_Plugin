"""Headless regression coverage for local/server Check ODB."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from WinUx.server_model import SSHServerModel


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "WinUx" / "services" / "odb_check.py"
SERVER = ROOT / "WinUx" / "server_model.py"
REMOTE_ODB = ROOT / "WinUx" / "services" / "remote_odb.py"
CONTROLLER = ROOT / "WinUx" / "controller.py"
JOB_PLOT_CONTROLLER = ROOT / "WinUx" / "controllers" / "job_plot.py"
FILE_PANEL = ROOT / "WinUx" / "components" / "file_panel.py"
JOBS_VIEW = ROOT / "WinUx" / "components" / "jobs_view.py"
DIALOG = ROOT / "WinUx" / "dialogs" / "odb_check_dialog.py"

SPEC = importlib.util.spec_from_file_location("winux_odb_check", SERVICE)
odb_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(odb_check)


class ODBExtractorTests(unittest.TestCase):
    def test_remote_script_is_history_only_and_avoids_expensive_inventory(self):
        script = odb_check.build_remote_odb_check_script()
        self.assertIn("from odbAccess import openOdb", script)
        self.assertIn('upper.startswith("RF")', script)
        self.assertIn('"loadDisplacementRows"', script)
        self.assertIn("_matching_displacement(", script)

        # Fast Check ODB must not enumerate the finite-element model or scan
        # nodal field outputs/frames just to report RF + displacement history.
        self.assertNotIn("odb.rootAssembly", script)
        self.assertNotIn("totalNodes", script)
        self.assertNotIn("totalElements", script)
        self.assertNotIn(".fieldOutputs", script)
        self.assertNotIn("getNodeFromLabel", script)
        self.assertNotIn("step.frames", script)

        compile(script, "remote_odb_check.py", "exec")
        self.assertNotIn('f"', script)
        self.assertNotIn("pathlib", script)

    def test_remote_extractor_keeps_every_rf_history_and_pairs_same_direction_u(self):
        import sys
        import types

        class Output:
            def __init__(self, data, description=""):
                self.data = data
                self.description = description

        class Region:
            def __init__(self, outputs):
                self.historyOutputs = outputs

        class Step:
            historyRegions = {
                "Node Set ASSEMBLY.TOP": Region({
                    "RF1": Output([(0.0, -10.0), (1.0, 20.0)]),
                    "U1": Output([(0.0, 0.0), (1.0, 2.0)]),
                    "RF3_ANTIALIASING": Output([(0.0, 1.0), (0.8, -30.0)]),
                    "U3_ANTIALIASING": Output([(0.0, 0.0), (0.8, 3.5)]),
                }),
                "Node Set ASSEMBLY.BOTTOM": Region({
                    "RF1": Output([(0.0, 2.0), (0.5, -12.0)]),
                    "U1": Output([(0.0, 0.0), (0.5, -0.7)]),
                }),
            }

        class Odb:
            name = "demo.odb"
            steps = {"Step-1": Step()}
            def close(self):
                pass

        fake = types.ModuleType("odbAccess")
        fake.openOdb = lambda path, readOnly=True: Odb()
        old = sys.modules.get("odbAccess")
        sys.modules["odbAccess"] = fake
        try:
            namespace = {"__name__": "winux_remote_test"}
            exec(compile(odb_check.ODB_CHECK_SCRIPT, "remote.py", "exec"), namespace)
            result = namespace["inspect_odb"]("/tmp/demo.odb")
        finally:
            if old is None:
                sys.modules.pop("odbAccess", None)
            else:
                sys.modules["odbAccess"] = old

        self.assertEqual(result["schemaVersion"], 3)
        rows = result["loadDisplacementRows"]
        self.assertEqual(len(rows), 3)

        # Equal RF component names from different node sets/regions must not be
        # collapsed into one row.
        rf1_rows = [row for row in rows if row["rfOutput"] == "RF1"]
        self.assertEqual(len(rf1_rows), 2)
        by_region = {row["historyRegion"]: row for row in rf1_rows}
        self.assertEqual(by_region["Node Set ASSEMBLY.TOP"]["rfValue"], 20.0)
        self.assertEqual(by_region["Node Set ASSEMBLY.TOP"]["uOutput"], "U1")
        self.assertEqual(by_region["Node Set ASSEMBLY.TOP"]["uValue"], 2.0)
        self.assertEqual(by_region["Node Set ASSEMBLY.BOTTOM"]["rfValue"], -12.0)
        self.assertEqual(by_region["Node Set ASSEMBLY.BOTTOM"]["uValue"], -0.7)

        # Custom output suffixes pair by exact RF->U name in the same region.
        custom = next(row for row in rows if row["rfOutput"] == "RF3_ANTIALIASING")
        self.assertEqual(custom["rfValue"], -30.0)
        self.assertEqual(custom["uOutput"], "U3_ANTIALIASING")
        self.assertEqual(custom["uValue"], 3.5)
        self.assertTrue(custom["governing"])
        self.assertEqual(result["governingReactionForce"]["component"], "RF3_ANTIALIASING")

        # No slow inventory/field-output data is produced.
        self.assertNotIn("totalNodes", result)
        self.assertNotIn("totalElements", result)
        self.assertNotIn("displacementAtGoverningLoad", result)
        self.assertNotIn("steps", result)

    def test_missing_displacement_history_leaves_u_columns_empty(self):
        import sys
        import types

        class Output:
            def __init__(self, data):
                self.data = data

        class Region:
            historyOutputs = {"RF1": Output([(0.0, 0.0), (1.0, 12.0)])}

        class Step:
            historyRegions = {"RP": Region()}

        class Odb:
            steps = {"Step-1": Step()}
            def close(self):
                pass

        fake = types.ModuleType("odbAccess")
        fake.openOdb = lambda path, readOnly=True: Odb()
        old = sys.modules.get("odbAccess")
        sys.modules["odbAccess"] = fake
        try:
            namespace = {"__name__": "winux_remote_test_missing_u"}
            exec(compile(odb_check.ODB_CHECK_SCRIPT, "remote.py", "exec"), namespace)
            result = namespace["inspect_odb"]("/tmp/no-u.odb")
        finally:
            if old is None:
                sys.modules.pop("odbAccess", None)
            else:
                sys.modules["odbAccess"] = old

        row = result["loadDisplacementRows"][0]
        self.assertEqual(row["rfOutput"], "RF1")
        self.assertIsNone(row["uOutput"])
        self.assertIsNone(row["uValue"])

    def test_delimited_json_is_parsed_from_abaqus_noise(self):
        output = "Abaqus banner\n{}\n{{\"error\": null, \"odb\": \"x.odb\"}}\n{}\nDone".format(
            odb_check.JSON_BEGIN, odb_check.JSON_END)
        payload = odb_check.parse_odb_check_output(output)
        self.assertEqual(payload["odb"], "x.odb")

    def test_extractor_error_becomes_runtime_error(self):
        output = "{}\n{{\"error\": \"bad odb\"}}\n{}".format(
            odb_check.JSON_BEGIN, odb_check.JSON_END)
        with self.assertRaisesRegex(RuntimeError, "bad odb"):
            odb_check.parse_odb_check_output(output)


    def test_local_checker_runs_configured_abaqus_and_returns_shared_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            odb_path = Path(tmp) / "local sample.odb"
            odb_path.write_bytes(b"odb")
            payload = (
                "Abaqus banner\n{}\n"
                "{{\"error\": null, \"odb\": \"local sample.odb\", "
                "\"loadDisplacementRows\": []}}\n{}"
            ).format(odb_check.JSON_BEGIN, odb_check.JSON_END)
            completed = mock.Mock(returncode=0, stdout=payload, stderr="")

            with mock.patch.object(odb_check.subprocess, "run", return_value=completed) as run:
                result = odb_check.check_local_odb(
                    odb_path, abaqus_commands=["abq2026"], timeout=12)

            self.assertEqual(result["odb"], "local sample.odb")
            self.assertEqual(result["source"], "local")
            self.assertEqual(result["abaqusCommand"], "abq2026")
            self.assertEqual(result["fileSize"], 3)
            command = run.call_args.args[0]
            self.assertIn("python", command if odb_check.os.name != "nt" else command[-1])
            self.assertIn(str(odb_path), command if odb_check.os.name != "nt" else command[-1])

    def test_local_checker_falls_back_when_launcher_returns_no_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            odb_path = Path(tmp) / "fallback.odb"
            odb_path.write_bytes(b"odb")
            missing = mock.Mock(returncode=1, stdout="", stderr="not found")
            payload = "{}\n{{\"error\": null, \"odb\": \"fallback.odb\"}}\n{}".format(
                odb_check.JSON_BEGIN, odb_check.JSON_END)
            success = mock.Mock(returncode=0, stdout=payload, stderr="")

            with mock.patch.object(
                    odb_check.subprocess, "run", side_effect=[missing, success]) as run:
                result = odb_check.check_local_odb(
                    odb_path, abaqus_commands=["abq2026", "abq2025"])

            self.assertEqual(run.call_count, 2)
            self.assertEqual(result["abaqusCommand"], "abq2025")


class ODBIntegrationArchitectureTests(unittest.TestCase):
    def test_context_menu_has_local_and_server_check_odb_action(self):
        source = FILE_PANEL.read_text(encoding="utf-8")
        self.assertIn('"id": "check_odb_local"', source)
        self.assertIn('"label": "Check ODB"', source)
        self.assertIn('"action": "check_odb"', source)
        self.assertIn('endswith(".odb")', source)
        self.assertIn('set_context_menu_item_enabled(', source)

    def test_job_viewer_has_check_odb_submenu(self):
        source = JOBS_VIEW.read_text(encoding="utf-8")
        self.assertIn('"label": "Check ODB"', source)
        self.assertIn('"action": "job_check_odb"', source)
        self.assertIn('"action": "job_extract_odb"', source)
        self.assertIn('"job_check_odb", "job_extract_odb"', source)

    def test_job_viewer_odb_actions_resolve_output_without_server_selection(self):
        facade = CONTROLLER.read_text(encoding="utf-8")
        source = JOB_PLOT_CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("def _job_odb_command", facade)
        self.assertIn("return self._job_plots.odb_command(action, values)", facade)
        self.assertIn("self.server.find_job_output_file(", source)
        self.assertIn('extension=".odb"', source)
        self.assertIn("self.app.check_odb(self.view.right, [path])", source)
        self.assertIn("self.app.extract_odb(self.view.right, [path])", source)
        self.assertIn('key=("job-odb-resolve", action, job_id)', source)

    def test_controller_uses_isolated_analysis_lane(self):
        source = (ROOT / "WinUx" / "controllers" / "odb_analysis.py").read_text(encoding="utf-8")
        app_source = (ROOT / "WinUx" / "controller.py").read_text(encoding="utf-8")
        self.assertIn('name="winux-analysis"', app_source)
        self.assertIn('self.app._submit_analysis(', source)
        self.assertIn('self.server.check_odb(', source)
        self.assertIn('check_local_odb(', source)
        self.assertIn('panel_id not in ("local", "server")', source)
        self.assertIn('self.view.show_odb_check(result)', source)

    def test_resolver_falls_back_when_abq2026_probe_fails(self):
        calls = []
        original = SSHServerModel._exec_client

        def fake_exec(_client, command, timeout=None):
            calls.append((command, timeout))
            if "abq2026 python" in command:
                return 127, "", "abq2026 failed"
            if "abq2025 python" in command:
                return 0, "__WINUX_ABAQUS_PYTHON_OK__", ""
            return 127, "", "not found"

        try:
            SSHServerModel._exec_client = staticmethod(fake_exec)
            command = SSHServerModel._resolve_abaqus_executable_on(
                object(), ["abq2026", "abq2025"])
        finally:
            SSHServerModel._exec_client = original

        self.assertEqual(command, "abq2025")
        self.assertGreaterEqual(len(calls), 2)
        self.assertIn("bash -lc", calls[0][0])

    def test_odb_compatibility_resolver_falls_back_to_release_that_opens_file(self):
        calls = []
        original = SSHServerModel._exec_client

        def fake_exec(_client, command, timeout=None):
            calls.append((command, timeout))
            if "abq2026 python" in command:
                return 1, "", "ODB was created by a previous release"
            if "abq2025 python" in command:
                return 1, "", "ODB was created by a previous release"
            if "abq2023 python" in command:
                return 0, "__WINUX_ODB_RELEASE_OK__", ""
            return 127, "", "not found"

        model = SSHServerModel()
        model.host = "cluster"
        model.username = "tester"
        try:
            SSHServerModel._exec_client = staticmethod(fake_exec)
            command = model._resolve_abaqus_for_odb_on(
                object(), "/scratch/Test Job/job.odb",
                ["abq2026", "abq2025", "abq2023"])
        finally:
            SSHServerModel._exec_client = original

        self.assertEqual(command, "abq2023")
        self.assertEqual([
            next(name for name in ("abq2026", "abq2025", "abq2023")
                 if name + " python" in call[0])
            for call in calls[:3]
        ], ["abq2026", "abq2025", "abq2023"])
        self.assertIn("Test Job/job.odb", calls[-1][0])
        self.assertTrue(all(timeout == model.ABAQUS_PROBE_TIMEOUT_SECONDS
                            for _command, timeout in calls[:3]))

    def test_odb_compatibility_resolver_reuses_successful_release_as_priority_hint(self):
        calls = []
        original = SSHServerModel._exec_client

        def fake_exec(_client, command, timeout=None):
            calls.append(command)
            if "abq2023 python" in command:
                return 0, "__WINUX_ODB_RELEASE_OK__", ""
            return 1, "", "release mismatch"

        model = SSHServerModel()
        model.host = "cluster"
        model.username = "tester"
        try:
            SSHServerModel._exec_client = staticmethod(fake_exec)
            first = model._resolve_abaqus_for_odb_on(
                object(), "/scratch/job.odb", ["abq2026", "abq2023"])
            calls[:] = []
            second = model._resolve_abaqus_for_odb_on(
                object(), "/scratch/job.odb", ["abq2026", "abq2023"])
        finally:
            SSHServerModel._exec_client = original

        self.assertEqual(first, "abq2023")
        self.assertEqual(second, "abq2023")
        self.assertTrue(calls[0].find("abq2023 python") >= 0)

    def test_server_odb_tools_probe_the_real_database_for_release_compatibility(self):
        source = REMOTE_ODB.read_text(encoding="utf-8")
        facade = SERVER.read_text(encoding="utf-8")
        self.assertIn("RemoteODBMixin", facade)
        self.assertIn("def _resolve_abaqus_for_odb_on", source)
        self.assertIn("odb=openOdb(path=sys.argv[1], readOnly=True)", source)
        self.assertIn("Detecting compatible Abaqus release", source)
        self.assertGreaterEqual(
            source.count("self._resolve_abaqus_for_odb_on("), 4)

    def test_server_uses_shared_transport_channels_for_odb_analysis(self):
        facade = SERVER.read_text(encoding="utf-8")
        source = REMOTE_ODB.read_text(encoding="utf-8")
        self.assertIn("def _auxiliary_session", facade)
        self.assertIn("_SharedTransportClient", facade)
        self.assertIn("with self._auxiliary_session()", source)
        self.assertNotIn("AUXILIARY_CONNECT_MIN_GAP_SECONDS", facade)
        self.assertIn("parse_odb_check_output", source)

    def test_server_prefers_abq2026_and_probes_odbaccess_in_login_shell(self):
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn('range(2026, 2017, -1)', source)
        self.assertIn('"bash -lc {}"', source)
        self.assertIn('from odbAccess import openOdb', source)
        self.assertIn('ABAQUS_PROBE_TIMEOUT_SECONDS', source)
        self.assertIn('Settings > Abaqus ', source)
        self.assertIn('Versions > Default command.', source)

    def test_controller_uses_preference_order_for_check_odb(self):
        source = (ROOT / "WinUx" / "controllers" / "odb_analysis.py").read_text(encoding="utf-8")
        self.assertIn('AbaqusVersionPreferences().ordered_commands()', source)

    def test_odb_result_window_routes_to_current_floating_adapter(self):
        source = DIALOG.read_text(encoding="utf-8")
        self.assertIn("from .floating_adapters import ODBCheckDialog", source)


if __name__ == "__main__":
    unittest.main()
