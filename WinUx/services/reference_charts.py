"""Named, persistent XY references independent of a job/ODB lifetime."""
from __future__ import annotations

import copy
import ast
import csv
import io
import json
import math
import re
import tokenize
import uuid

from ..preferences.storage import JsonPreferenceStore


def _number(value):
    text = str(value).strip().replace("\u00a0", " ").replace(" ", "")
    # Excel follows the OS locale.  When a rectangular clipboard paste uses
    # TAB separators, decimal-comma cells such as ``1,25`` remain intact.
    # Accept that representation without changing ordinary comma-delimited
    # CSV parsing, which is handled before values reach this function.
    if "," in text and "." not in text and text.count(",") == 1:
        text = text.replace(",", ".")
    value = float(text.replace("D", "E").replace("d", "e"))
    if not math.isfinite(value):
        raise ValueError("X and Y must be finite numbers.")
    return value


def validate_reference(series):
    if not isinstance(series, dict):
        raise ValueError("A reference series must contain a name and XY points.")
    name = str(series.get("name") or "").strip()
    if not name or any(ord(char) < 32 for char in name):
        raise ValueError("Enter a non-empty, single-line series name.")

    formula = str(series.get("formula") or "").strip()
    if formula:
        validate_reference_formula(formula)
        return {
            "id": str(series.get("id") or uuid.uuid4().hex),
            "name": name,
            "points": [],
            "enabled": bool(series.get("enabled", True)),
            "kind": "formula",
            "formula": formula,
        }

    points = []
    for point in series.get("points") or []:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("Each reference point must contain X and Y.")
        points.append([_number(point[0]), _number(point[1])])
    if not points:
        raise ValueError("Reference '{}' has no points.".format(name))
    return {"id": str(series.get("id") or uuid.uuid4().hex), "name": name,
            "points": points, "enabled": bool(series.get("enabled", True)),
            "kind": "xy"}


def reduce_reference_samples(points, max_error_ratio=0.0001):
    """Return an error-bounded subset of an XY reference curve.

    ``max_error_ratio`` is measured in a normalized XY space where each axis
    spans 0..1.  This makes the reduction insensitive to engineering units
    (for example millimetres on X and newtons on Y) while retaining the
    original acquisition order, endpoints, reversals and sharp turns.

    A ratio of ``0`` is lossless with respect to the polyline geometry: only
    duplicate/redundant collinear samples can disappear.  Positive ratios are
    bounded Ramer-Douglas-Peucker simplification; every omitted point remains
    within the requested normalized distance of the replacement segment.
    """
    if isinstance(max_error_ratio, bool):
        raise ValueError("Reduction error must be a finite, non-negative ratio.")
    try:
        max_error_ratio = float(max_error_ratio)
    except (TypeError, ValueError):
        raise ValueError("Reduction error must be a finite, non-negative ratio.") from None
    if not math.isfinite(max_error_ratio) or max_error_ratio < 0:
        raise ValueError("Reduction error must be a finite, non-negative ratio.")

    numeric = []
    for point in points or []:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("Each reference point must contain X and Y.")
        numeric.append([_number(point[0]), _number(point[1])])
    if len(numeric) <= 2:
        return numeric

    xs = [point[0] for point in numeric]
    ys = [point[1] for point in numeric]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_span = x_max - x_min
    y_span = y_max - y_min

    # Degenerate axes are valid (vertical/horizontal curves).  A zero span
    # contributes no normalized distance on that axis rather than dividing by
    # an arbitrary engineering-unit scale.
    normalized = [
        ((point[0] - x_min) / x_span if x_span else 0.0,
         (point[1] - y_min) / y_span if y_span else 0.0)
        for point in numeric
    ]

    def segment_distance(point, first, last):
        dx, dy = last[0] - first[0], last[1] - first[1]
        length_sq = dx * dx + dy * dy
        if length_sq == 0.0:
            return math.hypot(point[0] - first[0], point[1] - first[1])
        projection = ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy) / length_sq
        projection = max(0.0, min(1.0, projection))
        return math.hypot(
            point[0] - (first[0] + projection * dx),
            point[1] - (first[1] + projection * dy))

    # ``0`` means geometrically exact for practical double precision.  Use a
    # machine-scale epsilon so values produced by decimal->binary conversion
    # do not manufacture false curvature on an otherwise straight segment.
    effective_error = max(max_error_ratio, 1.0e-12)

    # Iterative Ramer-Douglas-Peucker. Preserve real reversals explicitly: a
    # later endpoint can otherwise enclose a backtracking path whose samples
    # happen to remain close to the same segment.
    keep = {0, len(normalized) - 1}
    distinct = []
    for index, point in enumerate(normalized):
        if not distinct or point != normalized[distinct[-1]]:
            distinct.append(index)
    for first, middle, last in zip(distinct, distinct[1:], distinct[2:]):
        previous = (normalized[middle][0] - normalized[first][0],
                    normalized[middle][1] - normalized[first][1])
        following = (normalized[last][0] - normalized[middle][0],
                     normalized[last][1] - normalized[middle][1])
        dot = previous[0] * following[0] + previous[1] * following[1]
        cross = previous[0] * following[1] - previous[1] * following[0]
        if dot < 0 or (max_error_ratio == 0 and abs(cross) > 1.0e-12):
            keep.add(middle)

    anchors = sorted(keep)
    pending = list(zip(anchors, anchors[1:]))
    while pending:
        first, last = pending.pop()
        if last - first < 2:
            continue
        furthest, distance = first + 1, -1.0
        for index in range(first + 1, last):
            candidate = segment_distance(
                normalized[index], normalized[first], normalized[last])
            if candidate > distance:
                furthest, distance = index, candidate
        if distance > effective_error:
            keep.add(furthest)
            pending.extend(((first, furthest), (furthest, last)))

    retained = sorted(keep)
    return [numeric[index] for index in retained]


