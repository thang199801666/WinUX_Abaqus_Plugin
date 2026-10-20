"""Ribbon image-tile texture generation.

This module is rendering infrastructure only; it does not know about the host application
resources. Icon path resolution is supplied by the Ribbon host.
"""
from __future__ import annotations

from pathlib import Path
import os


try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Pillow is bundled in production
    Image = ImageDraw = ImageFont = None

from ..gui.palette import QtFusionPalette


class RibbonTileTextures:
    """Build one transparent icon+caption texture for a large ribbon command.

    A large command is intentionally one Dear PyGui image button.  This avoids
    the clipping and mismatched hover geometry that occurs when an icon button
    and a caption button are stacked as separate controls.
    """

    TILE_FONT_SIZE = 9
    TILE_LINE_HEIGHT = 11
    TILE_TEXT_MARGIN = 6

    _cache: dict[tuple, object | None] = {}
    _registry_tag = "dearuiqt_ribbon_tile_texture_registry"

    @classmethod
    def reset_stale(cls, backend=None):
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        stale = []
        for key, tag in cls._cache.items():
            try:
                if tag is not None and not backend.does_item_exist(tag):
                    stale.append(key)
            except Exception:
                stale.append(key)
        for key in stale:
            cls._cache.pop(key, None)

    @staticmethod
    def _font(size=12):
        if ImageFont is None:
            return None
        windir = Path(os.environ.get("WINDIR", r"C:\\Windows"))
        for name in ("segoeui.ttf", "arial.ttf", "tahoma.ttf"):
            path = windir / "Fonts" / name
            if path.is_file():
                try:
                    return ImageFont.truetype(str(path), size)
                except Exception:
                    pass
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    @staticmethod
    def _wrapped_lines(label: str, *, draw=None, font=None, max_width: int | None = None):
        words = [part for part in str(label or "").split() if part]
        if not words:
            return [""]

        def width_of(value):
            if draw is not None and font is not None:
                try:
                    bbox = draw.textbbox((0, 0), value, font=font)
                    return max(0, bbox[2] - bbox[0])
                except Exception:
                    pass
            return max(0, len(value) * 6)

        full = " ".join(words)
        if max_width is None or width_of(full) <= max_width:
            return [full]
        if len(words) == 1:
            return [words[0]]

        # Choose the two-line split that both fits the available width and is
        # visually balanced. If no split fully fits, use the least-overflowing one.
        candidates = []
        for split in range(1, len(words)):
            first = " ".join(words[:split])
            second = " ".join(words[split:])
            w1, w2 = width_of(first), width_of(second)
            overflow = max(0, w1 - max_width) + max(0, w2 - max_width)
            balance = abs(w1 - w2)
            candidates.append((overflow, balance, first, second))
        candidates.sort(key=lambda item: (item[0], item[1]))
        _, _, first, second = candidates[0]
        return [first, second]

    @classmethod
    def get(cls, image_name: str, label: str, width: int, height: int, icon_size: int, *, icon_path_resolver=None, backend=None):
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        if Image is None or ImageDraw is None:
            return None
        cls.reset_stale(backend)
        if icon_path_resolver is None:
            path = Path(str(image_name))
        else:
            path = Path(icon_path_resolver(image_name))
        key = (
            str(path).casefold(), str(label), int(width), int(height), int(icon_size),
            cls.TILE_FONT_SIZE, cls.TILE_LINE_HEIGHT,
        )
        if key in cls._cache:
            return cls._cache[key]

        if not path.is_file():
            cls._cache[key] = None
            return None
        try:
            tile = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))
            icon = Image.open(path).convert("RGBA")
            icon.thumbnail((int(icon_size), int(icon_size)), Image.Resampling.LANCZOS)
            ix = max(0, (tile.width - icon.width) // 2)
            iy = 5
            tile.alpha_composite(icon, (ix, iy))

            draw = ImageDraw.Draw(tile)
            font = cls._font(cls.TILE_FONT_SIZE)
            max_text_width = max(12, tile.width - cls.TILE_TEXT_MARGIN * 2)
            lines = cls._wrapped_lines(
                label, draw=draw, font=font, max_width=max_text_width)
            line_height = cls.TILE_LINE_HEIGHT
            base_y = max(icon_size + 7, height - len(lines) * line_height - 9)
            color = tuple(QtFusionPalette.TEXT[:3]) + (255,)
            for index, line in enumerate(lines[:2]):
                try:
                    bbox = draw.textbbox((0, 0), line, font=font)
                    tw = bbox[2] - bbox[0]
                except Exception:
                    tw = max(0, len(line) * 6)
                tx = max(2, (tile.width - tw) // 2)
                draw.text((tx, base_y + index * line_height), line, font=font, fill=color)

            data = [channel / 255.0 for pixel in tile.getdata() for channel in pixel]
            if not backend.does_item_exist(cls._registry_tag):
                backend.add_texture_registry(tag=cls._registry_tag, show=False)
            tag = "dearuiqt_ribbon_tile_{}".format(len(cls._cache))
            backend.add_static_texture(tile.width, tile.height, data, parent=cls._registry_tag, tag=tag)
            cls._cache[key] = tag
            return tag
        except Exception:
            cls._cache[key] = None
            return None


__all__ = ["RibbonTileTextures"]
