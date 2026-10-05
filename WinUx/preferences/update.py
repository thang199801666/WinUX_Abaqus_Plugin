"""User-facing hybrid updater preferences.

The bootstrap reads these keys directly from the shared ``settings.json``.
The app-side writer shares the bootstrap's standard-library preference resolver
so Settings and startup agree on the default repository and legacy migration.
"""
from __future__ import annotations

from .storage import JsonPreferenceStore
from winux_update_providers import update_preferences

class UpdatePreferences:
    DEFAULT_PROVIDER = "auto"
    DEFAULT_CHANNEL = "stable"
    DEFAULT_LEGACY_SOURCE = (
        r"S:\WinUx"
    )
    VALID_PROVIDERS = {"auto", "github", "folder"}
    VALID_CHANNELS = {"stable", "beta"}
    LEGACY_DEPRECATION_NOTE = (
        "S: drive updates are in compatibility mode. Existing users remain supported, "
        "but new deployments should use public GitHub Releases. S: will move to fallback-only "
        "and be retired after the migration window."
    )
    CHANNEL_DESCRIPTIONS = {
        "stable": "Stable installs only non-prerelease GitHub Releases.",
        "beta": "Beta installs the newest semantic version, including GitHub prereleases.",
    }

    def __init__(self, root=None):
        self._store = JsonPreferenceStore("settings.json", root=root)
        self.path = self._store.path

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
            "legacy_source": str(data.get("update_source", "") or ""),
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

        legacy_source = str(legacy_source or "").strip().strip('"')
        if legacy_source:
            data["update_source"] = legacy_source
        else:
            # Blank means use the bootstrap's default shared-folder location.
            data.pop("update_source", None)
        self._store.save(data)
        return self.load()
