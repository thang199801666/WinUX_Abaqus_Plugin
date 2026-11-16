from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from WinUx.controllers.odb.analysis import OdbAnalysisController


class _Context:
    def __init__(self, app, remote=False):
        self.connection = "conn"
        self.remote = remote
    def check(self):
        return None
    def current(self):
        return True


class OdbExtractStartupTests(unittest.TestCase):
    def make_controller(self):
        status = Mock()
        panel = SimpleNamespace(panel_id="server", status=status)
        dialog = Mock()
        dialog.winfo_exists.return_value = True
        view = SimpleNamespace(
            show_odb_extract=Mock(return_value=dialog),
            show_error=Mock(), show_message=Mock(),
        )
        server = SimpleNamespace(
            normalize=lambda value: Path(str(value)),
            list_odb_history_outputs=Mock(return_value={
                "historyOutputs": [{"id": "H1", "points": 3}],
            }),
        )
        app = SimpleNamespace(
            _closing=False, view=view, server=server,
            _ensure_server_online=lambda: True,
            _submit_analysis=Mock(), _analysis_tasks=None,
        )
        controller = OdbAnalysisController(app)
        app._odb_extract_catalog_ready = controller._odb_extract_catalog_ready
        app._odb_extract_failed = controller._odb_extract_failed
        app._extract_odb_selected = Mock()
        return controller, app, panel, dialog

    def test_dialog_is_published_before_catalog_worker_runs(self):
        controller, app, panel, dialog = self.make_controller()
        captured = {}
        def submit(_submit, _tasks, _name, worker, completed, **kwargs):
            captured["worker"] = worker
            captured["completed"] = completed
            # Intentionally do not run worker here: opening the dialog must not
            # depend on Abaqus catalog completion.
            return object()
        with patch("WinUx.controllers.odb.analysis.OperationContext", _Context), \
             patch("WinUx.controllers.odb.analysis.submit_with_completion", side_effect=submit):
            controller.extract_odb(panel, ["/remote/sample.odb"])
        app.view.show_odb_extract.assert_called_once()
        payload = app.view.show_odb_extract.call_args.args[0]
        self.assertTrue(payload["loading"])
        self.assertEqual(payload["historyOutputs"], [])
        self.assertIn("worker", captured)
        self.assertFalse(app.server.list_odb_history_outputs.called)

    def test_catalog_completion_updates_existing_dialog_in_place(self):
        controller, app, panel, dialog = self.make_controller()
        catalog = {"historyOutputs": [{"id": "H1", "points": 3}]}
        controller._odb_extract_catalog_ready(panel, Path("sample.odb"), catalog, dialog=dialog)
        dialog.set_catalog.assert_called_once_with({
            "historyOutputs": [{"id": "H1", "points": 3}],
            "sessionKey": "sample.odb",
        })
        self.assertFalse(app.view.show_message.called)
        self.assertFalse(app.view.show_odb_extract.called)

    def test_empty_and_error_states_stay_in_existing_dialog(self):
        controller, app, panel, dialog = self.make_controller()
        controller._odb_extract_catalog_ready(panel, Path("sample.odb"), {"historyOutputs": []}, dialog=dialog)
        dialog.set_catalog.assert_called_once()
        self.assertIn("No History Output", dialog.set_catalog.call_args.kwargs["message"])
        controller._odb_extract_failed(panel, "reader failed", dialog=dialog)
        dialog.set_error.assert_called_once_with("reader failed")
        self.assertFalse(app.view.show_error.called)


if __name__ == "__main__":
    unittest.main(verbosity=2)

