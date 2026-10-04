from __future__ import annotations

import os
import re
import socket
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path, PurePosixPath

from ..model import JobItem
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
    def read_job_status(self, job_id, job_name):
        """Read the latest Abaqus progress marker from a job's .sta file."""
        name = str(job_name).strip()
        temp_folder = self._find_job_temp_folder_by_id(job_id)
        first_path = self._find_latest_file(temp_folder, "*.sta") if temp_folder else ""
        if not first_path and name:
            first_path = self._find_job_file(job_id, name, ".sta")
        if not first_path:
            return "No progress information found in the job file."

        file_content = self.run_command(
            "cat {}".format(self._shell_quote(first_path)))
        progress_pattern = re.compile(
            r"Output Field Frame Number\s+(?P<currentNum>\d+),\s+"
            r"of\s+(?P<totalNum>\d+),")
        matches = list(progress_pattern.finditer(file_content))
        if matches:
            latest = matches[-1]
            return "Process {}/{}.".format(
                latest.group("currentNum"), latest.group("totalNum"))
        return "No progress information found in the job file."

    @_serialized_wire_call
    def find_job_temp_folder(self, job_id, job_name):
        """Locate the scheduler Temp folder using username and numeric job ID."""
        temp_folder = self._find_job_temp_folder_by_id(job_id)
        if temp_folder:
            return PurePosixPath(temp_folder)

        # Compatibility fallback for older layouts that were located through
        # the status filename rather than the scheduler directory name.
        name = str(job_name).strip()
        first_path = self._find_job_file(job_id, name, ".sta") if name else ""
        if first_path:
            return PurePosixPath(first_path).parent
        raise RuntimeError("No Temp folder was found for job {}.".format(
            self.numeric_job_id(job_id)))

    @_serialized_wire_call
    def _find_job_temp_folder_by_id(self, job_id):
        """Find Temp/<user>/<jobid>.<server>_<job> without needing job name."""
        numeric_id = self.numeric_job_id(job_id)
        roots = (self.home / "Temp" / self.username, self.home / "Temp")
        pattern = "{}.*".format(numeric_id)
        for root in roots:
            command = (
                "find {} -mindepth 1 -maxdepth 1 -type d -name {} "
                "-print 2>/dev/null | head -n 1").format(
                    self._shell_quote(root), self._shell_quote(pattern))
            result = self.run_command(command)
            first_path = next((line.strip() for line in result.splitlines()
                               if line.strip()), "")
            if first_path:
                return first_path
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
    def _find_job_file(self, job_id, job_name, extension):
        """Find a job file below the connected account's actual home path."""
        numeric_id = self.numeric_job_id(job_id)
        name = str(job_name).strip()
        if not name:
            return ""
        root = self.home
        filename_pattern = "*{}*{}".format(name, extension)
        job_path_pattern = "*{}*/*{}*{}".format(
            numeric_id, name, extension)
        exclusion = (" ! -name {}".format(self._shell_quote("*-Temp.odb"))
                     if extension == ".odb" else "")

        # Older OHPC wrappers place results below a directory containing the
        # PBS ID. Preserve that exact match first. Jobs submitted directly by
        # WinUx write beside the .inp, so fall back to the newest matching file
        # anywhere below the home returned by SFTP. This is identical whether
        # the connection used the hostname or its IP address.
        exact_command = "find {} -type f -wholename {}{} -print -quit".format(
            self._shell_quote(root), self._shell_quote(job_path_pattern),
            exclusion)
        result = self.run_command(exact_command)
        first_path = next((line.strip() for line in result.splitlines()
                           if line.strip()), "")
        if first_path:
            return first_path

        latest_command = (
            "find {} -type f -name {}{} -printf '%T@\\t%p\\n' 2>/dev/null "
            "| sort -nr | cut -f2- | head -n 1").format(
                self._shell_quote(root), self._shell_quote(filename_pattern),
                exclusion)
        result = self.run_command(latest_command)
        return next((line.strip() for line in result.splitlines()
                     if line.strip()), "")

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
