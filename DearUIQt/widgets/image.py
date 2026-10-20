"""Qt-style retained image display widget."""
from __future__ import annotations

from .widget import QWidget


class QImageView(QWidget):
    """Lightweight image widget backed by one retained texture item.

    ``QImageView`` is intentionally a widget rather than a renderer primitive:
    it owns geometry/lifetime and can participate in DearUIQt layouts while the
    texture resource itself remains backend-managed.
    """

    def __init__(self, texture=None, *, parent=None, after=None, backend=None,
                 width=None, height=None, pos=None, uv_min=(0, 0), uv_max=(1, 1),
                 tint=(255, 255, 255, 255), border=(0, 0, 0, 0), tag=None):
        backend, options = self._construction(parent, backend)
        if after is not None:
            options["after"] = getattr(after, "tag", after)
        if width is not None:
            options["width"] = width
        if height is not None:
            options["height"] = height
        if pos is not None:
            options["pos"] = tuple(pos)
        if tag is not None:
            options["tag"] = tag
        native_texture = texture.nativeId() if hasattr(texture, "nativeId") else texture
        native = backend.add_image(
            native_texture, uv_min=uv_min, uv_max=uv_max,
            tint_color=tint, border_color=border, **options)
        super().__init__(native, parent=parent, after=after, backend=backend)
        self._texture = texture
        self._properties.update(texture_tag=texture, uv_min=tuple(uv_min), uv_max=tuple(uv_max),
                                tint_color=tuple(tint), border_color=tuple(border))

    def setPixmap(self, texture):
        self._texture = texture
        native_texture = texture.nativeId() if hasattr(texture, "nativeId") else texture
        self._on_ui("texture_tag", self._configure, "texture_tag", native_texture)

    def pixmap(self):
        return self._texture

    def setTint(self, color):
        self._on_ui("tint_color", self._configure, "tint_color", tuple(color))

    def setBorderColor(self, color):
        self._on_ui("border_color", self._configure, "border_color", tuple(color))


__all__ = ["QImageView"]
