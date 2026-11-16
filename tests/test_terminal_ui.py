"""Real docked terminal paint/input smoke test; no mouse/keyboard injection."""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from DearUIQt.core import Qt
from WinUx.dialogs.console_form import QKeyboard


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-terminal-ui-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            state = {'raw': '[test@host ~]$ ', 'visible': '[test@host ~]$ ',
                     'generation': 'test-session', 'connected': True}
            sent, sizes = [], []
            refresh_requests = []
            def refresh_console():
                refresh_requests.append(True)
                state.update(raw='[test@host /work]$ ', visible='[test@host /work]$ ',
                             generation='refreshed-session')
            callbacks = {key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS}
            callbacks.update(console_output=lambda: state['visible'],
                             console_raw_output=lambda: {'text': state['raw'], 'end': len(state['raw']), 'generation': state['generation']},
                             console_connected=lambda: state['connected'],
                             console_refresh=refresh_console,
                             console_input=lambda data: sent.append(data),
                             console_resize=lambda columns, rows: sizes.append((columns, rows)))
            # This test exercises the embedded canvas, not native undock hosts.
            with patch.object(WinUXView, '_prepare_console_native_host', return_value=False):
                view = WinUXView(callbacks)
                try:
                    view._gui_runtime.show()
                    view.set_console_visible(True, request_login=False)
                    panel = view.console_panel

                    def pump(count=15):
                        for _ in range(count):
                            view.update()
                            time.sleep(.01)

                    pump()
                    panel.focus_input()
                    state['raw'] += ('\x1b[?1049h\x1b[?1h\x1b[?7l\x1b[2J\x1b[H'
                                     '\x1b[7m GNU nano 8.0 \x1b[0m\x1b[2;1Hhello world'
                                     '\x1b[3;1H\x1b[38;5;196;48;2;30;40;50mcolored\x1b[0m'
                                     '\x1b[4;1HVie\u0323\u0302t 界\x1b[?1002;1006h')
                    panel._update_raw_terminal()
                    pump()
                    assert panel._raw_terminal_active()
                    assert panel._line_items, 'VT grid was not painted'
                    assert sizes, 'PTY dimensions were not propagated'
                    assert panel._vt_screen.text_rows()[0].startswith(' GNU nano')
                    panel._selection_anchor, panel._selection_focus = (3, 0), (3, 4)
                    assert panel._selected_text() == 'Việt'
                    panel._clear_selection()
                    with patch.object(panel, '_over_terminal', return_value=True), \
                            patch.object(panel, '_cell_from_mouse', return_value=(1, 3)), \
                            patch.object(QKeyboard, 'modifiers', return_value=0):
                        assert panel._terminal_mouse_event(0, 'press')
                        assert panel._terminal_mouse_event(0, 'release')
                    assert sent[-2:] == ['\x1b[<0;4;2M', '\x1b[<0;4;2m']
                    with patch.object(QKeyboard, 'modifiers', return_value=Qt.ControlModifier):
                        panel._raw_control_key(user_data=Qt.Key_O)
                        panel._raw_control_key(user_data=Qt.Key_X)
                    assert sent[-2:] == ['\x0f', '\x18']
                    state['raw'] += '\x1b[2;4H\x1b[6n'
                    panel._update_raw_terminal()
                    assert sent[-1] == '\x1b[2;4R'
                    state['raw'] += '\x1b[?1049l[test@host ~]$ '
                    panel._update_raw_terminal()
                    pump()
                    assert not panel._raw_terminal_active()
                    state['visible'] = ''.join('row {}\n'.format(i) for i in range(1000)) + '[test@host ~]$ '
                    panel._refresh()
                    pump()
                    assert not isinstance(panel._render_rows, list), 'Renderer copied full scrollback'
                    panel._selection_anchor, panel._selection_focus = (10, 0), (12, 6)
                    assert panel._selected_text() == 'row 10\nrow 11\nrow 12'
                    panel._clear_selection()
                    panel._find_query, panel._find_active = 'row 999', True
                    panel._rebuild_find_matches(panel._render_columns)
                    assert panel._find_matches == [(999, 0, 7)]
                    panel._find_active = False
                    view.set_console_visible(False, request_login=False)
                    pump(4)
                    with patch.object(panel.buffer, 'layout_view', wraps=panel.buffer.layout_view) as layout:
                        panel._paint()
                        layout.assert_not_called()
                    # Hidden painting must not suspend VT stream consumption.
                    state['raw'] += '\x1b[?1049h\x1b[2J\x1b[Hhidden editor output'
                    panel._refresh()
                    assert panel._vt_screen.text_rows()[0].startswith('hidden editor output')
                    view.set_console_visible(True, request_login=False)
                    pump()
                    assert panel._line_items
                    panel.buffer.type_text('unsaved draft')
                    panel._clear_base = 'old transcript'
                    panel._completion_pending = object()
                    panel._find_active, panel._find_query = True, 'old query'
                    panel._prepare_context_menu_state()
                    spec = panel._context_menu_obj._find_spec('refresh')
                    assert spec['label'] == 'Refresh SSH Console' and spec['enabled']
                    state['connected'] = False
                    panel._prepare_context_menu_state()
                    assert not panel._context_menu_obj._find_spec('refresh')['enabled']
                    state['connected'] = True
                    panel._context_menu_triggered('refresh')
                    panel._refresh()
                    pump()
                    assert refresh_requests == [True]
                    assert panel.buffer.output == '[test@host /work]$ '
                    assert panel.buffer.draft == '' and panel._clear_base is None
                    assert panel._completion_pending is None and not panel._find_active
                    assert not panel._raw_terminal_active()
                    print('PASS: real VT canvas colors, Unicode selection, mouse reports, input, resize and shell restore', flush=True)
                    print('PASS: Refresh SSH Console menu, offline guard, fresh stream, cleared draft/search/completion and alternate-screen reset', flush=True)
                finally:
                    view.request_shutdown()
                    view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
