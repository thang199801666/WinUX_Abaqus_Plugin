"""Lifecycle of the Explorer drag-preview paint surface."""
from __future__ import annotations

from DearUIQt.gui import QCursor, QFontMetrics
from DearUIQt.widgets import QRetainedItem, QViewportCanvas


class DragPreviewHelper:
    """Render an Explorer-like drag ghost above the viewport.

    The helper owns a :class:`QViewportCanvas` and retained primitives, so the
    Explorer feature never reaches into renderer draw-list or cursor APIs.
    """

    MAX_VISIBLE_ITEMS = 3
    OFFSET_X = 9.0
    OFFSET_Y = 11.0

    def __init__(self, uid, body_font=None):
        self.uid = uid
        self.body_font = body_font
        self.active = False
        self.can_copy = False
        self.items = []
        self._canvas = None
        self._drawlist = None  # legacy native-id alias
        self._parts = {}
        self.theme_config = {}
        self._metrics = QFontMetrics(body_font)

    def _ensure_built(self):
        if self._canvas is not None and self._canvas.exists():
            return True
        self._parts = {}
        if self._canvas is not None:
            try:
                self._canvas.delete()
            except Exception:
                pass
        try:
            self._canvas = QViewportCanvas(
                front=True, tag=f"{self.uid}_drag_preview_layer")
        except Exception:
            self._canvas = None
            self._drawlist = None
            return False
        self._drawlist = self._canvas.tag
        painter = self._canvas.painter()
        self._parts["shadow"] = painter.drawRect(
            (0, 0), (1, 1), fill=(0, 0, 0, 45), color=(0, 0, 0, 0),
            rounding=4, show=False)
        self._parts["panel"] = painter.drawRect(
            (0, 0), (1, 1), fill=(255, 255, 255, 238),
            color=(170, 170, 170, 230), thickness=1, rounding=4, show=False)
        self._parts["accent"] = painter.drawRect(
            (0, 0), (1, 1), fill=(0, 120, 215, 255),
            color=(0, 120, 215, 255), rounding=2, show=False)
        self._parts["texts"] = []
        for _ in range(self.MAX_VISIBLE_ITEMS + 1):
            text = painter.drawText(
                (0, 0), "", color=(25, 25, 25, 255), size=15,
                font=self.body_font, show=False)
            self._parts["texts"].append(text)
        self.set_theme(self.theme_config)
        return True

    def _measure(self, text):
        size = self._metrics.size(text)
        return float(size.width()), float(size.height())

    @staticmethod
    def _item(tag):
        return QRetainedItem(tag) if tag else None

    def set_theme(self, config):
        self.theme_config = dict(config or {})
        if not self._parts:
            return
        mapping = {
            "panel": {
                "fill": self.theme_config.get("drag_bg", (255, 255, 255, 238)),
                "color": self.theme_config.get("drag_border", (170, 170, 170, 230)),
            },
            "accent": {
                "fill": self.theme_config.get("drag_accent", (0, 120, 215, 255)),
                "color": self.theme_config.get("drag_accent", (0, 120, 215, 255)),
            },
        }
        for key, values in mapping.items():
            item = self._item(self._parts.get(key))
            if item is not None and item.exists():
                item.configure(**values)
        for tag in self._parts.get("texts", []):
            item = self._item(tag)
            if item is not None and item.exists():
                item.configure(color=self.theme_config.get("drag_text", (25, 25, 25, 255)))

    def begin(self, items):
        self.items = list(items)
        self.active = bool(self.items)
        self.can_copy = False
        if self.active and self._ensure_built():
            self.update(False)

    def update(self, can_copy, target_name=None):
        if not self.active or not self._ensure_built():
            return
        self.can_copy = bool(can_copy)
        pointer = QCursor.pos()
        mx, my = float(pointer.x()), float(pointer.y())
        target_name = str(target_name or "").strip()

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
        max_text_width = max((self._measure(name)[0] for name in display_names), default=80.0)
        width = min(330.0, max(150.0, max_text_width + 42.0))
        height = 14.0 + max(1, len(display_names)) * 21.0
        x, y = mx + self.OFFSET_X, my + self.OFFSET_Y

        self._item(self._parts["shadow"]).configure(
            pmin=(x + 3.0, y + 3.0), pmax=(x + width + 3.0, y + height + 3.0), show=True)
        self._item(self._parts["panel"]).configure(
            pmin=(x, y), pmax=(x + width, y + height), show=True)
        self._item(self._parts["accent"]).configure(
            pmin=(x + 7.0, y + 8.0), pmax=(x + 11.0, y + height - 8.0), show=True)

        for index, tag in enumerate(self._parts.get("texts", [])):
            item = self._item(tag)
            if index < len(display_names):
                item.configure(
                    pos=(x + 18.0, y + 7.0 + index * 21.0),
                    text=display_names[index], show=True)
            else:
                item.hide()

    def end(self):
        self.active = False
        self.can_copy = False
        self.items = []
        for key in ("shadow", "panel", "accent"):
            item = self._item(self._parts.get(key))
            if item is not None and item.exists():
                item.hide()
        for tag in self._parts.get("texts", []):
            item = self._item(tag)
            if item is not None and item.exists():
                item.hide()

    def destroy(self):
        self.end()
        canvas, self._canvas = self._canvas, None
        self._drawlist = None
        if canvas is not None:
            try:
                canvas.delete()
            except Exception:
                pass
