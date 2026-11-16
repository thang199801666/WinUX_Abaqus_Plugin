"""Unicode cells, mouse protocols and long-running bounded raw delivery."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.runtime.vt_terminal import VTTerminalScreen, terminal_text_width
from WinUx.runtime.terminal_stream import TerminalStreamReader
from WinUx.runtime.text_buffer import BoundedTextBuffer


class UnicodeMouseStreamTests(unittest.TestCase):
    def screen(self, columns=12, rows=4):
        vt = VTTerminalScreen(columns, rows)
        vt.feed('\x1b[?1049h')
        return vt

    def test_combining_vietnamese_does_not_advance_cursor(self):
        vt = self.screen()
        for char in 'Vie\u0323\u0302t':
            vt.feed(char)
        self.assertEqual(vt.cursor_col, 4)
        self.assertTrue(vt.text_rows()[0].startswith('Việt'))
        self.assertEqual(terminal_text_width(vt.cell_text(0)), 12)

    def test_wide_characters_take_two_cells(self):
        vt = self.screen()
        vt.feed('A界B')
        self.assertEqual(vt.cursor_col, 4)
        self.assertEqual(vt._screen[0][:4], ['A', '界', '', 'B'])
        self.assertEqual(vt.cell_text(0, 1, 3), '界')
        self.assertEqual(vt.cell_text(0, 2, 3), '界')
        self.assertEqual(terminal_text_width(vt.text_rows()[0]), 12)

    def test_wide_character_wraps_before_right_edge(self):
        vt = self.screen(4, 2)
        vt.feed('abc界Z')
        self.assertEqual(vt.text_rows(), ['abc ', '界Z '])
        self.assertEqual((vt.cursor_row, vt.cursor_col), (1, 3))

    def test_combining_mark_at_pending_wrap_stays_on_last_character(self):
        vt = self.screen(4, 2)
        vt.feed('abce\u0302')
        self.assertEqual(vt.text_rows(), ['abcê', '    '])
        vt.feed('X')
        self.assertEqual(vt.text_rows()[1], 'X   ')

    def test_overwrite_or_erase_continuation_clears_entire_glyph(self):
        vt = self.screen()
        vt.feed('A界B\x1b[1;3HX')
        self.assertEqual(vt._screen[0][:4], ['A', ' ', 'X', 'B'])
        vt.feed('\x1b[1;1H界\x1b[1;2H\x1b[X')
        self.assertEqual(vt._screen[0][:2], [' ', ' '])

    def test_resize_does_not_leave_half_a_wide_character(self):
        vt = self.screen(6, 2)
        vt.feed('abcd界')
        vt.resize(5, 2)
        self.assertEqual(vt.text_rows()[0], 'abcd ')

    def test_insert_delete_preserves_valid_wide_cells(self):
        vt = self.screen(6, 2)
        vt.feed('A界BC\x1b[1;2H\x1b[P')
        self.assertEqual(vt.text_rows()[0], 'A BC  ')
        vt.feed('\x1b[1;2H界\x1b[1;1H\x1b[@')
        self.assertEqual(terminal_text_width(vt.text_rows()[0]), 6)
        self.assertEqual(vt._screen[0][2:4], ['界', ''])

    def test_sgr_press_drag_release_wheel_and_modifiers(self):
        vt = self.screen(120, 40)
        vt.feed('\x1b[?1002;1006h')
        self.assertEqual(vt.mouse_sequence(0, 100, 20), '\x1b[<0;100;20M')
        self.assertEqual(vt.mouse_sequence(0, 101, 20, 'motion'), '\x1b[<32;101;20M')
        self.assertEqual(vt.mouse_sequence(0, 101, 20, 'release'), '\x1b[<0;101;20m')
        self.assertEqual(vt.mouse_sequence(64, 100, 20), '\x1b[<64;100;20M')
        self.assertEqual(vt.mouse_sequence(2, 3, 4, ctrl=True, alt=True), '\x1b[<26;3;4M')
        self.assertEqual(vt.mouse_sequence(None, 3, 4, 'motion'), '')

    def test_mouse_tracking_modes_and_reset(self):
        vt = self.screen()
        vt.feed('\x1b[?1000;1006h')
        self.assertEqual(vt.mouse_sequence(0, 2, 3, 'motion'), '')
        vt.feed('\x1b[?1003h')
        self.assertEqual(vt.mouse_sequence(None, 2, 3, 'motion'), '\x1b[<35;2;3M')
        vt.feed('\x1b[?1003l')
        self.assertEqual(vt.mouse_tracking, 1000)
        vt.feed('\x1b[?1049l')
        self.assertEqual(vt.mouse_sequence(0, 2, 3), '')
        self.assertFalse(vt.mouse_sgr)
        vt.reset()
        self.assertEqual(vt.mouse_tracking, 0)

    def test_legacy_mouse_and_coordinate_bounds(self):
        vt = self.screen()
        vt.feed('\x1b[?1000h')
        self.assertEqual(vt.mouse_sequence(0, 1, 1), '\x1b[M !!')
        self.assertEqual(vt.mouse_sequence(0, 1, 1, 'release'), '\x1b[M#!!')
        vt.feed('\x1b[?1006h')
        self.assertEqual(vt.mouse_sequence(1, -1, 999), '\x1b[<1;1;4M')

    def test_raw_rollover_does_not_reset_or_duplicate_vim_grid(self):
        buffer = BoundedTextBuffer(80)
        reader = TerminalStreamReader()
        vt = VTTerminalScreen(12, 4)
        chunks = ['\x1b[?1049h\x1b[Hvim'] + ['\x1b[2;1Hline {}'.format(i) for i in range(100)]
        for chunk in chunks:
            buffer.append(chunk)
            delta, reset = reader.read({'text': buffer.snapshot(), 'end': buffer.cursor(), 'generation': 'session1'})
            self.assertFalse(reset)
            self.assertEqual(delta, chunk)
            vt.feed(delta)
        self.assertTrue(vt.active)
        self.assertTrue(vt.text_rows()[0].startswith('vim'))
        self.assertTrue(vt.text_rows()[1].startswith('line 99'))
        self.assertEqual(reader.read({'text': buffer.snapshot(), 'end': buffer.cursor(), 'generation': 'session1'}), ('', False))

    def test_reconnect_or_delivery_gap_requires_reset(self):
        reader = TerminalStreamReader()
        reader.read({'text': 'abc', 'end': 3, 'generation': 'one'})
        self.assertEqual(reader.read({'text': 'xyz', 'end': 6, 'generation': 'two'}), ('xyz', True))
        self.assertEqual(reader.read({'text': 'tail', 'end': 100, 'generation': 'two'}), ('tail', True))

    def test_legacy_string_callbacks_remain_supported(self):
        reader = TerminalStreamReader()
        self.assertEqual(reader.read('abc'), ('abc', False))
        self.assertEqual(reader.read('abcdef'), ('def', False))
        self.assertEqual(reader.read('new session'), ('new session', True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
