from types import SimpleNamespace
import time
from unittest.mock import Mock, patch

from WinUx.ui.components.console_renderer import ConsoleRenderer
from WinUx.runtime.terminal_buffer import TerminalBuffer
from tests.test_ssh_console_menu_actions import load_methods


def _renderer_fixture():
    backend = Mock()
    backend.get_item_state.return_value = {'rect_size': (640, 240)}
    backend.get_y_scroll.return_value = 0
    backend.get_y_scroll_max.return_value = 1000
    backend.does_item_exist.return_value = True
    backend.draw_text.side_effect = iter(range(1000, 5000))
    buffer = TerminalBuffer()
    buffer.set_output('line1\nline2\n$ ')
    view = SimpleNamespace(
        content=1, canvas=2, _caret=3, _current_line_fill=4,
        buffer=buffer, _font=None, _char_width=8, _line_height=17,
        _find_active=False, _find_query='', _find_index=-1, _find_matches=[],
        _find_dirty=False, _find_columns=None, _find_pending_scroll=False,
        _scroll_pending=False, _cursor_scroll_pending=False,
        _manual_scroll_until=0.0, _selection_dragging=False, _follow_tail=True,
        _last_paint=None, _selection_items=[], _find_items=[], _find_match_items=[],
        _selection_bounds=Mock(return_value=None), _rebuild_find_matches=Mock(),
        keyboard_active=Mock(return_value=True), _caret_blink_started=0.0,
    )
    colors = {key: (100, 100, 100, 255) for key in (
        'COMMAND', 'FIND_BG', 'FIND_BORDER', 'FIND_CURRENT', 'FIND_MATCH',
        'FIND_MUTED', 'FIND_TEXT', 'SELECTION', 'TEXT')}
    colors['STYLE_COLORS'] = {}
    return view, backend, ConsoleRenderer(view, backend, colors)


def test_output_growth_preserves_manual_scrollback_position():
    view, backend, renderer = _renderer_fixture()
    with patch('WinUx.ui.components.console_renderer.time.monotonic', return_value=1.0):
        renderer.paint()
    view._follow_tail = False
    view._manual_scroll_until = 5.0
    backend.get_y_scroll.return_value = 180.0
    view.buffer.set_output('\n'.join('line {}'.format(i) for i in range(100)) + '\n$ ')
    backend.reset_mock()
    backend.get_item_state.return_value = {'rect_size': (640, 240)}
    backend.get_y_scroll.return_value = 180.0
    backend.get_y_scroll_max.return_value = 2000.0
    backend.does_item_exist.return_value = True
    backend.draw_text.side_effect = iter(range(5000, 9000))
    with patch('WinUx.ui.components.console_renderer.time.monotonic', return_value=2.0):
        renderer.paint()
    backend.set_y_scroll.assert_any_call(view.content, 180.0)
    assert view._follow_tail is False


def test_new_input_reveals_live_command_after_user_scrolled_away():
    view, backend, renderer = _renderer_fixture()
    view.buffer.set_output('\n'.join('line {}'.format(i) for i in range(80)) + '\n$ ')
    view.buffer.type_text('new command')
    view._follow_tail = True
    view._cursor_scroll_pending = True
    view._manual_scroll_until = 99.0
    backend.get_y_scroll.return_value = 0.0
    backend.get_y_scroll_max.return_value = 1800.0
    with patch('WinUx.ui.components.console_renderer.time.monotonic', return_value=2.0):
        renderer.paint()
    calls = [call for call in backend.set_y_scroll.call_args_list if call.args and call.args[0] == view.content]
    assert calls
    assert calls[-1].args[1] > 0
    assert view._cursor_scroll_pending is False
    assert view._manual_scroll_until == 0.0
    assert view._follow_tail is True


def test_wheel_scroll_disables_pending_autoscroll_in_both_directions():
    dpg = Mock()
    dpg.is_item_hovered.return_value = True
    methods = load_methods('ConsoleDialog', ['_wheel'], dpg=dpg, time=time)
    panel = SimpleNamespace(
        winfo_exists=lambda: True,
        content='terminal',
        _manual_scroll_until=0.0,
        _follow_tail=True,
        _scroll_pending=True,
        _cursor_scroll_pending=True,
    )
    with patch('time.monotonic', return_value=10.0):
        methods['_wheel'](panel, None, 1)
    assert panel._follow_tail is False
    assert panel._scroll_pending is False
    assert panel._cursor_scroll_pending is False
    assert panel._manual_scroll_until > 10.0

    panel._follow_tail = True
    panel._scroll_pending = True
    panel._cursor_scroll_pending = True
    with patch('time.monotonic', return_value=20.0):
        methods['_wheel'](panel, None, -1)
    assert panel._follow_tail is False
    assert panel._scroll_pending is False
    assert panel._cursor_scroll_pending is False
    assert panel._manual_scroll_until > 20.0


def test_docked_focus_does_not_refocus_item_when_keyboard_owner_is_already_active():
    import time as time_module

    dpg = Mock()
    methods = load_methods(
        'ConsoleDockPanel', ['focus_input'], dpg=dpg, time=time_module)
    active = [True]

    def set_owner(value, panel=None):
        active[0] = bool(value)

    panel = SimpleNamespace(
        winfo_exists=lambda: True,
        _caret_blink_started=0.0,
        _follow_tail=False,
        _scroll_pending=False,
        _manual_scroll_until=0.0,
        keyboard_active=lambda: active[0],
        view=SimpleNamespace(_set_console_keyboard_active=set_owner),
        tag='console',
    )
    methods['focus_input'](panel, follow_tail=False, focus_window=True)
    dpg.focus_item.assert_not_called()

    active[0] = False
    methods['focus_input'](panel, follow_tail=False, focus_window=True)
    dpg.focus_item.assert_called_once_with('console')
