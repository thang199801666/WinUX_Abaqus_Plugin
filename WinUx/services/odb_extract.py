"""Selective remote ODB History Output extraction and Abaqus-style combine.

The remote side has two modes:

* ``catalog`` reads only History Output metadata so the selection dialog opens
  quickly even for a large ODB.
* ``extract`` reads data only for the History Output entries explicitly chosen
  by the user.

The client-side combine operation mirrors Abaqus/CAE's ``combine(X,X)`` idea:
input histories are aligned on their independent coordinate (normally time),
then the first history's Y value becomes the combined X coordinate and the
second history's Y value becomes the combined Y coordinate.
"""

from __future__ import annotations

import json
import math
import re


JSON_BEGIN = "__WINUX_ODB_EXTRACT_JSON_BEGIN__"
JSON_END = "__WINUX_ODB_EXTRACT_JSON_END__"


ODB_EXTRACT_SCRIPT = r'''from __future__ import print_function
from odbAccess import openOdb
import json
import os
import re
import sys
import traceback

BEGIN = "__WINUX_ODB_EXTRACT_JSON_BEGIN__"
END = "__WINUX_ODB_EXTRACT_JSON_END__"


def _scalar(value):
    try:
        return float(value)
    except Exception:
        return None



def _clean_region_description(value):
    text = str(value or "").strip()
    prefixes = (
        "History Region for ",
        "History region for ",
    )
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text


def _history_region_context(region_name, region_description):
    """Return an Abaqus/CAE-like point context for one history region."""
    region_name = str(region_name or "").strip()
    region_description = _clean_region_description(region_description)
    upper_name = region_name.upper()
    upper_description = region_description.upper()

    if upper_name in ("ASSEMBLY ASSEMBLY", "ASSEMBLY", "WHOLE MODEL"):
        return "for Whole Model"
    if "WHOLE MODEL" in upper_description:
        return "for Whole Model"

    # If odbAccess already exposes the rich point description, preserve it.
    # This commonly carries NSET information that cannot be reconstructed from
    # the history-region dictionary key alone.
    if ("PI:" in region_description or
            " IN NSET " in (" " + upper_description + " ")):
        return region_description

    # Raw odbAccess node-region keys usually look like
    # ``Node INSTANCE-NAME.2595``.  Format that the same way Abaqus/CAE labels
    # History Output variables in its Variables dialog.
    match = re.match(r"^Node\s+(.+)\.(\d+)$", region_name, re.I)
    if match:
        instance_name = match.group(1).strip()
        node_label = match.group(2)
        context = "PI: %s Node %s" % (instance_name, node_label)
        # Some Abaqus versions keep the set name only in the description.
        nset_match = re.search(
            r"\bin\s+NSET\s+([^,;]+)$", region_description, re.I)
        if nset_match:
            context += " in NSET " + nset_match.group(1).strip()
        return context

    return region_description or region_name


def _history_display_name(output_name, description, region_name, region_description):
    """Build the same style of label Abaqus/CAE shows in History Output."""
    output_name = str(output_name or "").strip()
    description = str(description or "").strip()

    # Some Abaqus releases return only ``Reaction force (FILTERED)`` while
    # others already include ``: RF2_ANTIALIASING``.  Never duplicate the raw
    # variable name when it is already present in the description.
    if output_name and output_name.lower() in description.lower():
        label = description
    elif description and output_name:
        label = "%s: %s" % (description, output_name)
    else:
        label = description or output_name

    context = _history_region_context(region_name, region_description)
    if context:
        if context.lower() == "for whole model":
            if "whole model" not in label.lower():
                label += " for Whole Model"
        elif context.lower() not in label.lower():
            label += " " + context
    return label.strip()


def _catalog(odb, path):
    rows = []
    index = 0
    for step_name, step in odb.steps.items():
        for region_name, region in step.historyRegions.items():
            region_description = str(getattr(region, "description", "") or "")
            for output_name, output in region.historyOutputs.items():
                description = str(getattr(output, "description", "") or "")
                display_name = _history_display_name(
                    output_name, description, region_name, region_description)
                try:
                    points = len(getattr(output, "data", None) or [])
                except Exception:
                    points = 0
                item_id = "H%06d" % index
                index += 1
                rows.append({
                    "id": item_id,
                    "step": str(step_name),
                    "historyRegion": str(region_name),
                    "regionDescription": region_description,
                    "output": str(output_name),
                    "description": description,
                    "displayName": display_name,
                    "points": int(points),
                })
    return {
        "schemaVersion": 1,
        "mode": "catalog",
        "odb": os.path.basename(path),
        "path": path,
        "historyOutputs": rows,
    }


def _extract(odb, path, request_path):
    with open(request_path, "r") as stream:
        request = json.load(stream)
    requested = request.get("items") or []
    series = []
    for item in requested:
        step_name = str(item.get("step") or "")
        region_name = str(item.get("historyRegion") or "")
        output_name = str(item.get("output") or "")
        item_id = str(item.get("id") or "")
        try:
            step = odb.steps[step_name]
            region = step.historyRegions[region_name]
            output = region.historyOutputs[output_name]
        except Exception:
            series.append({
                "id": item_id,
                "step": step_name,
                "historyRegion": region_name,
                "output": output_name,
                "description": str(item.get("description") or ""),
                "displayName": str(item.get("displayName") or output_name),
                "points": [],
                "error": "History Output is no longer available",
            })
            continue

        points = []
        skipped = 0
        for pair in getattr(output, "data", None) or []:
            if not pair or len(pair) < 2:
                skipped += 1
                continue
            x_value = _scalar(pair[0])
            y_value = _scalar(pair[1])
            if x_value is None or y_value is None:
                skipped += 1
                continue
            points.append([x_value, y_value])
        series.append({
            "id": item_id,
            "step": step_name,
            "historyRegion": region_name,
            "output": output_name,
            "description": str(getattr(output, "description", "") or item.get("description") or ""),
            "displayName": str(item.get("displayName") or output_name),
            "points": points,
            "skipped": skipped,
            "error": None,
        })

    return {
        "schemaVersion": 1,
        "mode": "extract",
        "odb": os.path.basename(path),
        "path": path,
        "series": series,
    }


def main():
    try:
        if len(sys.argv) < 3:
            raise RuntimeError("Expected mode and ODB path")
        mode = str(sys.argv[1]).strip().lower()
        path = sys.argv[2]
        request_path = sys.argv[3] if len(sys.argv) > 3 else None
        odb = openOdb(path=path, readOnly=True)
        try:
            if mode == "catalog":
                payload = _catalog(odb, path)
            elif mode == "extract":
                if not request_path:
                    raise RuntimeError("Extract mode requires a request file")
                payload = _extract(odb, path, request_path)
            else:
                raise RuntimeError("Unsupported ODB extract mode: %s" % mode)
        finally:
            odb.close()
        payload["error"] = None
    except Exception as exc:
        payload = {
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    print(BEGIN)
    print(json.dumps(payload, sort_keys=True))
    print(END)


if __name__ == "__main__":
    main()
'''


