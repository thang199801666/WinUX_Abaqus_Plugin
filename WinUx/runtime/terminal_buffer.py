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
        return True

    def type_text(self, text):
        text = "".join(char for char in str(text) if char == "\t" or char.isprintable())
        if not text:
            return
        self._replace_selectionless(self.cursor, self.cursor, text)

    def paste(self, text):
        # One Enter submits one SSH command. Multi-line clipboard text therefore
        # stays on the current command line instead of firing commands silently.
        self.type_text(str(text).replace("\r\n", " ").replace("\n", " ").replace("\r", " "))

    def backspace(self):
        if self.pending is None and self.cursor > 0:
            self._replace_selectionless(self.cursor - 1, self.cursor)

    def delete(self):
        if self.pending is None and self.cursor < len(self.draft):
            self._replace_selectionless(self.cursor, self.cursor + 1)

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

    def move_home(self):
        if self.pending is None:
            self.cursor = 0

    def move_end(self):
        if self.pending is None:
            self.cursor = len(self.draft)

    def recall(self, direction):
        if self.pending is not None or not self.history:
            return
        if self.history_index == len(self.history):
            self._saved_draft = self.draft
        self.history_index = max(0, min(len(self.history), self.history_index + direction))
        self.draft = self.history[self.history_index] if self.history_index < len(self.history) else self._saved_draft
        self.cursor = len(self.draft)

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

    def layout(self, columns):
        columns = self._ensure_layout_cache(columns)
        prompt = self._tail
        tail = (prompt + self.draft).expandtabs(8)
        before_cursor = (prompt + self.draft[:self.cursor]).expandtabs(8)
        tail_rows = [tail[i:i + columns] for i in range(0, len(tail), columns)] or [""]
        rows = self._prefix_rows + tail_rows
        cursor_offset = len(before_cursor)
        cursor_row = len(self._prefix_rows) + cursor_offset // columns
        cursor_column = cursor_offset % columns
        if cursor_row == len(rows):
            rows.append("")
        return rows, cursor_row, cursor_column

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

    def styled_layout(self, columns):
        columns = self._ensure_layout_cache(columns)
        _rows, cursor_row, cursor_column = self.layout(columns)
        if self._styled_prefix_rows is None:
            self._styled_prefix_rows = [
                self._segments(row, ansi_styles, self._style_for_output_row(row))
                for row, ansi_styles in zip(self._prefix_rows, self._prefix_style_rows)
            ]
        # Callers receive their own lists; edits must not corrupt cached rows.
        styled_rows = [list(segments) for segments in self._styled_prefix_rows]

        prompt = self._tail
        tail = (prompt + self.draft).expandtabs(8)
        command = tail[len(prompt):]
        command_style = "command_pending" if self.pending is not None else "command"
        prompt_styles = list(self._tail_styles)
        visual_styles = prompt_styles + [command_style] * len(command)
        tail_rows = [tail[i:i + columns] for i in range(0, len(tail), columns)] or [""]
        for offset, row in enumerate(tail_rows):
            start = offset * columns
            row_styles = visual_styles[start:start + len(row)]
            # ANSI prompt colors win; otherwise the prompt is gray and the
            # editable command uses the dedicated command color.
            normalized = []
            for absolute, style in enumerate(row_styles, start=start):
                if absolute < len(prompt):
                    normalized.append(style if isinstance(style, tuple) else "prompt")
                else:
                    normalized.append(command_style)
            styled_rows.append(self._segments(row, normalized, "prompt"))
        return styled_rows, cursor_row, cursor_column
