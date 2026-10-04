"""Regression coverage for selective ODB History Output extraction/combine."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "WinUx" / "services" / "odb_extract.py"
SERVER = ROOT / "WinUx" / "server_model.py"
REMOTE_ODB = ROOT / "WinUx" / "services" / "remote_odb.py"
CONTROLLER = ROOT / "WinUx" / "controller.py"
FILE_PANEL = ROOT / "WinUx" / "components" / "file_panel.py"
DIALOG = ROOT / "WinUx" / "dialogs" / "odb_extract_form.py"
CALLBACKS = ROOT / "WinUx" / "controllers" / "callbacks.py"
LISTVIEW = ROOT / "WinUx" / "components" / "explorer_context_menu.py"

SPEC = importlib.util.spec_from_file_location("winux_odb_extract", SERVICE)
odb_extract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(odb_extract)


class ODBExtractServiceTests(unittest.TestCase):
    def test_remote_script_is_history_only_and_has_catalog_extract_modes(self):
        script = odb_extract.build_remote_odb_extract_script()
        self.assertIn("from odbAccess import openOdb", script)
        self.assertIn('mode == "catalog"', script)
        self.assertIn('mode == "extract"', script)
        self.assertIn("step.historyRegions.items()", script)
        self.assertIn("region.historyOutputs.items()", script)
        self.assertNotIn("fieldOutputs", script)
        self.assertNotIn("rootAssembly", script)
        self.assertNotIn("step.frames", script)
        compile(script, "remote_odb_extract.py", "exec")
        self.assertNotIn('f"', script)

    def test_catalog_contains_all_history_output_metadata(self):
        class Output:
            def __init__(self, description, data):
                self.description = description
                self.data = data

        class Region:
            description = "Node FIXTURE-1.732 in NSET POINT-LOAD"
            historyOutputs = {
                "RF2_ANTIALIASING": Output(
                    "Reaction force (FILTERED): RF2_ANTIALIASING", [(0.0, 0.0)]),
                "U2_ANTIALIASING": Output(
                    "Spatial displacement (FILTERED): U2_ANTIALIASING", [(0.0, 0.0)]),
                "ALLAE": Output("Artificial strain energy: ALLAE for Whole Model", [(0.0, 1.0)]),
            }

        class Step:
            historyRegions = {"Node FIXTURE-1.732": Region()}

        class Odb:
            steps = {"Step-1": Step()}

        fake = types.ModuleType("odbAccess")
        fake.openOdb = lambda path, readOnly=True: Odb()
        old_module = sys.modules.get("odbAccess")
        sys.modules["odbAccess"] = fake
        try:
            ns = {"__name__": "winux_remote_test"}
            exec(compile(odb_extract.ODB_EXTRACT_SCRIPT, "remote.py", "exec"), ns)
            result = ns["_catalog"](Odb(), "/tmp/demo.odb")
        finally:
            if old_module is None:
                sys.modules.pop("odbAccess", None)
            else:
                sys.modules["odbAccess"] = old_module
        self.assertEqual(len(result["historyOutputs"]), 3)
        outputs = {row["output"] for row in result["historyOutputs"]}
        self.assertEqual(outputs, {"RF2_ANTIALIASING", "U2_ANTIALIASING", "ALLAE"})
        first = result["historyOutputs"][0]
        self.assertIn("description", first)
        self.assertIn("historyRegion", first)
        self.assertIn("regionDescription", first)
        self.assertIn("displayName", first)
        self.assertIn("RF2_ANTIALIASING", first["displayName"])
        self.assertIn("POINT-LOAD", first["displayName"])
        self.assertIn("points", first)

    def test_catalog_builds_abaqus_style_display_labels(self):
        script = odb_extract.build_remote_odb_extract_script()
        self.assertIn("_history_display_name", script)
        self.assertIn("for Whole Model", script)
        self.assertIn("PI: %s Node %s", script)

    def test_extract_reads_only_requested_history_outputs(self):
        class Output:
            def __init__(self, description, data):
                self.description = description
                self.data = data

        class Region:
            historyOutputs = {
                "RF2": Output("RF2", [(0.0, 0.0), (1.0, 10.0)]),
                "U2": Output("U2", [(0.0, 0.0), (1.0, 2.0)]),
                "ALLAE": Output("ALLAE", [(0.0, 1.0), (1.0, 3.0)]),
            }

        class Step:
            historyRegions = {"RP": Region()}

        class Odb:
            steps = {"Step-1": Step()}

        request = {
            "items": [
                {"id": "H1", "step": "Step-1", "historyRegion": "RP", "output": "U2"},
                {"id": "H2", "step": "Step-1", "historyRegion": "RP", "output": "RF2"},
            ]
        }
        fake = types.ModuleType("odbAccess")
        fake.openOdb = lambda path, readOnly=True: Odb()
        old_module = sys.modules.get("odbAccess")
        sys.modules["odbAccess"] = fake
        try:
            ns = {"__name__": "winux_remote_test"}
            exec(compile(odb_extract.ODB_EXTRACT_SCRIPT, "remote.py", "exec"), ns)
            with tempfile.NamedTemporaryFile("w", delete=False) as stream:
                json.dump(request, stream)
                request_path = stream.name
            try:
                result = ns["_extract"](Odb(), "/tmp/demo.odb", request_path)
            finally:
                Path(request_path).unlink(missing_ok=True)
        finally:
            if old_module is None:
                sys.modules.pop("odbAccess", None)
            else:
                sys.modules["odbAccess"] = old_module
        self.assertEqual([row["output"] for row in result["series"]], ["U2", "RF2"])
        self.assertEqual(result["series"][0]["points"], [[0.0, 0.0], [1.0, 2.0]])
        self.assertNotIn("ALLAE", [row["output"] for row in result["series"]])

    def test_combine_matches_basic_abaqus_y_vs_y_semantics(self):
        x_series = {"points": [(1, 4), (2, 4), (3, 4), (4, 5), (5, 6)]}
        y_series = {"points": [(1, 9), (2, 8), (3, 7), (4, 6), (5, 4)]}
        self.assertEqual(
            odb_extract.combine_xy_series(x_series, y_series),
            [[4.0, 9.0], [4.0, 8.0], [4.0, 7.0], [5.0, 6.0], [6.0, 4.0]],
        )

    def test_combine_aligns_different_time_grids_by_interpolation_and_endpoint_extrapolation(self):
        x_series = {"points": [(0.0, 0.0), (2.0, 2.0)]}
        y_series = {"points": [(1.0, 10.0), (3.0, 30.0)]}
        result = odb_extract.combine_xy_series(x_series, y_series)
        self.assertEqual(result, [
            [0.0, 10.0],
            [1.0, 10.0],
            [2.0, 20.0],
            [2.0, 30.0],
        ])

    def test_reverse_modes_flip_only_requested_axis(self):
        x_series = {"points": [(0.0, 2.0)]}
        y_series = {"points": [(0.0, -3.0)]}
        self.assertEqual(
            odb_extract.combine_xy_series(x_series, y_series, "Reverse X"),
            [[-2.0, -3.0]],
        )
        self.assertEqual(
            odb_extract.combine_xy_series(x_series, y_series, "Reverse Y"),
            [[2.0, 3.0]],
        )
        self.assertEqual(
            odb_extract.combine_xy_series(x_series, y_series, "Reverse Both"),
            [[-2.0, 3.0]],
        )

    def test_cartesian_selection_creates_x1y1_x1y2_x2y1_x2y2(self):
        extracted = {
            "odb": "demo.odb",
            "series": [
                {"id": "x1", "points": [(0, 1)]},
                {"id": "x2", "points": [(0, 2)]},
                {"id": "y1", "points": [(0, 10)]},
                {"id": "y2", "points": [(0, 20)]},
            ],
        }
        selection = {
            "x": [{"id": "x1", "output": "X1"}, {"id": "x2", "output": "X2"}],
            "y": [{"id": "y1", "output": "Y1"}, {"id": "y2", "output": "Y2"}],
            "reverse": "As is",
        }
        result = odb_extract.build_combined_curves(extracted, selection)
        self.assertEqual(
            [curve["name"] for curve in result["curves"]],
            ["X1:Y1", "X1:Y2", "X2:Y1", "X2:Y2"],
        )


class ODBExtractArchitectureTests(unittest.TestCase):
    def test_check_odb_context_menu_is_grouped_into_quick_and_extract(self):
        source = FILE_PANEL.read_text(encoding="utf-8")
        self.assertIn('"id": "check_odb_group"', source)
        self.assertIn('"label": "Quick Check"', source)
        self.assertIn('"action": "check_odb"', source)
        self.assertIn('"label": "Extract Data"', source)
        self.assertIn('"action": "extract_odb"', source)

    def test_submenu_actions_can_be_logically_disabled(self):
        source = LISTVIEW.read_text(encoding="utf-8")
        self.assertIn("def _find_context_menu_action_spec", source)
        self.assertIn("item.get(\"children\") or []", source)

    def test_server_has_two_stage_selective_extraction(self):
        source = REMOTE_ODB.read_text(encoding="utf-8")
        facade = SERVER.read_text(encoding="utf-8")
        self.assertIn("RemoteODBMixin", facade)
        self.assertIn("def list_odb_history_outputs", source)
        self.assertIn("def extract_odb_history_data", source)
        self.assertIn("build_remote_odb_extract_script", source)
        self.assertIn("parse_odb_extract_output", source)
        self.assertIn("with self._auxiliary_session()", source)

    def test_controller_uses_analysis_lane_and_cartesian_combine(self):
        source = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("def extract_odb", source)
        source += (ROOT / "WinUx" / "controllers" / "odb_analysis.py").read_text(encoding="utf-8")
        self.assertIn("self.server.list_odb_history_outputs", source)
        self.assertIn("self.server.extract_odb_history_data", source)
        self.assertIn("build_combined_curves", source)
        self.assertIn("self.view.show_odb_extract", source)
        self.assertIn("self.view.show_odb_xy_results", source)

    def test_callback_contract_exposes_extract_odb(self):
        source = CALLBACKS.read_text(encoding="utf-8")
        self.assertIn('"extract_odb"', source)
        self.assertIn('controller.extract_odb', source)

    def test_native_selection_dialog_has_x_y_stacks_and_reverse_options(self):
        source = DIALOG.read_text(encoding="utf-8")
        self.assertIn("class ODBExtractDialog(QtDialog)", source)
        self.assertIn('for axis in ("x", "y")', source)
        self.assertIn('"Add to {}".format(axis.upper())', source)
        self.assertIn('"Remove {}".format(axis.upper())', source)
        self.assertIn('"Reverse X"', source)
        self.assertIn('"Reverse Y"', source)
        self.assertIn('"Reverse Both"', source)
        self.assertIn("len(self._x_ids) * len(self._y_ids)", source)

    def test_history_selector_uses_real_output_names_and_hides_step_column(self):
        source = DIALOG.read_text(encoding="utf-8")
        self.assertIn('("Output Variables", "Points")', source)
        self.assertNotIn('("Step",', source)
        self.assertIn("_item_label(item)", source)
        self.assertIn("self._items_by_id", source)

    def test_result_dialog_lazy_displays_one_combined_xy_table(self):
        source = DIALOG.read_text(encoding="utf-8")
        self.assertIn("class ODBXYResultDialog(QtDialog)", source)
        self.assertIn('QtTable(self.content, ("X", "Y")', source)
        self.assertIn("self._labels", source)
        self.assertIn("self._show_curve", source)

    def test_result_table_supports_excel_clipboard_and_multi_selection(self):
        source = DIALOG.read_text(encoding="utf-8")
        self.assertIn('QtTable(self.content, ("X", "Y"), height=-1, multiple=True)', source)
        self.assertIn('("Select All", self._select_all', source)
        self.assertIn('("Copy", self._copy_selected', source)
        self.assertIn("dpg.set_clipboard_text", source)
        self.assertIn('"\\t".join', source)
        self.assertIn('"\\r\\n".join', source)
        self.assertIn("self.table.selected", source)


if __name__ == "__main__":
    unittest.main()

    def test_result_table_is_compact_and_uses_plain_labels(self):
        source = DIALOG_PATH.read_text(encoding="utf-8")
        self.assertIn("COLUMN_WIDTH = 250", source)
        self.assertIn('stretch=False, anchor="e"', source)
        self.assertIn('text="X: {}"', source)
        self.assertIn('text="Y: {}"', source)
        self.assertNotIn(" — ", source)
        self.assertNotIn(" • ", source)
