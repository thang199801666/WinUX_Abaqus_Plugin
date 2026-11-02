"""Console styles scale with the viewport and derived state releases on Clear."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.runtime.terminal_buffer import TerminalBuffer


class TerminalMemoryTests(unittest.TestCase):
    def test_only_requested_rows_are_styled(self):
        buffer = TerminalBuffer()
        buffer.set_output(''.join('row {}\n'.format(i) for i in range(5000)))
        with patch.object(buffer, '_segments', wraps=buffer._segments) as segments:
            rows, _, _ = buffer.styled_layout_slice(100, 100, 132)
            self.assertEqual(len(rows), 32)
            self.assertEqual(segments.call_count, 32)
            self.assertEqual(len(buffer._styled_prefix_rows), 32)
            buffer.styled_layout_slice(100, 100, 132)
            self.assertEqual(segments.call_count, 32)

    def test_cache_bounded_when_scrolling_through_history(self):
        buffer = TerminalBuffer()
        buffer.set_output('line\n' * 2000)
        for start in range(0, 2000, 30):
            buffer.styled_layout_slice(80, start, start + 30)
            self.assertLessEqual(len(buffer._styled_prefix_rows), buffer.STYLED_ROW_CACHE_LIMIT)
        self.assertEqual(buffer.styled_layout_slice(80, 0, 1)[0], [[('output', 'line')]])

    def test_clear_releases_cache_before_next_paint(self):
        buffer = TerminalBuffer()
        buffer.set_output('cached history\n' * 1000)
        buffer.styled_layout_slice(40, 0, 30)
        buffer.draft = 'keep draft'
        buffer.clear_output()
        for value in (buffer.output, buffer.output_styles, buffer._prefix_rows,
                      buffer._prefix_offsets, buffer._styled_prefix_rows, buffer._tail_styles):
            self.assertFalse(value)
        self.assertIsNone(buffer._layout_key)
        self.assertEqual(buffer.draft, 'keep draft')

    def test_output_replacement_invalidates_even_when_not_painted(self):
        buffer = TerminalBuffer()
        buffer.set_output('old\n' * 100)
        buffer.styled_layout_slice(80, 0, 30)
        buffer.set_output('new\n')
        self.assertFalse(buffer._prefix_rows)
        self.assertFalse(buffer._styled_prefix_rows)
        self.assertEqual(buffer.styled_layout_slice(80, 0, 1)[0], [[('output', 'new')]])

    def test_full_layout_and_slices_keep_wrapped_ansi_styles(self):
        buffer = TerminalBuffer()
        buffer.set_output('\x1b[31m123456789012\x1b[0m plain\n\nnext line\nprompt> ')
        buffer.draft = 'command'
        buffer.cursor = 3
        full, row, col = buffer.styled_layout(8)
        for start in range(len(full)):
            selected, r, c = buffer.styled_layout_slice(8, start, start + 1)
            self.assertEqual(selected, full[start:start + 1])
            self.assertEqual((r, c), (row, col))
        self.assertIsInstance(full[0][0][0], tuple)
        buffer.styled_layout(20)
        self.assertLessEqual(len(buffer._styled_prefix_rows), buffer.STYLED_ROW_CACHE_LIMIT)


if __name__ == '__main__':
    unittest.main(verbosity=2)