def _table(text, base_name):
    lines = [(index, line.strip()) for index, line in enumerate(text.splitlines(), 1)
             if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise ValueError("Paste at least one row of X/Y data.")
    delimiter = next((value for value in ("\t", ";", ",") if value in lines[0][1]), None)
    rows = [(index, next(csv.reader([line], delimiter=delimiter)) if delimiter
             else re.split(r"\s+", line)) for index, line in lines]
    width = len(rows[0][1])
    if width < 2:
        raise ValueError("Use X in the first column and one or more Y columns.")
    first = rows[0][1]
    try:
        float(first[0].strip().replace("D", "E").replace("d", "e"))
        header = False
    except ValueError:
        header = True
    if header:
        names = [name.strip() for name in first[1:]]
        rows = rows[1:]
    else:
        names = [base_name if width == 2 else "{} {}".format(base_name, i)
                 for i in range(1, width)]
    series = [{"name": name, "points": []} for name in names]
    for line_number, row in rows:
        if len(row) != width:
            raise ValueError("Line {} has {} columns; expected {}.".format(line_number, len(row), width))
        try:
            values = [_number(value) for value in row]
        except (TypeError, ValueError) as exc:
            raise ValueError("Line {}: {}".format(line_number, exc)) from exc
        for item, y in zip(series, values[1:]):
            item["points"].append([values[0], y])
    return [validate_reference(item) for item in series]


def parse_reference_text(text, base_name="Reference"):
    """Read CSV/TSV/whitespace X,Y1,Y2 tables or [Name] XY blocks."""
    text = str(text or "").strip()
    base_name = str(base_name or "Reference").strip()
    sections = list(re.finditer(r"(?m)^\s*\[([^\r\n]+)\]\s*$", text))
    if not sections:
        result = _table(text, base_name)
    else:
        if text[:sections[0].start()].strip():
            raise ValueError("Place each XY block after its [Series name] heading.")
        result = []
        for index, section in enumerate(sections):
            end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
            block = _table(text[section.end():end], section.group(1).strip())
            if len(block) != 1:
                raise ValueError("Each named block must have exactly two columns: X and Y.")
            block[0]["name"] = section.group(1).strip()
            result.append(validate_reference(block[0]))
    names = [item["name"].casefold() for item in result]
    if len(names) != len(set(names)):
        raise ValueError("Give each reference series a unique name.")
    return result


class _ReferenceRowProxy:
    """List-like two-cell row backed by a lazy ReferenceTableModel."""

    __slots__ = ("_model", "_row")

    def __init__(self, model, row):
        self._model = model
        self._row = int(row)

    def __len__(self):
        return 2

    def __iter__(self):
        yield from self._model.row_text(self._row)

    def __getitem__(self, column):
        if isinstance(column, slice):
            return list(self)[column]
        column = int(column)
        if column < 0:
            column += 2
        if column not in (0, 1):
            raise IndexError(column)
        return self._model.cell_text(self._row, column)

    def __setitem__(self, column, value):
        column = int(column)
        if column < 0:
            column += 2
        if column not in (0, 1):
            raise IndexError(column)
        self._model.set_cell_text(self._row, column, value)

    def __eq__(self, other):
        try:
            return list(self) == list(other)
        except TypeError:
            return False

    def __repr__(self):
        return repr(list(self))


class _ReferenceCells:
    """Compatibility sequence that materializes only rows callers touch."""

    __slots__ = ("_model",)

    def __init__(self, model):
        self._model = model

    def __len__(self):
        return self._model.row_count

    def __iter__(self):
        for row in range(self._model.row_count):
            yield _ReferenceRowProxy(self._model, row)

    def __getitem__(self, row):
        if isinstance(row, slice):
            start, stop, step = row.indices(self._model.row_count)
            return [list(_ReferenceRowProxy(self._model, index))
                    for index in range(start, stop, step)]
        row = int(row)
        if row < 0:
            row += self._model.row_count
        if not 0 <= row < self._model.row_count:
            raise IndexError(row)
        return _ReferenceRowProxy(self._model, row)

    def __setitem__(self, row, values):
        row = int(row)
        if row < 0:
            row += self._model.row_count
        if not 0 <= row < self._model.row_count:
            raise IndexError(row)
        values = list(values)
        if len(values) != 2:
            raise ValueError("Reference rows contain exactly X and Y.")
        self._model.set_row_text(row, values)

    def __eq__(self, other):
        try:
            return [list(row) for row in self] == [list(row) for row in other]
        except TypeError:
            return False

    def __repr__(self):
        return repr([list(row) for row in self])


class ReferenceTableModel:
    """Two-column Excel-friendly worksheet used to create one reference chart.

    Saved XY data is attached lazily. Loading a 100k-row reference therefore
    records one read-only points sequence and materializes text only for rows
    that are actually displayed/edited. This keeps dialog activation bounded by
    the visible worksheet page rather than total dataset size.
    """

    COLUMN_COUNT = 2

    def __init__(self, rows=20, pairs=None):
        self._row_count = max(1, int(rows or 1))
        self._source_points = None
        self._source_count = 0
        self._overrides = {}
        self.cells = _ReferenceCells(self)

    @property
    def pair_count(self):
        return 1

    @property
    def row_count(self):
        return self._row_count

    def ensure_size(self, rows, pairs=1):
        if pairs not in (None, 1):
            raise ValueError("Reference input supports one X/Y pair at a time.")
        self._row_count = max(self._row_count, int(rows))

    @staticmethod
    def _format_value(value):
        if value is None or value == "":
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        try:
            return "{:.17g}".format(float(value))
        except (TypeError, ValueError):
            return str(value)

    def cell_text(self, row, column):
        row, column = int(row), int(column)
        if not (0 <= row < self._row_count and 0 <= column < self.COLUMN_COUNT):
            return ""
        override = self._overrides.get(row)
        if override is not None:
            return override[column]
        if self._source_points is not None and row < self._source_count:
            point = self._source_points[row]
            try:
                return self._format_value(point[column])
            except (IndexError, TypeError):
                return ""
        return ""

    def row_text(self, row):
        row = int(row)
        if not 0 <= row < self._row_count:
            return ["", ""]
        override = self._overrides.get(row)
        if override is not None:
            return list(override)
        if self._source_points is not None and row < self._source_count:
            try:
                point = self._source_points[row]
                return [self._format_value(point[0]), self._format_value(point[1])]
            except (IndexError, TypeError):
                return ["", ""]
        return ["", ""]

    def _ensure_override(self, row):
        row = int(row)
        current = self._overrides.get(row)
        if current is None:
            current = self.row_text(row)
            self._overrides[row] = current
        return current

    def set_cell_text(self, row, column, value):
        row, column = int(row), int(column)
        if row < 0 or column not in (0, 1):
            return False
        self.ensure_size(row + 1)
        text = str(value or "").strip()
        current = self.cell_text(row, column)
        if current == text:
            return False
        self._ensure_override(row)[column] = text
        return True

    def set_row_text(self, row, values):
        row = int(row)
        values = [str(value or "").strip() for value in list(values)[:2]]
        if len(values) < 2:
            values.extend([""] * (2 - len(values)))
        self.ensure_size(row + 1)
        if self.row_text(row) == values:
            return False
        self._overrides[row] = values
        return True

    def has_data(self):
        if self._source_count:
            overridden_source_rows = sum(
                1 for row in self._overrides if row < self._source_count)
            if overridden_source_rows < self._source_count:
                return True
        # Only sparse overrides can contain data outside/over a fully cleared
        # borrowed source, so never scan an untouched 100k-row backing array.
        return any(str(value).strip()
                   for values in self._overrides.values()
                   for value in values)

    @staticmethod
    def _read_clipboard_rows(text):
        text = str(text or "").strip("\r\n")
        if not text:
            return []
        delimiter = next((value for value in ("\t", ";", ",") if value in text), None)
        try:
            rows = list(csv.reader(text.splitlines(), delimiter=delimiter)) if delimiter else [
                re.split(r"\s+", line.strip()) if line.strip() else [""]
                for line in text.splitlines()]
        except csv.Error as exc:
            raise ValueError("Could not read clipboard table: {}".format(exc)) from exc
        normalized = []
        for values in rows:
            values = [str(value or "").strip() for value in values]
            while len(values) > 1 and not values[-1]:
                values.pop()
            normalized.append(values)
        return normalized

    @staticmethod
    def _is_number_text(value):
        try:
            _number(value)
            return True
        except (TypeError, ValueError):
            return False

    @classmethod
    def _strip_header(cls, rows, column):
        if not rows:
            return rows
        first = rows[0]
        expected = ("X", "Y")[column:column + len(first)]
        labels = tuple(str(value).strip().casefold() for value in first)
        if labels == tuple(value.casefold() for value in expected):
            return rows[1:]
        if len(rows) > 1 and first and all(not cls._is_number_text(value) for value in first):
            next_row = rows[1]
            if next_row and all(cls._is_number_text(value) for value in next_row):
                return rows[1:]
        return rows

    def paste(self, text, row=0, column=0):
        if row < 0 or column < 0 or column >= self.COLUMN_COUNT:
            raise ValueError("Choose an X or Y data cell to paste into.")
        rows = self._strip_header(self._read_clipboard_rows(text), column)
        if not rows:
            return 0
        width = max((len(values) for values in rows), default=0)
        if not width:
            return 0
        if column + width > self.COLUMN_COUNT:
            raise ValueError("Reference Chart accepts only two columns: X and Y.")
        self.ensure_size(row + len(rows))
        for offset, values in enumerate(rows):
            for index, value in enumerate(values):
                self.set_cell_text(row + offset, column + index, value)
        return len(rows)

    def load_series(self, series):
        items = list(series or [])
        if len(items) > 1:
            raise ValueError("Edit one reference chart at a time.")
        item = items[0] if items else None
        points = (item.get("points") or []) if item else []
        # Borrow the validated points sequence read-only. Edits are stored in
        # sparse row overrides and save/serialization creates independent data.
        self._source_points = points
        self._source_count = len(points)
        self._row_count = max(20, self._source_count)
        self._overrides.clear()

    def to_points(self):
        points = []
        for index in range(self._row_count):
            override = self._overrides.get(index)
            if override is None and self._source_points is not None and index < self._source_count:
                point = self._source_points[index]
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise ValueError("Row {}: X and Y must both have a value.".format(index + 1))
                try:
                    points.append([_number(point[0]), _number(point[1])])
                except ValueError as exc:
                    raise ValueError("Row {}: {}".format(index + 1, exc)) from exc
                continue
            x, y = [str(value or "").strip() for value in self.row_text(index)]
            if not x and not y:
                continue
            if not x or not y:
                raise ValueError("Row {}: X and Y must both have a value.".format(index + 1))
            try:
                points.append([_number(x), _number(y)])
            except ValueError as exc:
                raise ValueError("Row {}: {}".format(index + 1, exc)) from exc
        if not points:
            raise ValueError("Enter X/Y data for the chart.")
        return points

    def to_series(self, name="Reference"):
        return [validate_reference({"name": name, "points": self.to_points()})]

    def clear(self):
        self._source_points = None
        self._source_count = 0
        self._overrides.clear()

    def clear_row(self, row):
        if 0 <= row < self._row_count:
            self._overrides[int(row)] = ["", ""]

    def clear_cell(self, row, column):
        if 0 <= row < self._row_count and 0 <= column < self.COLUMN_COUNT:
            self.set_cell_text(row, column, "")

    def clipboard_text(self):
        last = 0
        rows = []
        for index in range(self._row_count):
            row = self.row_text(index)
            rows.append(row)
            if any(str(value).strip() for value in row):
                last = index + 1
        return "\n".join("\t".join(map(str, row))
                         for row in [["X", "Y"], *rows[:last]])


# ---------------------------------------------------------------------------
# Reference formula engine
# ---------------------------------------------------------------------------

class _FormulaExpr:
    def __init__(self, kind, value, args=None):
        self.kind = kind
        self.value = value
        self.args = list(args or [])


def _formula_top_level(text):
    """Lex separators without treating regex groups/classes as arithmetic."""
    depth = 0
    quote = None
    character_class = False
    quantifier_end = -1
    escaped = False
    for index, char in enumerate(text):
        if index <= quantifier_end:
            continue
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if quote == "/" and char == "[":
                character_class = True
            elif quote == "/" and char == "]":
                character_class = False
            elif char == quote and not character_class:
                quote = None
            continue
        if character_class:
            if char == "]":
                character_class = False
            continue
        if char == "[":
            character_class = True
            continue
        if char == "{":
            quantifier = re.match(r"\{\d+(?:,\d*)?\}", text[index:])
            if quantifier is not None:
                quantifier_end = index + len(quantifier.group()) - 1
                continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == "/":
            previous = text[:index].rstrip()
            if (not previous or previous[-1] in "(,+-*/%") and re.search(r"(?<!\\)/", text[index + 1:]):
                quote = char
                continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Unexpected ')' in formula.")
        elif depth == 0:
            yield index, char
    if quote:
        raise ValueError("Unterminated quoted selector in formula.")
    if depth != 0:
        raise ValueError("Unbalanced parentheses in formula.")
    if character_class:
        raise ValueError("Unterminated regex character class in formula.")


def _formula_split_args(text):
    args, start = [], 0
    for index, char in _formula_top_level(text):
        if char == ",":
            args.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail or args:
        args.append(tail)
    return args


def _parse_legacy_formula_expr(text):
    text = str(text or "").strip()
    if not text:
        raise ValueError("Enter a formula.")
    try:
        return _FormulaExpr("number", float(text))
    except ValueError:
        pass
    tokens = list(_formula_top_level(text))
    numeric_expression = bool(re.fullmatch(r"[\d.eE+\-*/%()\s]+", text))
    # Unquoted selectors are regular expressions. Require spaces around binary
    # operators so .*, RF[1-3], A+B and other existing regexes keep their meaning.
    for operators in ("+-", "*/%"):
        for index, char in reversed(tokens):
            if char not in operators or index == 0 or index == len(text) - 1:
                continue
            previous = text[:index].rstrip()
            if not previous:
                continue
            percentage_operand = False
            if previous.endswith("%"):
                try:
                    float(previous[:-1])
                    percentage_operand = True
                except ValueError:
                    pass
            if previous[-1] in "+-*/%" and not percentage_operand and (
                    numeric_expression or len(previous) == 1 or previous[-2].isspace()):
                continue
            if numeric_expression and char in "+-" and text[index - 1] in "eE":
                continue
            spaced = text[index - 1].isspace() and text[index + 1].isspace()
            if spaced or numeric_expression:
                return _FormulaExpr("binary", char, [
                    _parse_legacy_formula_expr(text[:index]), _parse_legacy_formula_expr(text[index + 1:])])
    if text[0] in "+-":
        return _FormulaExpr("unary", text[0], [_parse_legacy_formula_expr(text[1:])])
    # Numeric percentage literals are useful for scaling, e.g. 50% * regex.
    if text.endswith("%"):
        try:
            return _FormulaExpr("number", float(text[:-1]) / 100.0)
        except ValueError:
            pass
    if text[0] in ("'", '"', "/") and text[-1] == text[0] and not tokens:
        return _FormulaExpr("selector", text[1:-1])
    if text.startswith("(") and text.endswith(")") and not tokens:
        inner = _parse_legacy_formula_expr(text[1:-1])
        if inner.kind != "selector":
            return inner

    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)
    if match and text.endswith(")"):
        name = match.group(1).lower()
        open_index = text.find("(", match.start(1) + len(match.group(1)))
        body = text[open_index + 1:-1]
        return _FormulaExpr("call", name, [_parse_legacy_formula_expr(arg) for arg in _formula_split_args(body)])
    return _FormulaExpr("selector", text)


