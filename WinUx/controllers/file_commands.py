"""File command dispatch, deletion and inline rename coordination."""
from ..runtime.operation_context import OperationContext
from ..runtime.rename_result import RenameResult


class FileCommandController:
    def __init__(self, app):
        self.app = app

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    @property
    def model(self):
        return self.app.model

    def command(self, panel, action, selected_paths=None):
        context = OperationContext(self.app, remote=panel.panel_id == "server")
        if not context.current():
            return
        # Context-menu commands pass a frozen selection because opening the menu
        # moves focus away from the ListView. Keyboard/toolbar commands omit it
        # and use the current live selection instead.
        if selected_paths is not None:
            paths = list(selected_paths)
        else:
            # Delete applies to every selected real item, but never to the
            # synthetic parent-directory row (".."). This also makes Ctrl+A
            # safe at roots.
            paths = (panel.selected_transfer_paths() if action == "delete"
                     else panel.selected_paths())
        try:
            # WinSCP-style keyboard operations. These route through the same
            # controller paths as context-menu actions, so transfer conflict,
            # rename and refresh behaviour stay identical.
            if action == "transfer_selected":
                if paths:
                    self.app.transfer_selected(panel, paths)
                return
            if action == "edit":
                if not paths:
                    return
                if panel.panel_id == "server":
                    row = panel.row_for_path(paths[0])
                    item = panel.item_for_row(row)
                    if item is not None and not item.is_dir:
                        self.app.edit_server_file(panel, [paths[0]])
                    elif item is not None and item.is_dir:
                        self.app.open_path(panel, paths[0])
                else:
                    self.app.open_path(panel, paths[0])
                return
            if action == "parent":
                current = panel.current_path
                try:
                    parent = current.parent
                except AttributeError:
                    parent = None
                if parent is not None and parent != current:
                    self.app.open_path(panel, parent)
                return

            if panel.parent_selected() and action != "delete":
                if action == "open":
                    self.app.open_path(panel, panel.selected_parent_path())
                    return
                if action in ("copy", "cut", "rename"):
                    return

            # Explicit multi-file transfer commands use the frozen context-menu
            # selection. They share the same overwrite/conflict pipeline as
            # drag/drop, so one confirmation covers the whole selected batch.
            if action in ("upload_selected", "download_selected"):
                self.app.transfer_selected(panel, paths)
                return

            # Clipboard commands are shared by both panes. They publish/read
            # the Windows CF_HDROP formats in addition to WinUX's internal
            # local/server source metadata.
            if action in ("copy", "cut"):
                if paths:
                    self.app._publish_file_clipboard(
                        panel, list(paths), move=(action == "cut"))
                return
            if action == "paste":
                self.app._paste_file_clipboard(panel)
                return

            if panel.panel_id == "server":
                if action == "open" and paths:
                    row = panel.row_for_path(paths[0])
                    item = panel.item_for_row(row)
                    if item is not None and not item.is_dir:
                        self.app._open_remote_file(
                            panel, paths[0], int(item.size or 0))
                    else:
                        self.app.open_path(panel, paths[0])
                elif action == "refresh":
                    self.app.open_path(panel, panel.current_path, False)
                elif action == "rename" and len(paths) == 1:
                    path = paths[0]
                    row = panel.row_for_path(path)
                    if row is not None:
                        panel.begin_inline_rename(
                            row, lambda name: self._finish_inline_rename(
                                panel, path, name) if context.current() else False)
                elif action == "new_folder":
                    self._create_remote_item(panel, action)
                elif action == "new_file":
                    self._create_remote_item(panel, action)
                elif action == "delete" and paths:
                    delete_paths = list(paths)
                    self.view.confirm_action_async(
                        "Warning: Permanent Delete",
                        self._delete_warning_message(delete_paths, "server"),
                        lambda confirmed, selected=delete_paths, target=panel:
                            self._delete_server_items(target, selected)
                            if confirmed and context.current() else None,
                        primary_text="Delete",
                        secondary_text="Cancel",
                        intent="danger",
                    )
                return

            if action == "open" and paths:
                self.app.open_path(panel, paths[0])
            elif action == "rename" and len(paths) == 1:
                path = paths[0]
                row = panel.row_for_path(path)
                if row is not None:
                    panel.begin_inline_rename(
                        row, lambda name: self._finish_inline_rename(
                            panel, path, name))
            elif action == "new_folder":
                created = self.model.new_folder(panel.current_path)
                self._begin_created_rename(panel, created)
            elif action == "new_file":
                created = self.model.new_file(panel.current_path)
                self._begin_created_rename(panel, created)
            elif action == "delete" and paths:
                delete_paths = list(paths)
                self.view.confirm_action_async(
                    "Warning: Permanent Delete",
                    self._delete_warning_message(
                        delete_paths, "local computer"),
                    lambda confirmed, selected=delete_paths, target=panel:
                        self._delete_local_items(target, selected)
                        if confirmed and context.current() else None,
                    primary_text="Delete",
                    secondary_text="Cancel",
                    intent="danger",
                )
            elif action == "refresh":
                self.app.open_path(panel, panel.current_path, False)
        except (OSError, ValueError) as exc:
            self.view.show_error("WinUx", str(exc))


    @staticmethod
    def _delete_warning_message(paths, location):
        paths = list(paths or [])
        names = [getattr(path, "name", None) or str(path).rstrip("/\\").split("/")[-1].split("\\")[-1]
                 for path in paths]
        preview = names[:6]
        lines = [
            "You are about to permanently delete {} item(s) from {}.".format(
                len(paths), location),
            "",
        ]
        lines.extend("- {}".format(name) for name in preview)
        if len(names) > len(preview):
            lines.append("- ... and {} more".format(len(names) - len(preview)))
        lines.extend([
            "",
            "WARNING: This action cannot be undone.",
            "Select OK only when you are sure you want to continue.",
        ])
        return "\n".join(lines)

    def _create_remote_item(self, panel, action):
        context = OperationContext(self.app, remote=True)
        folder = panel.current_path
        panel.status.set("Creating server item...")
        def worker():
            try:
                context.check()
                create = self.server.new_folder if action == "new_folder" else self.server.new_file
                created = create(folder)
            except Exception as exc:
                context.post(0, self._create_remote_failed, panel, str(exc))
                return
            context.post(0, self._remote_item_created, panel, folder, created)
        handle = self.app._submit_background("server-create", worker)
        context.report_rejection(handle, self._create_remote_failed, panel)

    def _create_remote_failed(self, panel, error):
        panel.status.set("Server create failed")
        self.view.show_error("Create on server", error)

    def _remote_item_created(self, panel, folder, created):
        if panel.current_path == folder:
            self._begin_created_rename(panel, created)
        else:
            panel.status.set("Created {}".format(created))


    def _delete_local_items(self, panel, paths):
        try:
            self.model.delete(paths)
            panel.clear_selection()
            self.app._refresh_all()
        except (OSError, ValueError) as exc:
            self.view.show_error("Delete", str(exc))


    def _delete_server_items(self, panel, paths):
        """Delete remote files/directories without blocking the render thread."""
        selected = list(paths or [])
        if not selected:
            return
        context = OperationContext(self.app, remote=True)
        if not context.current():
            return
        panel.status.set("Deleting {} server item(s)...".format(len(selected)))

        def worker():
            try:
                context.check()
                deleted = self.server.delete(selected)
            except Exception as exc:
                context.post(
                    0, self._server_delete_failed, panel, str(exc))
                return
            context.post(
                0, self._server_delete_finished, panel, len(deleted))

        handle = self.app._submit_background("server-delete", worker)
        context.report_rejection(handle, self._delete_queue_rejected, panel)

    def _delete_queue_rejected(self, panel, error):
        panel.status.set("Server delete not started")
        self.view.show_error("Delete from server", error)


    def _server_delete_finished(self, panel, deleted_count):
        panel.clear_selection()
        self.app._refresh_all()
        panel.status.set("Deleted {} item(s)".format(int(deleted_count)))


    def _server_delete_failed(self, panel, error):
        # Refresh even after a partial recursive delete so the list never
        # displays remote entries that no longer exist.
        try:
            self.app._refresh_all()
        finally:
            panel.status.set("Server delete failed")
            self.view.show_error("Delete from server", str(error))


    def _finish_inline_rename(self, panel, path, new_name):
        context = OperationContext(self.app, remote=panel.panel_id == "server")
        if not context.current():
            return False
        if panel.panel_id == "server":
            return self._rename_remote(panel, path, new_name, context)
        try:
            renamed = self.model.rename(path, new_name)
        except (OSError, ValueError) as exc:
            dialog = self.view.show_error("Rename failed", str(exc))
            if dialog is not None:
                dialog.on_result = (
                    lambda _value: panel.refocus_inline_rename() if context.current() else None)
            return False
        context.post(
            0, self._complete_inline_rename, panel, renamed)
        return renamed

    def _rename_remote(self, panel, path, new_name, context):
        result = RenameResult()
        lifetime = OperationContext(self.app)
        folder = panel.current_path
        editor_callback = getattr(panel, "_rename_commit_callback", None)
        panel.status.set("Renaming server item...")
        def failed(error):
            result.complete(False)
            if context.current():
                panel.status.set("Server rename failed")
                dialog = self.view.show_error("Rename failed", error)
                if dialog is not None:
                    dialog.on_result = lambda value: panel.refocus_inline_rename() if (
                        context.current() and getattr(panel, "_rename_commit_callback", None) is editor_callback) else None
        def finished(renamed):
            same_editor = getattr(panel, "_rename_commit_callback", None) is editor_callback
            result.complete(context.current())
            if context.current():
                if panel.current_path == folder and same_editor:
                    self._complete_inline_rename(panel, renamed)
                else:
                    panel.status.set("Renamed {}".format(renamed))
        def worker():
            try:
                context.check()
                renamed = self.server.rename(path, new_name)
            except Exception as exc:
                lifetime.post(0, failed, str(exc))
                return
            lifetime.post(0, finished, renamed)
        handle = self.app._submit_background("server-rename", worker)
        lifetime.report_rejection(handle, failed)
        return result


    def _complete_inline_rename(self, panel, renamed):
        self.app._refresh_all()
        self.app._select_path(panel, renamed)


    def _begin_created_rename(self, panel, created):
        """Refresh, select a newly created item, and immediately edit its name."""
        self.app.open_path(panel, panel.current_path, False)
        row = panel.row_for_path(created)
        if row is not None:
            context = OperationContext(self.app, remote=panel.panel_id == "server")
            panel.select_row(row)
            panel.begin_inline_rename(
                row, lambda name: self._finish_inline_rename(
                    panel, created, name) if context.current() else False)

