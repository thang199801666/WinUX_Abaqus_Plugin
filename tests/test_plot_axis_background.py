"""Plot axis gutters must not paint over the plot frame border."""
from contextlib import contextmanager
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.gui import style


class Backend:
    def __init__(self):
        self.colors = []
        self.component = None

    def __getattr__(self, name):
        if name.startswith('mv'):
            return name
        raise AttributeError(name)

    def does_item_exist(self, _tag):
        return False

    @contextmanager
    def theme(self, **_kwargs):
        yield 'theme'

    @contextmanager
    def theme_component(self, component, **_kwargs):
        previous = self.component
        self.component = component
        yield component
        self.component = previous

    def add_theme_color(self, role, value, **_kwargs):
        self.colors.append((self.component, role, tuple(value)))

    def add_theme_style(self, _role, *_value, **_kwargs):
        pass


class PlotAxisBackgroundTests(unittest.TestCase):
    def test_axis_interaction_backgrounds_are_transparent(self):
        backend = Backend()
        style.plot_surface_theme(backend)
        expected = {
            ('mvPlot', 'mvPlotCol_AxisBg', (0, 0, 0, 0)),
            ('mvPlot', 'mvPlotCol_AxisBgHovered', (0, 0, 0, 0)),
            ('mvPlot', 'mvPlotCol_AxisBgActive', (0, 0, 0, 0)),
        }
        self.assertTrue(expected.issubset(set(backend.colors)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