_FORMULA_MATH = {
    'abs': abs, 'negate': lambda value: -value, 'sqrt': math.sqrt,
    'square': lambda value: value * value, 'sin': math.sin, 'cos': math.cos,
    'tan': math.tan, 'asin': math.asin, 'acos': math.acos, 'atan': math.atan,
    'sinh': math.sinh, 'cosh': math.cosh, 'tanh': math.tanh,
    'exp': math.exp, 'ln': math.log, 'log': math.log, 'log10': math.log10,
}
_FORMULA_FUNCTIONS = set(_FORMULA_MATH) | {
    'combine', 'add', 'subtract', 'multiply', 'divide', 'average',
    'magnitude', 'scale', 'offset',
}


def _uses_explicit_regex(text):
    previous = None
    try:
        for token in tokenize.generate_tokens(io.StringIO(str(text)).readline):
            if previous == (tokenize.NAME, 'regex') and token.string == '(':
                return True
            if token.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT):
                previous = (token.type, token.string)
    except (tokenize.TokenError, IndentationError):
        pass
    return False


def _parse_explicit_formula(text):
    """Parse Python/Abaqus-style arithmetic with explicitly delimited regexes.

    Whitelisted AST only: never eval, attribute access, indexing or Python code.
    Strings are Python string literals, including raw strings for backslashes.
    """
    text = str(text or '').strip()
    if not text:
        raise ValueError('Enter a formula.')
    if len(text) > 16384:
        raise ValueError('Formula is too long (maximum 16384 characters).')
    try:
        tree = ast.parse(text, mode='eval')
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ValueError('Invalid formula. Use regex("pattern") for names and ordinary + - * / ** expressions.') from exc
    if sum(1 for _ in ast.walk(tree)) > 512:
        raise ValueError('Formula is too complex.')
    operators = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/', ast.Mod: '%', ast.Pow: '**'}

    def convert(node, depth=0):
        if depth > 64:
            raise ValueError('Formula nesting is too deep.')
        child = lambda value: convert(value, depth + 1)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            try:
                value = float(node.value)
            except OverflowError as exc:
                raise ValueError('Formula numbers must be finite.') from exc
            if not math.isfinite(value):
                raise ValueError('Formula numbers must be finite.')
            return _FormulaExpr('number', value)
        if isinstance(node, ast.Name) and node.id in ('pi', 'e'):
            return _FormulaExpr('number', getattr(math, node.id))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return _FormulaExpr('unary', '+' if isinstance(node.op, ast.UAdd) else '-', [child(node.operand)])
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return _FormulaExpr('binary', operators[type(node.op)], [child(node.left), child(node.right)])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name == 'regex':
                if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                    raise ValueError('Use regex("pattern") with one quoted pattern.')
                pattern = node.args[0].value
                try:
                    re.compile(pattern, re.IGNORECASE)
                except (re.error, RecursionError) as exc:
                    raise ValueError('Invalid regex: {}'.format(exc)) from exc
                if any(ord(char) < 32 and char not in '\n\t\r' for char in pattern):
                    raise ValueError('Use a raw string for regex backslashes, e.g. regex(r"\\bU3\\b").')
                return _FormulaExpr('selector', pattern)
            if name in ('pow', 'power'):
                if len(node.args) != 2:
                    raise ValueError('{}() expects 2 arguments.'.format(name))
                return _FormulaExpr('binary', '**', [child(arg) for arg in node.args])
            if name not in _FORMULA_FUNCTIONS:
                raise ValueError("Unknown formula function '{}'.".format(name))
            count = len(node.args)
            required = 1 if name in _FORMULA_MATH else 2
            if count < required or (name in set(_FORMULA_MATH) | {'combine', 'scale', 'offset'} and count != required):
                raise ValueError('{}() expects {} argument(s).'.format(name, required))
            return _FormulaExpr('call', name, [child(arg) for arg in node.args])
        raise ValueError('Select names with regex("pattern"). Only numbers, supported functions and + - * / ** % are allowed.')
    return convert(tree.body)


