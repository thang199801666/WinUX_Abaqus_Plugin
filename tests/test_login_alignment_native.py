"""Login editors, combo arrow hit targets and labels share one 26 px grid."""
from types import SimpleNamespace
import os
import sys
import unittest

if sys.platform != 'win32':
    raise unittest.SkipTest('requires Windows Dear PyGui')
try:
    from WinUx.ui.components.explorer_list_view import dpg
except (ImportError, OSError) as exc:
    raise unittest.SkipTest('native Dear PyGui unavailable') from exc

from WinUx.dialogs.login_form import LoginForm
from WinUx.ui.appearance import configure_ui_context
from WinUx.runtime.dpg_callbacks import run_callback_jobs


class LoginAlignmentTests(unittest.TestCase):
    def test_editors_labels_busy_state_resize_and_history_selection(self):
        dpg.create_context()
        try:
            view = SimpleNamespace(after=lambda *args: None)
            configure_ui_context(view)
            initial = {'hosts': ['host01', 'host02'], 'host': 'host01',
                       'ports': {'host02': 2222}, 'port': '22',
                       'usernames': ['test_user'], 'username': 'test_user',
                       'password': 'test-value', 'remember': True}
            form = LoginForm(view, lambda *args: None, initial=initial)
            dpg.configure_item(form.tag, modal=False, no_title_bar=True)
            title = 'Login alignment regression %d' % os.getpid()
            dpg.create_viewport(title=title, width=420, height=form.preferred_size[1] + 40)
            dpg.setup_dearpygui()
            dpg.show_viewport()
            dpg.set_primary_window(form.tag, True)

            def pump(count=4):
                for _ in range(count):
                    dpg.render_dearpygui_frame()
                    run_callback_jobs(dpg.get_callback_queue() or [])

            def assert_geometry():
                rows = dpg.get_item_children(form._form, 1)
                fields = (form.host, form.port, form.username, form.password)
                origins = []
                for index, field in enumerate(fields):
                    cells = dpg.get_item_children(rows[index], 1)
                    label = dpg.get_item_children(cells[0], 1)[0]
                    origin = dpg.get_item_rect_min(cells[1])
                    origins.append(origin)
                    centre = origin[1] + 13
                    self.assertAlmostEqual(dpg.get_item_rect_min(label)[1] +
                                           dpg.get_item_rect_size(label)[1] / 2, centre, delta=.5)
                    self.assertAlmostEqual(dpg.get_item_rect_min(field)[1] +
                                           dpg.get_item_rect_size(field)[1] / 2, centre, delta=.5)
                    if index in (0, 2):
                        combo = form.host_combo if index == 0 else form.username_combo
                        self.assertEqual(dpg.get_item_rect_size(combo.shell)[1], 26)
                        self.assertEqual(dpg.get_item_rect_min(combo.input)[1], dpg.get_item_rect_min(combo.button)[1])
                        self.assertEqual(dpg.get_item_rect_size(combo.input)[1], dpg.get_item_rect_size(combo.button)[1])
                        input_end = dpg.get_item_rect_min(combo.input)[0] + dpg.get_item_rect_size(combo.input)[0]
                        arrow_start = dpg.get_item_rect_min(combo.button)[0] + dpg.get_item_rect_size(combo.button)[0] - 24
                        self.assertLessEqual(input_end, arrow_start)
                    else:
                        self.assertEqual(dpg.get_item_rect_size(field)[1], 26)
                self.assertEqual(len({origin[0] for origin in origins}), 1)
                self.assertEqual([origins[i+1][1] - origins[i][1] for i in range(3)], [30] * 3)
                self.assertEqual(dpg.get_item_rect_min(form.remember)[0], origins[0][0])
                self.assertEqual(dpg.get_item_rect_size(form.remember)[1], 14)
                self.assertEqual(dpg.get_y_scroll_max(form.content), 0)
                self.assertLess(dpg.get_item_rect_min(form.remember)[1] + 14,
                                dpg.get_item_rect_min(form.connect_button)[1])

            for width in (420, 520):
                dpg.configure_viewport(0, width=width)
                for busy in (False, True, False):
                    form._set_busy(busy)
                    pump()
                    assert_geometry()

            # Verify the arrow's uncovered hit region and history callback
            # against actual native item geometry (no input desktop required).
            x, y = dpg.get_item_rect_min(form.host_combo.button)
            width, height = dpg.get_item_rect_size(form.host_combo.button)
            cx, cy = int(x + width - 12), int(y + height / 2)
            self.assertTrue(form.host_combo._point_inside(form.host_combo.shell, cx, cy))
            self.assertFalse(form.host_combo._point_inside(form.host, cx, cy))
            form.host_combo._native_selected(form.host_combo.button, 'host02')
            self.assertEqual(form._snapshot()['host'], 'host02')
            self.assertEqual(form._snapshot()['port'], '2222')
        finally:
            dpg.destroy_context()
