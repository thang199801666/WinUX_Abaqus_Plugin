"""WinUx local-first update orchestrator.

Architecture:
    bootstrap child -> manifest/version check -> user confirmation ->
    cross-process lock -> staged copy -> SHA-256 verification -> atomic swap ->
    post-install health check/rollback -> launch local WinUx.

The UI remains isolated in the child ``abaqus python`` process started by
``winux_launcher``; this module never runs a nested update loop in Abaqus/CAE.
Keep standard-library/Python 2 + 3 compatibility for Abaqus releases.
"""
from __future__ import print_function

import datetime
import json
import os
import tempfile
import time

from winux_update_installer import (
    synchronize_project as _synchronize_project,
    synchronize_versioned_project as _synchronize_versioned_project,
)
from winux_installation_state import (
    INSTALL_MODE_KEY,
    install_mode as resolve_install_mode,
    install_root as versioned_install_root,
    versioned_install_enabled,
    resolve_active_installation,
    is_quarantined,
    quarantine_version,
    clear_quarantine,
)
from winux_update_lock import UpdateInProgress, UpdateLock
from winux_update_manifest import (
    MANIFEST_FILENAME,
    VERSION_FILENAME,
    compare_versions,
    read_version,
    source_descriptor,
    source_is_valid,
)
from winux_health_check import subprocess_health_check as _subprocess_health_check
from winux_update_providers import (
    GITHUB_API_BASE_KEY,
    GITHUB_REPOSITORY_KEY,
    PROVIDER_AUTO,
    PROVIDER_FOLDER,
    PROVIDER_GITHUB,
    UPDATE_CHANNEL_KEY,
    UPDATE_PROVIDER_KEY,
    GitHubReleaseProvider,
    should_use_github,
    update_preferences,
)


DEFAULT_NETWORK_PROJECT_DIR = (
    r"S:\WinUx"
)
UPDATE_SOURCE_KEY = "update_source"
SETTINGS_FILENAME = "settings.json"


def _text(value):
    try:
        text_type = unicode  # noqa: F821 - Python 2 only
    except NameError:
        text_type = str
    try:
        return text_type(value)
    except Exception:
        return str(value)


def _same_path(left, right):
    if not left or not right:
        return False
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _profile_settings_path(environ=None):
    environ = os.environ if environ is None else environ
    root = (
        environ.get("APPDATA")
        or environ.get("LOCALAPPDATA")
        or os.path.expanduser("~")
        or tempfile.gettempdir()
    )
    return os.path.join(root, "WinUX", SETTINGS_FILENAME)


def _read_settings(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        if not raw:
            return {}
        try:
            raw = raw.decode("utf-8")
        except AttributeError:
            pass
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError, TypeError):
        return {}


