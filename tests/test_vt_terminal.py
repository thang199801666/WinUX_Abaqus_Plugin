import unittest

from WinUx.runtime.vt_terminal import VTTerminalScreen, DEFAULT_FG, DEFAULT_BG


class VTTerminalScreenTests(unittest.TestCase):
    def screen(self, columns=10, rows=4):
        vt = VTTerminalScreen(columns, rows)
        vt.feed('\x1b[?1049h')
        return vt

    def test_last_cell_does_not_scroll_until_next_printable_character(self):
        vt = self.screen(4, 2)
        vt.feed('abcd\r\nefgh')
        self.assertEqual(vt.text_rows(), ['abcd', 'efgh'])
        vt.feed('i')
        self.assertEqual(vt.text_rows(), ['efgh', 'i   '])

    def test_explicit_cursor_move_cancels_pending_wrap(self):
        vt = self.screen(4, 2)
        vt.feed('abcd\x1b[1;1HX')
        self.assertEqual(vt.text_rows(), ['Xbcd', '    '])

    def test_ncurses_no_wrap_bottom_right_corner(self):
        vt = self.screen(4, 2)
        vt.feed('\x1b[?7l\x1b[2;1HabcdX')
        self.assertEqual(vt.text_rows(), ['    ', 'abcX'])

    def test_resize_expands_full_scroll_region(self):
        vt = self.screen(4, 2)
        vt.resize(6, 5)
        self.assertEqual((vt.scroll_top, vt.scroll_bottom), (0, 4))
        vt.feed('\x1b[5;1Hbottom')
        self.assertEqual(vt.text_rows()[4], 'bottom')

    def test_nano_reverse_video_menu_and_sgr_reset(self):
        vt = self.screen(20, 3)
        vt.feed('\x1b[7m GNU nano \x1b[0mtext')
        runs = vt.styled_rows()[0]
        self.assertEqual(runs[0], ((DEFAULT_BG, DEFAULT_FG, False), ' GNU nano '))
        self.assertEqual(runs[1][0], (DEFAULT_FG, DEFAULT_BG, False))

    def test_vim_256_color_truecolor_and_underline(self):
        vt = self.screen()
        vt.feed('\x1b[38;5;196;48;2;10;20;30;4mX\x1b[0mY')
        self.assertEqual(vt.styled_rows()[0][0],
                         (((255, 0, 0, 255), (10, 20, 30, 255), True), 'X'))
        self.assertEqual(vt.styled_rows()[0][1][0], (DEFAULT_FG, DEFAULT_BG, False))

    def test_erase_uses_current_background_and_scroll_moves_styles(self):
        vt = self.screen(4, 2)
        vt.feed('\x1b[41m\x1b[2J\x1b[32mAB\x1b[2;1HCD\n')
        self.assertTrue(vt.text_rows()[0].startswith('CD'))
        self.assertEqual(vt.styled_rows()[0][0][0][1], (205, 49, 49, 255))
        self.assertEqual(vt.styled_rows()[1][0][0][1], (205, 49, 49, 255))

    def test_insert_delete_cells_keep_matching_styles(self):
        vt = self.screen(6, 2)
        vt.feed('\x1b[31mABC\x1b[32mDEF\x1b[1;2H\x1b[2P\x1b[1@')
        self.assertEqual(vt.text_rows()[0], 'A DEF ')
        self.assertEqual(len(vt._styles[0]), 6)
        self.assertEqual(vt._styles[0][0][0], (205, 49, 49, 255))
        self.assertEqual(vt._styles[0][2][0], (13, 188, 121, 255))

    def test_insert_delete_lines_keep_matching_styles(self):
        vt = self.screen(4, 3)
        vt.feed('\x1b[31mA\x1b[2;1H\x1b[32mB\x1b[3;1HC\x1b[1;1H\x1b[L')
        self.assertTrue(vt.text_rows()[1].startswith('A'))
        self.assertEqual(vt._styles[1][0][0], (205, 49, 49, 255))
        vt.feed('\x1b[M')
        self.assertTrue(vt.text_rows()[0].startswith('A'))
        self.assertEqual(vt._styles[0][0][0], (205, 49, 49, 255))

    def test_origin_mode_and_normal_cursor_position_outside_scroll_region(self):
        vt = self.screen(10, 6)
        vt.feed('\x1b[2;5r\x1b[6;1Hbottom')
        self.assertEqual(vt.cursor_row, 5)
        vt.feed('\x1b[?6h\x1b[1;1Horigin')
        self.assertTrue(vt.text_rows()[1].startswith('origin'))
        vt.feed('\x1b[99B')
        self.assertEqual(vt.cursor_row, 4)
        vt.feed('\x1b[?6l\x1b[1;1Htop')
        self.assertTrue(vt.text_rows()[0].startswith('top'))

    def test_device_queries_are_incremental_and_drained_once(self):
        vt = self.screen()
        for char in '\x1b[3;4H\x1b[6n\x1b[5n\x1b[c\x1b[>c':
            vt.feed(char)
        self.assertEqual(vt.drain_replies(), '\x1b[3;4R\x1b[0n\x1b[?1;2c\x1b[>0;1;0c')
        self.assertEqual(vt.drain_replies(), '')

    def test_save_restore_cursor_also_restores_attributes(self):
        vt = self.screen()
        vt.feed('\x1b[31m\x1b[2;3H\x1b7\x1b[32m\x1b[1;1HX\x1b8Y')
        self.assertEqual(vt.text_rows()[1][2], 'Y')
        self.assertEqual(vt._styles[1][2][0], (205, 49, 49, 255))

    def test_ncurses_repeat_and_line_drawing(self):
        vt = self.screen(12, 3)
        vt.feed('\x1b(0lq\x1b[5bk\x1b(B')
        self.assertTrue(vt.text_rows()[0].startswith('┌──────┐'))

    def test_nano_style_session_is_identical_at_every_chunk_boundary(self):
        stream = ('\x1b[?1049h\x1b[?1h\x1b[?7l\x1b[2J\x1b[H'
                  '\x1b[7m GNU nano \x1b[0m\x1b[2;1Hhello world'
                  '\x1b[4;1H\x1b[7m^O Write Out  ^X Exit\x1b[0m\x1b[2;6H')
        reference = VTTerminalScreen(24, 4)
        reference.feed(stream)
        for split in range(len(stream) + 1):
            vt = VTTerminalScreen(24, 4)
            vt.feed(stream[:split])
            vt.feed(stream[split:])
            self.assertEqual(vt.styled_rows(), reference.styled_rows(), split)
            self.assertEqual((vt.cursor_row, vt.cursor_col), (1, 5))

    def test_ignores_normal_shell_and_enters_alt_screen(self):
        vt = VTTerminalScreen(20, 5)
        vt.feed("prompt$ nano a.txt\r\n")
        self.assertFalse(vt.active)
        vt.feed("\x1b[?1049h\x1b[2J\x1b[Hhello")
        self.assertTrue(vt.active)
        self.assertTrue(vt.text_rows()[0].startswith("hello"))

    def test_cursor_position_and_erase_line(self):
        vt = VTTerminalScreen(10, 4)
        vt.feed("\x1b[?1049h\x1b[2;3Habc\x1b[2;4H\x1b[K")
        self.assertEqual(vt.text_rows()[1][:3], "  a")
        self.assertEqual(vt.text_rows()[1][3:], " " * 7)

    def test_split_escape_sequence_across_chunks(self):
        vt = VTTerminalScreen(10, 4)
        vt.feed("\x1b[?104")
        self.assertFalse(vt.active)
        vt.feed("9hfoo")
        self.assertTrue(vt.active)
        self.assertTrue(vt.text_rows()[0].startswith("foo"))

    def test_alt_exit_restores_line_mode(self):
        vt = VTTerminalScreen(10, 4)
        vt.feed("\x1b[?1049hfoo\x1b[?1049lprompt$ ")
        self.assertFalse(vt.active)

    def test_scroll_region(self):
        vt = VTTerminalScreen(8, 3)
        vt.feed("\x1b[?1049h\x1b[1;1HA\x1b[2;1HB\x1b[3;1HC\x1b[3;1H\n")
        rows = vt.text_rows()
        self.assertTrue(rows[0].startswith("B"))
        self.assertTrue(rows[1].startswith("C"))

    def test_tracks_application_cursor_and_bracketed_paste_modes(self):
        vt = VTTerminalScreen(10, 4)
        vt.feed("\x1b[?1049h\x1b[?1h\x1b[?2004h")
        self.assertTrue(vt.application_cursor)
        self.assertTrue(vt.bracketed_paste)
        vt.feed("\x1b[?1l\x1b[?2004l")
        self.assertFalse(vt.application_cursor)
        self.assertFalse(vt.bracketed_paste)


if __name__ == "__main__":
    unittest.main()
