from __future__ import annotations

import codecs
import json
import re
import stat
import threading
import time
import uuid
from pathlib import PurePosixPath

from ..runtime import BoundedTextBuffer
from .odb_check import build_remote_odb_check_script, parse_odb_check_output
from .odb_extract import build_remote_odb_extract_script, parse_odb_extract_output
from .odb_history_live import build_remote_odb_history_live_script, parse_live_message


class RemoteODBMixin:
    """Remote Abaqus ODB operations multiplexed over the shared SSH transport."""

    ABAQUS_COMMAND_DIRECTORIES = (
        "/opt/ohpc/pub/apps/simulia/abaqus/Commands",
    )
    # Legacy 2016/2017 releases are intentionally omitted from automatic
    # Plot adapter detection. Installed releases from 2018 onwards are
    # considered, including releases newer than the built-in defaults.
    ABAQUS_MIN_PLOT_RELEASE = 2018

    # SSH multiplexes exec channels over one authenticated transport, so
    # probing several installed releases concurrently collapses wall-clock
    # release detection from the sum of every probe to the slowest probe.
    # The bound keeps pathological candidate lists from flooding a cluster
    # with simultaneous Abaqus Python interpreters.
    ABAQUS_PROBE_CONCURRENCY = 4

    # The next candidate starts while the previous probe is still spinning up
    # its interpreter, but only after this head start. Fast failures (a
    # launcher missing when discovery failed) settle long before the window
    # elapses, so cheap probes stay effectively sequential, while slow
    # release-mismatch interpreters overlap and the wall-clock cost of a
    # several-release fallback chain collapses to roughly one probe.
    ABAQUS_PROBE_STAGGER_SECONDS = 2.0

    @classmethod
    def _race_abaqus_probe_commands(cls, exec_client, client, probes, timeout,
                                    chunk_size=None, stagger=None,
                                    probe_success=None):
        """Run probe shell commands with speculative priority-order racing.

        ``probes`` is a list of ``(candidate, shell_command)`` pairs in
        candidate priority order.  Outcomes map each candidate to
        ``(status, output, error)`` on completion, or to the raised
        exception when the channel itself failed.

        Candidates launch one after the other: the next probe starts as soon
        as its predecessor has settled, or once
        ``ABAQUS_PROBE_STAGGER_SECONDS`` elapse while that predecessor is
        still running its interpreter.  Live probes are bounded by
        ``ABAQUS_PROBE_CONCURRENCY``, so the common single-release case never
        spawns extra interpreters while slow failing chains still race.
        When ``probe_success(outcome)`` matches a completed probe, further
        candidates are not launched: an earlier (higher-priority or
        still-running) probe may also succeed, and the caller selects the
        first success in candidate order.
        """
        pair_count = len(probes)
        chunk_bound = max(1, int(chunk_size or cls.ABAQUS_PROBE_CONCURRENCY))
        stagger = cls.ABAQUS_PROBE_STAGGER_SECONDS if stagger is None \
            else max(0.0, float(stagger))
        outcomes = {}
        failures = {}
        settled = [threading.Event() for _ in range(pair_count)]
        lock = threading.Lock()
        stop = threading.Event()
        slots = threading.BoundedSemaphore(chunk_bound)

        def worker(index, candidate, command):
            try:
                try:
                    status, output, error = exec_client(
                        client, command, timeout=timeout)
                except Exception as exc:
                    with lock:
                        failures[candidate] = exc
                else:
                    with lock:
                        outcomes[candidate] = (status, output, error)
                    if probe_success is not None and probe_success(
                            (status, output, error)):
                        stop.set()
            finally:
                settled[index].set()
                slots.release()

        threads = []
        launched = 0
        for index, (candidate, command) in enumerate(probes):
            if index > 0:
                # Speculative overlap: proceed when the previous probe
                # settled, or after the stagger window if it is still slow.
                settled[index - 1].wait(stagger)
            if stop.is_set():
                break
            slots.acquire()
            if stop.is_set():  # a winner settled while this launch waited
                slots.release()
                break
            thread = threading.Thread(
                target=worker, args=(index, candidate, command),
                name="winux-abq-probe-{}".format(candidate), daemon=True)
            try:
                thread.start()
            except Exception as exc:  # thread exhausted, probe impossible
                with lock:
                    failures[candidate] = exc
                settled[index].set()
                slots.release()
                continue
            threads.append(thread)
        for thread in threads:
            thread.join()
        return outcomes, failures

    @classmethod
    def _abaqus_discovery_script(cls, candidates):
        """Discover executable launchers, not installation targets or qcheck.

        Keep the Commands symlink path: invoking ABQLauncher/SMALauncher
        directly can lose the release-specific launcher environment.
        """
        directories = list(cls.ABAQUS_COMMAND_DIRECTORIES)
        for candidate in candidates:
            if str(candidate).startswith("/"):
                parent = str(PurePosixPath(candidate).parent)
                if parent not in directories:
                    directories.append(parent)
        values = " ".join(cls._shell_quote(value) for value in candidates)
        roots = " ".join(cls._shell_quote(value) for value in directories)
        return (
            "IFS=: read -r -a _winux_path_dirs <<< \"$PATH\"; "
            "for _winux_cmd in {values}; do "
            "if command -v \"$_winux_cmd\" >/dev/null 2>&1; then "
            "printf '__WINUX_ABAQUS_FOUND__%s\\n' \"$_winux_cmd\"; "
            "else for _winux_dir in {roots}; do "
            "if [ -f \"$_winux_dir/$_winux_cmd\" ] && "
            "[ -x \"$_winux_dir/$_winux_cmd\" ]; then "
            "printf '__WINUX_ABAQUS_FOUND__%s\\n' \"$_winux_dir/$_winux_cmd\"; "
            "break; fi; done; fi; done; "
            "for _winux_dir in {roots} \"${{_winux_path_dirs[@]}}\"; do "
            "for _winux_file in \"$_winux_dir\"/abq20* \"$_winux_dir\"/abaqus; do "
            "if [ -f \"$_winux_file\" ] && [ -x \"$_winux_file\" ]; then "
            "printf '__WINUX_ABAQUS_FOUND__%s\\n' \"$_winux_file\"; "
            "fi; done; done"
        ).format(values=values, roots=roots)

    def _available_abaqus_candidates_on(self, client, candidates):
        """Return launchers from the login PATH and known Commands directories.

        Compatibility probing is expensive because every failed candidate can
        start a full Abaqus Python runtime.  Most clusters expose only a small
        subset of WinUx's built-in fallback chain, so first resolve all command
        names with one cheap ``command -v`` and directory scan. A failed lookup
        must NOT turn into expensive probes of every configured/nonexistent
        launcher: the caller may retry discovery when SSH/login recovers.
        """
        candidates = list(candidates or ())
        if not candidates:
            return []

        cache_key = (
            str(self.host or ""),
            str(self.username or ""),
            tuple(candidates),
        )
        now = time.monotonic()
        with self._odb_abaqus_command_cache_lock:
            cached = self._abaqus_available_command_cache.get(cache_key)
        if cached:
            cached_at, available = cached
            if now - float(cached_at) <= self.ABAQUS_DISCOVERY_CACHE_SECONDS:
                return list(available)

        marker = "__WINUX_ABAQUS_FOUND__"
        discovery = self._abaqus_discovery_script(candidates)
        command = self._login_shell_command(discovery)
        try:
            status, output, _error = self._exec_client(
                client, command, timeout=self.ABAQUS_DISCOVERY_TIMEOUT_SECONDS)
        except Exception as exc:
            raise RuntimeError(
                "Unable to detect installed Abaqus versions on the server; "
                "will retry discovery: {}".format(exc)) from exc
        if status != 0:
            raise RuntimeError(
                "Abaqus version discovery failed (exit {}): {}".format(
                    status, str(_error or output or "login shell error")[:200]))

        candidate_set = set(candidates)
        available = []
        for line in str(output or "").splitlines():
            line = line.strip()
            if not line.startswith(marker):
                continue
            value = line[len(marker):].strip()
            launcher = PurePosixPath(value).name
            discovered = (
                value.startswith("/")
                and re.fullmatch(r"[A-Za-z0-9._/+:-]+", value)
                and (launcher == "abaqus" or re.fullmatch(
                    r"abq20\d{2}(?:hf\d+)?", launcher, re.IGNORECASE))
            )
            # Do not probe obsolete 2016/2017 adapters even if they happen
            # to be installed or appear in an older saved preference list.
            match = re.fullmatch(r"(?:abq|abaqus)(20\d{2})(?:hf\d+)?",
                                 launcher, re.IGNORECASE)
            if match and int(match.group(1)) < self.ABAQUS_MIN_PLOT_RELEASE:
                continue
            # PATH names retain precedence over duplicate directory entries.
            if value not in candidate_set and launcher in available:
                continue
            if (value in candidate_set or discovered) and value not in available:
                available.append(value)

        with self._odb_abaqus_command_cache_lock:
            self._abaqus_available_command_cache[cache_key] = (
                now, tuple(available))
        return available

    @staticmethod
    def _prioritize_abaqus_candidates(candidates, *hints):
        """Move valid cached hints to the front without removing fallbacks."""
        candidates = list(candidates or ())
        priority = []
        for hint in hints:
            if hint in candidates and hint not in priority:
                priority.append(hint)
        priority.extend(value for value in candidates if value not in priority)
        return priority

    @staticmethod
    def _newest_first_abaqus_candidates(candidates):
        """Sort explicit releases numerically, retaining custom launchers."""
        def release_key(command):
            launcher = str(command).rsplit("/", 1)[-1]
            match = re.fullmatch(
                r"(?:abq|abaqus)(20\d{2})(?:hf(\d+))?(?:[._-].*)?",
                launcher, re.IGNORECASE)
            if match:
                return (0, -int(match.group(1)), -int(match.group(2) or 0))
            if launcher.casefold() in ("abaqus", "abaqus.bat", "abaqus.cmd", "abaqus.exe"):
                return (2, 0, 0)
            return (1, 0, 0)
        return sorted(candidates or (), key=release_key)

    def _resolve_abaqus_for_odb_on(self, client, path, abaqus_commands=None,
                                 *, newest_first=True, cancel=None):
        """Return the first installed Abaqus release that can open *path*.

        Importing ``odbAccess`` is not enough for ODB compatibility.  A newer
        Abaqus launcher can be present and perfectly usable while refusing an
        ODB created by an older release until that database is upgraded.  Job
        Plots must not upgrade a running solver ODB, so probe the real ODB with
        every configured/fallback release and select the first one for which
        ``openOdb(..., readOnly=True)`` succeeds.

        All ODB tools discover installed launchers first, then invoke their
        Abaqus Python runtimes one at a time in descending release order. Neither the default
        command nor a previous successful ODB/directory/host hint may promote
        an older release. Unversioned/custom launchers are tried afterwards.
        ``newest_first`` is retained for caller compatibility; descending order
        is now mandatory, including when an older caller passes False.
        """
        path = PurePosixPath(str(path))
        all_candidates = self._abaqus_candidate_commands(abaqus_commands)
        all_candidates = self._newest_first_abaqus_candidates(all_candidates)
        candidates = self._available_abaqus_candidates_on(client, all_candidates)
        identity = (str(self.host or ""), str(self.username or ""))
        cache_key = identity + (str(path),)
        directory_key = identity + (str(path.parent),)
        # Sort after discovery too: Commands may contain releases newer than
        # the built-in fallback list. Never promote an older cached success.
        candidates = self._newest_first_abaqus_candidates(candidates)

        if not candidates:
            raise RuntimeError(
                "None of the configured Abaqus commands are available on the "
                "server login PATH or Abaqus Commands directories. Checked: {}. "
                "Update Settings > Abaqus "
                "Versions if the cluster uses a different launcher name."
                .format(", ".join(all_candidates) or "(none)"))

        marker = "__WINUX_ODB_RELEASE_OK__"
        # Keep this one-line probe compatible with Abaqus releases that still
        # embed Python 2.  Passing the path as argv also avoids shell escaping
        # bugs for spaces/special characters in job directories.
        # ``isUpgradeRequiredForOdb`` reads only the compatibility metadata and
        # is substantially cheaper than opening a large database.  Use it as a
        # fast rejection path for newer Abaqus releases before paying the full
        # ``openOdb`` cost.  A False result is still verified with ``openOdb``
        # so older-runtime/newer-ODB cases cannot be accepted accidentally.
        probe_code = (
            "from odbAccess import openOdb,isUpgradeRequiredForOdb; import sys; "
            "p=sys.argv[1]; "
            "needs=isUpgradeRequiredForOdb(upgradeRequiredOdbPath=p); "
            "sys.exit(3) if needs else None; "
            "odb=openOdb(path=p, readOnly=True); "
            "print(%r); odb.close()" % marker
        )
        attempted = []
        # Only the installed releases enter the expensive Abaqus Python probe.
        # Probe strictly newest -> oldest and return as soon as one opens the
        # database. This avoids spinning up several heavy Abaqus interpreters
        # concurrently for a file that the newest installed release can open.
        for candidate in candidates:
            if cancel is not None and cancel.is_set():
                raise RuntimeError("Plot monitor was cancelled")
            probe = "{} python -c {} {}".format(
                candidate, self._shell_quote(probe_code),
                self._shell_quote(path))
            try:
                status, output, error = self._exec_client(
                    client, self._login_shell_command(probe),
                    timeout=self.ABAQUS_PROBE_TIMEOUT_SECONDS)
            except Exception as exc:
                attempted.append("{} ({})".format(candidate, str(exc)[:180]))
                continue
            if status == 0 and marker in output:
                with self._odb_abaqus_command_cache_lock:
                    self._odb_abaqus_command_cache[cache_key] = candidate
                    self._odb_abaqus_directory_hint_cache[directory_key] = candidate
                    self._odb_abaqus_host_hint_cache[identity] = candidate
                return candidate

            detail = (error or output or "exit {}".format(status)).strip()
            if detail:
                lines = [line.strip() for line in detail.splitlines()
                         if line.strip()]
                detail = (lines[-1] if lines else detail)[:180]
                attempted.append("{} ({})".format(candidate, detail))
            else:
                attempted.append(candidate)

        with self._odb_abaqus_command_cache_lock:
            self._odb_abaqus_command_cache.pop(cache_key, None)
        tried = ", ".join(candidates) or "(none)"
        details = "; ".join(attempted[:6])
        message = (
            "No installed Abaqus release could open ODB {}. Tried: {}. "
            "WinUx probes the real database and automatically falls back to "
            "older releases; make sure the release that created this ODB is "
            "available in Settings > Abaqus Versions or on the server PATH."
            .format(path.name, tried)
        )
        if details:
            message += " Probe results: {}".format(details)
        raise RuntimeError(message)

    @staticmethod
    def _self_deleting_remote_python(source):
        """Return a helper script that unlinks itself as soon as it starts.

        Abaqus has already loaded the source by the time module execution begins,
        so unlinking ``__file__`` is safe on the Linux/HPC hosts used by WinUx.
        This prevents long-running realtime ODB monitors from leaving helper
        scripts visible in the user's home directory when WinUx or SSH exits
        unexpectedly.  ``from __future__`` must remain the first statement.
        """
        source = str(source or "")
        marker = "from __future__ import print_function\n"
        cleanup = (
            "import os as _winux_helper_os\n"
            "try:\n"
            "    _winux_helper_os.remove(__file__)\n"
            "except Exception:\n"
            "    pass\n"
        )
        if source.startswith(marker):
            return marker + cleanup + source[len(marker):]
        return cleanup + source

    @staticmethod
    def _cleanup_legacy_odb_helper_scripts(sftp):
        """Remove helper ``.py`` files left by releases before v1.5.36.

        Only generated Python helpers are removed.  Request JSON files are not
        touched because another active WinUx instance may still be consuming
        one.  Unlinking a script already executing under Abaqus is safe on the
        POSIX server side.
        """
        prefixes = (
            ".winux-live-odb-",
            ".winux-check-odb-",
            ".winux-extract-odb-",
        )
        try:
            home = PurePosixPath(sftp.normalize("."))
            names = sftp.listdir(str(home))
        except Exception:
            return
        for name in names:
            text_name = str(name or "")
            if not text_name.endswith(".py"):
                continue
            if not any(text_name.startswith(prefix) for prefix in prefixes):
                continue
            try:
                sftp.remove(str(home / text_name))
            except Exception:
                pass

    @staticmethod
    def _write_remote_odb_temp_file(sftp, filename, payload):
        """Write one generated ODB helper to remote system temp storage.

        ``/tmp`` keeps implementation files out of the browsed home directory
        and is automatically scavenged by the server OS.  A home-directory
        fallback preserves compatibility with restricted systems where SFTP is
        not allowed to write to ``/tmp``.
        """
        filename = str(filename)
        roots = [PurePosixPath("/tmp")]
        try:
            roots.append(PurePosixPath(sftp.normalize(".")))
        except Exception:
            pass
        last_error = None
        for root in roots:
            path = root / filename
            try:
                with sftp.open(str(path), "wb") as stream:
                    stream.write(payload)
                return path
            except Exception as exc:
                last_error = exc
        raise RuntimeError(
            "Unable to create remote WinUx ODB helper: {}".format(
                last_error or "no writable temporary directory"))

    def check_odb(self, path, abaqus_commands=None):
        """Inspect one remote ODB using dedicated channels on the shared SSH link.

        The ODB is never downloaded.  WinUx uploads a short Python-2-compatible
        extractor into the remote user's home directory, runs ``abaqus python``
        against the selected ODB, parses the delimited JSON result and removes
        the temporary script. Dedicated channels keep browsing, job polling
        and the Console responsive without creating another SSH login.
        """
        path = self.normalize(path)
        if path.suffix.casefold() != ".odb":
            raise ValueError("Check ODB requires one .odb file")
        started = time.monotonic()
        with self._auxiliary_session() as (client, sftp):
            try:
                attributes = sftp.stat(str(path))
            except Exception as exc:
                raise RuntimeError(
                    "ODB file is not accessible: {}".format(exc))
            if stat.S_ISDIR(attributes.st_mode):
                raise ValueError("Check ODB requires a file, not a folder")

            executable = self._resolve_abaqus_for_odb_on(
                client, path, abaqus_commands)
            self._cleanup_legacy_odb_helper_scripts(sftp)
            script_name = ".winux-check-odb-{}.py".format(uuid.uuid4().hex)
            script = self._self_deleting_remote_python(
                build_remote_odb_check_script()).encode("utf-8")
            script_path = self._write_remote_odb_temp_file(
                sftp, script_name, script)
            try:
                odb_command = "{} python {} {}".format(
                    executable,
                    self._shell_quote(script_path),
                    self._shell_quote(path),
                )
                command = self._login_shell_command(odb_command)
                status, output, error = self._exec_client(
                    client, command, timeout=self.ODB_CHECK_TIMEOUT_SECONDS)
                combined = "{}\n{}".format(output, error).strip()
                if status != 0 and "__WINUX_ODB_JSON_BEGIN__" not in combined:
                    raise RuntimeError(
                        error or output or
                        "Abaqus ODB check failed with exit code {}".format(
                            status))
                result = parse_odb_check_output(combined)
                result["abaqusCommand"] = executable
                result["analysisSeconds"] = round(
                    max(0.0, time.monotonic() - started), 3)
                result["remoteSize"] = int(attributes.st_size or 0)
                return result
            finally:
                try:
                    sftp.remove(str(script_path))
                except Exception:
                    pass

    def _run_odb_extract_mode(self, path, mode, abaqus_commands=None, items=None):
        """Run selective History Output metadata/data extraction on an aux SSH link."""
        path = self.normalize(path)
        if path.suffix.casefold() != ".odb":
            raise ValueError("ODB data extraction requires one .odb file")
        started = time.monotonic()
        with self._auxiliary_session() as (client, sftp):
            try:
                attributes = sftp.stat(str(path))
            except Exception as exc:
                raise RuntimeError(
                    "ODB file is not accessible: {}".format(exc))
            if stat.S_ISDIR(attributes.st_mode):
                raise ValueError("ODB data extraction requires a file, not a folder")

            executable = self._resolve_abaqus_for_odb_on(
                client, path, abaqus_commands)
            self._cleanup_legacy_odb_helper_scripts(sftp)
            token = uuid.uuid4().hex
            script_name = ".winux-extract-odb-{}.py".format(token)
            request_name = ".winux-extract-odb-{}.json".format(token)
            script = self._self_deleting_remote_python(
                build_remote_odb_extract_script()).encode("utf-8")
            script_path = self._write_remote_odb_temp_file(
                sftp, script_name, script)
            request_path = None
            request_written = False
            try:
                arguments = [
                    executable, "python", self._shell_quote(script_path),
                    self._shell_quote(mode), self._shell_quote(path),
                ]
                # executable and the python token must remain unquoted shell
                # words; script/mode/path are quoted independently below.
                odb_command = "{} python {} {} {}".format(
                    executable,
                    self._shell_quote(script_path),
                    self._shell_quote(mode),
                    self._shell_quote(path),
                )
                if mode == "extract":
                    payload = {"items": list(items or [])}
                    request_path = self._write_remote_odb_temp_file(
                        sftp, request_name,
                        json.dumps(payload).encode("utf-8"))
                    request_written = True
                    odb_command += " {}".format(
                        self._shell_quote(request_path))
                command = self._login_shell_command(odb_command)
                status, output, error = self._exec_client(
                    client, command, timeout=self.ODB_CHECK_TIMEOUT_SECONDS)
                combined = "{}\n{}".format(output, error).strip()
                if status != 0 and "__WINUX_ODB_EXTRACT_JSON_BEGIN__" not in combined:
                    raise RuntimeError(
                        error or output or
                        "Abaqus ODB extract failed with exit code {}".format(
                            status))
                result = parse_odb_extract_output(combined)
                result["abaqusCommand"] = executable
                result["analysisSeconds"] = round(
                    max(0.0, time.monotonic() - started), 3)
                result["remoteSize"] = int(attributes.st_size or 0)
                return result
            finally:
                for temp_path in (script_path, request_path if request_written else None):
                    if temp_path is None:
                        continue
                    try:
                        sftp.remove(str(temp_path))
                    except Exception:
                        pass

    def stream_odb_history(self, path, cancel, selection_provider, on_payload,
                           abaqus_commands=None, interval=1.0,
                           adaptive_settings=None,
                           adaptive_settings_provider=None):
        """Stream live History Output deltas from one remote ODB.

        The remote Abaqus helper uses an adaptive file-change watcher.  It
        checks ODB mtime/size first and only calls ``odb.update()`` / scans
        History Output data when the file actually changed (or the user changed
        the selected series).  This keeps a static/running-but-quiet ODB from
        consuming server CPU and filesystem I/O at a fixed 1 Hz forever.
        """
        path = self.normalize(path)
        if path.suffix.casefold() != ".odb":
            raise ValueError("Realtime History Plot requires one .odb file")
        if cancel is None:
            cancel = threading.Event()
        if not callable(selection_provider):
            raise TypeError("selection_provider must be callable")
        if not callable(on_payload):
            raise TypeError("on_payload must be callable")

        def normalized_adaptive(values):
            values = dict(values or {})
            minimum = max(0.25, float(values.get(
                "min_interval", interval or 1.0)))
            maximum = max(minimum, float(values.get(
                "max_interval", minimum)))
            stable = max(1, int(values.get("stable_samples_to_max", 8)))
            quiet = max(1.0, float(values.get("quiet_seconds_to_max", 180.0)))
            history_alpha = min(1.0, max(0.01, float(values.get(
                "history_alpha", 0.35))))
            prediction_fraction = min(1.0, max(0.05, float(values.get(
                "prediction_fraction", 0.25))))
            confidence_samples = max(1, int(values.get(
                "history_confidence_samples", 3)))
            catalog = max(1, int(values.get("catalog_changed_checks", 5)))
            return {
                "min_interval": minimum,
                "max_interval": maximum,
                "stable_samples_to_max": stable,
                "quiet_seconds_to_max": quiet,
                "history_alpha": history_alpha,
                "prediction_fraction": prediction_fraction,
                "history_confidence_samples": confidence_samples,
                "catalog_changed_checks": catalog,
                # Parent-side scheduling hint only; the remote helper receives
                # the concrete interval numbers, not this WinUx-specific name.
                "inactivity_stage": str(values.get("inactivity_stage") or "active"),
            }

        adaptive = normalized_adaptive(adaptive_settings)

        with self._auxiliary_session() as (client, sftp):
            try:
                attributes = sftp.stat(str(path))
            except Exception as exc:
                raise RuntimeError(
                    "ODB file is not accessible: {}".format(exc))
            if stat.S_ISDIR(attributes.st_mode):
                raise ValueError("Realtime History Plot requires a file")

            on_payload({
                "type": "status", "state": "version-detect",
                "message": "Detecting compatible Abaqus release...",
            })
            executable = self._resolve_abaqus_for_odb_on(
                client, path, abaqus_commands, newest_first=True,
                cancel=cancel)
            on_payload({
                "type": "status", "state": "opening",
                "message": "Opening ODB with {}...".format(executable),
                "abaqusCommand": executable,
            })
            self._cleanup_legacy_odb_helper_scripts(sftp)
            script_name = ".winux-live-odb-{}.py".format(uuid.uuid4().hex)
            script = self._self_deleting_remote_python(
                build_remote_odb_history_live_script()).encode("utf-8")
            script_path = self._write_remote_odb_temp_file(
                sftp, script_name, script)
            channel = None
            try:
                odb_command = (
                    "{} python {} {} {:.3f} {:.3f} {} {:.3f} {:.4f} {:.4f} {} {}".format(
                        executable,
                        self._shell_quote(script_path),
                        self._shell_quote(path),
                        adaptive["min_interval"],
                        adaptive["max_interval"],
                        adaptive["stable_samples_to_max"],
                        adaptive["quiet_seconds_to_max"],
                        adaptive["history_alpha"],
                        adaptive["prediction_fraction"],
                        adaptive["history_confidence_samples"],
                        adaptive["catalog_changed_checks"],
                    )
                )
                command = self._login_shell_command(odb_command)
                transport = client.get_transport()
                if transport is None or not transport.is_active():
                    raise RuntimeError("SSH transport is not active")
                channel = self._open_transport_session(transport)
                channel.exec_command(command)

                decoder = codecs.getincrementaldecoder("utf-8")("replace")
                text_buffer = ""
                stderr_buffer = BoundedTextBuffer(max_chars=64 * 1024)
                last_selection = None
                stop_sent = False
                last_adaptive_text = json.dumps(
                    adaptive, sort_keys=True, separators=(",", ":"))
                next_adaptive_check = time.monotonic() + 0.5

                while True:
                    if cancel.is_set() and not stop_sent:
                        try:
                            channel.sendall(b'{"cmd":"stop"}\n')
                        except Exception:
                            pass
                        stop_sent = True

                    if not cancel.is_set():
                        try:
                            selection = list(selection_provider() or [])
                        except Exception:
                            selection = []
                        selection_text = json.dumps(
                            selection, sort_keys=True, separators=(",", ":"))
                        if selection_text != last_selection:
                            payload = json.dumps(
                                {"cmd": "select", "items": selection},
                                separators=(",", ":"), sort_keys=True,
                            ).encode("utf-8") + b"\n"
                            try:
                                channel.sendall(payload)
                                last_selection = selection_text
                            except Exception:
                                if not cancel.is_set():
                                    raise

                        now = time.monotonic()
                        if (callable(adaptive_settings_provider) and
                                now >= next_adaptive_check):
                            next_adaptive_check = now + 0.5
                            try:
                                latest = normalized_adaptive(
                                    adaptive_settings_provider() or {})
                            except Exception:
                                latest = adaptive
                            latest_text = json.dumps(
                                latest, sort_keys=True, separators=(",", ":"))
                            if latest_text != last_adaptive_text:
                                config_payload = {
                                    "cmd": "config",
                                    "minInterval": latest["min_interval"],
                                    "maxInterval": latest["max_interval"],
                                    "stableChecksToMax": latest["stable_samples_to_max"],
                                    "quietSecondsToMax": latest["quiet_seconds_to_max"],
                                    "historyAlpha": latest["history_alpha"],
                                    "predictionFraction": latest["prediction_fraction"],
                                    "historyConfidenceSamples": latest["history_confidence_samples"],
                                    "catalogChangedChecks": latest["catalog_changed_checks"],
                                }
                                try:
                                    channel.sendall(json.dumps(
                                        config_payload, separators=(",", ":"),
                                        sort_keys=True).encode("utf-8") + b"\n")
                                    adaptive = latest
                                    last_adaptive_text = latest_text
                                except Exception:
                                    if not cancel.is_set():
                                        raise

                    received = False
                    while channel.recv_ready():
                        chunk = channel.recv(128 * 1024)
                        if not chunk:
                            break
                        received = True
                        text_buffer += decoder.decode(chunk)
                        while "\n" in text_buffer:
                            line, text_buffer = text_buffer.split("\n", 1)
                            message = parse_live_message(line)
                            if message is not None:
                                if message.get("type") == "fatal":
                                    raise RuntimeError(
                                        message.get("error") or
                                        "Remote ODB reader failed; retrying")
                                on_payload(message)

                    while channel.recv_stderr_ready():
                        chunk = channel.recv_stderr(32 * 1024)
                        if not chunk:
                            break
                        received = True
                        stderr_buffer.append(
                            chunk.decode("utf-8", "replace"))

                    if channel.exit_status_ready() and not channel.recv_ready():
                        text_buffer += decoder.decode(b"", final=True)
                        if text_buffer.strip():
                            message = parse_live_message(text_buffer.strip())
                            if message is not None:
                                if message.get("type") == "fatal":
                                    raise RuntimeError(
                                        message.get("error") or
                                        "Remote ODB reader failed; retrying")
                                on_payload(message)
                        status = channel.recv_exit_status()
                        if cancel.is_set():
                            return
                        if status != 0:
                            raise RuntimeError(
                                stderr_buffer.snapshot().strip() or
                                "Realtime Abaqus ODB monitor exited with code {}"
                                .format(status))
                        return

                    if cancel.is_set() and stop_sent:
                        cancel.wait(0.08)
                        if channel.exit_status_ready():
                            continue
                        return
                    if not received:
                        stage = str(adaptive.get("inactivity_stage") or "active")
                        local_wait = 0.25 if stage == "deep_idle" else (0.10 if stage == "away" else 0.05)
                        cancel.wait(local_wait)
            finally:
                if channel is not None:
                    try:
                        channel.close()
                    except Exception:
                        pass
                try:
                    sftp.remove(str(script_path))
                except Exception:
                    pass

    def list_odb_history_outputs(self, path, abaqus_commands=None):
        """Return lightweight metadata for every History Output in one ODB."""
        return self._run_odb_extract_mode(
            path, "catalog", abaqus_commands=abaqus_commands)

    def extract_odb_history_data(self, path, items, abaqus_commands=None):
        """Return point data only for the selected History Output entries."""
        return self._run_odb_extract_mode(
            path, "extract", abaqus_commands=abaqus_commands, items=items)

    def _validate_remote_odb_impl(self, path, abaqus_commands=None):
        """Return True/False when Abaqus is available, otherwise None."""
        try:
            executable = self._resolve_abaqus_for_odb_on(
                self.client, path, abaqus_commands)
        except RuntimeError:
            return None

        validator = PurePosixPath(str(path) + ".validate.py")
        script = (
            "from odbAccess import openOdb\n"
            "import sys\n"
            "odb = openOdb(path=sys.argv[1], readOnly=True)\n"
            "odb.close()\n"
        )
        try:
            with self.sftp.open(str(validator), "wb") as stream:
                stream.write(script.encode("utf-8"))
            validate_script = "{} python {} {}".format(
                executable,
                self._shell_quote(validator),
                self._shell_quote(path),
            )
            validate_command = self._login_shell_command(validate_script)
            validate_status, _stdout, _stderr = self._exec_remote(
                validate_command)
            return validate_status == 0
        finally:
            try:
                self.sftp.remove(str(validator))
            except Exception:
                pass
