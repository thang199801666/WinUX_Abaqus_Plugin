"""Local filesystem clipboard operations for ExplorerListView."""
from __future__ import annotations

import os
import shutil


class ExplorerFileOperationsMixin:
    @staticmethod
    def _split_name_for_conflict(name, is_dir=False):
        """Return ``(stem, extension)`` while preserving file extensions."""
        if is_dir:
            return name, ""
        stem, extension = os.path.splitext(name)
        return stem, extension

    @classmethod
    def unique_destination_path(cls, directory, name, is_dir=False, exclude_path=None):
        """Return a non-existing Explorer-style destination path.

        Conflicts use ``name (2).ext``, ``name (3).ext`` and so on. The first
        conflict starts at 2, matching Windows Explorer.
        """
        directory = os.path.abspath(os.fspath(directory))
        candidate = os.path.join(directory, name)
        excluded = os.path.normcase(os.path.abspath(exclude_path)) if exclude_path else None

        def available(path):
            normalized = os.path.normcase(os.path.abspath(path))
            return normalized == excluded or not os.path.exists(path)

        if available(candidate):
            return candidate
        stem, extension = cls._split_name_for_conflict(name, is_dir=is_dir)
        count = 2
        while True:
            candidate = os.path.join(directory, f"{stem} ({count}){extension}")
            if available(candidate):
                return candidate
            count += 1

    def copy_selected(self):
        paths = [os.path.abspath(item.path) for item in self.get_selected() if item.path]
        self._clipboard_paths = paths
        self._clipboard_mode = "copy" if paths else None
        return list(paths)

    def cut_selected(self):
        paths = [os.path.abspath(item.path) for item in self.get_selected() if item.path]
        self._clipboard_paths = paths
        self._clipboard_mode = "cut" if paths else None
        return list(paths)

    def clear_clipboard(self):
        self._clipboard_paths = []
        self._clipboard_mode = None
        return self

    def paste(self, destination=None):
        """Paste clipboard entries into a directory and return created paths."""
        if not self._clipboard_paths:
            return []
        destination = os.path.abspath(os.path.expanduser(destination or self.current_path or ""))
        if not destination or not os.path.isdir(destination):
            raise NotADirectoryError(destination)

        created = []
        errors = []
        mode = self._clipboard_mode or "copy"
        for source in list(self._clipboard_paths):
            try:
                if not os.path.exists(source):
                    raise FileNotFoundError(source)
                source_abs = os.path.abspath(source)
                if os.path.normcase(os.path.dirname(source_abs)) == os.path.normcase(destination) and mode == "cut":
                    continue
                is_dir = os.path.isdir(source_abs)
                target = self.unique_destination_path(destination, os.path.basename(source_abs), is_dir=is_dir)
                if is_dir:
                    if mode == "cut":
                        shutil.move(source_abs, target)
                    else:
                        shutil.copytree(source_abs, target)
                else:
                    if mode == "cut":
                        shutil.move(source_abs, target)
                    else:
                        shutil.copy2(source_abs, target)
                created.append(target)
            except Exception as exc:
                errors.append((source, exc))
                if self.on_move_error:
                    self.on_move_error(exc)

        if mode == "cut" and not errors:
            self.clear_clipboard()
        self.reload_path(preserve_selection=False)
        if created:
            normalized = {os.path.normcase(os.path.abspath(path)) for path in created}
            self.selected = {i for i, item in enumerate(self.items) if os.path.normcase(os.path.abspath(item.path)) in normalized}
            if self.selected:
                self._current_index = min(self.selected)
                self.last_clicked_index = self._current_index
            self._sync_qt_selection_from_fields()
            self._update_selection_draws()
            self._update_status_bar()
        return created

    def delete_selected(self):
        """Delete selected files/folders permanently and return deleted paths."""
        deleted = []
        for item in list(self.get_selected()):
            try:
                if item.is_dir:
                    shutil.rmtree(item.path)
                else:
                    os.remove(item.path)
                deleted.append(item.path)
            except Exception as exc:
                if self.on_move_error:
                    self.on_move_error(exc)
                else:
                    raise
        self.reload_path(preserve_selection=False)
        return deleted
