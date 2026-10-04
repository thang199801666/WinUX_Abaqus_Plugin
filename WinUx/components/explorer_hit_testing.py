"""Geometry-only hit testing for :class:`ExplorerListView`."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

import dearpygui.dearpygui as dpg

from .shared_scroller import dpg_window_rect


class ExplorerHitTestingMixin:
    def _header_mouse_position(self):
        """Return (inside_header, local_x) without relying on drawlist hover state."""
        if not dpg.does_item_exist(self.header_canvas):
            return False, 0.0
        try:
            mx, my = dpg.get_mouse_pos(local=False)
            rect = self._safe_item_rect(self.header_canvas)
            if rect is None:
                return False, 0.0
            x0, y0, x1, y1 = rect
            # get_item_rect_max can report the full unclipped drawlist width. For
            # hit testing, limit the active width to the visible pane as well.
            pane_w = max(1.0, float(dpg.get_item_rect_size(self.window_tag)[0]))
            total_w = sum(self._column_widths.get(c["key"], self.MIN_COLUMN_WIDTH)
                          for c in self._visible_columns())
            active_w = min(total_w, pane_w, max(0.0, x1 - x0))
            active_h = min(float(self.HEADER_HEIGHT), max(0.0, y1 - y0))
            inside = x0 <= mx <= x0 + active_w and y0 <= my <= y0 + active_h
            return inside, mx - x0
        except Exception:
            return False, 0.0


    def header_pointer_hit_test(self, separator_only=False):
        """Return whether the pointer belongs to this header interaction.

        Workspace splitters use a deliberately generous invisible grab band.
        The Job Viewer header can sit immediately beside one of those bands,
        so the parent window needs a geometry-only way to ask whether the
        header should receive the press first.  This mirrors Qt's child-widget
        hit-test priority: QHeaderView sorting/resizing wins over an enclosing
        QSplitter whenever the pointer is physically inside the header.
        """
        inside, local_x = self._header_mouse_position()
        if inside:
            return (self._separator_at(local_x) is not None
                    if separator_only else True)

        # On Windows mixed-DPI configurations, DPG's client coordinates can
        # lag the native cursor by one frame. Fall back to the physical screen
        # geometry already maintained for the native SIZEWE cursor hook.
        if os.name == "nt":
            try:
                rect = self._native_header_screen_rect
                if rect is None:
                    self._update_native_cursor_geometry()
                    rect = self._native_header_screen_rect
                if rect is not None:
                    point = wintypes.POINT()
                    user32 = ctypes.windll.user32
                    if user32.GetCursorPos(ctypes.byref(point)):
                        x0, y0, x1, y1 = map(float, rect)
                        if x0 <= point.x <= x1 and y0 <= point.y <= y1:
                            if not separator_only:
                                return True
                            hit = max(8.0, float(self.SEPARATOR_HIT))
                            return any(
                                abs(float(point.x) - float(separator_x)) <= hit
                                for separator_x in self._native_separator_screen_x
                            )
            except Exception:
                pass
        return False


    def _mouse_in_pinned_row(self):
        if self._pinned_item is None or not hasattr(self, "pinned_canvas"):
            return False
        if not dpg.does_item_exist(self.pinned_canvas) or not dpg.is_item_shown(self.pinned_canvas):
            return False

        # Mouse callbacks are registered globally for every ListView.  Never
        # trust only a cached rectangle here: after resize/navigation DPG can
        # briefly return the previous rectangle for another pane, causing both
        # Local and Server pinned rows to react to one click.  The hovered state
        # identifies the actual owner of the pointer.
        try:
            if dpg.is_item_hovered(self.pinned_canvas):
                return True
            if not dpg.is_item_hovered(self.window_tag):
                return False
        except Exception:
            pass

        rect = self._safe_item_rect(self.pinned_canvas)
        if not rect:
            return False
        try:
            mx, my = map(float, dpg.get_mouse_pos(local=False))
        except Exception:
            return False
        x0, y0, x1, y1 = rect
        return x0 <= mx <= x1 and y0 <= my <= y1


    def _row_at_mouse(self):
        """Return the row under the mouse only inside the actual column area.

        The child window may be wider than the combined visible columns. The
        blank area to the right of the last column is not part of any row and
        must never produce hover, selection, or item dragging.
        """
        body_pos = self._body_local_pos()
        if body_pos is None:
            return None

        x, y = body_pos
        content_width = self._row_content_width()
        if x < 0.0 or x >= content_width:
            return None

        index = int(y // self.ROW_HEIGHT)
        return index if 0 <= index < len(self.items) else None


    def _safe_item_rect(self, tag):
        """Return an item's screen-space rectangle or None while DPG is laying it out.

        Some Dear PyGui releases omit ``rect_min``/``rect_max`` from the item
        state for child windows during the first frame, while hidden, or while
        their parent is being resized.  Mouse handlers are global, so they may
        run during exactly that interval.  Never let that transient state escape
        as a KeyError.
        """
        if not tag or not dpg.does_item_exist(tag):
            return None

        try:
            state = dpg.get_item_state(tag) or {}
        except Exception:
            state = {}

        rect_min = state.get("rect_min")
        rect_size = state.get("rect_size")
        if rect_min is not None and rect_size is not None:
            try:
                x0, y0 = float(rect_min[0]), float(rect_min[1])
                width, height = float(rect_size[0]), float(rect_size[1])
                if width >= 0.0 and height >= 0.0:
                    return x0, y0, x0 + width, y0 + height
            except (TypeError, ValueError, IndexError):
                pass

        rect_max = state.get("rect_max")
        if rect_min is not None and rect_max is not None:
            try:
                return (
                    float(rect_min[0]), float(rect_min[1]),
                    float(rect_max[0]), float(rect_max[1]),
                )
            except (TypeError, ValueError, IndexError):
                pass

        window_rect = dpg_window_rect(dpg, tag)
        if window_rect is not None:
            return window_rect

        # Compatibility fallback for releases that expose geometry only through
        # the public getters.  Each call is protected because these getters may
        # still raise KeyError until the first completed render frame.
        try:
            x0, y0 = dpg.get_item_rect_min(tag)
            width, height = dpg.get_item_rect_size(tag)
            return float(x0), float(y0), float(x0) + float(width), float(y0) + float(height)
        except (KeyError, RuntimeError, TypeError, ValueError, IndexError):
            return None
        except Exception:
            return None


    def _mouse_in_item(self, tag):
        rect = self._safe_item_rect(tag)
        if rect is None:
            return False
        mx, my = dpg.get_mouse_pos(local=False)
        x0, y0, x1, y1 = rect
        return x0 <= mx <= x1 and y0 <= my <= y1


    def _body_viewport_rect(self):
        """Return the visible body viewport in screen coordinates."""
        overlay = getattr(self, "_scroller_arrow_overlay", None)
        geometry_item = overlay.container if overlay is not None else self.body_window
        rect = dpg_window_rect(dpg, geometry_item, clip=True)
        if rect is None:
            if dpg_window_rect(dpg, geometry_item) is not None:
                return None
            rect = self._safe_item_rect(geometry_item)
        if rect is not None:
            pane = self._safe_item_rect(self.window_tag)
            if pane is not None:
                rect = (max(rect[0], pane[0]), max(rect[1], pane[1]),
                        min(rect[2], pane[2]), min(rect[3], pane[3]))
            return rect if rect[2] > rect[0] and rect[3] > rect[1] else None

        # Some Dear PyGui releases (e.g. 2.x) no longer populate rect_min /
        # rect_max for child-window items -- only for drawing items. Rebuild
        # the visible viewport from the body canvas (a drawlist, whose
        # rect_min stays reliable) plus the current scroll offset, combined
        # with the body window's own rect_size (still reliable for windows).
        try:
            canvas_rect_min = dpg.get_item_rect_min(self.body_canvas)
        except Exception:
            canvas_rect_min = None
        if canvas_rect_min is not None:
            try:
                scroll_x = float(dpg.get_x_scroll(self.body_window))
            except Exception:
                scroll_x = 0.0
            try:
                scroll_y = float(dpg.get_y_scroll(self.body_window))
            except Exception:
                scroll_y = 0.0
            try:
                width, height = dpg.get_item_rect_size(self.body_window)
                vx0 = float(canvas_rect_min[0]) + scroll_x
                vy0 = float(canvas_rect_min[1]) + scroll_y
                vx1 = vx0 + float(width)
                vy1 = vy0 + float(height)
                pane = self._safe_item_rect(self.window_tag)
                if pane is not None:
                    px0, py0, px1, py1 = pane
                    vx0, vx1 = max(vx0, px0), min(vx1, px1)
                    vy0, vy1 = max(vy0, py0), min(vy1, py1)
                if vx1 > vx0 and vy1 > vy0:
                    return vx0, vy0, vx1, vy1
            except Exception:
                pass

        # Last-resort reconstruction from the list pane and header. This keeps
        # interaction alive on DPG builds that omit child-window rect state.
        pane = self._safe_item_rect(self.window_tag)
        header = self._safe_item_rect(self.header_canvas)
        if pane is None or header is None:
            return None
        px0, py0, px1, py1 = pane
        _, _, _, hy1 = header
        body_y0 = hy1
        pinned = self._safe_item_rect(self.pinned_canvas)
        try:
            pinned_shown = bool(dpg.is_item_shown(self.pinned_canvas))
        except Exception:
            pinned_shown = False
        if pinned_shown and pinned is not None:
            body_y0 = max(body_y0, float(pinned[3]))
        return px0, body_y0, px1, py1


    def _mouse_over_body_scrollbar(self, mx=None, my=None, viewport=None):
        """Return True when the pointer is over the child-window scrollbars.

        Dear PyGui reports the child-window rectangle including its scrollbar
        strips. Those strips must not participate in row hit-testing.
        """
        if viewport is None:
            viewport = self._body_viewport_rect()
        if viewport is None:
            return False

        if mx is None or my is None:
            try:
                mx, my = map(float, dpg.get_mouse_pos(local=False))
            except Exception:
                return False

        vx0, vy0, vx1, vy1 = viewport
        size = float(self.SCROLLBAR_HIT_SIZE)

        try:
            has_vertical = float(dpg.get_y_scroll_max(self.body_window)) > 0.0
        except Exception:
            has_vertical = False
        try:
            has_horizontal = float(dpg.get_x_scroll_max(self.body_window)) > 0.0
        except Exception:
            has_horizontal = False

        over_vertical = has_vertical and (vx1 - size <= mx <= vx1) and (vy0 <= my <= vy1)
        over_horizontal = has_horizontal and (vy1 - size <= my <= vy1) and (vx0 <= mx <= vx1)
        return over_vertical or over_horizontal


    def _body_local_pos(self):
        """Map the viewport mouse position into the scrollable body coordinates."""
        try:
            mx, my = dpg.get_mouse_pos(local=False)
            mx, my = float(mx), float(my)
        except Exception:
            return None

        viewport = self._body_viewport_rect()
        if viewport is None:
            return None
        vx0, vy0, vx1, vy1 = viewport
        if not (vx0 <= mx <= vx1 and vy0 <= my <= vy1):
            return None
        if self._mouse_over_body_scrollbar(mx, my, viewport):
            return None

        # Child-window origin + scroll is more consistent than drawlist rects
        # across Dear PyGui 1.x releases.
        try:
            scroll_x = float(dpg.get_x_scroll(self.body_window))
        except Exception:
            scroll_x = 0.0
        try:
            scroll_y = float(dpg.get_y_scroll(self.body_window))
        except Exception:
            scroll_y = 0.0

        return mx - vx0 + scroll_x, my - vy0 + scroll_y


    def _mouse_in_body(self):
        return self._body_local_pos() is not None

