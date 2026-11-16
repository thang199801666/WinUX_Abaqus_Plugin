from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .shared import _BINARY_TO_255_LUT, _NUMERIC_CHARS

@lru_cache(maxsize=512)
def _threshold_lut(threshold, *, dark=True, peak=1):
    """Reusable exact 8-bit thresholds; keys include polarity/output scale."""
    return bytes(peak if (value <= threshold if dark else value >= threshold) else 0
                 for value in range(256))


def _point_lut(image, lookup):
    """Public Pillow/bytes fast path without rebuilding/rounding a 256-item LUT."""
    if image.mode != 'L':
        return image.point(lookup)
    return Image.frombytes('L', image.size, image.tobytes().translate(lookup))


def _column_sums(mask):
    # zip and sum do the row/column traversal in C, avoiding a Python generator
    # and two indexed lookups for every glyph pixel. No resampling/rounding.
    return [sum(column) for column in zip(*mask)]


def _font_candidates() -> list[str]:
    candidates = []
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates.extend(str(Path(windir) / "Fonts" / name) for name in (
        "segoeui.ttf", "arial.ttf", "calibri.ttf", "tahoma.ttf", "verdana.ttf",
        "times.ttf", "timesbd.ttf", "arialbd.ttf"))
    candidates.extend((
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
        "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
        "/usr/share/fonts/truetype/croscore/Arimo-Regular.ttf",
        "/usr/share/fonts/truetype/croscore/Tinos-Regular.ttf",
    ))
    return [path for path in candidates if os.path.isfile(path)]


@lru_cache(maxsize=1)
def _template_fonts():
    fonts = []
    for path in _font_candidates()[:8]:
        try:
            fonts.append(ImageFont.truetype(path, 24))
        except OSError:
            pass
    if not fonts:
        fonts.append(ImageFont.load_default())
    return tuple(fonts)


def _template_font_indexes():
    """Return the preferred template faces that actually exist on this host.

    Windows normally exposes all of the historical 0/1/5/6/7 faces.  Test,
    portable and stripped-down deployments may expose fewer fonts; the OCR
    fallback must degrade to those available faces instead of indexing past
    the tuple and aborting a detection pass.
    """
    count = len(_template_fonts())
    preferred = [index for index in (0, 1, 5, 6, 7) if index < count]
    # Portable builds often have only 2-4 fonts, whose useful serif/bold face
    # may occupy index 2/3 rather than the Windows-specific 5/6/7 slots. Keep
    # the historical Windows ordering when available, but include every local
    # face when the font bank is smaller than that preferred set.
    if count < 8:
        preferred.extend(index for index in range(count) if index not in preferred)
    return tuple(preferred) or tuple(range(count))


def _otsu_threshold(gray: Image.Image, hist=None) -> int:
    hist = gray.histogram()[:256] if hist is None else hist
    total = sum(hist)
    if total <= 0:
        return 128
    total_sum = sum(i * count for i, count in enumerate(hist))
    background_weight = 0
    background_sum = 0
    best_variance = -1.0
    best = 128
    for threshold, count in enumerate(hist):
        background_weight += count
        if not background_weight:
            continue
        foreground_weight = total - background_weight
        if not foreground_weight:
            break
        background_sum += threshold * count
        mean_background = background_sum / background_weight
        mean_foreground = (total_sum - background_sum) / foreground_weight
        between = background_weight * foreground_weight * (mean_background - mean_foreground) ** 2
        if between > best_variance:
            best_variance = between
            best = threshold
    return int(best)


def _flat_pixels(image):
    """Compatibility helper for legacy regressions; hot paths must not call it."""
    getter = getattr(image, "get_flattened_data", None)
    return list(getter()) if getter is not None else list(image.getdata())


def _binary_mask(image: Image.Image) -> list[bytearray]:
    gray = image if image.mode == 'L' else image.convert("L")
    hist = gray.histogram()[:256]
    mode = max(range(256), key=lambda value: hist[value])
    otsu = _otsu_threshold(gray, hist)
    # Charts are normally light-on-dark or dark-on-light.  Stay a little away
    # from the dominant background so faint antialiasing does not connect words.
    if mode >= 128:
        threshold = min(mode - 8, max(otsu, mode - 62))
        lookup = _threshold_lut(threshold)
    else:
        threshold = max(mode + 8, min(otsu, mode + 62))
        lookup = _threshold_lut(threshold, dark=False)
    pixels = gray.tobytes().translate(lookup)
    return [bytearray(pixels[y * gray.width:(y + 1) * gray.width])
            for y in range(gray.height)]