def _write_settings(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        try:
            os.makedirs(directory)
        except OSError:
            if not os.path.isdir(directory):
                raise
    temporary = path + ".tmp"
    encoded = json.dumps(data, indent=2, sort_keys=True)
    if not isinstance(encoded, bytes):
        encoded = encoded.encode("utf-8")
    with open(temporary, "wb") as handle:
        handle.write(encoded)
        handle.write(b"\n")
    if os.path.exists(path):
        os.remove(path)
    os.rename(temporary, path)


def load_update_source(environ=None, settings_path=None):
    path = settings_path or _profile_settings_path(environ)
    value = _read_settings(path).get(UPDATE_SOURCE_KEY)
    if value is None:
        return None
    value = _text(value).strip().strip('"')
    return value or None


def save_update_source(source_dir, environ=None, settings_path=None):
    path = settings_path or _profile_settings_path(environ)
    data = _read_settings(path)
    data[UPDATE_SOURCE_KEY] = os.path.abspath(source_dir)
    _write_settings(path, data)
    return path




def load_update_preferences(environ=None, settings_path=None):
    """Return provider preferences from the shared WinUX settings file.

    ``update_source`` remains untouched for legacy S:/folder deployments.
    New installations default to the public WinUx repository. Existing folder
    settings keep their source until the user selects GitHub in Settings.
    """
    path = settings_path or _profile_settings_path(environ)
    return update_preferences(_read_settings(path), environ=environ)


def save_update_preferences(provider=None, github_repository=None, channel=None,
                            github_api_base=None, credential_target=None, environ=None,
                            settings_path=None):
    """Persist non-secret updater preferences without erasing existing keys."""
    path = settings_path or _profile_settings_path(environ)
    data = _read_settings(path)
    if provider is not None:
        # Run through the canonical resolver for validation/normalization.
        resolved = update_preferences({UPDATE_PROVIDER_KEY: provider}, environ={})
        data[UPDATE_PROVIDER_KEY] = resolved["provider"]
    if github_repository is not None:
        probe = update_preferences(
            {GITHUB_REPOSITORY_KEY: github_repository}, environ={}
        )
        if probe["github_repository"]:
            data[GITHUB_REPOSITORY_KEY] = probe["github_repository"]
        else:
            data[GITHUB_REPOSITORY_KEY] = ""
    if channel is not None:
        probe = update_preferences({UPDATE_CHANNEL_KEY: channel}, environ={})
        data[UPDATE_CHANNEL_KEY] = probe["channel"]
    if github_api_base is not None:
        value = _text(github_api_base).strip().rstrip("/")
        if value:
            data[GITHUB_API_BASE_KEY] = value
        else:
            data.pop(GITHUB_API_BASE_KEY, None)
    _write_settings(path, data)
    return path


def load_install_mode(environ=None, settings_path=None):
    """Return legacy or versioned install strategy for this launch."""
    path = settings_path or _profile_settings_path(environ)
    return resolve_install_mode(
        _read_settings(path), environ=environ, platform_name=os.name
    )


def save_install_mode(mode, environ=None, settings_path=None):
    """Persist the updater install strategy without touching provider settings."""
    path = settings_path or _profile_settings_path(environ)
    data = _read_settings(path)
    normalized = resolve_install_mode(
        {INSTALL_MODE_KEY: mode}, environ={}, platform_name="nt"
    )
    data[INSTALL_MODE_KEY] = normalized
    _write_settings(path, data)
    return path


def _use_versioned_install(environ=None, settings_path=None):
    path = settings_path or _profile_settings_path(environ)
    return versioned_install_enabled(
        _read_settings(path), environ=environ, platform_name=os.name
    )


def _refresh_active_local(local_dir, environ=None, settings_path=None):
    """Re-resolve the active immutable build after the shared update lock."""
    if not _use_versioned_install(environ=environ, settings_path=settings_path):
        return os.path.abspath(local_dir)
    resolved = resolve_active_installation(local_dir, environ=environ)
    return os.path.abspath(resolved or local_dir)


def _default_sync(source_dir, local_dir, progress_callback=None, health_check=None,
                  environ=None, settings_path=None, source_label=None,
                  before_activate=None):
    """Dispatch to versioned production install or legacy in-place fallback.

    Production Windows versioned installs run the candidate in a separate
    Python process before activation. Tests/non-Windows ports remain injectable
    and do not try to load bundled Windows native modules.
    """
    environ = os.environ if environ is None else environ
    if (health_check is None and os.name == "nt" and
            str(environ.get("WINUX_SKIP_SUBPROCESS_HEALTH_CHECK", "")).strip() != "1"):
        health_check = lambda deployment_dir, manifest: _subprocess_health_check(
            deployment_dir, manifest, environ=environ
        )
    if _use_versioned_install(environ=environ, settings_path=settings_path):
        return _synchronize_versioned_project(
            source_dir, local_dir, progress_callback=progress_callback,
            health_check=health_check, environ=environ, source_label=source_label,
            before_activate=before_activate,
        )
    return _synchronize_project(
        source_dir, local_dir, progress_callback=progress_callback,
        health_check=health_check,
    )


def _sync_result(status, result):
    """Normalize legacy string and versioned dict installer return values."""
    if isinstance(result, dict):
        status["local_version"] = result.get("version") or status.get("local_version")
        status["active_dir"] = result.get("active_dir")
        status["install_mode"] = result.get("mode") or "versioned"
        status["previous_version"] = result.get("previous_version")
        status["bootstrap"] = result.get("bootstrap")
        status["bootstrap_error"] = result.get("bootstrap_error")
        return status["local_version"]
    status["local_version"] = result
    status["active_dir"] = status.get("local_dir")
    status["install_mode"] = "legacy"
    return result


def _read_version_once(path, cache=None):
    if not path:
        return None
    key = os.path.normcase(os.path.abspath(path))
    if cache is not None and key in cache:
        return cache[key]
    version = read_version(path)
    if cache is not None:
        cache[key] = version
    return version


def _normalize_source_candidate(path, version_cache=None):
    if not path:
        return None
    value = os.path.expanduser(os.path.expandvars(_text(path).strip().strip('"')))
    if not value:
        return None
    value = os.path.abspath(value)
    # Flat deployments expose a tiny VERSION file. Do not load a manifest and
    # stat its required files over SMB merely to normalize a source folder.
    if _read_version_once(value, version_cache) or source_is_valid(value):
        return value
    nested = os.path.join(value, "WinUX_Abaqus_Plugin")
    if _read_version_once(nested, version_cache) or source_is_valid(nested):
        return os.path.abspath(nested)
    return value


def _source_path_exists(path):
    """Return True when a candidate update root is reachable.

    This check is intentionally weaker than ``source_is_valid``.  Version
    discovery must not be suppressed just because a manifest is stale or has
    not been republished yet; integrity is enforced later, when an accepted
    update is staged.
    """
    if not path:
        return False
    try:
        return os.path.isdir(os.path.abspath(path))
    except Exception:
        return False


def _source_has_version(path):
    return bool(path and read_version(path))


def _source_is_discoverable(path, version_cache=None):
    if not path:
        return False
    if _read_version_once(path, version_cache):
        return True
    return source_is_valid(path)


def configured_update_source(server_dir=None, environ=None, settings_path=None, _version_cache=None):
    """Resolve the update source for *this* launch.

    Production launches always probe the corporate S: deployment first.  A
    previously saved path is only a fallback when the default S: folder cannot
    be reached.  This prevents a stale ``settings.json`` value from silently
    hiding a newer release on the canonical server.  Explicit arguments and
    ``WINUX_UPDATE_SOURCE`` remain deliberate development/admin overrides.
    """
    environ = os.environ if environ is None else environ

    explicit = server_dir or environ.get("WINUX_UPDATE_SOURCE")
    if explicit:
        return _normalize_source_candidate(explicit, _version_cache)

    default_source = _normalize_source_candidate(DEFAULT_NETWORK_PROJECT_DIR, _version_cache)
    if _source_path_exists(default_source):
        return default_source

    saved = load_update_source(environ=environ, settings_path=settings_path)
    if saved:
        return _normalize_source_candidate(saved, _version_cache)
    return default_source


def get_update_status(local_dir, server_dir=None, environ=None, settings_path=None, _version_cache=None):
    """Describe update availability without copying deployment files.

    Availability is determined from the server ``VERSION`` first on every
    launch.  A stale/missing manifest must never hide the fact that a newer
    version exists.  Manifest validation is reported separately and is used by
    the transactional installer after the user chooses Update Now.
    """
    environ = os.environ if environ is None else environ
    version_cache = {} if _version_cache is None else _version_cache
    if environ.get("WINUX_SKIP_UPDATE", "").strip() == "1":
        server_dir = (server_dir or environ.get("WINUX_UPDATE_SOURCE")
                      or load_update_source(environ, settings_path) or DEFAULT_NETWORK_PROJECT_DIR)
    else:
        server_dir = configured_update_source(
            server_dir=server_dir, environ=environ, settings_path=settings_path,
            _version_cache=version_cache)
    result = {
        "local_dir": os.path.abspath(local_dir),
        "server_dir": os.path.abspath(server_dir or DEFAULT_NETWORK_PROJECT_DIR),
        "local_version": read_version(local_dir),
        "server_version": None,
        "manifest": None,
        "manifest_valid": False,
        "manifest_checked": False,
        "manifest_error": None,
        "release_dir": None,
        "available": False,
        "reason": "",
    }
    if environ.get("WINUX_SKIP_UPDATE", "").strip() == "1":
        result["reason"] = "update check disabled by WINUX_SKIP_UPDATE"
        return result
    if _same_path(local_dir, server_dir):
        result["reason"] = "local and server deployment are the same directory"
        return result

    # VERSION is the discovery signal.  Read it directly so a stale manifest
    # cannot suppress the update dialog.  Strict manifest validation remains a
    # separate concern for installation integrity.
    direct_server_version = _read_version_once(server_dir, version_cache)
    if direct_server_version and result["local_version"]:
        result["server_version"] = direct_server_version
        try:
            if compare_versions(result["local_version"], direct_server_version) >= 0:
                result["reason"] = "local version is current"
                return result
        except ValueError as exc:
            result["reason"] = str(exc)
            return result
    descriptor = None
    result["manifest_checked"] = True
    try:
        descriptor = source_descriptor(server_dir, verify_hashes=False)
        result["manifest"] = descriptor["manifest"]
        result["release_dir"] = descriptor["release_dir"]
        result["manifest_valid"] = True
    except Exception as exc:
        result["manifest_error"] = _text(exc)

    if direct_server_version:
        result["server_version"] = direct_server_version
    elif descriptor is not None:
        # Supports future immutable/versioned roots where VERSION may live only
        # in the release selected by update_manifest.json.
        result["server_version"] = descriptor["version"]
    else:
        result["reason"] = "shared update VERSION is unavailable"
        return result

    local_version = result["local_version"]
    if not local_version:
        result["available"] = True
        result["reason"] = "local VERSION is missing"
        return result
    try:
        result["available"] = compare_versions(local_version, result["server_version"]) < 0
    except ValueError as exc:
        result["reason"] = str(exc)
        return result

    if result["available"]:
        if result["manifest_valid"]:
            result["reason"] = "newer shared version available"
        else:
            result["reason"] = "newer shared VERSION available; manifest will be rebuilt for staging"
    else:
        result["reason"] = "local version is current"
    return result


def _update_log_path(environ=None):
    environ = os.environ if environ is None else environ
    root = environ.get("LOCALAPPDATA") or environ.get("APPDATA") or tempfile.gettempdir()
    directory = os.path.join(root, "WinUx", "logs")
    if not os.path.isdir(directory):
        try:
            os.makedirs(directory)
        except OSError:
            if not os.path.isdir(directory):
                raise
    return os.path.join(directory, "winux_update.log")


UPDATE_LOG_MAX_BYTES = 2 * 1024 * 1024
UPDATE_LOG_KEEP_BYTES = 512 * 1024


def _prune_update_log(path):
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if size <= UPDATE_LOG_MAX_BYTES:
        return
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, size - UPDATE_LOG_KEEP_BYTES))
            tail = handle.read()
        newline = tail.find(b"\n")
        if newline != -1:
            tail = tail[newline + 1:]
        with open(path, "wb") as handle:
            handle.write(b"[WinUx update history truncated; keeping recent entries]\n")
            handle.write(tail)
    except (OSError, IOError):
        pass


