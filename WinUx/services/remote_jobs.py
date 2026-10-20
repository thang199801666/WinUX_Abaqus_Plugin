from __future__ import annotations

import os
import re
import socket
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path, PurePosixPath

from ..models import JobItem
from .ssh_serialization import _serialized_wire_call


class RemoteJobsMixin:
    """PBS/Abaqus submission, monitoring, scheduling and job-file helpers."""

    @_serialized_wire_call
    def list_jobs(self):
        """Return all PBS jobs using the same fields as the C# JobViewer."""
        if not self.connected:
            raise RuntimeError("Not connected to an SSH server")
        _stdin, stdout, stderr = self._exec_command_streams(
            "qstat -f", timeout=20)
        output = stdout.read().decode("utf-8", "replace")
        error = stderr.read().decode("utf-8", "replace").strip()
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            raise RuntimeError(error or "qstat failed with exit code {}".format(
                exit_status))
        return self._parse_qstat_jobs(output)

    @_serialized_wire_call
    def run_command(self, command):
        """Execute a scheduler command and return its combined response."""
        if not self.connected:
            raise RuntimeError("Not connected to an SSH server")
        _stdin, stdout, stderr = self._exec_command_streams(
            command, timeout=20)
        output = stdout.read().decode("utf-8", "replace").strip()
        error = stderr.read().decode("utf-8", "replace").strip()
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            raise RuntimeError(error or output or
                               "Command failed with exit code {}".format(exit_status))
        return output or error

    @_serialized_wire_call
    def run_interactive_command(self, command, marker, timeout=30):
        """Run a command through an interactive SSH shell and await its marker."""
        if not self.client:
            raise RuntimeError("Not connected to an SSH server")
        if not self.shell or self.shell.closed:
            raise RuntimeError("Interactive SSH shell is not available")
        with self._shell_condition:
            start = self._shell_output.cursor()
        deadline = time.monotonic() + timeout
        completion_pattern = re.compile(re.escape(marker) + r":\d+")
        self.send_shell_command(command)
        with self._shell_condition:
            while time.monotonic() < deadline:
                response = self._shell_output.read_since(start)
                if completion_pattern.search(response):
                    return response
                if not self.shell or self.shell.closed:
                    break
                self._shell_condition.wait(min(0.2, deadline - time.monotonic()))
            response = self._shell_output.read_since(start).strip()
        raise RuntimeError(
            "Interactive command did not complete{}".format(
                ": {}".format(response[-500:]) if response else ""))

    @_serialized_wire_call
    def submit_abaqus_job(self, path, version, cpus, precision, overwrite=False):
        """Launch an Abaqus input file in its remote directory."""
        path = self.normalize(path)
        if path.suffix.casefold() != ".inp":
            raise ValueError("Only Abaqus .inp files can be submitted")
        executable = str(version).strip()
        if not re.match(r"^[A-Za-z0-9._/+:-]+$", executable):
            raise ValueError("Invalid Abaqus version command: {}".format(version))
        cpus = int(cpus)
        if cpus < 1:
            raise ValueError("CPU count must be positive")
        job_name = path.stem
        # Use the logged-in user's shared Temp directory for Abaqus scratch.
        # ``self.home`` is resolved by SFTP at login (normally /home/<user>),
        # so this remains correct even when the server uses a different home
        # root. The directory is created immediately before submission.
        scratch_dir = self.home / "Temp"
        arguments = [executable, "job={}".format(job_name),
                     "input={}".format(path.name), "cpus={}".format(cpus),
                     "scratch={}".format(scratch_dir)]
        if str(precision).casefold() == "double":
            arguments.append("double")
        if overwrite:
            arguments.append("ask_delete=OFF")
        marker = "__WINUX_JOB_STARTED_{}__".format(uuid.uuid4().hex)
        preparation = "mkdir -p -- {} && ".format(
            self._shell_quote(scratch_dir))
        if overwrite:
            # Remove only outputs with the exact job stem.  For example,
            # ``xxxx.*`` is removed while ``xxxx-1.*`` and the input file stay.
            preparation += ("find . -maxdepth 1 -type f -name {} ! -name {} "
                            "-delete && ").format(
                                self._shell_quote(job_name + ".*"),
                                self._shell_quote(path.name))
        # Run in a subshell so submitting a scheduled job cannot move the
        # Console away from the directory currently shown by SFTP.
        command = ("(cd {} && {{ {}nohup {} > {} 2>&1 & "
                   "_winux_pid=$!; printf '\\n{}:%s\\n' \"$_winux_pid\"; }})").format(
            self._shell_quote(path.parent),
            preparation,
            " ".join(self._shell_quote(value) for value in arguments),
            self._shell_quote(".winux_{}.log".format(job_name)), marker)
        output = self.run_interactive_command(command, marker)
        match = re.search(re.escape(marker) + r":(\d+)", output)
        if not match:
            raise RuntimeError("Interactive shell did not return the job process ID")
        process_id = match.group(1)
        return "{} ({})".format(job_name, process_id or "started")

    @_serialized_wire_call
    def schedule_abaqus_job(self, run_at, **job):
        """Create a Linux atd job that survives this app's shutdown."""
        self.require_atd()
        path = self.normalize(job["path"])
        scratch_dir = self.home / "Temp"
        arguments = [job["version"], "job={}".format(path.stem),
                     "input={}".format(path.name),
                     "cpus={}".format(int(job["cpus"])),
                     "scratch={}".format(scratch_dir)]
        if str(job.get("precision", "single")).casefold() == "double":
            arguments.append("double")
        if job.get("overwrite"):
            arguments.append("ask_delete=OFF")
        inner = "source ~/.bashrc 2>/dev/null || true; mkdir -p {} && cd {} && {}".format(
            self._shell_quote(scratch_dir), self._shell_quote(path.parent),
            " ".join(self._shell_quote(value) for value in arguments))
        command = "bash -ic {}".format(self._shell_quote(inner))
        at_time = self._linux_at_time(run_at)
        output = self.run_command(
            "printf '%s\\n' {} | at {} 2>&1".format(
                self._shell_quote(command), self._shell_quote(at_time)))
        match = re.search(r"job\s+(\d+)", output, re.IGNORECASE)
        if not match:
            raise RuntimeError("at did not return a job id: {}".format(output))
        return match.group(1), command

    @_serialized_wire_call
    def cancel_scheduled_job(self, at_job_id):
        job_id = str(at_job_id)
        if not re.fullmatch(r"\d+", job_id):
            raise ValueError("Invalid at job id")
        return self.run_command("atrm {}".format(job_id))

    @_serialized_wire_call
    def require_atd(self):
        """Fail early when the Linux at scheduler is unavailable."""
        output = self.run_command("command -v at && command -v atrm")
        if not output.strip():
            raise RuntimeError("Linux at/atd is not available")

    @_serialized_wire_call
    def scheduled_job_exists(self, at_job_id):
        job_id = str(at_job_id)
        if not re.fullmatch(r"\d+", job_id):
            return False
        try:
            output = self.run_command("atq")
        except Exception:
            return False
        return any(line.split() and line.split()[0] == job_id
                   for line in output.splitlines())

    @_serialized_wire_call
    def schedule_delete_job(self, run_at, job_id):
        """Schedule PBS cancellation through Linux atd."""
        self.require_atd()
        command = "bash -ic {}".format(self._shell_quote(
            "qdel {}".format(self.numeric_job_id(job_id))))
        at_time = self._linux_at_time(run_at)
        output = self.run_command(
            "printf '%s\\n' {} | at {} 2>&1".format(
                self._shell_quote(command), self._shell_quote(at_time)))
        match = re.search(r"job\s+(\d+)", output, re.IGNORECASE)
        if not match:
            raise RuntimeError("at did not return a job id: {}".format(output))
        return match.group(1), command

    def _linux_at_time(self, local_time):
        """Map Windows local time to the Linux server's local time."""
        raw_offset = self.run_command("date +%z").strip()
        match = re.fullmatch(r"([+-])(\d{2})(\d{2})", raw_offset)
        if not match:
            raise RuntimeError("Could not determine Linux timezone offset")
        minutes = int(match.group(2)) * 60 + int(match.group(3))
        if match.group(1) == "-":
            minutes = -minutes
        local_zone = datetime.now().astimezone().tzinfo
        aware = local_time.replace(tzinfo=local_zone)
        linux_zone = timezone(timedelta(minutes=minutes))
        return aware.astimezone(linux_zone).strftime("%H:%M %m/%d/%Y")

    @staticmethod
    def numeric_job_id(value):
        match = re.search(r"\d+", str(value))
        if not match:
            raise ValueError("Invalid job ID")
        return match.group(0)

    @_serialized_wire_call
    def check_job(self, job_id):
        return self.run_command("qstat {}".format(self.numeric_job_id(job_id)))

    @staticmethod
    def _shell_quote(value):
        """Quote one value for the remote POSIX shell."""
        return "'{}'".format(str(value).replace("'", "'\"'\"'"))

    @_serialized_wire_call
    def read_job_status(self, job_id, job_name, job_owner=None):
        """Read the latest Abaqus progress marker from a job's .sta file."""
        name = str(job_name).strip()
        current_username, current_hostname = self.current_remote_identity()
        owner = self._clean_job_owner(job_owner)
        if owner and owner.casefold() != current_username.casefold():
            raise RuntimeError(
                "Job {} belongs to {}, but the current SSH user is {}.".format(
                    self.numeric_job_id(job_id), owner, current_username))
        lookup_owner = owner or current_username
        temp_folder = self._find_job_temp_folder_by_id(
            job_id, lookup_owner, current_username, current_hostname)
        first_path = self._find_job_status_file(temp_folder, name) if temp_folder else ""
        if not first_path and name:
            first_path = self._find_job_file(
                job_id, name, ".sta", lookup_owner, current_username, current_hostname)
        if not first_path:
            return "No progress information found in the job file."

        file_content = self.run_command(
            "cat {}".format(self._shell_quote(first_path)))
        status = self._parse_abaqus_status(file_content)
        if status.get("state") in {"running", "starting", "preprocessing"}:
            try:
                checked_at = self.run_command(
                    "date '+%d-%b-%Y %H:%M:%S'").strip()
            except Exception:
                checked_at = ""
            self._apply_check_time_runtime(status, checked_at)
        return self._format_abaqus_status(status)

    def _find_job_status_file(self, folder, job_name):
        """Return the most appropriate ``.sta`` file in one scheduler folder.

        A scheduler directory can occasionally contain more than one status
        file (for example after retries or helper jobs).  The exact Abaqus job
        stem is authoritative; only when it is absent do we fall back to the
        newest ``*.sta`` file inside the already validated job-ID directory.
        """
        if not folder:
            return ""
        name = str(job_name or "").strip()
        if name:
            exact = self._find_latest_file(folder, name + ".sta")
            if exact:
                return exact
        return self._find_latest_file(folder, "*.sta")

    @staticmethod
    def _wall_time_seconds(value):
        """Convert Abaqus ``H+:MM:SS`` wall time to seconds."""
        match = re.fullmatch(r"\s*(\d{1,6}):(\d{2}):(\d{2})\s*", str(value or ""))
        if not match:
            return None
        return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))

    @staticmethod
    def _format_wall_seconds(value):
        """Format a non-negative number of seconds as ``H+:MM:SS``."""
        try:
            seconds = max(0, int(value))
        except (TypeError, ValueError):
            return None
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)

    @staticmethod
    def _parse_abaqus_status(file_content):
        """Parse a live Abaqus ``.sta`` file into job and per-step status.

        Abaqus/Explicit writes cumulative TOTAL TIME/WALL TIME while STEP TIME
        resets at every step.  Keeping one record per ``STEP n ORIGIN`` lets
        Check Job report multi-step analyses without losing compatibility with
        the legacy top-level fields (``frame``, ``increment``, ``step_time``,
        ...), which continue to mirror the latest/current step.
        """
        text = str(file_content or "").replace("\x00", "")
        result = {
            "state": "unknown",
            "frame": None,
            "total_frames": None,
            "step": None,
            "increment": None,
            "step_time": None,
            "total_time": None,
            "wall_time": None,
            "total_wall_time": None,
            "step_runtime": None,
            "frame_runtime": None,
            "total_runtime": None,
            "step_count": 0,
            "steps": [],
        }
        if not text.strip():
            return result

        number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
        step_pattern = re.compile(
            r"^\s*STEP\s+(?P<step>\d+)\s+ORIGIN(?:\s+(?P<origin>" + number + r"))?\b",
            re.IGNORECASE)
        frame_pattern = re.compile(
            r"^\s*Output\s+Field\s+Frame\s+Number\s+"
            r"(?P<frame>\d+)\s*,?\s*of\s+(?P<total>\d+)"
            r"(?:\s+(?:requested\s+)?time\s+points\b)?"
            r"(?:\s*,?\s*at\s+(?:step\s+time\s+(?P<frame_time>" + number + r")|increment\s+zero))?",
            re.IGNORECASE)
        increment_pattern = re.compile(
            r"^\s*(?P<increment>\d+)\s+"
            r"(?P<step_time>" + number + r")\s+"
            r"(?P<total_time>" + number + r")\s+"
            r"(?P<wall_time>\d{1,6}:\d{2}:\d{2})\s+"
            r"(?P<stable>" + number + r")\s+"
            r"(?P<critical>\d+)\b",
            re.IGNORECASE)

        steps = []
        current = None
        latest_activity_pos = -1
        offset = 0

        def make_step(number_value, origin, position):
            return {
                "number": int(number_value),
                "origin": origin,
                "state": "starting",
                "frame": None,
                "total_frames": None,
                "increment": None,
                "step_time": None,
                "total_time": None,
                "wall_time": None,
                "wall_elapsed": None,
                "frame_runtime": None,
                "_last_wall_seconds": None,
                "_frame_streams": {},
                "_activity_pos": position,
            }

        for raw_line in text.splitlines(True):
            line = raw_line.rstrip("\r\n")
            step_match = step_pattern.match(line)
            if step_match:
                step_number = int(step_match.group("step"))
                origin = step_match.group("origin")
                # A new step proves that the previous one reached its boundary.
                if current is not None and current.get("number") != step_number:
                    if (current.get("frame") is not None or
                            current.get("increment") is not None):
                        current["state"] = "completed"
                # Repeated STEP headers can occur after a restart. Reuse the
                # same logical step but let new activity supersede stale data.
                existing = next((item for item in reversed(steps)
                                 if item["number"] == step_number), None)
                if existing is None or (current is not None and current is not existing
                                        and current.get("number") == step_number):
                    current = make_step(step_number, origin, offset)
                    steps.append(current)
                else:
                    current = existing
                    if origin is not None:
                        current["origin"] = origin
                    current["_activity_pos"] = max(current.get("_activity_pos", -1), offset)

            frame_match = frame_pattern.match(line)
            if frame_match:
                frame = int(frame_match.group("frame"))
                total = int(frame_match.group("total"))
                if total > 0 and 0 <= frame <= total:
                    if current is None:
                        current = make_step(1, None, offset)
                        steps.append(current)
                    # Abaqus can emit more than one Output Field frame stream
                    # inside the same analysis step (for example 20 regular
                    # frames plus 6 requested time points).  The user-facing
                    # step progress should follow the primary stream, which is
                    # the stream with the largest total frame count.  A smaller
                    # auxiliary stream must never overwrite it merely because
                    # it was written later in the .sta file.
                    previous_total = current.get("total_frames")
                    use_frame = previous_total is None or total > previous_total or total == previous_total
                    if use_frame:
                        current["frame"] = frame
                        current["total_frames"] = total
                        frame_time = frame_match.group("frame_time")
                        if frame_time is not None:
                            current["step_time"] = frame_time
                    # Associate each frame marker with the WALL TIME from the
                    # immediately preceding increment record. Keep streams
                    # separated by their total frame count so auxiliary output
                    # streams (for example 6 requested points beside 20 regular
                    # frames) cannot corrupt the primary frame duration.
                    frame_wall = current.get("_last_wall_seconds")
                    if frame_wall is not None:
                        stream = current.setdefault("_frame_streams", {}).setdefault(total, [])
                        event = (frame, int(frame_wall), offset)
                        if not stream or stream[-1][:2] != event[:2]:
                            stream.append(event)
                    current["state"] = "running"
                    current["_activity_pos"] = offset
                    latest_activity_pos = max(latest_activity_pos, offset)

            increment_match = increment_pattern.match(line)
            if increment_match:
                if current is None:
                    current = make_step(1, None, offset)
                    steps.append(current)
                current["increment"] = int(increment_match.group("increment"))
                current["step_time"] = increment_match.group("step_time")
                current["total_time"] = increment_match.group("total_time")
                current["wall_time"] = increment_match.group("wall_time")
                current["_last_wall_seconds"] = RemoteJobsMixin._wall_time_seconds(
                    current["wall_time"])
                current["state"] = "running"
                current["_activity_pos"] = offset
                latest_activity_pos = max(latest_activity_pos, offset)
            offset += len(raw_line)

        terminal_events = []
        terminal_patterns = (
            ("completed", re.compile(
                r"(?im)^\s*(?:THE\s+)?ANALYSIS\s+(?:HAS\s+)?(?:BEEN\s+)?COMPLETED(?:\s+SUCCESSFULLY)?\b.*$")),
            ("completed", re.compile(
                r"(?im)^\s*Abaqus\s+JOB\b.*\bCOMPLETED\b.*$")),
            ("failed", re.compile(
                r"(?im)^\s*(?:THE\s+)?ANALYSIS\s+(?:HAS\s+)?(?:BEEN\s+)?TERMINATED\b.*$")),
            ("failed", re.compile(
                r"(?im)^\s*Abaqus(?:/Explicit)?\s+Analysis\s+exited\s+with\s+an\s+error\b.*$")),
            ("failed", re.compile(
                r"(?im)^\s*Abaqus\s+JOB\b.*\b(?:ABORTED|TERMINATED)\b.*$")),
            ("failed", re.compile(r"(?im)^\s*\*{3}\s*ERROR\b.*$")),
        )
        for state, pattern in terminal_patterns:
            terminal_events.extend((match.start(), state) for match in pattern.finditer(text))

        terminal_state = None
        if terminal_events:
            event_pos, event_state = max(terminal_events, key=lambda item: item[0])
            if event_pos >= latest_activity_pos:
                terminal_state = event_state

        # Normalize per-step state. Entering a later step proves all previous
        # step occurrences completed; only the latest step can be running or
        # failed at the end of the current status file.
        if steps:
            # Reaching a later STEP header is sufficient evidence that every
            # earlier step crossed its boundary, even when that earlier step
            # produced no output frame/increment row that our parser recognizes.
            for item in steps[:-1]:
                item["state"] = "completed"
            latest = steps[-1]
            if terminal_state == "completed":
                for item in steps:
                    item["state"] = "completed"
            elif terminal_state == "failed":
                latest["state"] = "failed"
            elif latest.get("frame") is not None or latest.get("increment") is not None:
                latest["state"] = "running"
            else:
                latest["state"] = "starting"

        # Derive the duration of the most recently completed frame in the
        # primary output stream. Frame time is the difference between the WALL
        # TIME recorded at frame N and frame N-1 of the same stream.
        for item in steps:
            total = item.get("total_frames")
            frame = item.get("frame")
            events = item.get("_frame_streams", {}).get(total, []) if total else []
            if frame is None or frame <= 0 or not events:
                continue
            current_index = next(
                (idx for idx in range(len(events) - 1, -1, -1)
                 if events[idx][0] == frame), None)
            if current_index is None:
                continue
            current_wall = events[current_index][1]
            previous = next(
                (event for event in reversed(events[:current_index])
                 if event[0] == frame - 1), None)
            if previous is None:
                continue
            previous_wall = previous[1]
            if current_wall >= previous_wall:
                item["frame_runtime"] = RemoteJobsMixin._format_wall_seconds(
                    current_wall - previous_wall)

        # Derive per-step runtime from Abaqus' wall clock. Normally WALL TIME
        # is cumulative, so the current step runtime is the difference between
        # the two nearest step endpoints. If Abaqus restarts its wall clock,
        # treat the current value as a fresh step duration instead of returning
        # a misleading zero.
        previous_wall_seconds = 0
        total_runtime_seconds = 0
        has_wall_time = False
        for item in steps:
            wall_seconds = RemoteJobsMixin._wall_time_seconds(item.get("wall_time"))
            if wall_seconds is not None:
                has_wall_time = True
                if wall_seconds >= previous_wall_seconds:
                    elapsed = wall_seconds - previous_wall_seconds
                else:
                    elapsed = wall_seconds
                item["wall_elapsed"] = RemoteJobsMixin._format_wall_seconds(elapsed)
                total_runtime_seconds += elapsed
                previous_wall_seconds = wall_seconds
        result["total_runtime"] = (
            RemoteJobsMixin._format_wall_seconds(total_runtime_seconds)
            if has_wall_time else None)

        # WALL TIME begins with the solution phase, not necessarily when the
        # Abaqus process/job itself first started.  Keep Step runtime tied to
        # WALL TIME, but make Total runtime include the preprocessing/startup
        # interval when the .sta file provides both absolute timestamps.
        #
        # Do not use an arbitrary later Abaqus page header as the solution
        # anchor: long .sta files can repeat DATE/TIME headers.  The header
        # immediately preceding the first SOLUTION PROGRESS section is the
        # stable boundary between startup/preprocessing and step execution.
        header_pattern = re.compile(
            r"(?im)^.*?DATE\s+(?P<date>\d{1,2}-[A-Za-z]{3}-\d{4})"
            r"\s+TIME\s+(?P<time>\d{1,2}:\d{2}:\d{2})\s*$")
        header_events = []
        for header_match in header_pattern.finditer(text):
            try:
                stamp = datetime.strptime(
                    "{} {}".format(header_match.group("date"), header_match.group("time")),
                    "%d-%b-%Y %H:%M:%S")
            except (TypeError, ValueError):
                continue
            header_events.append((header_match.start(), stamp))

        if header_events:
            result["_job_start_datetime"] = header_events[0][1]

        startup_seconds = None
        solution_match = re.search(r"(?im)^\s*SOLUTION\s+PROGRESS\s*$", text)
        if has_wall_time and header_events and solution_match is not None:
            solution_headers = [
                event for event in header_events if event[0] <= solution_match.start()
            ]
            if solution_headers:
                first_stamp = header_events[0][1]
                solution_stamp = solution_headers[-1][1]
                delta = int((solution_stamp - first_stamp).total_seconds())
                # Negative deltas mean malformed/out-of-order timestamps.  A
                # huge delta is also more likely a concatenated/stale status
                # file than one continuous job startup, so ignore it rather
                # than reporting a misleading runtime.
                if 0 <= delta <= 7 * 24 * 3600:
                    startup_seconds = delta
                    result["startup_runtime"] = RemoteJobsMixin._format_wall_seconds(delta)
                    result["total_runtime"] = RemoteJobsMixin._format_wall_seconds(
                        total_runtime_seconds + delta)

        public_steps = []
        for item in steps:
            public_steps.append({
                key: value for key, value in item.items()
                if not key.startswith("_")
                and not (key == "frame_runtime" and value is None)
            })
        result["steps"] = public_steps
        result["step_count"] = len(public_steps)

        latest = public_steps[-1] if public_steps else None
        if latest:
            result["step"] = latest.get("number")
            for key in ("frame", "total_frames", "increment", "step_time",
                        "total_time", "wall_time", "frame_runtime"):
                result[key] = latest.get(key)
            result["step_runtime"] = latest.get("wall_elapsed")
            result["total_wall_time"] = next(
                (item.get("wall_time") for item in reversed(public_steps)
                 if item.get("wall_time")), None)
            if not result.get("total_runtime"):
                result["total_runtime"] = result.get("total_wall_time")

        if terminal_state:
            result["state"] = terminal_state
        elif latest and (latest.get("frame") is not None or latest.get("increment") is not None):
            result["state"] = "running"
        elif re.search(r"(?im)^\s*SOLUTION\s+PROGRESS\s*$", text):
            result["state"] = "starting"
        else:
            result["state"] = "preprocessing"
        return result

    @staticmethod
    def _parse_remote_datetime(value):
        """Parse the server-local timestamp used by Check Job."""
        value = str(value or "").strip()
        for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
        return None

    @staticmethod
    def _apply_check_time_runtime(status, checked_at):
        """Set Total runtime to elapsed wall time from job start to Check Job."""
        status = status if isinstance(status, dict) else {}
        if status.get("state") not in {"running", "starting", "preprocessing"}:
            return status
        started_at = status.get("_job_start_datetime")
        if not isinstance(started_at, datetime):
            return status
        if not isinstance(checked_at, datetime):
            checked_at = RemoteJobsMixin._parse_remote_datetime(checked_at)
        if not isinstance(checked_at, datetime):
            return status
        elapsed = int((checked_at - started_at).total_seconds())
        if 0 <= elapsed <= 30 * 24 * 3600:
            status["total_runtime"] = RemoteJobsMixin._format_wall_seconds(elapsed)
        return status

    @staticmethod
    def _format_abaqus_status(status):
        """Format Check Job using plain ASCII and only the key runtime fields."""
        status = dict(status or {})
        state = status.get("state") or "unknown"
        steps = list(status.get("steps") or [])
        state_labels = {
            "running": "Running",
            "completed": "Completed",
            "failed": "Terminated",
            "starting": "Starting",
            "preprocessing": "Preprocessing",
            "unknown": "Unknown",
        }

        if not steps:
            if state == "completed":
                return "Status: Completed"
            if state == "failed":
                return "Status: Terminated"
            if state == "starting":
                return "Status: Starting\nCurrent step: 1\nFrame: N/A\nFrame time: N/A\nTotal runtime: N/A"
            if state == "preprocessing":
                return "Status: Preprocessing\nCurrent step: N/A\nFrame: N/A\nFrame time: N/A\nTotal runtime: N/A"
            return "Status: Unknown\nCurrent step: N/A\nFrame: N/A\nFrame time: N/A\nTotal runtime: N/A"

        current_number = status.get("step") or steps[-1].get("number")
        current = next(
            (item for item in reversed(steps) if item.get("number") == current_number),
            steps[-1])
        frame = current.get("frame")
        total_frames = current.get("total_frames")
        frame_text = "{}/{}".format(frame, total_frames) if frame is not None and total_frames else "N/A"
        frame_runtime = current.get("frame_runtime") or status.get("frame_runtime") or "N/A"
        total_runtime = status.get("total_runtime") or status.get("total_wall_time") or status.get("wall_time") or "N/A"

        lines = [
            "Status: {}".format(state_labels.get(state, str(state).title())),
            "Current step: {}".format(current_number),
            "Frame: {}".format(frame_text),
            "Frame time: {}".format(frame_runtime),
            "Total runtime: {}".format(total_runtime),
        ]
        # Keep dialog text strictly ASCII so typographic punctuation such as
        # em dashes cannot creep back into status output.
        return "\n".join(lines).encode("ascii", "replace").decode("ascii")

    @staticmethod
    def _parse_abaqus_progress(file_content):
        """Compatibility wrapper returning the latest ``(frame, total)`` pair."""
        status = RemoteJobsMixin._parse_abaqus_status(file_content)
        if status.get("frame") is None or not status.get("total_frames"):
            return None
        return int(status["frame"]), int(status["total_frames"])

    @_serialized_wire_call
    def find_job_temp_folder(self, job_id, job_name, job_owner=None):
        """Locate the scheduler Temp folder using username and numeric job ID."""
        current_username, current_hostname = self.current_remote_identity()
        owner = self._clean_job_owner(job_owner)
        if owner and owner.casefold() != current_username.casefold():
            raise RuntimeError(
                "Job {} belongs to {}, but the current SSH user is {}.".format(
                    self.numeric_job_id(job_id), owner, current_username))
        lookup_owner = owner or current_username
        temp_folder = self._find_job_temp_folder_by_id(
            job_id, lookup_owner, current_username, current_hostname)
        if temp_folder:
            return PurePosixPath(temp_folder)

        # Compatibility fallback for older layouts that were located through
        # the status filename rather than the scheduler directory name.
        name = str(job_name).strip()
        first_path = self._find_job_file(
            job_id, name, ".sta", lookup_owner, current_username, current_hostname
        ) if name else ""
        if first_path:
            return PurePosixPath(first_path).parent
        raise RuntimeError("No Temp folder was found for job {}.".format(
            self.numeric_job_id(job_id)))

    @staticmethod
    def _component_has_exact_job_id(component, job_id):
        """Return True when *component* contains the exact numeric job ID."""
        numeric_id = RemoteJobsMixin.numeric_job_id(job_id)
        token = re.compile(r"(?<!\d){}(?!\d)".format(re.escape(numeric_id)))
        return bool(token.search(str(component)))

    @staticmethod
    def _path_has_exact_job_id(path, job_id):
        """Return True when a directory component carries exactly *job_id*.

        Job files are associated with the scheduler through directory names
        such as ``31635.server_job``. Matching the ID as an isolated numeric
        token prevents job 31635 from accepting paths for 131635 or 316350.
        """
        parts = PurePosixPath(str(path)).parts
        # Only directory components prove scheduler ownership. The file name
        # may contain unrelated digits from the model/job name.
        return any(RemoteJobsMixin._component_has_exact_job_id(component, job_id)
                   for component in parts[:-1])

    @staticmethod
    def _clean_job_owner(value):
        owner = str(value or "").strip().split("@", 1)[0]
        if not owner or not re.fullmatch(r"[A-Za-z0-9._-]+", owner):
            return ""
        return owner

    @staticmethod
    def _clean_remote_hostname(value):
        hostname = str(value or "").strip().rstrip(".")
        if not hostname or not re.fullmatch(r"[A-Za-z0-9._-]+", hostname):
            return ""
        return hostname

    @_serialized_wire_call
    def current_remote_identity(self):
        """Return the username/hostname reported by the live SSH session.

        Check Job must not trust login-time cached identity because WinUx can
        reconnect or reuse a server model after the remote account/host has
        changed. Query both values for every operation that resolves scheduler
        Temp paths. ``hostname -f`` is preferred because PBS scratch folders
        normally embed the FQDN; plain ``hostname`` is the fallback.
        """
        command = (
            "_winux_user=$(whoami 2>/dev/null); "
            "[ -n \"$_winux_user\" ] || _winux_user=$(id -un 2>/dev/null); "
            "_winux_host=$(hostname -f 2>/dev/null); "
            "[ -n \"$_winux_host\" ] || _winux_host=$(hostname 2>/dev/null); "
            "printf '__WINUX_USER__=%s\\n__WINUX_HOST__=%s\\n' "
            "\"$_winux_user\" \"$_winux_host\""
        )
        output = self.run_command(command)
        user_match = re.search(r"(?:^|\n)__WINUX_USER__=([^\r\n]+)", output)
        host_match = re.search(r"(?:^|\n)__WINUX_HOST__=([^\r\n]+)", output)
        username = self._clean_job_owner(
            user_match.group(1) if user_match else "")
        hostname = self._clean_remote_hostname(
            host_match.group(1) if host_match else "")
        if not username or not hostname:
            raise RuntimeError(
                "Could not determine the current SSH username and hostname")
        return username, hostname

    @staticmethod
    def _hostname_aliases(hostname):
        hostname = RemoteJobsMixin._clean_remote_hostname(hostname).casefold()
        if not hostname:
            return ()
        # When hostname -f succeeds, keep the FQDN strict so a different host
        # with the same short label cannot be accepted accidentally. If only
        # the short hostname is available, matching permits a FQDN suffix.
        return (hostname,)

    @staticmethod
    def _component_matches_job_identity(component, job_id, hostname=None):
        """Match scheduler folder identity using exact job ID and live host.

        Current layouts use ``<id>.<hostname>_<job-name>``. Legacy layouts
        without a hostname (``<id>_...``/``<id>-...``) remain supported, but
        a folder that explicitly names a different host is rejected.
        """
        numeric_id = RemoteJobsMixin.numeric_job_id(job_id)
        value = str(component or "").strip()
        if not RemoteJobsMixin._component_has_exact_job_id(value, numeric_id):
            return False
        folded = value.casefold()
        prefix = numeric_id.casefold()
        aliases = RemoteJobsMixin._hostname_aliases(hostname)
        if folded == prefix or folded.startswith(prefix + "_") or folded.startswith(prefix + "-"):
            return True
        if folded.startswith(prefix + "."):
            if not aliases:
                return True
            remainder = folded[len(prefix) + 1:]
            return any(
                remainder == alias
                or remainder.startswith(alias + "_")
                or remainder.startswith(alias + "-")
                or ("." not in alias and remainder.startswith(alias + "."))
                for alias in aliases
            )
        # Nonstandard legacy names that merely contain the isolated ID are
        # accepted only when they do not advertise a conflicting hostname.
        return not aliases

    def _job_temp_search_roots(self, job_owner=None, current_username=None):
        """Return Temp roots, preferring live identity and selected job owner."""
        home = PurePosixPath(self.home)
        owner = self._clean_job_owner(job_owner)
        username = (self._clean_job_owner(current_username)
                    or self._clean_job_owner(getattr(self, "username", "")))
        candidates = []
        if owner:
            owner_home = home.parent / owner
            canonical_home = PurePosixPath("/home") / owner
            candidates.extend((
                owner_home / "Temp" / owner,
                owner_home / "Temp",
                canonical_home / "Temp" / owner,
                canonical_home / "Temp",
                home / "Temp" / owner,
            ))
        if username:
            current_home = PurePosixPath("/home") / username
            candidates.extend((
                current_home / "Temp" / username,
                current_home / "Temp",
                home / "Temp" / username,
            ))
        candidates.append(home / "Temp")
        unique, seen = [], set()
        for root in candidates:
            key = str(root)
            if key not in seen:
                seen.add(key)
                unique.append(root)
        return tuple(unique)

    @_serialized_wire_call
    def _find_job_temp_folder_by_id(self, job_id, job_owner=None, current_username=None, current_hostname=None):
        """Find a Temp job directory using the exact numeric scheduler ID.

        Both ``Temp/<job-dir>`` and ``Temp/<owner>/<job-dir>`` layouts are
        supported.  The latter matches cluster paths such as
        ``/home/huyhuynh/Temp/huyhuynh/31646.server_Job``.
        """
        numeric_id = self.numeric_job_id(job_id)
        patterns = (
            numeric_id,
            "{}.*".format(numeric_id),
            "{}_*".format(numeric_id),
            "{}-*".format(numeric_id),
        )
        for root in self._job_temp_search_roots(job_owner, current_username):
            predicates = " -o ".join(
                "-name {}".format(self._shell_quote(pattern))
                for pattern in patterns)
            quoted_root = self._shell_quote(root)
            command = (
                "if [ -d {} ]; then find {} -mindepth 1 -maxdepth 2 "
                "-type d \\( {} \\) -print 2>/dev/null; fi").format(
                    quoted_root, quoted_root, predicates)
            result = self.run_command(command)
            for line in result.splitlines():
                candidate = line.strip()
                if (candidate and self._component_matches_job_identity(
                        PurePosixPath(candidate).name, numeric_id, current_hostname)):
                    return candidate
        return ""

    @_serialized_wire_call
    def _find_latest_file(self, folder, filename_pattern, exclude_suffix=None):
        """Return the newest matching file below one known remote folder."""
        exclusion = ""
        if exclude_suffix:
            exclusion = " ! -name {}".format(
                self._shell_quote("*{}".format(exclude_suffix)))
        command = (
            "find {} -type f -name {}{} -printf '%T@\\t%p\\n' 2>/dev/null "
            "| sort -nr | cut -f2- | head -n 1").format(
                self._shell_quote(folder), self._shell_quote(filename_pattern),
                exclusion)
        result = self.run_command(command)
        return next((line.strip() for line in result.splitlines()
                     if line.strip()), "")

    @_serialized_wire_call
    def find_job_output_file(self, job_id, job_name, extension=".odb"):
        """Find a job output through its username/job-ID Temp directory."""
        name = str(job_name).strip()
        temp_folder = self._find_job_temp_folder_by_id(job_id)
        excluded = "-Temp{}".format(extension) if extension == ".odb" else None
        first_path = self._find_latest_file(
            temp_folder, "*{}".format(extension), excluded
        ) if temp_folder else ""
        if not first_path and name:
            first_path = self._find_job_file(job_id, name, extension)
        if not first_path:
            raise RuntimeError("No {} file was found for this job.".format(extension))
        return PurePosixPath(first_path)

    @_serialized_wire_call
    def _find_job_file(self, job_id, job_name, extension, job_owner=None, current_username=None, current_hostname=None):
        """Find the newest matching file owned by the exact scheduler job ID.

        Job names are reusable, so a name-only fallback can read the status or
        output of a different submission. A candidate is accepted only when a
        directory component contains the requested numeric ID as an isolated
        token.
        """
        numeric_id = self.numeric_job_id(job_id)
        name = str(job_name).strip()
        if not name:
            return ""
        filename_pattern = "*{}*{}".format(name, extension)
        exclusion = (" ! -name {}".format(self._shell_quote("*-Temp.odb"))
                     if extension == ".odb" else "")

        roots = list(self._job_temp_search_roots(job_owner, current_username))
        search_home = (PurePosixPath("/home") / current_username
                       if self._clean_job_owner(current_username)
                       else PurePosixPath(self.home))
        roots.append(search_home)
        seen = set()
        for root in roots:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            command = (
                "find {} -type f -name {}{} -printf '%T@\t%p\n' 2>/dev/null "
                "| sort -nr | cut -f2-").format(
                    self._shell_quote(root), self._shell_quote(filename_pattern),
                    exclusion)
            result = self.run_command(command)
            for line in result.splitlines():
                candidate = line.strip()
                if candidate and self._path_has_exact_job_id(candidate, numeric_id):
                    parts = PurePosixPath(candidate).parts[:-1]
                    if any(self._component_matches_job_identity(
                            component, numeric_id, current_hostname) for component in parts):
                        return candidate
        return ""

    def hot_download(self, job_id, job_name, local_folder, cancel=None,
                     progress=None, abaqus_commands=None):
        """Download an immutable, validated snapshot of a live job ODB.

        A unique remote name prevents concurrent hot downloads from deleting
        each other's staging file.  Reflink is preferred because it creates a
        point-in-time CoW clone; filesystems without reflink use a guarded copy
        that is discarded whenever the source changes during staging.
        """
        source = self.find_job_output_file(job_id, job_name, ".odb")
        staged = source.with_name(".{}.winux-snapshot-{}".format(
            source.name, uuid.uuid4().hex))
        # Staging metadata and cleanup use a dedicated SFTP channel. Snapshot
        # creation/validation still take the short serialized control lock, but
        # the potentially long raw ODB stream no longer blocks qstat or browser
        # navigation on ``_connection_lock``.
        with self._transfer_sftp() as hot_sftp:
            try:
                copy_error = None
                for attempt in range(1, self.ODB_SNAPSHOT_RETRIES + 1):
                    self._cancelled(cancel)
                    try:
                        self._copy_remote_snapshot(source, staged)
                        validation = self._validate_remote_odb(
                            staged, abaqus_commands=abaqus_commands)
                        if validation is False:
                            raise RuntimeError(
                                "Abaqus could not open the staged ODB snapshot")
                        copy_error = None
                        break
                    except Exception as exc:
                        copy_error = exc
                        try:
                            if self.exists(staged, sftp_client=hot_sftp):
                                hot_sftp.remove(str(staged))
                        except Exception:
                            pass
                        if attempt < self.ODB_SNAPSHOT_RETRIES:
                            if cancel is not None:
                                cancel.wait(0.5)
                            else:
                                time.sleep(0.5)
                if copy_error is not None:
                    raise RuntimeError(
                        "Could not create a stable ODB snapshot after {} attempts: {}"
                        .format(self.ODB_SNAPSHOT_RETRIES, copy_error))

                total = hot_sftp.stat(str(staged)).st_size or 0
                if progress:
                    # Snapshot creation is preparation, not downloaded payload.
                    # Start the file row at zero so speed/ETA sampling measures the
                    # actual SSH stream rather than seeing a false 100% -> 0% reset.
                    progress(source.name, 0, total, total, max(1, total * 2))

                local_target = self._unique_local_download(
                    Path(local_folder) /
                    "{}-Temp{}".format(source.stem, source.suffix))

                def download_progress(amount):
                    if progress:
                        current = min(total, download_progress.done + amount)
                        download_progress.done = current
                        progress(source.name, current, total,
                                 total + current, max(1, total * 2))
                download_progress.done = 0

                self._hot_download_stream(
                    staged, local_target, total, cancel=cancel,
                    advance=download_progress)
                return local_target
            finally:
                try:
                    if self.exists(staged, sftp_client=hot_sftp):
                        hot_sftp.remove(str(staged))
                except Exception:
                    pass

    def _hot_download_stream(self, remote_path, target, expected_size,
                             cancel=None, advance=None):
        """Stream one staged ODB through a raw SSH channel at full speed.

        Hot Download always reads an immutable snapshot, so the SFTP protocol's
        per-request bookkeeping is unnecessary here. A continuous ``cat``
        stream keeps the SSH channel full and normally performs much better on
        high-latency links. The final file is still published atomically.
        """
        if not self.client:
            raise RuntimeError("Not connected to an SSH server")

        transport = self.client.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("SSH transport is not active")

        remote_path = self.normalize(remote_path)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".winux-part")
        try:
            partial.unlink()
        except FileNotFoundError:
            pass

        import socket

        try:
            channel = self._open_transport_session(
                transport,
                window_size=self.HOT_DOWNLOAD_WINDOW_SIZE,
                max_packet_size=self.HOT_DOWNLOAD_PACKET_SIZE,
            )

            try:
                channel.settimeout(self.HOT_DOWNLOAD_CHANNEL_TIMEOUT)
                channel.exec_command(
                    "cat -- {}".format(self._shell_quote(remote_path)))

                received = 0
                pending_progress = 0
                last_progress = time.monotonic()
                progress_batch = 4 * 1024 * 1024
                with partial.open(
                        "wb", buffering=self.HOT_DOWNLOAD_READ_SIZE) as output:
                    while True:
                        self._cancelled(cancel)
                        try:
                            chunk = channel.recv(self.HOT_DOWNLOAD_READ_SIZE)
                        except socket.timeout:
                            if channel.exit_status_ready():
                                break
                            continue

                        if chunk:
                            output.write(chunk)
                            amount = len(chunk)
                            received += amount
                            pending_progress += amount
                            now = time.monotonic()
                            if (advance and
                                    (pending_progress >= progress_batch or
                                     now - last_progress >= 0.1)):
                                advance(pending_progress)
                                pending_progress = 0
                                last_progress = now
                            continue

                        if channel.exit_status_ready():
                            break

                    if advance and pending_progress:
                        advance(pending_progress)
                    output.flush()
                    os.fsync(output.fileno())

                error_chunks = []
                while channel.recv_stderr_ready():
                    error_chunks.append(channel.recv_stderr(65536))
                exit_status = channel.recv_exit_status()
                if exit_status != 0:
                    error = b"".join(error_chunks).decode(
                        "utf-8", "replace").strip()
                    raise RuntimeError(
                        error or "Hot Download stream failed with exit code {}"
                        .format(exit_status))

                actual_size = partial.stat().st_size
                expected_size = int(expected_size or 0)
                if actual_size != expected_size or received != expected_size:
                    raise RuntimeError(
                        "Incomplete Hot Download: expected {} bytes, received {}"
                        .format(expected_size, actual_size))

                os.replace(str(partial), str(target))
                return target
            finally:
                try:
                    channel.close()
                except Exception:
                    pass
        except Exception:
            try:
                partial.unlink()
            except OSError:
                pass
            raise

    @_serialized_wire_call
    def _exec_remote(self, command):
        if not self.client:
            raise RuntimeError("Not connected to an SSH server")
        _stdin, stdout, stderr = self._exec_command_streams(command)
        output = stdout.read().decode("utf-8", "replace").strip()
        error = stderr.read().decode("utf-8", "replace").strip()
        exit_status = stdout.channel.recv_exit_status()
        return exit_status, output, error

    @_serialized_wire_call
    def _remote_signature(self, path):
        command = "stat --printf='%s|%Y|%y' -- {}".format(
            self._shell_quote(path))
        status, output, _error = self._exec_remote(command)
        if status == 0 and output:
            return output
        attributes = self.sftp.stat(str(path))
        return "{}|{}".format(
            int(attributes.st_size or 0), int(attributes.st_mtime or 0))

    @_serialized_wire_call
    def _copy_remote_snapshot(self, source, target):
        """Create a stable remote copy, preferring an actual CoW reflink."""
        reflink = "cp --reflink=always --sparse=always -- {} {}".format(
            self._shell_quote(source), self._shell_quote(target))
        status, _output, _error = self._exec_remote(reflink)
        if status == 0:
            return "reflink"

        before = self._remote_signature(source)
        regular = "cp --sparse=always -- {} {}".format(
            self._shell_quote(source), self._shell_quote(target))
        status, output, error = self._exec_remote(regular)
        if status != 0:
            raise RuntimeError(error or output or
                               "Remote copy failed with exit code {}".format(
                                   status))
        after = self._remote_signature(source)
        if before != after:
            raise RuntimeError("The source ODB changed while it was being staged")
        return "guarded-copy"

    @_serialized_wire_call
    def _copy_remote_file(self, source, target):
        """Compatibility wrapper for callers that need a stable remote copy."""
        return self._copy_remote_snapshot(source, target)

    @staticmethod
    def _unique_local_download(target):
        if not target.exists():
            return target
        counter = 1
        while True:
            candidate = target.with_name(
                "{}-{}{}".format(target.stem, counter, target.suffix))
            if not candidate.exists():
                return candidate
            counter += 1

    @_serialized_wire_call
    def job_details(self, job_id):
        output = self.run_command(
            "qstat -f {}".format(self.numeric_job_id(job_id)))
        wanted = {
            "Job_Name", "Job_Owner", "resources_used.cput",
            "Resource_List.abqlicense", "resources_used.ncpus",
            "Output_Path", "jobdir", "resources_used.walltime", "ctime",
            "etime", "Submit_arguments", "Submit_Host",
        }
        details = []
        current = None
        for line in output.splitlines():
            job_match = re.match(r"^\s*Job\s+Id\s*:\s*(.+)$", line)
            if job_match:
                details.append("Job Id: {}".format(job_match.group(1).strip()))
                current = None
                continue
            field_match = re.match(r"^\s*([^=]+?)\s*=\s*(.*)$", line)
            if field_match:
                key = field_match.group(1).strip()
                current = key if key in wanted else None
                if current:
                    details.append("{}: {}".format(
                        key, field_match.group(2).strip()))
            elif current and line[:1].isspace() and details:
                details[-1] += line.strip()
        return "\n".join(details) or output

    @_serialized_wire_call
    def cancel_job(self, job_id):
        return self.run_command("qdel {}".format(self.numeric_job_id(job_id)))

    @staticmethod
    def _parse_qstat_jobs(output):
        """Parse wrapped ``qstat -f`` records into JobItem instances."""
        records = re.split(r"(?mi)^\s*Job\s+Id\s*:\s*", output)
        jobs = []
        state_names = {
            "B": "Begun", "E": "Exiting", "F": "Finished", "H": "Held",
            "M": "Moved", "Q": "Queued", "R": "Running", "S": "Suspended",
            "T": "Transitioning", "U": "Suspended", "W": "Waiting",
            "X": "Expired",
        }
        for block in records[1:]:
            lines = block.splitlines()
            if not lines:
                continue
            id_match = re.search(r"\d+", lines[0])
            if not id_match:
                continue
            # PBS commonly returns values such as 12345.server.  The viewer
            # intentionally exposes only the scheduler's numeric identifier.
            job_id = id_match.group(0)
            fields = {}
            current_key = None
            for line in lines[1:]:
                match = re.match(r"^\s*([^=]+?)\s*=\s*(.*)$", line)
                if match:
                    current_key = match.group(1).strip()
                    fields[current_key] = match.group(2).strip()
                elif current_key and line[:1].isspace():
                    fields[current_key] += line.strip()
            owner = fields.get("Job_Owner", "").split("@", 1)[0]
            state = fields.get("job_state", "")
            name = RemoteJobsMixin._extract_job_name(fields)
            if name.startswith("job_"):
                name = name[len("job_"):]
            jobs.append(JobItem(
                job_id=job_id,
                name=name,
                user=owner,
                tokens=RemoteJobsMixin._extract_abq_tokens(fields),
                status=state_names.get(state, state),
                elapsed=(fields.get("resources_used.walltime") or
                         fields.get("resources_used.cput", "")),
            ))
        return jobs

    @staticmethod
    def _extract_job_name(fields):
        """Extract the full Abaqus name from PBS Submit_arguments."""
        def clean_name(value):
            """Remove Abaqus input metadata accidentally appended by PBS."""
            value = str(value or "").strip().rstrip(",")
            value = re.split(r"\s+ABA_INPUTFILES\d*=", value,
                             maxsplit=1, flags=re.IGNORECASE)[0]
            value = value.strip().strip("\"'")
            value = re.split(r"[/\\]", value)[-1]
            if value.casefold().endswith((".que", ".inp")):
                value = value[:-4]
            return value

        # The target PBS server reports the desired full job name as the first
        # token in Submit_arguments, for example:
        # New-DSHS-1 ABA_INPUTFILES0=New-DSHS-1.com|New-DSHS-1.inp
        arguments = fields.get("Submit_arguments", "").strip()
        match = re.match(r"\s*(?:job=)?(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))",
                         arguments, re.IGNORECASE)
        if match:
            value = next(value for value in match.groups() if value)
            if not value.upper().startswith("ABA_INPUTFILES"):
                return clean_name(value)

        # Last-resort Abaqus fallback: derive the job name from the submitted
        # input filename, without its .inp extension.
        match = re.search(
            r"(?:ABA_INPUTFILES\d*|input)=(?:[^\s|]*\|)?(?:\"([^\"]+\.inp)\"|"
            r"'([^']+\.inp)'|([^\s]+?\.inp))(?:\s|$)",
            arguments, re.IGNORECASE)
        if match:
            input_name = next(value for value in match.groups() if value)
            return re.split(r"[/\\]", input_name)[-1][:-4]

        # Compatibility fallbacks only apply when Submit_arguments is absent.
        direct = clean_name(fields.get("ABA_JOBNAME", ""))
        if direct:
            return direct
        variables = fields.get("Variable_List", "")
        match = re.search(r"(?:^|,)ABA_JOBNAME=([^,]+)", variables)
        if match:
            return clean_name(match.group(1))
        return fields.get("Job_Name", "")

    @staticmethod
    def _extract_abq_tokens(fields):
        """Read Abaqus tokens from a dedicated or embedded PBS resource."""
        # This PBS configuration reports the allocated Abaqus capacity as its
        # CPU count. Prefer actual usage, then the requested CPU allocation.
        for key in ("resources_used.ncpus", "Resource_List.ncpus"):
            value = fields.get(key, "")
            number = re.search(r"\d+(?:\.\d+)?", value)
            if number:
                return number.group(0)

        # Field names can vary in case between PBS installations.
        for key, value in fields.items():
            normalized_key = key.casefold().replace("_", "")
            if (normalized_key.endswith(".abqlicense") or
                    normalized_key.endswith(".abaquslicense") or
                    normalized_key.endswith(".abaqustokens")):
                number = re.search(r"\d+(?:\.\d+)?", value)
                return number.group(0) if number else value.strip()

        # Some clusters embed custom resources inside Resource_List.select,
        # for example ``1:ncpus=8:abqlicense=12``.
        for key, value in fields.items():
            if not key.casefold().startswith("resource_list."):
                continue
            match = re.search(
                r"(?i)(?:abqlicense|abaquslicense|abaqustokens)\s*=\s*"
                r"(\d+(?:\.\d+)?)", value)
            if match:
                return match.group(1)
        return ""
