from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import tarfile
import time
import uuid
from pathlib import Path, PurePosixPath


class RemoteTransferMixin:
    """High-throughput upload/download operations on shared SSH transport channels."""

    # Paramiko/SFTP transfer tuning.  SSHServerModel inherits these constants so
    # existing callers and connection-channel setup keep the same public values.
    SFTP_WINDOW_SIZE = 64 * 1024 * 1024
    SFTP_PACKET_SIZE = 256 * 1024
    SFTP_REQUEST_SIZE = 128 * 1024
    SOCKET_BUFFER_SIZE = 8 * 1024 * 1024
    DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024
    STREAM_FILE_THRESHOLD = 4 * 1024 * 1024
    STREAM_IO_SIZE = 8 * 1024 * 1024
    STREAM_PROGRESS_BATCH = 2 * 1024 * 1024
    STREAM_PROGRESS_INTERVAL = 0.10
    SFTP_REQUEST_TIMEOUT_SECONDS = 30.0
    TRANSFER_STALL_TIMEOUT_SECONDS = 60.0
    STREAM_EXIT_TIMEOUT_SECONDS = 30.0
    DOWNLOAD_PREFETCH_REQUESTS = 64

    def _stream_transport(self, client=None):
        client = client or self.client
        if not client:
            raise RuntimeError("Not connected to an SSH server")
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("SSH transport is not active")
        return transport

    def _open_stream_channel(self, client=None):
        """Open a large-window channel on the single SSH transport."""
        transport = self._stream_transport(client=client)
        return self._open_transport_session(
            transport,
            window_size=self.HOT_DOWNLOAD_WINDOW_SIZE,
            max_packet_size=self.HOT_DOWNLOAD_PACKET_SIZE,
        )

    def _supports_remote_tar(self, client=None):
        """Cache whether the connected Linux host provides ``tar``.

        When a dedicated transfer client is supplied, probe on that transport
        rather than borrowing the serialized control connection.
        """
        if self._remote_tar_supported is None:
            try:
                command = "command -v tar >/dev/null 2>&1"
                if client is not None:
                    status, _output, _error = self._exec_client(
                        client, command, timeout=20)
                else:
                    status, _output, _error = self._exec_remote(command)
                self._remote_tar_supported = status == 0
            except Exception:
                self._remote_tar_supported = False
        return self._remote_tar_supported

    @staticmethod
    def _wait_stream_exit(channel, cancel=None, timeout=None):
        """Wait for an exec channel with cancellation and a hard deadline."""
        timeout = (RemoteTransferMixin.STREAM_EXIT_TIMEOUT_SECONDS
                   if timeout is None else max(0.1, float(timeout)))
        deadline = time.monotonic() + timeout
        while not channel.exit_status_ready():
            RemoteTransferMixin._cancelled(cancel)
            if time.monotonic() >= deadline:
                try:
                    channel.close()
                except Exception:
                    pass
                raise TimeoutError(
                    "Remote transfer did not finish within {:.0f}s".format(timeout))
            time.sleep(0.02)
        return channel.recv_exit_status()

    @staticmethod
    def _stream_stderr(channel):
        chunks = []
        while channel.recv_stderr_ready():
            chunks.append(channel.recv_stderr(65536))
        return b"".join(chunks).decode("utf-8", "replace").strip()

    def _upload_file_stream(self, local_path, remote_path, cancel=None,
                            advance=None, sftp_client=None, client=None):
        """Upload a large file over one continuous SSH stream.

        Data first lands in a unique remote temporary file. Only a completely
        received and size-validated file replaces the destination, preventing
        interrupted uploads from publishing a truncated result.
        """
        sftp_client = sftp_client or self.sftp
        local_path = Path(local_path)
        remote_path = self.normalize(remote_path)
        before = local_path.stat()
        expected_size = int(before.st_size or 0)
        temporary = remote_path.with_name(
            ".{}.winux-upload-{}".format(remote_path.name, uuid.uuid4().hex))
        channel = self._open_stream_channel(client=client)
        sent_total = 0
        pending_progress = 0
        last_progress = time.monotonic()
        last_io = last_progress

        try:
            channel.settimeout(self.HOT_DOWNLOAD_CHANNEL_TIMEOUT)
            channel.exec_command(
                "cat > {}".format(self._shell_quote(temporary)))
            with local_path.open("rb", buffering=self.STREAM_IO_SIZE) as source:
                while True:
                    self._cancelled(cancel)
                    chunk = source.read(self.STREAM_IO_SIZE)
                    if not chunk:
                        break
                    view = memoryview(chunk)
                    while view:
                        self._cancelled(cancel)
                        try:
                            amount = channel.send(view)
                        except socket.timeout:
                            if channel.exit_status_ready():
                                error = self._stream_stderr(channel)
                                raise RuntimeError(
                                    error or "Remote upload stream closed early")
                            if (time.monotonic() - last_io >=
                                    self.TRANSFER_STALL_TIMEOUT_SECONDS):
                                raise TimeoutError(
                                    "Upload stalled for more than {:.0f}s".format(
                                        self.TRANSFER_STALL_TIMEOUT_SECONDS))
                            continue
                        if amount <= 0:
                            error = self._stream_stderr(channel)
                            raise RuntimeError(
                                error or "Remote upload stream closed early")
                        view = view[amount:]
                        sent_total += amount
                        pending_progress += amount
                        last_io = time.monotonic()
                        now = time.monotonic()
                        if (advance and
                                (pending_progress >= self.STREAM_PROGRESS_BATCH or
                                 now - last_progress >=
                                 self.STREAM_PROGRESS_INTERVAL)):
                            advance(pending_progress)
                            pending_progress = 0
                            last_progress = now

            channel.shutdown_write()
            exit_status = self._wait_stream_exit(channel, cancel=cancel)
            error = self._stream_stderr(channel)
            if exit_status != 0:
                raise RuntimeError(
                    error or "Upload stream failed with exit code {}".format(
                        exit_status))
            if advance and pending_progress:
                advance(pending_progress)
                pending_progress = 0

            after = local_path.stat()
            if (int(after.st_size or 0) != expected_size or
                    int(getattr(after, "st_mtime_ns", after.st_mtime * 1e9)) !=
                    int(getattr(before, "st_mtime_ns", before.st_mtime * 1e9))):
                raise RuntimeError("Local file changed during upload")
            remote_size = int(sftp_client.stat(str(temporary)).st_size or 0)
            if sent_total != expected_size or remote_size != expected_size:
                raise RuntimeError(
                    "Incomplete upload: expected {} bytes, sent {}".format(
                        expected_size, sent_total))

            # The transfer channel has finished. Close it before opening any
            # fallback exec channel used for publication, so old Paramiko builds
            # never have two active upload/publish channels at this boundary.
            try:
                channel.close()
            finally:
                channel = None
            self._publish_uploaded_file(
                sftp_client, temporary, remote_path, client=client)
        finally:
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
            try:
                sftp_client.remove(str(temporary))
            except Exception:
                pass

    def _download_file_stream(self, remote_path, partial, offset,
                              expected_size, cancel=None, advance=None,
                              client=None):
        """Append a remote file to a resumable partial via raw SSH stdout."""
        remote_path = self.normalize(remote_path)
        partial = Path(partial)
        offset = int(offset or 0)
        expected_size = int(expected_size or 0)
        expected_remaining = max(0, expected_size - offset)
        if expected_remaining == 0:
            return

        if offset:
            command = "tail -c +{} -- {}".format(
                offset + 1, self._shell_quote(remote_path))
        else:
            command = "cat -- {}".format(self._shell_quote(remote_path))

        channel = self._open_stream_channel(client=client)
        received = 0
        pending_progress = 0
        last_progress = time.monotonic()
        last_io = last_progress
        try:
            channel.settimeout(self.HOT_DOWNLOAD_CHANNEL_TIMEOUT)
            channel.exec_command(command)
            with partial.open(
                    "ab" if offset else "wb",
                    buffering=self.STREAM_IO_SIZE) as destination:
                while True:
                    self._cancelled(cancel)
                    try:
                        chunk = channel.recv(self.STREAM_IO_SIZE)
                    except socket.timeout:
                        if channel.exit_status_ready():
                            break
                        if (time.monotonic() - last_io >=
                                self.TRANSFER_STALL_TIMEOUT_SECONDS):
                            raise TimeoutError(
                                "Download stalled for more than {:.0f}s".format(
                                    self.TRANSFER_STALL_TIMEOUT_SECONDS))
                        continue
                    if chunk:
                        last_io = time.monotonic()
                        destination.write(chunk)
                        amount = len(chunk)
                        received += amount
                        pending_progress += amount
                        now = time.monotonic()
                        if (advance and
                                (pending_progress >= self.STREAM_PROGRESS_BATCH or
                                 now - last_progress >=
                                 self.STREAM_PROGRESS_INTERVAL)):
                            advance(pending_progress)
                            pending_progress = 0
                            last_progress = now
                        continue
                    if channel.exit_status_ready():
                        break

                destination.flush()

            exit_status = self._wait_stream_exit(channel, cancel=cancel)
            error = self._stream_stderr(channel)
            if exit_status != 0:
                raise RuntimeError(
                    error or "Download stream failed with exit code {}".format(
                        exit_status))
            if advance and pending_progress:
                advance(pending_progress)
            if received != expected_remaining:
                raise RuntimeError(
                    "Incomplete download: expected {} remaining bytes, "
                    "received {}".format(expected_remaining, received))
        finally:
            try:
                channel.close()
            except Exception:
                pass

    def _upload_directory_stream(self, local_folder, remote_folder,
                                 cancel=None, advance=None, client=None):
        """Send a complete directory as one uncompressed tar stream."""
        local_folder = Path(local_folder)
        remote_folder = self.normalize(remote_folder)
        channel = self._open_stream_channel(client=client)

        model = self
        pending_progress = 0
        last_progress = time.monotonic()
        last_io = last_progress

        def report_progress(amount=0, force=False):
            nonlocal pending_progress, last_progress
            pending_progress += int(amount or 0)
            now = time.monotonic()
            if (advance and pending_progress and
                    (force or
                     pending_progress >= model.STREAM_PROGRESS_BATCH or
                     now - last_progress >= model.STREAM_PROGRESS_INTERVAL)):
                advance(pending_progress)
                pending_progress = 0
                last_progress = now

        class ChannelWriter:
            def write(self, data):
                nonlocal last_io
                view = memoryview(data)
                while view:
                    model._cancelled(cancel)
                    try:
                        amount = channel.send(view)
                    except socket.timeout:
                        if channel.exit_status_ready():
                            error = model._stream_stderr(channel)
                            raise RuntimeError(
                                error or "Remote tar upload closed early")
                        if (time.monotonic() - last_io >=
                                model.TRANSFER_STALL_TIMEOUT_SECONDS):
                            raise TimeoutError(
                                "Directory upload stalled for more than {:.0f}s"
                                .format(model.TRANSFER_STALL_TIMEOUT_SECONDS))
                        continue
                    if amount <= 0:
                        error = model._stream_stderr(channel)
                        raise RuntimeError(
                            error or "Remote tar upload closed early")
                    last_io = time.monotonic()
                    view = view[amount:]
                return len(data)

            def flush(self):
                return None

        class ProgressReader:
            def __init__(self, stream):
                self.stream = stream

            def read(self, size=-1):
                model._cancelled(cancel)
                data = self.stream.read(size)
                if data:
                    report_progress(len(data))
                return data

        def add_path(archive, source, archive_name):
            model._cancelled(cancel)
            info = archive.gettarinfo(str(source), arcname=str(archive_name))
            if info.isreg():
                with source.open("rb", buffering=model.STREAM_IO_SIZE) as stream:
                    archive.addfile(info, ProgressReader(stream))
            else:
                archive.addfile(info)
            if info.isdir():
                for child in sorted(source.iterdir(),
                                    key=lambda value: value.name.casefold()):
                    add_path(
                        archive, child,
                        PurePosixPath(str(archive_name)) / child.name)

        try:
            channel.settimeout(self.HOT_DOWNLOAD_CHANNEL_TIMEOUT)
            channel.exec_command(
                "tar -xpf - -C {}".format(self._shell_quote(remote_folder)))
            writer = ChannelWriter()
            with tarfile.open(
                    fileobj=writer, mode="w|", format=tarfile.PAX_FORMAT,
                    bufsize=self.STREAM_IO_SIZE, dereference=False) as archive:
                add_path(archive, local_folder, local_folder.name)
            report_progress(force=True)
            channel.shutdown_write()
            exit_status = self._wait_stream_exit(channel, cancel=cancel)
            error = self._stream_stderr(channel)
            if exit_status != 0:
                raise RuntimeError(
                    error or "Directory upload failed with exit code {}".format(
                        exit_status))
        finally:
            try:
                channel.close()
            except Exception:
                pass

    @staticmethod
    def _safe_tar_destination(root, member_name):
        parts = [part for part in PurePosixPath(str(member_name)).parts
                 if part not in ("", ".")]
        if not parts or any(part == ".." for part in parts):
            raise RuntimeError(
                "Unsafe path in remote archive: {}".format(member_name))
        destination = Path(root).joinpath(*parts)
        root_resolved = Path(root).resolve()
        destination_resolved = destination.resolve(strict=False)
        try:
            destination_resolved.relative_to(root_resolved)
        except ValueError:
            raise RuntimeError(
                "Unsafe path in remote archive: {}".format(member_name))
        return destination

    def _download_directory_stream(self, remote_folder, local_parent,
                                   cancel=None, advance=None, client=None):
        """Receive a directory as one tar stream and extract it safely."""
        remote_folder = self.normalize(remote_folder)
        local_parent = Path(local_parent)
        local_parent.mkdir(parents=True, exist_ok=True)
        channel = self._open_stream_channel(client=client)
        model = self

        class ChannelReader:
            def read(self, size=-1):
                requested = (model.STREAM_IO_SIZE if size is None or size < 0
                             else max(1, int(size)))
                while True:
                    model._cancelled(cancel)
                    try:
                        data = channel.recv(requested)
                    except socket.timeout:
                        if channel.exit_status_ready():
                            return b""
                        continue
                    if data:
                        return data
                    if channel.exit_status_ready():
                        return b""

        directory_metadata = []
        try:
            channel.settimeout(self.HOT_DOWNLOAD_CHANNEL_TIMEOUT)
            channel.exec_command(
                "tar -chpf - -C {} -- {}".format(
                    self._shell_quote(remote_folder.parent),
                    self._shell_quote(remote_folder.name)))
            with tarfile.open(
                    fileobj=ChannelReader(), mode="r|*",
                    bufsize=self.STREAM_IO_SIZE) as archive:
                for member in archive:
                    self._cancelled(cancel)
                    destination = self._safe_tar_destination(
                        local_parent, member.name)
                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                        directory_metadata.append((destination, member))
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if member.isreg():
                        source = archive.extractfile(member)
                        if source is None:
                            raise RuntimeError(
                                "Could not read {} from remote archive".format(
                                    member.name))
                        with source, destination.open(
                                "wb", buffering=self.STREAM_IO_SIZE) as output:
                            while True:
                                self._cancelled(cancel)
                                chunk = source.read(self.STREAM_IO_SIZE)
                                if not chunk:
                                    break
                                output.write(chunk)
                                if advance:
                                    advance(len(chunk))
                        try:
                            os.chmod(str(destination), member.mode)
                        except OSError:
                            pass
                        try:
                            os.utime(str(destination),
                                     (member.mtime, member.mtime))
                        except OSError:
                            pass
                        continue
                    if member.islnk():
                        link_target = self._safe_tar_destination(
                            local_parent, member.linkname)
                        try:
                            os.link(str(link_target), str(destination))
                        except OSError:
                            if link_target.is_file():
                                shutil.copy2(str(link_target), str(destination))
                            else:
                                raise
                        continue
                    if member.issym():
                        # GNU tar is invoked with --dereference, so only broken
                        # links should reach this branch. Match the old SFTP
                        # behavior by reporting a transfer error instead of
                        # creating an unexpected Windows shortcut/link.
                        raise RuntimeError(
                            "Cannot download broken symbolic link: {}".format(
                                member.name))

            exit_status = self._wait_stream_exit(channel, cancel=cancel)
            error = self._stream_stderr(channel)
            if exit_status != 0:
                raise RuntimeError(
                    error or "Directory download failed with exit code {}".format(
                        exit_status))
            for destination, member in reversed(directory_metadata):
                try:
                    os.chmod(str(destination), member.mode)
                except OSError:
                    pass
                try:
                    os.utime(str(destination), (member.mtime, member.mtime))
                except OSError:
                    pass
        finally:
            try:
                channel.close()
            except Exception:
                pass

    def _publish_uploaded_file(
            self, sftp_client, temporary, target, client=None):
        """Atomically replace *target* with a fully uploaded temporary file.

        Direct ``SFTPClient.put(..., target)`` truncates an existing destination
        before the upload is complete.  Besides exposing partial files, old
        Paramiko builds bundled with Abaqus have shown native instability when
        that overwrite races directory/status activity.  Publish by rename only
        after validation instead.
        """
        temporary = self.normalize(temporary)
        target = self.normalize(target)
        posix_rename = getattr(sftp_client, "posix_rename", None)
        if callable(posix_rename):
            try:
                posix_rename(str(temporary), str(target))
                return
            except (AttributeError, IOError, OSError):
                # Older/non-OpenSSH SFTP servers may not implement the extension.
                pass

        # Linux is the supported server platform. ``mv -f`` has atomic rename
        # semantics when source/target share the same directory/filesystem.
        command = "mv -f -- {} {}".format(
            self._shell_quote(temporary), self._shell_quote(target))
        if client is not None:
            status, output, error = self._exec_client(
                client, command, timeout=self.SFTP_REQUEST_TIMEOUT_SECONDS)
        else:
            status, output, error = self._exec_remote(command)
        if status != 0:
            raise RuntimeError(
                error or output or
                "Could not publish uploaded file (exit code {})".format(status))

    def _upload_small_file_atomic(self, local_path, target, cancel, advance,
                                  sftp_client, client=None):
        """Upload a small file to a sibling temp name, then atomically publish."""
        local_path = Path(local_path)
        target = self.normalize(target)
        before = local_path.stat()
        expected_size = int(before.st_size or 0)
        temporary = target.with_name(
            ".{}.winux-upload-{}".format(target.name, uuid.uuid4().hex))
        try:
            self._cancelled(cancel)
            sftp_client.put(
                str(local_path), str(temporary),
                callback=self._progress_callback(cancel, advance),
                confirm=False)
            self._cancelled(cancel)

            after = local_path.stat()
            before_mtime = int(getattr(
                before, "st_mtime_ns", before.st_mtime * 1e9))
            after_mtime = int(getattr(
                after, "st_mtime_ns", after.st_mtime * 1e9))
            if int(after.st_size or 0) != expected_size or after_mtime != before_mtime:
                raise RuntimeError("Local file changed during upload")

            remote_size = int(sftp_client.stat(str(temporary)).st_size or 0)
            if remote_size != expected_size:
                raise RuntimeError(
                    "Incomplete upload: expected {} bytes, uploaded {}".format(
                        expected_size, remote_size))
            self._publish_uploaded_file(
                sftp_client, temporary, target, client=client)
        finally:
            # After a successful atomic rename this path no longer exists. On
            # cancellation/error remove only the hidden temporary file; the old
            # destination remains intact.
            try:
                sftp_client.remove(str(temporary))
            except Exception:
                pass

    def upload(self, local_paths, remote_folder, move=False, cancel=None,
               progress=None):
        remote_folder = self.normalize(remote_folder)
        entries = [(Path(path), self._local_size(Path(path)))
                   for path in local_paths]
        overall_total = sum(size for _path, size in entries)
        overall_done = 0

        # Use dedicated channels on the application's single SSH transport.
        # Long/stalled transfers do not hold the browser/qstat wire lock, while
        # no second TCP/SSH login is created.
        with self._auxiliary_session() as (transfer_client, transfer_sftp):
            for local_path, current_total in entries:
                self._cancelled(cancel)
                current_done = 0

                def advance(amount):
                    nonlocal current_done, overall_done
                    current_done += amount
                    overall_done += amount
                    if progress:
                        progress(local_path.name, current_done, current_total,
                                 overall_done, overall_total)

                target = remote_folder / local_path.name
                if local_path.is_dir():
                    if self._supports_remote_tar(client=transfer_client):
                        self._upload_directory_stream(
                            local_path, remote_folder, cancel=cancel,
                            advance=advance, client=transfer_client)
                    else:
                        self._upload_dir(
                            local_path, target, cancel, advance,
                            sftp_client=transfer_sftp, client=transfer_client)
                    if move:
                        shutil.rmtree(str(local_path))
                else:
                    if current_total >= self.STREAM_FILE_THRESHOLD:
                        self._upload_file_stream(
                            local_path, target, cancel=cancel,
                            advance=advance, sftp_client=transfer_sftp, client=transfer_client)
                    else:
                        self._upload_small_file_atomic(
                            local_path, target, cancel, advance, transfer_sftp, client=transfer_client)
                    if move:
                        local_path.unlink()
                if progress:
                    progress(local_path.name, current_total, current_total,
                             overall_done, overall_total)

    def _upload_dir(self, local_folder, remote_folder, cancel=None, advance=None,
                    sftp_client=None, client=None):
        self._cancelled(cancel)
        sftp_client = sftp_client or self.sftp
        try:
            sftp_client.mkdir(str(remote_folder))
        except IOError:
            pass
        for child in local_folder.iterdir():
            target = remote_folder / child.name
            if child.is_dir():
                self._upload_dir(
                    child, target, cancel, advance,
                    sftp_client=sftp_client, client=client)
            else:
                size = int(child.stat().st_size or 0)
                if size >= self.STREAM_FILE_THRESHOLD:
                    self._upload_file_stream(
                        child, target, cancel=cancel, advance=advance,
                        sftp_client=sftp_client, client=client)
                else:
                    self._upload_small_file_atomic(
                        child, target, cancel, advance, sftp_client, client=client)

    def download(self, remote_paths, local_folder, move=False, cancel=None,
                 progress=None):
        local_folder = Path(local_folder)

        with self._auxiliary_session() as (transfer_client, transfer_sftp):
            entries = [(self.normalize(path),
                        self._remote_size(path, sftp_client=transfer_sftp))
                       for path in remote_paths]
            overall_total = sum(size for _path, size in entries)
            overall_done = 0
            for remote_path, current_total in entries:
                self._cancelled(cancel)
                current_done = 0

                def advance(amount):
                    nonlocal current_done, overall_done
                    current_done += amount
                    overall_done += amount
                    if progress:
                        progress(remote_path.name, current_done, current_total,
                                 overall_done, overall_total)

                target = local_folder / remote_path.name
                if self.is_dir(remote_path, sftp_client=transfer_sftp):
                    if self._supports_remote_tar(client=transfer_client):
                        self._download_directory_stream(
                            remote_path, local_folder, cancel=cancel,
                            advance=advance, client=transfer_client)
                    else:
                        self._download_dir(
                            remote_path, target, cancel, advance,
                            sftp_client=transfer_sftp, client=transfer_client)
                    if move:
                        self.remove(remote_path, sftp_client=transfer_sftp)
                else:
                    self._download_file(
                        remote_path, target, cancel=cancel, advance=advance,
                        sftp_client=transfer_sftp, client=transfer_client)
                    if move:
                        transfer_sftp.remove(str(remote_path))
                if progress:
                    progress(remote_path.name, current_total, current_total,
                             overall_done, overall_total)

    def _download_dir(self, remote_folder, local_folder, cancel=None,
                      advance=None, sftp_client=None, client=None):
        self._cancelled(cancel)
        sftp_client = sftp_client or self.sftp
        local_folder.mkdir(parents=True, exist_ok=True)
        for attr in sftp_client.listdir_attr(str(remote_folder)):
            source = remote_folder / attr.filename
            target = local_folder / attr.filename
            if stat.S_ISDIR(attr.st_mode):
                self._download_dir(
                    source, target, cancel, advance,
                    sftp_client=sftp_client, client=client)
            else:
                self._download_file(
                    source, target, cancel=cancel, advance=advance,
                    expected_attributes=attr, sftp_client=sftp_client, client=client)

    @staticmethod
    def _partial_paths(target):
        target = Path(target)
        partial = target.with_name(target.name + ".winux-part")
        metadata = target.with_name(target.name + ".winux-part.json")
        return partial, metadata

    @staticmethod
    def _remove_partial(partial, metadata):
        for path in (partial, metadata):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    @staticmethod
    def _write_resume_metadata(path, data):
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        os.replace(str(temporary), str(path))

    def _download_file(
            self, remote_path, target, cancel=None, advance=None,
            expected_attributes=None, sftp_client=None, client=None):
        """Resume into an app-owned partial and atomically publish on success."""
        sftp_client = sftp_client or self.sftp
        remote_path = self.normalize(remote_path)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        before = expected_attributes or sftp_client.stat(str(remote_path))
        signature = {
            "remote_path": str(remote_path),
            "size": int(before.st_size or 0),
            "mtime": int(before.st_mtime or 0),
        }
        partial, metadata = self._partial_paths(target)
        saved = None
        try:
            if metadata.is_file():
                saved = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            saved = None

        offset = partial.stat().st_size if partial.is_file() else 0
        if saved != signature or offset > signature["size"]:
            self._remove_partial(partial, metadata)
            offset = 0
        self._write_resume_metadata(metadata, signature)
        self._cancelled(cancel)
        if advance and offset:
            advance(offset)

        try:
            remaining = max(0, signature["size"] - offset)
            if remaining >= self.STREAM_FILE_THRESHOLD:
                self._download_file_stream(
                    remote_path, partial, offset, signature["size"],
                    cancel=cancel, advance=advance, client=client)
            # Paramiko's SFTPClient.get() owns an aggressively pipelined read
            # loop and remains efficient for small files where opening a new
            # exec channel would cost more than it saves.
            else:
                fast_get = getattr(sftp_client, "get", None)
                if offset == 0 and callable(fast_get):
                    previous = 0

                    def fast_progress(transferred, _total):
                        nonlocal previous
                        self._cancelled(cancel)
                        amount = max(0, int(transferred) - previous)
                        previous = int(transferred)
                        if advance and amount:
                            advance(amount)

                    try:
                        fast_get(
                            str(remote_path), str(partial),
                            callback=fast_progress,
                            prefetch=True,
                            max_concurrent_prefetch_requests=(
                                self.DOWNLOAD_PREFETCH_REQUESTS),
                        )
                    except TypeError:
                        # Paramiko < 3.3 does not expose the request-limit
                        # keyword, but its legacy get() remains pipelined.
                        fast_get(
                            str(remote_path), str(partial),
                            callback=fast_progress,
                        )
                else:
                    with sftp_client.open(str(remote_path), "rb") as source:
                        source.seek(offset)
                        try:
                            source.prefetch(
                                file_size=signature["size"],
                                max_concurrent_requests=(
                                    self.DOWNLOAD_PREFETCH_REQUESTS))
                        except (AttributeError, TypeError, OSError):
                            pass
                        with partial.open(
                                "ab" if offset else "wb",
                                buffering=self.DOWNLOAD_CHUNK_SIZE) as destination:
                            while True:
                                self._cancelled(cancel)
                                chunk = source.read(self.DOWNLOAD_CHUNK_SIZE)
                                if not chunk:
                                    break
                                destination.write(chunk)
                                if advance:
                                    advance(len(chunk))
                            destination.flush()
        except Exception:
            # Cancellation and transient network errors intentionally retain
            # the partial plus signature so the next attempt can resume.
            raise

        after = sftp_client.stat(str(remote_path))
        after_signature = {
            "remote_path": str(remote_path),
            "size": int(after.st_size or 0),
            "mtime": int(after.st_mtime or 0),
        }
        actual_size = partial.stat().st_size if partial.is_file() else -1
        if after_signature != signature:
            self._remove_partial(partial, metadata)
            raise RuntimeError(
                "Remote file changed during download; the partial copy was discarded")
        if actual_size != signature["size"]:
            raise RuntimeError(
                "Incomplete download: expected {} bytes, received {}"
                .format(signature["size"], actual_size))
        os.replace(str(partial), str(target))
        try:
            metadata.unlink()
        except FileNotFoundError:
            pass
        return target

    @staticmethod
    def _cancelled(cancel):
        if cancel is not None and cancel.is_set():
            raise RuntimeError("Operation cancelled")

    @staticmethod
    def _progress_callback(cancel, advance=None):
        previous = 0

        def progress(_transferred, _total):
            nonlocal previous
            RemoteTransferMixin._cancelled(cancel)
            if advance:
                advance(max(0, _transferred - previous))
            previous = _transferred
        return progress

    @staticmethod
    def _local_size(path):
        if path.is_file():
            return path.stat().st_size
        return sum(child.stat().st_size for child in path.rglob("*")
                   if child.is_file())