def _parse_formula_expr(text):
    return _parse_explicit_formula(text) if _uses_explicit_regex(text) else _parse_legacy_formula_expr(text)


def normalize_reference_formula(formula, *, canonical=False):
    """Convert saved legacy selectors to explicit regex() without evaluating data."""
    if _uses_explicit_regex(formula) and not canonical:
        return str(formula).strip()
    expr = _parse_formula_expr(formula)
    def render(node):
        if node.kind == 'selector':
            # Slash delimiters in old generated rules escaped '/', which is
            # not special in a Python regex. Canonical comparison may remove
            # that redundant escape, but must preserve paired backslashes.
            pattern = re.sub(r'(?<!\\)((?:\\\\)*)\\/', r'\1/', node.value) if canonical else node.value
            return 'regex({})'.format(json.dumps(pattern, ensure_ascii=False))
        if node.kind == 'number':
            return repr(float(node.value))
        if node.kind == 'unary':
            return render(node.args[0]) if node.value == '+' else '-({})'.format(render(node.args[0]))
        if node.kind == 'binary':
            return '({} {} {})'.format(render(node.args[0]), node.value, render(node.args[1]))
        return '{}({})'.format(node.value, ', '.join(render(arg) for arg in node.args))
    return render(expr)


def _formula_source_name(row):
    return str(row.get("displayName") or row.get("name") or row.get("output") or row.get("id") or "History Output")


