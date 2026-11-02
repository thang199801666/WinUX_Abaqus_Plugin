"""Persistent user preferences with lazy public exports.

Individual preference stores are independent.  Importing one should not import
all of the others, especially during application startup.
"""
from __future__ import annotations

from importlib import import_module

_LAZY_PREFERENCES = {
    "AbaqusVersionPreferences": (".abaqus_versions", "AbaqusVersionPreferences"),
    "DialogGeometryPreferences": (".dialog_geometry", "DialogGeometryPreferences"),
    "GeneralPreferences": (".general", "GeneralPreferences"),
    "INPPreferences": (".inp", "INPPreferences"),
    "JobManagerPreferences": (".job_manager", "JobManagerPreferences"),
    "LoginPreferences": (".login", "LoginPreferences"),
    "NavigationPreferences": (".navigation", "NavigationPreferences"),
    "PerformancePreferences": (".performance", "PerformancePreferences"),
    "PlotDigitizerPreferences": (".plot_digitizer", "PlotDigitizerPreferences"),
    "UpdatePreferences": (".update", "UpdatePreferences"),
    "JsonPreferenceStore": (".storage", "JsonPreferenceStore"),
    "user_profile_path": (".storage", "user_profile_path"),
    "SitePreferences": (".sites", "SitePreferences"),
}

__all__ = list(_LAZY_PREFERENCES)


def __getattr__(name):
    target = _LAZY_PREFERENCES.get(name)
    if target is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
