"""User-facing hybrid updater preferences.

The bootstrap reads these keys directly from the shared ``settings.json``.
The app-side writer shares the bootstrap's standard-library preference resolver
so Settings and startup agree on the default repository and legacy migration.
"""
from __future__ import annotations

from .storage import JsonPreferenceStore
from winux_runtime.update.providers import update_preferences

class UpdatePreferences:
    DEFAULT_PROVIDER = "github"
    DEFAULT_CHANNEL = "stable"
    DEFAULT_LEGACY_SOURCE = ""
    VALID_PROVIDERS = {"github"}
    VALID_CHANNELS = {"stable", "beta"}
    CHANNEL_DESCRIPTIONS = {
        "stable": "Stable installs only non-prerelease GitHub Releases.",
        "beta": "Beta installs the newest semantic version, including GitHub prereleases.",
    }

    def __init__(self, root=None):
        self._store = JsonPreferenceStore("settings.json", root=root)
        self.path = self._store.path

    @classmethod
    def defaults(cls):
        return {
            "provider": cls.DEFAULT_PROVIDER,
            "channel": cls.DEFAULT_CHANNEL,
            "github_repository": update_preferences({}, environ={})["github_repository"] or "",
            "legacy_source": "",
        }

    @staticmethod
    def _repository(value):
        value = str(value or "").strip().strip("/")
        lower = value.lower()
        for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
            if lower.startswith(prefix):
                value = value[len(prefix):].strip("/")
                break
        if value.lower().endswith(".git"):
            value = value[:-4]
        if not value:
            return ""
        pieces = [piece for piece in value.split("/") if piece]
        if len(pieces) != 2:
            raise ValueError("GitHub repository must use owner/repository format.")
        return "/".join(pieces)

    def load(self, include_credentials=False):
        # include_credentials is retained as a compatibility no-op; GitHub is public.
        data = self._store.load()
        provider = str(data.get("update_provider", self.DEFAULT_PROVIDER)).strip().lower()
        # Migrate historical folder/S: settings silently to GitHub-only updates.
        if provider not in self.VALID_PROVIDERS:
            provider = self.DEFAULT_PROVIDER
        channel = str(data.get("update_channel", self.DEFAULT_CHANNEL)).strip().lower()
        if channel not in self.VALID_CHANNELS:
            channel = self.DEFAULT_CHANNEL
        try:
            repository = update_preferences(
                dict(data, update_provider=provider, update_channel=channel), environ={}
            )["github_repository"] or ""
        except ValueError:
            repository = ""
        result = {
            "provider": provider,
            "github_repository": repository,
            "channel": channel,
            "legacy_source": "",
        }
        return result

    def save(self, *, provider, github_repository, channel, legacy_source):
        provider = str(provider or self.DEFAULT_PROVIDER).strip().lower()
        if provider not in self.VALID_PROVIDERS:
            raise ValueError("Unsupported update provider: {}".format(provider))
        channel = str(channel or self.DEFAULT_CHANNEL).strip().lower()
        if channel not in self.VALID_CHANNELS:
            raise ValueError("Unsupported update channel: {}".format(channel))
        repository = self._repository(github_repository)
        if provider == "github" and not repository:
            raise ValueError("Configure a GitHub repository before forcing GitHub updates.")

        data = self._store.load()
        data["update_provider"] = provider
        data["update_channel"] = channel
        if repository:
            data["github_repository"] = repository
        else:
            # Persist the opt-out instead of restoring the built-in repository.
            data["github_repository"] = ""

        # S:/shared-folder update settings are obsolete for normal app launches.
        # Remove stale persisted values so future bootstrap runs never probe them.
        data.pop("update_source", None)
        self._store.save(data)
        return self.load()
