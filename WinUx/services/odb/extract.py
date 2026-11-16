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
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path


JSON_BEGIN = "__WINUX_ODB_EXTRACT_JSON_BEGIN__"
JSON_END = "__WINUX_ODB_EXTRACT_JSON_END__"
CATALOG_CACHE_MAX_POINTS = 20000
CATALOG_CACHE_MAX_POINTS_PER_SERIES = 2500


ODB_BUSY_WAIT_TIMEOUT_SECONDS = 1800.0
ODB_BUSY_POLL_SECONDS = 2.0
ODB_BUSY_STABLE_POLLS = 2
ODB_BUSY_RECENT_SECONDS = 6.0

# Only these errors are eligible for the "ODB is still being written" wait
# path.  A lock file or a recent mtime alone is not enough: version mismatch,
# launcher errors, parser failures, permissions, etc. must fail/fallback
# immediately instead of sitting in Loading for minutes.
ODB_BUSY_ERROR_MARKERS = (
    "being updated",
    "currently being updated",
    "database is locked",
    "odb is locked",
    "file is locked",
    "sharing violation",
    "used by another process",
    "in use by another process",
    "resource temporarily unavailable",
    "temporarily unavailable",
    "database is busy",
    "odb is busy",
)

# Compatibility failures must be classified before filesystem activity.  Abaqus
# error text differs slightly across releases/platforms, so keep the signatures
# intentionally broad but specific to ODB release/upgrade semantics.
ODB_VERSION_ERROR_MARKERS = (
    "more recent release of abaqus",
    "newer release of abaqus",
    "newer version of abaqus",
    "created by a newer release",
    "created by a later release",
    "upgrade is required",
    "upgrade required",
    "isupgraderequiredforodb",
    "odb upgrade",
    "database must be upgraded",
    "incompatible odb",
    "incompatible database",
    "incompatible release",
    "incompatible abaqus release",
)

ODB_CORRUPT_ERROR_MARKERS = (
    "corrupt",
    "invalid odb",
    "invalid database",
    "not a valid odb",
    "unexpected end of file",
    "truncated",
)

ODB_FAILURE_BUSY = "busy"
ODB_FAILURE_VERSION = "version_mismatch"
ODB_FAILURE_CORRUPT = "corrupt"
ODB_FAILURE_UNKNOWN = "unknown"


def _odb_error_text(error, traceback_text=""):
    return "{}\n{}".format(error or "", traceback_text or "").casefold()


def odb_error_indicates_busy(error, traceback_text=""):
    text = _odb_error_text(error, traceback_text)
    return any(marker in text for marker in ODB_BUSY_ERROR_MARKERS)


def odb_error_indicates_version_mismatch(error, traceback_text=""):
    text = _odb_error_text(error, traceback_text)
    return any(marker in text for marker in ODB_VERSION_ERROR_MARKERS)


def classify_odb_open_failure(error, traceback_text="", *,
                              known_compatible=False, processing_hint=False):
    """Classify an ODB open/read failure without conflating busy and version.

    Evidence order is deliberate:
    1. Explicit release/upgrade signatures always mean VERSION_MISMATCH, even
       when a stale ``.lck`` exists or the file was touched recently.
    2. Explicit lock/busy signatures mean BUSY only while filesystem activity
       also says the ODB is live.
    3. A launcher that already opened this exact ODB in the current WinUx
       session is strong compatibility evidence.  If that same launcher later
       fails while the ODB is actively changing, classify it as BUSY even when
       Abaqus returns a generic open/read error.
    4. Stable corruption signatures are CORRUPT; everything else is UNKNOWN.
    """
    if odb_error_indicates_version_mismatch(error, traceback_text):
        return ODB_FAILURE_VERSION
    if processing_hint and odb_error_indicates_busy(error, traceback_text):
        return ODB_FAILURE_BUSY
    if processing_hint and known_compatible:
        return ODB_FAILURE_BUSY
    text = _odb_error_text(error, traceback_text)
    if any(marker in text for marker in ODB_CORRUPT_ERROR_MARKERS):
        return ODB_FAILURE_CORRUPT
    return ODB_FAILURE_UNKNOWN