def _log(message, environ=None):
    try:
        path = _update_log_path(environ)
        _prune_update_log(path)
        line = "[{}] [pid={}] {}\n".format(
            datetime.datetime.now().isoformat(), os.getpid(), _text(message)
        )
        with open(path, "ab") as handle:
            handle.write(line.encode("utf-8"))
    except Exception:
        pass


def _message_box(title, message, flags):
    if os.name != "nt":
        return 1
    try:
        import ctypes
        return ctypes.windll.user32.MessageBoxW(None, _text(message), _text(title), flags)
    except Exception:
        return 0


def show_update_available(local_version, server_version, server_dir):
    try:
        from winux_update_ui import confirm_update
        return bool(confirm_update(local_version, server_version, server_dir))
    except Exception as exc:
        _log("custom update dialog failed: {}".format(exc))
        message = (
            "A new WinUx version is available.\n\n"
            "Current version: {0}\nNew version: {1}\n\n"
            "Select Yes to update now, or No to use the current local version."
        ).format(local_version or "unknown", server_version or "unknown")
        return _message_box(
            "WinUx Update",
            message,
            0x00000004 | 0x00000040 | 0x00010000 | 0x00002000,
        ) == 6


def prompt_update_source(current_path):
    try:
        from winux_update_ui import prompt_update_source as prompt
        return prompt(current_path)
    except Exception as exc:
        _log("update source dialog failed: {}".format(exc))
        return None