def _bbox(mask) -> tuple[int, int, int, int] | None:
    """Return an inclusive bounding box using Pillow's C-backed getbbox.

    The previous Python pixel walk allocated two coordinate lists for every
    glyph/mask. Tick OCR calls this helper many times, so keeping the same
    0/1 representation but letting Pillow scan it is materially faster.
    """
    if not mask or not mask[0]:
        return None
    height, width = len(mask), len(mask[0])
    box = Image.frombytes("L", (width, height), b"".join(mask)).getbbox()
    if box is None:
        return None
    return box[0], box[1], box[2] - 1, box[3] - 1


def _crop_mask(mask, box):
    x0, y0, x1, y1 = box
    return [bytearray(row[x0:x1 + 1]) for row in mask[y0:y1 + 1]]


def _projection_bands(values: Iterable[int], *, minimum: int = 1, merge_gap: int = 1):
    active = [index for index, value in enumerate(values) if value >= minimum]
    if not active:
        return []
    groups = [[active[0]]]
    for value in active[1:]:
        if value - groups[-1][-1] <= merge_gap + 1:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [(group[0], group[-1]) for group in groups]


_BINARY_BYTE_LUT = bytes([0] + [1] * 255)


def _components(mask):
    if not mask or not mask[0]:
        return []
    height, width = len(mask), len(mask[0])
    # Only small label/glyph masks are cached. Large axis strips bypass the
    # cache; mutable source masks are keyed by normalized *pixels*, not identity.
    if width * height > 16384:
        return _components_uncached(mask)
    pixels = b''.join(map(bytes, mask)).translate(_BINARY_BYTE_LUT)
    # Noisy masks can contain hundreds of isolated components. Bound both
    # source bytes and result complexity, not just the number of cache entries.
    if pixels.count(b'\x01') > 512:
        return _components_uncached(mask)
    return list(_cached_components(width, height, pixels))


@lru_cache(maxsize=128)
def _cached_components(width, height, pixels):
    mask = [pixels[y * width:(y + 1) * width] for y in range(height)]
    return tuple(_components_uncached(mask))


def _components_uncached(mask):
    """Return 8-connected components with a sparse run-length scan.

    Numeric-label masks are mostly background.  The previous flood fill walked
    every pixel in Python and then revisited every foreground pixel through an
    8-neighbour stack.  This version finds horizontal runs with ``bytes.find``
    (C-backed), unions only runs that touch in adjacent rows, and preserves the
    exact inclusive bounding boxes/pixel areas of the old 8-connected result.
    """
    if not mask or not mask[0]:
        return []
    width = len(mask[0])
    parents = []
    ranks = []
    records = []  # x0, y0, x1, y1, area

    def make_set(x0, y, x1):
        index = len(parents)
        parents.append(index)
        ranks.append(0)
        records.append([x0, y, x1, y, x1 - x0 + 1])
        return index

    def find(index):
        root = index
        while parents[root] != root:
            root = parents[root]
        while parents[index] != index:
            parent = parents[index]
            parents[index] = root
            index = parent
        return root

    def union(first, second):
        a, b = find(first), find(second)
        if a == b:
            return a
        if ranks[a] < ranks[b]:
            a, b = b, a
        parents[b] = a
        if ranks[a] == ranks[b]:
            ranks[a] += 1
        return a

    previous = []  # (x0, x1, set_id)
    for y, source in enumerate(mask):
        # Normalize any non-zero mask representation (1 or 255) in C.
        row = bytes(source).translate(_BINARY_BYTE_LUT)
        current = []
        start = row.find(b"\x01")
        while start >= 0:
            end = row.find(b"\x00", start)
            if end < 0:
                end = width
            set_id = make_set(start, y, end - 1)
            current.append((start, end - 1, set_id))
            start = row.find(b"\x01", end)

        # 8-connectivity: horizontal runs connect when their intervals overlap
        # after either interval is expanded by one pixel.
        prev_index = 0
        for x0, x1, set_id in current:
            while prev_index < len(previous) and previous[prev_index][1] < x0 - 1:
                prev_index += 1
            scan = prev_index
            while scan < len(previous) and previous[scan][0] <= x1 + 1:
                union(set_id, previous[scan][2])
                scan += 1
        previous = current

    if not records:
        return []
    merged = {}
    for index, record in enumerate(records):
        root = find(index)
        item = merged.get(root)
        if item is None:
            merged[root] = record[:]
        else:
            item[0] = min(item[0], record[0])
            item[1] = min(item[1], record[1])
            item[2] = max(item[2], record[2])
            item[3] = max(item[3], record[3])
            item[4] += record[4]
    return sorted(tuple(item) for item in merged.values())


