"""Explorer navigation, file commands, clipboard and server-editor facade methods."""
from __future__ import annotations

from pathlib import Path
import tempfile


class ExplorerFacadeMixin:
    def _navigation_controller(self):
        component = getattr(self, "_navigation", None)
        if component is None:
            from ...controllers.explorer.navigation import NavigationController
            component = NavigationController(self)
            self._navigation = component
        return component
    def _load_initial_local_async(self):
        return self._navigation_controller().load_initial()
    def _initial_local_loaded(self, path, items):
        return self._navigation_controller().initial_loaded(path, items)
    def _initial_local_failed(self, error):
        return self._navigation_controller().initial_failed(error)
    def _local_watch_controller(self):
        component = getattr(self, "_local_watch", None)
        if component is None:
            from ...controllers.explorer.local_watch import LocalWatchController
            component = LocalWatchController(self)
            self._local_watch = component
        return component
    @staticmethod
    def _same_local_path(first, second):
        from ...controllers.explorer.local_watch import LocalWatchController
        return LocalWatchController.same_path(first, second)
    def _watch_local_path(self, path):
        return self._local_watch_controller().watch(path)
    def _stop_local_watcher(self, wait=True):
        return self._local_watch_controller().stop(wait=wait)
    def _local_watcher_error(self, path, error):
        return self._local_watch_controller().report_error(path, error)
    def _local_directory_changed(self, path, generation):
        return self._local_watch_controller().changed(path, generation)
    def _local_listview_is_busy(self):
        return self._local_watch_controller().is_busy()
    def _begin_local_watch_refresh(self, path, generation):
        return self._local_watch_controller().begin_refresh(path, generation)
    def _complete_local_watch_refresh(self, path, generation, items, error):
        return self._local_watch_controller().complete_refresh(path, generation, items, error)
    def choose_path(self, panel):
        if panel.panel_id == "local":
            self.view.show_local_folder_dialog(
                initial=str(panel.current_path),
                on_selected=lambda selected: self.open_path(panel, selected),
            )
            return
        if not self._ensure_server_online():
            return
        self.view.show_server_path(
            initial=str(panel.current_path),
            suggestion_provider=self._suggest_server_paths,
            on_selected=lambda selected: self.open_path(panel, selected),
            task_submitter=self._submit_background,
        )
    def _suggest_server_paths(self, value):
        """Return remote folders whose names match the typed path fragment."""
        typed = str(value).strip().replace("\\", "/")
        if not typed:
            typed = str(self.server.home)
        elif not typed.startswith("/"):
            return self.server.search_directories(typed, limit=100)
        trailing_separator = typed.endswith("/")
        normalized = self.server.normalize(typed)
        if trailing_separator or str(normalized) == "/":
            parent, fragment = normalized, ""
        else:
            parent, fragment = normalized.parent, normalized.name.casefold()
        folders = []
        for item in self.server.list_directory(parent):
            if item.is_dir and fragment in item.name.casefold():
                folders.append(str(item.path))
        return folders[:100]
    def open_path(self, panel, value, record_history=True):
        return self._navigation_controller().open(panel, value, record_history)
    def _local_path_loaded(self, panel, path, items, record_history, generation):
        return self._navigation_controller().local_loaded(panel, path, items, record_history, generation)
    def _local_path_failed(self, panel, path, generation, error):
        return self._navigation_controller().local_failed(panel, path, generation, error)
    def _server_path_loaded(self, panel, path, items, record_history, generation):
        return self._navigation_controller().server_loaded(panel, path, items, record_history, generation)
    def _server_path_failed(self, panel, path, generation, error):
        return self._navigation_controller().server_failed(panel, path, generation, error)
    def navigate(self, panel, action):
        if action == "refresh":
            return self.open_path(panel, panel.current_path, False)
        if action == "parent":
            return self.open_path(panel, panel.current_path.parent)
        if action == "home":
            return self.open_path(panel, self.server.home if panel.panel_id == "server" else Path.home())
        step = -1 if action == "back" else 1
        target = panel.history_index + step
        if 0 <= target < len(panel.history):
            panel.history_index = target
            self.open_path(panel, panel.history[target], False)
    def _server_notepad_controller(self):
        component = getattr(self, "_server_notepad", None)
        if component is None:
            from ...controllers.server_notepad import ServerNotepadController
            component = ServerNotepadController(self)
            self._server_notepad = component
        return component
    def edit_server_file(self, panel, selected_paths=None):
        return self._server_notepad_controller().edit(panel, selected_paths)
    def _load_server_notepad(self, dialog, path):
        return self._server_notepad_controller().load(dialog, path)
    def _server_notepad_stream_finished(self, dialog, snapshot):
        return self._server_notepad_controller().stream_finished(dialog, snapshot)
    def _server_notepad_loaded(self, dialog, snapshot):
        return self._server_notepad_controller().loaded(dialog, snapshot)
    def _save_server_notepad(self, dialog, path, text, encoding, expected_signature, force):
        return self._server_notepad_controller().save(
            dialog, path, text, encoding, expected_signature, force)
    def _server_notepad_saved(self, dialog, snapshot):
        return self._server_notepad_controller().saved(dialog, snapshot)
    def _reload_server_notepad(self, dialog, path):
        return self._server_notepad_controller().reload(dialog, path)
    def double_click(self, panel, event):
        if isinstance(event, (int, str)):
            item = panel.item_for_row(event)
        elif hasattr(event, "path"):
            item = event
        else:
            item = None
        if item is None:
            return
        path = item.data.get("path") or item.path
        if panel.panel_id == "server" and not item.is_dir:
            # Server files use the WinUx internal editor on double-click.
            # Keep the explicit context-menu ``Open`` command available for
            # users who intentionally want the legacy download + OS-default
            # application behavior.  Passing the activated path explicitly
            # also avoids relying on whatever selection state remains after
            # the double-click gesture.
            self.edit_server_file(panel, [path])
            return
        self.open_path(panel, path)
    def _open_remote_file(self, panel, remote_path, size):
        if size > 10 * 1024 * 1024 and not self.view.confirm_action(
                "Large file",
                "File size larger than 10MB. Download and open this file?"):
            return
        panel.status.set("Downloading {}...".format(remote_path.name))

        def worker():
            try:
                temp_folder = Path(tempfile.mkdtemp(prefix="WinUX_"))
                self.server.download([remote_path], temp_folder)
                local_path = temp_folder / remote_path.name
            except Exception as exc:
                self.view.after(0, self.view.show_error,
                                "Open remote file failed", str(exc))
                return
            self.view.after(0, self._remote_file_downloaded,
                            panel, local_path)

        self._submit_transfer("open-remote-file", worker)
    def _remote_file_downloaded(self, panel, local_path):
        try:
            self._launch(local_path)
            panel.status.set("Opened {}".format(local_path.name))
        except OSError as exc:
            self.view.show_error("Open remote file failed", str(exc))
    def _file_clipboard_controller(self):
        component = getattr(self, "_file_clipboard", None)
        if component is None:
            from ...controllers.explorer.clipboard import FileClipboardController
            component = FileClipboardController(self)
            self._file_clipboard = component
        return component
    def _cleanup_old_clipboard_cache(self):
        return self._file_clipboard_controller().cleanup_cache()
    def _reset_internal_clipboard(self):
        return self._file_clipboard_controller().reset()
    def _begin_internal_clipboard(self, panel_id, paths, move):
        return self._file_clipboard_controller().begin(panel_id, paths, move)
    @staticmethod
    def _clipboard_item_names(paths):
        from ...controllers.explorer.clipboard import FileClipboardController
        return FileClipboardController.item_names(paths)
    def _publish_file_clipboard(self, panel, paths, move):
        return self._file_clipboard_controller().publish(panel, paths, move)
    def _prepare_server_file_clipboard(self, panel, remote_paths, move, generation, token):
        return self._file_clipboard_controller().prepare_server(panel, remote_paths, move, generation, token)
    def _server_clipboard_prepare_failed(self, panel, generation, stage_dir, dialog, error):
        return self._file_clipboard_controller().prepare_failed(panel, generation, stage_dir, dialog, error)
    def _server_clipboard_prepare_finished(self, panel, generation, token, start_sequence, remote_paths, staged_paths, move, stage_dir, dialog):
        return self._file_clipboard_controller().prepare_finished(panel, generation, token, start_sequence, remote_paths, staged_paths, move, stage_dir, dialog)
    def _monitor_server_cut_paste(self, remote_paths, staged_paths):
        return self._file_clipboard_controller().monitor_cut(remote_paths, staged_paths)
    def _server_cut_committed_to_explorer(self, count):
        return self._file_clipboard_controller().cut_committed(count)
    def _resolve_file_clipboard(self):
        return self._file_clipboard_controller().resolve()
    def _paste_file_clipboard(self, target_panel):
        return self._file_clipboard_controller().paste(target_panel)
    def _file_command_controller(self):
        component = getattr(self, "_file_commands", None)
        if component is None:
            from ...controllers.explorer.commands import FileCommandController
            component = FileCommandController(self)
            self._file_commands = component
        return component
    def command(self, panel, action, selected_paths=None):
        return self._file_command_controller().command(panel, action, selected_paths)
    @staticmethod
    def _delete_warning_message(paths, location):
        from ...controllers.explorer.commands import FileCommandController
        return FileCommandController._delete_warning_message(paths, location)
    def _delete_local_items(self, panel, paths):
        return self._file_command_controller()._delete_local_items(panel, paths)
    def _delete_server_items(self, panel, paths):
        return self._file_command_controller()._delete_server_items(panel, paths)
    def _server_delete_finished(self, panel, deleted_count):
        return self._file_command_controller()._server_delete_finished(panel, deleted_count)
    def _server_delete_failed(self, panel, error):
        return self._file_command_controller()._server_delete_failed(panel, error)
    def active_command(self, action):
        panel = next(
            (item for item in self.view.panels if item.is_focused),
            self.view.left,
        )
        self.command(panel, action)
    def _finish_inline_rename(self, panel, path, new_name):
        return self._file_command_controller()._finish_inline_rename(panel, path, new_name)
    def _complete_inline_rename(self, panel, renamed):
        return self._file_command_controller()._complete_inline_rename(panel, renamed)
    def _begin_created_rename(self, panel, created):
        return self._file_command_controller()._begin_created_rename(panel, created)
    def cancel(self):
        self.transfer_cancel.set()
        self._drag_target_panel = None
        self._drag_target_destination = None
        self._drag_target_point = None
        self._reset_internal_clipboard()
        self.view.clear_job_selection()
        for panel in self.view.panels:
            panel.clear_selection()
            panel.cancel_drag()
            panel.status.set("Operation cancelled" if panel.panel_id == "local" else
                             ("Connected to {}".format(self.server.host)
                              if self.server.connected else "SSH server disconnected"))
    def sort_changed(self, panel, column, descending):
        self.navigation_preferences.save_sort(
            panel.panel_id, column, descending)
    def _refresh_all(self):
        self.open_path(self.view.left, self.view.left.current_path, False)
        if self.server.connected:
            self.open_path(self.view.right, self.view.right.current_path, False)
    @staticmethod
    def _select_path(panel, path):
        panel.select_path(path)
    @staticmethod
    def _launch(path):
        from ...services.platform_integration import launch_path
        return launch_path(path)
