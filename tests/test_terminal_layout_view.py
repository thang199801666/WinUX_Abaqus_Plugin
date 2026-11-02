"""Read-only terminal row view preserves selection/find and snapshot semantics."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.runtime.terminal_buffer import TerminalBuffer
from WinUx.runtime.vt_terminal import VTTerminalScreen
from WinUx.ui.components.console_renderer import ConsoleRenderer


class LayoutViewTests(unittest.TestCase):
    def test_view_matches_legacy_rows_and_cursor(self):
        buffer = TerminalBuffer()
        buffer.set_output('first\n\n1234567890\nlast prompt> ')
        buffer.draft, buffer.cursor = 'a\tb', 2
        for columns in (8, 12, 80):
            full, row, col = buffer.layout(columns)
            view, r, c = buffer.layout_view(columns)
            self.assertEqual(list(view), full)
            self.assertEqual((r, c), (row, col))
            for key in (slice(None), slice(1, -1), slice(None, None, -1), slice(-100, 100, 2)):
                self.assertEqual(view[key], full[key])
            for index in range(-len(full), len(full)):
                self.assertEqual(view[index], full[index])
            with self.assertRaises(IndexError):
                _ = view[len(full)]
            with self.assertRaises(TypeError):
                view[0] = 'cannot mutate'

    def test_old_view_survives_output_replacement_resize_and_clear(self):
        buffer = TerminalBuffer()
        buffer.set_output('original\nold prompt ')
        old, _, _ = buffer.layout_view(8)
        snapshot = list(old)
        buffer.set_output('new\n')
        buffer.layout_view(80)
        buffer.clear_output()
        self.assertEqual(list(old), snapshot)

    def test_view_reuses_prefix_and_preserves_find(self):
        buffer = TerminalBuffer()
        buffer.set_output('find me\n' * 1000)
        view, _, _ = buffer.layout_view(80)
        self.assertIs(view._prefix, buffer._prefix_rows)
        self.assertEqual(len(TerminalBuffer.find_matches(view, 'find')), 1000)
        full, _, _ = buffer.layout(80)
        full[0] = 'independent list'
        self.assertEqual(view[0], 'find me')

    def test_vt_slice_preserves_styles_wide_and_combining_cells(self):
        vt = VTTerminalScreen(20, 6)
        vt.feed('\x1b[?1049h\x1b[31mred\x1b[0m\r\nViệt 界\r\nthird')
        full = vt.styled_rows()
        for start, stop in ((0, 1), (1, 3), (-3, None), (3, 1), (0, 100)):
            self.assertEqual(vt.styled_rows(start, stop), full[start:stop])
        for row, runs in zip(vt.text_rows(), full):
            self.assertEqual(''.join(text for style, text in runs), row)

    def test_hidden_console_skips_layout_and_releases_chrome_grab(self):
        palette = {name: None for name in (
            'COMMAND', 'FIND_BG', 'FIND_BORDER', 'FIND_CURRENT', 'FIND_MATCH',
            'FIND_MUTED', 'FIND_TEXT', 'SELECTION', 'STYLE_COLORS', 'TEXT')}
        view = SimpleNamespace(content='content', canvas='canvas', _scroller_arrow_overlay=Mock())
        renderer = ConsoleRenderer(view, Mock(), palette)
        with patch.object(renderer, '_item', return_value=SimpleNamespace(
                nativeState=lambda: {'visible': False, 'rect_size': (800, 200)})), \
                patch('WinUx.ui.components.console_renderer.QFontMetrics') as metrics, \
                patch('WinUx.ui.components.console_renderer.QPainter') as painter:
            renderer.paint()
            metrics.assert_not_called()
            painter.assert_not_called()
        view._scroller_arrow_overlay.hide.assert_called_once()

    def test_hidden_ancestor_overrides_stale_visible_child_state(self):
        renderer = ConsoleRenderer.__new__(ConsoleRenderer)
        content = SimpleNamespace(isVisible=lambda: True, parentItem=lambda: 'hidden dock')
        ancestor = SimpleNamespace(isVisible=lambda: False)
        with patch.object(renderer, '_item', return_value=ancestor):
            self.assertFalse(renderer._viewport_shown(content, {'visible': True}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
