"""Abaqus ODB upgrade inspection and in-place replacement helpers.

The actual Abaqus API writes an upgraded database to a *new* path.  WinUx
therefore upgrades to a sibling temporary file first, then swaps it into the
original pathname only after Abaqus reports success.  This keeps the original
ODB intact when conversion fails.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

JSON_BEGIN = "__WINUX_ODB_UPGRADE_JSON_BEGIN__"
JSON_END = "__WINUX_ODB_UPGRADE_JSON_END__"

# Large ODB upgrades can legitimately take a long time.  They run in the
# analysis worker lane, so a generous bound protects against a permanently
# wedged child without tying the operation to UI responsiveness.
ODB_UPGRADE_TIMEOUT_SECONDS = 24.0 * 60.0 * 60.0
ODB_UPGRADE_CHECK_TIMEOUT_SECONDS = 10.0 * 60.0
ODB_UPGRADE_MAX_WORKERS = 4


ODB_UPGRADE_SCRIPT = r'''from __future__ import print_function
import json
import os
import sys
import uuid
from odbAccess import (
    isUpgradeRequiredForOdb,
    upgradeOdb,
)

JSON_BEGIN = "__WINUX_ODB_UPGRADE_JSON_BEGIN__"
JSON_END = "__WINUX_ODB_UPGRADE_JSON_END__"


def emit(payload):
    print(JSON_BEGIN)
    print(json.dumps(payload, sort_keys=True))
    print(JSON_END)


def cleanup(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def temp_paths(source):
    root, ext = os.path.splitext(source)
    if not ext:
        root = source
    token = uuid.uuid4().hex
    upgraded = root + ".winux-upgrade-" + token + ".odb"
    backup = root + ".winux-backup-" + token + ".odb"
    log_path = os.path.splitext(upgraded)[0] + ".log"
    return upgraded, backup, log_path


def upgraded_copy_path(source):
    root, ext = os.path.splitext(source)
    if not ext:
        root = source
    candidate = root + "_upgraded.odb"
    index = 2
    while os.path.exists(candidate):
        candidate = root + "_upgraded_" + str(index) + ".odb"
        index += 1
    return candidate


def check_one(path):
    row = {
        "path": path,
        "name": os.path.basename(path),
        "requiresUpgrade": False,
        "error": None,
    }
    try:
        row["requiresUpgrade"] = bool(
            isUpgradeRequiredForOdb(upgradeRequiredOdbPath=path))
    except Exception as exc:
        row["error"] = str(exc)
    return row


def upgrade_one(path, overwrite=True):
    row = check_one(path)
    row["status"] = "error" if row.get("error") else "current"
    if row.get("error") or not row.get("requiresUpgrade"):
        return row

    upgraded, backup, log_path = temp_paths(path)
    original_moved = False
    try:
        cleanup(upgraded)
        cleanup(backup)
        cleanup(log_path)
        upgradeOdb(existingOdbPath=path, upgradedOdbPath=upgraded)
        if not os.path.isfile(upgraded):
            raise RuntimeError("Abaqus did not create the upgraded ODB")

        if overwrite:
            # Cross-platform replacement compatible with Abaqus Python 2 runtimes:
            # move the original aside, move the completed upgraded ODB into its
            # pathname, then remove the backup.  If the second rename fails, roll
            # the original back into place before surfacing the error.
            os.rename(path, backup)
            original_moved = True
            try:
                os.rename(upgraded, path)
            except Exception:
                try:
                    os.rename(backup, path)
                    original_moved = False
                except Exception:
                    pass
                raise
            cleanup(backup)
            original_moved = False
            output_path = path
        else:
            output_path = upgraded_copy_path(path)
            os.rename(upgraded, output_path)

        cleanup(log_path)
        row["status"] = "upgraded"
        row["requiresUpgrade"] = False
        row["outputPath"] = output_path
        row["outputName"] = os.path.basename(output_path)
        row["overwritten"] = bool(overwrite)
        return row
    except Exception as exc:
        row["status"] = "error"
        row["error"] = str(exc)
        # Never delete the backup if it is the only surviving original.
        if original_moved and not os.path.exists(path) and os.path.exists(backup):
            try:
                os.rename(backup, path)
                original_moved = False
            except Exception:
                pass
        cleanup(upgraded)
        cleanup(log_path)
        if not original_moved:
            cleanup(backup)
        return row


mode = str(sys.argv[1] if len(sys.argv) > 1 else "check").strip().lower()
overwrite = True
path_index = 2
if len(sys.argv) > 2 and str(sys.argv[2]).strip().lower() in ("overwrite", "keep"):
    overwrite = str(sys.argv[2]).strip().lower() != "keep"
    path_index = 3
paths = [str(value) for value in sys.argv[path_index:]]
if mode not in ("check", "upgrade"):
    emit({"mode": mode, "results": [], "error": "Unsupported mode"})
    sys.exit(2)

results = []
for path in paths:
    results.append(check_one(path) if mode == "check" else upgrade_one(path, overwrite=overwrite))
emit({"mode": mode, "results": results})
'''


def run_parallel_odb_upgrades(paths, run_one, max_workers=ODB_UPGRADE_MAX_WORKERS):
    """Run independent ODB upgrade jobs concurrently, capped at four workers.

    Each worker receives exactly one path and returns the normal WinUx upgrade
    payload.  Results are reassembled in input order.  A failure in one Abaqus
    process becomes an error row for that ODB and does not cancel the remaining
    upgrades.  Running separate Abaqus Python processes also avoids sharing
    ``odbAccess`` objects across threads/processes.
    """
    ordered = list(paths or ())
    if not ordered:
        raise ValueError("Select one or more .odb files")
    worker_count = min(
        ODB_UPGRADE_MAX_WORKERS, max(1, int(max_workers or 1)), len(ordered))
    started = time.monotonic()
    rows = [None] * len(ordered)

    def error_row(path, error):
        text = str(path)
        name = text.replace("\\", "/").rsplit("/", 1)[-1] or "ODB"
        return {
            "path": text,
            "name": name,
            "requiresUpgrade": True,
            "status": "error",
            "error": str(error),
        }

    with ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="winux-odb-upgrade") as pool:
        pending = {
            pool.submit(run_one, path): (index, path)
            for index, path in enumerate(ordered)
        }
        for future in as_completed(pending):
            index, path = pending[future]
            try:
                payload = future.result()
                result_rows = list((payload or {}).get("results") or [])
                if not result_rows:
                    rows[index] = error_row(
                        path, "Abaqus returned no result for this ODB")
                else:
                    rows[index] = dict(result_rows[0])
            except Exception as exc:
                rows[index] = error_row(path, exc)

    return {
        "mode": "upgrade",
        "results": rows,
        "workerCount": worker_count,
        "analysisSeconds": round(max(0.0, time.monotonic() - started), 3),
    }


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


def newest_first_abaqus_commands(values):
    """Sort explicit ``abq20xx`` launchers newest first, custom names later."""
    def release_key(command):
        launcher = str(command).replace("\\", "/").rsplit("/", 1)[-1]
        match = re.fullmatch(
            r"(?:abq|abaqus)(20\d{2})(?:hf(\d+))?(?:[._-].*)?",
            launcher, re.IGNORECASE)
        if match:
            return (0, -int(match.group(1)), -int(match.group(2) or 0))
        if launcher.casefold() in (
                "abaqus", "abaqus.bat", "abaqus.cmd", "abaqus.exe"):
            return (2, 0, 0)
        return (1, 0, 0)
    return sorted(_unique_commands(values), key=release_key)


def build_odb_upgrade_script():
    """Return the Python-2-compatible Abaqus helper used locally/remotely."""
    return ODB_UPGRADE_SCRIPT


def parse_odb_upgrade_output(output):
    text = str(output or "")
    start = text.rfind(JSON_BEGIN)
    if start < 0:
        raise ValueError("Abaqus ODB upgrader did not return a WinUx JSON payload")
    start += len(JSON_BEGIN)
    end = text.find(JSON_END, start)
    if end < 0:
        raise ValueError("Abaqus ODB upgrader returned an incomplete JSON payload")
    raw = text[start:end].strip()
    if not raw:
        raise ValueError("Abaqus ODB upgrader returned an empty JSON payload")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Abaqus ODB upgrader returned an invalid payload")
    return payload


def _validate_local_paths(paths):
    validated = []
    for raw in paths or ():
        path = Path(raw).expanduser()
        if path.suffix.casefold() != ".odb":
            raise ValueError("Upgrade ODB requires only .odb files")
        if not path.exists():
            raise RuntimeError("ODB file is not accessible: {}".format(path))
        if not path.is_file():
            raise ValueError("Upgrade ODB requires files, not folders")
        validated.append(path)
    if not validated:
        raise ValueError("Select one or more .odb files")
    return validated


def _local_process_command(abaqus_command, script_path, mode, paths, overwrite=True):
    parts = [str(abaqus_command), "python", str(script_path), str(mode),
             "overwrite" if overwrite else "keep"]
    parts.extend(str(path) for path in paths)
    if os.name != "nt":
        return parts
    return [
        os.environ.get("COMSPEC") or "cmd.exe",
        "/d", "/s", "/c", subprocess.list2cmdline(parts),
    ]


def _run_local_upgrade_helper(paths, commands, mode, *, timeout, overwrite=True):
    paths = _validate_local_paths(paths)
    candidates = newest_first_abaqus_commands(commands) or ["abaqus"]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    script_path = None
    attempts = []
    started = time.monotonic()
    try:
        fd, script_name = tempfile.mkstemp(prefix="winux-upgrade-odb-", suffix=".py")
        script_path = Path(script_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(build_odb_upgrade_script())

        for candidate in candidates:
            command = _local_process_command(
                candidate, script_path, mode, paths, overwrite=overwrite)
            try:
                completed = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=creationflags,
                    timeout=max(1.0, float(timeout)),
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                attempts.append("{} ({})".format(candidate, exc))
                continue

            combined = "{}\n{}".format(
                completed.stdout or "", completed.stderr or "").strip()
            if JSON_BEGIN in combined:
                payload = parse_odb_upgrade_output(combined)
                payload["abaqusCommand"] = candidate
                payload["analysisSeconds"] = round(
                    max(0.0, time.monotonic() - started), 3)
                payload["source"] = "local"
                return payload

            detail = (completed.stderr or completed.stdout or
                      "exit {}".format(completed.returncode)).strip()
            if detail:
                detail = detail.splitlines()[-1][:220]
            attempts.append("{} ({})".format(candidate, detail or "no result payload"))

        raise RuntimeError(
            "No usable local Abaqus Python command could run Upgrade ODB. Tried: {}"
            .format("; ".join(attempts) if attempts else "(none)"))
    finally:
        if script_path is not None:
            try:
                script_path.unlink()
            except OSError:
                pass


def check_local_odb_upgrades(paths, abaqus_commands=None,
                             timeout=ODB_UPGRADE_CHECK_TIMEOUT_SECONDS):
    return _run_local_upgrade_helper(
        paths, abaqus_commands, "check", timeout=timeout)


def upgrade_local_odbs(paths, abaqus_command,
                       timeout=ODB_UPGRADE_TIMEOUT_SECONDS,
                       max_workers=ODB_UPGRADE_MAX_WORKERS, overwrite=True):
    # Upgrade with the exact release used by the preflight check so the user's
    # confirmation always refers to the actual target Abaqus version.  Each
    # ODB gets its own Abaqus Python process; up to four run concurrently.
    validated = _validate_local_paths(paths)

    def run_one(path):
        return _run_local_upgrade_helper(
            [path], [abaqus_command], "upgrade", timeout=timeout,
            overwrite=overwrite)

    payload = run_parallel_odb_upgrades(
        validated, run_one, max_workers=max_workers)
    payload["abaqusCommand"] = str(abaqus_command)
    payload["source"] = "local"
    payload["overwrite"] = bool(overwrite)
    return payload