class OdbExtractFacadeForwardingTests(unittest.TestCase):
    def make_app(self):
        from WinUx.app.facades.analysis import AnalysisFacadeMixin
        controller = Mock()
        class _App(AnalysisFacadeMixin):
            def _odb_analysis_controller(self_inner):
                return controller
        return _App(), controller

    def test_catalog_ready_forwards_dialog_keyword(self):
        app, controller = self.make_app()
        panel = object()
        path = Path("sample.odb")
        catalog = {"historyOutputs": [{"id": "H1"}]}
        dialog = object()
        app._odb_extract_catalog_ready(panel, path, catalog, dialog=dialog)
        controller._odb_extract_catalog_ready.assert_called_once_with(
            panel, path, catalog, dialog=dialog)

    def test_extract_failed_forwards_dialog_keyword(self):
        app, controller = self.make_app()
        panel = object()
        dialog = object()
        app._odb_extract_failed(panel, "reader failed", dialog=dialog)
        controller._odb_extract_failed.assert_called_once_with(
            panel, "reader failed", dialog=dialog)


class OdbExtractDialogHostContractTests(unittest.TestCase):
    def test_inprocess_form_exposes_async_catalog_api(self):
        from WinUx.dialogs.odb.odb_extract_form import ODBExtractDialog
        self.assertTrue(callable(getattr(ODBExtractDialog, "set_catalog", None)))
        self.assertTrue(callable(getattr(ODBExtractDialog, "set_error", None)))

    def test_public_catalog_api_delegates_to_shared_mutator(self):
        from WinUx.dialogs.odb.odb_extract_form import ODBExtractDialog
        dialog = object.__new__(ODBExtractDialog)
        dialog._set_catalog = Mock()
        catalog = {"historyOutputs": [{"id": "H1"}]}
        dialog.set_catalog(catalog, "ready")
        dialog._set_catalog.assert_called_once_with(catalog, "ready")
        dialog._set_catalog.reset_mock()
        dialog.set_error("reader failed")
        dialog._set_catalog.assert_called_once_with({}, "reader failed")

class OdbExtractFastPathTests(unittest.TestCase):
    def make_controller(self):
        status = Mock()
        panel = SimpleNamespace(panel_id="server", status=status)
        view = SimpleNamespace(show_odb_xy_results=Mock(), show_error=Mock(), show_message=Mock())
        server = SimpleNamespace(extract_odb_history_data=Mock())
        app = SimpleNamespace(
            _closing=False, view=view, server=server, _submit_analysis=Mock(),
            _analysis_tasks=None,
        )
        controller = OdbAnalysisController(app)
        app._odb_extract_succeeded = controller._odb_extract_succeeded
        app._odb_extract_failed = controller._odb_extract_failed
        return controller, app, panel

    @staticmethod
    def _item(item_id, values, output):
        return {
            "id": item_id, "step": "Step-1", "historyRegion": "Region-1",
            "output": output, "displayName": output, "cachedPoints": values,
        }

    def test_all_cached_histories_skip_second_abaqus_extract(self):
        controller, app, panel = self.make_controller()
        x = self._item("HX", [[0.0, 0.0], [1.0, 2.0]], "U2")
        y = self._item("HY", [[0.0, 0.0], [1.0, 4.0]], "RF2")
        selection = {"x": [x], "y": [y], "reverse": "As is", "abaqusCommand": "abq2026"}
        captured = {}
        def submit(_submit, _tasks, _name, worker, completed, **kwargs):
            captured["result"] = worker()
            return object()
        with patch("WinUx.controllers.odb.analysis.OperationContext", _Context), \
             patch("WinUx.controllers.odb.analysis.submit_with_completion", side_effect=submit):
            controller._extract_odb_selected(panel, Path("sample.odb"), selection)
        self.assertFalse(app.server.extract_odb_history_data.called)
        self.assertTrue(captured["result"]["cacheHit"])
        self.assertEqual(captured["result"]["curves"][0]["points"], [[0.0, 0.0], [2.0, 4.0]])

    def test_partial_cache_extracts_only_missing_histories(self):
        controller, app, panel = self.make_controller()
        x = self._item("HX", [[0.0, 0.0], [1.0, 2.0]], "U2")
        y = {"id": "HY", "step": "Step-1", "historyRegion": "Region-1",
             "output": "RF2", "displayName": "RF2"}
        app.server.extract_odb_history_data.return_value = {
            "odb": "sample.odb", "path": "sample.odb", "abaqusCommand": "abq2026",
            "analysisSeconds": 1.0,
            "series": [{"id": "HY", "points": [[0.0, 0.0], [1.0, 4.0]]}],
        }
        selection = {"x": [x], "y": [y], "reverse": "As is", "abaqusCommand": "abq2026"}
        def submit(_submit, _tasks, _name, worker, completed, **kwargs):
            worker()
            return object()
        with patch("WinUx.controllers.odb.analysis.OperationContext", _Context), \
             patch("WinUx.controllers.odb.analysis.submit_with_completion", side_effect=submit):
            controller._extract_odb_selected(panel, Path("sample.odb"), selection)
        app.server.extract_odb_history_data.assert_called_once()
        sent = app.server.extract_odb_history_data.call_args.args[1]
        self.assertEqual([item["id"] for item in sent], ["HY"])
        self.assertEqual(app.server.extract_odb_history_data.call_args.kwargs["abaqus_command"], "abq2026")


    def test_odb_extract_tables_use_stable_native_qtable_style(self):
        source = (ROOT / "WinUx" / "dialogs" / "odb" / "odb_extract_form.py").read_text(encoding="utf-8")
        self.assertNotIn('class _ODBQtTable(QtTable)', source)
        self.assertNotIn('_presentation_header_row', source)
        self.assertIn('self.history = QtTable', source)
        self.assertIn('row_height=22', source)
        self.assertIn('self.history.setColumnWidth("1", 72)', source)
        self.assertIn('def _center_native_header', source)
        self.assertIn('def _history_rows', source)
        self.assertIn('self.axes[axis] = QtTable', source)
        self.assertIn('"Extract ODB History Data", 570, 585', source)

    def test_result_dialog_uses_compact_initial_geometry(self):
        source = (ROOT / "WinUx" / "dialogs" / "odb" / "odb_extract_form.py").read_text(encoding="utf-8")
        self.assertIn('"Extracted ODB Data", 455, 510', source)