def show_invalid_update_source(path):
    try:
        from winux_update_ui import show_invalid_update_source as show_invalid
        show_invalid(path)
        return
    except Exception:
        pass
    _message_box(
        "WinUx Update Source",
        "The selected folder is not a published WinUx update source.\n\n"
        "It must contain a valid {} and complete release:\n\n{}".format(MANIFEST_FILENAME, path),
        0x00000000 | 0x00000030 | 0x00010000 | 0x00002000,
    )


def create_progress_dialog(local_version, server_version):
    try:
        from winux_update_ui import create_progress_dialog as create_dialog
        dialog = create_dialog(local_version, server_version)
        if os.name == "nt" and dialog is None:
            raise RuntimeError("The WinUx update progress dialog was not created.")
        return dialog
    except Exception as exc:
        _log("progress dialog failed: {}".format(exc))
        # Never perform a silent/invisible update on Windows.  The caller will
        # route this through the normal update-failed path, preserve the local
        # installation, and then start the current WinUx version.
        if os.name == "nt":
            raise
        return None


def show_update_failed(error, local_version):
    message = (
        "WinUx could not install the update.\n\n"
        "{0}\n\n"
        "The existing local version ({1}) will be started instead."
    ).format(error, local_version or "unknown")
    _message_box(
        "WinUx Update",
        message,
        0x00000000 | 0x00000030 | 0x00010000 | 0x00002000,
    )


def show_update_in_progress(local_version):
    _message_box(
        "WinUx Update",
        "Another WinUx instance is already updating this local installation.\n\n"
        "The current local version ({}) will be used for this launch.".format(
            local_version or "unknown"
        ),
        0x00000000 | 0x00000040 | 0x00010000 | 0x00002000,
    )


def _notify_progress(callback, percent, message):
    if callback is None:
        return
    try:
        callback(int(percent), _text(message))
    except Exception as exc:
        _log("progress callback warning: {}".format(exc))


def synchronize_project(server_dir, local_dir, progress_callback=None, health_check=None):
    """Compatibility/public wrapper around the transactional installer."""
    installed = _synchronize_project(
        server_dir,
        local_dir,
        progress_callback=progress_callback,
        health_check=health_check,
    )
    _log("local deployment updated successfully to {}".format(installed))
    return installed


def _resolve_interactive_source(server_dir, environ, settings_path,
                                 source_prompt, invalid_source_dialog, version_cache=None):
    source = configured_update_source(
        server_dir=server_dir,
        environ=environ,
        settings_path=settings_path,
        _version_cache=version_cache,
    )
    if _source_is_discoverable(source, version_cache):
        return source, False
    if environ.get("WINUX_SKIP_UPDATE", "").strip() == "1":
        return source, False

    current = source
    while not _source_is_discoverable(current, version_cache):
        replacement = source_prompt(current)
        if not replacement:
            return current, True
        # User selection is a fresh probe, including when a folder was just
        # published while the source dialog was open.
        if version_cache is not None:
            version_cache.clear()
        candidate = _normalize_source_candidate(replacement)
        if _source_is_discoverable(candidate):
            save_update_source(candidate, environ=environ, settings_path=settings_path)
            _log("saved new update source '{}'".format(candidate), environ)
            return candidate, False
        try:
            invalid_source_dialog(candidate or replacement)
        except Exception:
            pass
        current = candidate or replacement
    return current, False



