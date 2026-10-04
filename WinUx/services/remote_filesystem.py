from __future__ import annotations

import posixpath
import shutil
import stat
from pathlib import PurePosixPath

from ..model import FileItem, FileSystemModel
from .ssh_serialization import _serialized_wire_call


class RemoteFilesystemMixin:
    """Remote browsing and filesystem mutation over the shared SSH transport."""

    @_serialized_wire_call
    def list_directory(self, folder):
        if not self.connected:
            raise RuntimeError("Not connected to an SSH server")
        folder = self.normalize(folder)
        items = []
        for attr in self.sftp.listdir_attr(str(folder)):
            is_dir = stat.S_ISDIR(attr.st_mode)
            items.append(FileItem(attr.filename, folder / attr.filename, is_dir,
                                  attr.st_size or 0, attr.st_mtime or 0))
        return sorted(items, key=lambda item: (not item.is_dir, item.name.casefold()))

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
        """Copy or move remote items within the connected server."""
        remote_folder = self.normalize(remote_folder)
        created = []
        for source in remote_paths:
            self._cancelled(cancel)
            source = self.normalize(source)
            target = self.unique_target(remote_folder / source.name)
            if move:
                self.sftp.rename(str(source), str(target))
            else:
                self._copy_path(source, target, cancel)
            created.append(target)
        return created

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
