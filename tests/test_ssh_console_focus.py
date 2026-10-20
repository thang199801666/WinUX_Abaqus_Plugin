"""Terminal click/caret behavior independent of native viewport timing."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from WinUx.runtime.terminal_buffer import TerminalBuffer
from tests.test_ssh_console_menu_actions import load_methods


class TerminalMouseCaretTests(unittest.TestCase):
    def setUp(self):
        self.buffer = TerminalBuffer()
        self.buffer.set_output('old output\n$ ')
        self.buffer.type_text('abcdefghijklmno')

    def test_wrapped_draft_click_inserts_at_clicked_character(self):
        self.assertTrue(self.buffer.move_cursor_to_cell(8, 3, 3))
        self.assertEqual(self.buffer.cursor, 9)
        self.buffer.type_text('X')
        self.assertEqual(self.buffer.draft, 'abcdefghiXjklmno')

    def test_prompt_and_scrollback_clicks_preserve_caret(self):
        for row, column in ((0, 2), (1, 0), (5, 0)):
            self.assertFalse(self.buffer.move_cursor_to_cell(8, row, column))
            self.assertEqual(self.buffer.cursor, 15)

    def test_tabs_and_wrapping_match_rendered_caret_cells(self):
        self.buffer.draft = 'a\tbcd\tef'
        for columns in (8, 11, 40):
            for offset in range(len(self.buffer.draft) + 1):
                self.buffer.cursor = offset
                _, row, column = self.buffer.layout(columns)
                self.buffer.move_end()
                self.assertTrue(self.buffer.move_cursor_to_cell(columns, row, column))
                self.assertEqual(self.buffer.cursor, offset)

    def test_pending_command_cannot_be_repositioned(self):
        self.buffer.begin_submit()
        self.assertFalse(self.buffer.move_cursor_to_cell(8, 1, 3))
        self.assertEqual(self.buffer.cursor, 15)


class ConsoleFocusTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.get_mouse_pos.return_value = (10, 10)
        self.queued = []
        self.view = SimpleNamespace(
            after=lambda delay, callback, *args: self.queued.append((callback, args)),
            _set_console_keyboard_active=Mock())
        self.panel = SimpleNamespace(
            view=self.view, winfo_exists=lambda: True,
            _mouse_over_context_menu=lambda: False,
            _terminal_rect_contains=lambda pos: pos == (10, 10),
            focus_input=Mock(), _hide_context_menu=Mock(),
            _over_terminal=Mock(return_value=True),
            _suppress_left_click_until=0, _last_click_row=None,
            _last_click_time=0, _click_count=0, _find_active=False,
            _scroll_pending=True, _follow_tail=True,
            _cell_from_mouse=Mock(return_value=(1, 4)),
            _render_columns=8, buffer=TerminalBuffer())
        self.panel.buffer.set_output('output\n$ ')
        self.panel.buffer.type_text('abcdef')
        self.methods = load_methods('ConsoleDialog', [
            '_mouse_click', '_deactivate_keyboard_if_pointer_outside',
            '_canvas_left_click', '_mouse_release', '_edited', '_clear_selection',
        ], dpg=self.backend, time=time)
        for name, method in self.methods.items():
            setattr(self.panel, name, lambda *args, _method=method: _method(self.panel, *args))

    def drain(self):
        for callback, args in self.queued:
            callback(*args)
        self.queued.clear()

    def test_inside_click_does_not_lose_focus_if_pointer_moves_before_queue_drains(self):
        self.panel._mouse_click()
        self.backend.get_mouse_pos.return_value = (500, 500)
        self.drain()
        self.view._set_console_keyboard_active.assert_not_called()
        self.panel.focus_input.assert_called_once_with(follow_tail=False, focus_window=False)
        self.panel._over_terminal.assert_called_once_with()

    def test_outside_click_releases_focus_even_if_pointer_returns_before_queue_drains(self):
        self.backend.get_mouse_pos.return_value = (500, 500)
        self.panel._mouse_click()
        self.backend.get_mouse_pos.return_value = (10, 10)
        self.drain()
        self.view._set_console_keyboard_active.assert_called_once_with(False, self.panel)

    def test_single_click_repositions_only_draft_without_scrolling(self):
        self.panel._canvas_left_click()
        self.panel._mouse_release()
        self.assertEqual(self.panel.buffer.cursor, 2)
        self.assertFalse(self.panel._scroll_pending)
        self.assertFalse(self.panel._follow_tail)
        self.assertIsNone(self.panel._selection_anchor)
        self.backend.focus_item.assert_not_called()

    def test_drag_selects_output_without_moving_command_caret(self):
        self.panel._cell_from_mouse.return_value = (0, 0)
        self.panel._canvas_left_click()
        self.panel._cell_from_mouse.return_value = (0, 4)
        self.panel._mouse_release()
        self.assertEqual(self.panel.buffer.cursor, 6)
        self.assertEqual(self.panel._selection_anchor, (0, 0))
        self.assertEqual(self.panel._selection_focus, (0, 4))

    def test_edit_clears_scrollback_selection(self):
        self.panel._selection_anchor, self.panel._selection_focus = (0, 0), (0, 4)
        self.panel._selection_dragging = True
        self.panel._edited()
        self.assertIsNone(self.panel._selection_anchor)
        self.assertIsNone(self.panel._selection_focus)
        self.assertFalse(self.panel._selection_dragging)

    def test_overlapping_window_does_not_activate_terminal(self):
        self.panel._over_terminal.return_value = False
        self.panel._mouse_click()
        self.drain()
        self.panel.focus_input.assert_not_called()
        self.view._set_console_keyboard_active.assert_not_called()

    def test_inside_click_with_stale_hover_does_not_queue_focus_deactivation(self):
        self.panel._over_terminal.return_value = False
        self.panel._mouse_click()
        # The item-scoped handler activates the terminal independently of
        # the global observer's stale child hover flag.
        self.panel._canvas_left_click()
        self.panel._mouse_release()
        self.drain()
        self.view._set_console_keyboard_active.assert_not_called()
        self.panel.focus_input.assert_called_once_with(follow_tail=False, focus_window=False)

    def test_child_without_rect_min_uses_screen_space_window_bounds(self):
        self.backend.get_item_rect_min.side_effect = KeyError('rect_min')
        bounds = Mock(return_value=(100, 200, 600, 400))
        methods = load_methods('ConsoleDialog', ['_terminal_rect_contains'],
                               dpg=self.backend, dpg_window_rect=bounds)
        self.panel.content = 'terminal_child'
        self.assertTrue(methods['_terminal_rect_contains'](self.panel, (150, 250)))
        self.assertFalse(methods['_terminal_rect_contains'](self.panel, (150, 450)))
        bounds.assert_called_with(self.backend, 'terminal_child', clip=True)

    def test_queued_native_character_does_not_edit_after_focus_changes(self):
        methods = load_methods('ConsoleDialog', ['native_character'])
        self.panel.keyboard_active = lambda: False
        methods['native_character'](self.panel, ord('X'))
        self.assertEqual(self.panel.buffer.draft, 'abcdef')

    def test_queued_editor_key_does_not_run_after_focus_has_changed(self):
        methods = load_methods('ConsoleDockPanel', ['_dock_key_callback', '_run_dock_key'])
        active = [True]
        self.panel.keyboard_active = lambda: active[0]
        self.panel._run_dock_key = lambda callback: methods['_run_dock_key'](self.panel, callback)
        action = Mock()
        methods['_dock_key_callback'](self.panel, user_data=action)
        active[0] = False
        self.drain()
        action.assert_not_called()
