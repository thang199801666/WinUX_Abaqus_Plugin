"""Plot context menu spacing must stay balanced despite compact app padding."""
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
        self.styles = []
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

    def add_theme_style(self, role, *value, **_kwargs):
        self.styles.append((self.component, role, tuple(value)))


class PlotContextMenuThemeTests(unittest.TestCase):
    def test_plot_popup_overrides_compact_application_padding(self):
        backend = Backend()
        style.plot_surface_theme(backend)
        styles = set(backend.styles)
        self.assertIn(('mvPlot', 'mvStyleVar_WindowPadding', (8, 6)), styles)
        self.assertIn(('mvPlot', 'mvStyleVar_FramePadding', (5, 3)), styles)
        self.assertIn(('mvPlot', 'mvStyleVar_ItemSpacing', (6, 3)), styles)
        self.assertIn(('mvPlot', 'mvStyleVar_ItemInnerSpacing', (6, 3)), styles)
        self.assertIn(('mvPlot', 'mvStyleVar_PopupRounding', (3,)), styles)
        self.assertIn(('mvPlot', 'mvStyleVar_WindowBorderSize', (1,)), styles)

    def test_plot_popup_uses_light_fusion_menu_colors(self):
        backend = Backend()
        style.plot_surface_theme(backend)
        colors = set(backend.colors)
        self.assertIn(('mvPlot', 'mvThemeCol_PopupBg', (250, 250, 250, 255)), colors)
        self.assertIn(('mvPlot', 'mvThemeCol_Border', (176, 176, 176, 255)), colors)
        self.assertIn(('mvPlot', 'mvThemeCol_FrameBg', (255, 255, 255, 255)), colors)


if __name__ == '__main__':
    unittest.main(verbosity=2)
