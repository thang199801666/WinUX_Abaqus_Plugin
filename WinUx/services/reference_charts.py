"""Named, persistent XY references independent of a job/ODB lifetime."""
from __future__ import annotations

import copy
import csv
import math
import re
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


def _formula_split_args(text):
    args, start, depth = [], 0, 0
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Unexpected ')' in formula.")
        elif char == "," and depth == 0:
            args.append(text[start:index].strip())
            start = index + 1
    if quote:
        raise ValueError("Unterminated quoted selector in formula.")
    if depth != 0:
        raise ValueError("Unbalanced parentheses in formula.")
    tail = text[start:].strip()
    if tail or args:
        args.append(tail)
    return args


def _parse_formula_expr(text):
    text = str(text or "").strip()
    if not text:
        raise ValueError("Enter a formula.")
    try:
        return _FormulaExpr("number", float(text))
    except ValueError:
        pass
    if ((text.startswith('"') and text.endswith('"')) or
            (text.startswith("'") and text.endswith("'"))):
        return _FormulaExpr("selector", text[1:-1])
    if text.startswith("/") and text.endswith("/") and len(text) >= 2:
        return _FormulaExpr("selector", text[1:-1])

    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)
    if match and text.endswith(")"):
        name = match.group(1).lower()
        open_index = text.find("(", match.start(1) + len(match.group(1)))
        body = text[open_index + 1:-1]
        return _FormulaExpr("call", name, [_parse_formula_expr(arg) for arg in _formula_split_args(body)])
    return _FormulaExpr("selector", text)


def _formula_source_name(row):
    return str(row.get("displayName") or row.get("name") or row.get("output") or row.get("id") or "History Output")


def _selector_curves(pattern, history_outputs):
    try:
        regex = re.compile(str(pattern or ""), re.IGNORECASE)
    except re.error as exc:
        raise ValueError("Invalid regex '{}': {}".format(pattern, exc)) from exc
    matched, available = [], []
    for row in history_outputs or []:
        name = _formula_source_name(row)
        haystack = "\n".join(str(row.get(key) or "") for key in
                             ("displayName", "name", "output", "historyRegion", "id"))
        if regex.search(haystack):
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


def _evaluate_formula_expr(expr, history_outputs):
    if expr.kind == "number":
        return float(expr.value)
    if expr.kind == "selector":
        return _selector_curves(expr.value, history_outputs)

    fn = expr.value
    aliases = {"sum": "add", "sub": "subtract", "mul": "multiply",
               "div": "divide", "avg": "average", "mean": "average",
               "mag": "magnitude", "neg": "negate"}
    fn = aliases.get(fn, fn)
    supported = {"combine", "add", "subtract", "multiply", "divide",
                 "average", "magnitude", "abs", "negate", "sqrt",
                 "square", "scale", "offset"}
    if fn not in supported:
        raise ValueError("Unknown formula function '{}'.".format(expr.value))
    values = [_evaluate_formula_expr(arg, history_outputs) for arg in expr.args]

    if fn in {"abs", "negate", "sqrt", "square"}:
        if len(values) != 1 or not isinstance(values[0], list):
            raise ValueError("{}() expects one History Output expression.".format(fn))
    elif fn in {"scale", "offset"}:
        if len(values) != 2 or not isinstance(values[0], list) or isinstance(values[1], list):
            raise ValueError("{}() expects (series, number).".format(fn))
    elif fn == "combine":
        if len(values) != 2 or not all(isinstance(value, list) for value in values):
            raise ValueError("combine() expects two regex/series expressions.")
    else:
        if len(values) < 2 or not all(isinstance(value, list) for value in values):
            raise ValueError("{}() expects two or more History Output expressions.".format(fn))

    if fn in {"abs", "negate", "sqrt", "square"}:
        result = []
        for curve in values[0]:
            points = []
            for x, y in curve["points"]:
                if fn == "abs": out = abs(y)
                elif fn == "negate": out = -y
                elif fn == "sqrt":
                    if y < 0: continue
                    out = math.sqrt(y)
                else: out = y * y
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
                if zero: continue
            elif fn == "average": out = sum(ys) / len(ys)
            elif fn == "magnitude": out = math.sqrt(sum(value * value for value in ys))
            else: raise AssertionError(fn)
            if math.isfinite(out):
                points.append([x, out])
        if not points:
            raise ValueError("Formula '{}' produced no finite points.".format(fn))
        result.append({"name": _formula_name(fn, curves), "points": points})
    return result


def validate_reference_formula(formula):
    """Validate formula syntax without requiring any current History Output."""
    expr = _parse_formula_expr(formula)
    if expr.kind != "call":
        raise ValueError(
            "A formula must start with a function, for example "
            "combine(.*U1, .*RF1).")
    allowed = {
        "combine", "add", "subtract", "multiply", "divide", "average",
        "magnitude", "abs", "negate", "sqrt", "square", "scale", "offset",
    }

    def visit(node):
        if node.kind == "call":
            if str(node.value).casefold() not in allowed:
                raise ValueError("Unknown formula function '{}'.".format(node.value))
            for child in node.args:
                visit(child)
    visit(expr)
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
        elif node.kind == "call":
            for child in node.args:
                collect(child)
    collect(expr)

    ids = []
    for selector in selectors:
        pattern = re.compile(selector, re.IGNORECASE)
        for row in history_outputs or []:
            if pattern.search(_formula_source_name(row)):
                item_id = str(row.get("id") or "")
                if item_id and item_id not in ids:
                    ids.append(item_id)
    return ids


def make_formula_reference(formula, name=None, enabled=True):
    """Create a persistent regex/formula rule without evaluating Plot data."""
    validate_reference_formula(formula)
    formula = str(formula).strip()
    label = str(name or "").strip() or formula
    return validate_reference({
        "name": label,
        "formula": formula,
        "enabled": enabled,
    })


def evaluate_reference_formula(formula, history_outputs):
    """Evaluate a regex formula against the current Plot History Output data.

    Selectors are Python regular expressions matched against display name, output,
    history region and id.  No Python ``eval`` is used.  The result is a list of
    validated reference-series dictionaries ready for the Reference Chart library.
    """
    expr = _parse_formula_expr(formula)
    if expr.kind != "call":
        raise ValueError("A formula must start with a function, for example combine(.*U1, .*RF1).")
    curves = _evaluate_formula_expr(expr, history_outputs)
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
