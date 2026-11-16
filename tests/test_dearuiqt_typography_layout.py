import itertools
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import Qt, QSize
from DearUIQt.gui import QFontMetrics, QScreen, metrics_for_dpi, metrics_for_screen
from DearUIQt.layouts import QHBoxLayout, QGridLayout
from DearUIQt.widgets import QLabel, QWidget
from DearUIQt.dialogs.sizing import compact_message_size


class MetricsBackend:
    def get_text_size(self, text, **kwargs):
        del kwargs
        if text == 'Ag':
            return 14, 20
        if text == 'H':
            return 8, 15
        if text == 'x':
            return 7, 11
        return len(text) * 8, 20

    def get_logical_dpi(self):
        return (120, 120)


class LargeMetricsBackend(MetricsBackend):
    def get_text_size(self, text, **kwargs):
        del kwargs
        if text == 'Ag':
            return 24, 32
        if text == 'H':
            return 13, 24
        if text == 'x':
            return 12, 18
        return len(text) * 13, 32


class CountingMetricsBackend(MetricsBackend):
    def __init__(self):
        self.calls = 0

    def get_text_size(self, text, **kwargs):
        self.calls += 1
        return super().get_text_size(text, **kwargs)


class Backend(MetricsBackend):
    mvTable_SizingStretchProp = 0

    def __init__(self):
        self.sequence = itertools.count(1)
        self.items = {}

    def _add(self, **options):
        tag = next(self.sequence)
        self.items[tag] = dict(options)
        self.items[tag].setdefault('value', options.get('default_value', ''))
        return tag

    def add_group(self, **options):
        return self._add(**options)

    add_table = add_table_row = add_table_column = add_group

    def add_text(self, value='', **options):
        options['value'] = str(value)
        return self._add(**options)

    def get_item_parent(self, tag):
        return self.items[tag].get('parent')

    def get_item_configuration(self, tag):
        return dict(self.items[tag])

    def does_item_exist(self, tag):
        return tag in self.items

    def configure_item(self, tag, **options):
        self.items[tag].update(options)

    def move_item(self, tag, *, parent, **options):
        self.items[tag]['parent'] = parent
        self.items[tag].update(options)

    def delete_item(self, tag):
        self.items.pop(tag, None)

    def set_value(self, tag, value):
        self.items[tag]['value'] = value

    def get_value(self, tag):
        return self.items[tag].get('value', '')


class BaselineWidget(QWidget):
    def __init__(self, backend, parent, height, baseline):
        super().__init__(backend.add_group(parent=parent.tag), parent=parent, backend=backend)
        self._height = height
        self._baseline = baseline
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def sizeHint(self):
        return QSize(40, self._height)

    minimumSizeHint = sizeHint

    def heightForWidth(self, width):
        del width
        return self._height

    def baselineOffset(self, width=None):
        del width
        return self._baseline


