"""Small dependency-free VT/xterm alternate-screen emulator for SSH TUIs.

WinUx keeps its normal shell prompt as a local CMD/readline-style editor. Full
screen programs such as nano/vim/top are different: they take ownership of the
PTY and redraw a character grid with ANSI cursor-control sequences.  This
module implements the common VT100/xterm subset those applications use so the
same custom DearUIQt canvas can render them without adding a third-party
terminal dependency to Abaqus Python deployments.
"""
from __future__ import annotations
import unicodedata


def terminal_text_width(text):
    """Width of ordinary Unicode text in terminal cells (not Python chars)."""
    return sum(0 if unicodedata.combining(char) or unicodedata.category(char) == "Cf"
               else 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
               for char in text)


_ALT_MODES = {47, 1047, 1049}
DEFAULT_FG = (212, 212, 212, 255)
DEFAULT_BG = (12, 12, 12, 255)
ANSI_COLORS = (
    (0, 0, 0), (205, 49, 49), (13, 188, 121), (229, 229, 16),
    (36, 114, 200), (188, 63, 188), (17, 168, 205), (229, 229, 229),
    (102, 102, 102), (241, 76, 76), (35, 209, 139), (245, 245, 67),
    (59, 142, 234), (214, 112, 214), (41, 184, 219), (255, 255, 255),
)


