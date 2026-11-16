from contextlib import contextmanager
from pathlib import Path
import itertools
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.gui import QStyle, metrics_for_backend, metrics_for_dpi
from DearUIQt.gui.style import button_theme, line_edit_theme, tab_widget_theme
from DearUIQt.widgets.buttons import ImGuiPushButton, QToolButton
from DearUIQt.widgets.menu_bar import QMenuBar


class ThemeBackend:
    def __init__(self, dpi=96):
        self.dpi = dpi
        self.styles = []
        self.colors = []
        self._existing = set()

    def get_logical_dpi(self):
        return self.dpi, self.dpi

    def does_item_exist(self, tag):
        return tag in self._existing

    @contextmanager
    def theme(self, tag=None):
        if tag is not None:
            self._existing.add(tag)
        yield tag

    @contextmanager
    def theme_component(self, *_args, **_kwargs):
        yield

    def add_theme_style(self, role, *values, **kwargs):
        self.styles.append((role, values, kwargs))

    def add_theme_color(self, role, value, **kwargs):
        self.colors.append((role, value, kwargs))

    def __getattr__(self, name):
        if name.startswith('mv'):
            return name
        raise AttributeError(name)


class WidgetBackend:
    def __init__(self, dpi=96):
        self.dpi = dpi
        self._ids = itertools.count(1)
        self.items = {}

    def get_logical_dpi(self):
        return self.dpi, self.dpi

    def _add(self, **options):
        tag = next(self._ids)
        self.items[tag] = dict(options)
        return tag

    def add_button(self, **options):
        return self._add(**options)

    def add_group(self, **options):
        return self._add(**options)

    def does_item_exist(self, tag):
        return tag in self.items

    def configure_item(self, tag, **options):
        self.items[tag].update(options)

    def get_item_configuration(self, tag):
        return dict(self.items[tag])

    def get_item_state(self, tag):
        del tag
        return {}

    def delete_item(self, tag, **_kwargs):
        self.items.pop(tag, None)

    def set_value(self, tag, value):
        self.items[tag]['value'] = value

    def get_value(self, tag):
        return self.items[tag].get('value')


class DpiControlMetricTests(unittest.TestCase):
    def test_backend_metric_resolution_matches_dpi_scaling(self):
        for dpi in (96, 120, 144, 192):
            self.assertEqual(metrics_for_backend(WidgetBackend(dpi)), metrics_for_dpi(dpi))
        self.assertIs(metrics_for_dpi(144), metrics_for_dpi(144))

    def test_theme_cache_and_padding_are_dpi_specific(self):
        low = ThemeBackend(96)
        high = ThemeBackend(144)
        low_line = line_edit_theme(low)
        high_line = line_edit_theme(high)
        low_button = button_theme(low)
        high_button = button_theme(high)
        low_tabs = tab_widget_theme(low)
        high_tabs = tab_widget_theme(high)
        self.assertNotEqual(low_line, high_line)
        self.assertNotEqual(low_button, high_button)
        self.assertNotEqual(low_tabs, high_tabs)
        self.assertIn((low.mvStyleVar_FramePadding, (6, 6), {}), low.styles)
        self.assertIn((high.mvStyleVar_FramePadding, (9, 9), {}), high.styles)
        self.assertIn((low.mvStyleVar_FramePadding, (8, 3), {}), low.styles)
        self.assertIn((high.mvStyleVar_FramePadding, (12, 4), {}), high.styles)
        self.assertIn((high.mvStyleVar_FramePadding, (14, 6), {}), high.styles)

    def test_push_and_tool_button_default_geometry_scales_with_backend(self):
        backend = WidgetBackend(144)
        with patch('DearUIQt.widgets.buttons._bind_focus_state_handlers', return_value=None), \
             patch('DearUIQt.widgets.buttons.bind_theme', return_value=True):
            button = ImGuiPushButton('Run', backend=backend)
            tool = QToolButton('Tool', backend=backend)
        try:
            metrics = metrics_for_dpi(144)
            self.assertEqual(backend.items[button.tag]['height'], metrics.button_height)
            self.assertEqual(backend.items[tool.tag]['height'], metrics.tool_button_height)
            self.assertEqual(tool.iconSize(), (metrics.tool_button_icon_size,) * 2)
            self.assertEqual(button.controlMetrics(), metrics)
        finally:
            button.delete()
            tool.delete()

    def test_menu_bar_default_height_and_qstyle_metrics_scale(self):
        backend = WidgetBackend(144)
        bar = QMenuBar(backend=backend)
        try:
            metrics = metrics_for_dpi(144)
            self.assertEqual(bar.height, metrics.menu_bar_height)
            with patch('DearUIQt.widgets.buttons._bind_focus_state_handlers', return_value=None), \
                 patch('DearUIQt.widgets.buttons.bind_theme', return_value=True):
                button = ImGuiPushButton('Metric owner', backend=backend)
            try:
                style = QStyle()
                self.assertEqual(style.pixelMetric(QStyle.PM_ButtonMargin, widget=button), metrics.frame_pad_x)
                self.assertEqual(style.pixelMetric(QStyle.PM_SplitterWidth, widget=button), metrics.splitter_handle_width)
                self.assertGreater(style.pixelMetric(QStyle.PM_ScrollBarExtent, widget=button), 14)
            finally:
                button.delete()
        finally:
            bar.delete()


if __name__ == '__main__':
    unittest.main(verbosity=2)