class OdbCatalogAtomicCommitTests(unittest.TestCase):
    def test_async_catalog_rows_are_hidden_until_native_population_finishes(self):
        from WinUx.dialogs.odb import odb_extract_form as form
        dialog = object.__new__(form.ODBExtractDialog)
        dialog._items = [
            {"id": "H1", "displayName": "One", "points": 3},
            {"id": "H2", "displayName": "Two", "points": 4},
        ]
        dialog.history = SimpleNamespace(tag=101, set_rows=Mock())
        dialog._refresh_history_tooltips = Mock()
        events = []

        def configure(tag, **kwargs):
            events.append(("show", kwargs.get("show")))

        def set_rows(rows):
            events.append(("rows", len(rows)))

        dialog.history.set_rows.side_effect = set_rows
        fake_dpg = SimpleNamespace(
            does_item_exist=lambda tag: True,
            configure_item=configure,
        )
        with patch.object(form, "dpg", fake_dpg):
            dialog._replace_history_rows_atomic()

        self.assertEqual(events, [("show", False), ("rows", 2), ("show", True)])
        dialog._refresh_history_tooltips.assert_called_once_with()


class OdbCatalogCacheContractTests(unittest.TestCase):
    def test_remote_catalog_has_bounded_small_history_cache(self):
        from WinUx.services.odb.extract import ODB_EXTRACT_SCRIPT
        self.assertIn('CACHE_MAX_POINTS = 20000', ODB_EXTRACT_SCRIPT)
        self.assertIn('CACHE_MAX_POINTS_PER_SERIES = 2500', ODB_EXTRACT_SCRIPT)
        self.assertIn('row["cachedPoints"] = cached', ODB_EXTRACT_SCRIPT)