def _local_odb_lock_paths(path):
    path = Path(path)
    return (path.with_suffix(".lck"), Path(str(path) + ".lck"))


def _local_odb_snapshot(path):
    path = Path(path)
    stat_result = path.stat()
    return (int(stat_result.st_size), int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1e9))))


def _local_odb_processing_hint(path):
    path = Path(path)
    for lock_path in _local_odb_lock_paths(path):
        try:
            if lock_path.exists():
                return True
        except OSError:
            pass
    try:
        stat_result = path.stat()
        return (time.time() - float(stat_result.st_mtime)) <= ODB_BUSY_RECENT_SECONDS
    except OSError:
        return False


def _wait_for_local_odb_ready(path, timeout=None, poll=None, stable_polls=None):
    path = Path(path)
    timeout = ODB_BUSY_WAIT_TIMEOUT_SECONDS if timeout is None else max(0.0, float(timeout))
    poll = ODB_BUSY_POLL_SECONDS if poll is None else max(0.2, float(poll))
    stable_polls = ODB_BUSY_STABLE_POLLS if stable_polls is None else max(1, int(stable_polls))
    deadline = time.monotonic() + timeout
    previous = None
    stable = 0
    waited = False
    while True:
        locked = False
        for lock_path in _local_odb_lock_paths(path):
            try:
                if lock_path.exists():
                    locked = True
                    break
            except OSError:
                pass
        try:
            current = _local_odb_snapshot(path)
        except OSError:
            current = None
        changed = previous is not None and current is not None and current != previous
        # A stale .lck must not hold the UI in Loading forever.  Treat a lock
        # as active only while the ODB itself still shows recent write activity.
        recent = False
        try:
            stat_result = path.stat()
            recent = (time.time() - float(stat_result.st_mtime)) <= ODB_BUSY_RECENT_SECONDS
        except OSError:
            pass
        active_lock = bool(locked and (changed or recent))
        if not active_lock and current is not None and not changed:
            stable += 1
        else:
            stable = 0
        if stable >= stable_polls:
            return waited
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "ODB is still being updated by Abaqus after {:.0f}s: {}".format(timeout, path))
        waited = True
        previous = current
        time.sleep(poll)

# Session-only accelerator for local ODB tools.  Once one Abaqus launcher has
# successfully opened a local ODB, try it first for subsequent local catalog/
# extract calls.  This is intentionally process-memory only and is never
# persisted to preferences.
_LOCAL_LAST_GOOD_ABAQUS_COMMAND = None
# Exact ODB-path -> launcher compatibility evidence for this WinUx process.
# Unlike the global launcher accelerator, this cache is authoritative only for
# the same ODB path and is therefore safe to use when distinguishing a busy
# database from a version mismatch.
_LOCAL_ODB_COMPAT_COMMANDS = {}


