"""Retained visual renderers used by :mod:`DearUIQt.ribbon`.

The renderer layer owns visual primitives that cannot be expressed accurately by
Dear PyGui themes alone.  It deliberately contains no application content.
"""
from __future__ import annotations


def _rgba(value):
    if value is None:
        return None
    values = tuple(int(channel) for channel in value)
    if len(values) == 3:
        values += (255,)
    if len(values) != 4:
        raise ValueError("Ribbon accent colors must be RGB or RGBA tuples.")
    return tuple(max(0, min(255, channel)) for channel in values)


class RibbonTabRenderer:
    """Render tab headers with retained primitives.

    Each tab owns stable input and decoration layers. Indicator/context/badge
    changes therefore reconfigure draw primitives without recreating the tab
    button or its callback.
    """

    INDICATOR_STYLES = ("underline", "top-line", "side-accent")

    def __init__(self, ribbon):
        self.ribbon = ribbon

    def __getattr__(self, name):
        return getattr(self.ribbon, name)

    def _badge_width(self, badge) -> int:
        text = "" if badge is None else str(badge)
        return 0 if not text else max(16, 8 + len(text) * 6)

    def width_for_label(self, label: str, badge=None) -> int:
        base = max(
            self.TAB_MIN_WIDTH,
            2 * self.TAB_PADDING_X + len(str(label)) * self.TAB_CHAR_WIDTH,
        )
        badge_width = self._badge_width(badge)
        return base + (badge_width + 4 if badge_width else 0)

    def create(self, key: str, label: str, *, accent=None, context_accent=None, badge=None,
               badge_color=None, badge_text_color=None):
        width = self.width_for_label(label, badge)
        host = self.backend.add_child_window(
            parent=self.tab_row,
            width=width,
            height=self.TAB_HEIGHT,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        )
        self.backend.bind_item_theme(host, self._surface_theme("tab_host"))

        header = self.backend.add_button(
            label=str(label),
            parent=host,
            width=width,
            height=max(1, self.TAB_HEIGHT - 3),
            callback=lambda *_args, tab_key=key: self.set_active_tab(tab_key),
        )

        # Dear PyGui drawlists do not reliably honor their own ``pos``. A
        # positioned group gives each overlay a stable (0, 0) drawing origin.
        indicator_anchor = self.backend.add_group(parent=host, pos=(0, 0))
        indicator = self.backend.add_drawlist(
            parent=indicator_anchor, width=width, height=self.TAB_HEIGHT, show=False)
        indicator_line = self.backend.draw_line(
            (1, self.TAB_HEIGHT - 1), (max(1, width - 1), self.TAB_HEIGHT - 1),
            parent=indicator, color=self.visual_style.tab_active_border,
            thickness=float(max(1, self.TAB_INDICATOR_HEIGHT)),
        )

        decoration_anchor = self.backend.add_group(parent=host, pos=(0, 0))
        decoration = self.backend.add_drawlist(
            parent=decoration_anchor, width=width, height=self.TAB_HEIGHT, show=False)
        context_line = self.backend.draw_line(
            (1, 1), (max(1, width - 1), 1), parent=decoration,
            color=context_accent or self.visual_style.tab_active_border,
            thickness=2.0, show=False,
        )
        draw_rectangle = getattr(self.backend, "draw_rectangle", None)
        badge_bg = (
            draw_rectangle(
                (0, 0), (0, 0), parent=decoration,
                color=(0, 0, 0, 0), fill=(0, 0, 0, 0), thickness=0.0,
                rounding=6.0, show=False,
            ) if callable(draw_rectangle) else None
        )
        draw_text = getattr(self.backend, "draw_text", None)
        badge_text = (
            draw_text(
                (0, 0), "", parent=decoration,
                color=badge_text_color or self.visual_style.application_text,
                size=9, show=False,
            ) if callable(draw_text) else None
        )
        return {
            "host": host,
            "header": header,
            "indicator_anchor": indicator_anchor,
            "indicator": indicator,
            "indicator_line": indicator_line,
            "decoration_anchor": decoration_anchor,
            "decoration": decoration,
            "context_line": context_line,
            "badge_bg": badge_bg,
            "badge_text_item": badge_text,
            "header_width": width,
            "accent": _rgba(accent),
            "context_accent": _rgba(context_accent),
            "badge": None if badge is None else str(badge),
            "badge_color": _rgba(badge_color),
            "badge_text_color": _rgba(badge_text_color),
        }

    def _indicator_geometry(self, width: int, style: str, thickness: int, *, contextual=False):
        t = max(1, int(thickness))
        if style == "top-line":
            # Keep the active line distinct from the contextual band when both
            # are present on the same retained tab header.
            y = max(0.5, (3 if contextual else 0) + t / 2.0)
            return (1, y), (max(1, width - 1), y)
        if style == "side-accent":
            x = max(0.5, t / 2.0)
            return (x, 3), (x, max(3, self.TAB_HEIGHT - 3))
        y = max(0.5, self.TAB_HEIGHT - (t / 2.0))
        return (1, y), (max(1, width - 1), y)

    def refresh(self, record, *, active: bool):
        badge = record.get("badge")
        width = self.width_for_label(record.get("label", ""), badge)
        indicator_height = max(1, int(self.TAB_INDICATOR_HEIGHT))
        indicator_mode = self.tab_render_style in self.INDICATOR_STYLES
        accent = record.get("accent") or self.visual_style.tab_active_border
        visible = bool(record.get("visible", True))

        self.backend.configure_item(record["host"], width=width, height=self.TAB_HEIGHT, show=visible)
        self.backend.configure_item(
            record["header"], width=width, height=max(1, self.TAB_HEIGHT - 3), show=visible)
        self.backend.configure_item(
            record["indicator"], width=width, height=self.TAB_HEIGHT,
            show=bool(indicator_mode and active and visible),
        )
        p1, p2 = self._indicator_geometry(
            width, self.tab_render_style, indicator_height,
            contextual=bool(record.get("context_group")))
        self.backend.configure_item(
            record["indicator_line"], p1=p1, p2=p2, color=accent,
            thickness=float(indicator_height),
        )

        context_accent = record.get("context_accent")
        context_visible = bool(record.get("context_group") and visible)
        badge_visible = bool(badge and visible)
        self.backend.configure_item(
            record["decoration"], width=width, height=self.TAB_HEIGHT,
            show=bool(context_visible or badge_visible),
        )
        self.backend.configure_item(
            record["context_line"], p1=(1, 1), p2=(max(1, width - 1), 1),
            color=context_accent or self.visual_style.tab_active_border,
            thickness=2.0, show=context_visible,
        )

        badge_width = self._badge_width(badge)
        badge_height = min(16, max(12, self.TAB_HEIGHT - 8))
        badge_x2 = max(2, width - 4)
        badge_x1 = max(1, badge_x2 - badge_width)
        badge_y1 = max(2, (self.TAB_HEIGHT - badge_height) // 2)
        badge_y2 = badge_y1 + badge_height
        badge_color = record.get("badge_color") or context_accent or accent
        badge_text_color = record.get("badge_text_color") or self.visual_style.application_text
        badge_bg = record.get("badge_bg")
        if badge_bg is not None:
            self.backend.configure_item(
                badge_bg, pmin=(badge_x1, badge_y1), pmax=(badge_x2, badge_y2),
                color=badge_color or (0, 0, 0, 0), fill=badge_color or (0, 0, 0, 0),
                show=badge_visible,
            )
        text_x = badge_x1 + max(3, (badge_width - len(str(badge or "")) * 6) // 2)
        text_y = badge_y1 + 2
        badge_text_item = record.get("badge_text_item")
        if badge_text_item is not None:
            self.backend.configure_item(
                badge_text_item, pos=(text_x, text_y), text=str(badge or ""),
                color=badge_text_color, show=badge_visible,
            )

        self.backend.bind_item_theme(record["host"], self._surface_theme("tab_host"))
        self.backend.bind_item_theme(record["header"], self._tab_theme(active))
        record["header_width"] = width

    def set_accent(self, record, accent=None):
        record["accent"] = _rgba(accent)
        self.refresh(record, active=record.get("key") == self._active_tab)
        return record["accent"]

    def set_context_accent(self, record, accent=None):
        record["context_accent"] = _rgba(accent)
        self.refresh(record, active=record.get("key") == self._active_tab)
        return record["context_accent"]

    def set_badge(self, record, badge=None, *, color=None, text_color=None):
        record["badge"] = None if badge in (None, "") else str(badge)
        if color is not None:
            record["badge_color"] = _rgba(color)
        elif badge in (None, ""):
            record["badge_color"] = None
        if text_color is not None:
            record["badge_text_color"] = _rgba(text_color)
        elif badge in (None, ""):
            record["badge_text_color"] = None
        self.refresh(record, active=record.get("key") == self._active_tab)
        return record["badge"]


__all__ = ["RibbonTabRenderer"]
