"""Change-only scrollbar painting and update-scoped geometry snapshots."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends.dearpygui_scroller import DpgScrollerArrowOverlay


class RetainedScrollerTests(unittest.TestCase):
    def overlay(self):
        overlay = DpgScrollerArrowOverlay.__new__(DpgScrollerArrowOverlay)
        overlay.dpg = Mock()
        overlay._chrome_config = {}
        overlay._geometry_cache = None
        overlay._origin = (0, 0)
        overlay._parts = {'v_track': 'track', 'v_thumb': 'thumb',
                          'v_thumb_start': 'start', 'v_thumb_end': 'end'}
        return overlay

    def test_repeated_paint_does_not_mutate_native_items(self):
        overlay = self.overlay()
        overlay._set_part('v_track', (1, 2, 10, 100), fill=(1, 2, 3), rounding=2)
        overlay.dpg.configure_item.assert_called_once()
        overlay.dpg.configure_item.reset_mock()
        for _ in range(100):
            overlay._set_part('v_track', (1, 2, 10, 100), fill=(1, 2, 3), rounding=2)
        overlay.dpg.configure_item.assert_not_called()
        overlay._set_part('v_track', (1, 2, 10, 100), fill=(4, 5, 6), rounding=2)
        overlay.dpg.configure_item.assert_called_once_with('track', fill=(4, 5, 6))

    def test_capsule_updates_only_changed_geometry(self):
        overlay = self.overlay()
        overlay._set_part('v_thumb', (1, 2, 7, 50))
        self.assertEqual(overlay.dpg.configure_item.call_count, 3)
        overlay.dpg.configure_item.reset_mock()
        overlay._set_part('v_thumb', (1, 2, 7, 50))
        overlay.dpg.configure_item.assert_not_called()
        overlay._set_part('v_thumb', (1, 12, 7, 60))
        self.assertEqual(overlay.dpg.configure_item.call_count, 3)

    def test_visibility_changes_preserve_geometry_and_can_restore(self):
        overlay = self.overlay()
        overlay._configure_chrome('hit', show=True, pos=(2, 3), width=10)
        overlay.dpg.configure_item.reset_mock()
        overlay._configure_chrome('hit', show=False)
        overlay._configure_chrome('hit', show=False)
        overlay._configure_chrome('hit', show=True, pos=(2, 3), width=10)
        self.assertEqual(overlay.dpg.configure_item.call_args_list,
                         [unittest.mock.call('hit', show=False), unittest.mock.call('hit', show=True)])

    def test_failed_native_update_is_not_cached(self):
        overlay = self.overlay()
        overlay.dpg.configure_item.side_effect = RuntimeError('temporary backend failure')
        with self.assertRaises(RuntimeError):
            overlay._configure_chrome('hit', show=True)
        self.assertNotIn('hit', overlay._chrome_config)
        overlay.dpg.configure_item.side_effect = None
        overlay._configure_chrome('hit', show=True)
        self.assertEqual(overlay.dpg.configure_item.call_count, 2)

    def test_geometry_cache_lives_for_one_update_only(self):
        overlay = self.overlay()
        def sample():
            for _ in range(10):
                overlay._window_rect('target', clip=True)
        overlay._update = sample
        with patch('DearUIQt.backends.dearpygui_scroller.dpg_window_rect', return_value=None) as measure:
            overlay.update()
            measure.assert_called_once()
            self.assertIsNone(overlay._geometry_cache)
            overlay.update()
            self.assertEqual(measure.call_count, 2)
            overlay._window_rect('target', clip=True)
            self.assertEqual(measure.call_count, 3)

    def test_geometry_cache_clears_on_failure(self):
        overlay = self.overlay()
        overlay._update = Mock(side_effect=ValueError('failed update'))
        with self.assertRaises(ValueError):
            overlay.update()
        self.assertIsNone(overlay._geometry_cache)


if __name__ == '__main__':
    unittest.main(verbosity=2)