_UR_RF_COMPONENT = re.compile(r"(?<![A-Za-z0-9_])(RF|U)([123])((?:_[A-Za-z0-9]+)*)(?![A-Za-z0-9_])", re.IGNORECASE)


def _reference_component(row):
    output = str(row.get("output") or "").strip()
    # Structured Abaqus output names are authoritative. A description merely
    # mentioning U3 must not turn an energy/UR/custom output into displacement.
    match = (_UR_RF_COMPONENT.fullmatch(output) if output else
             _UR_RF_COMPONENT.search(_formula_source_name(row)))
    if match is None:
        return None
    return match.group(1).upper(), int(match.group(2)), match.group(3).upper()


def _reference_context(row):
    context = row.get("historyRegion") or row.get("regionDescription")
    if not context:
        label = _formula_source_name(row)
        match = _UR_RF_COMPONENT.search(label)
        context = label[match.end():].strip(" :;,") if match is not None else ""
    return " ".join(str(context or "").split()).casefold()


def _formula_selector_text(row, pattern):
    text = "\n".join(str(row.get(key) or "") for key in
                     ("displayName", "name", "output", "historyRegion", "id"))
    # Generated selectors explicitly request these reserved metadata lines.
    # Keep the original haystack/anchor semantics for every existing formula.
    if "@reference-" in pattern:
        component = _reference_component(row)
        output = "{}{}{}".format(*component) if component is not None else ""
        step = " ".join(str(row.get("step") or "").split()).casefold()
        text += "\n@reference-output={}\n@reference-step={}\n@reference-region={}".format(
            output, step, _reference_context(row))
    return text


