"""Use the real workspace and gutter handler to verify splitter resizing."""
import sys
import unittest
from unittest.mock import patch

if sys.platform != 'win32':
    raise unittest.SkipTest('requires Windows Dear PyGui')
try:
    from WinUx.ui.components.explorer_list_view import dpg
except (ImportError, OSError) as exc:
    raise unittest.SkipTest('native Dear PyGui unavailable') from exc

from WinUx.view import WinUXView
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from DearUIQt.input_gate import release_pointer_input


class NativeFileJobSplitterTests(unittest.TestCase):
    def test_bound_gutter_click_resizes_real_file_panels_and_job_viewer(self):
        callbacks = {key: (lambda *args: None) for key in REQUIRED_CALLBACK_KEYS}
        callbacks['console_output'] = lambda: ''
        view = None
        with patch('WinUx.dialogs.prewarm_pool.start_dialog_prewarm'), patch('WinUx.view.UIHangWatchdog'):
            try:
                view = WinUXView(callbacks)
                view._console_dock_visible = False
                dpg.show_viewport()
                for _ in range(6):
                    view._apply_split_layout(force=True)
                    dpg.render_dearpygui_frame()
                top_before = dpg.get_item_pos(view.horizontal_splitter_hitbox)[1]
                left_before = dpg.get_item_configuration(view.left_parent)['height']
                bottom_before = dpg.get_item_configuration(view.bottom_region)['height']
                handlers = dpg.get_item_children(view._horizontal_splitter_handlers, 1)
                callback = dpg.get_item_configuration(handlers[0])['callback']
                with patch.object(view, '_left_mouse_button_down', return_value=True), \
                     patch.object(view, '_job_view_header_owns_pointer', return_value=True), \
                     patch.object(view, '_splitter_input_blocked', return_value=False), \
                     patch.object(dpg, 'is_item_hovered', return_value=False), \
                     patch.object(dpg, 'is_item_active', return_value=False), \
                     patch.object(view, '_native_cursor_screen_y', side_effect=[1000, 970]):
                    # Global polling can reject a stale header/hover decision;
                    # the real bound item handler must still acquire the press.
                    view._pre_dispatch_splitter_input()
                    self.assertFalse(view._horizontal_splitter_dragging)
                    callback(None, None, None)
                    self.assertTrue(view._horizontal_splitter_dragging)
                    view._drag_horizontal_splitter()
                self.assertEqual(dpg.get_item_pos(view.horizontal_splitter_hitbox)[1], top_before - 30)
                self.assertEqual(dpg.get_item_configuration(view.left_parent)['height'], left_before - 30)
                self.assertEqual(dpg.get_item_configuration(view.right_parent)['height'], left_before - 30)
                self.assertEqual(dpg.get_item_configuration(view.bottom_region)['height'], bottom_before + 30)
                view._end_horizontal_splitter_drag()
                self.assertFalse(view._horizontal_splitter_dragging)
                view._apply_split_layout(force=True)
                dpg.render_dearpygui_frame()
                # Plot divider owns real layout space in every docking area,
                # rather than an invisible hit halo covering list/header cells.
                with patch.object(view, '_job_plot_dock_visible', return_value=True):
                    for area in ('left', 'right', 'top', 'bottom'):
                        view._plot_dock_area = area
                        view._apply_split_layout(force=True)
                        dpg.render_dearpygui_frame()
                        hit = dpg.get_item_configuration(view.job_plot_separator_hitbox)
                        job = dpg.get_item_configuration(view.bottom_region)
                        plot = dpg.get_item_configuration(view.plot_region)
                        hx, hy = dpg.get_item_pos(view.job_plot_separator_hitbox)
                        jx, jy = dpg.get_item_pos(view.bottom_region)
                        px, py = dpg.get_item_pos(view.plot_region)
                        if area in ('left', 'right'):
                            self.assertEqual(hit['width'], 9)
                            near, far = ((px + plot['width'], jx) if area == 'left'
                                         else (jx + job['width'], px))
                            self.assertEqual((hx, hx + hit['width']), (near, far))
                        else:
                            self.assertEqual(hit['height'], 9)
                            near, far = ((py + plot['height'], jy) if area == 'top'
                                         else (jy + job['height'], py))
                            self.assertEqual((hy, hy + hit['height']), (near, far))
            finally:
                if view is not None:
                    view._end_horizontal_splitter_drag()
                    view._alive = False
                release_pointer_input()
                dpg.destroy_context()
