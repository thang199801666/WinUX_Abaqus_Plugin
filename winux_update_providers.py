"""Update-source providers for WinUx.

The updater historically consumed a published deployment from a corporate
folder (normally the S: drive).  This module adds a GitHub Releases provider
without breaking that workflow.  Provider selection is deliberately kept
standard-library only and Python 2/3 compatible because it runs in the small
bootstrap child before WinUx imports any vendored packages.
"""
from __future__ import print_function

import hashlib
import json
import ntpath
import os
import shutil
import stat
import tempfile
import zipfile

try:  # Python 3
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen
except ImportError:  # Python 2
    from urllib2 import HTTPError, Request, URLError, urlopen

from winux_update_manifest import compare_versions, read_version, source_descriptor, write_manifest

PROVIDER_AUTO = "auto"
PROVIDER_FOLDER = "folder"
PROVIDER_GITHUB = "github"
VALID_PROVIDERS = (PROVIDER_AUTO, PROVIDER_FOLDER, PROVIDER_GITHUB)

DEFAULT_GITHUB_API_BASE = "https://api.github.com"
DEFAULT_GITHUB_REPOSITORY = "thang199801666/WinUX_Abaqus_Plugin"
DEFAULT_UPDATE_CHANNEL = "stable"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_CACHE_KEEP_PACKAGES = 3
DEFAULT_CACHE_MAX_AGE_DAYS = 30
DEFAULT_PARTIAL_MAX_AGE_DAYS = 7
DEFAULT_STAGING_MAX_AGE_HOURS = 24
GITHUB_RELEASE_METADATA_ASSET = "winux-release.json"
GITHUB_PRODUCT_ID = "com.winux.desktop"

UPDATE_PROVIDER_KEY = "update_provider"
GITHUB_REPOSITORY_KEY = "github_repository"
UPDATE_CHANNEL_KEY = "update_channel"
GITHUB_API_BASE_KEY = "github_api_base"


def _text(value):
    try:
        text_type = unicode  # noqa: F821 - Python 2 only
    except NameError:
        text_type = str
    try:
        return text_type(value)
    except Exception:
        return str(value)


