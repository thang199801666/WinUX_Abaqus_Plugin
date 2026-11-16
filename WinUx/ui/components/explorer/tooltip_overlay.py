"""Non-interactive viewport tooltip surface for Explorer draw-list rows.

Dear PyGui tooltips are native children of their hover target.  ``mvDrawlist``
accepts draw primitives only, so attaching ``mvTooltip`` directly to a QCanvas
is invalid and can also unbalance Dear PyGui's container stack when construction
fails.  Explorer rows are painted into a draw list, therefore their tooltip is
painted into a front viewport layer instead of using ``mvTooltip``.
"""
from __future__ import annotations

from DearUIQt.core import Qt
from DearUIQt.gui import QCursor, QFontMetrics, QtFusionPalette
from DearUIQt.widgets import QPaintGroup, QRetainedItem, QViewportCanvas


class ExplorerTooltipOverlay:
    """Small, input-transparent paint overlay positioned beside the cursor."""

    MAX_CONTENT_WIDTH = 420.0
    MIN_CONTENT_WIDTH = 150.0
    OFFSET_X = 14.0
    OFFSET_Y = 18.0
    MAX_BODY_LINES = 9

    def __init__(self, uid, *, body_font=None, header_font=None,
                 primary_viewport=False):
        self.uid = str(uid)
        self.body_font = body_font
        self.header_font = header_font or body_font
        self._body_metrics = QFontMetrics(body_font)
        self._header_metrics = QFontMetrics(self.header_font)
        self._primary_viewport = bool(primary_viewport)
        self._canvas = None
        self._group = None
        self._destroyed = False
        self._parts = {}
        self._adapters = {}
        self._visible = False
        self._content_size = (0.0, 0.0)
        self._content = ("", "", "")

    def exists(self):
        """Logical existence; the native surface is created lazily on first show."""
        return not self._destroyed

    def _item(self, tag):
        if not tag:
            return None
        item = self._adapters.get(tag)
        if item is None:
            item = QRetainedItem(tag).setImmediateUpdates(True)
            self._adapters[tag] = item
        return item

    def _ensure_built(self):
        if self._destroyed:
            return False
        if self._canvas is not None and self._canvas.exists():
            return True
        self._parts = {}
        self._adapters = {}
        try:
            self._canvas = QViewportCanvas(
                front=True,
                tag=f"{self.uid}_viewport_tooltip",
                primary_viewport=self._primary_viewport,
            )
            self._group = QPaintGroup(parent=self._canvas, show=False)
            painter = self._group.painter()
            self._parts["shadow"] = painter.drawRect(
                (0, 0), (1, 1), fill=(0, 0, 0, 40), color=(0, 0, 0, 0),
                rounding=4, show=False)
            self._parts["panel"] = painter.drawRect(
                (0, 0), (1, 1), fill=QtFusionPalette.TOOLTIP_BG,
                color=QtFusionPalette.TOOLTIP_BORDER, thickness=1,
                rounding=4, show=False)
            self._parts["separator"] = painter.drawLine(
                (0, 0), (1, 0), color=QtFusionPalette.BORDER_LIGHT,
                thickness=1, show=False)
            self._parts["title"] = []
            for _ in range(2):
                self._parts["title"].append(painter.drawText(
                    (0, 0), "", color=QtFusionPalette.TEXT, size=14,
                    font=self.header_font, show=False))
            self._parts["body"] = []
            for _ in range(self.MAX_BODY_LINES):
                self._parts["body"].append(painter.drawText(
                    (0, 0), "", color=QtFusionPalette.TEXT_MUTED, size=13,
                    font=self.body_font, show=False))
            return True
        except Exception:
            canvas, self._canvas = self._canvas, None
            self._group = None
            if canvas is not None:
                try:
                    canvas.delete()
                except Exception:
                    pass
            return False

    @staticmethod
    def _split_paragraph(paragraph, metrics, width):
        paragraph = str(paragraph or "")
        if not paragraph:
            return [""]
        if metrics.horizontalAdvance(paragraph) <= width:
            return [paragraph]
        words = paragraph.split(" ")
        if len(words) > 1:
            lines, current = [], ""
            for word in words:
                candidate = word if not current else current + " " + word
                if current and metrics.horizontalAdvance(candidate) > width:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
            # Long tokens (paths/URLs) still need hard wrapping.
            result = []
            for line in lines:
                result.extend(ExplorerTooltipOverlay._split_paragraph(line, metrics, width)
                              if metrics.horizontalAdvance(line) > width and " " not in line
                              else [line])
            return result

        # One long token: measurement-driven hard wrap.
        result = []
        remaining = paragraph
        while remaining:
            if metrics.horizontalAdvance(remaining) <= width:
                result.append(remaining)
                break
            lo, hi = 1, len(remaining)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if metrics.horizontalAdvance(remaining[:mid]) <= width:
                    lo = mid
                else:
                    hi = mid - 1
            count = max(1, lo)
            result.append(remaining[:count])
            remaining = remaining[count:]
        return result

    @classmethod
    def _wrap(cls, text, metrics, width, max_lines):
        lines = []
        for paragraph in str(text or "").splitlines() or [""]:
            lines.extend(cls._split_paragraph(paragraph, metrics, width))
            if len(lines) >= max_lines:
                break
        lines = lines[:max_lines]
        return lines

    def _desired_content_width(self, title, details, path):
        widths = [self.MIN_CONTENT_WIDTH]
        for paragraph in str(title or "").splitlines():
            widths.append(float(self._header_metrics.horizontalAdvance(paragraph)))
        for block in (details, path):
            for paragraph in str(block or "").splitlines():
                widths.append(float(self._body_metrics.horizontalAdvance(paragraph)))
        return min(self.MAX_CONTENT_WIDTH, max(widths))

    def setContent(self, title, details="", path=""):
        self._content = (str(title or ""), str(details or ""), str(path or ""))
        if not self._ensure_built():
            return False
        title, details, path = self._content
        inner_w = self._desired_content_width(title, details, path)
        title_lines = self._wrap(title, self._header_metrics, inner_w, 2)
        body_rows = []
        if details:
            body_rows.extend((line, QtFusionPalette.TEXT_MUTED)
                             for line in self._wrap(details, self._body_metrics, inner_w, 5))
        if path:
            body_rows.extend((line, QtFusionPalette.HIGHLIGHT)
                             for line in self._wrap(path, self._body_metrics, inner_w, 4))
        body_rows = body_rows[:self.MAX_BODY_LINES]

        pad_x, pad_y = 8.0, 6.0
        title_h = max(14.0, float(self._header_metrics.lineSpacing()))
        body_h = max(14.0, float(self._body_metrics.lineSpacing()))
        y = pad_y
        for index, tag in enumerate(self._parts["title"]):
            item = self._item(tag)
            if index < len(title_lines):
                item.configure(pos=(pad_x, y), text=title_lines[index],
                               color=QtFusionPalette.TEXT, show=True)
                y += title_h
            else:
                item.configure(show=False)

        has_body = bool(body_rows)
        separator = self._item(self._parts["separator"])
        if has_body:
            y += 3.0
            separator.configure(p1=(pad_x, y), p2=(pad_x + inner_w, y), show=True)
            y += 5.0
        else:
            separator.configure(show=False)

        for index, tag in enumerate(self._parts["body"]):
            item = self._item(tag)
            if index < len(body_rows):
                line, color = body_rows[index]
                item.configure(pos=(pad_x, y), text=line, color=color, show=True)
                y += body_h
            else:
                item.configure(show=False)

        width = inner_w + pad_x * 2.0
        height = max(24.0, y + pad_y)
        self._content_size = (width + 3.0, height + 3.0)
        self._item(self._parts["shadow"]).configure(
            pmin=(3.0, 3.0), pmax=(width + 3.0, height + 3.0), show=True)
        self._item(self._parts["panel"]).configure(
            pmin=(0.0, 0.0), pmax=(width, height), show=True)
        return True

    def _paint_bounds(self):
        if self._canvas is None:
            return None
        backend = self._canvas.backend
        try:
            from DearUIQt.backends.native_windows import NativeWindowBackend
            rect = NativeWindowBackend(backend).primaryClientPaintRect()
            if rect is not None:
                return tuple(map(float, rect))
        except Exception:
            pass
        try:
            width = float(backend.get_viewport_client_width())
            height = float(backend.get_viewport_client_height())
            if width > 0.0 and height > 0.0:
                return (0.0, 0.0, width, height)
        except Exception:
            pass
        return None

    def _move_to_cursor(self):
        if self._group is None:
            return
        point = QCursor.paintPos(backend=self._canvas.backend if self._canvas else None)
        mx, my = float(point.x()), float(point.y())
        width, height = self._content_size
        tx, ty = mx + self.OFFSET_X, my + self.OFFSET_Y
        bounds = self._paint_bounds()
        if bounds is not None:
            left, top, right, bottom = bounds
            margin = 4.0
            if tx + width + margin > right:
                tx = mx - width - self.OFFSET_X
            if ty + height + margin > bottom:
                ty = my - height - self.OFFSET_Y
            tx = min(max(left + margin, tx), max(left + margin, right - width - margin))
            ty = min(max(top + margin, ty), max(top + margin, bottom - height - margin))
        self._group.setTranslation(tx, ty)

    def show(self):
        if not self._ensure_built() or self._group is None:
            return False
        self._move_to_cursor()
        self._group.configure(show=True)
        self._visible = True
        return True

    def hide(self):
        if self._group is not None and self._group.exists():
            self._group.configure(show=False)
        self._visible = False
        return True

    def isVisible(self):
        return bool(self._visible)

    def setPrimaryViewport(self, primary=True):
        self._primary_viewport = bool(primary)
        if self._canvas is not None and self._canvas.exists():
            self._canvas.setPrimaryViewport(self._primary_viewport)
        return self

    def destroy(self):
        self._visible = False
        self._destroyed = True
        canvas, self._canvas = self._canvas, None
        self._group = None
        self._parts = {}
        self._adapters.clear()
        if canvas is not None:
            try:
                canvas.delete()
            except Exception:
                pass


__all__ = ["ExplorerTooltipOverlay"]