def _hole_centers(mask):
    if not mask or not mask[0]:
        return []
    height, width = len(mask), len(mask[0])
    seen = [bytearray(width) for _ in range(height)]
    holes = []
    for start_y in range(height):
        for start_x in range(width):
            if mask[start_y][start_x] or seen[start_y][start_x]:
                continue
            stack = [(start_x, start_y)]
            seen[start_y][start_x] = 1
            points = []
            touches_edge = False
            while stack:
                x, y = stack.pop()
                points.append((x, y))
                if x in (0, width - 1) or y in (0, height - 1):
                    touches_edge = True
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < width and 0 <= ny < height and not mask[ny][nx]
                            and not seen[ny][nx]):
                        seen[ny][nx] = 1
                        stack.append((nx, ny))
            if not touches_edge and len(points) >= 2:
                holes.append((sum(x for x, _ in points) / len(points) / max(1, width),
                              sum(y for _, y in points) / len(points) / max(1, height)))
    return holes


def _mask_image(mask) -> Image.Image:
    if not mask or not mask[0]:
        return Image.new("L", (1, 1), 0)
    height, width = len(mask), len(mask[0])
    # b"".join is implemented in C and the LUT expands 0/1 to 0/255 in C.
    # This replaces a Python generator over every mask pixel.
    return Image.frombytes("L", (width, height), b"".join(mask).translate(_BINARY_TO_255_LUT))


def _shift_mask_image(image, dx, dy):
    """Translate a binary L image without ImageChops.offset wrap-around."""
    width, height = image.size
    out = Image.new('L', (width, height), 0)
    src_left = max(0, -dx)
    src_top = max(0, -dy)
    src_right = min(width, width - dx)
    src_bottom = min(height, height - dy)
    if src_right > src_left and src_bottom > src_top:
        out.paste(image.crop((src_left, src_top, src_right, src_bottom)),
                  (src_left + dx, src_top + dy))
    return out


def _dilate_binary_square(image, radius):
    """Fast square dilation for 0/255 masks using separable max composition."""
    radius = max(0, int(radius))
    if radius <= 0:
        return image.copy()
    horizontal = image
    for delta in range(1, radius + 1):
        horizontal = ImageChops.lighter(horizontal, _shift_mask_image(image, delta, 0))
        horizontal = ImageChops.lighter(horizontal, _shift_mask_image(image, -delta, 0))
    vertical = horizontal
    for delta in range(1, radius + 1):
        vertical = ImageChops.lighter(vertical, _shift_mask_image(horizontal, 0, delta))
        vertical = ImageChops.lighter(vertical, _shift_mask_image(horizontal, 0, -delta))
    return vertical