def _json_loads(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def normalize_provider(value):
    value = _text(value or PROVIDER_AUTO).strip().lower()
    aliases = {
        "legacy": PROVIDER_FOLDER,
        "network": PROVIDER_FOLDER,
        "s": PROVIDER_FOLDER,
        "s-drive": PROVIDER_FOLDER,
        "github-releases": PROVIDER_GITHUB,
        "releases": PROVIDER_GITHUB,
    }
    value = aliases.get(value, value)
    if value not in VALID_PROVIDERS:
        raise ValueError("Unsupported WinUx update provider: {}".format(value))
    return value


def normalize_channel(value):
    value = _text(value or DEFAULT_UPDATE_CHANNEL).strip().lower()
    if value in ("release", "stable", "production"):
        return "stable"
    if value in ("beta", "prerelease", "preview"):
        return "beta"
    raise ValueError("Unsupported WinUx update channel: {}".format(value))


def normalize_github_repository(value):
    """Return ``owner/repository`` from a short name or GitHub URL."""
    value = _text(value or "").strip().strip("/")
    if not value:
        return None
    lower = value.lower()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if lower.startswith(prefix):
            value = value[len(prefix):].strip("/")
            break
    if value.lower().endswith(".git"):
        value = value[:-4]
    pieces = [piece for piece in value.split("/") if piece]
    if len(pieces) != 2:
        raise ValueError(
            "GitHub repository must use owner/repository format: {}".format(value)
        )
    owner, repository = pieces
    if any(ch in owner + repository for ch in "\\?#"):
        raise ValueError("Invalid GitHub repository: {}".format(value))
    return owner + "/" + repository


def update_preferences(settings=None, environ=None):
    """Resolve provider preferences while preserving legacy settings.

    Existing users that only have ``update_source`` continue to use the folder
    provider. New installations use the public WinUx repository in auto mode.
    An explicitly empty repository disables GitHub discovery in auto mode.
    """
    settings = settings if isinstance(settings, dict) else {}
    environ = os.environ if environ is None else environ

    provider_raw = environ.get("WINUX_UPDATE_PROVIDER")
    if provider_raw is None:
        provider_raw = settings.get(UPDATE_PROVIDER_KEY, PROVIDER_AUTO)
    provider = normalize_provider(provider_raw)

    repository_raw = environ.get("WINUX_GITHUB_REPOSITORY")
    if repository_raw is None:
        default_repository = DEFAULT_GITHUB_REPOSITORY
        if settings.get("update_source") and provider != PROVIDER_GITHUB:
            default_repository = None
        repository_raw = settings.get(GITHUB_REPOSITORY_KEY, default_repository)
    repository = normalize_github_repository(repository_raw) if repository_raw else None

    channel_raw = environ.get("WINUX_UPDATE_CHANNEL")
    if channel_raw is None:
        channel_raw = settings.get(UPDATE_CHANNEL_KEY, DEFAULT_UPDATE_CHANNEL)
    channel = normalize_channel(channel_raw)

    api_base = environ.get("WINUX_GITHUB_API_BASE") or settings.get(
        GITHUB_API_BASE_KEY, DEFAULT_GITHUB_API_BASE
    )
    api_base = _text(api_base or DEFAULT_GITHUB_API_BASE).strip().rstrip("/")

    return {
        "provider": provider,
        "github_repository": repository,
        "channel": channel,
        "github_api_base": api_base,
    }


def should_use_github(preferences, explicit_folder_source=False):
    if explicit_folder_source:
        return False
    provider = normalize_provider(preferences.get("provider"))
    repository = preferences.get("github_repository")
    if provider == PROVIDER_FOLDER:
        return False
    if provider == PROVIDER_GITHUB:
        return True
    return bool(repository)


def _response_bytes(response):
    try:
        return response.read()
    finally:
        try:
            response.close()
        except Exception:
            pass


def _asset_name(asset):
    return _text((asset or {}).get("name", "")).strip()


def _sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value):
    value = _text(value or "").strip().lower()
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _safe_zip_member(name):
    portable = _text(name).replace("\\", "/")
    if not portable or portable.endswith("/"):
        return portable
    if portable.startswith("/") or portable.startswith("\\"):
        raise RuntimeError("Unsafe absolute path in GitHub update package: {}".format(name))
    drive, _tail = ntpath.splitdrive(portable)
    if drive:
        raise RuntimeError("Unsafe drive-qualified path in GitHub update package: {}".format(name))
    normalized = os.path.normpath(portable.replace("/", os.sep))
    if normalized == os.pardir or normalized.startswith(os.pardir + os.sep):
        raise RuntimeError("Unsafe parent path in GitHub update package: {}".format(name))
    return normalized


def _zip_member_is_symlink(info):
    mode = (int(getattr(info, "external_attr", 0)) >> 16) & 0xFFFF
    return bool(mode and stat.S_ISLNK(mode))