def _github_status(local_dir, candidate, error=None):
    """Normalize GitHub provider state to the historical updater status shape."""
    source_label = (candidate or {}).get("source_label") or "GitHub Releases"
    status = {
        "local_dir": os.path.abspath(local_dir),
        # ``server_dir`` is retained for update-dialog/API compatibility.  For
        # non-folder providers it is a human-readable source descriptor.
        "server_dir": source_label,
        "source_label": source_label,
        "provider": PROVIDER_GITHUB,
        "github_repository": (candidate or {}).get("repository"),
        "channel": (candidate or {}).get("channel"),
        "prerelease": bool((candidate or {}).get("prerelease")),
        "release_url": (candidate or {}).get("release_url"),
        "published_at": (candidate or {}).get("published_at"),
        "package_sha256": (candidate or {}).get("package_sha256"),
        "local_version": (candidate or {}).get("local_version") or read_version(local_dir),
        "server_version": (candidate or {}).get("server_version"),
        "manifest": None,
        "manifest_valid": False,
        "manifest_checked": False,
        "manifest_error": None,
        "release_dir": None,
        "available": bool((candidate or {}).get("available")),
        "reason": (candidate or {}).get("reason") or "",
        "updated": False,
        "cancelled": False,
        "error": _text(error) if error is not None else None,
        "locked": False,
        "active_dir": os.path.abspath(local_dir),
        "install_mode": None,
    }
    return status


def _scaled_progress(callback, start, end):
    if callback is None:
        return None
    span = max(0, int(end) - int(start))

    def emit(percent, message):
        value = max(0, min(100, int(percent)))
        mapped = int(start) + int((float(value) / 100.0) * span)
        _notify_progress(callback, mapped, message)
    return emit


def _github_provider_from_preferences(preferences, environ=None, provider_factory=None):
    repository = preferences.get("github_repository")
    if not repository:
        raise RuntimeError(
            "GitHub update provider is enabled but github_repository is not configured."
        )
    factory = provider_factory or GitHubReleaseProvider
    return factory(
        repository=repository,
        channel=preferences.get("channel", "stable"),
        api_base=preferences.get("github_api_base"),
        environ=environ,
    )


