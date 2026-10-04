"""Realtime Abaqus ODB History Output streaming helpers.

The remote helper is intentionally Python-2-compatible because many Abaqus
installations still embed a Python 2 runtime.  One long-lived ``abaqus python``
process opens the ODB read-only and calls ``odb.update()`` while the analysis is
running.  WinUx sends the currently checked History Output entries over stdin;
the helper returns compact JSON catalog/status/delta frames over stdout.
"""

from __future__ import annotations

import json
import math


LIVE_PREFIX = "__WINUX_ODB_HISTORY_LIVE__"


ODB_HISTORY_LIVE_SCRIPT = r'''from __future__ import print_function
from odbAccess import openOdb
import hashlib
import json
import os
import re
import select
import sys
import time
import traceback

PREFIX = "__WINUX_ODB_HISTORY_LIVE__"


def _emit(payload):
    try:
        text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    except TypeError:
        text = json.dumps(payload, sort_keys=True)
    print(PREFIX + text)
    sys.stdout.flush()


def _scalar(value):
    try:
        return float(value)
    except Exception:
        return None


def _clean_region_description(value):
    text = str(value or "").strip()
    for prefix in ("History Region for ", "History region for "):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text


def _history_region_context(region_name, region_description):
    region_name = str(region_name or "").strip()
    region_description = _clean_region_description(region_description)
    upper_name = region_name.upper()
    upper_description = region_description.upper()
    if upper_name in ("ASSEMBLY ASSEMBLY", "ASSEMBLY", "WHOLE MODEL"):
        return "for Whole Model"
    if "WHOLE MODEL" in upper_description:
        return "for Whole Model"
    if "PI:" in region_description or " IN NSET " in (" " + upper_description + " "):
        return region_description
    match = re.match(r"^Node\s+(.+)\.(\d+)$", region_name, re.I)
    if match:
        context = "PI: %s Node %s" % (match.group(1).strip(), match.group(2))
        nset_match = re.search(r"\bin\s+NSET\s+([^,;]+)$", region_description, re.I)
        if nset_match:
            context += " in NSET " + nset_match.group(1).strip()
        return context
    return region_description or region_name


def _history_display_name(output_name, description, region_name, region_description):
    output_name = str(output_name or "").strip()
    description = str(description or "").strip()
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


def _stable_id(step_name, region_name, output_name):
    key = "%s\x1f%s\x1f%s" % (step_name, region_name, output_name)
    try:
        encoded = key.encode("utf-8")
    except Exception:
        encoded = str(key)
    return "H" + hashlib.sha1(encoded).hexdigest()[:14]


def _catalog(odb, path):
    rows = []
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
                rows.append({
                    "id": _stable_id(step_name, region_name, output_name),
                    "step": str(step_name),
                    "historyRegion": str(region_name),
                    "regionDescription": region_description,
                    "output": str(output_name),
                    "description": description,
                    "displayName": display_name,
                    "points": int(points),
                })
    rows.sort(key=lambda row: (
        row.get("step", ""), row.get("historyRegion", ""),
        row.get("output", "")))
    return {
        "type": "catalog",
        "odb": os.path.basename(path),
        "path": path,
        "historyOutputs": rows,
    }


def _read_command(timeout):
    try:
        readable, _writable, _errors = select.select([sys.stdin], [], [], timeout)
    except Exception:
        time.sleep(timeout)
        return None
    if not readable:
        return None
    line = sys.stdin.readline()
    if line == "":
        return {"cmd": "stop"}
    try:
        return json.loads(line)
    except Exception:
        return None


def _selected_series(odb, items, last_counts):
    rows = []
    active_ids = set()
    for item in items or []:
        item_id = str(item.get("id") or "")
        active_ids.add(item_id)
        step_name = str(item.get("step") or "")
        region_name = str(item.get("historyRegion") or "")
        output_name = str(item.get("output") or "")
        try:
            output = odb.steps[step_name].historyRegions[region_name].historyOutputs[output_name]
            data = getattr(output, "data", None) or []
        except Exception:
            rows.append({
                "id": item_id,
                "displayName": str(item.get("displayName") or output_name),
                "output": output_name,
                "points": [],
                "totalPoints": 0,
                "reset": True,
                "error": "History Output is not currently available",
            })
            last_counts[item_id] = 0
            continue

        total = len(data)
        previous = int(last_counts.get(item_id, 0) or 0)
        reset = previous > total
        start = 0 if reset else previous
        points = []
        for pair in data[start:]:
            if not pair or len(pair) < 2:
                continue
            x_value = _scalar(pair[0])
            y_value = _scalar(pair[1])
            if x_value is None or y_value is None:
                continue
            points.append([x_value, y_value])
        last_counts[item_id] = total
        if points or reset or previous == 0:
            rows.append({
                "id": item_id,
                "displayName": str(item.get("displayName") or output_name),
                "output": output_name,
                "points": points,
                "totalPoints": total,
                "reset": bool(reset or previous == 0),
                "error": None,
            })

    for item_id in list(last_counts.keys()):
        if item_id not in active_ids:
            del last_counts[item_id]
    return rows


def _open_odb(path):
    return openOdb(path=path, readOnly=True)


def _file_fingerprint(path):
    try:
        info = os.stat(path)
        return (float(info.st_mtime), int(info.st_size))
    except Exception:
        return None


class _AdaptiveInterval(object):
    """Backoff plus cadence learning for remote ODB file checks.

    This class stays Python-2-compatible because it is embedded into the
    remote Abaqus helper. It learns the spacing between actual ODB writes with
    an EWMA and starts checking more often near the predicted next write.
    """

    def __init__(self, minimum, maximum, stable_to_max, quiet_to_max,
                 history_alpha=0.35, prediction_fraction=0.25,
                 confidence_samples=3):
        self.current = 0.0
        self.stable = 0
        self.last_change = time.time()
        self.last_event = None
        self.learned_interval = None
        self.learned_deviation = 0.0
        self.history_samples = 0
        self.configure(
            minimum, maximum, stable_to_max, quiet_to_max,
            history_alpha, prediction_fraction, confidence_samples)
        self.current = self.minimum

    def configure(self, minimum, maximum, stable_to_max, quiet_to_max,
                  history_alpha=None, prediction_fraction=None,
                  confidence_samples=None):
        try:
            minimum = max(0.25, float(minimum))
        except Exception:
            minimum = 1.0
        try:
            maximum = max(minimum, float(maximum))
        except Exception:
            maximum = minimum
        try:
            stable_to_max = max(1, int(stable_to_max))
        except Exception:
            stable_to_max = 8
        try:
            quiet_to_max = max(1.0, float(quiet_to_max))
        except Exception:
            quiet_to_max = 180.0
        if history_alpha is None:
            history_alpha = getattr(self, "history_alpha", 0.35)
        if prediction_fraction is None:
            prediction_fraction = getattr(self, "prediction_fraction", 0.25)
        if confidence_samples is None:
            confidence_samples = getattr(self, "confidence_samples", 3)
        try:
            history_alpha = min(1.0, max(0.01, float(history_alpha)))
        except Exception:
            history_alpha = 0.35
        try:
            prediction_fraction = min(
                1.0, max(0.05, float(prediction_fraction)))
        except Exception:
            prediction_fraction = 0.25
        try:
            confidence_samples = max(1, int(confidence_samples))
        except Exception:
            confidence_samples = 3
        self.minimum = minimum
        self.maximum = maximum
        self.stable_to_max = stable_to_max
        self.quiet_to_max = quiet_to_max
        self.history_alpha = history_alpha
        self.prediction_fraction = prediction_fraction
        self.confidence_samples = confidence_samples
        if self.current:
            self.current = min(self.maximum, max(self.minimum, self.current))

    def force_fast(self):
        self.stable = 0
        self.last_change = time.time()
        self.current = self.minimum
        return self.current

    def _learn_event(self, now):
        if self.last_event is not None:
            interval = max(0.0, now - self.last_event)
            if interval > 0.0:
                if self.learned_interval is None:
                    self.learned_interval = interval
                    self.learned_deviation = 0.0
                else:
                    previous = self.learned_interval
                    error = abs(interval - previous)
                    self.learned_interval = previous + self.history_alpha * (
                        interval - previous)
                    self.learned_deviation = self.learned_deviation + self.history_alpha * (
                        error - self.learned_deviation)
                self.history_samples += 1
        self.last_event = now

    def _history_delay(self, now, baseline):
        if self.learned_interval is None or self.history_samples <= 0:
            return baseline
        age = max(0.0, now - self.last_change)
        mean = max(self.minimum, float(self.learned_interval))
        expected_age = max(
            self.minimum, mean - max(0.0, self.learned_deviation))
        remaining = expected_age - age
        probe = min(
            self.maximum,
            max(self.minimum, mean * self.prediction_fraction))
        if remaining > self.minimum:
            predicted = min(max(probe, remaining * 0.5), remaining)
        else:
            predicted = probe
        confidence = min(
            1.0,
            float(self.history_samples) / float(self.confidence_samples))
        value = baseline + (predicted - baseline) * confidence
        return min(self.maximum, max(self.minimum, value))

    def observe(self, changed):
        now = time.time()
        if changed:
            self._learn_event(now)
            self.stable = 0
            self.last_change = now
            # Once several writes have been observed, do not blindly return to
            # a 1 Hz loop after every write. Reuse the learned write cadence.
            self.current = self._history_delay(now, self.minimum)
            return self.current
        self.stable += 1
        sample_progress = min(1.0, float(self.stable) / float(self.stable_to_max))
        quiet_progress = min(1.0, max(0.0, now - self.last_change) / self.quiet_to_max)
        progress = 0.5 * sample_progress + 0.5 * quiet_progress
        baseline = self.minimum + (self.maximum - self.minimum) * progress
        self.current = self._history_delay(now, baseline)
        return self.current

    def snapshot(self):
        return {
            "interval": self.current,
            "learnedInterval": self.learned_interval,
            "learnedDeviation": self.learned_deviation,
            "historySamples": self.history_samples,
        }

def main():
    if len(sys.argv) < 2:
        _emit({"type": "fatal", "error": "Expected ODB path"})
        return
    path = sys.argv[1]
    try:
        minimum = max(0.25, float(sys.argv[2])) if len(sys.argv) > 2 else 1.0
    except Exception:
        minimum = 1.0
    try:
        maximum = max(minimum, float(sys.argv[3])) if len(sys.argv) > 3 else minimum
    except Exception:
        maximum = minimum
    try:
        stable_to_max = max(1, int(sys.argv[4])) if len(sys.argv) > 4 else 8
    except Exception:
        stable_to_max = 8
    try:
        quiet_to_max = max(1.0, float(sys.argv[5])) if len(sys.argv) > 5 else 180.0
    except Exception:
        quiet_to_max = 180.0
    try:
        history_alpha = min(1.0, max(0.01, float(sys.argv[6]))) if len(sys.argv) > 6 else 0.35
    except Exception:
        history_alpha = 0.35
    try:
        prediction_fraction = min(1.0, max(0.05, float(sys.argv[7]))) if len(sys.argv) > 7 else 0.25
    except Exception:
        prediction_fraction = 0.25
    try:
        confidence_samples = max(1, int(sys.argv[8])) if len(sys.argv) > 8 else 3
    except Exception:
        confidence_samples = 3
    try:
        catalog_changed_checks = max(1, int(sys.argv[9])) if len(sys.argv) > 9 else 5
    except Exception:
        catalog_changed_checks = 5

    policy = _AdaptiveInterval(
        minimum, maximum, stable_to_max, quiet_to_max,
        history_alpha, prediction_fraction, confidence_samples)
    odb = None
    selected = []
    last_counts = {}
    last_catalog_signature = None
    changed_since_catalog = 0
    last_fingerprint = None
    try:
        while odb is None:
            try:
                odb = _open_odb(path)
            except Exception as exc:
                _emit({"type": "status", "state": "waiting", "message": str(exc)})
                command = _read_command(policy.current)
                if command and command.get("cmd") == "stop":
                    return
                if command and command.get("cmd") == "select":
                    selected = list(command.get("items") or [])
                policy.observe(False)

        catalog = _catalog(odb, path)
        _emit(catalog)
        last_catalog_signature = [
            (row.get("step"), row.get("historyRegion"), row.get("output"))
            for row in catalog.get("historyOutputs") or []
        ]
        last_fingerprint = _file_fingerprint(path)
        _emit({"type": "status", "state": "live", "message": "ODB opened"})

        while True:
            command = _read_command(policy.current)
            force_refresh = False
            if command:
                if command.get("cmd") == "stop":
                    return
                if command.get("cmd") == "select":
                    selected = list(command.get("items") or [])
                    # Selection changes need one immediate complete frame even
                    # when the ODB file itself has not changed.
                    last_counts = {}
                    force_refresh = True
                    policy.force_fast()
                elif command.get("cmd") == "config":
                    policy.configure(
                        command.get("minInterval", policy.minimum),
                        command.get("maxInterval", policy.maximum),
                        command.get("stableChecksToMax", policy.stable_to_max),
                        command.get("quietSecondsToMax", policy.quiet_to_max),
                        command.get("historyAlpha", policy.history_alpha),
                        command.get("predictionFraction", policy.prediction_fraction),
                        command.get("historyConfidenceSamples", policy.confidence_samples),
                    )
                    try:
                        catalog_changed_checks = max(1, int(command.get(
                            "catalogChangedChecks", catalog_changed_checks)))
                    except Exception:
                        pass

            fingerprint = _file_fingerprint(path)
            file_changed = fingerprint != last_fingerprint
            if file_changed:
                last_fingerprint = fingerprint
            if file_changed:
                policy.observe(True)
            elif force_refresh:
                policy.force_fast()
            else:
                policy.observe(False)

            # The key load reduction: if mtime/size are unchanged, do not call
            # odb.update(), do not walk HistoryOutput.data, and do not rescan
            # the catalog. Only the cheap local stat/check interval backs off.
            if not file_changed and not force_refresh:
                continue

            try:
                update = getattr(odb, "update", None)
                if callable(update):
                    update()
                else:
                    odb.close()
                    odb = _open_odb(path)
            except Exception:
                try:
                    odb.close()
                except Exception:
                    pass
                odb = _open_odb(path)
                last_counts = {}

            if file_changed:
                changed_since_catalog += 1
            if changed_since_catalog >= catalog_changed_checks:
                changed_since_catalog = 0
                catalog = _catalog(odb, path)
                signature = [
                    (row.get("step"), row.get("historyRegion"), row.get("output"))
                    for row in catalog.get("historyOutputs") or []
                ]
                if signature != last_catalog_signature:
                    _emit(catalog)
                    last_catalog_signature = signature

            series = _selected_series(odb, selected, last_counts)
            if series:
                _emit({
                    "type": "frame",
                    "path": path,
                    "timestamp": time.time(),
                    "series": series,
                })
    except Exception as exc:
        _emit({
            "type": "fatal",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })
    finally:
        if odb is not None:
            try:
                odb.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
'''


