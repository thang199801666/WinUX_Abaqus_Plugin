"""Plot Digitizer OCR cache lifecycle regression tests."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.core.engine import DigitizerEngine
from WinUx.plotdigitizer.core.ticks import cache as tick_cache


class DigitizerTickCacheLifecycleTests(unittest.TestCase):
    def test_cache_registry_contains_only_pixel_derived_caches(self):
        names = set(tick_cache.image_cache_info())
        self.assertIn('_cached_components', names)
        self.assertIn('_cached_word_candidates', names)
        self.assertIn('_cached_rotated_source_word', names)
        self.assertNotIn('_template_fonts', names)
        self.assertNotIn('_word_templates', names)
        self.assertNotIn('_template_prefix_advance', names)

    def test_apply_image_clears_pixel_derived_tick_caches(self):
        engine = DigitizerEngine()
        image = Image.new('RGB', (16, 16), 'white')
        with patch.object(tick_cache, 'clear_image_caches') as clear:
            engine.apply_image(image, 'sample.png')
        clear.assert_called_once_with()

    def test_clean_project_clears_pixel_derived_tick_caches(self):
        engine = DigitizerEngine()
        with patch.object(tick_cache, 'clear_image_caches') as clear:
            engine.clean_project()
        clear.assert_called_once_with()

    def test_clear_image_caches_resets_populated_cache(self):
        # _cached_components is intentionally easy to populate without font or
        # native UI dependencies: a 2x2 binary mask encoded as bytes.
        from WinUx.plotdigitizer.core.ticks.pixels import _cached_components
        _cached_components.cache_clear()
        _cached_components(2, 2, b'\x01\x00\x00\x01')
        self.assertGreater(_cached_components.cache_info().currsize, 0)
        tick_cache.clear_image_caches()
        self.assertEqual(_cached_components.cache_info().currsize, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
