"""XLPP-backed Plot Digitizer export without requiring the Windows native module."""
from pathlib import Path
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from PIL import Image
from WinUx.plotdigitizer.core import DigitizerEngine
from WinUx.services.excel_export import export_plot_digitizer_xlsx


class FakeSheet:
    def __init__(self, name):
        self.name = name
        self.rows = []

    def append(self, row):
        self.rows.append(list(row))


class FakeWorkbook:
    last = None

    def __init__(self):
        self.sheets = {}
        self.saved = None
        FakeWorkbook.last = self

    def add_worksheet(self, name):
        sheet = FakeSheet(name)
        self.sheets[name] = sheet
        return sheet

    def save(self, path):
        self.saved = path


class PlotDigitizerXLPPExportTests(unittest.TestCase):
    def setUp(self):
        self.engine = DigitizerEngine()
        self.engine.apply_image(Image.new("RGB", (100, 100), "white"), "chart.png")
        for key, x, y, value in (("x1", 0, 0, 0), ("x2", 99, 0, 99),
                                 ("y1", 0, 0, 99), ("y2", 0, 99, 0)):
            self.engine.set_anchor(key, x, y, value)
        for point in ((30, 80), (10, 20), (20, 50)):
            self.engine.add_manual_point(*point)
        self.fake = types.SimpleNamespace(Workbook=FakeWorkbook)

    def export(self, *, sort_by=None, dataset_index=None, suffix=True):
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"xlpp": self.fake}):
            path = Path(directory) / ("points.xlsx" if suffix else "points")
            export_plot_digitizer_xlsx(self.engine, str(path), dataset_index, sort_by=sort_by)
            return FakeWorkbook.last

    def test_writes_xy_calibration_and_metadata_sheets(self):
        workbook = self.export()
        self.assertEqual(set(workbook.sheets), {"XY Data", "Calibration", "Metadata"})
        rows = workbook.sheets["XY Data"].rows
        self.assertEqual(rows[0], ["Dataset", "Index", "X", "Y", "PixelX", "PixelY", "Source"])
        self.assertEqual([round(row[2]) for row in rows[1:]], [30, 10, 20])
        self.assertTrue(all(row[-1] == "Manual" for row in rows[1:]))
        calibration = workbook.sheets["Calibration"].rows
        self.assertIn(["X scale", "Linear"], calibration)
        self.assertIn(["X1", 0.0, 0.0, 0.0], calibration)
        metadata = workbook.sheets["Metadata"].rows
        self.assertIn(["Active dataset", "Serie-1"], metadata)
        self.assertTrue(workbook.saved.endswith("points.xlsx"))

    def test_sort_scope_and_extension_match_csv_semantics(self):
        other = self.engine.add_dataset("Other")
        self.engine.set_active_dataset(other)
        self.engine.add_manual_point(8, 90)
        self.engine.add_manual_point(5, 10)
        workbook = self.export(sort_by="y", dataset_index=other, suffix=False)
        rows = workbook.sheets["XY Data"].rows[1:]
        self.assertEqual([row[0] for row in rows], ["Other", "Other"])
        self.assertEqual([round(row[2]) for row in rows], [8, 5])
        self.assertTrue(workbook.saved.endswith(".xlsx"))

    def test_invalid_sort_is_rejected_before_loading_xlpp(self):
        with patch("WinUx.services.excel_export._load_xlpp") as loader:
            with self.assertRaises(ValueError):
                export_plot_digitizer_xlsx(self.engine, "ignored.xlsx", sort_by="z")
            loader.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
