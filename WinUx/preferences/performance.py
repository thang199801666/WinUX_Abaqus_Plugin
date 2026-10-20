"""Performance and server-load tuning preferences."""

from __future__ import annotations

from .storage import JsonPreferenceStore


class PerformancePreferences:
    """Persist adaptive polling limits used by qstat and live ODB plots."""

    DEFAULTS = {
        "qstat_min_interval": 5.0,
        "qstat_max_interval": 30.0,
        "qstat_stable_samples_to_max": 8,
        "qstat_quiet_seconds_to_max": 90.0,
        # Client-side inactivity backoff is intentionally more aggressive than
        # scheduler-state backoff.  After 30 minutes without WinUx input qstat
        # is suspended until interaction resumes; live ODB monitors keep only a
        # sparse heartbeat so their remote helper remains reusable.
        "inactivity_idle_seconds": 120.0,
        "inactivity_away_seconds": 600.0,
        "inactivity_deep_idle_seconds": 1800.0,
        "inactivity_idle_qstat_interval": 60.0,
        "inactivity_away_qstat_interval": 180.0,
        "inactivity_deep_qstat_interval": 0.0,
        "inactivity_deep_odb_interval": 600.0,
        "odb_min_interval": 1.0,
        "odb_max_interval": 60.0,
        "odb_stable_samples_to_max": 8,
        "odb_quiet_seconds_to_max": 180.0,
        "odb_history_alpha": 0.35,
        "odb_prediction_fraction": 0.25,
        "odb_history_confidence_samples": 3,
        "odb_catalog_changed_checks": 5,
    }

    def __init__(self, root=None):
        self._store = JsonPreferenceStore("performance.json", root=root)
        self.path = self._store.path

    @classmethod
    def _validated(cls, values):
        data = dict(cls.DEFAULTS)
        data.update(values or {})

        def number(name, minimum, maximum):
            try:
                value = float(data[name])
            except (TypeError, ValueError):
                value = float(cls.DEFAULTS[name])
            return min(maximum, max(minimum, value))

        def integer(name, minimum, maximum):
            try:
                value = int(data[name])
            except (TypeError, ValueError):
                value = int(cls.DEFAULTS[name])
            return min(maximum, max(minimum, value))

        result = {
            "qstat_min_interval": number("qstat_min_interval", 1.0, 300.0),
            "qstat_max_interval": number("qstat_max_interval", 1.0, 300.0),
            "qstat_stable_samples_to_max": integer(
                "qstat_stable_samples_to_max", 1, 100),
            "qstat_quiet_seconds_to_max": number(
                "qstat_quiet_seconds_to_max", 1.0, 3600.0),
            "inactivity_idle_seconds": number(
                "inactivity_idle_seconds", 5.0, 86400.0),
            "inactivity_away_seconds": number(
                "inactivity_away_seconds", 5.0, 86400.0),
            "inactivity_deep_idle_seconds": number(
                "inactivity_deep_idle_seconds", 5.0, 172800.0),
            "inactivity_idle_qstat_interval": number(
                "inactivity_idle_qstat_interval", 1.0, 3600.0),
            "inactivity_away_qstat_interval": number(
                "inactivity_away_qstat_interval", 1.0, 7200.0),
            "inactivity_deep_qstat_interval": number(
                "inactivity_deep_qstat_interval", 0.0, 21600.0),
            "inactivity_deep_odb_interval": number(
                "inactivity_deep_odb_interval", 30.0, 21600.0),
            "odb_min_interval": number("odb_min_interval", 0.25, 600.0),
            "odb_max_interval": number("odb_max_interval", 0.25, 600.0),
            "odb_stable_samples_to_max": integer(
                "odb_stable_samples_to_max", 1, 100),
            "odb_quiet_seconds_to_max": number(
                "odb_quiet_seconds_to_max", 1.0, 7200.0),
            "odb_history_alpha": number("odb_history_alpha", 0.01, 1.0),
            "odb_prediction_fraction": number(
                "odb_prediction_fraction", 0.05, 1.0),
            "odb_history_confidence_samples": integer(
                "odb_history_confidence_samples", 1, 20),
            "odb_catalog_changed_checks": integer(
                "odb_catalog_changed_checks", 1, 100),
        }
        result["qstat_max_interval"] = max(
            result["qstat_min_interval"], result["qstat_max_interval"])
        result["inactivity_away_seconds"] = max(
            result["inactivity_idle_seconds"], result["inactivity_away_seconds"])
        result["inactivity_deep_idle_seconds"] = max(
            result["inactivity_away_seconds"], result["inactivity_deep_idle_seconds"])
        result["inactivity_away_qstat_interval"] = max(
            result["inactivity_idle_qstat_interval"],
            result["inactivity_away_qstat_interval"])
        result["odb_max_interval"] = max(
            result["odb_min_interval"], result["odb_max_interval"])
        return result

    def load(self):
        return self._validated(self._store.load())

    def save(self, values):
        data = self._validated(values)
        self._store.save(data)
        return data
