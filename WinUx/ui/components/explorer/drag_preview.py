"""Lifecycle of the Explorer drag-preview paint surface."""
from __future__ import annotations

from DearUIQt.gui import QCursor, QFontMetrics
from DearUIQt.gui.palette import QtFusionPalette
from DearUIQt.widgets import QRetainedItem, QViewportCanvas, QPaintGroup


class DragPreviewHelper:
    """Render an Explorer-like drag ghost above the viewport.

    The helper owns a :class:`QViewportCanvas` and retained primitives, so the
    Explorer feature never reaches into renderer draw-list or cursor APIs.
    """

    MAX_VISIBLE_ITEMS = 3
    OFFSET_X = 9.0
    OFFSET_Y = 11.0

    def __init__(self, uid, body_font=None, runtime=None):
        self.uid = uid
        self.body_font = body_font
        self.active = False
        self.can_copy = False
        self.items = []
        self._canvas = None
        self._drawlist = None  # legacy native-id alias
        self._parts = {}
        self._group = None
        self._adapters = {}
        self._content_signature = None
        self._feedback_signature = None
        self.theme_config = {}
        self._metrics = QFontMetrics(body_font)
        self._runtime = runtime
        self._render_token = None
        self._primary_viewport = False
        self._content_size = (0.0, 0.0)

    def _ensure_built(self):
        if self._canvas is not None and self._canvas.exists():
            return True
        self._parts = {}
        self._adapters = {}
        self._content_signature = None
        self._feedback_signature = None
        if self._canvas is not None:
            try:
                self._canvas.delete()
            except Exception:
                pass
        try:
            self._canvas = QViewportCanvas(
                front=True, tag=f"{self.uid}_drag_preview_layer",
                primary_viewport=self._primary_viewport)
        except Exception:
            self._canvas = None
            self._drawlist = None
            return False
        self._drawlist = self._canvas.tag
        self._group = QPaintGroup(parent=self._canvas, show=False)
        painter = self._group.painter()
        self._parts["shadow"] = painter.drawRect(
            (0, 0), (1, 1), fill=(0, 0, 0, 45), color=(0, 0, 0, 0),
            rounding=4, show=False)
        self._parts["panel"] = painter.drawRect(
            (0, 0), (1, 1), fill=QtFusionPalette.MENU[:3] + (238,),
            color=QtFusionPalette.BORDER[:3] + (230,), thickness=1, rounding=4, show=False)
        self._parts["accent"] = painter.drawRect(
            (0, 0), (1, 1), fill=QtFusionPalette.HIGHLIGHT,
            color=QtFusionPalette.HIGHLIGHT, rounding=2, show=False)
        self._parts["texts"] = []
        for _ in range(self.MAX_VISIBLE_ITEMS + 1):
            text = painter.drawText(
                (0, 0), "", color=QtFusionPalette.TEXT, size=15,
                font=self.body_font, show=False)
            self._parts["texts"].append(text)
        self.set_theme(self.theme_config)
        return True

    def _measure(self, text):
        size = self._metrics.size(text)
        return float(size.width()), float(size.height())

    def _item(self, tag):
        if not tag:
            return None
        item = self._adapters.get(tag)
        if item is None:
            item = QRetainedItem(tag).setImmediateUpdates(True)
            self._adapters[tag] = item
        return item

    def set_theme(self, config):
        self.theme_config = dict(config or {})
        if not self._parts:
            return
        mapping = {
            "panel": {
                "fill": self.theme_config.get("drag_bg", QtFusionPalette.MENU[:3] + (238,)),
                "color": self.theme_config.get("drag_border", QtFusionPalette.BORDER[:3] + (230,)),
            },
            "accent": {
                "fill": self.theme_config.get("drag_accent", QtFusionPalette.HIGHLIGHT),
                "color": self.theme_config.get("drag_accent", QtFusionPalette.HIGHLIGHT),
            },
        }
        for key, values in mapping.items():
            item = self._item(self._parts.get(key))
            if item is not None and item.exists():
                item.configure(**values)
        for tag in self._parts.get("texts", []):
            item = self._item(tag)
            if item is not None and item.exists():
                item.configure(color=self.theme_config.get("drag_text", QtFusionPalette.TEXT))

    def set_primary_viewport(self, primary=True):
        self._primary_viewport = bool(primary)
        if self._canvas is not None and self._canvas.exists():
            self._canvas.setPrimaryViewport(self._primary_viewport)

    def begin(self, items):
        self.items = list(items)
        self.active = bool(self.items)
        self.can_copy = False
        self._feedback_signature = None
        if self.active and self._ensure_built():
            if self._runtime is not None and self._render_token is None:
                self._render_token = self._runtime.addBeforeRenderCallback(self.moveToCursor, late=True)
            self.update(False)

    def update(self, can_copy, target_name=None):
        if not self.active or not self._ensure_built():
            return
        self.can_copy = bool(can_copy)
        target_name = str(target_name or "").strip()
        feedback = (self.can_copy, target_name)
        if feedback == self._feedback_signature:
            if self._runtime is None:
                self.moveToCursor()
            return
        self._feedback_signature = feedback

        if self.can_copy and target_name:
            if len(self.items) == 1:
                source_name = str(self.items[0].name or "")
                names = [f'Copy "{source_name}"', f'To: "{target_name}"']
            else:
                names = [f"Copy {len(self.items)} items", f'To: "{target_name}"']
        else:
            names = [str(item.name or "") for item in self.items[:self.MAX_VISIBLE_ITEMS]]
            hidden_count = len(self.items) - self.MAX_VISIBLE_ITEMS
            if hidden_count > 0:
                names.append(f"+{hidden_count} more item(s)")
        if not names:
            names = [""]

        display_names = [name[:39] + "..." if len(name) > 42 else name for name in names]
        signature = tuple(display_names)
        if signature != self._content_signature:
            self._layout_content(display_names)
            self._content_signature = signature
        self.moveToCursor()
        self._group.configure(show=True)

    def _paint_bounds(self):
        """Return live primary-client bounds in this viewport canvas' paint space."""
        runtime = getattr(self, "_runtime", None)
        backend = getattr(runtime, "backend", None)
        if backend is None:
            return None
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

    def moveToCursor(self, pointer=None):
        """Keep the preview close to the live pointer in paint coordinates.

        QViewportCanvas is a viewport *paint* layer.  On native Windows
        multi-viewport builds that coordinate space is desktop/screen space,
        even when the layer is associated with the primary viewport.  Feeding
        it client coordinates therefore offsets the ghost by the window's
        desktop origin.  Always sample QCursor.paintPos() for this surface.

        Near an edge, flip the panel to the opposite side of the cursor instead
        of hard-clamping it far away.  This keeps the visual association with
        the pointer for every window size.
        """
        if not self.active or self._group is None:
            return
        if pointer is None:
            pointer = QCursor.paintPos()
        mx, my = map(float, pointer)
        content_w, content_h = getattr(self, "_content_size", (0.0, 0.0))
        gap_x = float(self.OFFSET_X)
        gap_y = float(self.OFFSET_Y)
        tx = mx + gap_x
        ty = my + gap_y

        bounds = self._paint_bounds()
        if bounds is not None and content_w > 0.0 and content_h > 0.0:
            left, top, right, bottom = bounds
            margin = 4.0
            if tx + content_w + margin > right:
                tx = mx - content_w - gap_x
            if ty + content_h + margin > bottom:
                ty = my - content_h - gap_y
            # Extremely small windows can fit neither side.  Clamp only as a
            # final safety net; ordinary edge cases remain adjacent to cursor.
            tx = min(max(left + margin, tx), max(left + margin, right - content_w - margin))
            ty = min(max(top + margin, ty), max(top + margin, bottom - content_h - margin))

        self._group.setTranslation(tx, ty)

    def _layout_content(self, display_names):
        max_text_width = max((self._measure(name)[0] for name in display_names), default=80.0)
        width = min(330.0, max(150.0, max_text_width + 42.0))
        height = 14.0 + max(1, len(display_names)) * 21.0
        self._content_size = (width + 3.0, height + 3.0)

        self._item(self._parts["shadow"]).configure(
            pmin=(3.0, 3.0), pmax=(width + 3.0, height + 3.0), show=True)
        self._item(self._parts["panel"]).configure(
            pmin=(0, 0), pmax=(width, height), show=True)
        self._item(self._parts["accent"]).configure(
            pmin=(7.0, 8.0), pmax=(11.0, height - 8.0), show=True)

        for index, tag in enumerate(self._parts.get("texts", [])):
            item = self._item(tag)
            if index < len(display_names):
                item.configure(
                    pos=(18.0, 7.0 + index * 21.0),
                    text=display_names[index], show=True)
            else:
                item.configure(show=False)

    def end(self):
        self.active = False
        self.can_copy = False
        self.items = []
        if self._runtime is not None and self._render_token is not None:
            self._runtime.removeBeforeRenderCallback(self._render_token)
            self._render_token = None
        if self._group is not None and self._group.exists():
            self._group.configure(show=False)

    def destroy(self):
        self.end()
        canvas, self._canvas = self._canvas, None
        self._drawlist = None
        self._group = None
        self._adapters.clear()
        if canvas is not None:
            try:
                canvas.delete()
            except Exception:
                pass