def _formula_pattern_matches(row, pattern, regex, explicit=False):
    if explicit and '@reference-' not in pattern:
        # regex("^U3$") must match a name, not a concatenation padded with
        # empty metadata lines. Legacy rules keep their historical haystack.
        return any(regex.search(str(row.get(key))) for key in
                   ('displayName', 'name', 'output', 'historyRegion', 'id') if row.get(key))
    return regex.search(_formula_selector_text(row, pattern))


def _selector_curves(pattern, history_outputs, *, explicit=False):
    try:
        regex = re.compile(str(pattern or ""), re.IGNORECASE)
    except re.error as exc:
        raise ValueError("Invalid regex '{}': {}".format(pattern, exc)) from exc
    matched, available = [], []
    for row in history_outputs or []:
        name = _formula_source_name(row)
        if _formula_pattern_matches(row, str(pattern or ''), regex, explicit):
            matched.append(name)
            points = []
            for point in row.get("points") or []:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                try:
                    x, y = float(point[0]), float(point[1])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(x) and math.isfinite(y):
                    points.append([x, y])
            if points:
                available.append({"name": name, "points": points})
    if not matched:
        raise ValueError("Regex '{}' did not match any History Output in the current Plot.".format(pattern))
    if not available:
        raise ValueError("Regex '{}' matched History Output(s), but no live data is available yet.".format(pattern))
    return sorted(available, key=lambda item: item["name"].casefold())


def _formula_align(curves):
    if not curves:
        return []
    maps = []
    for curve in curves:
        maps.append({round(float(x), 12): float(y) for x, y in curve["points"]})
    common = set(maps[0])
    for values in maps[1:]:
        common.intersection_update(values)
    return [(x, [values[x] for values in maps]) for x in sorted(common)]


def _formula_curve_groups(values):
    curve_lists = [value for value in values if isinstance(value, list)]
    if not curve_lists:
        return []
    size = max(len(items) for items in curve_lists)
    for items in curve_lists:
        if len(items) not in (1, size):
            raise ValueError("Regex selectors returned incompatible match counts: {}.".format(
                ", ".join(str(len(group)) for group in curve_lists)))
    groups = []
    for index in range(size):
        group = []
        for value in values:
            if isinstance(value, list):
                group.append(value[0 if len(value) == 1 else index])
            else:
                group.append(value)
        groups.append(group)
    return groups


def _formula_name(function, curves):
    names = [item["name"] for item in curves if isinstance(item, dict)]
    if function == "combine" and len(names) >= 2:
        return "{} vs {}".format(names[1], names[0])
    return "{}({})".format(function, ", ".join(names))


def _evaluate_formula_expr(expr, history_outputs, *, strict=False):
    if expr.kind == "number":
        return float(expr.value)
    if expr.kind == "selector":
        return _selector_curves(expr.value, history_outputs, explicit=strict)
    if expr.kind == "unary":
        value = _evaluate_formula_expr(expr.args[0], history_outputs, strict=strict)
        factor = -1 if expr.value == "-" else 1
        if not isinstance(value, list):
            return factor * value
        return [{"name": "{}({})".format(expr.value, curve["name"]),
                 "points": [[x, factor * y] for x, y in curve["points"]]} for curve in value]
    if expr.kind == "binary":
        values = [_evaluate_formula_expr(arg, history_outputs, strict=strict) for arg in expr.args]

        def operation(a, b):
            if expr.value == "+": return a + b
            if expr.value == "-": return a - b
            if expr.value == "*": return a * b
            if expr.value == "/": return a / b
            if expr.value == "%": return a % b
            if expr.value == "**": return math.pow(a, b)
            raise AssertionError(expr.value)

        if not any(isinstance(value, list) for value in values):
            try:
                result = operation(*values)
            except (ZeroDivisionError, ValueError, OverflowError) as exc:
                raise ValueError("Invalid arithmetic domain, overflow or division by zero in formula.") from exc
            if not math.isfinite(result):
                raise ValueError("Arithmetic expression produced a non-finite value.")
            return result
        result = []
        for group in _formula_curve_groups(values):
            curves = [item for item in group if isinstance(item, dict)]
            aligned = _formula_align(curves)
            if not aligned:
                raise ValueError("Matched History Outputs do not share common sample times.")
            points = []
            for x, ys in aligned:
                samples = iter(ys)
                operands = [next(samples) if isinstance(item, dict) else item for item in group]
                try:
                    out = operation(*operands)
                except (ZeroDivisionError, ValueError, OverflowError) as exc:
                    if strict:
                        raise ValueError('Invalid arithmetic domain, overflow or division by zero in formula.') from exc
                    continue  # Same sample-skipping policy as divide().
                if strict and not math.isfinite(out):
                    raise ValueError('Arithmetic expression produced a non-finite value.')
                if math.isfinite(out):
                    points.append([x, out])
            if not points:
                raise ValueError("Arithmetic expression produced no finite points.")
            names = [item["name"] if isinstance(item, dict) else "{:g}".format(item) for item in group]
            result.append({"name": "({} {} {})".format(names[0], expr.value, names[1]), "points": points})
        return result

    fn = expr.value
    aliases = {"sum": "add", "sub": "subtract", "mul": "multiply",
               "div": "divide", "avg": "average", "mean": "average",
               "mag": "magnitude", "neg": "negate"}
    fn = aliases.get(fn, fn)
    supported = _FORMULA_FUNCTIONS
    if fn not in supported:
        raise ValueError("Unknown formula function '{}'.".format(expr.value))
    values = [_evaluate_formula_expr(arg, history_outputs, strict=strict) for arg in expr.args]

    if fn in _FORMULA_MATH:
        if len(values) != 1:
            raise ValueError("{}() expects one expression.".format(fn))
    elif fn in {"scale", "offset"}:
        if len(values) != 2 or not isinstance(values[0], list) or isinstance(values[1], list):
            raise ValueError("{}() expects (series, number).".format(fn))
    elif fn == "combine":
        if len(values) != 2 or not all(isinstance(value, list) for value in values):
            raise ValueError("combine() expects two regex/series expressions.")
    else:
        if len(values) < 2 or not all(isinstance(value, list) for value in values):
            raise ValueError("{}() expects two or more History Output expressions.".format(fn))

    if fn in _FORMULA_MATH:
        operation = _FORMULA_MATH[fn]
        if not isinstance(values[0], list):
            try:
                out = operation(values[0])
            except (ValueError, OverflowError, ZeroDivisionError) as exc:
                raise ValueError('Invalid domain or overflow in {}().'.format(fn)) from exc
            if not math.isfinite(out):
                raise ValueError('Non-finite result in {}().'.format(fn))
            return out
        result = []
        for curve in values[0]:
            points = []
            for x, y in curve["points"]:
                try:
                    out = operation(y)
                except (ValueError, OverflowError, ZeroDivisionError) as exc:
                    if strict:
                        raise ValueError('Invalid domain or overflow in {}().'.format(fn)) from exc
                    continue
                if strict and not math.isfinite(out):
                    raise ValueError('Non-finite result in {}().'.format(fn))
                if math.isfinite(out):
                    points.append([x, out])
            result.append({"name": "{}({})".format(fn, curve["name"]), "points": points})
        return result

    if fn in {"scale", "offset"}:
        factor = float(values[1])
        result = []
        for curve in values[0]:
            points = [[x, y * factor if fn == "scale" else y + factor]
                      for x, y in curve["points"]]
            result.append({"name": "{}({}, {:g})".format(fn, curve["name"], factor), "points": points})
        return result

    result = []
    for group in _formula_curve_groups(values):
        curves = [item for item in group if isinstance(item, dict)]
        aligned = _formula_align(curves)
        if not aligned:
            raise ValueError("Matched History Outputs do not share common sample times.")
        points = []
        for x, ys in aligned:
            if fn == "combine":
                points.append([ys[0], ys[1]])
                continue
            if fn == "add": out = sum(ys)
            elif fn == "subtract": out = ys[0] - sum(ys[1:])
            elif fn == "multiply": out = math.prod(ys)
            elif fn == "divide":
                out = ys[0]
                zero = False
                for value in ys[1:]:
                    if value == 0:
                        zero = True
                        break
                    out /= value
                if zero:
                    if strict:
                        raise ValueError('Division by zero in formula.')
                    continue
            elif fn == "average": out = sum(ys) / len(ys)
            elif fn == "magnitude": out = math.sqrt(sum(value * value for value in ys))
            else: raise AssertionError(fn)
            if strict and not math.isfinite(out):
                raise ValueError("Formula '{}' produced a non-finite value.".format(fn))
            if math.isfinite(out):
                points.append([x, out])
        if not points:
            raise ValueError("Formula '{}' produced no finite points.".format(fn))
        result.append({"name": _formula_name(fn, curves), "points": points})
    return result


