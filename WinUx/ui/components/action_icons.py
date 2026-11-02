"""Small semantic action glyphs, drawn consistently instead of reusing placeholders."""
from __future__ import annotations

from array import array

ACTION_ICONS = frozenset({
    'terminal', 'transfercenter', 'compactmonitor', 'jobschedule',
    'referencechart', 'plotdigitizer', 'sitemanager', 'bookmarks', 'diagnostics',
})


def action_icon_pixels(name, size=32):
    name = str(name).casefold()
    if name not in ACTION_ICONS:
        return None
    from PIL import Image, ImageDraw
    size = max(16, int(size or 32))
    image = Image.new('RGBA', (size * 4, size * 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = image.width / 24.0
    ink, accent = '#52616f', '#0078d4'
    surface = '#eef6fc'

    def points(coords):
        return [(round(x * scale), round(y * scale)) for x, y in coords]

    def line(coords, color=ink, width=1.7):
        draw.line(points(coords), fill=color, width=max(1, round(width * scale)), joint='curve')

    def box(rect, color=ink, fill=None, radius=1.5):
        draw.rounded_rectangle(points((rect[:2], rect[2:])),
                               radius=radius * scale, outline=color,
                               fill=fill, width=max(1, round(1.6 * scale)))

    def circle(rect, color=accent, fill=None):
        draw.ellipse(points((rect[:2], rect[2:])), outline=color, fill=fill,
                     width=max(1, round(1.5 * scale)))

    if name == 'terminal':
        box((2, 4, 22, 20), fill=surface)
        line(((6, 9), (9, 12), (6, 15)), accent)
        line(((12, 15), (18, 15)))
    elif name == 'transfercenter':
        line(((3, 8), (20, 8)), accent)
        line(((16, 4), (20, 8), (16, 12)), accent)
        line(((21, 16), (4, 16)))
        line(((8, 12), (4, 16), (8, 20)))
    elif name == 'compactmonitor':
        box((2, 4, 22, 20))
        line(((3, 8), (21, 8)), width=1.2)
        box((12, 11, 19, 17), color=accent, fill=surface, radius=.8)
    elif name == 'jobschedule':
        box((3, 5, 19, 21))
        line(((4, 10), (18, 10)), width=1.2)
        line(((7, 2), (7, 7)))
        line(((15, 2), (15, 7)))
        circle((12, 12, 23, 23), fill='white')
        line(((17.5, 14.5), (17.5, 17.5), (20, 18.5)), accent, width=1.4)
    elif name == 'referencechart':
        line(((3, 3), (3, 21), (22, 21)))
        line(((6, 17), (11, 11), (15, 14), (21, 5)), accent)
        for x, y in ((6, 17), (11, 11), (15, 14), (21, 5)):
            circle((x - 1, y - 1, x + 1, y + 1), fill=accent)
    elif name == 'plotdigitizer':
        box((2, 3, 21, 22))
        line(((5, 17), (10, 12), (14, 15), (19, 8)), accent)
        circle((11, 7, 19, 15), fill='white')
        line(((15, 5), (15, 17)), accent, width=1.3)
        line(((9, 11), (21, 11)), accent, width=1.3)
    elif name == 'sitemanager':
        for y in (3, 10, 17):
            box((3, y, 21, y + 5), radius=1)
            circle((6, y + 2, 7, y + 3), fill=accent)
            line(((11, y + 2.5), (18, y + 2.5)), width=1)
    elif name == 'bookmarks':
        line(((6, 22), (6, 3), (18, 3), (18, 22), (12, 18), (6, 22)), accent)
        line(((9, 8), (15, 8)), width=1.3)
        line(((9, 12), (15, 12)), width=1.3)
    elif name == 'diagnostics':
        box((2, 4, 22, 20))
        line(((4, 13), (8, 13), (10, 8), (13, 17), (16, 11), (20, 11)), accent)
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    return size, size, array('f', (value / 255.0 for value in image.tobytes()))