def _update_local_from_github(local_dir, provider, candidate, environ,
                              dialog_available, dialog_failed, sync_callable,
                              progress_factory, before_sync, lock_factory,
                              health_check, in_progress_dialog, settings_path=None,
                              custom_sync=False):
    """Install one GitHub release using the existing transactional installer."""
    status = _github_status(local_dir, candidate)
    _log(
        "update check provider=github repo={} local_version={} server_version={} available={} reason={}".format(
            candidate.get("repository"), status["local_version"],
            status["server_version"], status["available"], status["reason"]
        ),
        environ,
    )
    if not status["available"]:
        return status

    package_sha256 = _text((candidate or {}).get("package_sha256") or "").strip().lower()
    if is_quarantined(status.get("server_version"), package_sha256, environ=environ):
        status["available"] = False
        status["reason"] = "GitHub release is quarantined after a failed verification/health check"
        status["quarantined"] = True
        _log("skipping quarantined GitHub release {}".format(status.get("server_version")), environ)
        return status

    try:
        accepted = bool(
            dialog_available(
                status["local_version"],
                status["server_version"],
                status["source_label"],
            )
        )
    except Exception as exc:
        _log("GitHub update confirmation failed: {}".format(exc), environ)
        accepted = False
    if not accepted:
        status["cancelled"] = True
        status["reason"] = "update cancelled by user; using local version"
        return status

    progress = None
    lock = None
    materialized = None
    try:
        progress = progress_factory(status["local_version"], status["server_version"])
        progress_callback = getattr(progress, "update", None) if progress is not None else None
        _notify_progress(progress_callback, 0, "Preparing GitHub update...")

        lock_target = (
            versioned_install_root(environ)
            if (not custom_sync and _use_versioned_install(environ, settings_path))
            else status["local_dir"]
        )
        lock = lock_factory(lock_target)
        try:
            lock.acquire()
        except AttributeError:
            lock.__enter__()
        status["locked"] = True

        # Another bootstrap may have activated a newer immutable version while
        # this process waited for the shared installation lock. Re-resolve the
        # active pointer before comparing versions so we never reinstall over a
        # stale process-local path.
        if not custom_sync:
            status["local_dir"] = _refresh_active_local(
                status["local_dir"], environ=environ, settings_path=settings_path
            )
            status["local_version"] = read_version(status["local_dir"])
            status["active_dir"] = status["local_dir"]

        # Release metadata is re-read after acquiring the deployment lock. This
        # prevents an older candidate from being installed after another WinUx
        # bootstrap has already completed an update.
        refreshed_candidate = provider.check(read_version(status["local_dir"]))
        if not refreshed_candidate.get("available"):
            refreshed = _github_status(status["local_dir"], refreshed_candidate)
            status.update(refreshed)
            status["reason"] = "local version became current before installation"
            _notify_progress(progress_callback, 100, "WinUx is already up to date.")
            return status
        refreshed_sha256 = _text(refreshed_candidate.get("package_sha256") or "").strip().lower()
        if is_quarantined(refreshed_candidate.get("server_version"), refreshed_sha256, environ=environ):
            status["available"] = False
            status["quarantined"] = True
            status["reason"] = "GitHub release is quarantined after a failed verification/health check"
            _notify_progress(progress_callback, 100, "Published WinUx build is quarantined; using current version.")
            return status

        # Download/verify while the existing WinUx process can still remain
        # open. It is only terminated immediately before the atomic local swap.
        materialized = provider.materialize(
            refreshed_candidate,
            progress_callback=_scaled_progress(progress_callback, 2, 35),
        )
        status["server_version"] = refreshed_candidate.get("server_version")
        status["release_dir"] = materialized.get("source_dir")
        status["manifest_checked"] = True
        status["manifest_valid"] = True

        versioned_mode = (
            not custom_sync and _use_versioned_install(environ, settings_path)
        )
        if before_sync is not None and not versioned_mode:
            _notify_progress(progress_callback, 36, "Closing the current WinUx instance...")
            before_sync()
        _notify_progress(progress_callback, 38, "Installing verified GitHub release...")
        sync_kwargs = {
            "progress_callback": _scaled_progress(progress_callback, 38, 99),
        }
        if health_check is not None:
            sync_kwargs["health_check"] = health_check
        if custom_sync:
            result = sync_callable(
                materialized["source_dir"], status["local_dir"], **sync_kwargs
            )
        else:
            result = _default_sync(
                materialized["source_dir"], status["local_dir"],
                progress_callback=sync_kwargs.get("progress_callback"),
                health_check=health_check, environ=environ, settings_path=settings_path,
                source_label=status.get("source_label"),
                before_activate=before_sync if versioned_mode else None,
            )
        _sync_result(status, result)
        _notify_progress(progress_callback, 100, "Update complete. Starting WinUx...")
        status["updated"] = True
        status["available"] = False
        status["reason"] = "GitHub release installed and verified successfully"
        try:
            clear_quarantine(status.get("server_version"), environ=environ)
        except Exception:
            pass
        return status
    except UpdateInProgress as exc:
        status["error"] = _text(exc)
        status["reason"] = "another update is in progress; using local version"
        _log(status["reason"], environ)
        if progress is not None:
            try:
                progress.close()
            except Exception:
                pass
            progress = None
        try:
            in_progress_dialog(status["local_version"])
        except Exception:
            pass
        return status
    except Exception as exc:
        status["error"] = _text(exc)
        status["reason"] = "GitHub update failed; local version restored"
        if materialized is not None:
            try:
                quarantine_version(
                    status.get("server_version"),
                    _text((refreshed_candidate or candidate or {}).get("package_sha256") or "").strip().lower(),
                    reason=_text(exc), environ=environ,
                )
                status["quarantined"] = True
            except Exception:
                pass
        _log("GitHub update failed: {}".format(exc), environ)
        if progress is not None:
            try:
                progress.close()
            except Exception:
                pass
            progress = None
        try:
            dialog_failed(exc, status["local_version"])
        except Exception:
            pass
        return status
    finally:
        if materialized is not None:
            try:
                provider.cleanup_materialized(materialized)
            except Exception:
                pass
        if lock is not None and status.get("locked"):
            try:
                lock.release()
            except AttributeError:
                try:
                    lock.__exit__(None, None, None)
                except Exception:
                    pass
            except Exception:
                pass
        if progress is not None:
            try:
                progress.close()
            except Exception:
                pass



def check_for_updates(local_dir, server_dir=None, environ=None, settings_path=None,
                      github_provider_factory=None):
    """Perform an explicit, discovery-only update check.

    This is the Settings > Updates action. It never shows the startup updater,
    never downloads/installs a package, and never changes the active runtime.
    In automatic mode public GitHub is tried first when configured, then the
    legacy S:/shared-folder source remains the compatibility fallback.
    """
    environ = os.environ if environ is None else environ
    local_dir = os.path.abspath(local_dir)
    if environ.get("WINUX_SKIP_UPDATE", "").strip() == "1":
        return {
            "provider": None,
            "local_dir": local_dir,
            "local_version": read_version(local_dir),
            "server_version": None,
            "available": False,
            "reason": "update check disabled by WINUX_SKIP_UPDATE",
            "error": None,
        }

    explicit_folder_source = bool(server_dir or environ.get("WINUX_UPDATE_SOURCE"))
    preferences = load_update_preferences(environ=environ, settings_path=settings_path)

    if should_use_github(preferences, explicit_folder_source=explicit_folder_source):
        try:
            provider = _github_provider_from_preferences(
                preferences, environ=environ, provider_factory=github_provider_factory
            )
            candidate = provider.check(read_version(local_dir))
            return _github_status(local_dir, candidate)
        except Exception as exc:
            _log("manual GitHub update check failed: {}".format(exc), environ)
            if preferences.get("provider") == PROVIDER_GITHUB:
                return _github_status(local_dir, {
                    "provider": PROVIDER_GITHUB,
                    "source_label": "GitHub Releases: {}".format(
                        preferences.get("github_repository") or "not configured"
                    ),
                    "repository": preferences.get("github_repository"),
                    "channel": preferences.get("channel"),
                    "local_version": read_version(local_dir),
                    "server_version": None,
                    "available": False,
                    "reason": "GitHub update check unavailable",
                }, error=exc)
            # Automatic mode deliberately falls through to S:/folder compatibility.

    source = (server_dir or environ.get("WINUX_UPDATE_SOURCE")
              or load_update_source(environ=environ, settings_path=settings_path)
              or DEFAULT_NETWORK_PROJECT_DIR)
    status = get_update_status(
        local_dir,
        server_dir=source,
        environ=environ,
        settings_path=settings_path,
        _version_cache={},
    )
    status["provider"] = PROVIDER_FOLDER
    status["source_label"] = "Legacy shared folder: {}".format(
        status.get("server_dir") or source
    )
    status["legacy_provider"] = True
    status["error"] = (
        status.get("manifest_error") if not status.get("server_version") else None
    )
    return status

