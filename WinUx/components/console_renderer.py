"""Viewport-limited terminal drawing independent of console command handling."""
import math
import time


class ConsoleRenderer:
    def __init__(self, view, backend, palette):
        self.view, self.backend = view, backend
        self.palette = {key: palette[key] for key in ('COMMAND', 'FIND_BG', 'FIND_BORDER', 'FIND_CURRENT', 'FIND_MATCH', 'FIND_MUTED', 'FIND_TEXT', 'SELECTION', 'STYLE_COLORS', 'TEXT')}
        self._caret_state = None
        self._canvas_size = None

    def paint(self):
        view = self.view
        dpg = self.backend
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
        state = dpg.get_item_state(view.content)
        rect = state.get("rect_size")
        if not rect:
            return
        overlay = getattr(view, "_scroller_arrow_overlay", None)
        if overlay is not None:
            overlay.update()
        if view._font:
            measured = dpg.get_text_size("M", font=view._font)
            if measured:
                view._char_width = max(1, measured[0])
                view._line_height = max(16, measured[1] + 2)
        width = max(40, int(rect[0])-24)
        columns = int(width/view._char_width)
        styled_rows, cursor_row, cursor_column = view.buffer.styled_layout(columns)
        rows = ["".join(segment for _style, segment in segments) for segments in styled_rows]
        view._render_rows = rows
        if view._find_active and (view._find_dirty or view._find_columns != columns):
            view._rebuild_find_matches(columns)
        total = max(20, len(rows)*view._line_height + 8)
        size = (width, total)
        if size != self._canvas_size:
            dpg.configure_item(view.canvas, width=width, height=total)
            self._canvas_size = size
        if view._scroll_pending:
            dpg.set_y_scroll(view.content, max(0, total-rect[1]+10))
            view._scroll_pending = False
        if view._find_pending_scroll and view._find_matches and view._find_index >= 0:
            row = view._find_matches[view._find_index][0]
            target = max(0, row*view._line_height - max(0, int(rect[1]/2)))
            dpg.set_y_scroll(view.content, target)
            view._find_pending_scroll = False
            view._follow_tail = False
        scroll = dpg.get_y_scroll(view.content)
        try:
            scroll_max = dpg.get_y_scroll_max(view.content)
            near_bottom = scroll_max <= scroll + view._line_height * 1.5
            if not view._selection_dragging and not view._find_active:
                view._follow_tail = near_bottom
        except Exception:
            pass
        first = max(0, int(scroll/view._line_height)-1)
        last = min(len(rows), first + int(math.ceil(rect[1]/view._line_height)) + 3)
        blink = int(time.monotonic()*2) % 2 == 0
        current_match = view._find_matches[view._find_index] if view._find_matches and view._find_index >= 0 else None
        paint = (first, last, tuple(tuple(segments) for segments in styled_rows[first:last]), cursor_row, cursor_column, width, view._char_width, view._line_height, view._font,
                 int(scroll), view._find_active, view._find_query, view._find_index, len(view._find_matches), current_match)
        if paint != view._last_paint:
            for item in getattr(view, "_line_items", []):
                if dpg.does_item_exist(item):
                    dpg.delete_item(item)
            for item in getattr(view, "_selection_items", []):
                if dpg.does_item_exist(item):
                    dpg.delete_item(item)
            for item in getattr(view, "_find_match_items", []):
                if dpg.does_item_exist(item):
                    dpg.delete_item(item)
            for item in getattr(view, "_find_items", []):
                if dpg.does_item_exist(item):
                    dpg.delete_item(item)
            view._line_items = []
            view._selection_items = []
            view._find_match_items = []
            view._find_items = []
            if view._find_active and view._find_query:
                for match_index, (row_index, start_col, end_col) in enumerate(view._find_matches):
                    if first <= row_index < last:
                        fill = FIND_CURRENT if match_index == view._find_index else FIND_MATCH
                        item = dpg.draw_rectangle(
                            (start_col*view._char_width, row_index*view._line_height),
                            (end_col*view._char_width, (row_index+1)*view._line_height),
                            color=fill, fill=fill, parent=view.canvas)
                        view._find_match_items.append(item)
            bounds = view._selection_bounds()
            if bounds is not None:
                (r0, c0), (r1, c1) = bounds
                for row_index in range(max(first, r0), min(last - 1, r1) + 1):
                    start_col = c0 if row_index == r0 else 0
                    end_col = c1 if row_index == r1 else len(rows[row_index])
                    if end_col > start_col:
                        rect = dpg.draw_rectangle(
                            (start_col*view._char_width, row_index*view._line_height),
                            (end_col*view._char_width, (row_index+1)*view._line_height),
                            color=SELECTION, fill=SELECTION, parent=view.canvas)
                        view._selection_items.append(rect)
            current_top = cursor_row * view._line_height
            dpg.configure_item(view._current_line_fill,
                               pmin=(0, current_top),
                               pmax=(width + 4, current_top + view._line_height),
                               show=True)
            for offset, segments in enumerate(styled_rows[first:last]):
                row_y = (first + offset) * view._line_height
                row_x = 0
                for style_name, segment_text in segments:
                    if not segment_text:
                        continue
                    item = dpg.draw_text((row_x, row_y), segment_text,
                                         color=(style_name if isinstance(style_name, tuple) else STYLE_COLORS.get(style_name, TEXT)),
                                         size=15, parent=view.canvas)
                    if view._font:
                        try:
                            dpg.bind_item_font(item, view._font)
                        except Exception:
                            pass
                    view._line_items.append(item)
                    row_x += len(segment_text) * view._char_width
            if view._find_active:
                box_width = min(360, max(240, int(width * 0.44)))
                box_x = max(4, width - box_width - 8)
                box_y = int(scroll) + 6
                box_h = 26
                bg = dpg.draw_rectangle((box_x, box_y), (box_x + box_width, box_y + box_h),
                                        color=FIND_BORDER, fill=FIND_BG, parent=view.canvas)
                view._find_items.append(bg)
                count_text = "0/0" if not view._find_matches else "{}/{}".format(view._find_index + 1, len(view._find_matches))
                query_text = view._find_query or "type to find"
                max_query = max(8, int((box_width - 130) / max(1, view._char_width)))
                if len(query_text) > max_query:
                    query_text = "..." + query_text[-max(1, max_query - 3):]
                query_color = FIND_TEXT if view._find_query else FIND_MUTED
                item = dpg.draw_text((box_x + 8, box_y + 4), "Find: " + query_text, color=query_color, size=14, parent=view.canvas)
                view._find_items.append(item)
                item = dpg.draw_text((box_x + box_width - 82, box_y + 4), count_text, color=FIND_TEXT, size=14, parent=view.canvas)
                view._find_items.append(item)
                item = dpg.draw_text((box_x + box_width - 50, box_y + 4), "F3 Esc", color=FIND_MUTED, size=11, parent=view.canvas)
                view._find_items.append(item)
                if view._font:
                    for item in view._find_items[1:]:
                        try:
                            dpg.bind_item_font(item, view._font)
                        except Exception:
                            pass
            view._last_paint = paint
        x, y = cursor_column*view._char_width, cursor_row*view._line_height
        # Classic conhost/cmd uses a low horizontal caret. Keep the caret
        # inside the current character cell and anchor it to the same row
        # grid that the terminal text uses.
        caret_width = max(2, int(view._char_width))
        caret_height = 2
        caret_top = y + view._line_height - caret_height - 1
        caret_state = (x, caret_top, caret_width, caret_height, blink, view.buffer.pending is None, view._find_active)
        if caret_state != self._caret_state:
            dpg.configure_item(view._caret, pmin=(x, caret_top),
                           pmax=(x + caret_width, caret_top + caret_height),
                           color=COMMAND, fill=COMMAND,
                           show=blink and view.buffer.pending is None and not view._find_active)
            self._caret_state = caret_state


