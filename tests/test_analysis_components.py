from pathlib import PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.controllers.odb_analysis import OdbAnalysisController
from WinUx.controllers.job_submission import JobSubmissionController
from WinUx.controllers.inp_analysis import InpAnalysisController
from WinUx.runtime.operation_context import OperationContext


def fixture():
    workers, callbacks, keys = [], [], []
    def submit(name, worker, **kwargs):
        workers.append(worker)
        keys.append(kwargs.get("key"))
        return SimpleNamespace(state="pending")
    panel = SimpleNamespace(panel_id="server", status=Mock(), selected_transfer_paths=lambda: [])
    app = SimpleNamespace(
        _closing=False, _connection_generation=1,
        server=SimpleNamespace(normalize=PurePosixPath, check_odb=Mock(return_value={"valid": True}),
                               extract_odb_history_data=Mock(return_value={}), submit_abaqus_job=Mock(return_value="submitted")),
        view=SimpleNamespace(winfo_exists=lambda: True, show_error=Mock(), show_odb_extract=Mock(),
                             after=lambda delay, cb, *args: callbacks.append((cb, args))),
        _ensure_server_online=lambda: True, _submit_analysis=submit, _submit_background=submit,
        _odb_check_succeeded=Mock(), _odb_check_failed=Mock(), _odb_extract_succeeded=Mock(), _odb_extract_failed=Mock(),
        _extract_odb_selected=Mock(), _refresh_jobs_now=Mock(),
        _schedule_execution_controller=lambda: SimpleNamespace(schedule_run=lambda *args: False),
    )
    return app, panel, workers, callbacks, keys


def drain(callbacks):
    while callbacks:
        callback, args = callbacks.pop(0)
        callback(*args)


class AnalysisTests(unittest.TestCase):
    def test_remote_context_rejects_old_session_and_closed_window_callbacks(self):
        app, _, _, callbacks, _ = fixture()
        context = OperationContext(app, remote=True)
        callback = Mock()
        context.post(0, callback, "result")
        app._connection_generation = 2
        drain(callbacks)
        callback.assert_not_called()
        with self.assertRaises(RuntimeError):
            context.check()

    def test_local_context_survives_remote_reconnect(self):
        app, _, _, callbacks, _ = fixture()
        context = OperationContext(app)
        callback = Mock()
        context.post(0, callback)
        app._connection_generation = 2
        drain(callbacks)
        callback.assert_called_once()

    def test_queued_odb_check_does_not_query_replaced_session(self):
        app, panel, workers, callbacks, _ = fixture()
        analysis = OdbAnalysisController(app)
        analysis.check_odb(panel, ["/file.odb"])
        app._connection_generation = 2
        workers[0]()
        drain(callbacks)
        app.server.check_odb.assert_not_called()
        app._odb_check_succeeded.assert_not_called()

    def test_queued_result_does_not_publish_after_reconnect(self):
        app, panel, workers, callbacks, _ = fixture()
        analysis = OdbAnalysisController(app)
        analysis.check_odb(panel, ["/file.odb"])
        with patch("WinUx.controllers.odb_analysis.AbaqusVersionPreferences") as prefs:
            prefs.return_value.ordered_commands.return_value = ["abaqus"]
            workers[0]()
        app._connection_generation = 2
        drain(callbacks)
        app._odb_check_succeeded.assert_not_called()

    def test_rejection_reports_analysis_failure(self):
        app, panel, _, callbacks, _ = fixture()
        app._submit_analysis = lambda *args, **kwargs: SimpleNamespace(state="rejected")
        OdbAnalysisController(app).check_odb(panel, ["/file.odb"])
        drain(callbacks)
        app._odb_check_failed.assert_called_once_with(panel, "Background queue is full; try again")

    def test_distinct_xy_pairings_have_distinct_request_keys(self):
        app, panel, _, _, keys = fixture()
        analysis = OdbAnalysisController(app)
        a, b, c = ({"id": value} for value in "abc")
        analysis._extract_odb_selected(panel, PurePosixPath("/file.odb"), {"x": [a], "y": [b, c]})
        analysis._extract_odb_selected(panel, PurePosixPath("/file.odb"), {"x": [a, b], "y": [c]})
        self.assertNotEqual(keys[0], keys[1])

    def test_extraction_uses_frozen_selection(self):
        app, panel, workers, _, _ = fixture()
        selection = {"x": [{"id": "a"}], "y": [{"id": "b"}]}
        analysis = OdbAnalysisController(app)
        analysis._extract_odb_selected(panel, PurePosixPath("/file.odb"), selection)
        selection["x"][0]["id"] = "changed"
        with patch("WinUx.controllers.odb_analysis.AbaqusVersionPreferences"), \
             patch("WinUx.controllers.odb_analysis.build_combined_curves", return_value={}) as combine:
            workers[0]()
        self.assertEqual(combine.call_args.args[1]["x"][0]["id"], "a")

    def test_old_catalog_dialog_cannot_start_extraction_in_new_session(self):
        app, panel, _, _, _ = fixture()
        analysis = OdbAnalysisController(app)
        analysis._odb_extract_catalog_ready(panel, "/file.odb", {"historyOutputs": [{"id": "a"}]})
        selected = app.view.show_odb_extract.call_args.args[1]
        app._connection_generation = 2
        selected({"x": [{"id": "a"}], "y": [{"id": "a"}]})
        app._extract_odb_selected.assert_not_called()
        app.view.show_error.assert_called_once()

    def test_submission_uses_frozen_job_parameters(self):
        app, _, workers, callbacks, _ = fixture()
        dialog = Mock()
        jobs = [{"path": PurePosixPath("/file.inp"), "cpus": 4}]
        JobSubmissionController(app)._submit_jobs(dialog, jobs)
        jobs[0]["cpus"] = 99
        workers[0]()
        drain(callbacks)
        app.server.submit_abaqus_job.assert_called_once_with(path=PurePosixPath("/file.inp"), cpus=4)
        dialog.submission_finished.assert_called_once_with(1, 0)

    def test_submission_refuses_replaced_session(self):
        app, _, workers, _, _ = fixture()
        JobSubmissionController(app)._submit_jobs(Mock(), [{"path": "/file.inp"}])
        app._connection_generation = 2
        workers[0]()
        app.server.submit_abaqus_job.assert_not_called()

    def test_queued_callback_skips_destroyed_window(self):
        app, _, _, callbacks, _ = fixture()
        callback = Mock()
        OperationContext(app).post(0, callback)
        app.view.winfo_exists = lambda: False
        drain(callbacks)
        callback.assert_not_called()

    def test_queued_inp_check_skips_replaced_session(self):
        app, panel, workers, callbacks, _ = fixture()
        app.server.read_text = Mock()
        app._inp_check_failed = Mock()
        panel.selected_transfer_paths = lambda: [PurePosixPath("/file.inp")]
        InpAnalysisController(app).check_inp(panel)
        app._connection_generation = 2
        workers[0]()
        drain(callbacks)
        app.server.read_text.assert_not_called()
        app._inp_check_failed.assert_not_called()

    def test_inp_queue_rejection_reports_failure(self):
        app, panel, _, callbacks, _ = fixture()
        app._inp_check_failed = Mock()
        app._submit_background = lambda *args, **kwargs: SimpleNamespace(state="rejected")
        panel.selected_transfer_paths = lambda: [PurePosixPath("/file.inp")]
        InpAnalysisController(app).check_inp(panel)
        drain(callbacks)
        app._inp_check_failed.assert_called_once_with(panel, "Background queue is full; try again")
