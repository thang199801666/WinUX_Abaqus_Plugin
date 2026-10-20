"""File selection using the app's shared folder-browser surface and controls."""
from __future__ import annotations

import os
from pathlib import Path

from DearUIQt.backends import dpg

from .local_folder_form import LocalFolderDialog
from .folder_browser_style import METRICS


class LocalFileDialog(LocalFolderDialog):
    """Open/save a single file with the same browser as LocalFolderDialog."""

    selection_caption = "File name:"
    context_selection_caption = "Select file"
    selection_height = METRICS.selection_height

    def __init__(self, view, initial, on_result, *, extensions=(), save=False,
                 default_filename=""):
        self.save = bool(save)
        self.extensions = tuple(dict.fromkeys(
            ("." + str(ext).lstrip("*. ")).lower()
            for ext in extensions if str(ext).strip() not in ("", "*", ".*", "*.*")))
        self._show_all_files = not self.extensions
        self._filename = str(default_filename or "")
        self._overwrite_path = None
        self.dialog_title = "Save File" if self.save else "Open File"
        self.accept_caption = "Save" if self.save else "Open"
        super().__init__(view, initial, on_result)

    def _resolve_initial_location(self, value):
        if os.path.isfile(value):
            return str(Path(value).parent), Path(value).name
        return super()._resolve_initial_location(value)

    def _apply_initial_filename(self, filename):
        if filename is not None:
            self._filename = filename
        dpg.set_value(self.file_edit, self._filename)

    def _build_selection_fields(self):
        super()._build_selection_fields()
        self.file_edit = self.folder_edit
        dpg.set_value(self.file_edit, self._filename)
        self._supported_filter = "Supported files ({})".format(
            ", ".join("*" + ext for ext in self.extensions))
        filters = [self._supported_filter, "All files (*.*)"] if self.extensions else ["All files (*.*)"]
        self._form_labels['filter'] = self._form_caption("Files of type:", self._selection_grid.cell(1, 0))
        self.file_type = self.combo(
            filters, parent=self._selection_grid.cell(1, 1).tag,
            default_value=filters[0], width=-1, callback=self._file_type_changed,
            theme_provider=self._selector_theme_provider('combo'))

    def _include_entry(self, entry, is_dir):
        return is_dir or (entry.is_file(follow_symlinks=True) and
                          (self._show_all_files or Path(entry.name).suffix.lower() in self.extensions))

    def _file_type_changed(self, _sender, value, *_args):
        self._show_all_files = value == "All files (*.*)"
        self._refresh()

    def _filter_entries(self):
        super()._filter_entries()
        # Reuse the shared list renderer, search and sorting, including folders
        # so every location remains navigable with any extension filter.
        query = str(dpg.get_value(self.filter_edit) or "").strip()
        if not self.listbox._values:
            self.listbox.empty_text = "No files match your search." if query else "No matching files in this folder."
            self.listbox.setItems([])
        self._set_status("{} item(s)".format(len(self.listbox._values)))

    def _selection_changed(self, key):
        if key in self._entries and self._entry_types.get(key) != "Folder":
            dpg.set_value(self.file_edit, Path(key).name)
            self._overwrite_path = None

    def _navigate(self, value, remember=True):
        filename = str(dpg.get_value(self.file_edit) or "")
        changed = super()._navigate(value, remember)
        if changed:
            dpg.set_value(self.file_edit, filename if self.save else "")
            self._overwrite_path = None
        return changed

    def _enter_key(self, key):
        path = self._entries.get(key) or str(key or "")
        if os.path.isdir(path):
            self._navigate(path)
        elif path:
            dpg.set_value(self.file_edit, path)
            self._select_folder()

    def _commit_folder_rename(self, path=None, new_name=None):
        source = self._rename_path
        is_folder = bool(source and os.path.isdir(source))
        filename = dpg.get_value(self.file_edit)
        renamed = super()._commit_folder_rename(path, new_name)
        if renamed and is_folder:
            dpg.set_value(self.file_edit, filename)
        return renamed

    def _select_folder(self):
        """Override the shared browser's accept action with file semantics."""
        if self._rename_path is not None and not self._commit_folder_rename():
            return
        value = str(dpg.get_value(self.file_edit) or "").strip()
        if not value:
            self._set_status("Enter or select a file name.", error=True)
            return
        path = Path(os.path.abspath(os.path.join(
            self._current_path, os.path.expandvars(os.path.expanduser(value)))))
        if path.is_dir():
            self._navigate(str(path))
            return
        if self.save and not path.suffix and self.extensions and not self._show_all_files:
            path = path.with_suffix(self.extensions[0])
        if not self._show_all_files and path.suffix.lower() not in self.extensions:
            self._set_status("Choose a supported file type or select All files.", error=True)
            return
        if self.save:
            if not path.parent.is_dir():
                self._set_status("Destination folder does not exist.", error=True)
                return
            if path.exists() and not path.is_file():
                self._set_status("Destination is not a regular file.", error=True)
                return
            if path.exists() and self._overwrite_path != str(path):
                self._overwrite_path = str(path)
                self._set_status("File exists. Press Save again to replace it.", error=True)
                return
        elif not path.is_file():
            self._set_status("File does not exist: {}".format(path), error=True)
            return
        self.finish(str(path))

    def _run_folder_menu_action(self, action, context):
        if action == "select" and context:
            self._folder_menu_action_pending = False
            parent, path = context
            if self.winfo_exists() and parent == self._current_path and path in self._entries:
                self._enter_key(path)
            return
        super()._run_folder_menu_action(action, context)
