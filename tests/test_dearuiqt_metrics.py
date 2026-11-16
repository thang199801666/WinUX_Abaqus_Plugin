import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.gui import QFontMetrics, QScreen


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
        return (120, 144)

    def get_physical_dpi(self):
        return (110, 112)

    def get_device_pixel_ratio(self):
        return 1.5


class DefaultBackend:
    pass


class DearUIQtMetricsTests(unittest.TestCase):
    def test_font_metrics_expose_qt_style_vertical_and_average_metrics(self):
        metrics = QFontMetrics(backend=MetricsBackend())
        self.assertEqual(metrics.height(), 20)
        self.assertEqual(metrics.lineSpacing(), 20)
        self.assertEqual(metrics.leading(), 0)
        self.assertEqual(metrics.descent(), 4)
        self.assertEqual(metrics.ascent(), 16)
        self.assertEqual(metrics.capHeight(), 15)
        self.assertEqual(metrics.xHeight(), 11)
        self.assertEqual(metrics.averageCharWidth(), 8)

    def test_screen_uses_backend_dpi_hooks_when_available(self):
        screen = QScreen(backend=MetricsBackend())
        self.assertEqual(screen.logicalDotsPerInchX(), 120)
        self.assertEqual(screen.logicalDotsPerInchY(), 144)
        self.assertEqual(screen.logicalDotsPerInch(), 120)
        self.assertEqual(screen.physicalDotsPerInchX(), 110)
        self.assertEqual(screen.physicalDotsPerInchY(), 112)
        self.assertEqual(screen.devicePixelRatio(), 1.5)
        self.assertEqual(screen.devicePixelRatioF(), 1.5)

    def test_screen_has_platform_neutral_96_dpi_fallback(self):
        screen = QScreen(backend=DefaultBackend())
        self.assertEqual(screen.logicalDotsPerInch(), 96.0)
        self.assertEqual(screen.physicalDotsPerInch(), 96.0)
        self.assertEqual(screen.devicePixelRatio(), 1.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
