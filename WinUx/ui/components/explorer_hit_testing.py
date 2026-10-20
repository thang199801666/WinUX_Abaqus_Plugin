"""Geometry-only hit testing for :class:`ExplorerListView`."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from DearUIQt.gui import QCursor
from DearUIQt.widgets import QRetainedItem

from ...platform.windows_icons import ICON_SIZE


class ExplorerHitTestingMixin:
    def _header_mouse_position(self):
        """Return (inside_header, local_x) without relying on drawlist hover state."""
        header_item = QRetainedItem(self.header_canvas)
        if not header_item.exists():
            return False, 0.0
        try:
            pointer = QCursor.pos()
            mx, my = float(pointer.x()), float(pointer.y())
            rect = self._safe_item_rect(self.header_canvas)
            if rect is None:
                return False, 0.0
            x0, y0, x1, y1 = rect
            # get_item_rect_max can report the full unclipped drawlist width. For
            # hit testing, limit the active width to the visible pane as well.
            pane_w = max(1.0, float(QRetainedItem(self.window_tag).globalGeometry().width()))
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
        pinned_item = QRetainedItem(self.pinned_canvas)
        if not pinned_item.exists() or not pinned_item.isVisible():
            return False

        # Mouse callbacks are registered globally for every ListView.  Never
        # trust only a cached rectangle here: after resize/navigation DPG can
        # briefly return the previous rectangle for another pane, causing both
        # Local and Server pinned rows to react to one click.  The hovered state
        # identifies the actual owner of the pointer.
        try:
            if pinned_item.underMouse():
                return True
            if not QRetainedItem(self.window_tag).underMouse():
                return False
        except Exception:
            pass

        rect = self._safe_item_rect(self.pinned_canvas)
        if not rect:
            return False
        try:
            pointer = QCursor.pos()
            mx, my = float(pointer.x()), float(pointer.y())
        except Exception:
            return False
        x0, y0, x1, y1 = rect
        return x0 <= mx <= x1 and y0 <= my <= y1


    def _body_point_is_on_item_drag_handle(self, index, body_pos):
        """Return True only over the native-like item drag surface.

        Explorer Details view keeps full-row click selection, but file dragging
        is acquired from the icon/label surface.  The rest of the visible row
        background remains available as a rubber-band origin.  This prevents
        full-row selection from making rubber-band selection practically
        unreachable in a densely populated folder.
        """
        if body_pos is None or not (0 <= int(index) < len(self.items)):
            return False

        x, y = map(float, body_pos)
        row_height = max(1.0, float(self.ROW_HEIGHT))
        row_offset = y % row_height
        gap = max(0.0, float(getattr(self, "ROW_SPACING", 0.0)) * 0.5)
        if gap and (row_offset < gap or row_offset >= row_height - gap):
            return False

        geometry = self._column_geometry().get("name")
        if geometry is None:
            return False
        column_x, column_width = map(float, geometry)
        if x < column_x or x >= column_x + column_width:
            return False

        # Icon hit area. Keep a small horizontal tolerance so dragging the icon
        # feels natural even with DPI rounding.
        icon_left = column_x + 3.0
        icon_right = icon_left + float(ICON_SIZE) + 3.0
        if icon_left <= x <= icon_right:
            return True

        # Filename label hit area. Reuse the existing measured-label helper so
        # truncated/short names do not turn the whole Name column into a drag
        # surface.
        try:
            return bool(self._body_point_is_on_name(index, body_pos))
        except Exception:
            return False


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
        """Return an item's screen-space rectangle during retained layout.

        DearUIQt owns the renderer-version fallbacks in ``QRetainedItem``.  The
        explicit native-state path remains useful for draw primitives whose
        ``rect_min``/``rect_size`` are more precise than configured geometry.
        """
        if not tag:
            return None
        item = QRetainedItem(tag)
        if not item.exists():
            return None
        state = item.nativeState()
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
                return (float(rect_min[0]), float(rect_min[1]),
                        float(rect_max[0]), float(rect_max[1]))
            except (TypeError, ValueError, IndexError):
                pass
        try:
            geometry = item.globalGeometry()
            if geometry.isValid():
                return (float(geometry.x()), float(geometry.y()),
                        float(geometry.x() + geometry.width()),
                        float(geometry.y() + geometry.height()))
        except Exception:
            pass
        return None


    def _mouse_in_item(self, tag):
        rect = self._safe_item_rect(tag)
        if rect is None:
            return False
        pointer = QCursor.pos()
        mx, my = float(pointer.x()), float(pointer.y())
        x0, y0, x1, y1 = rect
        return x0 <= mx <= x1 and y0 <= my <= y1


    def _body_viewport_rect(self):
        """Return the visible body viewport in screen coordinates."""
        overlay = getattr(self, "_scroller_arrow_overlay", None)
        geometry_item = overlay.container if overlay is not None else self.body_window
        geometry = QRetainedItem(geometry_item)
        rect = None
        if geometry.exists():
            try:
                clipped = geometry.globalGeometry(clipped=True)
                if clipped.isValid():
                    rect = (float(clipped.x()), float(clipped.y()),
                            float(clipped.x() + clipped.width()),
                            float(clipped.y() + clipped.height()))
            except Exception:
                rect = None
        if rect is not None:
            pane = self._safe_item_rect(self.window_tag)
            if pane is not None:
                rect = (max(rect[0], pane[0]), max(rect[1], pane[1]),
                        min(rect[2], pane[2]), min(rect[3], pane[3]))
            return rect if rect[2] > rect[0] and rect[3] > rect[1] else None

        # Drawlist geometry + child scroll is a reliable retained fallback on
        # renderer versions that do not expose child-window ``rect_min``.
        canvas = QRetainedItem(self.body_canvas)
        body = QRetainedItem(self.body_window)
        canvas_state = canvas.nativeState() if canvas.exists() else {}
        canvas_rect_min = canvas_state.get("rect_min")
        if canvas_rect_min is None and canvas.exists():
            try:
                pos = canvas.globalPos()
                canvas_rect_min = (pos.x(), pos.y())
            except Exception:
                canvas_rect_min = None
        if canvas_rect_min is not None and body.exists():
            try:
                scroll_x = body.horizontalScrollValue()
                scroll_y = body.verticalScrollValue()
                size = body.globalGeometry().size()
                vx0 = float(canvas_rect_min[0]) + scroll_x
                vy0 = float(canvas_rect_min[1]) + scroll_y
                vx1 = vx0 + float(size.width())
                vy1 = vy0 + float(size.height())
                pane = self._safe_item_rect(self.window_tag)
                if pane is not None:
                    px0, py0, px1, py1 = pane
                    vx0, vx1 = max(vx0, px0), min(vx1, px1)
                    vy0, vy1 = max(vy0, py0), min(vy1, py1)
                if vx1 > vx0 and vy1 > vy0:
                    return vx0, vy0, vx1, vy1
            except Exception:
                pass

        pane = self._safe_item_rect(self.window_tag)
        header = self._safe_item_rect(self.header_canvas)
        if pane is None or header is None:
            return None
        px0, py0, px1, py1 = pane
        _, _, _, hy1 = header
        body_y0 = hy1
        pinned = self._safe_item_rect(self.pinned_canvas)
        pinned_item = QRetainedItem(self.pinned_canvas)
        if pinned_item.exists() and pinned_item.isVisible() and pinned is not None:
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
                pointer = QCursor.pos()
                mx, my = float(pointer.x()), float(pointer.y())
            except Exception:
                return False

        vx0, vy0, vx1, vy1 = viewport
        size = float(self.SCROLLBAR_HIT_SIZE)

        try:
            has_vertical = QRetainedItem(self.body_window).verticalScrollMaximum() > 0.0
        except Exception:
            has_vertical = False
        try:
            has_horizontal = QRetainedItem(self.body_window).horizontalScrollMaximum() > 0.0
        except Exception:
            has_horizontal = False

        over_vertical = has_vertical and (vx1 - size <= mx <= vx1) and (vy0 <= my <= vy1)
        over_horizontal = has_horizontal and (vy1 - size <= my <= vy1) and (vx0 <= mx <= vx1)
        return over_vertical or over_horizontal


    def _body_local_pos(self):
        """Map the viewport mouse position into the scrollable body coordinates."""
        try:
            pointer = QCursor.pos()
            mx, my = float(pointer.x()), float(pointer.y())
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
            scroll_x = QRetainedItem(self.body_window).horizontalScrollValue()
        except Exception:
            scroll_x = 0.0
        try:
            scroll_y = QRetainedItem(self.body_window).verticalScrollValue()
        except Exception:
            scroll_y = 0.0

        return mx - vx0 + scroll_x, my - vy0 + scroll_y


    def _mouse_in_body(self):
        return self._body_local_pos() is not None