class OdbExtractSessionChoiceTests(unittest.TestCase):
    def setUp(self):
        from WinUx.dialogs.odb import odb_extract_form as form
        form._ODB_EXTRACT_SESSION_CHOICES.clear()
        self.form = form

    def _dialog(self, key, item_ids=("A", "B", "C"), loading=False):
        dialog = object.__new__(self.form.ODBExtractDialog)
        dialog._session_key = key
        dialog._loading = bool(loading)
        dialog._items_by_id = {item_id: {"id": item_id} for item_id in item_ids}
        dialog._x_ids = []
        dialog._y_ids = []
        dialog.REVERSE_OPTIONS = self.form.ODBExtractDialog.REVERSE_OPTIONS
        dialog.reverse = 100
        dialog.control_value = lambda tag: getattr(dialog, "_reverse_value", "As is")
        dialog.set_control_value = lambda tag, value: setattr(dialog, "_reverse_value", value)
        dialog._reverse_value = "As is"
        return dialog

    def test_same_odb_restores_x_y_and_combine_choice(self):
        first = self._dialog("/run/a.odb")
        first._x_ids[:] = ["A", "C"]
        first._y_ids[:] = ["B"]
        first._reverse_value = "Reverse Y"
        first._remember_session_choices()

        reopened = self._dialog("/run/a.odb")
        reopened._restore_session_choices()
        self.assertEqual(reopened._x_ids, ["A", "C"])
        self.assertEqual(reopened._y_ids, ["B"])
        self.assertEqual(reopened._reverse_value, "Reverse Y")

    def test_different_odb_does_not_reuse_another_odb_choices(self):
        first = self._dialog("/run/a.odb")
        first._x_ids[:] = ["A"]
        first._y_ids[:] = ["B"]
        first._reverse_value = "Reverse Both"
        first._remember_session_choices()

        other = self._dialog("/run/b.odb")
        other._restore_session_choices()
        self.assertEqual(other._x_ids, [])
        self.assertEqual(other._y_ids, [])
        self.assertEqual(other._reverse_value, "As is")

    def test_loading_shell_does_not_erase_saved_choices(self):
        first = self._dialog("/run/a.odb")
        first._x_ids[:] = ["A"]
        first._y_ids[:] = ["B"]
        first._remember_session_choices()

        loading = self._dialog("/run/a.odb", item_ids=(), loading=True)
        loading._x_ids[:] = []
        loading._y_ids[:] = []
        loading._remember_session_choices()
        self.assertEqual(self.form._ODB_EXTRACT_SESSION_CHOICES["/run/a.odb"]["x_ids"], ["A"])
        self.assertEqual(self.form._ODB_EXTRACT_SESSION_CHOICES["/run/a.odb"]["y_ids"], ["B"])

    def test_controller_supplies_stable_session_key_before_catalog_finishes(self):
        source = (ROOT / "WinUx" / "controllers" / "odb" / "analysis.py").read_text(encoding="utf-8")
        self.assertIn('"sessionKey": str(path)', source)
        self.assertIn('catalog.setdefault("sessionKey", str(path))', source)

