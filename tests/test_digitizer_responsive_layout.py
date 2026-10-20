"""Portable layout policy checks; native rendering is tested separately."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


class DataGridResponsiveTests(unittest.TestCase):
    def view(self, height=300):
        return SimpleNamespace(
            winfo_exists=lambda: True, _active_tool="data",
            _data_grid_height=height, REGION_GAP=8,
            settings_panel="panel", export_data_button="export",
            _selected_point=None, _point_keys=lambda: [],
            result_grid=SimpleNamespace(setFixedHeight=Mock()),
        )

    def layout(self, view, panel_bottom, tail_bottom, scroll=0):
        bounds = {"panel": (0, 0, 280, panel_bottom),
                  "export": (0, tail_bottom - 26, 100, tail_bottom)}
        with patch("WinUx.plotdigitizer.ui.dialog.item_rect", side_effect=bounds.get), \
                patch("WinUx.plotdigitizer.ui.dialog.QRetainedItem") as retained:
            retained.return_value.verticalScrollValue.return_value = scroll
            PlotDigitizerDialog._layout_data_grid(view)

    def test_grid_grows_into_free_panel_space(self):
        view = self.view()
        self.layout(view, 800, 600)
        self.assertEqual(view._data_grid_height, 492)
        view.result_grid.setFixedHeight.assert_called_once_with(492)

    def test_grid_shrinks_instead_of_pushing_controls_off_screen(self):
        view = self.view()
        self.layout(view, 600, 670)
        self.assertEqual(view._data_grid_height, 222)

    def test_scroll_position_does_not_inflate_the_table(self):
        view = self.view()
        self.layout(view, 600, 620, scroll=50)
        self.assertEqual(view._data_grid_height, 222)

    def test_very_small_panels_preserve_a_readable_minimum(self):
        view = self.view()
        self.layout(view, 200, 600)
        self.assertEqual(view._data_grid_height, 100)

    def test_settled_layout_does_not_reconfigure(self):
        view = self.view()
        self.layout(view, 600, 592)
        view.result_grid.setFixedHeight.assert_not_called()

    def test_resize_requests_are_coalesced(self):
        view = SimpleNamespace(_active_tool="data", _data_layout_pending=False,
                               view=SimpleNamespace(after_render=Mock()),
                               _layout_data_grid=Mock())
        PlotDigitizerDialog._schedule_data_layout(view)
        PlotDigitizerDialog._schedule_data_layout(view)
        view.view.after_render.assert_called_once()
        view.view.after_render.call_args.args[0]()
        self.assertFalse(view._data_layout_pending)
        view._layout_data_grid.assert_called_once()


if __name__ == "__main__":
    unittest.main()