def build_remote_odb_extract_script() -> str:
    return ODB_EXTRACT_SCRIPT


def parse_odb_extract_output(output: str) -> dict:
    text = str(output or "")
    start = text.rfind(JSON_BEGIN)
    if start < 0:
        raise ValueError("Abaqus ODB extractor did not return a WinUx JSON payload")
    start += len(JSON_BEGIN)
    end = text.find(JSON_END, start)
    if end < 0:
        raise ValueError("Abaqus ODB extractor returned an incomplete JSON payload")
    payload_text = text[start:end].strip()
    if not payload_text:
        raise ValueError("Abaqus ODB extractor returned an empty JSON payload")
    payload = json.loads(payload_text)
    if not isinstance(payload, dict):
        raise ValueError("Abaqus ODB extractor returned an invalid payload")
    if payload.get("error"):
        raise RuntimeError(str(payload.get("error")))
    return payload


def _clean_points(points):
    """Return sorted unique finite ``(independent, value)`` pairs."""
    cleaned = []
    for pair in points or []:
        if not pair or len(pair) < 2:
            continue
        try:
            x_value = float(pair[0])
            y_value = float(pair[1])
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(x_value) and math.isfinite(y_value)):
            continue
        cleaned.append((x_value, y_value))
    cleaned.sort(key=lambda item: item[0])
    # Abaqus histories should have monotonically increasing independent data,
    # but restarted/custom outputs can repeat a time. Keep the newest value for
    # an exact duplicate so interpolation remains deterministic.
    unique = []
    for item in cleaned:
        if unique and item[0] == unique[-1][0]:
            unique[-1] = item
        else:
            unique.append(item)
    return unique


