"""Viewport-limited terminal drawing independent of console command handling.

The renderer deliberately depends only on DearUIQt retained/painting facades.
The native backend is injected by ``ConsoleDockPanel`` for deterministic tests,
but no Dear PyGui symbols leak into WinUx rendering code.
"""
import math
import time
from ...runtime.terminal.vt import terminal_text_width

from DearUIQt.gui import QFontMetrics, QPainter
from DearUIQt.widgets import QRetainedItem


class ConsoleRenderer:
    def __init__(self, view, backend, palette):
        self.view, self.backend = view, backend
        self.palette = {key: palette[key] for key in (
            'COMMAND', 'FIND_BG', 'FIND_BORDER', 'FIND_CURRENT', 'FIND_MATCH',
            'FIND_MUTED', 'FIND_TEXT', 'SELECTION', 'STYLE_COLORS', 'TEXT')}
        self._caret_state = None
        self._canvas_size = None

    def _item(self, tag):
        return QRetainedItem(tag, backend=self.backend, owns_native=False)

    def _delete_items(self, items):
        for tag in tuple(items or ()):
            try:
                self._item(tag).deleteNative()
            except Exception:
                pass

    def _viewport_shown(self, content, state):
        if state.get('visible') is False:
            return False
        # DPG can retain visible=True on a child after its dock/ancestor hides.
        # Check native ancestry too; adapted widgets may be hidden externally.
        item = content
        while item is not None:
            if not item.isVisible():
                return False
            parent = item.parentItem()
            item = self._item(parent) if parent else None
        return True

    def paint(self):
        view = self.view
        COMMAND = self.palette["COMMAND"]
        FIND_BG = self.palette["FIND_BG"]
        FIND_BORDER = self.palette["FIND_BORDER"]
        FIND_CURRENT = self.palette["FIND_CURRENT"]
        FIND_MATCH = self.palette["FIND_MATCH"]
        FIND_MUTED = self.palette["FIND_MUTED"]
        FIND_TEXT = self.palette["FIND_TEXT"]
        SELECTION = self.palette["SELECTION"]
        STYLE_COLORS = self.palette["STYLE_COLORS"]
        TEXT = self.palette["TEXT"]

        content = self._item(view.content)
        canvas = self._item(view.canvas)
        state = content.nativeState()
        overlay = getattr(view, "_scroller_arrow_overlay", None)
        if not self._viewport_shown(content, state):
            # Retained hidden/clipped panels still expose their previous rect.
            # Keep terminal parsing in the refresh path, but do no layout/font
            # work or painting for an invisible viewport. Release any old grab.
            if overlay is not None:
                overlay.hide()
            return
        rect = state.get("rect_size")
        if not rect:
            return

        if overlay is not None:
            overlay.update()

        if view._font:
            measured = QFontMetrics(view._font, backend=self.backend).size("M")
            if measured.width() > 0 and measured.height() > 0:
                view._char_width = max(1, measured.width())
                view._line_height = max(16, measured.height() + 2)

        width = max(40, int(rect[0]) - 24)
        columns = max(8, int(width / view._char_width))
        view._render_columns = columns
        terminal_rows = max(2, int(max(20, rect[1] - 4) / view._line_height))
        dimension_callback = getattr(view, "_terminal_dimensions_changed", None)
        if callable(dimension_callback):
            dimension_callback(columns, terminal_rows)
        raw_mode = bool(getattr(view, "_raw_terminal_active", lambda: False)())
        if raw_mode:
            vt = view._vt_screen
            rows = vt.text_rows()
            cursor_row, cursor_column = vt.cursor_row, vt.cursor_col
            view._render_rows = rows
            total = max(20, len(rows) * view._line_height)
        else:
            rows, cursor_row, cursor_column = view.buffer.layout_view(columns)
            view._render_rows = rows
            if view._find_active and (view._find_dirty or view._find_columns != columns):
                view._rebuild_find_matches(columns)
            total = max(20, len(rows) * view._line_height + 8)
        size = (width, total)

        # Capture the user's viewport *before* changing canvas height. Dear
        # ImGui may clamp/rebase scroll when content geometry changes, which
        # made SSH output appear to jump while the user was reading history.
        scroll_before_resize = content.verticalScrollValue()
        manual_scroll_locked = (
            False if raw_mode else
            time.monotonic() < float(getattr(view, "_manual_scroll_until", 0.0) or 0.0))
        preserve_viewport = bool(
            not raw_mode and not view._follow_tail
            and not getattr(view, "_cursor_scroll_pending", False)
            and not view._find_pending_scroll)
        if size != self._canvas_size:
            canvas.configure(width=width, height=total)
            self._canvas_size = size
            if preserve_viewport:
                content.setVerticalScrollValue(max(0.0, scroll_before_resize))

        # Explicit navigation has priority over background tail following.
        if raw_mode:
            content.setVerticalScrollValue(0)
            scroll = 0.0
            view._scroll_pending = False
            view._cursor_scroll_pending = False
        elif view._find_pending_scroll and view._find_matches and view._find_index >= 0:
            row = view._find_matches[view._find_index][0]
            target = max(0, row * view._line_height - max(0, int(rect[1] / 2)))
            content.setVerticalScrollValue(target)
            view._find_pending_scroll = False
            view._follow_tail = False
            scroll = float(target)
        else:
            scroll = content.verticalScrollValue()
            if scroll == 0.0 and scroll_before_resize:
                scroll = scroll_before_resize

        # Any local edit/caret movement must reveal the command being edited.
        cursor_revealed = False
        if getattr(view, "_cursor_scroll_pending", False):
            top = cursor_row * view._line_height
            bottom = top + view._line_height + 8
            if top < scroll:
                scroll = max(0, top)
                content.setVerticalScrollValue(scroll)
            elif bottom > scroll + rect[1]:
                scroll = max(0, bottom - rect[1])
                content.setVerticalScrollValue(scroll)
            view._cursor_scroll_pending = False
            view._scroll_pending = False
            view._follow_tail = True
            view._manual_scroll_until = 0.0
            manual_scroll_locked = False
            cursor_revealed = True
        elif view._scroll_pending and not manual_scroll_locked:
            scroll = max(0, total - rect[1] + 10)
            content.setVerticalScrollValue(scroll)
            view._scroll_pending = False

        scroll_max = content.verticalScrollMaximum()
        near_bottom = scroll_max <= scroll + view._line_height * 1.5
        if (not raw_mode and not cursor_revealed and not manual_scroll_locked
                and not view._selection_dragging and not view._find_active
                and view._selection_bounds() is None):
            view._follow_tail = near_bottom

        first = max(0, int(scroll / view._line_height) - 1)
        last = min(len(rows), first + int(math.ceil(rect[1] / view._line_height)) + 3)
        if raw_mode:
            styled_rows = vt.styled_rows(first, last)
        else:
            styled_rows, _cursor_row, _cursor_column = view.buffer.styled_layout_slice(
                columns, first, last)
        elapsed = max(0.0, time.monotonic() - getattr(view, "_caret_blink_started", 0.0))
        blink = int(elapsed * 2) % 2 == 0
        current_match = (
            view._find_matches[view._find_index]
            if view._find_matches and view._find_index >= 0 else None)
        paint = (
            first, last, tuple(tuple(segments) for segments in styled_rows),
            cursor_row, cursor_column, width, view._char_width, view._line_height,
            view._font, int(scroll), view._find_active, view._find_query,
            view._find_index, len(view._find_matches), current_match, raw_mode)

        painter = QPainter(canvas, backend=self.backend)
        if paint != view._last_paint:
            self._delete_items(getattr(view, "_line_items", []))
            self._delete_items(getattr(view, "_selection_items", []))
            self._delete_items(getattr(view, "_find_match_items", []))
            self._delete_items(getattr(view, "_find_items", []))
            view._line_items = []
            view._selection_items = []
            view._find_match_items = []
            view._find_items = []

            if view._find_active and view._find_query:
                for match_index, (row_index, start_col, end_col) in enumerate(view._find_matches):
                    if first <= row_index < last:
                        fill = FIND_CURRENT if match_index == view._find_index else FIND_MATCH
                        item = painter.drawRect(
                            (start_col * view._char_width, row_index * view._line_height),
                            (end_col * view._char_width, (row_index + 1) * view._line_height),
                            color=fill, fill=fill)
                        view._find_match_items.append(item)

            current_top = cursor_row * view._line_height
            self._item(view._current_line_fill).configure(
                pmin=(0, current_top),
                pmax=(width + 4, current_top + view._line_height),
                show=not raw_mode)

            # ``styled_rows`` is already the [first:last] viewport slice.
            for offset, segments in enumerate(styled_rows):
                row_y = (first + offset) * view._line_height
                row_x = 0
                for style_name, segment_text in segments:
                    if not segment_text:
                        continue
                    cell_style = raw_mode and isinstance(style_name, tuple) and isinstance(style_name[0], tuple)
                    foreground = style_name[0] if cell_style else (
                        style_name if isinstance(style_name, tuple) else STYLE_COLORS.get(style_name, TEXT))
                    if cell_style:
                        background, underline = style_name[1:]
                        end_x = row_x + terminal_text_width(segment_text) * view._char_width
                        if background != (12, 12, 12, 255):
                            view._line_items.append(painter.drawRect(
                                (row_x, row_y), (end_x, row_y + view._line_height),
                                color=background, fill=background))
                        if underline:
                            view._line_items.append(painter.drawRect(
                                (row_x, row_y + view._line_height - 2),
                                (end_x, row_y + view._line_height - 1),
                                color=foreground, fill=foreground))
                    item = painter.drawText(
                        (row_x, row_y), segment_text,
                        color=foreground,
                        size=15, font=view._font)
                    view._line_items.append(item)
                    row_x += (terminal_text_width(segment_text) if raw_mode else len(segment_text)) * view._char_width

            # Selection and cursor must be above terminal background fills;
            # otherwise reverse-video editor menus hide both overlays.
            bounds = view._selection_bounds()
            if bounds is not None:
                (r0, c0), (r1, c1) = bounds
                for row_index in range(max(first, r0), min(last - 1, r1) + 1):
                    start_col = c0 if row_index == r0 else 0
                    end_col = c1 if row_index == r1 else (vt.columns if raw_mode else len(rows[row_index]))
                    if end_col > start_col:
                        view._selection_items.append(painter.drawRect(
                            (start_col * view._char_width, row_index * view._line_height),
                            (end_col * view._char_width, (row_index + 1) * view._line_height),
                            color=SELECTION, fill=SELECTION))
            self._item(view._caret).deleteNative()
            view._caret = painter.drawRect((0, 0), (0, 0), color=COMMAND, fill=COMMAND)
            self._caret_state = None

            if view._find_active:
                box_width = min(360, max(240, int(width * 0.44)))
                box_x = max(4, width - box_width - 8)
                box_y = int(scroll) + 6
                box_h = 26
                bg = painter.drawRect(
                    (box_x, box_y), (box_x + box_width, box_y + box_h),
                    color=FIND_BORDER, fill=FIND_BG)
                view._find_items.append(bg)
                count_text = (
                    "0/0" if not view._find_matches
                    else "{}/{}".format(view._find_index + 1, len(view._find_matches)))
                query_text = view._find_query or "type to find"
                max_query = max(8, int((box_width - 130) / max(1, view._char_width)))
                if len(query_text) > max_query:
                    query_text = "..." + query_text[-max(1, max_query - 3):]
                query_color = FIND_TEXT if view._find_query else FIND_MUTED
                view._find_items.append(painter.drawText(
                    (box_x + 8, box_y + 4), "Find: " + query_text,
                    color=query_color, size=14, font=view._font))
                view._find_items.append(painter.drawText(
                    (box_x + box_width - 82, box_y + 4), count_text,
                    color=FIND_TEXT, size=14, font=view._font))
                view._find_items.append(painter.drawText(
                    (box_x + box_width - 50, box_y + 4), "F3 Esc",
                    color=FIND_MUTED, size=11, font=view._font))
            view._last_paint = paint

        x, y = cursor_column * view._char_width, cursor_row * view._line_height
        caret_width = max(2, int(view._char_width))
        overwrite = False if raw_mode else bool(getattr(view.buffer, "overwrite_mode", False))
        caret_height = (max(2, int(view._line_height) - 4)
                        if (overwrite or raw_mode) else 2)
        caret_top = (y + 2 if (overwrite or raw_mode)
                     else y + view._line_height - caret_height - 1)
        keyboard_active = getattr(view, "keyboard_active", lambda: True)()
        bounds = view._selection_bounds()
        selecting = bounds is not None and bounds[0] != bounds[1]
        vt_cursor_visible = bool(getattr(getattr(view, "_vt_screen", None), "cursor_visible", True))
        pending_clear = True if raw_mode else view.buffer.pending is None
        caret_state = (
            x, caret_top, caret_width, caret_height, overwrite, blink,
            pending_clear, view._find_active, keyboard_active, selecting,
            raw_mode, vt_cursor_visible)
        if caret_state != self._caret_state:
            self._item(view._caret).configure(
                pmin=(x, caret_top),
                pmax=(x + caret_width, caret_top + caret_height),
                color=COMMAND, fill=COMMAND,
                show=(blink and pending_clear and not view._find_active
                      and keyboard_active and not selecting and vt_cursor_visible))
            self._caret_state = caret_state
