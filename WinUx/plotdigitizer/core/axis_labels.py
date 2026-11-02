"""Independent printed-label parsing; no neighbouring values or tick sequences."""
from datetime import datetime, timezone
import math
import re


def parse_axis_label(text):
    """Return (numeric value, notation), preserving years as numeric years.

    Full dates use UTC epoch seconds; times alone use seconds since midnight.
    Exp/e-power labels represent positive exp(n) values, not a different log
    interpolation geometry. No arbitrary locale-dependent date order is guessed.
    """
    text = str(text).strip().replace('−', '-')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?', text):
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp(), 'datetime'
    if re.fullmatch(r'\d{1,2}:\d{2}(?::\d{2})?', text):
        parts = [int(part) for part in text.split(':')]
        hour, minute = parts[:2]
        second = parts[2] if len(parts) == 3 else 0
        if hour > 23 or minute > 59 or second > 59:
            raise ValueError('Invalid clock label.')
        return float(hour * 3600 + minute * 60 + second), 'datetime'
    match = re.fullmatch(r'(exp\(([-+\d.eE]+)\)|e\^([-+\d.eE]+)|10\^([-+\d.eE]+))', text)
    if match:
        exponent = float(next(value for value in match.groups()[1:] if value is not None))
        value = 10 ** exponent if match.group(4) is not None else math.exp(exponent)
        kind = 'log10' if match.group(4) is not None else ('exp' if match.group(2) is not None else 'ln')
    else:
        if ',' in text:
            if not re.fullmatch(r'[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?', text):
                raise ValueError('Invalid thousands grouping.')
            text = text.replace(',', '')
        value, kind = float(text), None
    if not math.isfinite(value):
        raise ValueError('Tick value must be finite.')
    return value, kind