ODB_EXTRACT_SCRIPT = r'''from __future__ import print_function
from odbAccess import openOdb
import json
import os
import re
import sys
import time
import traceback

BEGIN = "__WINUX_ODB_EXTRACT_JSON_BEGIN__"
END = "__WINUX_ODB_EXTRACT_JSON_END__"
CACHE_MAX_POINTS = 20000
CACHE_MAX_POINTS_PER_SERIES = 2500


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


def _catalog(odb, path, cache_points=True):
    rows = []
    index = 0
    cache_remaining = CACHE_MAX_POINTS
    cached_series = 0
    cached_points_total = 0
    for step_name, step in odb.steps.items():
        for region_name, region in step.historyRegions.items():
            region_description = str(getattr(region, "description", "") or "")
            for output_name, output in region.historyOutputs.items():
                description = str(getattr(output, "description", "") or "")
                display_name = _history_display_name(
                    output_name, description, region_name, region_description)
                try:
                    data = getattr(output, "data", None) or []
                    points = len(data)
                except Exception:
                    data = []
                    points = 0
                item_id = "H%06d" % index
                index += 1
                row = {
                    "id": item_id,
                    "step": str(step_name),
                    "historyRegion": str(region_name),
                    "regionDescription": region_description,
                    "output": str(output_name),
                    "description": description,
                    "displayName": display_name,
                    "points": int(points),
                }
                # Small-history fast path.  The catalog already touches the
                # HistoryOutput object to obtain its point count.  For compact
                # histories, cache the actual numeric pairs in the same Abaqus
                # process so a later Extract click can combine locally instead
                # of launching Abaqus/openOdb a second time.  The strict global
                # and per-series budgets keep large ODB catalogs lightweight.
                if (cache_points and points > 0 and
                        points <= CACHE_MAX_POINTS_PER_SERIES and
                        points <= cache_remaining):
                    cached = []
                    valid = True
                    try:
                        for pair in data:
                            if not pair or len(pair) < 2:
                                valid = False
                                break
                            x_value = _scalar(pair[0])
                            y_value = _scalar(pair[1])
                            if x_value is None or y_value is None:
                                valid = False
                                break
                            cached.append([x_value, y_value])
                    except Exception:
                        valid = False
                    if valid and len(cached) == points:
                        row["cachedPoints"] = cached
                        cache_remaining -= points
                        cached_series += 1
                        cached_points_total += points
                rows.append(row)
    return {
        "schemaVersion": 1,
        "mode": "catalog",
        "odb": os.path.basename(path),
        "path": path,
        "historyOutputs": rows,
        "cachedSeries": cached_series,
        "cachedPoints": cached_points_total,
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
        open_started = time.time()
        odb = openOdb(path=path, readOnly=True)
        open_seconds = max(0.0, time.time() - open_started)
        work_started = time.time()
        try:
            if mode == "catalog":
                payload = _catalog(odb, path, cache_points=True)
            elif mode in ("catalog-fast", "catalog_fast"):
                # Local UI fast path: keep point counts for display but avoid
                # converting every numeric pair into JSON before publishing
                # the catalog.  Numeric data is read only for user-selected
                # histories during Extract.
                payload = _catalog(odb, path, cache_points=False)
                payload["mode"] = "catalog"
                payload["fastCatalog"] = True
            elif mode == "extract":
                if not request_path:
                    raise RuntimeError("Extract mode requires a request file")
                payload = _extract(odb, path, request_path)
            else:
                raise RuntimeError("Unsupported ODB extract mode: %s" % mode)
        finally:
            odb.close()
        payload["openOdbSeconds"] = round(open_seconds, 4)
        payload["readSeconds"] = round(max(0.0, time.time() - work_started), 4)
        payload["error"] = None
    except Exception as exc:
        payload = {
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    print(BEGIN)
    print(json.dumps(payload, separators=(",", ":")))
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


def _local_extract_process_command(abaqus_command, script_path, mode, odb_path, request_path=None):
    parts = [str(abaqus_command), "python", str(script_path), str(mode), str(odb_path)]
    if request_path is not None:
        parts.append(str(request_path))
    if os.name != "nt":
        return parts
    command_line = subprocess.list2cmdline(parts)
    return [os.environ.get("COMSPEC") or "cmd.exe", "/d", "/s", "/c", command_line]


def _run_local_odb_extract_mode(path, mode, *, items=None, abaqus_commands=None,
                                abaqus_command=None, timeout=600.0):
    """Run the shared ODB History helper against a local ODB.

    The payload is intentionally identical to the server implementation so the
    controller/dialog path is transport-agnostic.  A catalog pass records the
    launcher that successfully opened the ODB; extract mode can reuse that
    exact launcher and avoid probing releases again.
    """
    path = Path(path).expanduser()
    if path.suffix.casefold() != ".odb":
        raise ValueError("Extract ODB Data requires one .odb file")
    if not path.exists():
        raise RuntimeError("ODB file is not accessible: {}".format(path))
    if not path.is_file():
        raise ValueError("Extract ODB Data requires a file, not a folder")

    global _LOCAL_LAST_GOOD_ABAQUS_COMMAND
    path_key = os.path.normcase(os.path.abspath(str(path)))
    known_command = str(_LOCAL_ODB_COMPAT_COMMANDS.get(path_key) or "").strip()
    commands = _unique_commands([abaqus_command] if abaqus_command else abaqus_commands)
    if not commands:
        commands = ["abaqus"]
    # Prefer the launcher that already succeeded in this WinUx process.  This
    # avoids repeatedly paying full Abaqus startup cost for incompatible or
    # unavailable releases on every local ODB action.
    cached_command = str(_LOCAL_LAST_GOOD_ABAQUS_COMMAND or "").strip()
    # Exact-path compatibility evidence has precedence over the generic last
    # good launcher.  This matters when multiple Abaqus releases coexist.
    if known_command and known_command in commands and not abaqus_command:
        commands = [known_command] + [cmd for cmd in commands if cmd != known_command]
    elif cached_command and cached_command in commands and not abaqus_command:
        commands = [cached_command] + [cmd for cmd in commands if cmd != cached_command]

    script_path = None
    request_path = None
    attempts = []
    started = time.monotonic()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        fd, script_name = tempfile.mkstemp(prefix="winux-odb-history-", suffix=".py")
        script_path = Path(script_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(build_remote_odb_extract_script())

        if str(mode).strip().lower() == "extract":
            fd, request_name = tempfile.mkstemp(prefix="winux-odb-history-request-", suffix=".json")
            request_path = Path(request_name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump({"items": list(items or [])}, stream, separators=(",", ":"))

        for command in commands:
            waited_for_update = False
            for run_index in range(2):
                process_command = _local_extract_process_command(
                    command, script_path, mode, path, request_path=request_path)
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
                    attempts.append("{} (timed out after {:.0f}s)".format(command, float(timeout)))
                    break
                except (OSError, ValueError) as exc:
                    attempts.append("{} ({})".format(command, exc))
                    break

                combined = "{}\n{}".format(completed.stdout or "", completed.stderr or "").strip()
                if JSON_BEGIN in combined:
                    payload = parse_odb_extract_output(combined, allow_error=True)
                    payload_error = str(payload.get("error") or "").strip()
                    if payload_error:
                        # A compatible ODB can be temporarily unreadable while
                        # Abaqus is updating it.  Only wait when filesystem
                        # activity/lock evidence says the file is still live;
                        # true compatibility/version errors fall through.
                        processing_hint = _local_odb_processing_hint(path)
                        failure_kind = classify_odb_open_failure(
                            payload_error, payload.get("traceback"),
                            known_compatible=(command == known_command),
                            processing_hint=processing_hint)
                        if run_index == 0 and failure_kind == ODB_FAILURE_BUSY:
                            waited_for_update = _wait_for_local_odb_ready(
                                path, timeout=min(ODB_BUSY_WAIT_TIMEOUT_SECONDS, max(1.0, float(timeout))))
                            continue
                        attempts.append("{} [{}] ({})".format(
                            command, failure_kind, payload_error[:180]))
                        # A proven version mismatch should immediately move to
                        # the next launcher. Unknown/corrupt failures do too,
                        # but they are preserved in diagnostics.
                        break
                    _LOCAL_LAST_GOOD_ABAQUS_COMMAND = command
                    _LOCAL_ODB_COMPAT_COMMANDS[path_key] = command
                    payload["abaqusCommand"] = command
                    payload["odbOpenState"] = "ready"
                    payload["analysisSeconds"] = round(max(0.0, time.monotonic() - started), 3)
                    payload["source"] = "local"
                    payload["launcherCacheHit"] = bool(cached_command and command == cached_command)
                    payload["waitedForOdbUpdate"] = bool(waited_for_update)
                    try:
                        payload["fileSize"] = int(path.stat().st_size)
                    except OSError:
                        pass
                    return payload

                detail = (completed.stderr or completed.stdout or
                          "exit {}".format(completed.returncode)).strip()
                processing_hint = _local_odb_processing_hint(path)
                failure_kind = classify_odb_open_failure(
                    detail, "", known_compatible=(command == known_command),
                    processing_hint=processing_hint)
                if run_index == 0 and failure_kind == ODB_FAILURE_BUSY:
                    waited_for_update = _wait_for_local_odb_ready(
                        path, timeout=min(ODB_BUSY_WAIT_TIMEOUT_SECONDS, max(1.0, float(timeout))))
                    continue
                if detail:
                    detail = detail.splitlines()[-1][:180]
                attempts.append("{} [{}] ({})".format(
                    command, failure_kind, detail or "no WinUx result payload"))
                break

        detail = "; ".join(attempts) if attempts else "no commands were tried"
        raise RuntimeError(
            "No usable local Abaqus Python command could read this ODB. Tried: {}".format(detail))
    finally:
        for candidate in (request_path, script_path):
            if candidate is not None:
                try:
                    candidate.unlink()
                except OSError:
                    pass


def list_local_odb_history_outputs(path, abaqus_commands=None, timeout=600.0):
    # Populate the local selection table as soon as metadata + point counts are
    # available.  Do not serialize all numeric History Output values during the
    # catalog pass; Extract reads only the X/Y histories the user actually picks.
    return _run_local_odb_extract_mode(
        path, "catalog-fast", abaqus_commands=abaqus_commands, timeout=timeout)


def extract_local_odb_history_data(path, items, abaqus_commands=None,
                                   abaqus_command=None, timeout=600.0):
    return _run_local_odb_extract_mode(
        path, "extract", items=items, abaqus_commands=abaqus_commands,
        abaqus_command=abaqus_command, timeout=timeout)


def build_remote_odb_extract_script() -> str:
    return ODB_EXTRACT_SCRIPT


def parse_odb_extract_output(output: str, *, allow_error=False) -> dict:
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
    if payload.get("error") and not allow_error:
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


def _combine_clean_points(x_points, y_points, reverse="As is"):
    """Combine already-cleaned histories without sorting them again."""
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


def combine_xy_series(x_series, y_series, reverse="As is"):
    """Combine two history series into one X/Y curve.

    The union of both histories' independent coordinates is used for alignment.
    The first series' dependent value becomes result X and the second series'
    dependent value becomes result Y.  Reverse options multiply the requested
    result axis by -1 without changing the independent/time coordinate used for
    alignment.
    """
    return _combine_clean_points(
        _clean_points((x_series or {}).get("points")),
        _clean_points((y_series or {}).get("points")),
        reverse=reverse,
    )


def build_combined_curves(extracted, selection):
    """Build Cartesian XxY combinations in the user's selection order."""
    series_by_id = {
        str(item.get("id")): item
        for item in (extracted or {}).get("series", [])
        if item.get("id") is not None
    }
    x_items = list((selection or {}).get("x") or [])
    y_items = list((selection or {}).get("y") or [])
    reverse = str((selection or {}).get("reverse") or "As is")
    # Clean/sort every selected history exactly once.  Cartesian XxY
    # combinations used to repeat this O(n log n) work for every pair, which
    # became noticeable when users selected several histories at once.
    cleaned_by_id = {
        key: _clean_points((series or {}).get("points"))
        for key, series in series_by_id.items()
    }
    curves = []
    for x_index, x_item in enumerate(x_items, 1):
        x_id = str(x_item.get("id") or "")
        x_series = series_by_id.get(x_id)
        x_points = cleaned_by_id.get(x_id)
        if not x_series or not x_points:
            continue
        for y_index, y_item in enumerate(y_items, 1):
            y_id = str(y_item.get("id") or "")
            y_series = series_by_id.get(y_id)
            y_points = cleaned_by_id.get(y_id)
            if not y_series or not y_points:
                continue
            points = _combine_clean_points(x_points, y_points, reverse=reverse)
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
    "list_local_odb_history_outputs", "extract_local_odb_history_data",
    "combine_xy_series", "build_combined_curves",
]
