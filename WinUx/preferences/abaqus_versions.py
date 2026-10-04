"""Persistent Abaqus executable choices used by WinUx."""

from __future__ import annotations

from .storage import JsonPreferenceStore


class AbaqusVersionPreferences:
    """Store Abaqus commands and the preferred/default command.

    Existing profiles containing only ``versions`` are migrated lazily.  The
    preferred command defaults to ``abq2026`` and is always tried before the
    remaining configured/built-in commands. ODB readers additionally probe the
    real database and fall back until a release can open that ODB.
    """

    DEFAULT_COMMAND = "abq2026"
    DEFAULT_COMMANDS = tuple(
        ["abq{}".format(year) for year in range(2026, 2017, -1)]
        + ["abaqus"]
    )

    def __init__(self, root=None):
        self._store = JsonPreferenceStore("abaqus_versions.json", root=root)
        self.path = self._store.path

    @staticmethod
    def _clean(values):
        result = []
        for value in values or ():
            value = str(value).strip()
            if value and value not in result:
                result.append(value)
        return result

    def load(self, defaults=None):
        defaults = list(defaults or self.DEFAULT_COMMANDS)
        data = self._store.load()
        values = data.get("versions", [])
        source = values if isinstance(values, list) and values else defaults
        result = self._clean(source)
        return result or self._clean(defaults) or [self.DEFAULT_COMMAND]

    def load_settings(self, defaults=None):
        versions = self.load(defaults)
        data = self._store.load()
        preferred = str(data.get("default_command") or "").strip()
        if not preferred:
            # Migration rule: profiles created before the default-command
            # setting existed start with abq2026, even if their old version
            # list contained only ``abaqus`` or another release.
            preferred = self.DEFAULT_COMMAND
        if preferred not in versions:
            # Keep a previously configured custom launcher visible/selectable
            # after migration from older settings files.
            versions.insert(0, preferred)
        return {
            "versions": versions,
            "default_command": preferred,
        }

    def load_default(self, defaults=None):
        return self.load_settings(defaults)["default_command"]

    def ordered_commands(self, defaults=None):
        settings = self.load_settings(defaults)
        ordered = [settings["default_command"]]
        ordered.extend(settings["versions"])
        # Always retain the built-in release fallback chain even when the user
        # has a short custom list.  This is especially useful on shared Linux
        # clusters where different nodes expose different Abaqus releases.
        ordered.extend(self.DEFAULT_COMMANDS)
        return self._clean(ordered)

    def save(self, versions, default_command=None):
        values = self._clean(versions)
        if not values:
            values = list(self.DEFAULT_COMMANDS)
        preferred = str(default_command or "").strip()
        if not preferred:
            old = str(self._store.load().get("default_command") or "").strip()
            preferred = old or (self.DEFAULT_COMMAND if self.DEFAULT_COMMAND in values
                                else values[0])
        if preferred not in values:
            values.insert(0, preferred)
        # Running jobs must remain possible when the profile is read-only.
        self._store.save(
            {"versions": values, "default_command": preferred},
            suppress_errors=True,
        )
