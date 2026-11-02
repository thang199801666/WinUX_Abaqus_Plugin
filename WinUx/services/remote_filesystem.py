from __future__ import annotations

import posixpath
import shutil
import stat
import time
from pathlib import PurePosixPath

from ..models import FileItem, FileSystemModel
from .ssh_serialization import _serialized_wire_call
from .remote_identity import RemoteIdentityNames
from .transfer.conflicts import TransferItemState


class RemoteFilesystemMixin:
    """Remote browsing and filesystem mutation over the shared SSH transport."""

    @_serialized_wire_call
    def transfer_path_metadata(self, path):
        if not self.connected:
            raise RuntimeError('Not connected to an SSH server')
        try:
            return TransferItemState.from_stat(self.sftp.lstat(str(self.normalize(path))))
        except OSError as exc:
            if exc.errno == 2:
                return None
            raise

    def transfer_directory_metadata(self, folder, *, limit=10000, check=lambda: None):
        """Bounded metadata-only listing; do not resolve owners or follow links."""
        if not self.connected:
            raise RuntimeError('Not connected to an SSH server')
        from .transfer.tree import read_sftp_directory
        with self._auxiliary_session() as (_, sftp):
            return read_sftp_directory(sftp, self.normalize(folder), limit=limit, check=check)

    @_serialized_wire_call
    def transfer_metadata(self, paths):
        """One attribute listing per parent; no owner lookup or UI row building."""
        if not self.connected:
            raise RuntimeError('Not connected to an SSH server')
        groups, result = {}, {}
        for path in paths:
            path = self.normalize(path)
            groups.setdefault(path.parent, []).append(path)
        for parent, requested in groups.items():
            entries = {entry.filename: entry for entry in self.sftp.listdir_attr(str(parent))}
            for path in requested:
                attr = entries.get(path.name)
                result[str(path)] = TransferItemState.from_stat(attr) if attr is not None else None
        return result

    @_serialized_wire_call
    def list_directory_names(self, folder):
        """Name-only preflight: do not resolve owners/groups or build row data."""
        if not self.connected:
            raise RuntimeError('Not connected to an SSH server')
        return self.sftp.listdir(str(self.normalize(folder)))

    @_serialized_wire_call
    def list_directory(self, folder):
        if not self.connected:
            raise RuntimeError("Not connected to an SSH server")
        folder = self.normalize(folder)
        attrs = self.sftp.listdir_attr(str(folder))
        client = getattr(self, 'client', None)
        if (not hasattr(self, '_identity_names') or
                getattr(self, '_identity_names_client', None) is not client):
            self._identity_names = RemoteIdentityNames()
            self._identity_names_client = client
        uids = {attr.st_uid for attr in attrs if getattr(attr, 'st_uid', None) is not None}
        gids = {attr.st_gid for attr in attrs if getattr(attr, 'st_gid', None) is not None}
        owners, groups = self._identity_names.resolve(uids, gids, self._lookup_identity_names)
        items = []
        for attr in attrs:
            is_dir = stat.S_ISDIR(attr.st_mode)
            items.append(FileItem(attr.filename, folder / attr.filename, is_dir,
                                  attr.st_size or 0, attr.st_mtime or 0,
                                  is_hidden=attr.filename.startswith("."),
                                  mode=getattr(attr, "st_mode", None),
                                  uid=getattr(attr, "st_uid", None),
                                  gid=getattr(attr, "st_gid", None),
                                  accessed=getattr(attr, "st_atime", None),
                                  owner_name=owners.get(getattr(attr, 'st_uid', None), ''),
                                  group_name=groups.get(getattr(attr, 'st_gid', None), ''),
                                  is_symlink=stat.S_ISLNK(attr.st_mode)))
        return sorted(items, key=lambda item: (not item.is_dir, item.name.casefold()))

    def _lookup_identity_names(self, command):
        _stdin, stdout, stderr = self._exec_command_streams(command, timeout=5)
        try:
            return stdout.read().decode('utf-8', 'replace')
        finally:
            stdout.channel.close()

    @_serialized_wire_call
    def search_directories(self, text, limit=100):
        """Find folders below the remote home directory by partial name."""
        if not self.client:
            raise RuntimeError("Not connected to an SSH server")
        query = str(text).strip()
        if not query:
            return [str(item.path) for item in self.list_directory(self.home)
                    if item.is_dir][:limit]
        # Quote both the search root and wildcard pattern so user-entered text
        # can never be interpreted as part of the remote shell command.
        pattern = "*{}*".format(query)
        command = "find {} -type d -iname {} -print 2>/dev/null | head -n {}".format(
            self._shell_quote(self.home), self._shell_quote(pattern), int(limit))
        output = self.run_command(command)
        return [line.strip() for line in output.splitlines() if line.strip()]

    @_serialized_wire_call
    def is_dir(self, path, sftp_client=None):
        sftp_client = sftp_client or self.sftp
        return stat.S_ISDIR(sftp_client.stat(str(path)).st_mode)

    @_serialized_wire_call
    def exists(self, path, sftp_client=None):
        if sftp_client is None and not self.connected:
            return False
        sftp_client = sftp_client or self.sftp
        try:
            sftp_client.stat(str(self.normalize(path)))
            return True
        except OSError:
            return False

    @_serialized_wire_call
    def move(self, remote_paths, remote_folder, cancel=None):
        remote_folder = self.normalize(remote_folder)
        for source in remote_paths:
            self._cancelled(cancel)
            source = self.normalize(source)
            self.sftp.rename(str(source), str(remote_folder / source.name))

    @_serialized_wire_call
    def transfer(self, remote_paths, remote_folder, move=False, cancel=None):
        """Copy or move items entirely on the connected server.

        Earlier builds implemented remote copy by opening each source through
        SFTP and writing it back through SFTP.  Although no temporary file was
        created, every byte still travelled server -> WinUX -> server.  Use the
        host filesystem instead so same-server clipboard operations are as
        cheap as running ``cp``/``mv`` directly in an SSH terminal.
        """
        if not self.connected:
            raise RuntimeError("Not connected to an SSH server")
        remote_folder = self.normalize(remote_folder)
        created = []
        for source in remote_paths:
            self._cancelled(cancel)
            source = self.normalize(source)
            target = self.unique_target(remote_folder / source.name)
            command = "{} -- {} {}".format(
                "mv" if move else "cp -a",
                self._shell_quote(source), self._shell_quote(target))
            self._run_server_file_command(command, cancel=cancel)
            created.append(target)
        return created

    def _run_server_file_command(self, command, cancel=None):
        """Run one quiet filesystem command on the remote host.

        The exec channel is polled so application shutdown/cancellation can
        close it without waiting for a large server-side recursive copy.
        ``cp``/``mv`` are intentionally run on the server; stdout/stderr are
        expected to remain tiny and are consumed only after completion.
        """
        _stdin, stdout, stderr = self._exec_command_streams(command, timeout=None)
        channel = stdout.channel
        try:
            while not channel.exit_status_ready():
                self._cancelled(cancel)
                time.sleep(0.05)
            status = channel.recv_exit_status()
            output = stdout.read().decode("utf-8", "replace").strip()
            error = stderr.read().decode("utf-8", "replace").strip()
        except Exception:
            try:
                channel.close()
            except Exception:
                pass
            raise
        if status != 0:
            raise RuntimeError(
                error or output or
                "Remote filesystem command failed with exit code {}".format(status))
        return True

    @_serialized_wire_call
    def _copy_path(self, source, target, cancel=None):
        self._cancelled(cancel)
        if self.is_dir(source):
            self.sftp.mkdir(str(target))
            for item in self.sftp.listdir_attr(str(source)):
                self._copy_path(source / item.filename, target / item.filename,
                                cancel)
            return
        with self.sftp.open(str(source), "rb") as source_file:
            with self.sftp.open(str(target), "wb") as target_file:
                shutil.copyfileobj(source_file, target_file, length=1024 * 1024)

    @_serialized_wire_call
    def rename(self, path, new_name):
        path = self.normalize(path)
        new_name = FileSystemModel.validate_name(new_name)
        if new_name == path.name:
            return path
        target = path.parent / new_name
        if self.exists(target):
            raise OSError("An item with that name already exists")
        self.sftp.rename(str(path), str(target))
        return target

    @_serialized_wire_call
    def new_folder(self, parent, name="New folder"):
        target = self.unique_target(self.normalize(parent) / name)
        self.sftp.mkdir(str(target))
        return target

    @_serialized_wire_call
    def new_file(self, parent, name="New file"):
        target = self.unique_target(self.normalize(parent) / name)
        with self.sftp.open(str(target), "wb"):
            pass
        return target

    def delete(self, paths):
        """Recursively delete distinct top-level remote selections.

        Multi-selection may contain both a directory and one of its children.
        Removing the child first and then traversing the parent used to produce
        false 'not found' errors. Descendants of an already selected directory
        are therefore removed from the operation list.
        """
        normalized = []
        seen = set()
        for value in paths:
            path = self.normalize(value)
            if str(path) == "/":
                raise ValueError("The server root directory cannot be deleted")
            key = str(path)
            if key not in seen:
                seen.add(key)
                normalized.append(path)

        normalized.sort(key=lambda item: (len(item.parts), str(item).casefold()))
        roots = []
        for path in normalized:
            if any(parent == path or parent in path.parents for parent in roots):
                continue
            roots.append(path)

        deleted = []
        # Recursive deletion runs on a dedicated SFTP channel. The controller
        # executes this method on a worker thread, so reusing the browsing SFTP
        # client could otherwise race with directory refreshes on the UI thread.
        with self._transfer_sftp() as delete_sftp:
            for path in roots:
                if not self.exists(path, sftp_client=delete_sftp):
                    continue
                self.remove(path, sftp_client=delete_sftp)
                deleted.append(path)
        return deleted

    @_serialized_wire_call
    def unique_target(self, target):
        target = self.normalize(target)
        if not self.exists(target):
            return target
        suffix = target.suffix
        stem = target.name[:-len(suffix)] if suffix else target.name
        counter = 1
        while True:
            label = "{} - Copy".format(stem)
            if counter > 1:
                label += " ({})".format(counter)
            candidate = target.parent / (label + suffix)
            if not self.exists(candidate):
                return candidate
            counter += 1

    @_serialized_wire_call
    def _remote_size(self, path, sftp_client=None):
        sftp_client = sftp_client or self.sftp
        path = self.normalize(path)
        attributes = sftp_client.stat(str(path))
        if not stat.S_ISDIR(attributes.st_mode):
            return attributes.st_size or 0
        total = 0
        for child in sftp_client.listdir_attr(str(path)):
            child_path = path / child.filename
            total += (self._remote_size(
                child_path, sftp_client=sftp_client)
                if stat.S_ISDIR(child.st_mode) else child.st_size or 0)
        return total

    @_serialized_wire_call
    def remove(self, remote_path, sftp_client=None):
        remote_path = self.normalize(remote_path)
        sftp_client = sftp_client or self.sftp
        if self.is_dir(remote_path, sftp_client=sftp_client):
            for attr in sftp_client.listdir_attr(str(remote_path)):
                self.remove(
                    remote_path / attr.filename, sftp_client=sftp_client)
            sftp_client.rmdir(str(remote_path))
        else:
            sftp_client.remove(str(remote_path))

    @staticmethod
    def normalize(path):
        value = posixpath.normpath(str(path).replace("\\", "/"))
        if not value.startswith("/"):
            value = "/" + value
        return PurePosixPath(value)