class TypographyLayoutTests(unittest.TestCase):
    def test_font_metrics_elide_modes_are_measurement_driven(self):
        metrics = QFontMetrics(backend=MetricsBackend())
        self.assertEqual(metrics.elidedText('abcdef', Qt.ElideRight, 40), 'abcd…')
        self.assertEqual(metrics.elidedText('abcdef', Qt.ElideLeft, 40), '…cdef')
        self.assertEqual(metrics.elidedText('abcdef', Qt.ElideMiddle, 40), 'ab…ef')
        self.assertEqual(metrics.elidedText('abc', Qt.ElideRight, 40), 'abc')
        self.assertEqual(metrics.elidedText('abcdef', Qt.ElideNone, 8), 'abcdef')

    def test_repeated_elision_reuses_measured_substring_widths(self):
        backend = CountingMetricsBackend()
        metrics = QFontMetrics(backend=backend)
        for _ in range(100):
            self.assertEqual(metrics.elidedText('abcdefghijklmnopqrstuvwxyz', Qt.ElideMiddle, 80),
                             'abcde…wxyz')
        self.assertLess(backend.calls, 20)

    def test_word_wrap_and_bounding_rect_use_line_metrics(self):
        metrics = QFontMetrics(backend=MetricsBackend())
        self.assertEqual(metrics.wrappedLines('one two three', 56), ('one two', 'three'))
        self.assertEqual(metrics.size('one two three', Qt.TextWordWrap, 56), QSize(56, 40))
        rect = metrics.boundingRect(0, 0, 56, 100,
                                    Qt.TextWordWrap | Qt.AlignVCenter,
                                    'one two three')
        self.assertEqual((rect.x(), rect.y(), rect.width(), rect.height()), (0, 30, 56, 40))

    def test_long_tokens_break_without_infinite_wrap(self):
        metrics = QFontMetrics(backend=MetricsBackend())
        self.assertEqual(metrics.wrappedLines('abcdefgh', 24), ('abc', 'def', 'gh'))
        self.assertEqual(metrics.wrappedLines('ab cd', 16, Qt.TextWrapAnywhere), ('ab', ' c', 'd'))

    def test_label_word_wrap_participates_in_height_for_width(self):
        backend = Backend()
        root = QHBoxLayout(backend=backend, spacing=0)
        try:
            label = QLabel('one two three', parent=root, backend=backend, wrap=56)
            self.assertTrue(label.hasHeightForWidth())
            self.assertEqual(label.heightForWidth(56), 40)
            self.assertEqual(label.sizeHint(), QSize(56, 40))
            self.assertEqual(label.minimumSizeHint(), QSize(40, 20))  # 'three'
            self.assertEqual(label.baselineOffset(), 16)
            label.setText('one two')
            self.assertEqual(label.text(), 'one two')
        finally:
            root.delete()

    def test_horizontal_layout_reserves_mixed_font_baseline_extent(self):
        backend = Backend()
        layout = QHBoxLayout(backend=backend, spacing=0)
        try:
            first = BaselineWidget(backend, layout, 20, 15)   # ascent 15, descent 5
            second = BaselineWidget(backend, layout, 30, 10)  # ascent 10, descent 20
            self.assertEqual(layout.heightForWidth(100), 30)
            self.assertTrue(layout.setAlignment(first, Qt.AlignBaseline))
            self.assertTrue(layout.setAlignment(second, Qt.AlignBaseline))
            self.assertEqual(layout.heightForWidth(100), 35)
            self.assertEqual(layout.itemAt(0).alignment(), Qt.AlignBaseline)
        finally:
            layout.delete()

    def test_grid_row_reserves_baseline_for_explicitly_aligned_items(self):
        backend = Backend()
        grid = QGridLayout(2, backend=backend)
        try:
            first_cell = grid.cell(0, 0)
            second_cell = grid.cell(0, 1)
            first = BaselineWidget(backend, first_cell, 20, 15)
            second = BaselineWidget(backend, second_cell, 30, 10)
            grid.addWidget(first, 0, 0, alignment=Qt.AlignBaseline)
            grid.addWidget(second, 0, 1, alignment=Qt.AlignBaseline)
            self.assertEqual(grid.heightForWidth(100), 35)
            self.assertEqual(grid.itemAt(0).alignment(), Qt.AlignBaseline)
        finally:
            grid.delete()

    def test_compact_message_geometry_tracks_actual_font_metrics(self):
        normal = QFontMetrics(backend=MetricsBackend())
        large = QFontMetrics(backend=LargeMetricsBackend())
        normal_size = compact_message_size(
            'Are you sure you want to exit WinUx?', heading='Exit WinUx?',
            body_metrics=normal, heading_metrics=normal)
        large_size = compact_message_size(
            'Are you sure you want to exit WinUx?', heading='Exit WinUx?',
            body_metrics=large, heading_metrics=large)
        self.assertGreater(large_size[0], normal_size[0])
        self.assertGreater(large_size[1], normal_size[1])

    def test_scaled_control_metrics_cover_common_windows_dpi_levels(self):
        self.assertEqual(metrics_for_dpi(96).control_height, 26)
        self.assertEqual(metrics_for_dpi(120).control_height, 32)
        self.assertEqual(metrics_for_dpi(144).control_height, 39)
        self.assertEqual(metrics_for_dpi(192).control_height, 52)
        screen = QScreen(backend=MetricsBackend())
        self.assertAlmostEqual(screen.dpiScale(), 1.25)
        self.assertEqual(metrics_for_screen(screen).button_height, 32)


if __name__ == '__main__':
    unittest.main(verbosity=2)
