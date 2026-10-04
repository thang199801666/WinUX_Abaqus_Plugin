from __future__ import annotations

import codecs
import json
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

    def _resolve_abaqus_for_odb_on(self, client, path, abaqus_commands=None):
        """Return the first installed Abaqus release that can open *path*.

        Importing ``odbAccess`` is not enough for ODB compatibility.  A newer
        Abaqus launcher can be present and perfectly usable while refusing an
        ODB created by an older release until that database is upgraded.  Job
        Plots must not upgrade a running solver ODB, so probe the real ODB with
        every configured/fallback release and select the first one for which
        ``openOdb(..., readOnly=True)`` succeeds.

        The configured default (normally ``abq2026``) remains the first
        candidate.  If it cannot open the ODB WinUx automatically falls back
        through ``abq2025``, ``abq2024``, ``abq2023`` ... and finally the
        generic ``abaqus`` launcher.
        """
        path = PurePosixPath(str(path))
        candidates = self._abaqus_candidate_commands(abaqus_commands)
        cache_key = (str(self.host or ""), str(self.username or ""), str(path))
        with self._odb_abaqus_command_cache_lock:
            cached = self._odb_abaqus_command_cache.get(cache_key)
        if cached in candidates:
            candidates.remove(cached)
            candidates.insert(0, cached)

        marker = "__WINUX_ODB_RELEASE_OK__"
        # Keep this one-line probe compatible with Abaqus releases that still
        # embed Python 2.  Passing the path as argv also avoids shell escaping
        # bugs for spaces/special characters in job directories.
        probe_code = (
            "from odbAccess import openOdb; import sys; "
            "odb=openOdb(path=sys.argv[1], readOnly=True); "
            "print(%r); odb.close()" % marker
        )
        attempted = []
        for candidate in candidates:
            probe = "{} python -c {} {}".format(
                candidate, self._shell_quote(probe_code),
                self._shell_quote(path))
            command = self._login_shell_command(probe)
            try:
                status, output, error = self._exec_client(
                    client, command, timeout=self.ABAQUS_PROBE_TIMEOUT_SECONDS)
            except Exception as exc:
                attempted.append("{} ({})".format(candidate, exc))
                continue
            if status == 0 and marker in output:
                with self._odb_abaqus_command_cache_lock:
                    self._odb_abaqus_command_cache[cache_key] = candidate
                return candidate

            detail = (error or output or "exit {}".format(status)).strip()
            if detail:
                # Abaqus often prints a long banner before the useful release
                # mismatch message.  Keep only the final non-empty line in the
                # user-facing retry/error summary.
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
                client, path, abaqus_commands)
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
                next_adaptive_check = time.monotonic() + 2.0

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
                            next_adaptive_check = now + 2.0
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
                        cancel.wait(0.05)
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