class VTTerminalScreen:
    """Incremental VT alternate-screen model.

    Ordinary shell bytes are ignored until an xterm alternate-screen DECSET is
    observed. While active, printable characters and the common CSI/ESC editing
    operations mutate a fixed cell grid. DECRST for the alternate screen exits
    interactive mode and the regular WinUx transcript becomes authoritative
    again.
    """

    def __init__(self, columns=120, rows=40):
        self.columns = max(2, int(columns))
        self.rows = max(2, int(rows))
        self.active = False
        self.cursor_visible = True
        self.application_cursor = False
        self.bracketed_paste = False
        self.cursor_row = 0
        self.cursor_col = 0
        self.saved_cursor = (0, 0)
        self.scroll_top = 0
        self.scroll_bottom = self.rows - 1
        self._pending = ""
        self._screen = self._blank_screen()
        self._reset_attributes()
        self._styles = self._blank_styles()
        self._replies = []
        self.autowrap = True
        self.origin_mode = False
        self.insert_mode = False
        self._wrap_pending = False
        self._saved_attributes = None
        self._graphics = False
        self._last_char = " "
        self._mouse_modes = set()
        self.mouse_sgr = False
        self.mouse_utf8 = False

    def _reset_attributes(self):
        self.foreground, self.background = DEFAULT_FG, DEFAULT_BG
        self.bold = self.inverse = self.underline = False

    def _style(self):
        fg, bg = self.foreground, self.background
        if self.bold and fg[:3] in ANSI_COLORS[:8]:
            fg = ANSI_COLORS[ANSI_COLORS.index(fg[:3]) + 8] + (255,)
        return (bg, fg, self.underline) if self.inverse else (fg, bg, self.underline)

    def _blank_styles(self):
        return [[self._style()] * self.columns for _ in range(self.rows)]

    def drain_replies(self):
        """Return and clear terminal protocol replies (never user keystrokes)."""
        replies, self._replies = self._replies, []
        return "".join(replies)

    def styled_rows(self, start=0, end=None):
        """Return styled cell runs for a row slice (all rows by default)."""
        result = []
        first, stop, _step = slice(start, end).indices(len(self._screen))
        for row in range(first, stop):
            chars, styles = self._screen[row], self._styles[row]
            runs = []
            current_style = None
            current = []
            for char, style in zip(chars, styles):
                if current and style != current_style:
                    runs.append((current_style, ''.join(current)))
                    current = []
                current_style = style
                current.append(char)
            if current:
                runs.append((current_style, ''.join(current)))
            result.append(runs)
        return result

    def _blank_screen(self):
        return [[" "] * self.columns for _ in range(self.rows)]

    def reset(self, *, keep_size=True):
        columns, rows = self.columns, self.rows
        self.active = False
        self.cursor_visible = True
        self.application_cursor = False
        self.bracketed_paste = False
        self.cursor_row = self.cursor_col = 0
        self.saved_cursor = (0, 0)
        self._pending = ""
        if not keep_size:
            columns, rows = 120, 40
            self.columns, self.rows = columns, rows
        self.scroll_top = 0
        self.scroll_bottom = rows - 1
        self._screen = self._blank_screen()
        self._reset_attributes()
        self._styles = self._blank_styles()
        self._replies = []
        self.autowrap, self.origin_mode, self.insert_mode = True, False, False
        self._wrap_pending = False
        self._saved_attributes = None
        self._graphics = False
        self._last_char = " "
        self._mouse_modes.clear()
        self.mouse_sgr = self.mouse_utf8 = False

    def resize(self, columns, rows):
        columns = max(2, int(columns))
        rows = max(2, int(rows))
        if (columns, rows) == (self.columns, self.rows):
            return False
        old = self._screen
        old_styles = self._styles
        full_region = self.scroll_top == 0 and self.scroll_bottom == self.rows - 1
        new = [[" "] * columns for _ in range(rows)]
        styles = [[self._style()] * columns for _ in range(rows)]
        for r in range(min(rows, len(old))):
            source = old[r]
            for c in range(min(columns, len(source))):
                new[r][c] = source[c]
                styles[r][c] = old_styles[r][c]
        self.columns, self.rows = columns, rows
        self._screen = new
        self._styles = styles
        for row in range(rows):
            self._repair_row(row)
        self._wrap_pending = False
        self.cursor_row = min(self.cursor_row, rows - 1)
        self.cursor_col = min(self.cursor_col, columns - 1)
        self.scroll_top = min(self.scroll_top, rows - 1)
        self.scroll_bottom = rows - 1 if full_region else min(max(self.scroll_top, self.scroll_bottom), rows - 1)
        return True

    def text_rows(self):
        # Keep the complete row width while active. Trailing blanks cost almost
        # nothing to draw and preserve correct mouse/cursor cell geometry.
        return ["".join(row) for row in self._screen]

    def cell_text(self, row, start=0, end=None):
        """Copy cell ranges without exposing wide-character continuation cells."""
        start = max(0, min(self.columns, start))
        end = self.columns if end is None else max(start, min(self.columns, end))
        if start < end and start and self._screen[row][start] == "":
            start -= 1
        return "".join(self._screen[row][start:end])

    def word_bounds(self, row, column):
        cells = self._screen[row]
        column = min(max(0, column), self.columns - 1)
        if column and not cells[column]:
            column -= 1
        def kind(value):
            return "space" if value.isspace() else "word" if value[0].isalnum() or value[0] == "_" else "punct"
        category = kind(cells[column])
        start, end = column, column + 1
        while start and (not cells[start - 1] or kind(cells[start - 1]) == category):
            start -= 1
        while end < self.columns and (not cells[end] or kind(cells[end]) == category):
            end += 1
        return start, end

    def _repair_row(self, row):
        cells = self._screen[row]
        for col, char in enumerate(cells):
            if not char:
                if col == 0 or terminal_text_width(cells[col - 1]) != 2:
                    cells[col] = " "
            elif terminal_text_width(char) == 2:
                if col + 1 >= self.columns or cells[col + 1] != "":
                    cells[col] = " "

    @staticmethod
    def _params(body, default=1):
        if body.startswith("?") or body.startswith(">") or body.startswith("!"):
            body = body[1:]
        if not body:
            return [default]
        result = []
        for part in body.split(";"):
            try:
                result.append(int(part) if part else default)
            except ValueError:
                result.append(default)
        return result or [default]

    def _clear(self):
        self._screen = self._blank_screen()
        self._styles = self._blank_styles()
        self._wrap_pending = False
        self.cursor_row = self.cursor_col = 0
        self.scroll_top = 0
        self.scroll_bottom = self.rows - 1

    def _enter_alt(self):
        if self.active:
            return
        self.active = True
        self.cursor_visible = True
        self._clear()

    def _leave_alt(self):
        self.active = False
        self.application_cursor = False
        self.bracketed_paste = False
        self.cursor_visible = True
        self._pending = ""
        self._reset_attributes()
        self.autowrap, self.origin_mode, self.insert_mode = True, False, False
        self._wrap_pending = False
        self._graphics = False
        self._mouse_modes.clear()
        self.mouse_sgr = self.mouse_utf8 = False

    @property
    def mouse_tracking(self):
        return max(self._mouse_modes, default=0) if self.active else 0

    def mouse_sequence(self, button, column, row, event="press", *, shift=False,
                       alt=False, ctrl=False):
        """Encode xterm SGR/legacy mouse reports using one-based cell coords."""
        mode = self.mouse_tracking
        if not mode or event not in ("press", "release", "motion"):
            return ""
        if event == "motion" and (mode == 1000 or mode == 1002 and button is None):
            return ""
        column, row = max(1, min(self.columns, column)), max(1, min(self.rows, row))
        code = (3 if button is None else button) + 4 * bool(shift) + 8 * bool(alt) + 16 * bool(ctrl)
        if event == "motion":
            code += 32
        if self.mouse_sgr:
            return "\x1b[<{};{};{}{}".format(code, column, row, "m" if event == "release" else "M")
        if not self.mouse_utf8 and (column > 95 or row > 95):
            # Non-UTF8 X10 coordinates above ASCII require byte transport;
            # never send misleading UTF8 coordinates on the text input API.
            return ""
        if event == "release":
            code = 3 + 4 * bool(shift) + 8 * bool(alt) + 16 * bool(ctrl)
        return "\x1b[M" + chr(code + 32) + chr(column + 32) + chr(row + 32)

    def _save_cursor(self):
        self.saved_cursor = (self.cursor_row, self.cursor_col)
        self._saved_attributes = (self.foreground, self.background, self.bold,
                                  self.inverse, self.underline, self.origin_mode,
                                  self.autowrap, self._graphics, self._wrap_pending)

    def _restore_cursor(self):
        self.cursor_row, self.cursor_col = self.saved_cursor
        self.cursor_row = max(0, min(self.rows - 1, self.cursor_row))
        self.cursor_col = max(0, min(self.columns - 1, self.cursor_col))
        if self._saved_attributes is not None:
            (self.foreground, self.background, self.bold, self.inverse,
             self.underline, self.origin_mode, self.autowrap, self._graphics,
             self._wrap_pending) = self._saved_attributes

    def _scroll_up(self, count=1):
        if not self.active:
            return
        count = max(1, int(count))
        top, bottom = self.scroll_top, self.scroll_bottom
        for _ in range(min(count, bottom - top + 1)):
            del self._screen[top]
            self._screen.insert(bottom, [" "] * self.columns)
            del self._styles[top]
            self._styles.insert(bottom, [self._style()] * self.columns)

    def _scroll_down(self, count=1):
        if not self.active:
            return
        count = max(1, int(count))
        top, bottom = self.scroll_top, self.scroll_bottom
        for _ in range(min(count, bottom - top + 1)):
            del self._screen[bottom]
            self._screen.insert(top, [" "] * self.columns)
            del self._styles[bottom]
            self._styles.insert(top, [self._style()] * self.columns)

    def _index(self):
        if self.cursor_row == self.scroll_bottom:
            self._scroll_up(1)
        else:
            self.cursor_row = min(self.rows - 1, self.cursor_row + 1)

    def _reverse_index(self):
        if self.cursor_row == self.scroll_top:
            self._scroll_down(1)
        else:
            self.cursor_row = max(0, self.cursor_row - 1)

    def _put(self, char):
        if not self.active:
            return
        width = terminal_text_width(char)
        if width == 0:
            column = self.cursor_col if self._wrap_pending else self.cursor_col - 1
            while column > 0 and not self._screen[self.cursor_row][column]:
                column -= 1
            if column >= 0 and self._screen[self.cursor_row][column].strip():
                self._screen[self.cursor_row][column] = unicodedata.normalize(
                    "NFC", self._screen[self.cursor_row][column] + char)
            return
        self._last_char = char
        if self._wrap_pending and self.autowrap:
            self.cursor_col = 0
            self._index()
        self._wrap_pending = False
        if width == 2 and self.cursor_col == self.columns - 1:
            if self.autowrap:
                self.cursor_col = 0
                self._index()
            else:
                char, width = "\ufffd", 1
        if 0 <= self.cursor_row < self.rows and 0 <= self.cursor_col < self.columns:
            if self.insert_mode:
                self._screen[self.cursor_row][self.cursor_col:self.cursor_col] = [" "] * width
                del self._screen[self.cursor_row][self.columns:]
                self._styles[self.cursor_row][self.cursor_col:self.cursor_col] = [self._style()] * width
                del self._styles[self.cursor_row][self.columns:]
            self._erase_cells(self.cursor_row, self.cursor_col, self.cursor_col + width)
            self._screen[self.cursor_row][self.cursor_col] = char
            self._styles[self.cursor_row][self.cursor_col] = self._style()
            if width == 2:
                self._screen[self.cursor_row][self.cursor_col + 1] = ""
                self._styles[self.cursor_row][self.cursor_col + 1] = self._style()
            if self.insert_mode:
                self._repair_row(self.cursor_row)
        if self.cursor_col + width >= self.columns:
            self.cursor_col = self.columns - 1
            self._wrap_pending = self.autowrap
        else:
            self.cursor_col += width

    def _erase_cells(self, row, start, end):
        if start and start < self.columns and self._screen[row][start] == "":
            start -= 1
        if end < self.columns and self._screen[row][end] == "":
            end += 1
        self._screen[row][start:end] = [" "] * (end - start)
        self._styles[row][start:end] = [self._style()] * (end - start)

    def _erase_display(self, mode):
        if not self.active:
            return
        mode = int(mode or 0)
        if mode in (2, 3):
            self._screen = self._blank_screen()
            self._styles = self._blank_styles()
            return
        if mode == 0:
            self._erase_cells(self.cursor_row, self.cursor_col, self.columns)
            for r in range(self.cursor_row + 1, self.rows):
                self._erase_cells(r, 0, self.columns)
        elif mode == 1:
            for r in range(0, self.cursor_row):
                self._erase_cells(r, 0, self.columns)
            self._erase_cells(self.cursor_row, 0, min(self.columns, self.cursor_col + 1))

    def _erase_line(self, mode):
        if not self.active:
            return
        mode = int(mode or 0)
        if mode == 2:
            self._erase_cells(self.cursor_row, 0, self.columns)
        elif mode == 1:
            self._erase_cells(self.cursor_row, 0, min(self.columns, self.cursor_col + 1))
        else:
            self._erase_cells(self.cursor_row, self.cursor_col, self.columns)

    def _private_mode(self, body, enabled):
        raw = body[1:] if body.startswith("?") else body
        modes = []
        for part in raw.split(";"):
            try:
                modes.append(int(part))
            except (TypeError, ValueError):
                continue
        for mode in modes:
            if mode in _ALT_MODES:
                if enabled:
                    self._enter_alt()
                else:
                    self._leave_alt()
            elif mode == 25:
                self.cursor_visible = bool(enabled)
            elif mode == 1:
                self.application_cursor = bool(enabled)
            elif mode == 2004:
                self.bracketed_paste = bool(enabled)
            elif mode in (1000, 1002, 1003):
                if enabled:
                    self._mouse_modes.add(mode)
                else:
                    self._mouse_modes.discard(mode)
            elif mode == 1006:
                self.mouse_sgr = bool(enabled)
            elif mode == 1005:
                self.mouse_utf8 = bool(enabled)
            elif mode == 7:
                self.autowrap = bool(enabled)
                self._wrap_pending = False
            elif mode == 6:
                self.origin_mode = bool(enabled)
                self.cursor_row = self.scroll_top if enabled else 0
                self.cursor_col = 0
                self._wrap_pending = False

    @staticmethod
    def _palette_color(index):
        index = max(0, min(255, index))
        if index < 16:
            return ANSI_COLORS[index] + (255,)
        if index >= 232:
            shade = 8 + (index - 232) * 10
            return (shade, shade, shade, 255)
        index -= 16
        levels = (0, 95, 135, 175, 215, 255)
        return (levels[index // 36], levels[(index // 6) % 6], levels[index % 6], 255)

    def _sgr(self, body):
        params = self._params(body, default=0)
        i = 0
        while i < len(params):
            value = params[i]
            if value == 0:
                self._reset_attributes()
            elif value in (1, 22):
                self.bold = value == 1
            elif value in (4, 24):
                self.underline = value == 4
            elif value in (7, 27):
                self.inverse = value == 7
            elif value == 39:
                self.foreground = DEFAULT_FG
            elif value == 49:
                self.background = DEFAULT_BG
            elif 30 <= value <= 37 or 90 <= value <= 97:
                self.foreground = self._palette_color(value - 30 if value < 90 else value - 90 + 8)
            elif 40 <= value <= 47 or 100 <= value <= 107:
                self.background = self._palette_color(value - 40 if value < 100 else value - 100 + 8)
            elif value in (38, 48) and i + 2 < len(params):
                color = None
                if params[i + 1] == 5:
                    color = self._palette_color(params[i + 2])
                    i += 2
                elif params[i + 1] == 2 and i + 4 < len(params):
                    color = tuple(max(0, min(255, v)) for v in params[i + 2:i + 5]) + (255,)
                    i += 4
                if color is not None:
                    if value == 38:
                        self.foreground = color
                    else:
                        self.background = color
            i += 1

    def _csi(self, body, command):
        private = body.startswith("?")
        if command in ("h", "l") and private:
            self._private_mode(body, command == "h")
            return
        if not self.active:
            return
        if command == "m":
            self._sgr(body)
            return
        if command == "n":
            if body == "5":
                self._replies.append("\x1b[0n")
            elif body in ("6", "?6"):
                row = self.cursor_row - (self.scroll_top if self.origin_mode else 0) + 1
                self._replies.append("\x1b[{}{};{}R".format("?" if private else "", row, self.cursor_col + 1))
            return
        if command == "c":
            # VT100 + advanced video; do not advertise unsupported capabilities.
            if body in ("", "0"):
                self._replies.append("\x1b[?1;2c")
            elif body in (">", ">0"):
                self._replies.append("\x1b[>0;1;0c")
            return
        if command in ("h", "l") and not private:
            if 4 in self._params(body):
                self.insert_mode = command == "h"
            return
        params = self._params(body)
        first = params[0] if params else 1
        if command in "ABCDEFGH`dfJKLMPSTX@r":
            self._wrap_pending = False
        top = self.scroll_top if self.origin_mode else 0
        bottom = self.scroll_bottom if self.origin_mode else self.rows - 1
        if command == "A":
            self.cursor_row = max(top, self.cursor_row - max(1, first))
        elif command == "B":
            self.cursor_row = min(bottom, self.cursor_row + max(1, first))
        elif command == "C":
            self.cursor_col = min(self.columns - 1, self.cursor_col + max(1, first))
        elif command == "D":
            self.cursor_col = max(0, self.cursor_col - max(1, first))
        elif command == "E":
            self.cursor_row = min(bottom, self.cursor_row + max(1, first))
            self.cursor_col = 0
        elif command == "F":
            self.cursor_row = max(top, self.cursor_row - max(1, first))
            self.cursor_col = 0
        elif command in ("G", "`"):
            self.cursor_col = max(0, min(self.columns - 1, max(1, first) - 1))
        elif command == "d":
            self.cursor_row = max(top, min(bottom, top + max(1, first) - 1))
        elif command == "Z":
            self.cursor_col = max(0, ((self.cursor_col - 1) // 8 - max(1, first) + 1) * 8)
            self._wrap_pending = False
        elif command == "b":
            for _ in range(min(max(1, first), self.columns * self.rows)):
                self._put(self._last_char)
        elif command in ("H", "f"):
            row = params[0] if len(params) > 0 else 1
            col = params[1] if len(params) > 1 else 1
            self.cursor_row = max(top, min(bottom, top + max(1, row) - 1))
            self.cursor_col = max(0, min(self.columns - 1, max(1, col) - 1))
        elif command == "J":
            self._erase_display(0 if body == "" else first)
        elif command == "K":
            self._erase_line(0 if body == "" else first)
        elif command == "X":
            count = max(1, first)
            self._erase_cells(self.cursor_row, self.cursor_col, min(self.columns, self.cursor_col + count))
        elif command == "P":
            count = min(max(1, first), self.columns - self.cursor_col)
            row = self._screen[self.cursor_row]
            del row[self.cursor_col:self.cursor_col + count]
            row.extend([" "] * count)
            styles = self._styles[self.cursor_row]
            del styles[self.cursor_col:self.cursor_col + count]
            styles.extend([self._style()] * count)
            self._repair_row(self.cursor_row)
        elif command == "@":
            count = min(max(1, first), self.columns - self.cursor_col)
            row = self._screen[self.cursor_row]
            for _ in range(count):
                row.insert(self.cursor_col, " ")
            del row[self.columns:]
            styles = self._styles[self.cursor_row]
            styles[self.cursor_col:self.cursor_col] = [self._style()] * count
            del styles[self.columns:]
            self._repair_row(self.cursor_row)
        elif command == "L":
            count = min(max(1, first), self.scroll_bottom - self.cursor_row + 1)
            if self.scroll_top <= self.cursor_row <= self.scroll_bottom:
                for _ in range(count):
                    self._screen.insert(self.cursor_row, [" "] * self.columns)
                    del self._screen[self.scroll_bottom + 1]
                    self._styles.insert(self.cursor_row, [self._style()] * self.columns)
                    del self._styles[self.scroll_bottom + 1]
        elif command == "M":
            count = min(max(1, first), self.scroll_bottom - self.cursor_row + 1)
            if self.scroll_top <= self.cursor_row <= self.scroll_bottom:
                for _ in range(count):
                    del self._screen[self.cursor_row]
                    self._screen.insert(self.scroll_bottom, [" "] * self.columns)
                    del self._styles[self.cursor_row]
                    self._styles.insert(self.scroll_bottom, [self._style()] * self.columns)
        elif command == "S":
            self._scroll_up(max(1, first))
        elif command == "T":
            self._scroll_down(max(1, first))
        elif command == "r":
            top = params[0] if len(params) > 0 else 1
            bottom = params[1] if len(params) > 1 else self.rows
            if 1 <= top < bottom <= self.rows:
                self.scroll_top, self.scroll_bottom = top - 1, bottom - 1
                self.cursor_row = self.scroll_top if self.origin_mode else 0
                self.cursor_col = 0
        elif command == "s":
            self._save_cursor()
        elif command == "u":
            self._restore_cursor()

    def feed(self, data):
        """Consume one raw PTY chunk and return whether screen state changed."""
        if not data:
            return False
        source = self._pending + str(data)
        self._pending = ""
        changed = False
        i, n = 0, len(source)
        while i < n:
            char = source[i]
            if char == "\x1b":
                if i + 1 >= n:
                    self._pending = source[i:]
                    break
                nxt = source[i + 1]
                if nxt == "[":
                    j = i + 2
                    while j < n and not ("@" <= source[j] <= "~"):
                        j += 1
                    if j >= n:
                        self._pending = source[i:]
                        break
                    self._csi(source[i + 2:j], source[j])
                    changed = True
                    i = j + 1
                    continue
                if nxt == "]":  # OSC title/clipboard sequence
                    j = i + 2
                    complete = False
                    while j < n:
                        if source[j] == "\x07":
                            j += 1
                            complete = True
                            break
                        if source[j] == "\x1b" and j + 1 < n and source[j + 1] == "\\":
                            j += 2
                            complete = True
                            break
                        j += 1
                    if not complete:
                        self._pending = source[i:]
                        break
                    i = j
                    continue
                if nxt in ("P", "^", "_"):  # DCS/PM/APC until ST
                    end = source.find("\x1b\\", i + 2)
                    if end < 0:
                        self._pending = source[i:]
                        break
                    i = end + 2
                    continue
                if self.active:
                    if nxt == "7":
                        self._save_cursor()
                    elif nxt == "8":
                        self._restore_cursor()
                    elif nxt == "D":
                        self._index()
                    elif nxt == "M":
                        self._reverse_index()
                    elif nxt == "E":
                        self._index(); self.cursor_col = 0
                    elif nxt == "c":
                        self._reset_attributes()
                        self._clear()
                    changed = True
                # Charset/keypad selectors consume one following byte; charset
                # selectors consume an additional designation character.
                if nxt in ("(", ")", "*", "+") and i + 2 >= n:
                    self._pending = source[i:]
                    break
                if nxt == "(" and self.active:
                    self._graphics = source[i + 2] == "0"
                i += 3 if nxt in ("(", ")", "*", "+") else 2
                continue

            if not self.active:
                i += 1
                continue
            if char == "\r":
                self.cursor_col = 0
                self._wrap_pending = False
                changed = True
            elif char in ("\n", "\v", "\f"):
                self._wrap_pending = False
                self._index()
                changed = True
            elif char == "\b":
                self._wrap_pending = False
                self.cursor_col = max(0, self.cursor_col - 1)
                changed = True
            elif char == "\t":
                self._wrap_pending = False
                self.cursor_col = min(self.columns - 1, ((self.cursor_col // 8) + 1) * 8)
                changed = True
            elif ord(char) >= 32 and char != "\x7f":
                if self._graphics:
                    char = dict(zip("jklmnqtuvwx", "┘┐┌└┼─├┤┴┬│")).get(char, char)
                self._put(char)
                changed = True
            i += 1
        return changed