def validate_reference_formula(formula, *, explicit_regex=False):
    """Validate formula syntax without requiring any current History Output."""
    explicit = explicit_regex or _uses_explicit_regex(formula)
    expr = _parse_explicit_formula(formula) if explicit else _parse_formula_expr(formula)
    if expr.kind not in {"call", "binary", "unary"} and not (explicit and expr.kind == 'selector'):
        raise ValueError(
            "Use a function, signed selector or arithmetic expression, for example "
            'combine(regex(".*U3.*"), -regex(".*RF3.*")).')
    allowed = _FORMULA_FUNCTIONS
    selectors = []

    def visit(node):
        if node.kind == 'selector':
            selectors.append(node)
        if node.kind == "call":
            if str(node.value).casefold() not in allowed:
                raise ValueError("Unknown formula function '{}'.".format(node.value))
        for child in node.args:
            visit(child)
    visit(expr)
    if explicit and not selectors:
        raise ValueError('Use at least one regex("pattern") History Output selector.')
    return True


def resolve_reference_formula_ids(formula, history_outputs):
    """Return exact History Output ids referenced by regex selectors.

    Resolution needs only the catalog metadata; live point data is not required.
    """
    validate_reference_formula(formula)
    expr = _parse_formula_expr(formula)
    selectors = []

    def collect(node):
        if node.kind == "selector":
            selectors.append(str(node.value or ""))
        else:
            for child in node.args:
                collect(child)
    collect(expr)

    ids = []
    explicit = _uses_explicit_regex(formula)
    for selector in selectors:
        pattern = re.compile(selector, re.IGNORECASE)
        for row in history_outputs or []:
            if _formula_pattern_matches(row, selector, pattern, explicit):
                item_id = str(row.get("id") or "")
                if item_id and item_id not in ids:
                    ids.append(item_id)
    return ids


def make_formula_reference(formula, name=None, enabled=True, *, explicit_regex=False):
    """Create a persistent regex/formula rule without evaluating Plot data."""
    validate_reference_formula(formula, explicit_regex=explicit_regex)
    formula = str(formula).strip()
    label = str(name or "").strip() or formula
    return validate_reference({
        "name": label,
        "formula": formula,
        "enabled": enabled,
    })


