"""Resizable pane minima are pixel-based, not percentage-based."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from WinUx.view import WinUXView
from WinUx.ui.behaviors.splitter_behavior import SplitterLayoutBehaviorMixin


class MinimumPaneSizeTests(unittest.TestCase):
    def test_all_workspace_panes_have_fifty_pixel_minima(self):
        for key in ('MIN_PANEL_WIDTH', 'MIN_TOP_HEIGHT', 'MIN_BOTTOM_HEIGHT',
                    'MIN_JOB_VIEWER_WIDTH', 'MIN_JOB_VIEWER_DOCK_HEIGHT',
                    'MIN_PLOT_DOCK_WIDTH', 'MIN_PLOT_DOCK_HEIGHT',
                    'MIN_CONSOLE_DOCK_WIDTH', 'MIN_CONSOLE_DOCK_HEIGHT'):
            self.assertEqual(getattr(WinUXView, key), 50, key)

    def test_plot_minimum_is_not_held_at_five_percent(self):
        class Host(SplitterLayoutBehaviorMixin):
            PLOT_DOCK_AREAS = ('left', 'right', 'top', 'bottom')
            PLOT_DOCK_DEFAULT_RATIO = .5
            PLOT_DOCK_SEPARATOR_SIZE = 9
            MIN_JOB_VIEWER_WIDTH = MIN_PLOT_DOCK_WIDTH = 50
            MIN_JOB_VIEWER_DOCK_HEIGHT = MIN_PLOT_DOCK_HEIGHT = 50
            _plot_dock_area = 'right'
            _plot_split_ratios = {}

        host = Host()
        for area in ('left', 'right', 'top', 'bottom'):
            for ratio, index in ((0.0, 0), (1.0, 1)):
                host._set_plot_ratio_for_area(ratio, area)
                sizes = (host._plot_split_widths(2000, area) if area in ('left', 'right')
                         else host._plot_split_heights(2000, area))
                self.assertEqual(sizes[index], 50, (area, ratio, sizes))
