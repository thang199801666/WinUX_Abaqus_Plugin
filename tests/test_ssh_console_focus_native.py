"""Exercise terminal click handling against real DPG viewport geometry."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

if sys.platform != 'win32':
    raise unittest.SkipTest('requires native Windows Dear PyGui')
try:
    import dearpygui.dearpygui as dpg
except (ImportError, OSError) as exc:
    raise unittest.SkipTest('native Dear PyGui unavailable') from exc

from WinUx.dialogs.console_form import ConsoleDockPanel


class NativeConsoleFocusTests(unittest.TestCase):
    def test_click_edit_selection_and_focus_leave_keep_native_scroll_stable(self):
        dpg.create_context()
        panel = None
        try:
            dpg.configure_app(manual_callback_management=True)
            root = dpg.add_window(width=780, height=420)
            dpg.add_input_text(parent=root, label='Other control')
            queued = []
            view = SimpleNamespace(
                terminal_font=None, _console_keyboard_panel=None,
                _console_dock_visible=True,
                after=lambda delay, callback, *args: queued.append((callback, args)))
            font_path = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', 'consola.ttf')
            with dpg.font_registry():
                view.terminal_font = dpg.add_font(font_path, 15)

            def set_owner(active, target):
                view._console_keyboard_panel = target if active else None

            view._set_console_keyboard_active = set_owner
            output = '\n'.join('output line %d' % i for i in range(60)) + '\n$ '
            panel = ConsoleDockPanel(view, root, lambda: output, lambda command: True, lambda: True)
            panel.buffer.type_text('abcdef')
            dpg.create_viewport(title='SSH Console focus regression', width=800, height=460)
            dpg.setup_dearpygui()
            dpg.show_viewport()
            dpg.set_primary_window(root, True)

            def pump():
                dpg.render_dearpygui_frame()
                panel._paint()
                # Discard physical callbacks; each gesture below is dispatched
                # explicitly using pixel positions from the real viewport.
                dpg.get_callback_queue()

            panel.focus_input()
            for _ in range(5):
                pump()
            scroll_before = dpg.get_y_scroll(panel.content)
            self.assertGreater(scroll_before, 0)
            rows, cursor_row, _column = panel.buffer.layout(panel._render_columns)
            x0, y0 = dpg.get_item_rect_min(panel.canvas)
            position = (x0 + 5.25 * panel._char_width,
                        y0 + (cursor_row + 0.5) * panel._line_height)
            with patch.object(dpg, 'get_mouse_pos', return_value=position):
                # Reproduce the real global/item callback ordering with the
                # child hover flag missing during input dispatch.
                with patch.object(panel, '_over_terminal', return_value=False):
                    panel._mouse_click()
                callback, args = queued[-1]
                panel._canvas_left_click()
                panel._mouse_release()
                callback(*args)
            self.assertEqual(panel.buffer.cursor, 3)
            self.assertTrue(panel.keyboard_active(), (position, dpg.get_item_state(panel.content), args))
            with patch('WinUx.ui.components.console_renderer.time.monotonic',
                       return_value=panel._caret_blink_started + .01):
                panel._paint()
            self.assertTrue(dpg.get_item_configuration(panel._caret)['show'])
            for _ in range(3):
                pump()
            self.assertAlmostEqual(dpg.get_y_scroll(panel.content), scroll_before, delta=1)
            panel.native_character(ord('X'))
            self.assertEqual(panel.buffer.draft, 'abcXdef')
            pump()
            self.assertAlmostEqual(dpg.get_y_scroll(panel.content), scroll_before, delta=1)

            # Clicking earlier output does not move the editable command caret.
            panel._last_click_time = 0
            position = (x0 + 2.25 * panel._char_width,
                        y0 + (cursor_row - 1 + 0.5) * panel._line_height)
            with patch.object(dpg, 'get_mouse_pos', return_value=position):
                panel._canvas_left_click()
                panel._mouse_release()
            self.assertEqual(panel.buffer.cursor, 4)
            for _ in range(3):
                pump()
            self.assertAlmostEqual(dpg.get_y_scroll(panel.content), scroll_before, delta=1)

            # Outside click remains an outside click even if the mouse returns.
            with patch.object(dpg, 'get_mouse_pos', return_value=(-100, -100)):
                panel._mouse_click()
            callback, args = queued[-1]
            with patch.object(dpg, 'get_mouse_pos', return_value=position):
                callback(*args)
            self.assertFalse(panel.keyboard_active())
            panel.native_character(ord('Y'))
            self.assertEqual(panel.buffer.draft, 'abcXdef')
            with patch('WinUx.ui.components.console_renderer.time.monotonic', return_value=0):
                panel._paint()
            self.assertFalse(dpg.get_item_configuration(panel._caret)['show'])
        finally:
            if panel is not None:
                panel.destroy()
            dpg.destroy_context()
