"""User-wide Plot Digitizer display and interaction preferences.

These settings are separate from per-project calibration/extraction data; changing
how points are *shown* must never mutate the points saved in a .pdg project.
"""
from __future__ import annotations

from .storage import JsonPreferenceStore


class PlotDigitizerPreferences:
    FILE = "plot_digitizer.json"
    DEFAULTS = {
        "show_automatic_points": True,
        "show_manual_points": True,
        "show_crosshair": True,
        "show_magnifier": True,
        "preview_zoom": 5,
        "preview_size": 140,
        "preview_crosshair": True,
        "mouse_wheel_zoom": True,
        "wheel_zoom_percent": 12,
        "fit_images_on_open": True,
        "marker_size_percent": 100,
    }
    INT_RANGES = {
        "marker_size_percent": (50, 250),
        "preview_zoom": (1, 20),
        "preview_size": (80, 320),
        "wheel_zoom_percent": (5, 50),
    }

    def __init__(self, root=None):
        self._store = JsonPreferenceStore(self.FILE, root=root)
        self.path = self._store.path

    @classmethod
    def normalize(cls, values):
        """Ignore unrecognized/corrupt keys, never coerce strings into booleans."""
        values = values if isinstance(values, dict) else {}
        normalized = dict(cls.DEFAULTS)
        for key, default in cls.DEFAULTS.items():
            value = values.get(key)
            if isinstance(default, bool):
                if type(value) is bool:
                    normalized[key] = value
            elif type(value) is int and cls.INT_RANGES[key][0] <= value <= cls.INT_RANGES[key][1]:
                normalized[key] = value
        return normalized

    def load(self):
        return self.normalize(self._store.load())

    def save(self, values):
        settings = self.normalize(values)
        self._store.save(settings)
        return settings

    def reset(self):
        return self.save(self.DEFAULTS)