class OdbExtractLocalParityTests(unittest.TestCase):
    def make_controller(self):
        status = Mock()
        panel = SimpleNamespace(panel_id="local", status=status)
        dialog = Mock()
        dialog.winfo_exists.return_value = True
        view = SimpleNamespace(
            show_odb_extract=Mock(return_value=dialog),
            show_error=Mock(), show_message=Mock(), show_odb_xy_results=Mock(),
        )
        server = SimpleNamespace(
            ODB_CHECK_TIMEOUT_SECONDS=600.0,
            normalize=lambda value: Path(str(value)),
            list_odb_history_outputs=Mock(),
            extract_odb_history_data=Mock(),
        )
        app = SimpleNamespace(
            _closing=False, view=view, server=server,
            _ensure_server_online=Mock(return_value=False),
            _submit_analysis=Mock(), _analysis_tasks=None,
        )
        controller = OdbAnalysisController(app)
        app._odb_extract_catalog_ready = controller._odb_extract_catalog_ready
        app._odb_extract_failed = controller._odb_extract_failed
        app._extract_odb_selected = controller._extract_odb_selected
        app._odb_extract_succeeded = controller._odb_extract_succeeded
        return controller, app, panel, dialog

    def test_local_catalog_does_not_require_server_and_uses_local_helper(self):
        controller, app, panel, dialog = self.make_controller()
        captured = {}
        local_catalog = {"historyOutputs": [{"id": "H1", "points": 2}], "source": "local"}
        def submit(_submit, _tasks, _name, worker, completed, **kwargs):
            captured["result"] = worker()
            return object()
        with patch("WinUx.controllers.odb.analysis.OperationContext", _Context), \
             patch("WinUx.controllers.odb.analysis.submit_with_completion", side_effect=submit), \
             patch("WinUx.controllers.odb.analysis.list_local_odb_history_outputs", return_value=local_catalog) as local_read, \
             patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.is_file", return_value=True):
            controller.extract_odb(panel, ["C:/work/sample.odb"])
        app._ensure_server_online.assert_not_called()
        self.assertFalse(app.server.list_odb_history_outputs.called)
        local_read.assert_called_once()
        self.assertEqual(captured["result"], local_catalog)
        app.view.show_odb_extract.assert_called_once()

    def test_local_partial_cache_uses_local_extract_not_server(self):
        controller, app, panel, _dialog = self.make_controller()
        x = {"id": "HX", "step": "Step-1", "historyRegion": "R", "output": "U2",
             "displayName": "U2", "cachedPoints": [[0.0, 0.0], [1.0, 1.0]]}
        y = {"id": "HY", "step": "Step-1", "historyRegion": "R", "output": "RF2",
             "displayName": "RF2"}
        local_result = {
            "odb": "sample.odb", "path": "C:/work/sample.odb", "abaqusCommand": "abq2026",
            "series": [{"id": "HY", "points": [[0.0, 0.0], [1.0, 2.0]]}],
        }
        selection = {"x": [x], "y": [y], "reverse": "As is", "abaqusCommand": "abq2026"}
        def submit(_submit, _tasks, _name, worker, completed, **kwargs):
            captured = worker()
            self.assertEqual(captured["curves"][0]["points"], [[0.0, 0.0], [1.0, 2.0]])
            return object()
        with patch("WinUx.controllers.odb.analysis.OperationContext", _Context), \
             patch("WinUx.controllers.odb.analysis.submit_with_completion", side_effect=submit), \
             patch("WinUx.controllers.odb.analysis.extract_local_odb_history_data", return_value=local_result) as local_extract:
            controller._extract_odb_selected(panel, Path("C:/work/sample.odb"), selection)
        local_extract.assert_called_once()
        self.assertFalse(app.server.extract_odb_history_data.called)

class LocalOdbFastCatalogContractTests(unittest.TestCase):
    def test_local_catalog_uses_metadata_first_fast_mode(self):
        from WinUx.services.odb import extract as odb_extract
        with patch.object(odb_extract, "_run_local_odb_extract_mode", return_value={"historyOutputs": []}) as run:
            odb_extract.list_local_odb_history_outputs(Path("C:/work/sample.odb"), abaqus_commands=["abq2026"])
        self.assertEqual(run.call_args.args[1], "catalog-fast")

    def test_helper_fast_catalog_keeps_counts_but_skips_cached_point_conversion(self):
        from WinUx.services.odb.extract import ODB_EXTRACT_SCRIPT
        self.assertIn('mode in ("catalog-fast", "catalog_fast")', ODB_EXTRACT_SCRIPT)
        self.assertIn('_catalog(odb, path, cache_points=False)', ODB_EXTRACT_SCRIPT)
        self.assertIn('payload["fastCatalog"] = True', ODB_EXTRACT_SCRIPT)

    def test_local_launcher_success_cache_is_session_only(self):
        from WinUx.services.odb import extract as odb_extract
        source = (ROOT / "WinUx" / "services" / "odb" / "extract.py").read_text(encoding="utf-8")
        self.assertIn("_LOCAL_LAST_GOOD_ABAQUS_COMMAND = None", source)
        self.assertIn("commands = [cached_command] +", source)
        self.assertNotIn("save_local_abaqus_command", source)
