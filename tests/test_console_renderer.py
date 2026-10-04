from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.components.console_renderer import ConsoleRenderer
from WinUx.runtime.terminal_buffer import TerminalBuffer


def fixture():
    backend = Mock()
    backend.get_item_state.return_value = {'rect_size': (640, 240)}
    backend.get_y_scroll.return_value = 0
    backend.get_y_scroll_max.return_value = 0
    backend.does_item_exist.return_value = True
    backend.draw_text.side_effect = iter(range(1000, 2000))
    buffer = TerminalBuffer()
    buffer.set_output('line1\nline2\n$ ')
    view = SimpleNamespace(content=1, canvas=2, _caret=3, _current_line_fill=4,
        buffer=buffer, _font=None, _char_width=8, _line_height=17,
        _find_active=False, _find_query='', _find_index=-1, _find_matches=[],
        _find_dirty=False, _find_columns=None, _find_pending_scroll=False,
        _scroll_pending=False, _selection_dragging=False, _follow_tail=True,
        _last_paint=None, _selection_items=[], _find_items=[], _find_match_items=[],
        _selection_bounds=Mock(return_value=None), _rebuild_find_matches=Mock())
    colors = {key: (100, 100, 100, 255) for key in ('COMMAND', 'FIND_BG', 'FIND_BORDER',
        'FIND_CURRENT', 'FIND_MATCH', 'FIND_MUTED', 'FIND_TEXT', 'SELECTION', 'TEXT')}
    colors['STYLE_COLORS'] = {}
    return view, backend, ConsoleRenderer(view, backend, colors)


class ConsoleRendererTests(unittest.TestCase):
    def paint_at(self, renderer, now):
        with patch('WinUx.components.console_renderer.time.monotonic', return_value=now):
            renderer.paint()

    def test_blink_changes_only_caret_without_recreating_text(self):
        view, backend, renderer = fixture()
        self.paint_at(renderer, 0)
        items = tuple(view._line_items)
        backend.reset_mock()
        self.paint_at(renderer, .51)
        self.assertEqual(tuple(view._line_items), items)
        backend.draw_text.assert_not_called()
        backend.delete_item.assert_not_called()
        backend.configure_item.assert_called_once()
        self.assertEqual(backend.configure_item.call_args.args, (view._caret,))
        self.assertFalse(backend.configure_item.call_args.kwargs['show'])

    def test_unchanged_frame_skips_all_native_writes(self):
        _, backend, renderer = fixture()
        self.paint_at(renderer, .1)
        backend.reset_mock()
        self.paint_at(renderer, .2)
        backend.configure_item.assert_not_called()
        backend.draw_text.assert_not_called()
        backend.delete_item.assert_not_called()

    def test_output_and_font_geometry_changes_repaint_text(self):
        view, backend, renderer = fixture()
        self.paint_at(renderer, 0)
        original = tuple(view._line_items)
        view.buffer.set_output('changed\n$ ')
        self.paint_at(renderer, 0)
        self.assertNotEqual(tuple(view._line_items), original)
        backend.reset_mock()
        view._font = 10
        backend.get_text_size.return_value = (9, 18)
        self.paint_at(renderer, 0)
        backend.draw_text.assert_called()
        backend.bind_item_font.assert_called()

    def test_find_and_pending_command_suppress_caret(self):
        view, backend, renderer = fixture()
        self.paint_at(renderer, 0)
        for change in ('find', 'pending'):
            if change == 'find':
                view._find_active = True
            else:
                view._find_active = False
                view.buffer.pending = 'command'
            backend.reset_mock()
            self.paint_at(renderer, 0)
            caret_calls = [call for call in backend.configure_item.call_args_list if call.args == (view._caret,)]
            self.assertEqual(len(caret_calls), 1)
            self.assertFalse(caret_calls[0].kwargs['show'])

    def test_selection_invalidation_redraws_rectangles(self):
        view, backend, renderer = fixture()
        self.paint_at(renderer, 0)
        view._selection_bounds.return_value = ((0, 0), (0, 3))
        view._last_paint = None
        backend.reset_mock()
        self.paint_at(renderer, 0)
        backend.draw_rectangle.assert_called()
        self.assertEqual(len(view._selection_items), 1)

    def test_resize_reconfigures_canvas_and_repaints(self):
        view, backend, renderer = fixture()
        self.paint_at(renderer, 0)
        backend.get_item_state.return_value = {'rect_size': (320, 240)}
        backend.reset_mock()
        self.paint_at(renderer, 0)
        self.assertIn(view.canvas, [call.args[0] for call in backend.configure_item.call_args_list])
        backend.draw_text.assert_called()


if __name__ == '__main__':
    unittest.main()
