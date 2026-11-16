"""Regression coverage for Reference Chart reduction/worksheet integration."""
import math
import unittest

from DearUIQt.themes.factories import worksheet_theme_spec
from DearUIQt.themes.spec import ThemeColor, ThemeStyle, ThemeTarget
from WinUx.dialogs.reference_chart_form import ReferenceChartDialog


class _TableStub:
    def __init__(self, points):
        self.points = [list(point) for point in points]

    def to_points(self):
        return [list(point) for point in self.points]

    def load_series(self, series):
        self.points = [list(point) for point in series[0]["points"]]


class ReferenceReductionUiContractTests(unittest.TestCase):
    def test_worksheet_theme_keeps_shared_scrollbar_roles(self):
        spec = worksheet_theme_spec()
        table = next(item for item in spec.components if item.target is ThemeTarget.TABLE)
        color_roles = {item.role for item in table.colors}
        style_roles = {item.role for item in table.styles}
        self.assertTrue({
            ThemeColor.SCROLLBAR_BACKGROUND,
            ThemeColor.SCROLLBAR_GRAB,
            ThemeColor.SCROLLBAR_GRAB_HOVERED,
            ThemeColor.SCROLLBAR_GRAB_ACTIVE,
        }.issubset(color_roles))
        self.assertTrue({
            ThemeStyle.SCROLLBAR_SIZE,
            ThemeStyle.SCROLLBAR_ROUNDING,
        }.issubset(style_roles))

    def test_reference_sheet_registers_native_table_with_shared_scroller(self):
        import inspect
        from WinUx.ui.components.reference_data_table import ReferenceDataTable
        source = inspect.getsource(ReferenceDataTable._create_table)
        self.assertIn("register_scroll_surface", source)
        self.assertIn("viewport=self._frame.tag", source)

    def test_repeat_reduce_keeps_reducing_from_same_source(self):
        dialog = ReferenceChartDialog.__new__(ReferenceChartDialog)
        dialog._finished = False
        dialog._formula_mode = False
        points = [
            [index / 1000.0, math.sin(index / 80.0) * 0.1 + index / 1000.0]
            for index in range(1001)
        ]
        dialog.data_table = _TableStub(points)
        dialog._reduction_source_points = None
        dialog._reduction_applied_preset = None
        dialog._reduction_effective_tolerance = None
        dialog._reduction_pass_count = 0
        dialog._editor_dirty = False
        dialog.reduce_accuracy_combo = "combo"
        dialog.status = "status"
        values = {"combo": "Balanced (0.05%)", "status": ""}
        dialog.control_value = lambda item, default=None: values.get(item, default)
        dialog.set_control_value = lambda item, value: values.__setitem__(item, value)
        dialog._render_preview = lambda curves: True

        self.assertTrue(dialog._reduce_xy_samples())
        first_count = len(dialog.data_table.points)
        first_tolerance = dialog._reduction_effective_tolerance
        source_snapshot = [list(point) for point in dialog._reduction_source_points]
        self.assertLess(first_count, len(points))

        self.assertTrue(dialog._reduce_xy_samples())
        second_count = len(dialog.data_table.points)
        second_tolerance = dialog._reduction_effective_tolerance
        self.assertLessEqual(second_count, max(2, int(math.floor(first_count * 0.80))))
        self.assertGreater(second_tolerance, first_tolerance)
        self.assertEqual(dialog._reduction_source_points, source_snapshot)

        self.assertTrue(dialog._reduce_xy_samples())
        third_count = len(dialog.data_table.points)
        self.assertLessEqual(third_count, max(2, int(math.floor(second_count * 0.80))))
        self.assertGreater(dialog._reduction_effective_tolerance, second_tolerance)
        self.assertEqual(dialog._reduction_source_points, source_snapshot)
        self.assertIn("Reduce pass 3", values["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
