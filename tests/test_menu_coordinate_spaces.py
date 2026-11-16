"""Focused regressions for context menus in detached single-viewport hosts."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from DearUIQt.widgets.menu import QMenu


class MenuCoordinateTests(unittest.TestCase):
    def setUp(self):
        self.menu = QMenu.__new__(QMenu)
        self.menu.backend = Mock()
        self.menu._parent_window = None
        self.menu._parent_menu = None
        self.menu._popup_global_position = True
        self.menu.tag = 123
        self.menu.backend.get_viewport_client_width.return_value = 800
        self.menu.backend.get_viewport_client_height.return_value = 500
        self.native = Mock()
        self.native.isEnabled.return_value = False
        self.native.primaryWinId.return_value = 777
        self.native_patch = patch('DearUIQt.backends.native_windows.NativeWindowBackend',
                                  return_value=self.native)
        self.native_patch.start()
        self.addCleanup(self.native_patch.stop)

    def test_disabled_multiwindow_still_uses_primary_client_origin(self):
        def client_to_screen(_hwnd, pointer):
            point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
            point.x, point.y = 308, 181
            return True
        self.menu.backend.get_viewport_pos.return_value = (-999, -999)
        with patch('ctypes.windll.user32.ClientToScreen', side_effect=client_to_screen):
            self.assertEqual(self.menu._single_viewport_origin(), (308, 181))
        self.native.primaryWinId.assert_called_once()

    def test_native_multiwindow_coordinates_are_unchanged(self):
        self.native.isEnabled.return_value = True
        self.assertEqual(self.menu._renderer_popup_position((440, 250)), (440, 250))
        self.assertEqual(self.menu._popup_screen_rect((10, 20, 80, 90)), (10, 20, 80, 90))
        self.native.primaryWinId.assert_not_called()

    def test_negative_monitor_origin_is_supported(self):
        self.menu._single_viewport_origin = lambda: (-1500, -120)
        self.assertEqual(self.menu._renderer_popup_position((-1360, -20)), (140, 100))
        self.assertEqual(self.menu._popup_screen_rect((140, 100, 342, 300)),
                         (-1360, -20, -1158, 180))

    def test_local_popup_position_is_not_converted(self):
        self.menu._single_viewport_origin = Mock(return_value=(300, 150))
        self.menu._popup_global_position = False
        self.assertEqual(self.menu._renderer_popup_position((140, 100)), (140, 100))
        self.menu._single_viewport_origin.assert_not_called()

    def test_single_viewport_bounds_use_live_client_origin(self):
        self.menu._single_viewport_origin = lambda: (300, 150)
        self.assertEqual(self.menu._global_popup_bounds((440, 250)), (300, 150, 1100, 650))

    def test_global_owner_anchor_keeps_same_client_offset_after_move(self):
        origin = [300, 150]
        self.menu._single_viewport_origin = lambda: tuple(origin)
        self.menu._popup_size = lambda: (202, 200)
        self.menu.popup = Mock(return_value=True)
        with patch('DearUIQt.gui.placement.visible_item_screen_rect', return_value=(0, 0, 800, 500)):
            self.assertTrue(self.menu.popupGlobal((440, 250), owner=777))
            resolver = self.menu.popup.call_args.kwargs['_placement']
            point, _size = resolver()
            self.assertEqual(self.menu._renderer_popup_position(point), (140, 100))
            origin[:] = [620, 270]
            point, _size = resolver()
            self.assertEqual(point, (760, 370))
            self.assertEqual(self.menu._renderer_popup_position(point), (140, 100))

    def test_row_hit_rect_is_in_screen_space_for_global_menus(self):
        self.menu._single_viewport_origin = lambda: (300, 150)
        self.menu.backend.get_x_scroll.return_value = 0
        self.menu.backend.get_y_scroll.return_value = 0
        def rect(_backend, item, **_kwargs):
            return (0, 0, 400, 300) if item == self.menu.tag else (25, 35, 100, 60)
        with patch('DearUIQt.widgets.menu.dpg_window_rect', side_effect=rect):
            self.assertEqual(self.menu._pointer_row_rect(456), (325, 185, 400, 210))

    def test_global_geometry_matches_screen_hit_testing(self):
        self.menu._single_viewport_origin = lambda: (300, 150)
        self.menu.exists = lambda: True
        with patch('DearUIQt.widgets.menu.dpg_window_rect', return_value=(140, 100, 342, 300)):
            self.assertEqual(self.menu.globalGeometry().toTuple(), (440, 250, 202, 200))
            self.assertTrue(self.menu.containsGlobalPoint((450, 260)))
            self.assertFalse(self.menu.containsGlobalPoint((150, 110)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
