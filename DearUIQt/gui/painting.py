"""Qt-style retained painting primitives over the active renderer.

The public API deliberately exposes drawing intent rather than Dear PyGui
symbols.  ``QPainter`` still returns native retained-item ids because WinUx and
other applications may cache/configure individual primitives between frames.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..backends import dpg, get_backend


@dataclass(frozen=True)
class QPen:
    """Minimal QPen-compatible stroke description."""

    color: object = (255, 255, 255, 255)
    width: float = 1.0


@dataclass(frozen=True)
class QBrush:
    """Minimal QBrush-compatible fill description."""

    color: object = (0, 0, 0, 0)


class QPainter:
    """Retained painter for :class:`~DearUIQt.widgets.QCanvas` or native layers.

    A painter can be constructed with a paint device or begun later.  Methods
    accept explicit ``color``/``fill`` values for painless migration of retained
    renderer code while ``setPen``/``setBrush`` provide the Qt-style stateful
    path for new code.
    """

    def __init__(self, device=None, *, backend=None):
        self._device = None
        self._backend = backend or getattr(device, "backend", None) or get_backend()
        if self._backend is dpg:
            self._backend = get_backend()
        self._active = False
        self._pen = QPen()
        self._brush = QBrush()
        if device is not None:
            self.begin(device)

    def begin(self, device):
        if device is None:
            raise ValueError("QPainter requires a paint device")
        device_backend = getattr(device, "backend", None)
        if device_backend is dpg:
            device_backend = get_backend()
        if device_backend is not None:
            if self._backend is not None and self._backend is not device_backend:
                raise ValueError("painter and paint device must use the same backend")
            self._backend = device_backend
        self._device = device
        self._active = True
        return True

    def end(self):
        was_active = self._active
        self._active = False
        self._device = None
        return was_active

    def isActive(self):
        return bool(self._active)

    def device(self):
        return self._device

    def setPen(self, pen):
        if isinstance(pen, QPen):
            self._pen = pen
        else:
            self._pen = QPen(color=pen, width=self._pen.width)

    def pen(self):
        return self._pen

    def setBrush(self, brush):
        self._brush = brush if isinstance(brush, QBrush) else QBrush(color=brush)

    def brush(self):
        return self._brush

    def _parent(self, parent=None):
        if parent is not None:
            return getattr(parent, "tag", parent)
        if not self._active or self._device is None:
            raise RuntimeError("QPainter is not active")
        return getattr(self._device, "tag", self._device)

    def _stroke(self, color=None, thickness=None):
        return (
            self._pen.color if color is None else color,
            self._pen.width if thickness is None else thickness,
        )

    def _shape_style(self, color=None, fill=None, thickness=None):
        stroke, width = self._stroke(color, thickness)
        return {
            "color": stroke,
            "fill": self._brush.color if fill is None else fill,
            "thickness": width,
        }

    def drawLine(self, p1, p2, *, color=None, thickness=None, parent=None, **kwargs):
        color, thickness = self._stroke(color, thickness)
        return self._backend.draw_line(
            p1, p2, color=color, thickness=thickness,
            parent=self._parent(parent), **kwargs)

    def drawRect(self, p1, p2, *, color=None, fill=None, thickness=None,
                 rounding=0, parent=None, **kwargs):
        style = self._shape_style(color, fill, thickness)
        return self._backend.draw_rectangle(
            p1, p2, rounding=rounding, parent=self._parent(parent), **style, **kwargs)

    def drawEllipse(self, center, radius, *, color=None, fill=None, thickness=None,
                    segments=0, parent=None, **kwargs):
        style = self._shape_style(color, fill, thickness)
        return self._backend.draw_circle(
            center, radius, segments=segments, parent=self._parent(parent), **style, **kwargs)

    def drawTriangle(self, p1, p2, p3, *, color=None, fill=None, thickness=None,
                     parent=None, **kwargs):
        style = self._shape_style(color, fill, thickness)
        return self._backend.draw_triangle(
            p1, p2, p3, parent=self._parent(parent), **style, **kwargs)

    def drawQuad(self, p1, p2, p3, p4, *, color=None, fill=None, thickness=None,
                 parent=None, **kwargs):
        style = self._shape_style(color, fill, thickness)
        return self._backend.draw_quad(
            p1, p2, p3, p4, parent=self._parent(parent), **style, **kwargs)

    def drawPolygon(self, points, *, color=None, fill=None, thickness=None,
                    parent=None, **kwargs):
        style = self._shape_style(color, fill, thickness)
        return self._backend.draw_polygon(
            points, parent=self._parent(parent), **style, **kwargs)

    def drawText(self, pos, text, *, color=None, size=0, font=None, parent=None, **kwargs):
        color = self._pen.color if color is None else color
        tag = self._backend.draw_text(
            pos, text, color=color, size=size, parent=self._parent(parent), **kwargs)
        # DPG binds fonts after creating draw_text; keeping that detail here
        # avoids leaking renderer-specific font semantics into application code.
        if font is not None and hasattr(self._backend, "bind_item_font"):
            native_font = font.nativeId() if hasattr(font, "nativeId") else font
            self._backend.bind_item_font(tag, native_font)
        return tag

    def drawImage(self, texture, pmin, pmax, *, uv_min=(0, 0), uv_max=(1, 1),
                  color=(255, 255, 255, 255), parent=None, **kwargs):
        native_texture = texture.nativeId() if hasattr(texture, "nativeId") else texture
        return self._backend.draw_image(
            native_texture, pmin, pmax, uv_min=uv_min, uv_max=uv_max,
            color=color, parent=self._parent(parent), **kwargs)


__all__ = ["QPen", "QBrush", "QPainter"]
