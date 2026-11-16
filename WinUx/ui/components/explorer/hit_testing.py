"""Geometry-only hit testing for :class:`ExplorerListView`."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from DearUIQt.gui import QCursor
from DearUIQt.gui.placement import item_screen_rect
from DearUIQt.widgets import QRetainedItem

from ....platform.windows_icons import ICON_SIZE


class ExplorerHitTestingMixin:
    def _physical_pointer_position(self):
        """Return the *real* desktop cursor position for this input turn.

        Selection must never be inferred from viewport size, configured widget
        bounds, or renderer mouse coordinates.  On Windows QCursor.screenPos()
        is backed by USER32 GetCursorPos, so this is the physical pointer the
        user actually clicked.  QApplication delivery snapshots it once for the
        whole callback to prevent a queued renderer callback from retargeting a
        later cursor position.
        """
        sentinel = object()
        snapshot = getattr(self, "_qt_screen_position", sentinel)
        if snapshot is not sentinel and snapshot is not None:
            try:
                return float(snapshot[0]), float(snapshot[1])
            except Exception:
                pass
        try:
            point = QCursor.screenPos()
            return float(point.x()), float(point.y())
        except Exception:
            return None

    def _screen_item_rect(self, tag):
        """Return the rendered item rectangle in physical desktop coordinates."""
        if not tag:
            return None
        try:
            item = QRetainedItem(tag)
            if not item.exists():
                return None
            rect = item_screen_rect(item.backend, tag)
            if rect is None:
                return None
            x0, y0, x1, y1 = map(float, rect)
            if x1 <= x0 or y1 <= y0:
                return None
            return x0, y0, x1, y1
        except Exception:
            return None

    def _body_screen_viewport_rect(self):
        """Actual on-screen body viewport; independent of app/max-size math."""
        rect = self._screen_item_rect(getattr(self, "body_window", None))
        pane = self._screen_item_rect(getattr(self, "window_tag", None))
        if rect is None:
            return None
        if pane is not None:
            rect = (max(rect[0], pane[0]), max(rect[1], pane[1]),
                    min(rect[2], pane[2]), min(rect[3], pane[3]))
        return rect if rect[2] > rect[0] and rect[3] > rect[1] else None

    def _body_local_pos_from_screen(self, point=None):
        """Map a physical desktop cursor point directly into body canvas space."""
        if point is None:
            point = self._physical_pointer_position()
        if point is None:
            return None
        try:
            sx, sy = map(float, point)
        except Exception:
            return None
        viewport = self._body_screen_viewport_rect()
        if viewport is None:
            return None
        vx0, vy0, vx1, vy1 = viewport
        if not (vx0 <= sx < vx1 and vy0 <= sy < vy1):
            return None

        # Scrollbar strips are part of the child-window HWND/retained rectangle
        # but are not row content.
        size = float(self.SCROLLBAR_HIT_SIZE)
        body = QRetainedItem(self.body_window)
        try:
            has_vertical = body.verticalScrollMaximum() > 0.0
        except Exception:
            has_vertical = False
        try:
            has_horizontal = body.horizontalScrollMaximum() > 0.0
        except Exception:
            has_horizontal = False
        if has_vertical and sx >= vx1 - size:
            return None
        if has_horizontal and sy >= vy1 - size:
            return None

        # Use the *painted canvas* origin on the desktop. item_screen_rect()
        # already applies ancestor scrolling, so no viewport/max-size offset is
        # guessed here. This is the key selection transform.
        canvas = self._screen_item_rect(getattr(self, "body_canvas", None))
        if canvas is not None:
            return sx - canvas[0], sy - canvas[1]

        # Conservative fallback for unusual renderer builds that do not expose
        # drawlist screen geometry. It still starts from the physical cursor and
        # the actual body screen rectangle, never from application dimensions.
        try:
            scroll_x = body.horizontalScrollValue()
        except Exception:
            scroll_x = 0.0
        try:
            scroll_y = body.verticalScrollValue()
        except Exception:
            scroll_y = 0.0
        return sx - vx0 + scroll_x, sy - vy0 + scroll_y

    def row_at_screen_point(self, x, y):
        """Resolve an item row from a physical desktop cursor coordinate."""
        body_pos = self._body_local_pos_from_screen((x, y))
        if body_pos is None:
            return None
        local_x, local_y = body_pos
        if local_x < 0.0 or local_x >= self._row_content_width():
            return None
        index = int(local_y // max(1.0, float(self.ROW_HEIGHT)))
        return index if 0 <= index < len(self.items) else None

    def _pointer_position(self):
        """Return the pointer in the ListView's primary-client viewport space.

        File-list retained geometry (header/body/rows/pane rectangles) is
        primary-client geometry.  QCursor.pos() is deliberately avoided because
        Dear PyGui can expose it as either client or desktop coordinates on
        Windows native/multi-viewport builds.  During QApplication delivery we
        keep one viewport snapshot for the entire gesture callback so hit-tests
        cannot retarget between mouse-down and the row-selection logic.
        """
        sentinel = object()
        snapshot = getattr(self, "_qt_viewport_position", sentinel)
        if snapshot is not sentinel:
            if snapshot is not None:
                try:
                    return float(snapshot[0]), float(snapshot[1])
                except Exception:
                    pass
        else:
            # Compatibility for direct/legacy dispatch that supplies a Qt event
            # without going through _handle_qt_pointer_event().  The normal app
            # path always installs the authoritative viewport snapshot above.
            event = getattr(self, "_qt_pointer_event", None)
            if event is not None:
                try:
                    point = event.globalPosition()
                    return float(point.x()), float(point.y())
                except Exception:
                    pass
        try:
            point = QCursor.viewportPos()
            return float(point.x()), float(point.y())
        except Exception:
            return None

    def _header_mouse_position(self):
        """Return header hit/local x from the physical desktop cursor."""
        try:
            point = self._physical_pointer_position()
            if point is None:
                return False, 0.0
            mx, my = point
            rect = self._screen_item_rect(self.header_canvas)
            pane = self._screen_item_rect(self.window_tag)
            if rect is None:
                return False, 0.0
            x0, y0, x1, y1 = rect
            if pane is not None:
                x0, y0 = max(x0, pane[0]), max(y0, pane[1])
                x1, y1 = min(x1, pane[2]), min(y1, pane[3])
            total_w = sum(self._column_widths.get(c["key"], self.MIN_COLUMN_WIDTH)
                          for c in self._visible_columns())
            active_w = min(total_w, max(0.0, x1 - x0))
            active_h = min(float(self.HEADER_HEIGHT), max(0.0, y1 - y0))
            inside = x0 <= mx < x0 + active_w and y0 <= my < y0 + active_h
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
        screen_rect = getattr(self, "_screen_item_rect", None)
        physical = getattr(self, "_physical_pointer_position", None)
        if callable(screen_rect) and callable(physical):
            rect = screen_rect(self.pinned_canvas)
            point = physical()
            pane = screen_rect(self.window_tag)
        else:
            # Legacy/direct-mixin compatibility. QApplication's delivered press
            # remains preferable to a later renderer cursor snapshot.
            rect = self._safe_item_rect(self.pinned_canvas)
            event = getattr(self, "_qt_pointer_event", None)
            point = None
            if event is not None:
                try:
                    p = event.globalPosition()
                    point = (float(p.x()), float(p.y()))
                except Exception:
                    point = None
            if point is None:
                try:
                    p = QCursor.pos()
                    point = (float(p.x()), float(p.y()))
                except Exception:
                    point = None
            pane = self._safe_item_rect(self.window_tag)
        if rect is None or point is None:
            return False
        x0, y0, x1, y1 = rect
        if pane is not None:
            x0, y0 = max(x0, pane[0]), max(y0, pane[1])
            x1, y1 = min(x1, pane[2]), min(y1, pane[3])
        mx, my = point
        return x0 <= mx < x1 and y0 <= my < y1


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


    def row_at_viewport_point(self, x, y):
        """Return the row at an explicit primary-client viewport point.

        This is the canonical point->row transform used by drop resolution.
        It intentionally recomputes the live body viewport and scroll offset on
        every call so resize/splitter motion cannot leave a stale row origin.
        """
        body_pos = self._body_local_pos((x, y))
        if body_pos is None:
            return None
        index = int(float(body_pos[1]) // max(1.0, float(self.ROW_HEIGHT)))
        return index if 0 <= index < len(self.items) else None


    def _row_at_mouse(self):
        """Return the row under the *physical* mouse cursor.

        The authoritative path is desktop cursor -> rendered body canvas -> row.
        Renderer/client coordinates are retained only as a non-Windows/test
        fallback. This prevents window size, maximize state, splitter geometry,
        or a stale app-relative mouse position from selecting another item.
        """
        screen = self._physical_pointer_position()
        if screen is not None:
            row = self.row_at_screen_point(*screen)
            if row is not None:
                return row
            # If the real cursor is physically inside the body but not on a row
            # (blank/right-side area), that is authoritative: do not fall back
            # to a stale renderer point that could fabricate a different row.
            viewport = self._body_screen_viewport_rect()
            if viewport is not None:
                x0, y0, x1, y1 = viewport
                if x0 <= screen[0] < x1 and y0 <= screen[1] < y1:
                    return None

        point = self._pointer_position()
        if point is None:
            return None
        body_pos = self._body_local_pos(point)
        if body_pos is None:
            return None
        x, y = body_pos
        if x < 0.0 or x >= self._row_content_width():
            return None
        index = int(float(y) // max(1.0, float(self.ROW_HEIGHT)))
        return index if 0 <= index < len(self.items) else None


    def _safe_item_rect(self, tag):
        """Return an item's retained viewport rectangle during layout.

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
        point = self._pointer_position()
        if point is None:
            return False
        mx, my = point
        x0, y0, x1, y1 = rect
        return x0 <= mx <= x1 and y0 <= my <= y1


    def _body_viewport_rect(self):
        """Return the visible body viewport in primary-client coordinates."""
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
            point = self._pointer_position()
            if point is None:
                return False
            mx, my = point

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


    def _body_local_pos(self, point=None):
        """Map a primary-client viewport point into scrollable body coordinates."""
        if point is None:
            point = self._pointer_position()
        if point is None:
            return None
        try:
            if hasattr(point, "x"):
                mx, my = float(point.x()), float(point.y())
            else:
                mx, my = map(float, point)
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
        # Mouse ownership for selection is screen-space authoritative.
        point = self._physical_pointer_position()
        if point is not None and self._body_screen_viewport_rect() is not None:
            return self._body_local_pos_from_screen(point) is not None
        return self._body_local_pos() is not None
