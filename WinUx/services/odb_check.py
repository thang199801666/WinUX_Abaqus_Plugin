"""Remote Abaqus ODB history-output inspection helpers.

Check ODB is intentionally history-only and fast.  One result row represents
one RF history output from one Step/History Region.  The RF value is the
signed value at that history's maximum absolute reaction force.  When a
matching displacement history exists in the same History Region, the row also
contains the same-direction U value sampled at the RF governing time.

No node/element inventory and no Field Output/frame scan is performed.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


JSON_BEGIN = "__WINUX_ODB_JSON_BEGIN__"
JSON_END = "__WINUX_ODB_JSON_END__"


ODB_CHECK_SCRIPT = r'''from __future__ import print_function
from odbAccess import openOdb
import json
import math
import os
import re
import sys
import traceback

BEGIN = "__WINUX_ODB_JSON_BEGIN__"
END = "__WINUX_ODB_JSON_END__"


def _as_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _json_value(value):
    scalar = _as_float(value)
    if scalar is not None:
        return scalar
    try:
        return [float(item) for item in value]
    except Exception:
        return str(value)


def _magnitude(value):
    scalar = _as_float(value)
    if scalar is not None:
        return abs(scalar)
    try:
        return math.sqrt(sum(float(item) * float(item) for item in value))
    except Exception:
        return None


def _best_history_item(data):
    best = None
    for item in data or []:
        if not item or len(item) < 2:
            continue
        time_value = _as_float(item[0])
        magnitude = _magnitude(item[1])
        if time_value is None or magnitude is None:
            continue
        if best is None or magnitude > best[0]:
            best = (magnitude, time_value, item[1])
    return best


def _nearest_history_item(data, target_time):
    best = None
    for item in data or []:
        if not item or len(item) < 2:
            continue
        time_value = _as_float(item[0])
        if time_value is None:
            continue
        delta = abs(time_value - target_time)
        if best is None or delta < best[0]:
            best = (delta, time_value, item[1])
    return best


def _rf_direction(name):
    match = re.match(r"^RF([123])(?:$|[^0-9])", str(name or "").upper())
    return match.group(1) if match else None


def _matching_displacement(region, rf_name, target_time):
    """Return the same-direction U history from the same History Region.

    Prefer the exact RF->U name transform so custom history names such as
    RF3_ANTIALIASING pair with U3_ANTIALIASING.  Fall back to U1/U2/U3 for
    normal Abaqus component names.  No field output is inspected.
    """
    outputs = {}
    for name, output in getattr(region, "historyOutputs", {}).items():
        outputs[str(name or "").upper()] = (str(name or ""), output)

    upper_rf = str(rf_name or "").upper()
    direction = _rf_direction(upper_rf)
    candidates = []
    if upper_rf.startswith("RF"):
        candidates.append("U" + upper_rf[2:])
    if direction:
        generic = "U" + direction
        if generic not in candidates:
            candidates.append(generic)
    elif upper_rf == "RF":
        candidates.append("U")

    for candidate in candidates:
        pair = outputs.get(candidate)
        if pair is None:
            continue
        original_name, output = pair
        nearest = _nearest_history_item(
            getattr(output, "data", None), target_time)
        if nearest is None:
            continue
        _delta, sample_time, raw_value = nearest
        return {
            "output": original_name,
            "value": _json_value(raw_value),
            "time": sample_time,
        }
    return None


def inspect_odb(path):
    result = {
        "schemaVersion": 3,
        "odb": os.path.basename(path),
        "path": path,
        "governingReactionForce": None,
        "loadDisplacementRows": [],
    }

    odb = openOdb(path=path, readOnly=True)
    try:
        rows = []
        governing = None

        # One row per RF history output.  Do not collapse equal component names
        # across different Steps/History Regions (node sets/reference points).
        for step_name, step in odb.steps.items():
            for region_name, region in step.historyRegions.items():
                for output_name, output in region.historyOutputs.items():
                    upper = str(output_name or "").upper()
                    if not upper.startswith("RF"):
                        continue
                    best = _best_history_item(getattr(output, "data", None))
                    if best is None:
                        continue
                    absolute_value, time_value, raw_value = best
                    displacement = _matching_displacement(
                        region, output_name, time_value)
                    row = {
                        "rfOutput": str(output_name or ""),
                        "rfValue": _json_value(raw_value),
                        "absoluteValue": absolute_value,
                        "uOutput": displacement.get("output") if displacement else None,
                        "uValue": displacement.get("value") if displacement else None,
                        "step": step_name,
                        "historyRegion": region_name,
                        "time": time_value,
                        "displacementTime": displacement.get("time") if displacement else None,
                        "governing": False,
                    }
                    rows.append(row)
                    if governing is None or absolute_value > governing[0]:
                        governing = (absolute_value, row)

        if governing is not None:
            governing[1]["governing"] = True
            result["governingReactionForce"] = {
                "component": governing[1]["rfOutput"],
                "signedValue": governing[1]["rfValue"],
                "absoluteValue": governing[1]["absoluteValue"],
                "step": governing[1]["step"],
                "historyRegion": governing[1]["historyRegion"],
                "time": governing[1]["time"],
                "uOutput": governing[1]["uOutput"],
                "uValue": governing[1]["uValue"],
            }

        rows.sort(key=lambda row: (
            str(row.get("step", "")),
            str(row.get("historyRegion", "")),
            str(row.get("rfOutput", "")),
        ))
        result["loadDisplacementRows"] = rows
    finally:
        odb.close()
    return result


def main():
    payload = {"error": None}
    try:
        if len(sys.argv) != 2:
            raise RuntimeError("Expected exactly one ODB path")
        payload = inspect_odb(sys.argv[1])
        payload["error"] = None
    except Exception as exc:
        payload = {
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "odb": os.path.basename(sys.argv[1]) if len(sys.argv) > 1 else "",
        }
    print(BEGIN)
    print(json.dumps(payload, sort_keys=True))
    print(END)


if __name__ == "__main__":
    main()
'''



def _unique_commands(values):
    result = []
    seen = set()
    for value in values or ():
        value = str(value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _local_process_command(abaqus_command, script_path, odb_path):
    """Build a platform-correct ``abaqus python`` child command.

    Abaqus launchers on Windows are normally batch files, so they must be
    resolved by ``cmd.exe``.  On POSIX the launcher can be executed directly.
    """
    parts = [
        str(abaqus_command), "python", str(script_path), str(odb_path),
    ]
    if os.name != "nt":
        return parts
    command_line = subprocess.list2cmdline(parts)
    return [
        os.environ.get("COMSPEC") or "cmd.exe",
        "/d", "/s", "/c", command_line,
    ]


def check_local_odb(path, abaqus_commands=None, timeout=600.0):
    """Inspect one local ODB in an isolated Abaqus Python child process.

    The local path never passes through SSH.  Each configured Abaqus launcher
    is tried until one actually starts the checker and emits the WinUx JSON
    payload.  Once a payload is emitted, its ODB error (if any) is authoritative
    and is surfaced rather than silently retrying another Abaqus version.
    """
    path = Path(path).expanduser()
    if path.suffix.casefold() != ".odb":
        raise ValueError("Check ODB requires one .odb file")
    if not path.exists():
        raise RuntimeError("ODB file is not accessible: {}".format(path))
    if not path.is_file():
        raise ValueError("Check ODB requires a file, not a folder")

    commands = _unique_commands(abaqus_commands)
    if not commands:
        commands = ["abaqus"]

    script_path = None
    started = time.monotonic()
    attempts = []
    try:
        fd, script_name = tempfile.mkstemp(
            prefix="winux-check-odb-", suffix=".py")
        script_path = Path(script_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(build_remote_odb_check_script())

        for command in commands:
            process_command = _local_process_command(
                command, script_path, path)
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0
            )
            try:
                completed = subprocess.run(
                    process_command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=max(1.0, float(timeout)),
                    creationflags=creationflags,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    "Local Abaqus ODB check timed out after {:.0f}s".format(
                        max(1.0, float(timeout))))
            except (OSError, ValueError) as exc:
                attempts.append("{} ({})".format(command, exc))
                continue

            output = str(completed.stdout or "")
            error = str(completed.stderr or "")
            combined = "{}\n{}".format(output, error).strip()
            if JSON_BEGIN in combined:
                result = parse_odb_check_output(combined)
                result["abaqusCommand"] = command
                result["analysisSeconds"] = round(
                    max(0.0, time.monotonic() - started), 3)
                try:
                    result["fileSize"] = int(path.stat().st_size)
                except OSError:
                    pass
                result["source"] = "local"
                return result

            detail = (error or output or
                      "exit {}".format(completed.returncode)).strip()
            if detail:
                detail = detail.splitlines()[-1][:180]
            attempts.append("{} ({})".format(
                command, detail or "no WinUx result payload"))

        detail = "; ".join(attempts) if attempts else "no commands were tried"
        raise RuntimeError(
            "No usable local Abaqus Python command could check this ODB. "
            "Tried: {}".format(detail))
    finally:
        if script_path is not None:
            try:
                script_path.unlink()
            except OSError:
                pass


def build_remote_odb_check_script() -> str:
    """Return the Python-2-compatible script uploaded to the Linux server."""
    return ODB_CHECK_SCRIPT


def parse_odb_check_output(output: str) -> dict:
    """Extract and validate the JSON payload from Abaqus stdout."""
    text = str(output or "")
    start = text.rfind(JSON_BEGIN)
    if start < 0:
        raise ValueError("Abaqus ODB checker did not return a WinUx JSON payload")
    start += len(JSON_BEGIN)
    end = text.find(JSON_END, start)
    if end < 0:
        raise ValueError("Abaqus ODB checker returned an incomplete JSON payload")
    payload_text = text[start:end].strip()
    if not payload_text:
        raise ValueError("Abaqus ODB checker returned an empty JSON payload")
    payload = json.loads(payload_text)
    if not isinstance(payload, dict):
        raise ValueError("Abaqus ODB checker returned an invalid payload")
    error = payload.get("error")
    if error:
        raise RuntimeError(str(error))
    return payload


__all__ = [
    "JSON_BEGIN",
    "JSON_END",
    "ODB_CHECK_SCRIPT",
    "build_remote_odb_check_script",
    "check_local_odb",
    "parse_odb_check_output",
]
