"""SSH TUI keyboard/transport contracts without a live SSH account or GUI."""
import codecs
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.server_model import SSHServerModel
from WinUx.dialogs.console_form import ConsoleDialog, QKeyboard, Qt
from WinUx.runtime.vt_terminal import VTTerminalScreen


class TerminalInteractionTests(unittest.TestCase):
    def test_floating_refresh_event_routes_to_parent_controller(self):
        from WinUx.dialogs.floating_adapters import ConsoleDialog as Adapter
        callback = Mock()
        Adapter.handle_event(SimpleNamespace(refresh_callback=callback), 'refresh', {})
        callback.assert_called_once_with()
        Adapter.handle_event(SimpleNamespace(refresh_callback=None), 'refresh', {})

    def test_floating_delivery_preserves_raw_cursor_metadata(self):
        from WinUx.dialogs.floating_forms import deliver_command
        from WinUx.dialogs.native_dock_forms import ConsoleDockForm
        snapshot = {'text': 'raw data', 'end': 12345, 'generation': 'session'}
        form = SimpleNamespace(_floating_kind='console', _remote_state={}, _update_raw_terminal=lambda: None)
        deliver_command(form, 'raw_output', [snapshot])
        self.assertEqual(form._remote_state['raw_output'], snapshot)
        ConsoleDockForm.handle_command(form, 'raw_output', snapshot)
        self.assertEqual(form._raw_output_state, snapshot)

    def mouse_form(self):
        form, sent = self.form()
        form._vt_screen.feed('\x1b[?1049h\x1b[?1002;1006h')
        form._shift_down = lambda: False
        form._mouse_over_context_menu = lambda: False
        form._over_terminal = lambda: True
        form._cell_from_mouse = lambda: (1, 2)
        form.focus_input = lambda **kwargs: None
        form._remote_mouse_enabled = lambda: ConsoleDialog._remote_mouse_enabled(form)
        return form, sent

    def test_mouse_press_deduplication_drag_and_release(self):
        form, sent = self.mouse_form()
        with patch.object(QKeyboard, 'modifiers', return_value=0):
            self.assertTrue(ConsoleDialog._terminal_mouse_event(form, 0, 'press'))
            ConsoleDialog._terminal_mouse_event(form, 0, 'press')
            ConsoleDialog._terminal_mouse_event(form, 0, 'motion', (1, 3))
            ConsoleDialog._terminal_mouse_event(form, 0, 'motion', (1, 3))
            form._over_terminal = lambda: False  # Release outside still terminates drag.
            ConsoleDialog._terminal_mouse_event(form, 0, 'release', (1, 3))
        self.assertEqual(sent, ['\x1b[<0;3;2M', '\x1b[<32;4;2M', '\x1b[<0;4;2m'])
        self.assertFalse(form._terminal_mouse_buttons)

    def test_shift_uses_local_selection_but_releases_existing_remote_drag(self):
        form, sent = self.mouse_form()
        with patch.object(QKeyboard, 'modifiers', return_value=0):
            ConsoleDialog._terminal_mouse_event(form, 0, 'press')
            form._shift_down = lambda: True
            ConsoleDialog._terminal_mouse_event(form, 0, 'release')
            self.assertFalse(ConsoleDialog._terminal_mouse_event(form, 0, 'press'))
        self.assertEqual(len(sent), 2)
        self.assertTrue(sent[-1].endswith('m'))

    def test_hover_motion_never_steals_keyboard_focus(self):
        form, sent = self.mouse_form()
        form._vt_screen.feed('\x1b[?1003h')
        form.focus_input = lambda **kwargs: self.fail('Hover stole keyboard focus')
        with patch.object(QKeyboard, 'modifiers', return_value=0):
            ConsoleDialog._terminal_mouse_event(form, None, 'motion')
        self.assertEqual(sent, ['\x1b[<35;3;2M'])

    def form(self, focused=True, ctrl=False):
        sent = []
        form = SimpleNamespace(
            _raw_terminal_active=lambda: True,
            keyboard_active=lambda: focused,
            _context_menu_obj=None,
            _ctrl_down=lambda: ctrl,
            _send_raw=lambda value: sent.append(value),
            _vt_screen=VTTerminalScreen(),
        )
        form._raw_keyboard_owned = lambda: ConsoleDialog._raw_keyboard_owned(form)
        return form, sent

    def test_nano_save_exit_and_vim_controls_forward_exactly_once(self):
        form, sent = self.form(ctrl=True)
        with patch.object(QKeyboard, 'modifiers', return_value=Qt.ControlModifier):
            for key in (Qt.Key_O, Qt.Key_X, Qt.Key_C, Qt.Key_R, Qt.Key_W, Qt.Key_Z):
                ConsoleDialog._raw_control_key(form, user_data=key)
        self.assertEqual(sent, ['\x0f', '\x18', '\x03', '\x12', '\x17', '\x1a'])

    def test_background_console_cannot_send_control_or_function_keys(self):
        form, sent = self.form(focused=False, ctrl=True)
        ConsoleDialog._raw_control_key(form, user_data=Qt.Key_X)
        ConsoleDialog._raw_function_key(form, user_data=Qt.Key_F2)
        ConsoleDialog._raw_sequence_callback(form, user_data='\x1b[5~')
        self.assertEqual(sent, [])

    def test_context_menu_keeps_keyboard_ownership(self):
        form, sent = self.form(ctrl=True)
        form._context_menu_obj = SimpleNamespace(is_open=True)
        ConsoleDialog._raw_control_key(form, user_data=Qt.Key_X)
        self.assertEqual(sent, [])

    def test_function_keys_and_application_cursor(self):
        form, sent = self.form()
        ConsoleDialog._raw_function_key(form, user_data=Qt.Key_F2)
        ConsoleDialog._raw_function_key(form, user_data=Qt.Key_F12)
        form._vt_screen.application_cursor = True
        with patch.object(QKeyboard, 'modifiers', return_value=0):
            ConsoleDialog._raw_cursor_special(form, '\x1b[A', '\x1bOA')
        with patch.object(QKeyboard, 'modifiers', return_value=Qt.ControlModifier):
            ConsoleDialog._raw_cursor_special(form, '\x1b[D', '\x1bOD')
        self.assertEqual(sent, ['\x1bOQ', '\x1b[24~', '\x1bOA', '\x1b[1;5D'])

    def test_paste_keeps_line_breaks_and_brackets(self):
        form, sent = self.form()
        form._vt_screen.bracketed_paste = True
        with patch('WinUx.dialogs.console_form._win_clipboard_text_get', return_value='one\r\ntwo'):
            ConsoleDialog._paste_clipboard(form)
        self.assertEqual(sent, ['\x1b[200~one\ntwo\x1b[201~'])

    def test_nonletter_control_and_alt_character(self):
        form, sent = self.form(ctrl=True)
        form.winfo_exists = lambda: True
        form._surrogate = None
        ConsoleDialog.native_character(form, 27)
        ConsoleDialog.native_character(form, 31)
        # A-Z control bytes have already been sent by keydown handlers.
        ConsoleDialog.native_character(form, 15)
        with patch.object(QKeyboard, 'modifiers', return_value=Qt.AltModifier):
            ConsoleDialog.native_character(form, ord('u'))
        self.assertEqual(sent, ['\x1b', '\x1f', '\x1bu'])

    def test_raw_transport_preserves_bytes_and_partial_writes(self):
        server = SSHServerModel()
        writes = []

        def send(payload):
            writes.append(payload[:2])
            return min(2, len(payload))

        server.shell = SimpleNamespace(closed=False, send=send)
        server.send_shell_input('Việt\x1b[A\x0f')
        self.assertEqual(b''.join(writes), 'Việt\x1b[A\x0f'.encode('utf-8'))

    def test_closed_channel_during_write_raises(self):
        server = SSHServerModel()
        server.shell = SimpleNamespace(closed=False, send=lambda data: 0)
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            server.send_shell_input('text')

    def test_full_screen_blocks_internal_cd_and_job_command(self):
        server = SSHServerModel()
        writes = []
        server.shell = SimpleNamespace(closed=False, send=writes.append)
        server._shell_alt_screen_active = True
        self.assertFalse(server.set_shell_directory('/work'))
        with self.assertRaisesRegex(RuntimeError, 'full-screen'):
            server.send_shell_command('nohup abaqus job=model')
        self.assertEqual(writes, [])
        self.assertIsNone(server._shell_directory)

    def test_pty_resize_calls_channel_in_cells(self):
        server = SSHServerModel()
        sizes = []
        server.shell = SimpleNamespace(closed=False, resize_pty=lambda **kwargs: sizes.append(kwargs))
        self.assertTrue(server.resize_shell_pty(132, 43))
        self.assertEqual(sizes, [{'width': 132, 'height': 43}])

    def test_utf8_characters_split_at_every_byte(self):
        # Same incremental decoder used by the SSH reader, not per-recv decode.
        payload = 'Tiếng Việt'.encode('utf-8')
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        text = ''.join(decoder.decode(bytes([byte])) for byte in payload)
        self.assertEqual(text, 'Tiếng Việt')


if __name__ == '__main__':
    unittest.main(verbosity=2)
