"""Behavioral coverage for the CMD-style inline SSH terminal line editor."""
import unittest
from unittest.mock import patch
from pathlib import Path

from WinUx.runtime.terminal_buffer import TerminalBuffer, clean_output, parse_ansi_output


class TerminalBufferTests(unittest.TestCase):
    def test_draft_edits_reuse_transcript_styles(self):
        buffer = TerminalBuffer()
        buffer.set_output("Warning: first\ncompleted\nhost$ ")
        buffer.styled_layout(80)
        with patch.object(buffer, "_style_for_output_row", wraps=buffer._style_for_output_row) as classify:
            buffer.type_text("ls")
            rows, row, column = buffer.styled_layout(80)
            classify.assert_not_called()
        self.assertEqual(rows[:2], [[("warning", "Warning: first")], [("success", "completed")]])
        self.assertEqual(rows[-1], [("prompt", "host$ "), ("command", "ls")])
        self.assertEqual((row, column), (2, 8))
        rows[0].clear()
        self.assertEqual(buffer.styled_layout(80)[0][0], [("warning", "Warning: first")])

    def test_transcript_style_cache_refreshes_on_color_width_and_clear(self):
        buffer = TerminalBuffer()
        buffer.set_output("\x1b[31mabcdefghij\x1b[0m\nhost$ ")
        red_rows = buffer.styled_layout(80)[0]
        buffer.set_output("\x1b[32mabcdefghij\x1b[0m\nhost$ ")
        green_rows = buffer.styled_layout(80)[0]
        self.assertNotEqual(red_rows[0], green_rows[0])
        self.assertEqual(green_rows[0], [((19, 161, 14, 255), "abcdefghij")])
        self.assertEqual(buffer.styled_layout(8)[0][:2], [
            [((19, 161, 14, 255), "abcdefgh")], [((19, 161, 14, 255), "ij")]])
        buffer.clear_output()
        self.assertEqual(buffer.styled_layout(8), ([[('prompt', '')]], 0, 0))

    def test_command_is_rendered_inline_after_remote_prompt(self):
        buffer = TerminalBuffer()
        buffer.set_output("user@host:~$ ")
        buffer.type_text("dir")
        rows, row, column = buffer.layout(80)
        self.assertEqual(rows, ["user@host:~$ dir"])
        self.assertEqual((row, column), (0, len("user@host:~$ dir")))

    def test_cursor_edits_only_draft_not_remote_transcript(self):
        buffer = TerminalBuffer()
        buffer.set_output("C:\\work> ")
        buffer.type_text("abde")
        buffer.move_cursor(-2)
        buffer.type_text("c")
        buffer.delete()
        self.assertEqual(buffer.output, "C:\\work> ")
        self.assertEqual(buffer.draft, "abce")
        buffer.backspace()
        self.assertEqual(buffer.draft, "abe")
        buffer.move_home()
        buffer.type_text("X")
        buffer.move_end()
        buffer.type_text("Y")
        self.assertEqual(buffer.draft, "XabeY")

    def test_ctrl_word_navigation_matches_command_line_editing(self):
        buffer = TerminalBuffer()
        buffer.type_text("one two three")
        buffer.move_cursor(-1, by_word=True)
        self.assertEqual(buffer.cursor, 8)
        buffer.move_cursor(-1, by_word=True)
        self.assertEqual(buffer.cursor, 4)
        buffer.move_cursor(1, by_word=True)
        self.assertEqual(buffer.cursor, 8)

    def test_history_restores_unsent_draft_and_places_caret_at_end(self):
        buffer = TerminalBuffer()
        for command in ("pwd", "ls -la"):
            buffer.type_text(command)
            submitted = buffer.begin_submit()
            buffer.command_result(submitted, True)
        buffer.type_text("draft")
        buffer.recall(-1)
        self.assertEqual((buffer.draft, buffer.cursor), ("ls -la", len("ls -la")))
        buffer.recall(1)
        self.assertEqual((buffer.draft, buffer.cursor), ("draft", len("draft")))

    def test_multiline_paste_stays_one_command(self):
        buffer = TerminalBuffer()
        buffer.paste("echo one\r\necho two")
        self.assertEqual(buffer.draft, "echo one echo two")

    def test_ansi_and_carriage_return_are_cleaned_for_console_display(self):
        self.assertEqual(clean_output("\x1b[32mgreen\x1b[0m\r\nnext"), "green\nnext")
        self.assertEqual(clean_output("progress 10%\rprogress 20%"), "progress 20%")
        self.assertEqual(clean_output("long progress 100%\rshort"), "short")

    def test_layout_uses_prompt_relative_tab_stops_and_middle_cursor(self):
        buffer = TerminalBuffer()
        buffer.set_output("x> ")
        buffer.type_text("a\tb")
        buffer.move_cursor(-1)
        rows, row, column = buffer.layout(40)
        self.assertEqual(rows, ["x> a    b"])
        self.assertEqual((row, column), (0, 8))

    def test_ansi_sgr_colors_are_preserved_for_rendering(self):
        plain, styles = parse_ansi_output("normal \x1b[31mred\x1b[0m end")
        self.assertEqual(plain, "normal red end")
        self.assertIsNone(styles[0])
        red_start = plain.index("red")
        self.assertEqual(styles[red_start], (197, 15, 31, 255))
        self.assertIsNone(styles[plain.index(" end")])

    def test_truecolor_and_256_color_sequences_are_supported(self):
        plain, styles = parse_ansi_output("\x1b[38;2;1;2;3mR\x1b[38;5;196mX\x1b[0m")
        self.assertEqual(plain, "RX")
        self.assertEqual(styles[0], (1, 2, 3, 255))
        self.assertEqual(styles[1], (255, 0, 0, 255))

    def test_styled_layout_prefers_remote_ansi_color_over_fallback(self):
        buffer = TerminalBuffer()
        buffer.set_output("\x1b[36mremote\x1b[0m output\nuser@host$ ")
        styled, _row, _col = buffer.styled_layout(80)
        self.assertEqual(styled[0][0], ((58, 150, 221, 255), "remote"))
        self.assertEqual(styled[-1], [("prompt", "user@host$ ")])

    def test_styled_layout_separates_prompt_command_and_output_styles(self):
        buffer = TerminalBuffer()
        buffer.set_output("Warning: check settings\nuser@host:~$ ")
        buffer.type_text("ls -la")
        styled_rows, row, column = buffer.styled_layout(80)
        self.assertEqual(styled_rows[0], [("warning", "Warning: check settings")])
        self.assertEqual(styled_rows[1], [("prompt", "user@host:~$ "), ("command", "ls -la")])
        self.assertEqual((row, column), (1, len("user@host:~$ ls -la")))

    def test_find_matches_is_case_insensitive_and_reports_row_columns(self):
        rows = ["Alpha beta ALPHA", "nothing", "alpha"]
        self.assertEqual(TerminalBuffer.find_matches(rows, "alpha"), [(0, 0, 5), (0, 11, 16), (2, 0, 5)])
        self.assertEqual(TerminalBuffer.find_matches(rows, "ALPHA", case_sensitive=True), [(0, 11, 16)])

    def test_word_bounds_selects_shell_token_without_crossing_whitespace(self):
        line = "cat /home/user/My-File.log --tail"
        self.assertEqual(TerminalBuffer.word_bounds(line, line.index("user")), (4, 26))
        self.assertEqual(line[slice(*TerminalBuffer.word_bounds(line, line.index("user")))], "/home/user/My-File.log")

    def test_console_source_has_find_navigation_and_multiclick_selection(self):
        source = (Path(__file__).resolve().parents[1] / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
        for token in ("mvKey_F3", "_open_find", "_find_next", "_select_word_at", "_select_line_at", "mvMouseButton_Middle"):
            self.assertIn(token, source)
        self.assertIn("self.focus_input(follow_tail=False)", source)

    def test_console_form_has_no_detached_command_textbox(self):
        source = (Path(__file__).resolve().parents[1] / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
        self.assertNotIn("add_input_text", source)
        self.assertIn("self.output = self.input = self.canvas", source)
        for token in ("mvKey_Left", "mvKey_Right", "mvKey_Home", "mvKey_End", "mvKey_Delete"):
            self.assertIn(token, source)

    def test_console_draw_text_uses_supported_font_binding_path(self):
        source = (Path(__file__).resolve().parents[1] / "WinUx" / "components" / "console_renderer.py").read_text(encoding="utf-8")
        draw_lines = [line for line in source.splitlines() if "dpg.draw_text(" in line]
        self.assertTrue(draw_lines)
        self.assertFalse(any("font=" in line for line in draw_lines))
        self.assertNotIn('**({"font"', source)
        self.assertIn("dpg.bind_item_font(item, view._font)", source)

    def test_console_click_focus_is_scoped_to_canvas_not_child_window(self):
        source = (Path(__file__).resolve().parents[1] / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
        self.assertNotIn("bind_item_handler_registry(self.content", source)
        self.assertIn("dpg.bind_item_handler_registry(owner.canvas", source)
        self.assertIn("button=dpg.mvMouseButton_Left", source)
        self.assertIn("button=dpg.mvMouseButton_Middle", source)
        menu = source.split("class _ConsoleContextMenu:", 1)[1].split("def terminal_theme", 1)[0]
        self.assertNotIn("button=dpg.mvMouseButton_Right", menu)
        self.assertIn("dpg.add_mouse_click_handler", source)
        self.assertIn("dpg.is_item_hovered(self.content)", source)
        self.assertIn("dpg.is_item_hovered(self.canvas)", source)

    def test_console_has_mouse_selection_and_modeless_cmd_context_menu(self):
        source = (Path(__file__).resolve().parents[1] / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
        for token in ("add_mouse_drag_handler", "add_mouse_release_handler", "mvMouseButton_Right", "_selected_text", "_select_all", "_clear_console"):
            self.assertIn(token, source)
        self.assertIn("class _ConsoleContextMenu", source)
        self.assertNotIn("TrackPopupMenuEx", source)
        for label in ("Copy", "Paste", "Select All", "Find", "Clear"):
            self.assertIn('"{}"'.format(label), source)

    def test_console_close_cleanup_does_not_reference_removed_click_registry(self):
        source = (Path(__file__).resolve().parents[1] / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
        self.assertIn('getattr(self, "_terminal_handlers", None)', source)
        self.assertIn('getattr(self, "_theme", None)', source)
        self.assertNotIn("self._click_handlers", source)

    def test_console_renders_visible_rows_individually_for_caret_alignment(self):
        source = (Path(__file__).resolve().parents[1] / "WinUx" / "components" / "console_renderer.py").read_text(encoding="utf-8")
        self.assertIn("view._line_items = []", source)
        self.assertIn("for offset, segments in enumerate(styled_rows[first:last]):", source)
        self.assertIn("view._current_line_fill", source)
        self.assertIn("caret_top = y + view._line_height - caret_height - 1", source)


if __name__ == "__main__":
    unittest.main()
