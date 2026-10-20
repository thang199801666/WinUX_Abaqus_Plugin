"""Single-series X/Y worksheet and Excel paste semantics."""
import unittest

from WinUx.services.reference_charts import ReferenceTableModel


class ReferenceTableModelTests(unittest.TestCase):
    def test_sheet_is_fixed_to_one_xy_pair(self):
        table = ReferenceTableModel()
        table.paste("X\tY\n0\t1\n1\t2\n2\t3")
        self.assertEqual(table.pair_count, 1)
        self.assertTrue(all(len(row) == 2 for row in table.cells))
        self.assertEqual(table.to_series("Experiment")[0]["points"],
                         [[0, 1], [1, 2], [2, 3]])

    def test_paste_at_offset_preserves_other_cells_and_expands_rows(self):
        table = ReferenceTableModel(rows=1)
        table.paste("0\t1")
        table.paste("2\t3\n4\t5", row=1, column=0)
        self.assertEqual(table.row_count, 3)
        self.assertEqual(table.cells[0], ["0", "1"])
        self.assertEqual(table.to_series("Offset")[0]["points"],
                         [[0, 1], [2, 3], [4, 5]])

    def test_excel_headers_generic_headers_and_blank_trailing_cells_are_accepted(self):
        table = ReferenceTableModel()
        table.paste("Time\tForce\t\n0\t1\t\n1\t2\t")
        self.assertEqual(table.to_series("Measured")[0]["points"], [[0, 1], [1, 2]])

    def test_more_than_two_columns_are_rejected(self):
        table = ReferenceTableModel()
        with self.assertRaisesRegex(ValueError, "only two columns"):
            table.paste("0\t1\t2")
        with self.assertRaisesRegex(ValueError, "only two columns"):
            table.paste("0\t1", column=1)

    def test_missing_coordinate_reports_row(self):
        table = ReferenceTableModel()
        table.cells[2][1] = "4"
        with self.assertRaisesRegex(ValueError, "Row 3: X and Y"):
            table.to_series("Incomplete")

    def test_nonfinite_invalid_values_are_rejected_and_decimal_comma_excel_cells_work(self):
        for value in ("NaN", "inf", "bad"):
            table = ReferenceTableModel()
            table.paste("0\t" + value)
            with self.assertRaises(ValueError):
                table.to_series("Invalid")
        table = ReferenceTableModel()
        table.paste("X\tY\n0,5\t1,25\n1,5\t2,75")
        self.assertEqual(table.to_series("Locale")[0]["points"],
                         [[0.5, 1.25], [1.5, 2.75]])

    def test_loading_one_saved_series_and_copying_table_round_trip_points(self):
        saved = {"name": "Experiment A", "points": [[0, 1], [1, 2]]}
        table = ReferenceTableModel()
        table.load_series([saved])
        copied = ReferenceTableModel()
        copied.paste(table.clipboard_text())
        self.assertEqual(copied.to_series(saved["name"])[0]["points"], saved["points"])
        with self.assertRaisesRegex(ValueError, "one reference chart"):
            table.load_series([saved, saved])

    def test_clear_cell_row_and_all_keep_two_column_shape(self):
        table = ReferenceTableModel(rows=3)
        table.paste("0\t1\n2\t3\n4\t5")
        table.clear_cell(0, 1)
        self.assertEqual(table.cells[0], ["0", ""])
        table.clear_row(1)
        self.assertEqual(table.cells[1], ["", ""])
        table.clear()
        self.assertEqual(table.cells, [["", ""], ["", ""], ["", ""]])

    def test_empty_sheet_cannot_create_empty_reference(self):
        table = ReferenceTableModel()
        self.assertFalse(table.has_data())
        with self.assertRaisesRegex(ValueError, "Enter X/Y data"):
            table.to_series("Empty")


if __name__ == "__main__":
    unittest.main()