def format_axis_value(value, scale):
    """Format a numeric calibration value for the selected axis scale.

    Date/Time keeps numeric storage for interpolation, but presents calendar
    values to the user. Four-digit year axes intentionally remain plain years
    for backwards compatibility with existing projects.
    """
    from .models import AxisScale
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if scale != AxisScale.DATETIME:
        return "{:.10g}".format(numeric)
    if not math.isfinite(numeric):
        return str(value)
    rounded = round(numeric)
    if abs(numeric - rounded) < 1e-9 and 1500 <= rounded <= 2500:
        return str(int(rounded))
    # Clock-only labels are stored as seconds since midnight. Keep this branch
    # below the year special case and above epoch conversion.
    if 0 <= numeric < 86400:
        seconds = int(round(numeric))
        hour, remainder = divmod(seconds, 3600)
        minute, second = divmod(remainder, 60)
        return f"{hour:02d}:{minute:02d}" if second == 0 else f"{hour:02d}:{minute:02d}:{second:02d}"
    try:
        dt = datetime.fromtimestamp(numeric, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return "{:.10g}".format(numeric)
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return dt.strftime("%Y-%m-%d")
    if dt.second == 0:
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_axis_value_input(text, scale):
    """Parse one editable calibration value using the selected axis scale."""
    from .models import AxisScale
    raw = str(text).strip()
    if scale == AxisScale.DATETIME:
        try:
            value, _kind = parse_axis_label(raw)
            return float(value)
        except (ValueError, OverflowError):
            pass
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError('Tick value must be finite.')
    return value


def _glyph_reading(mask, td):
    bounds = td._bbox(mask)
    if bounds is None:
        return '?', 1.0
    mask = td._crop_mask(mask, bounds)
    height, width = len(mask), len(mask[0])
    digit, confidence = td._classify_digit(mask)
    error = 1.0 - confidence
    holes = [part for part in td._components([bytearray(1 - v for v in row) for row in mask])
             if part[0] > 0 and part[1] > 0 and part[2] < width - 1 and part[3] < height - 1]
    # Strong closed bowls help choose a split through a joined glyph group.
    # This path is restricted to readable 8+ px text and verified as a whole
    # word afterwards; tiny compressed 5/6 labels keep the established OCR path.
    if len(holes) == 1:
        hole = holes[0]
        center_y = (hole[1] + hole[3]) / 2
        if hole[3] - hole[1] + 1 >= height * .5 and hole[4] >= width * height * .15:
            digit, error = '0', .06
        elif digit in '0689' and center_y < height * .4:
            digit, error = '9', min(error, .12)
        elif digit in '0689' and center_y > height * .55:
            digit, error = '6', min(error, .12)
    elif len(holes) == 2 and digit in '0689':
        digit, error = '8', min(error, .09)
    return digit, error


def read_joined_numeric_label(mask):
    """Read touching digits and comma groups using only this word's pixels."""
    from . import tick_detection as td
    bounds = td._bbox(mask)
    if bounds is None:
        return None
    mask = td._crop_mask(mask, bounds)
    if not 8 <= len(mask) <= 22:
        return None
    parts = td._components(mask)
    body = [part for part in parts if part[3] - part[1] + 1 >= len(mask) * .6]
    if not body:
        return None
    height = sorted(part[3] - part[1] + 1 for part in body)[len(body) // 2]
    baseline = max(part[3] for part in body)
    first_digit = min(part[0] for part in body)
    text, total_error, digits = '', 0.0, 0
    clean = [bytearray(row) for row in mask]
    for x0, y0, x1, y1, area in parts:
        width, part_height = x1 - x0 + 1, y1 - y0 + 1
        if part_height < height * .6:
            if y0 >= height * .65:
                text += ',' if y1 > baseline else '.'
            elif width >= height * .2 and part_height <= height * .4:
                if x0 < first_digit:
                    text += '-'
                elif x1 >= len(mask[0]) - 2:
                    for row in clean[y0:y1 + 1]:
                        row[x0:x1 + 1] = bytearray(width)  # Disconnected tick-stroke remnant.
                else:
                    text += '-'
            else:
                return None
            continue
        count = max(1, round(width / (height * .72))) if width > height * 1.1 else 1
        if count > 8:
            return None
        sub = td._crop_mask(mask, (x0, y0, x1, y1))
        beam = [(0.0, '', 0)]
        cache = {}
        for index in range(1, count + 1):
            target = round(width * index / count)
            ends = [width] if index == count else range(max(1, target - 2), min(width - 1, target + 2) + 1)
            alternatives = []
            for cost, token, start in beam:
                for end in ends:
                    if end <= start:
                        continue
                    key = (start, end)
                    if key not in cache:
                        cache[key] = _glyph_reading(td._crop_mask(sub, (start, 0, end - 1, len(sub) - 1)), td)
                    digit, error = cache[key]
                    error += .03 * abs(end - start - width / count) / (width / count)
                    alternatives.append((cost + error, token + digit, end))
            beam = sorted(alternatives)[:6]
            if not beam:
                return None
        cost, token, _ = beam[0]
        text += token
        total_error += cost
        digits += count
    if not digits or total_error / digits > .23:
        return None
    try:
        value, notation = parse_axis_label(text)
    except (ValueError, OverflowError):
        return None
    observed = td._normalize_word_mask(clean)
    variants = [text]
    if notation is None and value >= 1000 and value == int(value):
        variants.append(format(int(value), ','))
    score, text = min((td._normalized_word_template_score(observed, candidate), candidate) for candidate in variants)
    score_limit = .34 if text.isdigit() and len(text) == 4 and total_error / digits <= .16 else .24
    if score > score_limit:
        return None
    return text, value, min(.95, 1 - max(score, total_error / digits) * 1.4)


def independent_formatted_axis(image, rect, axis, scale, words, label_words, cancelled=None):
    """Use independently read grouped numbers/year labels, never sequence repair."""
    from . import tick_detection as td
    usable = [mask for mask, _ in label_words.values() if 8 <= len(mask) <= 22]
    if axis == 'x' and sum(2 <= len(mask[0]) / len(mask) <= 4 for mask in usable) < 4:
        return None
    if axis == 'y':
        comma_words = 0
        for mask in usable:
            parts = td._components(mask)
            body = [p for p in parts if p[3] - p[1] + 1 >= len(mask) * .6]
            if body and any(p[3] > max(b[3] for b in body) and p[3] - p[1] + 1 < len(mask) * .6 for p in parts):
                comma_words += 1
        if comma_words < 2:
            return None
    combined = dict(label_words) if axis == 'x' else dict(words)
    for position, word in label_words.items():
        near = min(combined, key=lambda p: abs(p - position), default=None)
        combined[near if near is not None and abs(near - position) <= 2 else position] = word
    ticks, unread = [], []
    for position, (mask, bbox) in sorted(combined.items()):
        td._check_tick_cancelled(cancelled)
        reading = read_joined_numeric_label(mask)
        if reading is None:
            unread.append(position)
        else:
            text, value, confidence = reading
            ticks.append(td.TickReading(position, value, text, confidence, bbox))
    years = (axis == 'x' and len(ticks) >= 4 and
             all(t.text.isdigit() and len(t.text) == 4 and 1500 <= t.value <= 2500 for t in ticks))
    grouped = sum(',' in tick.text for tick in ticks) >= 2
    if not (years or grouped) or len(ticks) < max(3, math.ceil(len(combined) * .8)):
        return None
    actual_scale = td._observed_axis_scale(ticks, scale)
    if years and scale == td.AxisScale.LINEAR:
        actual_scale = td.AxisScale.DATETIME
    result = td.AxisTickDetection(axis, tuple(ticks), min(t.confidence for t in ticks), actual_scale,
                                  tuple(unread), tuple(sorted(combined)))
    return result if result.ready else None
