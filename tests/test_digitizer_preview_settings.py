"""Preview magnification/preferences remain valid, persistent and data-independent."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from WinUx.preferences.plot_digitizer import PlotDigitizerPreferences
from WinUx.plotdigitizer.ui.preview import preview_geometry


class PreviewSettingsTests(unittest.TestCase):
    def test_existing_preferences_receive_preview_defaults(self):
        settings = PlotDigitizerPreferences.normalize({'show_magnifier': False, 'marker_size_percent': 150})
        self.assertFalse(settings['show_magnifier'])
        self.assertEqual(settings['marker_size_percent'], 150)
        self.assertEqual(settings['preview_zoom'], 5)
        self.assertEqual(settings['preview_size'], 140)
        self.assertTrue(settings['preview_crosshair'])

    def test_numeric_ranges_and_types_are_checked_per_setting(self):
        for key, (low, high) in PlotDigitizerPreferences.INT_RANGES.items():
            for value in (low, high):
                self.assertEqual(PlotDigitizerPreferences.normalize({key: value})[key], value)
            for value in (low - 1, high + 1, True, str(low), float(low), None):
                self.assertEqual(PlotDigitizerPreferences.normalize({key: value})[key],
                                 PlotDigitizerPreferences.DEFAULTS[key])

    def test_zoom_changes_sampled_region_without_stretching(self):
        for zoom in (1, 5, 9, 20):
            result = preview_geometry((1000, 800), (500, 400), 2, 200, magnification=zoom)
            sampled_width = (result.uv_max[0] - result.uv_min[0]) * 1000
            self.assertAlmostEqual(sampled_width * 2 * zoom, 200)
            self.assertEqual(result.image_min, (0, 0))
            self.assertAlmostEqual(result.image_max[0], 200)

    def test_edge_clipping_retains_configured_zoom(self):
        result = preview_geometry((1000, 800), (0, 0), 2, 200, magnification=10)
        self.assertEqual(result.image_min, (100, 100))
        sampled_width = (result.uv_max[0] - result.uv_min[0]) * 1000
        self.assertAlmostEqual(sampled_width * 20, 100)

    def test_new_settings_round_trip_and_reset(self):
        temp = Path.home() / 'AppData' / 'Local' / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(prefix='preview-settings-', dir=temp) as profile:
            store = PlotDigitizerPreferences(root=profile)
            store.save({'preview_zoom': 12, 'preview_size': 240, 'preview_crosshair': False,
                        'wheel_zoom_percent': 30})
            settings = store.load()
            self.assertEqual(settings['preview_zoom'], 12)
            self.assertEqual(settings['preview_size'], 240)
            self.assertFalse(settings['preview_crosshair'])
            self.assertEqual(settings['wheel_zoom_percent'], 30)
            self.assertEqual(store.reset(), PlotDigitizerPreferences.DEFAULTS)


if __name__ == '__main__':
    unittest.main()
