"""WinUXView dialog facade and serialized modal ownership behavior.

Dialog constructor resolution stays compatible with monkey-patches applied to
``WinUx.view`` / ``WinUx.ui.main_window`` by integrations and tests.
"""
from __future__ import annotations

from collections import deque
import sys

from ....diagnostics import log_exception


def _main_window_module():
    return sys.modules.get("WinUx.ui.main_window") or sys.modules.get("WinUx.view")


def _resolve_dialog_type(name):
    module = _main_window_module()
    resolver = getattr(module, "_dialog_type", None) if module is not None else None
    if resolver is None:
        from ....ui.main_window import _dialog_type as resolver
    return resolver(name)


def _inprocess_dialogs_enabled():
    module = _main_window_module()
    resolver = getattr(module, "_use_inprocess_dialogs", None) if module is not None else None
    if resolver is None:
        from ....ui.main_window import _use_inprocess_dialogs as resolver
    return bool(resolver())


class DialogFacadeMixin:
    def show_login(self):
        dialog = getattr(self, "login_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return dialog

        # A dropped SSH connection can leave the server-path chooser visible.
        # Do not stack another native modal on top of it: Dear PyGui's modal
        # stack is not reliable while the older dialog is being removed.
        server_path_dialog = getattr(self, "server_path_dialog", None)
        if (server_path_dialog is not None and
                server_path_dialog.winfo_exists()):
            server_path_dialog.destroy()
            return self.after_render(self.show_login)

        # Capture before cold imports/form construction. A concurrently warming
        # native host can change foreground even while this GUI callback is
        # still importing the first Login form.
        from DearUIQt.backends.native_windows import NativeWindowBackend
        opening = NativeWindowBackend(self._gui_runtime.backend).beginOwnerOpen(
            self.primary_window_tag, owner_hwnd=self._find_main_viewport_hwnd())
        self.login_dialog = _resolve_dialog_type("LoginDialog")(
            self,
            self.callbacks["login"],
        )
        # Start the native show transaction inside the button's UI turn, while
        # its main HWND still owns foreground, not in a later startup timer.
        self.login_dialog.lift()
        if opening is not None:
            self.login_dialog._native_owner_open_lease = opening
        return self.login_dialog

    def show_transfer_progress(self, operation, cancel_event, items=None):
        center = self._get_transfer_center()
        return center.add_task(operation, cancel_event, items=items)

    def _get_transfer_center(self):
        center = getattr(self, "transfer_center_dialog", None)
        if center is None or not center.winfo_exists():
            center = _resolve_dialog_type("TransferCenterDialog")(self)
            self.transfer_center_dialog = center
        return center

    def _prewarm_transfer_center(self):
        """Prepare Transfer Center during an idle turn without process startup.

        The normal path builds one retained in-process Qt-style tool and hides
        it. Legacy process-host mode keeps its historical bounded prewarm pool.
        """
        if not self.winfo_exists() or getattr(self, "_floating_focus_suppressed", False):
            return
        if _inprocess_dialogs_enabled():
            center = getattr(self, 'transfer_center_dialog', None)
            if center is not None and center.winfo_exists():
                return
            # Do not construct a widget tree in the middle of a live pointer
            # gesture. The first real transfer creates the retained shell;
            # subsequent transfers reuse it without taxing idle memory.
            if any(getattr(panel.listview, '_item_drag_active', False)
                   for panel in self.panels):
                return
            # Build the retained widget tree during an idle UI turn. This pays
            # no process/IPC cost and makes the first explicit show a constant-
            # time visibility/activation transaction.
            self._get_transfer_center().hide()
            return
        try:
            from ...hosting.host import dialog_host_manager
            dialog_host_manager(self).refill()
        except Exception:
            # Idle preparation is optional and must never affect the main HWND.
            log_exception("Could not refill the floating dialog host pool", sys.exc_info())

    def _prewarm_inprocess_dialog_imports(self, index=0):
        """Incrementally resolve normal dialog classes during GUI idle time.

        This is intentionally import-only: retained heavy tools decide their own
        preconstruction policy, while transient dialogs still allocate widgets
        only when requested. No worker, subprocess or secondary event loop is
        created.
        """
        if not self.winfo_exists() or not _inprocess_dialogs_enabled():
            return False
        names = (
            # Resolving one transient class imports the shared transient module
            # and therefore warms Login/Job/Edit/file selectors/ODB/progress.
            "BlockingDialog",
            "SettingsDialog",
            "JobScheduleDialog",
            "BookmarksDialog",
            "SiteManagerDialog",
            "SyncPreviewDialog",
            "DiagnosticsDialog",
            "TransferCenterDialog",
        )
        index = max(0, int(index or 0))
        if index >= len(names):
            return True
        try:
            _resolve_dialog_type(names[index])
        except Exception:
            # Warmup is speculative; the normal click path remains authoritative.
            log_exception(
                "Could not warm in-process dialog {}".format(names[index]),
                sys.exc_info(), fatal=False)
        if index + 1 < len(names) and self.winfo_exists():
            self.after(24, self._prewarm_inprocess_dialog_imports, index + 1)
        return True

    def _prewarm_retained_dialog_shells(self, index=0):
        """Build common argument-free retained shells during idle turns.

        The shell remains hidden and shares QApplication's one GUI event loop.
        Settings page I/O keeps using its existing QThreadPool bridge, while no
        native dialog process or secondary renderer is created.
        """
        if not self.winfo_exists() or not _inprocess_dialogs_enabled():
            return False
        specs = (
            ("settings_dialog", "SettingsDialog"),
            ("diagnostics_dialog", "DiagnosticsDialog"),
        )
        index = max(0, int(index or 0))
        if index >= len(specs):
            return True
        attribute, class_name = specs[index]
        current = getattr(self, attribute, None)
        if current is None or not current.winfo_exists():
            try:
                current = _resolve_dialog_type(class_name)(self)
                setattr(self, attribute, current)
                current.hide()
            except Exception:
                # Keep idle warmup optional; the normal menu path can retry.
                setattr(self, attribute, None)
                log_exception(
                    "Could not prewarm retained {}".format(class_name),
                    sys.exc_info(), fatal=False)
        if index + 1 < len(specs) and self.winfo_exists():
            self.after(80, self._prewarm_retained_dialog_shells, index + 1)
        return True

    def show_transfer_center(self):
        center = self._get_transfer_center()
        center.show()
        return center

    def show_job_manager(self, paths, run_callback, compute_callback):
        self.job_manager_dialog = _resolve_dialog_type("JobManagerDialog")(
            self, paths, run_callback, compute_callback)
        return self.job_manager_dialog

    def show_server_notepad(self, path, on_load, on_save, on_reload):
        current = getattr(self, "server_notepad_dialog", None)
        if current is not None and current.winfo_exists():
            # One standalone editor window owns a Notepad++-style tab session.
            # If IPC has gone stale, do not keep returning a facade that can no
            # longer show a window; tear it down and launch a clean child.
            if current.queue_open(path):
                current.lift()
                return current
            try:
                current.destroy(wait=False)
            except Exception:
                pass
        self.server_notepad_dialog = _resolve_dialog_type("ServerNotepadDialog")(
            self, path, on_load=on_load, on_save=on_save, on_reload=on_reload)
        return self.server_notepad_dialog

    def show_odb_check(self, result):
        current = getattr(self, "odb_check_dialog", None)
        if current is not None and current.winfo_exists():
            current.destroy()
        self.odb_check_dialog = _resolve_dialog_type("ODBCheckDialog")(self, result)
        return self.odb_check_dialog

    def show_odb_extract(self, catalog, on_result):
        current = getattr(self, "odb_extract_dialog", None)
        if current is not None and current.winfo_exists():
            current.destroy()
        self.odb_extract_dialog = _resolve_dialog_type("ODBExtractDialog")(
            self, catalog, on_result)
        return self.odb_extract_dialog

    def show_odb_xy_results(self, result):
        current = getattr(self, "odb_xy_result_dialog", None)
        if current is not None and current.winfo_exists():
            current.destroy()
        self.odb_xy_result_dialog = _resolve_dialog_type("ODBXYResultDialog")(self, result)
        return self.odb_xy_result_dialog

    def _blocking_modal(
            self, title, message, kind="message", initial="",
            primary_text=None, secondary_text=None, intent="info"):
        return _resolve_dialog_type("BlockingDialog")(
            self, title, message, kind, initial,
            primary_text=primary_text,
            secondary_text=secondary_text,
            intent=intent,
        ).wait()

    def confirm_overwrite(self, message):
        return bool(self._blocking_modal(
            "Overwrite?", message, "confirm",
            primary_text="Replace", secondary_text="Cancel",
            intent="warning"))

    def confirm_action(
            self, title, message, primary_text=None,
            secondary_text="Cancel", intent="question"):
        return bool(self._blocking_modal(
            title, message, "confirm",
            primary_text=primary_text,
            secondary_text=secondary_text,
            intent=intent))

    def confirm_action_async(
            self, title, message, callback, primary_text=None,
            secondary_text="Cancel", intent="question", parent=None):
        """Show one asynchronous confirmation dialog on the UI queue."""
        title_key = str(title or "").casefold()
        if primary_text is None:
            if "overwrite" in title_key or "replace" in title_key:
                primary_text = "Replace"
                if intent == "question":
                    intent = "warning"
            elif "delete" in title_key:
                primary_text = "Delete"
                intent = "danger"
            elif "close" in title_key or "exit" in title_key:
                primary_text = "Exit"
            else:
                primary_text = "OK"
        requests = getattr(self, "_async_confirm_requests", None)
        if requests is None:
            requests = self._async_confirm_requests = deque()
        request = (
            title, message, callback, primary_text, secondary_text, intent,
            None, False)
        if parent is not None:
            # Slots 8/9 are reserved for transfer-conflict payload/callback.
            request += (None, None, parent)
        requests.append(request)
        return self._drain_async_confirm_requests()

    def confirm_action_checkbox_async(
            self, title, message, callback, *, checkbox_text, checkbox_checked=True,
            primary_text=None, secondary_text="Cancel", intent="question"):
        """Confirm an action and return the state of one inline checkbox."""
        title_key = str(title or "").casefold()
        if primary_text is None:
            primary_text = "Upgrade" if "upgrade" in title_key else "OK"
        requests = getattr(self, "_async_confirm_requests", None)
        if requests is None:
            requests = self._async_confirm_requests = deque()

        def decoded(value):
            if isinstance(value, dict):
                accepted = bool(value.get("accepted"))
                checked = bool(value.get("checked", checkbox_checked))
            else:
                accepted = bool(value)
                checked = bool(checkbox_checked)
            callback(accepted, checked)

        requests.append((
            title, message, decoded, primary_text, secondary_text, intent,
            str(checkbox_text or ""), bool(checkbox_checked)))
        return self._drain_async_confirm_requests()

    def _drain_async_confirm_requests(self):
        """Serialize confirmations without dropping another action's callback."""
        if getattr(self, "_async_confirm_active", None) is not None:
            current = getattr(self, "_async_confirm_dialog", None)
            if current is not None and current.winfo_exists():
                current.lift()
            return None
        requests = getattr(self, "_async_confirm_requests", None)
        if not requests or not getattr(self, "_alive", True):
            return None
        request = requests.popleft()
        if len(request) >= 8:
            (title, message, callback, primary_text, secondary_text, intent,
             option_text, option_checked) = request[:8]
        else:
            title, message, callback, primary_text, secondary_text, intent = request
            option_text, option_checked = None, False
        parent = request[10] if len(request) > 10 else None
        if parent is not None and (
                not getattr(parent, "winfo_exists", lambda: True)()
                or not getattr(parent, "isVisible", lambda: True)()):
            # A queued tool confirmation must not appear over an unrelated
            # window after its launching tool has already gone away.
            self.after(0, callback, False)
            self.after_render(self._drain_async_confirm_requests)
            return None
        token = self._async_confirm_active = object()

        def completed(value):
            if self._async_confirm_active is not token:
                return
            self._async_confirm_active = None
            self._async_confirm_dialog = None
            try:
                callback(value)
            finally:
                # Native in-process HWND teardown is committed by rendering,
                # not after(0). Serialize the next request across that boundary.
                self.after_render(self._drain_async_confirm_requests)

        try:
            if len(request) > 8 and request[8] is not None:
                from ....dialogs.transfer.transfer_conflict_form import TransferConflictDialog
                dialog = TransferConflictDialog(self, request[8], completed,
                    on_review_contents=request[9] if len(request) > 9 else None)
            else:
                owner_options = {"parent": request[10]} if len(request) > 10 else {}
                dialog = _resolve_dialog_type("BlockingDialog")(
                    self, title, message, "confirm", on_result=completed,
                    primary_text=primary_text,
                    secondary_text=secondary_text,
                    intent=intent,
                    option_text=option_text,
                    option_checked=option_checked, **owner_options)
            self._async_confirm_dialog = dialog
            dialog.lift()
        except Exception:
            self._async_confirm_active = None
            self._async_confirm_dialog = None
            self.after(0, callback, False)
            self.after(0, self._drain_async_confirm_requests)
            raise
        return dialog

    def confirm_transfer_conflicts_async(self, review, callback, on_review_contents=None):
        """Use the ordinary serialized modal queue and native teardown boundary."""
        requests = getattr(self, '_async_confirm_requests', None)
        if requests is None:
            requests = self._async_confirm_requests = deque()
        def decoded(value):
            callback(value is not None and value is not False, value if value else False)
        requests.append(('Existing destination items', '', decoded, None, 'Cancel',
                         'warning', None, False, review, on_review_contents))
        return self._drain_async_confirm_requests()

    def _show_message_dialog(self, title, message, intent="info"):
        # Informational dialogs never need a nested render loop. Starting a
        # second render_dearpygui_frame() loop from a menu/context callback is
        # undefined in Dear PyGui and is the main source of whole-app flicker.
        dialog = _resolve_dialog_type("BlockingDialog")(
            self, title, message, "message",
            primary_text="OK", intent=intent)
        dialog.lift()
        return dialog

    def show_error(self, title, message):
        return self._show_message_dialog(title, message, intent="error")

    def show_message(self, title, message):
        return self._show_message_dialog(title, message, intent="info")

    def ask_text(self, title, prompt, initial=""):
        return self._blocking_modal(title, prompt, "input", initial)

    def ask_text_async(self, title, prompt, initial="", callback=None):
        """Show one input dialog without starting a nested render loop."""
        current = getattr(self, "_async_text_dialog", None)
        if current is not None and current.winfo_exists():
            current.lift()
            return current

        def completed(value):
            self._async_text_dialog = None
            if callable(callback):
                callback(value)

        dialog = _resolve_dialog_type("BlockingDialog")(
            self, title, prompt, "input", initial, on_result=completed)
        self._async_text_dialog = dialog
        dialog.lift()
        return dialog

    def show_local_folder_dialog(self, initial, on_selected):
        """Open the local-folder browser on the shared QApplication event loop."""
        dialog = getattr(self, "_local_folder_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return dialog

        def selected(path):
            current = getattr(self, "_local_folder_dialog", None)
            if current is dialog:
                self._local_folder_dialog = None
            if path and callable(on_selected):
                on_selected(path)

        dialog = _resolve_dialog_type("LocalFolderDialog")(self, initial, selected)
        self._local_folder_dialog = dialog
        return dialog

    def show_server_path(
            self, initial, suggestion_provider, on_selected, task_submitter=None):
        dialog = getattr(self, "server_path_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return dialog

        self.server_path_dialog = _resolve_dialog_type("ServerPathDialog")(
            self,
            initial,
            suggestion_provider,
            on_selected=on_selected,
            task_submitter=task_submitter,
        )
        return self.server_path_dialog

    def show_settings(self):
        dialog = getattr(self, "settings_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return dialog
        self.settings_dialog = _resolve_dialog_type("SettingsDialog")(self)
        self.settings_dialog.show()
        return self.settings_dialog

    def show_bookmarks(self, entries, on_open, on_remove, on_rename):
        dialog = getattr(self, "bookmarks_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(entries, on_open, on_remove, on_rename)
            dialog.lift()
            return dialog
        self.bookmarks_dialog = _resolve_dialog_type("BookmarksDialog")(
            self, entries, on_open, on_remove, on_rename)
        self.bookmarks_dialog.show()
        return self.bookmarks_dialog

    def show_site_manager(self, sites, on_save, on_delete, on_connect):
        dialog = getattr(self, "site_manager_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(sites, on_save=on_save, on_delete=on_delete, on_connect=on_connect)
            dialog.lift()
            return dialog
        self.site_manager_dialog = _resolve_dialog_type("SiteManagerDialog")(
            self, sites, on_save, on_delete, on_connect)
        self.site_manager_dialog.show()
        return self.site_manager_dialog

    def show_sync_preview(
            self, rows, local_path, server_path, on_refresh, on_transfer):
        dialog = getattr(self, "sync_preview_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh(rows, local_path, server_path, on_refresh, on_transfer)
            dialog.lift()
            return dialog
        self.sync_preview_dialog = _resolve_dialog_type("SyncPreviewDialog")(
            self, rows, local_path, server_path, on_refresh, on_transfer)
        self.sync_preview_dialog.show()
        return self.sync_preview_dialog

    def show_diagnostics(self):
        dialog = getattr(self, "diagnostics_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.refresh()
            dialog.lift()
            return dialog
        self.diagnostics_dialog = _resolve_dialog_type("DiagnosticsDialog")(self)
        self.diagnostics_dialog.show()
        return self.diagnostics_dialog

    def show_job_schedule(self):
        dialog = getattr(self, "job_schedule_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            # Hidden retained Job Schedule refreshes from showEvent().  Avoid a
            # second provider call on the same reopen transaction; an already
            # visible tool still refreshes explicitly when selected from View.
            was_visible = bool(getattr(dialog, "isVisible", lambda: True)())
            dialog.lift()
            if was_visible:
                dialog.refresh()
            return dialog
        self.job_schedule_dialog = _resolve_dialog_type("JobScheduleDialog")(
            self, self.callbacks["job_schedule"],
            self.callbacks["job_schedule_command"],
        )
        self.job_schedule_dialog.show()
        return self.job_schedule_dialog

    def edit_job(self, values, settings=None, callback=None):
        """Open and retain one non-blocking Edit Job dialog."""
        current = getattr(self, "edit_job_dialog", None)
        if current is not None and current.winfo_exists():
            current.lift()
            return current

        def completed(value):
            self.edit_job_dialog = None
            if callable(callback):
                callback(value)

        dialog = _resolve_dialog_type("JobEditDialog")(
            self, values, settings or {}, on_result=completed)
        self.edit_job_dialog = dialog
        dialog.lift()
        return dialog


__all__ = ["DialogFacadeMixin"]