def update_local_if_newer(local_dir, server_dir=None, environ=None,
                          dialog_available=None, dialog_failed=None,
                          sync_callable=None, source_prompt=None,
                          invalid_source_dialog=None, progress_factory=None,
                          settings_path=None, before_sync=None,
                          lock_factory=None, health_check=None,
                          in_progress_dialog=None, github_provider_factory=None):
    """Check and transactionally install a published WinUx update.

    Cancel is session-only: it never records a skipped version. A valid update
    is installed only after its manifest-declared files have been staged and
    SHA-256 verified. A deployment-scoped cross-process lock prevents two
    Abaqus instances from swapping the same local folder concurrently.
    """
    environ = os.environ if environ is None else environ
    started = time.time()
    version_cache = {}
    dialog_available = dialog_available or show_update_available
    dialog_failed = dialog_failed or show_update_failed
    custom_sync = sync_callable is not None
    sync_callable = sync_callable or synchronize_project
    source_prompt = source_prompt or prompt_update_source
    invalid_source_dialog = invalid_source_dialog or show_invalid_update_source
    progress_factory = progress_factory or create_progress_dialog
    in_progress_dialog = in_progress_dialog or show_update_in_progress
    lock_factory = lock_factory or (lambda path: UpdateLock(path, environ=environ))

    # Hybrid provider rollout. New installs default to public GitHub; existing
    # saved folder sources retain their compatibility workflow. An
    # explicit folder argument/WINUX_UPDATE_SOURCE always remains an admin
    # override and bypasses GitHub for that launch.
    explicit_folder_source = bool(server_dir or environ.get("WINUX_UPDATE_SOURCE"))
    preferences = load_update_preferences(environ=environ, settings_path=settings_path)
    if (environ.get("WINUX_SKIP_UPDATE", "").strip() != "1" and
            should_use_github(preferences, explicit_folder_source=explicit_folder_source)):
        provider = None
        try:
            provider = _github_provider_from_preferences(
                preferences, environ=environ, provider_factory=github_provider_factory
            )
            candidate = provider.check(read_version(local_dir))
        except Exception as exc:
            _log("GitHub update discovery failed: {}".format(exc), environ)
            if preferences.get("provider") == PROVIDER_GITHUB:
                failed_candidate = {
                    "provider": PROVIDER_GITHUB,
                    "source_label": "GitHub Releases: {}".format(
                        preferences.get("github_repository") or "not configured"
                    ),
                    "repository": preferences.get("github_repository"),
                    "local_version": read_version(local_dir),
                    "server_version": None,
                    "available": False,
                    "reason": "GitHub update check unavailable; using local version",
                }
                return _github_status(local_dir, failed_candidate, error=exc)
            # AUTO is intentionally resilient. If GitHub, internet, proxy or
            # credentials are unavailable, fall through to the historical S:
            # provider so existing corporate deployments remain operational.
            _log("falling back to legacy folder update provider", environ)
        else:
            return _update_local_from_github(
                local_dir, provider, candidate, environ,
                dialog_available, dialog_failed, sync_callable,
                progress_factory, before_sync, lock_factory, health_check,
                in_progress_dialog, settings_path=settings_path,
                custom_sync=custom_sync,
            )

    source, source_cancelled = _resolve_interactive_source(
        server_dir,
        environ,
        settings_path,
        source_prompt,
        invalid_source_dialog,
        version_cache,
    )
    status = get_update_status(
        local_dir,
        server_dir=source,
        environ=environ,
        settings_path=settings_path,
        _version_cache=version_cache,
    )
    _log(
        "update check local={} server={} local_version={} server_version={} available={} reason={} elapsed={:.3f}s manifest_checked={}".format(
            status["local_dir"],
            status["server_dir"],
            status["local_version"],
            status["server_version"],
            status["available"],
            status["reason"],
            max(0.0, time.time() - started),
            status["manifest_checked"],
        ),
        environ,
    )
    status["updated"] = False
    status["cancelled"] = bool(source_cancelled)
    status["error"] = None
    status["locked"] = False
    status["active_dir"] = status["local_dir"]
    status["install_mode"] = None
    if source_cancelled:
        status["reason"] = "update source selection cancelled; using local version"
        return status
    if not status["available"]:
        return status

    try:
        accepted = bool(
            dialog_available(
                status["local_version"],
                status["server_version"],
                status["server_dir"],
            )
        )
    except Exception as exc:
        _log("update confirmation failed: {}".format(exc), environ)
        accepted = False
    if not accepted:
        status["cancelled"] = True
        status["reason"] = "update cancelled by user; using local version"
        _log(status["reason"], environ)
        return status

    progress = None
    lock = None
    try:
        progress = progress_factory(status["local_version"], status["server_version"])
        progress_callback = getattr(progress, "update", None) if progress is not None else None
        _notify_progress(progress_callback, 0, "Preparing update...")

        lock_target = (
            versioned_install_root(environ)
            if (not custom_sync and _use_versioned_install(environ, settings_path))
            else status["local_dir"]
        )
        lock = lock_factory(lock_target)
        try:
            lock.acquire()
        except AttributeError:
            # Test/custom lock factories may return context-manager-only locks.
            lock.__enter__()
        status["locked"] = True

        if not custom_sync:
            status["local_dir"] = _refresh_active_local(
                status["local_dir"], environ=environ, settings_path=settings_path
            )
            status["local_version"] = read_version(status["local_dir"])
            status["active_dir"] = status["local_dir"]

        # Re-check after acquiring the lock. Another updater may have completed
        # between the first status check and this process acquiring the lock.
        refreshed = get_update_status(
            status["local_dir"],
            server_dir=status["server_dir"],
            environ=environ,
            settings_path=settings_path,
        )
        if not refreshed["available"]:
            status.update(refreshed)
            status["updated"] = False
            status["reason"] = "local version became current before installation"
            _notify_progress(progress_callback, 100, "WinUx is already up to date.")
            return status

        versioned_mode = (
            not custom_sync and _use_versioned_install(environ, settings_path)
        )
        if before_sync is not None and not versioned_mode:
            _notify_progress(progress_callback, 1, "Closing the current WinUx instance...")
            before_sync()
        _notify_progress(
            progress_callback, 2,
            "Preparing immutable version..." if versioned_mode else "Starting file synchronization..."
        )
        sync_kwargs = {"progress_callback": progress_callback}
        if health_check is not None:
            sync_kwargs["health_check"] = health_check
        if custom_sync:
            result = sync_callable(
                status["server_dir"], status["local_dir"], **sync_kwargs
            )
        else:
            result = _default_sync(
                status["server_dir"], status["local_dir"],
                progress_callback=progress_callback, health_check=health_check,
                environ=environ, settings_path=settings_path,
                source_label=status.get("server_dir"),
                before_activate=before_sync if versioned_mode else None,
            )
        _sync_result(status, result)
        _notify_progress(progress_callback, 100, "Update complete. Starting WinUx...")
        status["updated"] = True
        status["reason"] = "local version updated and verified successfully"
        return status
    except UpdateInProgress as exc:
        status["error"] = _text(exc)
        status["reason"] = "another update is in progress; using local version"
        _log(status["reason"], environ)
        if progress is not None:
            try:
                progress.close()
            except Exception:
                pass
            progress = None
        try:
            in_progress_dialog(status["local_version"])
        except Exception:
            pass
        return status
    except Exception as exc:
        status["error"] = _text(exc)
        status["reason"] = "update failed; local version restored"
        _log("update failed: {}".format(exc), environ)
        if progress is not None:
            try:
                progress.close()
            except Exception:
                pass
            progress = None
        try:
            dialog_failed(exc, status["local_version"])
        except Exception:
            pass
        return status
    finally:
        if lock is not None and status.get("locked"):
            try:
                lock.release()
            except AttributeError:
                try:
                    lock.__exit__(None, None, None)
                except Exception:
                    pass
            except Exception:
                pass
        if progress is not None:
            try:
                progress.close()
            except Exception:
                pass


__all__ = [
    "DEFAULT_NETWORK_PROJECT_DIR",
    "MANIFEST_FILENAME",
    "SETTINGS_FILENAME",
    "UPDATE_SOURCE_KEY",
    "VERSION_FILENAME",
    "compare_versions",
    "check_for_updates",
    "configured_update_source",
    "create_progress_dialog",
    "get_update_status",
    "load_install_mode",
    "load_update_source",
    "prompt_update_source",
    "read_version",
    "save_install_mode",
    "save_update_source",
    "show_invalid_update_source",
    "show_update_available",
    "show_update_failed",
    "show_update_in_progress",
    "synchronize_project",
    "update_local_if_newer",
]
