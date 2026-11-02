"""Bounded screen-space marker sizes and drawing helpers for plot-digitizer points."""
import math
from dataclasses import dataclass

from DearUIQt.gui import QPainter


MARKER_GLYPHS = {
    "circle": "○",
    "square": "□",
    "triangle": "△",
    "diamond": "◇",
    "plus": "+",
    "cross": "×",
    "star": "*",
    "triangle_down": "▽",
}


@dataclass(frozen=True)
class MarkerMetrics:
    radius: float
    selection_radius: float
    hit_radius: float


def marker_metrics(zoom, source='auto', size_scale=1.0):
    """Return one shared screen-space marker size for every point source.

    ``source`` is intentionally retained for API compatibility and visibility /
    selection routing, but it must not change the painted marker size.  Manual,
    automatic and resampled points therefore remain visually uniform.
    """
    zoom = float(zoom)
    if not math.isfinite(zoom) or zoom <= 0:
        zoom = 1.0
    size_scale = max(0.5, min(2.5, float(size_scale)))
    base_radius = min(5.5, max(2.0, 3.0 * math.sqrt(zoom)))
    radius = base_radius * size_scale
    return MarkerMetrics(radius, min(26.0, max(5.5, radius + 3)), max(8.0, radius + 3))


def marker_glyph(style: str) -> str:
    return MARKER_GLYPHS.get(str(style or '').strip().lower(), '•')


def cursor_hits_marker(datasets, px, py, zoom, *, size_scale=1.0,
                       show_automatic=True, show_manual=True):
    """Hit-test visible painted markers, including locked/inactive datasets."""
    scale = max(.001, float(zoom))
    for dataset in datasets:
        if not dataset.visible:
            continue
        # Match the automatic-marker sampling used by the canvas renderer.
        stride = max(1, len(dataset.extracted_pixels) // 1200 or 1)
        for source, points in (
                ("auto", dataset.extracted_pixels[::stride]),
                ("manual", ((point.px, point.py) for point in dataset.manual_points))):
            if (source == "auto" and not show_automatic) or (source == "manual" and not show_manual):
                continue
            radius2 = (marker_metrics(scale, source, size_scale).hit_radius / scale) ** 2
            if any((x - px) ** 2 + (y - py) ** 2 <= radius2 for x, y in points):
                return True
    return False


def _regular_polygon(center, radius, sides, rotation=0.0):
    cx, cy = center
    return [
        (cx + radius * math.cos(rotation + 2 * math.pi * i / sides),
         cy + radius * math.sin(rotation + 2 * math.pi * i / sides))
        for i in range(sides)
    ]


def _star_polygon(center, outer_radius, inner_radius=None, points=5, rotation=-math.pi / 2):
    if inner_radius is None:
        inner_radius = outer_radius * 0.45
    cx, cy = center
    vertices = []
    for i in range(points * 2):
        radius = outer_radius if i % 2 == 0 else inner_radius
        angle = rotation + math.pi * i / points
        vertices.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return vertices


def draw_marker(parent, center, radius, style='circle', *, color=(255, 255, 255, 255),
                outline=(255, 255, 255, 255), thickness=1.0):
    style = str(style or 'circle').strip().lower()
    radius = max(1.0, float(radius))
    cx, cy = center
    painter = QPainter(parent)

    if style == 'circle':
        painter.drawEllipse((cx, cy), radius, fill=color, color=outline, thickness=thickness)
        return
    if style == 'square':
        painter.drawRect((cx - radius, cy - radius), (cx + radius, cy + radius),
                         fill=color, color=outline, thickness=thickness)
        return
    if style == 'triangle':
        points = _regular_polygon((cx, cy), radius * 1.15, 3, rotation=-math.pi / 2)
        painter.drawTriangle(points[0], points[1], points[2], fill=color, color=outline, thickness=thickness)
        return
    if style == 'triangle_down':
        points = _regular_polygon((cx, cy), radius * 1.15, 3, rotation=math.pi / 2)
        painter.drawTriangle(points[0], points[1], points[2], fill=color, color=outline, thickness=thickness)
        return
    if style == 'diamond':
        points = _regular_polygon((cx, cy), radius * 1.15, 4, rotation=math.pi / 4)
        painter.drawQuad(points[0], points[1], points[2], points[3], fill=color, color=outline, thickness=thickness)
        return
    if style == 'plus':
        width = max(1.5, thickness + 0.5)
        painter.drawLine((cx - radius, cy), (cx + radius, cy), color=outline, thickness=width)
        painter.drawLine((cx, cy - radius), (cx, cy + radius), color=outline, thickness=width)
        return
    if style == 'cross':
        width = max(1.5, thickness + 0.5)
        painter.drawLine((cx - radius, cy - radius), (cx + radius, cy + radius), color=outline, thickness=width)
        painter.drawLine((cx - radius, cy + radius), (cx + radius, cy - radius), color=outline, thickness=width)
        return
    if style == 'star':
        points = _star_polygon((cx, cy), radius * 1.2)
        painter.drawPolygon(points, color=outline, fill=color, thickness=thickness)
        return

    painter.drawEllipse((cx, cy), radius, fill=color, color=outline, thickness=thickness)


def draw_axis_marker(parent, center, axis, *, kind='tick', radius=6,
                     color=(0, 120, 215, 255)):
    """Axes use a literal asterisk; the shared X1/Y1 origin is a hollow donut."""
    painter = QPainter(parent)
    x, y = center
    r = float(radius)
    if kind == 'origin':
        # Transparent fill keeps the hole open over both light and dark charts.
        for thickness, ink in ((5, (255, 255, 255, 255)), (3, color)):
            painter.drawEllipse((x, y), r, fill=(0, 0, 0, 0), color=ink, thickness=thickness)
        return
    # Three crossing strokes form '*', not the dataset's filled star polygon.
    segments = [((x - r * math.cos(angle), y - r * math.sin(angle)),
                 (x + r * math.cos(angle), y + r * math.sin(angle)))
                for angle in (math.pi / 2, math.pi / 6, -math.pi / 6)]
    for thickness, ink in ((4, (255, 255, 255, 255)), (2, color)):
        for a, b in segments:
            painter.drawLine(a, b, color=ink, thickness=thickness)