def build_remote_odb_history_live_script() -> str:
    return ODB_HISTORY_LIVE_SCRIPT


def parse_live_message(line: str):
    """Parse one stdout line emitted by the remote live-history helper."""
    text = str(line or "").strip()
    if not text.startswith(LIVE_PREFIX):
        return None
    payload = json.loads(text[len(LIVE_PREFIX):])
    if not isinstance(payload, dict):
        raise ValueError("Realtime ODB monitor returned an invalid payload")
    return payload


def default_history_ids(history_outputs):
    """Return ALLKE/ALLIE IDs in catalog order, case-insensitively."""
    selected = []
    for item in history_outputs or []:
        output = str(item.get("output") or "").strip().upper()
        if output in ("ALLKE", "ALLIE"):
            item_id = str(item.get("id") or "")
            if item_id:
                selected.append(item_id)
    return selected


def merge_series_delta(existing, update):
    """Merge one remote delta into an in-memory ``[[x, y], ...]`` series."""
    points = [] if update.get("reset") else list(existing or [])
    for pair in update.get("points") or []:
        if not pair or len(pair) < 2:
            continue
        try:
            x_value = float(pair[0])
            y_value = float(pair[1])
        except (TypeError, ValueError):
            continue
        if math.isfinite(x_value) and math.isfinite(y_value):
            points.append([x_value, y_value])
    return points
