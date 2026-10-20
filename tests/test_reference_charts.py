"""Parsing and persistence contracts for independent reference curves."""
import tempfile
import unittest
from unittest.mock import Mock, patch

from WinUx.services.reference_charts import ReferenceChartLibrary, parse_reference_text


class ReferenceChartParserTests(unittest.TestCase):
    def test_excel_table_imports_multiple_named_curves(self):
        series = parse_reference_text("Time\tExperiment A\tExperiment B\n0\t1\t3\n1\t2\t4")
        self.assertEqual([row["name"] for row in series], ["Experiment A", "Experiment B"])
        self.assertEqual(series[0]["points"], [[0, 1], [1, 2]])
        self.assertEqual(series[1]["points"], [[0, 3], [1, 4]])

    def test_headerless_csv_uses_supplied_name(self):
        series = parse_reference_text("0,1\n1,2", "Measured energy")
        self.assertEqual(series[0]["name"], "Measured energy")
        self.assertTrue(series[0]["enabled"])

    def test_named_blocks_can_have_different_x_values(self):
        series = parse_reference_text("[Curve A]\n0 1\n1 2\n\n[Curve B]\n0.5 3\n2.5 4")
        self.assertEqual([row["name"] for row in series], ["Curve A", "Curve B"])
        self.assertEqual(series[1]["points"], [[0.5, 3], [2.5, 4]])

    def test_scientific_notation_comments_and_quoted_csv_headers(self):
        series = parse_reference_text('# comment\nX,"Load, measured"\n0,1D-3\n1,2e-3')
        self.assertEqual(series[0]["name"], "Load, measured")
        self.assertEqual(series[0]["points"], [[0, 0.001], [1, 0.002]])

    def test_headerless_multiple_y_columns_get_distinct_names(self):
        series = parse_reference_text("0;1;2\n1;3;4", "Reference")
        self.assertEqual([row["name"] for row in series], ["Reference 1", "Reference 2"])

    def test_invalid_input_does_not_produce_partial_series(self):
        for text in ("", "0\n1", "0,1\n1,2,3", "0,NaN", "0,inf",
                     "0,1\n1,bad", "X,A,a\n0,1,2", "[Empty]",
                     "[A]\n0,1,2", "[A]\n0,1\n[A]\n1,2"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_reference_text(text)


class ReferenceChartPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = ReferenceChartLibrary(root=self.temp.name)

    def test_data_and_visibility_survive_new_library_instance(self):
        series = parse_reference_text("X,Curve A,Curve B\n0,1,3\n1,2,4")
        self.library.replace(series)
        self.library.set_enabled(series[0]["id"], False)
        reopened = ReferenceChartLibrary(root=self.temp.name)
        result = reopened.snapshot()
        self.assertEqual(result[0]["points"], [[0, 1], [1, 2]])
        self.assertFalse(result[0]["enabled"])
        self.assertTrue(result[1]["enabled"])
        self.assertEqual(result[0]["id"], series[0]["id"])

    def test_drafts_do_not_mutate_saved_library(self):
        self.library.replace(parse_reference_text("0,1", "Curve"))
        draft = self.library.snapshot()
        draft[0]["points"][0][1] = 99
        self.assertEqual(self.library.snapshot()[0]["points"], [[0, 1]])

    def test_failed_save_keeps_data_and_does_not_notify(self):
        self.library.replace(parse_reference_text("0,1", "Original"))
        before = self.library.snapshot()
        notified = Mock()
        self.library.subscribe(notified)
        with patch.object(self.library.store, "save", side_effect=OSError("Read-only profile")):
            with self.assertRaises(OSError):
                self.library.replace(parse_reference_text("0,2", "New curve"))
        self.assertEqual(self.library.snapshot(), before)
        notified.assert_not_called()

    def test_duplicate_names_or_ids_cannot_overwrite_library(self):
        series = parse_reference_text("0,1", "Curve")
        self.library.replace(series)
        with self.assertRaises(ValueError):
            self.library.replace(series + series)
        self.assertEqual(len(self.library.snapshot()), 1)

    def test_remove_all_and_unsubscribe_are_persistent(self):
        callback = Mock()
        self.library.subscribe(callback)
        self.library.replace(parse_reference_text("0,1"))
        callback.assert_called_once_with()
        self.library.unsubscribe(callback)
        self.library.replace([])
        callback.assert_called_once_with()
        self.assertEqual(ReferenceChartLibrary(root=self.temp.name).snapshot(), [])


if __name__ == "__main__":
    unittest.main()
