"""Regression tests for press-time File/Job splitter jumps."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.behaviors.splitter_behavior import SplitterLayoutBehaviorMixin as Splitters


class HorizontalSplitterAnchorTests(unittest.TestCase):
    def host(self, *, top=400.0, height=600, ratio=0.66):
        host = SimpleNamespace(
            _horizontal_splitter_owner=object(),
            _horizontal_splitter_dragging=True,
            _horizontal_splitter_drag_start_screen_y=500.0,
            _horizontal_splitter_drag_start_delta_y=0.0,
            _horizontal_splitter_drag_start_top=float(top),
            _horizontal_splitter_drag_content_size=(800, int(height)),
            _horizontal_splitter_live_top_height=float(top),
            _top_ratio=float(ratio),
            _layout_dirty=False,
            _plot_dock_scope="inner",
            _plot_dock_area="right",
            _console_dock_visible=False,
            _console_dock_mode="docked",
            _console_dock_scope="inner",
            _console_dock_area="bottom",
            MIN_TOP_HEIGHT=260,
            MIN_BOTTOM_HEIGHT=150,
            MIN_JOB_VIEWER_DOCK_HEIGHT=120,
            MIN_PLOT_DOCK_HEIGHT=180,
            PLOT_DOCK_SEPARATOR_SIZE=9,
            MIN_CONSOLE_DOCK_HEIGHT=150,
            CONSOLE_DOCK_SPLITTER_GUTTER_SIZE=9,
            FILE_JOB_SPLITTER_GUTTER_SIZE=9,
            _splitter_input_blocked=Mock(return_value=False),
            _native_cursor_screen_y=Mock(return_value=500.0),
            _interactive_content_size=Mock(return_value=(800, int(height))),
            _job_plot_dock_visible=Mock(return_value=False),
            _plot_dock_is_vertical_split=Mock(return_value=True),
            _normalize_console_dock_area=lambda value: value,
            _apply_split_layout=Mock(),
            _end_horizontal_splitter_drag=Mock(),
        )
        return host

    def test_mouse_down_with_zero_delta_does_not_snap_to_ratio_rounding(self):
        host = self.host(top=400.0, height=600, ratio=0.66)

        Splitters._drag_horizontal_splitter(host)

        self.assertEqual(host._top_ratio, 0.66)
        host._apply_split_layout.assert_not_called()

    def test_outer_docks_do_not_shrink_file_job_drag_range(self):
        host = self.host(top=430.0, height=600, ratio=430.0 / 600.0)
        host._job_plot_dock_visible.return_value = True
        host._plot_dock_scope = "outer"
        host._plot_dock_area = "top"
        host._console_dock_visible = True
        host._console_dock_scope = "outer"
        host._console_dock_area = "top"

        Splitters._drag_horizontal_splitter(host)

        self.assertAlmostEqual(host._top_ratio, 430.0 / 600.0)
        host._apply_split_layout.assert_not_called()
        host._plot_dock_is_vertical_split.assert_not_called()

    def test_inner_bottom_console_still_reserves_vertical_space(self):
        host = self.host(top=430.0, height=600, ratio=430.0 / 600.0)
        host._console_dock_visible = True
        host._console_dock_scope = "inner"
        host._console_dock_area = "bottom"

        Splitters._drag_horizontal_splitter(host)

        expected_top = 600 - (150 + 150 + 9) - 9 - 1
        self.assertAlmostEqual(host._top_ratio, expected_top / 600.0)
        host._apply_split_layout.assert_called_once_with(
            force=True, interactive=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