def safe_extract_zip(zip_path, destination):
    """Extract a release ZIP without path traversal or symlink entries."""
    destination = os.path.abspath(destination)
    if not os.path.isdir(destination):
        os.makedirs(destination)
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            if _zip_member_is_symlink(info):
                raise RuntimeError(
                    "Symlinks are not allowed in WinUx update packages: {}".format(info.filename)
                )
            relative = _safe_zip_member(info.filename)
            if not relative:
                continue
            target = os.path.abspath(os.path.join(destination, relative))
            prefix = destination + os.sep
            if target != destination and not target.startswith(prefix):
                raise RuntimeError("Unsafe path in GitHub update package: {}".format(info.filename))
            if info.filename.endswith("/"):
                if not os.path.isdir(target):
                    os.makedirs(target)
                continue
            parent = os.path.dirname(target)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent)
            source = archive.open(info, "r")
            try:
                with open(target, "wb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
            finally:
                source.close()
    return destination


def _deployment_candidates(extract_dir):
    extract_dir = os.path.abspath(extract_dir)
    candidates = [extract_dir]
    try:
        first_level = sorted(os.listdir(extract_dir))
    except OSError:
        first_level = []
    for name in first_level:
        path = os.path.join(extract_dir, name)
        if os.path.isdir(path):
            candidates.append(path)
            nested = os.path.join(path, "WinUX_Abaqus_Plugin")
            if os.path.isdir(nested):
                candidates.append(nested)
    return candidates


def find_deployment_root(extract_dir):
    for candidate in _deployment_candidates(extract_dir):
        if read_version(candidate) and os.path.isfile(
            os.path.join(candidate, "WinUx", "__main__.py")
        ):
            return os.path.abspath(candidate)
    raise RuntimeError("GitHub package does not contain a complete WinUx deployment.")


class GitHubReleaseProvider(object):
    """Discover and materialize immutable WinUx GitHub Release packages."""

    def __init__(self, repository, channel="stable",
                 api_base=DEFAULT_GITHUB_API_BASE, timeout=DEFAULT_TIMEOUT_SECONDS,
                 opener=None, cache_dir=None, environ=None):
        self.repository = normalize_github_repository(repository)
        if not self.repository:
            raise ValueError("A GitHub repository is required for the GitHub update provider.")
        self.channel = normalize_channel(channel)
        self.api_base = _text(api_base or DEFAULT_GITHUB_API_BASE).strip().rstrip("/")
        self.timeout = float(timeout or DEFAULT_TIMEOUT_SECONDS)
        self.opener = opener
        self.environ = os.environ if environ is None else environ
        self.cache_dir = cache_dir or self._default_cache_dir()

    @property
    def source_label(self):
        return "GitHub Releases: {} ({})".format(self.repository, self.channel)

    def _default_cache_dir(self):
        root = (
            self.environ.get("LOCALAPPDATA")
            or self.environ.get("APPDATA")
            or tempfile.gettempdir()
        )
        return os.path.join(root, "WinUx", "cache", "updates")

    def _request(self, url, accept="application/vnd.github+json"):
        headers = {
            "User-Agent": "WinUx-Updater",
            "Accept": accept,
        }
        return Request(url, headers=headers)

    def _open(self, request):
        try:
            if self.opener is not None:
                try:
                    return self.opener(request, self.timeout)
                except TypeError:
                    return self.opener(request)
            return urlopen(request, timeout=self.timeout)
        except HTTPError as exc:
            raise RuntimeError(
                "GitHub returned HTTP {} for {}".format(getattr(exc, "code", "?"), self.repository)
            )
        except URLError as exc:
            raise RuntimeError("GitHub is unavailable: {}".format(getattr(exc, "reason", exc)))
        except Exception as exc:
            raise RuntimeError("GitHub request failed: {}".format(exc))

    def _get_json(self, url):
        payload = _response_bytes(self._open(self._request(url)))
        try:
            return _json_loads(payload)
        except Exception as exc:
            raise RuntimeError("GitHub returned invalid JSON: {}".format(exc))

    def _download_bytes(self, asset):
        url = asset.get("browser_download_url") or asset.get("url")
        if not url:
            raise RuntimeError("GitHub release asset has no download URL: {}".format(_asset_name(asset)))
        accept = "application/octet-stream" if asset.get("url") == url else "application/octet-stream"
        return _response_bytes(self._open(self._request(url, accept=accept)))

    def _list_releases(self):
        url = "{}/repos/{}/releases?per_page=20".format(self.api_base, self.repository)
        releases = self._get_json(url)
        if not isinstance(releases, list):
            raise RuntimeError("GitHub release API did not return a release list.")
        return releases

    def _select_release(self, releases):
        """Return the highest semantic version allowed by the channel policy.

        Stable never consumes GitHub prereleases. Beta/preview consumes the
        newest release regardless of prerelease flag, so a stable release may
        still supersede an older beta. Invalid/non-semantic tags are ignored
        instead of breaking update discovery for every user.
        """
        selected = None
        selected_version = None
        for release in releases:
            if not isinstance(release, dict) or release.get("draft"):
                continue
            if self.channel == "stable" and release.get("prerelease"):
                continue
            try:
                version = self._version_from_release(release)
            except Exception:
                continue
            if selected is None or compare_versions(selected_version, version) < 0:
                selected = release
                selected_version = version
        return selected

    def _version_from_release(self, release):
        tag = _text(release.get("tag_name", "")).strip()
        if not tag:
            raise RuntimeError("GitHub release has no tag_name.")
        if tag.lower().startswith("winux-"):
            tag = tag[len("WinUx-"):]
        version = tag[1:] if tag[:1].lower() == "v" else tag
        # compare_versions validates the syntax without requiring another parser.
        compare_versions(version, version)
        return version

    @staticmethod
    def _asset_map(release):
        result = {}
        for asset in release.get("assets") or []:
            name = _asset_name(asset)
            if name:
                result[name.lower()] = asset
        return result

    def _metadata_contract(self, release, release_version):
        assets = self._asset_map(release)
        metadata_asset = assets.get(GITHUB_RELEASE_METADATA_ASSET.lower())
        if metadata_asset is not None:
            metadata = _json_loads(self._download_bytes(metadata_asset))
            if not isinstance(metadata, dict):
                raise RuntimeError("{} must contain a JSON object.".format(GITHUB_RELEASE_METADATA_ASSET))
            schema_version = int(metadata.get("schema_version", 1))
            if schema_version not in (1, 2):
                raise RuntimeError("Unsupported WinUx GitHub release schema: {}".format(schema_version))
            product_id = metadata.get("product_id")
            if product_id and _text(product_id) != GITHUB_PRODUCT_ID:
                raise RuntimeError("GitHub release product_id does not describe WinUx.")
            metadata_channel = metadata.get("channel")
            if metadata_channel:
                metadata_channel = normalize_channel(metadata_channel)
                # A GitHub prerelease is never valid stable-channel content.
                if release.get("prerelease") and metadata_channel != "beta":
                    raise RuntimeError("GitHub prerelease metadata must use the beta channel.")
                # Stable clients never reach prereleases; beta clients may also
                # consume stable releases when stable is the newer build.
                if self.channel == "stable" and metadata_channel != "stable":
                    raise RuntimeError("Stable update channel rejected non-stable release metadata.")
            metadata_version = _text(metadata.get("version", release_version)).strip()
            if compare_versions(metadata_version, release_version) != 0:
                raise RuntimeError(
                    "GitHub release metadata version {} does not match tag {}.".format(
                        metadata_version, release_version
                    )
                )
            package = metadata.get("package") or {}
            package_name = _text(
                package.get("asset") or package.get("name") or metadata.get("asset") or ""
            ).strip()
            package_sha256 = _text(
                package.get("sha256") or metadata.get("sha256") or ""
            ).strip().lower()
            if not package_name or package_name.lower() not in assets:
                raise RuntimeError("GitHub release metadata references a missing WinUx package asset.")
            if not _valid_sha256(package_sha256):
                raise RuntimeError("GitHub release metadata has an invalid package SHA-256.")
            return metadata, assets[package_name.lower()], package_sha256

        # Manual GitHub uploads may use WinUx-<version>.zip. GitHub's asset
        # digest is an alternative integrity contract to a sibling .sha256.
        package_asset = None
        manual_package_name = "WinUx-{}.zip".format(release_version).lower()
        for asset in release.get("assets") or []:
            name = _asset_name(asset)
            if name.lower().endswith("_full.zip") or (
                name.lower().endswith(".zip") and "full" in name.lower()
            ) or name.lower() == manual_package_name:
                package_asset = asset
                break
        if package_asset is None:
            raise RuntimeError(
                "GitHub release is missing {} or a WinUx FULL.zip/WinUx-<version>.zip asset.".format(
                    GITHUB_RELEASE_METADATA_ASSET
                )
            )
        package_name = _asset_name(package_asset)
        checksum_asset = assets.get((package_name + ".sha256").lower())
        if checksum_asset is None:
            digest = _text(package_asset.get("digest") or "").strip().lower()
            checksum = digest[len("sha256:"):] if digest.startswith("sha256:") else ""
            if not _valid_sha256(checksum):
                raise RuntimeError(
                    "GitHub release package {} has no SHA-256 metadata or valid GitHub asset digest.".format(package_name)
                )
        else:
            checksum_text = _text(self._download_bytes(checksum_asset).decode("utf-8", "ignore")).strip()
            checksum = checksum_text.split()[0].lower() if checksum_text else ""
        if not _valid_sha256(checksum):
            raise RuntimeError("GitHub release checksum asset is invalid: {}".format(_asset_name(checksum_asset)))
        metadata = {
            "schema_version": 1,
            "product_id": GITHUB_PRODUCT_ID,
            "version": release_version,
            "package": {"asset": package_name, "sha256": checksum},
        }
        return metadata, package_asset, checksum

    def check(self, local_version):
        release = self._select_release(self._list_releases())
        if release is None:
            return {
                "provider": PROVIDER_GITHUB,
                "source_label": self.source_label,
                "repository": self.repository,
                "local_version": local_version,
                "server_version": None,
                "available": False,
                "reason": "no GitHub release is published for channel {}".format(self.channel),
            }
        server_version = self._version_from_release(release)
        metadata, package_asset, package_sha256 = self._metadata_contract(release, server_version)
        assets = self._asset_map(release)
        github_digest_contract = (
            GITHUB_RELEASE_METADATA_ASSET.lower() not in assets
            and (_asset_name(package_asset) + ".sha256").lower() not in assets
        )
        available = True if not local_version else compare_versions(local_version, server_version) < 0
        return {
            "provider": PROVIDER_GITHUB,
            "source_label": self.source_label,
            "repository": self.repository,
            "channel": self.channel,
            "local_version": local_version,
            "server_version": server_version,
            "available": bool(available),
            "reason": (
                "newer GitHub release available" if available else "local version is current"
            ),
            "release": release,
            "release_metadata": metadata,
            "package_asset": package_asset,
            "package_sha256": package_sha256,
            "github_digest_contract": github_digest_contract,
            "prerelease": bool(release.get("prerelease")),
            "release_url": release.get("html_url"),
            "published_at": release.get("published_at") or release.get("created_at"),
        }

    def _ensure_cache(self):
        if not os.path.isdir(self.cache_dir):
            try:
                os.makedirs(self.cache_dir)
            except OSError:
                if not os.path.isdir(self.cache_dir):
                    raise

    def _download_asset_to_file(self, asset, target, expected_sha256, progress_callback=None):
        """Download a public release asset with a resumable .partial cache."""
        self._ensure_cache()
        partial = target + ".partial"
        expected_size = int(asset.get("size") or 0)
        offset = 0
        if os.path.isfile(partial):
            try:
                offset = int(os.path.getsize(partial))
            except OSError:
                offset = 0
        if expected_size and offset > expected_size:
            try:
                os.remove(partial)
            except OSError:
                pass
            offset = 0

        url = asset.get("browser_download_url") or asset.get("url")
        if not url:
            raise RuntimeError("GitHub package asset has no download URL.")
        request = self._request(url, accept="application/octet-stream")
        if offset > 0:
            try:
                request.add_header("Range", "bytes={}-".format(offset))
            except Exception:
                offset = 0
        response = self._open(request)

        # If GitHub/CDN ignores Range and returns a full 200 response, restart
        # from byte zero instead of appending duplicate content.
        status_code = getattr(response, "status", None) or getattr(response, "code", None)
        content_range = None
        try:
            content_range = response.headers.get("Content-Range")
        except Exception:
            pass
        resumed = bool(offset and (status_code == 206 or content_range))
        if offset and not resumed:
            offset = 0
        mode = "ab" if resumed else "wb"
        copied = offset
        try:
            with open(partial, mode) as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    copied += len(chunk)
                    if progress_callback is not None:
                        if expected_size > 0:
                            percent = min(85, int((float(copied) / float(expected_size)) * 85.0))
                        else:
                            percent = 20
                        message = "Resuming {}..." if resumed else "Downloading {}..."
                        progress_callback(percent, message.format(_asset_name(asset)))
        finally:
            try:
                response.close()
            except Exception:
                pass

        # Keep an incomplete partial for the next launch; only corrupt/oversized
        # content is discarded.
        if expected_size and copied != expected_size:
            raise RuntimeError(
                "GitHub package download is incomplete ({} of {} bytes); it will resume next time.".format(
                    copied, expected_size
                )
            )
        actual = _sha256_file(partial)
        if actual.lower() != expected_sha256.lower():
            try:
                os.remove(partial)
            except OSError:
                pass
            raise RuntimeError("GitHub package SHA-256 verification failed.")
        if os.path.exists(target):
            try:
                os.remove(target)
            except OSError:
                pass
        os.rename(partial, target)
        if progress_callback is not None:
            progress_callback(88, "GitHub package verified.")
        return target

    def _cache_policy(self):
        def positive_int(name, default):
            try:
                value = int(self.environ.get(name, default))
            except (TypeError, ValueError):
                value = int(default)
            return max(0, value)
        return {
            "keep_packages": positive_int("WINUX_UPDATE_CACHE_KEEP", DEFAULT_CACHE_KEEP_PACKAGES),
            "package_max_age_days": positive_int("WINUX_UPDATE_CACHE_DAYS", DEFAULT_CACHE_MAX_AGE_DAYS),
            "partial_max_age_days": positive_int("WINUX_UPDATE_PARTIAL_DAYS", DEFAULT_PARTIAL_MAX_AGE_DAYS),
            "staging_max_age_hours": positive_int("WINUX_UPDATE_STAGING_HOURS", DEFAULT_STAGING_MAX_AGE_HOURS),
        }

    @staticmethod
    def _older_than(path, max_age_seconds, now=None):
        if max_age_seconds <= 0:
            return False
        try:
            age = float((now if now is not None else __import__("time").time())) - float(os.path.getmtime(path))
            return age > float(max_age_seconds)
        except (OSError, TypeError, ValueError):
            return False

    def cleanup_cache(self, keep_packages=None, package_max_age_days=None,
                      partial_max_age_days=None, staging_max_age_hours=None, now=None):
        """Apply bounded + age-based cache retention.

        Verified packages are capped by count and age, stale resumable partials
        expire independently, and only abandoned staging directories older than
        the staging TTL are removed. The policy can be overridden by environment
        variables for enterprise deployments without adding user-facing clutter.
        """
        self._ensure_cache()
        policy = self._cache_policy()
        if keep_packages is None:
            keep_packages = policy["keep_packages"]
        if package_max_age_days is None:
            package_max_age_days = policy["package_max_age_days"]
        if partial_max_age_days is None:
            partial_max_age_days = policy["partial_max_age_days"]
        if staging_max_age_hours is None:
            staging_max_age_hours = policy["staging_max_age_hours"]

        removed = []
        staging = os.path.join(self.cache_dir, "staging")
        if os.path.isdir(staging):
            ttl = int(staging_max_age_hours) * 60 * 60
            for name in os.listdir(staging):
                path = os.path.join(staging, name)
                if os.path.isdir(path) and self._older_than(path, ttl, now=now):
                    try:
                        shutil.rmtree(path)
                        removed.append(path)
                    except Exception:
                        pass

        partial_ttl = int(partial_max_age_days) * 24 * 60 * 60
        packages = []
        for name in os.listdir(self.cache_dir):
            path = os.path.join(self.cache_dir, name)
            if not os.path.isfile(path):
                continue
            lower = name.lower()
            if lower.endswith(".partial"):
                if self._older_than(path, partial_ttl, now=now):
                    try:
                        os.remove(path)
                        removed.append(path)
                    except OSError:
                        pass
                continue
            if lower.endswith(".zip"):
                try:
                    packages.append((os.path.getmtime(path), path))
                except OSError:
                    pass

        packages.sort(reverse=True)
        package_ttl = int(package_max_age_days) * 24 * 60 * 60
        keep_packages = max(0, int(keep_packages))
        for index, (_mtime, path) in enumerate(packages):
            expired = self._older_than(path, package_ttl, now=now)
            over_limit = index >= keep_packages
            if not (expired or over_limit):
                continue
            try:
                os.remove(path)
                removed.append(path)
            except OSError:
                pass
        return removed

    def materialize(self, candidate, progress_callback=None):
        """Download, verify and safely extract a candidate release.

        Returns a dict with ``source_dir`` plus ``cleanup_dir``.  The existing
        transactional installer then performs its normal per-file manifest
        verification and atomic local-directory swap.
        """
        asset = candidate.get("package_asset") or {}
        checksum = candidate.get("package_sha256")
        if not asset or not _valid_sha256(checksum):
            raise RuntimeError("GitHub update candidate is missing verified package metadata.")
        self._ensure_cache()
        try:
            self.cleanup_cache()
        except Exception:
            pass
        package_name = _asset_name(asset)
        target = os.path.join(self.cache_dir, package_name)
        if os.path.isfile(target) and _sha256_file(target).lower() == checksum.lower():
            if progress_callback is not None:
                progress_callback(88, "Using verified cached GitHub package.")
        else:
            self._download_asset_to_file(asset, target, checksum, progress_callback)

        extract_parent = os.path.join(self.cache_dir, "staging")
        if not os.path.isdir(extract_parent):
            os.makedirs(extract_parent)
        extract_dir = tempfile.mkdtemp(prefix="winux_github_", dir=extract_parent)
        try:
            if progress_callback is not None:
                progress_callback(90, "Extracting GitHub update package...")
            safe_extract_zip(target, extract_dir)
            source_dir = find_deployment_root(extract_dir)
            packaged_version = read_version(source_dir)
            if compare_versions(packaged_version, candidate["server_version"]) != 0:
                raise RuntimeError(
                    "GitHub package VERSION {} does not match release {}.".format(
                        packaged_version, candidate["server_version"]
                    )
                )
            if candidate.get("github_digest_contract"):
                # Manual uploads can contain a stale development manifest.
                # The complete ZIP was already verified against GitHub's SHA-256;
                # generate the per-file install contract only inside staging.
                write_manifest(source_dir)
            if progress_callback is not None:
                progress_callback(94, "Validating GitHub release manifest...")
            descriptor = source_descriptor(source_dir, verify_hashes=True)
            packaged_version = descriptor["version"]
            if compare_versions(packaged_version, candidate["server_version"]) != 0:
                raise RuntimeError(
                    "GitHub package VERSION {} does not match release {}.".format(
                        packaged_version, candidate["server_version"]
                    )
                )
            if progress_callback is not None:
                progress_callback(100, "GitHub release is ready to install.")
            return {
                "source_dir": source_dir,
                "cleanup_dir": extract_dir,
                "package_path": target,
                "descriptor": descriptor,
            }
        except Exception:
            try:
                shutil.rmtree(extract_dir)
            except Exception:
                pass
            raise

    @staticmethod
    def cleanup_materialized(materialized):
        cleanup_dir = (materialized or {}).get("cleanup_dir")
        if cleanup_dir and os.path.isdir(cleanup_dir):
            try:
                shutil.rmtree(cleanup_dir)
            except Exception:
                pass


__all__ = [
    "DEFAULT_GITHUB_API_BASE",
    "DEFAULT_GITHUB_REPOSITORY",
    "DEFAULT_CACHE_KEEP_PACKAGES",
    "DEFAULT_CACHE_MAX_AGE_DAYS",
    "DEFAULT_PARTIAL_MAX_AGE_DAYS",
    "DEFAULT_STAGING_MAX_AGE_HOURS",
    "DEFAULT_UPDATE_CHANNEL",
    "GITHUB_API_BASE_KEY",
    "GITHUB_PRODUCT_ID",
    "GITHUB_RELEASE_METADATA_ASSET",
    "GITHUB_REPOSITORY_KEY",
    "GitHubReleaseProvider",
    "PROVIDER_AUTO",
    "PROVIDER_FOLDER",
    "PROVIDER_GITHUB",
    "UPDATE_CHANNEL_KEY",
    "UPDATE_PROVIDER_KEY",
    "find_deployment_root",
    "normalize_channel",
    "normalize_github_repository",
    "normalize_provider",
    "safe_extract_zip",
    "should_use_github",
    "update_preferences",
]
