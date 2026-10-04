"""Preferences used by the Abaqus INP sizing recommendation."""

from __future__ import annotations

from .storage import JsonPreferenceStore


class INPPreferences:
    """Persist and validate the DOF-to-core recommendation formula."""

    FORMULA_LEGACY = "legacy_tiers"
    FORMULA_ADAPTIVE = "adaptive"

    DEFAULTS = {
        "formula": FORMULA_LEGACY,
        "dof_per_core": 5000,
        "minimum_cores": 32,
        "maximum_cores": 160,
        "core_step": 4,
    }
    # Kept for callers and tests written against older releases.
    DEFAULT_SCALE = DEFAULTS["dof_per_core"]

    def __init__(self, root=None):
        self._store = JsonPreferenceStore("settings.json", root=root)
        self.path = self._store.path

    @classmethod
    def normalize(cls, values=None):
        source = dict(values or {})
        formula = str(
            source.get("formula", cls.DEFAULTS["formula"])
        ).strip()
        if formula not in (cls.FORMULA_LEGACY, cls.FORMULA_ADAPTIVE):
            formula = cls.DEFAULTS["formula"]

        def positive_int(key):
            try:
                value = int(source.get(key, cls.DEFAULTS[key]))
            except (TypeError, ValueError):
                value = cls.DEFAULTS[key]
            return value if value > 0 else cls.DEFAULTS[key]

        result = {
            "formula": formula,
            "dof_per_core": positive_int("dof_per_core"),
            "minimum_cores": positive_int("minimum_cores"),
            "maximum_cores": positive_int("maximum_cores"),
            "core_step": positive_int("core_step"),
        }
        if result["maximum_cores"] < result["minimum_cores"]:
            result["maximum_cores"] = result["minimum_cores"]
        return result

    def load(self):
        data = self._store.load()
        # Migrate the original single-value key without rewriting the file.
        values = {
            "formula": data.get(
                "inp_core_formula", self.DEFAULTS["formula"]
            ),
            "dof_per_core": data.get(
                "inp_dof_per_core",
                data.get("inp_dof_scale", self.DEFAULTS["dof_per_core"]),
            ),
            "minimum_cores": data.get(
                "inp_minimum_cores", self.DEFAULTS["minimum_cores"]
            ),
            "maximum_cores": data.get(
                "inp_maximum_cores", self.DEFAULTS["maximum_cores"]
            ),
            "core_step": data.get(
                "inp_core_step", self.DEFAULTS["core_step"]
            ),
        }
        return self.normalize(values)

    def save(self, values):
        normalized = self.normalize(values)
        data = self._store.load()
        data.update({
            "inp_core_formula": normalized["formula"],
            "inp_dof_per_core": normalized["dof_per_core"],
            # Keep the old key synchronized for compatibility with older builds.
            "inp_dof_scale": normalized["dof_per_core"],
            "inp_minimum_cores": normalized["minimum_cores"],
            "inp_maximum_cores": normalized["maximum_cores"],
            "inp_core_step": normalized["core_step"],
        })
        self._store.save(data)
        return normalized

    def load_scale(self):
        return int(self.load()["dof_per_core"])

    def save_scale(self, value):
        settings = self.load()
        settings["dof_per_core"] = int(value)
        return self.save(settings)