def _aligned_values(points, coordinates):
    """Align one series to sorted coordinates in linear time."""
    if not points:
        return [None] * len(coordinates)
    if len(points) == 1:
        return [points[0][1]] * len(coordinates)
    result = []
    right = 1
    for coordinate in coordinates:
        if coordinate <= points[0][0]:
            result.append(points[0][1])
            continue
        if coordinate >= points[-1][0]:
            result.append(points[-1][1])
            continue
        while right < len(points) and points[right][0] < coordinate:
            right += 1
        if right < len(points) and points[right][0] == coordinate:
            result.append(points[right][1])
            continue
        left = max(0, right - 1)
        x0, y0 = points[left]
        x1, y1 = points[right]
        if x1 == x0:
            result.append(y1)
        else:
            ratio = (coordinate - x0) / (x1 - x0)
            result.append(y0 + (y1 - y0) * ratio)
    return result


def combine_xy_series(x_series, y_series, reverse="As is"):
    """Combine two history series into one X/Y curve.

    The union of both histories' independent coordinates is used for alignment.
    The first series' dependent value becomes result X and the second series'
    dependent value becomes result Y.  Reverse options multiply the requested
    result axis by -1 without changing the independent/time coordinate used for
    alignment.
    """
    x_points = _clean_points((x_series or {}).get("points"))
    y_points = _clean_points((y_series or {}).get("points"))
    if not x_points or not y_points:
        return []
    coordinates = sorted(set(
        [item[0] for item in x_points] + [item[0] for item in y_points]
    ))
    mode = str(reverse or "As is").strip().casefold()
    reverse_x = mode in {"reverse x", "reversex", "reverse both", "reverseboth"}
    reverse_y = mode in {"reverse y", "reversey", "reverse both", "reverseboth"}
    x_values = _aligned_values(x_points, coordinates)
    y_values = _aligned_values(y_points, coordinates)
    result = []
    for x_value, y_value in zip(x_values, y_values):
        if x_value is None or y_value is None:
            continue
        if reverse_x:
            x_value = -x_value
        if reverse_y:
            y_value = -y_value
        result.append([x_value, y_value])
    return result


def build_combined_curves(extracted, selection):
    """Build Cartesian X×Y combinations in the user's selection order."""
    series_by_id = {
        str(item.get("id")): item
        for item in (extracted or {}).get("series", [])
        if item.get("id") is not None
    }
    x_items = list((selection or {}).get("x") or [])
    y_items = list((selection or {}).get("y") or [])
    reverse = str((selection or {}).get("reverse") or "As is")
    curves = []
    for x_index, x_item in enumerate(x_items, 1):
        x_id = str(x_item.get("id") or "")
        x_series = series_by_id.get(x_id)
        if not x_series:
            continue
        for y_index, y_item in enumerate(y_items, 1):
            y_id = str(y_item.get("id") or "")
            y_series = series_by_id.get(y_id)
            if not y_series:
                continue
            points = combine_xy_series(x_series, y_series, reverse=reverse)
            curves.append({
                "name": "X{}:Y{}".format(x_index, y_index),
                "x": dict(x_item),
                "y": dict(y_item),
                "reverse": reverse,
                "points": points,
                "pointCount": len(points),
            })
    return {
        "schemaVersion": 1,
        "odb": (extracted or {}).get("odb", ""),
        "path": (extracted or {}).get("path", ""),
        "reverse": reverse,
        "curves": curves,
    }


__all__ = [
    "JSON_BEGIN", "JSON_END", "ODB_EXTRACT_SCRIPT",
    "build_remote_odb_extract_script", "parse_odb_extract_output",
    "combine_xy_series", "build_combined_curves",
]
