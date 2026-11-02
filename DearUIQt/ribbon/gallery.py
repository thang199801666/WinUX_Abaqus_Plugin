"""Generic appearance catalog and preview helpers for :mod:`DearUIQt.ribbon`.

The gallery is deliberately content-agnostic.  It previews appearance tokens and
geometry using miniature generic primitives; it never defines application tabs,
groups or commands.  Applying a gallery item delegates to RibbonBar's retained
runtime appearance switch, so application widget identity and callbacks survive.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .appearance_templates import (
    RibbonAppearanceTemplate,
    get_ribbon_appearance_template,
    ribbon_appearance_template_names,
)
from .display_templates import get_ribbon_display_template
from .visual_styles import get_ribbon_visual_style


@dataclass(frozen=True)
class RibbonAppearancePreview:
    """Backend-independent description of one ready-made appearance preset."""

    key: str
    name: str
    description: str
    display_template: str
    visual_style: str
    tab_style: str
    group_style: str
    button_style: str
    tab_height: int
    body_height: int
    large_button_width: int
    large_icon_size: int
    accent: tuple[int, int, int, int]
    root_background: tuple[int, int, int, int]
    body_background: tuple[int, int, int, int]
    group_background: tuple[int, int, int, int]
    text_color: tuple[int, int, int, int]

    @classmethod
    def from_template(cls, template: str | RibbonAppearanceTemplate):
        appearance = get_ribbon_appearance_template(template)
        display = get_ribbon_display_template(appearance.display_template)
        style = get_ribbon_visual_style(appearance.visual_style)
        return cls(
            key=appearance.key,
            name=appearance.name,
            description=appearance.description,
            display_template=display.key,
            visual_style=style.key,
            tab_style=appearance.tab_style,
            group_style=appearance.group_style,
            button_style=appearance.button_style,
            tab_height=display.tab_height,
            body_height=display.body_height,
            large_button_width=display.large_button_width,
            large_icon_size=display.large_icon_size,
            accent=style.tab_active_border,
            root_background=style.root_bg,
            body_background=style.body_bg,
            group_background=style.group_bg,
            text_color=style.text,
        )


@dataclass(frozen=True)
class RibbonAppearanceSnapshot:
    """Restorable runtime appearance state for preview/selection workflows."""

    appearance_template: str | None
    display_template: str
    visual_style: str
    tab_style: str
    group_style: str
    button_style: str


@dataclass
class RibbonAppearanceGalleryView:
    """Handles created by :meth:`RibbonAppearanceGallery.create_view`."""

    root: object
    cards: dict[str, dict]
    selected: str | None = None


class RibbonAppearanceGallery:
    """Content-independent catalog, preview and runtime apply helper.

    ``create_view`` is intentionally lightweight: each card is a small retained
    miniature (tab strip, group and command blocks) drawn from the template's
    own geometry/colors plus an Apply button.  It does not instantiate nested
    RibbonBar objects and therefore does not duplicate application commands.
    """

    def __init__(self, appearances: Iterable[str | RibbonAppearanceTemplate] | None = None):
        source = ribbon_appearance_template_names() if appearances is None else appearances
        previews = []
        seen = set()
        for item in source:
            preview = RibbonAppearancePreview.from_template(item)
            if preview.key in seen:
                continue
            seen.add(preview.key)
            previews.append(preview)
        self._previews = tuple(previews)
        self._by_key = {preview.key: preview for preview in self._previews}

    @property
    def previews(self) -> tuple[RibbonAppearancePreview, ...]:
        return self._previews

    def names(self) -> tuple[str, ...]:
        return tuple(preview.key for preview in self._previews)

    def get(self, key: str) -> RibbonAppearancePreview:
        normalized = str(key).strip().lower()
        try:
            return self._by_key[normalized]
        except KeyError as exc:
            raise KeyError(
                "Unknown ribbon appearance preview {!r}. Available: {}".format(
                    normalized, ", ".join(self.names()) or "<none>"
                )
            ) from exc

    @staticmethod
    def snapshot(ribbon) -> RibbonAppearanceSnapshot:
        return RibbonAppearanceSnapshot(
            appearance_template=getattr(ribbon, "appearance_template_key", None),
            display_template=ribbon.display_template_key,
            visual_style=ribbon.visual_style_key,
            tab_style=ribbon.tab_render_style,
            group_style=ribbon.group_render_style,
            button_style=ribbon.button_render_style,
        )

    def apply(self, ribbon, key: str, **overrides):
        self.get(key)  # fail early with gallery-scoped diagnostics
        return ribbon.set_appearance_template(key, **overrides)

    @staticmethod
    def restore(ribbon, snapshot: RibbonAppearanceSnapshot):
        if not isinstance(snapshot, RibbonAppearanceSnapshot):
            raise TypeError("snapshot must be a RibbonAppearanceSnapshot")
        if snapshot.appearance_template:
            return ribbon.set_appearance_template(
                snapshot.appearance_template,
                display_template=snapshot.display_template,
                visual_style=snapshot.visual_style,
                tab_style=snapshot.tab_style,
                group_style=snapshot.group_style,
                button_style=snapshot.button_style,
            )
        ribbon.set_display_template(snapshot.display_template)
        ribbon.set_visual_style(snapshot.visual_style)
        ribbon.set_render_styles(
            tab_style=snapshot.tab_style,
            group_style=snapshot.group_style,
            button_style=snapshot.button_style,
        )
        return ribbon.appearance_state()

    @staticmethod
    def _safe_draw(backend, method: str, *args, **kwargs):
        fn = getattr(backend, method, None)
        if not callable(fn):
            return None
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None

    def _draw_preview(self, backend, parent, preview: RibbonAppearancePreview, width: int, height: int):
        drawlist = backend.add_drawlist(parent=parent, width=width, height=height)
        # Geometry is normalized into a miniature while preserving relative
        # density differences between templates.
        tab_h = max(12, min(22, int(round(preview.tab_height * 0.62))))
        body_top = tab_h + 2
        body_h = max(28, height - body_top - 2)
        self._safe_draw(
            backend, "draw_rectangle", (0, 0), (width - 1, height - 1), parent=drawlist,
            color=preview.root_background, fill=preview.root_background, thickness=1.0,
        )
        self._safe_draw(
            backend, "draw_rectangle", (0, body_top), (width - 1, height - 1), parent=drawlist,
            color=preview.body_background, fill=preview.body_background, thickness=1.0,
        )
        tab_w = max(34, min(64, int(round(preview.large_button_width * 0.62))))
        self._safe_draw(
            backend, "draw_rectangle", (5, 3), (5 + tab_w, tab_h), parent=drawlist,
            color=preview.group_background, fill=preview.group_background,
            thickness=1.0, rounding=4.0 if preview.tab_style == "pill" else 1.0,
        )
        if preview.tab_style in ("underline", "top-line", "side-accent"):
            if preview.tab_style == "underline":
                p1, p2 = (5, tab_h), (5 + tab_w, tab_h)
            elif preview.tab_style == "top-line":
                p1, p2 = (5, 3), (5 + tab_w, 3)
            else:
                p1, p2 = (5, 3), (5, tab_h)
            self._safe_draw(
                backend, "draw_line", p1, p2, parent=drawlist,
                color=preview.accent, thickness=2.0,
            )
        group_y1 = body_top + 4
        group_y2 = body_top + body_h - 4
        group_w = max(60, min(width - 12, int(round(preview.large_button_width * 1.35))))
        self._safe_draw(
            backend, "draw_rectangle", (5, group_y1), (5 + group_w, group_y2), parent=drawlist,
            color=preview.group_background, fill=preview.group_background,
            thickness=1.0, rounding=4.0 if preview.group_style == "card" else 0.0,
        )
        cmd_h = max(16, group_y2 - group_y1 - 10)
        cmd_w = max(20, min(38, int(round(preview.large_icon_size * 0.8))))
        x = 10
        for _ in range(3):
            self._safe_draw(
                backend, "draw_rectangle", (x, group_y1 + 5), (x + cmd_w, group_y1 + 5 + cmd_h),
                parent=drawlist, color=preview.accent if preview.button_style == "outlined" else preview.group_background,
                fill=(0, 0, 0, 0) if preview.button_style == "outlined" else preview.group_background,
                thickness=1.0, rounding=3.0 if preview.button_style == "raised" else 1.0,
            )
            x += cmd_w + 5
        return drawlist

    def create_view(
        self,
        parent,
        ribbon,
        *,
        card_width: int = 220,
        preview_height: int = 82,
        on_changed=None,
    ) -> RibbonAppearanceGalleryView:
        """Create a lightweight generic appearance gallery using ``ribbon.backend``.

        The view is optional; callers that only need settings/preferences data can
        use :attr:`previews`, :meth:`apply`, :meth:`snapshot` and :meth:`restore`.
        """
        backend = ribbon.backend
        root = backend.add_child_window(
            parent=parent, width=-1, height=-1, border=False,
            no_scrollbar=False, no_scroll_with_mouse=False,
        )
        cards: dict[str, dict] = {}
        for preview in self._previews:
            card = backend.add_child_window(
                parent=root, width=max(140, int(card_width)), height=preview_height + 54,
                border=True, no_scrollbar=True, no_scroll_with_mouse=True,
            )
            title = backend.add_text(preview.name, parent=card)
            mini = self._draw_preview(
                backend, card, preview, max(120, int(card_width) - 12), int(preview_height))

            def choose(*_args, key=preview.key):
                result = self.apply(ribbon, key)
                view.selected = key
                if callable(on_changed):
                    on_changed(key, result)

            button = backend.add_button(
                label="Apply", parent=card, width=max(70, int(card_width) - 12), callback=choose)
            cards[preview.key] = {
                "card": card, "title": title, "preview": mini, "apply": button,
            }
        view = RibbonAppearanceGalleryView(
            root=root, cards=cards, selected=getattr(ribbon, "appearance_template_key", None))
        return view


__all__ = [
    "RibbonAppearancePreview", "RibbonAppearanceSnapshot",
    "RibbonAppearanceGalleryView", "RibbonAppearanceGallery",
]
