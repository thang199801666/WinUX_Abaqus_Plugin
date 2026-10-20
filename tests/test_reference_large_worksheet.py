"""Saved XY data must not allocate a native editor for every point."""
import os
import unittest
from unittest.mock import Mock

import WinUx  # Select the application's ABI-matched bundled dependencies.
from WinUx.ui.components.reference_data_table import ReferenceDataTable


@unittest.skipUnless(os.name == "nt", "Native worksheet regression")
class LargeReferenceWorksheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import dearpygui.dearpygui as dpg
        cls.dpg = dpg
        dpg.create_context()
        dpg.configure_app(manual_callback_management=True)

    @classmethod
    def tearDownClass(cls):
        cls.dpg.destroy_context()

    def setUp(self):
        self.window = self.dpg.add_window()
        self.pending = []
        self.errors = Mock()
        self.sheet = ReferenceDataTable(
            self.window, lambda delay, callback, *args: self.pending.append((callback, args)), self.errors)

    def tearDown(self):
        self.sheet.delete()
        self.dpg.delete_item(self.window)
        self.errors.assert_not_called()

    def series(self, count=13873):
        return {"name": "Large test reference", "points": [[i, i * 2] for i in range(count)]}

    def drain_population(self):
        guard = 0
        while self.pending:
            callback, args = self.pending.pop(0)
            callback(*args)
            guard += 1
            self.assertLess(guard, 10000)

    def test_large_load_defers_native_rows_then_materializes_every_row(self):
        item = self.series()
        self.sheet.load_series([item])
        self.assertEqual(self.sheet.model.row_count, len(item["points"]))
        # Loading the model must not synchronously construct 13k native rows.
        self.assertLess(self.sheet._table_widget.rowCount(), len(item["points"]))
        self.assertTrue(self.pending)
        self.drain_population()
        self.assertEqual(self.sheet._table_widget.rowCount(), len(item["points"]))
        self.assertTrue(self.sheet.population_complete)
        self.assertEqual(self.sheet.to_series("Round trip")[0]["points"], item["points"])

    def test_page_edits_preserve_values_on_other_pages(self):
        item = self.series()
        self.sheet.load_series([item])
        self.drain_population()
        self.sheet.cells[0, 1].setText("777")
        self.sheet.show_page(13000)
        self.sheet.cells[13000, 1].setText("999")
        self.sheet.show_page(13872)
        self.sheet.cells[13872, 1].setText("123")
        self.sheet.show_page(0)
        result = self.sheet.to_series("Edited")[0]["points"]
        self.assertEqual(len(result), 13873)
        self.assertEqual(result[0], [0, 777])
        self.assertEqual(result[13000], [13000, 999])
        self.assertEqual(result[13872], [13872, 123])
        self.assertEqual(result[5000], item["points"][5000])
        # Delegate-style editing keeps only the active cell editor alive.
        self.assertLessEqual(len(self.sheet.cells), 1)

    def test_paste_crossing_page_boundary_does_not_truncate_data(self):
        self.sheet.load_series([self.series(1001)])
        self.drain_population()
        self.sheet.paste_text("9\t8\n7\t6", (49, 0))
        self.sheet.show_page(50)
        self.assertEqual(self.sheet.cells[50, 0].text(), "7")
        self.assertEqual(self.sheet.cells[50, 1].text(), "6")
        result = self.sheet.to_series("Pasted")[0]["points"]
        self.assertEqual(len(result), 1001)
        self.assertEqual(result[49:51], [[9, 8], [7, 6]])
        self.assertEqual(result[-1], [1000, 2000])


if __name__ == "__main__":
    unittest.main()