def generate_reference_ur_rf(history_outputs=None, *, directions=(1, 2, 3),
                             antialiasing=True, reverse_u=False, reverse_rf=True):
    """Generate same-direction U/RF rules, scoped per Plot step/history region.

    Catalog metadata is sufficient; point data need not be loaded yet. Without
    a catalog, return portable component-regex templates instead of inventing
    node identities. Never zip unrelated regions or broadcast a missing pair.
    """
    if isinstance(directions, (str, int)):
        directions = (directions,)
    try:
        axes = tuple(dict.fromkeys(int(axis) for axis in directions))
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose direction 1, 2 or 3.") from exc
    if not axes or any(axis not in (1, 2, 3) for axis in axes):
        raise ValueError("Choose direction 1, 2 or 3.")
    rows = list(history_outputs or [])

    def rule(axis, suffix, step="", region="", *, scoped=False):
        def selector(component, reverse):
            variable = "{}{}{}".format(component, axis, suffix)
            if scoped:
                pattern = (r"(?m)^@reference-output=" + re.escape(variable) + r"$"
                           + r"(?=[\s\S]*^@reference-step=" + re.escape(step) + r"$)"
                           + r"(?=[\s\S]*^@reference-region=" + re.escape(region) + r"$)")
            else:
                pattern = r".*\b" + re.escape(variable) + r"\b.*"
            return ("-" if reverse else "") + 'regex({})'.format(json.dumps(pattern, ensure_ascii=False))

        formula = "combine({}, {})".format(selector("U", reverse_u), selector("RF", reverse_rf))
        name = "U{}-RF{}{}".format(axis, axis, suffix)
        if region:
            name += " | " + region
        if step:
            name += " | " + step
        return make_formula_reference(formula, name)

    if not rows:
        suffix = "_ANTIALIASING" if antialiasing else ""
        return [rule(axis, suffix) for axis in axes]

    groups = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        component = _reference_component(row)
        if component is None:
            continue
        kind, axis, suffix = component
        filtered = "ANTIALIASING" in suffix.split("_")
        if axis not in axes or (antialiasing and not filtered) or (not antialiasing and suffix):
            continue
        step = " ".join(str(row.get("step") or "").split()).casefold()
        region = _reference_context(row)
        group = groups.setdefault((axis, suffix, step, region), {"U": {}, "RF": {}})
        identity = str(row.get("id") or "") or id(row)
        group[kind][identity] = row

    generated = []
    for (axis, suffix, step, region), pair in sorted(groups.items()):
        if not pair["U"] or not pair["RF"]:
            continue
        if len(pair["U"]) != 1 or len(pair["RF"]) != 1:
            raise ValueError("Ambiguous U{0}/RF{0} pair in the same step/region; more than one matching output exists.".format(axis))
        generated.append(rule(axis, suffix, step, region, scoped=True))
    if not generated:
        raise ValueError("No same-direction U/RF {}pair found in the same step and history region.".format(
            "ANTIALIASING " if antialiasing else "unfiltered "))
    return generated


def evaluate_reference_formula(formula, history_outputs):
    """Evaluate a regex formula against the current Plot History Output data.

    Selectors are Python regular expressions matched against display name, output,
    history region and id.  No Python ``eval`` is used.  The result is a list of
    validated reference-series dictionaries ready for the Reference Chart library.
    """
    expr = _parse_formula_expr(formula)
    if expr.kind not in {"call", "binary", "unary"} and not (_uses_explicit_regex(formula) and expr.kind == 'selector'):
        raise ValueError('Use regex("pattern") in a formula, for example combine(regex(".*U3.*"), -regex(".*RF3.*")).')
    curves = _evaluate_formula_expr(expr, history_outputs, strict=_uses_explicit_regex(formula))
    if not isinstance(curves, list):
        raise ValueError("A reference formula must use at least one History Output expression.")
    return [validate_reference(curve) for curve in curves]


class ReferenceChartLibrary:
    """Atomic profile storage plus UI-thread change notifications."""

    def __init__(self, root=None):
        self.store = JsonPreferenceStore("reference_charts.json", root=root)
        self._listeners = []
        self._series = []
        self._revision = 0
        data = self.store.load().get("series", [])
        if isinstance(data, list):
            seen_ids, seen_names = set(), set()
            for raw in data:
                try:
                    item = validate_reference(raw)
                except (TypeError, ValueError, OverflowError):
                    continue
                if item["id"] in seen_ids or item["name"].casefold() in seen_names:
                    continue
                self._series.append(item)
                seen_ids.add(item["id"])
                seen_names.add(item["name"].casefold())

    @property
    def revision(self):
        return self._revision

    def snapshot(self):
        """Return a fully detached public snapshot.

        This preserves the historical mutation-safety contract for callers that
        may modify nested point arrays. UI editors that use copy-on-write should
        prefer ``editor_snapshot`` to avoid cloning very large XY datasets.
        """
        return copy.deepcopy(self._series)

    def editor_snapshot(self):
        """Return metadata copies that borrow validated XY arrays read-only.

        The Reference Chart worksheet never mutates borrowed point arrays; it
        stores edits in sparse overrides and emits fresh arrays on commit. This
        makes dialog activation O(series + visible rows) instead of O(points).
        """
        result = []
        for raw in self._series:
            item = dict(raw)
            item["points"] = raw.get("points") or []
            result.append(item)
        return result

    def subscribe(self, callback):
        self._listeners.append(callback)

    def unsubscribe(self, callback):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def replace(self, series):
        validated = [validate_reference(item) for item in series]
        ids = [item["id"] for item in validated]
        names = [item["name"].casefold() for item in validated]
        if len(ids) != len(set(ids)) or len(names) != len(set(names)):
            raise ValueError("Reference series IDs and names must be unique.")
        # Publish only after persistence succeeds: a failed write must not
        # pretend references will survive an app restart.
        self.store.save({"schema_version": 1, "series": validated})
        self._series = validated
        self._revision += 1
        for callback in tuple(self._listeners):
            callback()

    def set_enabled(self, series_id, enabled):
        series = self.snapshot()
        item = next((item for item in series if item["id"] == series_id), None)
        if item is None:
            raise ValueError("Reference series no longer exists.")
        if item["enabled"] != bool(enabled):
            item["enabled"] = bool(enabled)
            self.replace(series)
