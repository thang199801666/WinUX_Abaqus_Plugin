"""Image clipping for a fixed-size magnifier synchronized with canvas zoom."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PreviewGeometry:
    image_min: tuple
    image_max: tuple
    uv_min: tuple
    uv_max: tuple


def preview_geometry(image_size, center, canvas_scale, panel_size=140, magnification=5):
    """Return panel-local image bounds and UVs, preserving scale at image edges.

    Uncovered space remains background instead of stretching a clipped sample
    to fill the panel. Thus one image pixel is always canvas_scale * 5 pixels
    wide in the default preview, including at corners and extreme zoom levels.
    """
    width, height = image_size
    scale = float(canvas_scale) * float(magnification)
    if width <= 0 or height <= 0 or panel_size <= 0 or not math.isfinite(scale) or scale <= 0:
        raise ValueError("Preview image, size and zoom must be positive")
    cx = min(float(width), max(0., float(center[0])))
    cy = min(float(height), max(0., float(center[1])))
    half = float(panel_size) / (2 * scale)
    left, top = cx - half, cy - half
    x0, y0 = max(0., left), max(0., top)
    x1, y1 = min(float(width), cx + half), min(float(height), cy + half)
    return PreviewGeometry(
        ((x0 - left) * scale, (y0 - top) * scale),
        ((x1 - left) * scale, (y1 - top) * scale),
        (x0 / width, y0 / height), (x1 / width, y1 / height))
