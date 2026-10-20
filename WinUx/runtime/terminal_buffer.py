"""Inline SSH terminal state: protected transcript, editable command and history."""
from __future__ import annotations

import re

ANSI_PATTERN = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")

ANSI_16 = {
    30: (12, 12, 12, 255), 31: (197, 15, 31, 255), 32: (19, 161, 14, 255),
    33: (193, 156, 0, 255), 34: (0, 55, 218, 255), 35: (136, 23, 152, 255),
    36: (58, 150, 221, 255), 37: (204, 204, 204, 255),
    90: (118, 118, 118, 255), 91: (231, 72, 86, 255), 92: (22, 198, 12, 255),
    93: (249, 241, 165, 255), 94: (59, 120, 255, 255), 95: (180, 0, 158, 255),
    96: (97, 214, 214, 255), 97: (242, 242, 242, 255),
}


def _xterm_256(index):
    index = max(0, min(255, int(index)))
    if index < 16:
        table = [
            (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
            (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
            (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
            (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
        ]
        r, g, b = table[index]
        return r, g, b, 255
    if index < 232:
        value = index - 16
        r, value = divmod(value, 36)
        g, b = divmod(value, 6)
        levels = (0, 95, 135, 175, 215, 255)
        return levels[r], levels[g], levels[b], 255
    gray = 8 + (index - 232) * 10
    return gray, gray, gray, 255


def _apply_sgr(params, foreground):
    if not params:
        params = [0]
    index = 0
    while index < len(params):
        code = params[index]
        if code in (0, 39):
            foreground = None
        elif code in ANSI_16:
            foreground = ANSI_16[code]
        elif code == 38 and index + 1 < len(params):
            mode = params[index + 1]
            if mode == 5 and index + 2 < len(params):
                foreground = _xterm_256(params[index + 2])
                index += 2
            elif mode == 2 and index + 4 < len(params):
                try:
                    r, g, b = (max(0, min(255, int(value))) for value in params[index + 2:index + 5])
                    foreground = (r, g, b, 255)
                except (TypeError, ValueError):
                    pass
                index += 4
        index += 1
    return foreground


def parse_ansi_output(value):
    """Return terminal text plus per-character ANSI foreground colors.

    This deliberately implements the text/color subset needed by an SSH command
    console rather than pretending to be a full VT emulator. SGR foreground
    colors (16/256/truecolor), CR line rewrite, LF, backspace and OSC stripping
    are retained. ``None`` in the style list means the console default color.
    """
    source = str(value or "")
    output, styles = [], []
    line_start = 0
    cursor = 0
    index = 0
    foreground = None
    while index < len(source):
        char = source[index]
        if char == "\x1b":
            if index + 1 < len(source) and source[index + 1] == "[":
                final = index + 2
                while final < len(source) and not ("@" <= source[final] <= "~"):
                    final += 1
                if final < len(source):
                    command = source[final]
                    body = source[index + 2:final]
                    if command == "m":
                        try:
                            params = [int(part) if part else 0 for part in body.split(";")]
                        except ValueError:
                            params = [0]
                        foreground = _apply_sgr(params, foreground)
                    index = final + 1
                    continue
            elif index + 1 < len(source) and source[index + 1] == "]":
                final = index + 2
                while final < len(source):
                    if source[final] == "\x07":
                        final += 1
                        break
                    if source[final] == "\x1b" and final + 1 < len(source) and source[final + 1] == "\\":
                        final += 2
                        break
                    final += 1
                index = final
                continue
            index += 2
            continue
        if char == "\r":
            if index + 1 < len(source) and source[index + 1] == "\n":
                output.append("\n")
                styles.append(None)
                cursor = len(output)
                line_start = cursor
                index += 2
                continue
            del output[line_start:]
            del styles[line_start:]
            cursor = line_start
            index += 1
            continue
        if char == "\n":
            if cursor < len(output):
                del output[cursor:]
                del styles[cursor:]
            output.append("\n")
            styles.append(None)
            cursor = len(output)
            line_start = cursor
            index += 1
            continue
        if char == "\b":
            if cursor > line_start:
                cursor -= 1
            index += 1
            continue
        if char == "\t":
            count = 8 - ((cursor - line_start) % 8)
            for _ in range(count):
                if cursor < len(output) and output[cursor] != "\n":
                    output[cursor] = " "
                    styles[cursor] = foreground
                else:
                    output.insert(cursor, " ")
                    styles.insert(cursor, foreground)
                cursor += 1
            index += 1
            continue
        if ord(char) >= 32 and char != "\x7f":
            if cursor < len(output) and output[cursor] != "\n":
                output[cursor] = char
                styles[cursor] = foreground
            else:
                output.insert(cursor, char)
                styles.insert(cursor, foreground)
            cursor += 1
        index += 1
    return "".join(output), styles


def clean_output(value):
    return parse_ansi_output(value)[0]


class TerminalBuffer:
    """Small line editor placed directly at the end of the SSH transcript.

    ``output`` is immutable from the user's point of view. ``draft`` is the
    current command and ``cursor`` is always an offset inside that draft, which
    makes the interaction match a normal Windows command prompt instead of a
    detached textbox.
    """

    HISTORY_LIMIT = 50
    SCROLLBACK_LIMIT = 256 * 1024
    COMMAND_LIMIT = 16 * 1024

    def __init__(self):
        self.output = ""
        self.output_styles = []
        self.draft = ""
        self.cursor = 0
        self.pending = None
        self.history = []
        self.history_index = 0
        self._saved_draft = ""
        self._history_prefix = None
        self._history_prefix_index = None
        self._history_contains = None
        self._history_contains_index = None
        self._kill_buffer = ""
        self.overwrite_mode = False
        self._layout_key = None
        self._prefix_rows = []
        self._prefix_style_rows = []
        self._styled_prefix_rows = None
        self._tail = ""
        self._tail_styles = []

    @classmethod
    def updated_history(cls, history, command):
        command = str(command).strip()
        if not command:
            return list(history)
        return ([item for item in history if item != command] + [command])[-cls.HISTORY_LIMIT:]

    @staticmethod
    def find_matches(rows, query, case_sensitive=False):
        query = str(query or "")
        if not query:
            return []
        needle = query if case_sensitive else query.lower()
        matches = []
        for row_index, row in enumerate(rows):
            haystack = row if case_sensitive else row.lower()
            start = 0
            while True:
                column = haystack.find(needle, start)
                if column < 0:
                    break
                matches.append((row_index, column, column + len(query)))
                start = column + max(1, len(query))
        return matches

    @staticmethod
    def word_bounds(text, column):
        text = str(text or "")
        if not text:
            return 0, 0
        column = max(0, min(len(text), int(column)))
        if column == len(text) and column:
            column -= 1
        if text[column].isspace():
            return column, min(len(text), column + 1)
        start, end = column, column + 1
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        while end < len(text) and not text[end].isspace():
            end += 1
        return start, end

    def set_output(self, text):
        output, styles = parse_ansi_output(text)
        if len(output) > self.SCROLLBACK_LIMIT:
            cut = len(output) - self.SCROLLBACK_LIMIT
            output = output[cut:]
            styles = styles[cut:]
            newline = output.find("\n")
            if newline >= 0:
                output = output[newline + 1:]
                styles = styles[newline + 1:]
        if output != self.output or styles != self.output_styles:
            self.output = output
            self.output_styles = styles
            self._layout_key = None
            return True
        return False

    def clear_output(self):
        self.output = ""
        self.output_styles = []
        self._layout_key = None

    def _reset_history_prefix_search(self):
        self._history_prefix = None
        self._history_prefix_index = None

    def _reset_history_contains_search(self):
        self._history_contains = None
        self._history_contains_index = None

    def _reset_history_searches(self):
        self._reset_history_prefix_search()
        self._reset_history_contains_search()

    def _replace_selectionless(self, start, end, text=""):
        if self.pending is not None:
            return False
        start = max(0, min(len(self.draft), int(start)))
        end = max(start, min(len(self.draft), int(end)))
        room = max(0, self.COMMAND_LIMIT - (len(self.draft) - (end - start)))
        text = str(text)[:room]
        self.draft = self.draft[:start] + text + self.draft[end:]
        self.cursor = start + len(text)
        self.history_index = len(self.history)
        self._reset_history_searches()
        return True

    def type_text(self, text):
        text = "".join(char for char in str(text) if char == "\t" or char.isprintable())
        if not text or self.pending is not None:
            return
        if not self.overwrite_mode or self.cursor >= len(self.draft):
            self._replace_selectionless(self.cursor, self.cursor, text)
            return
        # cmd.exe-style Insert/Overwrite editing.  Only characters underneath
        # the newly typed text are replaced; text beyond the end is appended.
        end = min(len(self.draft), self.cursor + len(text))
        self._replace_selectionless(self.cursor, end, text)

    def paste(self, text):
        # One Enter submits one SSH command. Multi-line clipboard text therefore
        # stays on the current command line instead of firing commands silently.
        text = str(text).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        text = "".join(char for char in text if char == "\t" or char.isprintable())
        if text:
            # Paste remains insertional even while overwrite typing is enabled,
            # matching modern Windows terminal behavior and avoiding data loss.
            self._replace_selectionless(self.cursor, self.cursor, text)

    def backspace(self):
        if self.pending is None and self.cursor > 0:
            self._replace_selectionless(self.cursor - 1, self.cursor)

    def delete(self):
        if self.pending is None and self.cursor < len(self.draft):
            self._replace_selectionless(self.cursor, self.cursor + 1)

    def _word_left_range(self):
        end = self.cursor
        start = end
        while start > 0 and self.draft[start - 1].isspace():
            start -= 1
        while start > 0 and not self.draft[start - 1].isspace():
            start -= 1
        return start, end

    def _word_right_range(self):
        start = self.cursor
        end = start
        while end < len(self.draft) and self.draft[end].isspace():
            end += 1
        while end < len(self.draft) and not self.draft[end].isspace():
            end += 1
        while end < len(self.draft) and self.draft[end].isspace():
            end += 1
        return start, end

    def delete_word_left(self):
        if self.pending is not None or self.cursor <= 0:
            return
        start, end = self._word_left_range()
        self._replace_selectionless(start, end)

    def delete_word_right(self):
        if self.pending is not None or self.cursor >= len(self.draft):
            return
        start, end = self._word_right_range()
        self._replace_selectionless(start, end)

    def _kill_range(self, start, end):
        if self.pending is not None:
            return False
        start = max(0, min(len(self.draft), int(start)))
        end = max(start, min(len(self.draft), int(end)))
        if start == end:
            return False
        self._kill_buffer = self.draft[start:end]
        return self._replace_selectionless(start, end)

    def kill_word_left(self):
        if self.pending is not None or self.cursor <= 0:
            return False
        return self._kill_range(*self._word_left_range())

    def kill_word_right(self):
        if self.pending is not None or self.cursor >= len(self.draft):
            return False
        return self._kill_range(*self._word_right_range())

    def delete_to_start(self):
        if self.pending is None and self.cursor > 0:
            self._replace_selectionless(0, self.cursor)

    def delete_to_end(self):
        if self.pending is None and self.cursor < len(self.draft):
            self._replace_selectionless(self.cursor, len(self.draft))

    def kill_to_start(self):
        return self._kill_range(0, self.cursor)

    def kill_to_end(self):
        return self._kill_range(self.cursor, len(self.draft))

    def yank(self):
        if self.pending is not None or not self._kill_buffer:
            return False
        return self._replace_selectionless(
            self.cursor, self.cursor, self._kill_buffer)

    def clear_draft(self):
        if self.pending is None and self.draft:
            self._replace_selectionless(0, len(self.draft))

    def _template_command(self):
        """Return the DOSKEY-style template (the most recent command)."""
        return self.history[-1] if self.history else ""

    def copy_template_char(self):
        """F1: copy one character from the previous command at this column."""
        if self.pending is not None:
            return False
        template = self._template_command()
        if self.cursor >= len(template):
            return False
        return self._replace_selectionless(
            self.cursor, self.cursor, template[self.cursor])

    def copy_template_remainder(self):
        """F3: copy the previous command from the current caret column onward."""
        if self.pending is not None:
            return False
        template = self._template_command()
        if self.cursor >= len(template):
            return False
        # DOSKEY treats the last submitted command as a column-aligned
        # template. Replacing the editable suffix avoids duplicated text when
        # F3 is pressed in the middle of an already populated command line.
        return self._replace_selectionless(
            self.cursor, len(self.draft), template[self.cursor:])

    def copy_template(self):
        """F5: replace the current line with the previous command template."""
        if self.pending is not None:
            return False
        template = self._template_command()
        if not template:
            return False
        self.draft = template[:self.COMMAND_LIMIT]
        self.cursor = len(self.draft)
        self.history_index = max(0, len(self.history) - 1)
        self._saved_draft = ""
        self._reset_history_searches()
        return True

    def toggle_overwrite(self):
        if self.pending is None:
            self.overwrite_mode = not self.overwrite_mode
        return self.overwrite_mode

    def move_cursor(self, delta, by_word=False):
        if self.pending is not None:
            return
        if not by_word:
            self.cursor = max(0, min(len(self.draft), self.cursor + int(delta)))
            return
        if delta < 0:
            pos = self.cursor
            while pos > 0 and self.draft[pos - 1].isspace():
                pos -= 1
            while pos > 0 and not self.draft[pos - 1].isspace():
                pos -= 1
            self.cursor = pos
        elif delta > 0:
            pos = self.cursor
            while pos < len(self.draft) and not self.draft[pos].isspace():
                pos += 1
            while pos < len(self.draft) and self.draft[pos].isspace():
                pos += 1
            self.cursor = pos

    def move_cursor_to_cell(self, columns, row, column):
        """Place the caret in the editable draft, never in scrollback/prompt.

        Use the same wrapping and tab stops as layout(), including commands
        spanning multiple rows. A click in old output leaves the caret alone.
        """
        if self.pending is not None:
            return False
        columns = self._ensure_layout_cache(columns)
        start = len(self._tail.expandtabs(8))
        end = len((self._tail + self.draft).expandtabs(8))
        relative_row = int(row) - len(self._prefix_rows)
        if not start // columns <= relative_row <= end // columns:
            return False
        target = relative_row * columns + max(0, min(columns, int(column)))
        if target < start:
            return False
        target = min(end, target)
        visual = start
        offset = 0
        for char in self.draft:
            next_visual = visual + (8 - visual % 8 if char == "\t" else 1)
            if target < next_visual:
                break
            visual = next_visual
            offset += 1
        self.cursor = offset
        return True

    def move_home(self):
        if self.pending is None:
            self.cursor = 0

    def move_end(self):
        if self.pending is None:
            self.cursor = len(self.draft)

    def recall(self, direction):
        if self.pending is not None or not self.history:
            return
        self._reset_history_searches()
        if self.history_index == len(self.history):
            self._saved_draft = self.draft
        self.history_index = max(0, min(len(self.history), self.history_index + direction))
        self.draft = self.history[self.history_index] if self.history_index < len(self.history) else self._saved_draft
        self.cursor = len(self.draft)

    def recall_prefix(self, direction=-1):
        """Recall history entries beginning with the current CMD-style prefix.

        F8 in cmd.exe searches history using the characters already typed. The
        prefix is captured on the first search and kept stable while F8 is
        pressed repeatedly, so replacing the draft with a match does not alter
        the search key.
        """
        if self.pending is not None or not self.history:
            return False
        self._reset_history_contains_search()
        step = -1 if int(direction or -1) < 0 else 1
        if self._history_prefix is None:
            self._history_prefix = self.draft[:self.cursor]
            self._history_prefix_index = len(self.history) if step < 0 else -1
            self._saved_draft = self.draft
        prefix = self._history_prefix
        start = int(self._history_prefix_index)
        indexes = (
            range(start - 1, -1, -1) if step < 0
            else range(start + 1, len(self.history))
        )
        for index in indexes:
            candidate = self.history[index]
            if candidate.startswith(prefix):
                self._history_prefix_index = index
                self.history_index = index
                self.draft = candidate
                self.cursor = len(candidate)
                return True
        return False

    def recall_contains(self, direction=-1):
        """Recall history entries containing the current search text.

        This is a compact reverse-search companion to :meth:`recall_prefix`.
        The query is captured from the draft up to the caret on the first call
        and remains stable while Ctrl+R is repeated.  Ordinary editing resets
        the search, matching readline's expectation that new text starts a new
        lookup rather than continuing a stale cycle.
        """
        if self.pending is not None or not self.history:
            return False
        self._reset_history_prefix_search()
        step = -1 if int(direction or -1) < 0 else 1
        if self._history_contains is None:
            self._history_contains = self.draft[:self.cursor]
            self._history_contains_index = (
                len(self.history) if step < 0 else -1)
            self._saved_draft = self.draft
        needle = self._history_contains
        start = int(self._history_contains_index)
        indexes = (
            range(start - 1, -1, -1) if step < 0
            else range(start + 1, len(self.history))
        )
        for index in indexes:
            candidate = self.history[index]
            if needle in candidate:
                self._history_contains_index = index
                self.history_index = index
                self.draft = candidate
                self.cursor = len(candidate)
                return True
        return False

    def begin_submit(self):
        command = self.draft
        if not command.strip() or self.pending is not None:
            return None
        self.pending = command
        return command

    def command_result(self, command, accepted):
        if command != self.pending:
            return
        if accepted:
            self.history = self.updated_history(self.history, command)
            self.history_index = len(self.history)
            self._saved_draft = ""
            self._reset_history_searches()
            self.draft = ""
            self.cursor = 0
        self.pending = None

    def interrupt_result(self, accepted):
        if accepted:
            self.pending = None
            self.draft = ""
            self.cursor = 0
            self.history_index = len(self.history)
            self._saved_draft = ""
            self._reset_history_searches()

    def _style_for_output_row(self, row):
        lowered = row.lower()
        if any(token in lowered for token in ("error", "exception", "traceback", "failed", "fatal")):
            return "error"
        if any(token in lowered for token in ("warning", "warn", "deprecated")):
            return "warning"
        if any(token in lowered for token in ("success", "completed", "done", "copied", "connected")):
            return "success"
        return "output"

    def _ensure_layout_cache(self, columns):
        columns = max(8, int(columns))
        if self._layout_key == (self.output, columns):
            return columns
        rows, style_rows = [], []
        start = 0
        lines = self.output.split("\n")
        for line in lines[:-1]:
            line_styles = self.output_styles[start:start + len(line)]
            if line:
                for offset in range(0, len(line), columns):
                    rows.append(line[offset:offset + columns])
                    style_rows.append(line_styles[offset:offset + columns])
            else:
                rows.append("")
                style_rows.append([])
            start += len(line) + 1
        self._prefix_rows = rows
        self._prefix_style_rows = style_rows
        self._styled_prefix_rows = None
        self._tail = lines[-1]
        self._tail_styles = self.output_styles[start:start + len(self._tail)]
        self._layout_key = self.output, columns
        return columns

    def _tail_layout(self, columns):
        """Return the mutable prompt/draft rows and cursor geometry.

        Prefix rows are cached by :meth:`_ensure_layout_cache`; only the last
        prompt/command row can change while the user is typing.  Keeping this
        calculation separate lets renderers request only the styled viewport
        instead of cloning the complete scrollback on every paint tick.
        """
        prompt = self._tail
        tail = (prompt + self.draft).expandtabs(8)
        before_cursor = (prompt + self.draft[:self.cursor]).expandtabs(8)
        tail_rows = [tail[i:i + columns] for i in range(0, len(tail), columns)] or [""]
        cursor_offset = len(before_cursor)
        cursor_row = len(self._prefix_rows) + cursor_offset // columns
        cursor_column = cursor_offset % columns
        if cursor_row == len(self._prefix_rows) + len(tail_rows):
            tail_rows.append("")
        return prompt, tail_rows, cursor_row, cursor_column

    def layout(self, columns):
        columns = self._ensure_layout_cache(columns)
        _prompt, tail_rows, cursor_row, cursor_column = self._tail_layout(columns)
        return self._prefix_rows + tail_rows, cursor_row, cursor_column

    @staticmethod
    def _segments(text, styles, fallback):
        if not text:
            return [(fallback, "")]
        segments = []
        current_style = styles[0] if styles and styles[0] is not None else fallback
        current = []
        for index, char in enumerate(text):
            style = styles[index] if index < len(styles) and styles[index] is not None else fallback
            if style != current_style and current:
                segments.append((current_style, "".join(current)))
                current = []
                current_style = style
            current.append(char)
        if current:
            segments.append((current_style, "".join(current)))
        return segments

    def _ensure_styled_prefix_cache(self):
        if self._styled_prefix_rows is None:
            self._styled_prefix_rows = [
                self._segments(row, ansi_styles, self._style_for_output_row(row))
                for row, ansi_styles in zip(self._prefix_rows, self._prefix_style_rows)
            ]

    def styled_layout_slice(self, columns, start=0, end=None):
        """Return styled rows for ``[start:end]`` without cloning scrollback.

        The legacy :meth:`styled_layout` API still returns every row.  The
        console renderer uses this viewport API so idle/scroll paints scale
        with visible rows rather than total terminal history.
        """
        columns = self._ensure_layout_cache(columns)
        prompt, tail_rows, cursor_row, cursor_column = self._tail_layout(columns)
        total_rows = len(self._prefix_rows) + len(tail_rows)
        start = max(0, min(total_rows, int(start or 0)))
        if end is None:
            end = total_rows
        end = max(start, min(total_rows, int(end)))

        self._ensure_styled_prefix_cache()
        styled_rows = []
        prefix_end = min(end, len(self._prefix_rows))
        if start < prefix_end:
            styled_rows.extend(
                list(segments) for segments in self._styled_prefix_rows[start:prefix_end]
            )

        tail_start = max(0, start - len(self._prefix_rows))
        tail_end = max(0, end - len(self._prefix_rows))
        if tail_start < tail_end:
            tail = (prompt + self.draft).expandtabs(8)
            command = tail[len(prompt):]
            command_style = "command_pending" if self.pending is not None else "command"
            visual_styles = list(self._tail_styles) + [command_style] * len(command)
            for offset in range(tail_start, tail_end):
                row = tail_rows[offset]
                row_start = offset * columns
                row_styles = visual_styles[row_start:row_start + len(row)]
                normalized = []
                for absolute, style in enumerate(row_styles, start=row_start):
                    if absolute < len(prompt):
                        normalized.append(style if isinstance(style, tuple) else "prompt")
                    else:
                        normalized.append(command_style)
                styled_rows.append(self._segments(row, normalized, "prompt"))
        return styled_rows, cursor_row, cursor_column

    def styled_layout(self, columns):
        return self.styled_layout_slice(columns, 0, None)