def _normalized_mask(mask, width=20, height=28):
    box = _bbox(mask)
    if box is None:
        return Image.new("1", (width, height), 0)
    cropped = _mask_image(_crop_mask(mask, box))
    cw, ch = cropped.size
    scale = min((width - 2) / max(1, cw), (height - 2) / max(1, ch))
    rw, rh = max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))
    resized = _point_lut(cropped.resize((rw, rh), Image.Resampling.BILINEAR),
                         _threshold_lut(96, dark=False, peak=255))
    out = Image.new("1", (width, height), 0)
    out.paste(resized.convert("1"), ((width - rw) // 2, (height - rh) // 2))
    return out


@lru_cache(maxsize=256)
def _glyph_templates(char: str):
    templates = []
    for font in _template_fonts():
        try:
            bbox = font.getbbox(char)
            image = Image.new("L", (max(12, bbox[2] - bbox[0] + 10),
                                    max(16, bbox[3] - bbox[1] + 10)), 255)
            draw = ImageDraw.Draw(image)
            draw.text((5 - bbox[0], 5 - bbox[1]), char, font=font, fill=0)
            mask = _binary_mask(image)
            box = _bbox(mask)
            if box is None:
                continue
            cropped = _crop_mask(mask, box)
            h, w = len(cropped), len(cropped[0])
            templates.append((_normalized_mask(cropped), w / max(1.0, h)))
        except Exception:
            continue
    return tuple(templates)


def _glyph_score(mask, char):
    box = _bbox(mask)
    if box is None:
        return 9.0
    cropped = _crop_mask(mask, box)
    height, width = len(cropped), len(cropped[0])
    normalized = _normalized_mask(cropped)
    aspect = width / max(1.0, height)
    return _normalized_glyph_score(normalized, aspect, char)


def _normalized_glyph_score(normalized, aspect, char):
    best = 9.0
    for template, template_aspect in _glyph_templates(char):
        histogram = ImageChops.logical_xor(normalized, template).histogram()
        mismatch = histogram[255] / max(1, normalized.width * normalized.height)
        aspect_penalty = 0.12 * abs(math.log(max(1e-3, aspect) / max(1e-3, template_aspect)))
        best = min(best, mismatch + aspect_penalty)
    return best


def _split_wide_component(mask, box):
    x0, y0, x1, y1 = box
    sub = _crop_mask(mask, box)
    height, width = len(sub), len(sub[0])
    if width < height * 1.24:
        return [box]
    count = max(1, min(4, int(round(width / max(1.0, height * 0.84)))))
    if count <= 1:
        return [box]
    projection = _column_sums(sub)
    cuts = []
    previous = 0
    for index in range(1, count):
        target = index * width / count
        radius = max(1, int(width / count * 0.28))
        low = max(previous + 1, int(target) - radius)
        high = min(width - 1, int(target) + radius)
        cut = min(range(low, high + 1), key=lambda column: projection[column]) if high >= low else int(target)
        cuts.append(cut)
        previous = cut
    bounds = [0] + cuts + [width]
    return [(x0 + bounds[i], y0, x0 + bounds[i + 1] - 1, y1)
            for i in range(len(bounds) - 1) if bounds[i + 1] > bounds[i]]


def _numeric_glyph_boxes(mask):
    box = _bbox(mask)
    if box is None:
        return []
    height = box[3] - box[1] + 1
    result = []
    for x0, y0, x1, y1, area in _components(mask):
        component_height, component_width = y1 - y0 + 1, x1 - x0 + 1
        if area <= 1:
            continue
        tiny = (component_height <= max(4, int(height * .36))
                and component_width <= max(5, int(height * .42)))
        if tiny:
            result.append((x0, y0, x1, y1, "punct"))
            continue
        for split in _split_wide_component(mask, (x0, y0, x1, y1)):
            result.append((*split, "digit"))
    return sorted(result, key=lambda item: (item[0], item[1]))


def _classify_digit(mask):
    if not mask or not mask[0]:
        return '?', 0.0
    return _cached_classify_digit(len(mask[0]), len(mask), b''.join(mask))


@lru_cache(maxsize=4096)
def _cached_classify_digit(width, height, pixels):
    mask = [bytearray(pixels[y * width:(y + 1) * width]) for y in range(height)]
    bounds = _bbox(mask)
    if bounds is None:
        return '?', 0.0
    cropped = _crop_mask(mask, bounds)
    normalized = _normalized_mask(cropped)
    aspect = len(cropped[0]) / max(1.0, len(cropped))
    # Topology is useful for distinguishing 0/6/8/9, but it must remain a
    # *soft* hint.  At chart-label sizes antialiasing can close the bowl of a
    # 5 or open the bowl of a 6, and the old hard hole rule then converted an
    # otherwise good glyph into 0/6/9.  Score every digit against the bundled
    # font templates and apply only a small topology penalty.
    holes = _hole_centers(mask)
    hole_count = len(holes)
    candidates = []
    for digit in _NUMERIC_CHARS:
        score = _normalized_glyph_score(normalized, aspect, digit)
        if hole_count >= 2:
            score += 0.0 if digit == "8" else .18
        elif hole_count == 1:
            score += 0.0 if digit in "069" else (.07 if digit == "8" else .15)
            if holes:
                hole_y = holes[0][1]
                if digit == "9" and hole_y > .58:
                    score += .08
                elif digit == "6" and hole_y < .30:
                    score += .08
        elif digit in "0689":
            score += .10
        candidates.append((score, digit))
    candidates.sort()
    if not candidates:
        return "?", 0.0
    score, digit = candidates[0]
    confidence = max(.18, min(.94, 1.0 - score * 1.28))
    return digit, confidence
