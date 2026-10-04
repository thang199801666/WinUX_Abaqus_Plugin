"""Job menu actions and asynchronous confirmation lifecycle."""
from pathlib import Path
import threading

from ..abaqus_version_preferences import AbaqusVersionPreferences
from ..runtime.operation_context import OperationContext


class JobActionsController:
    def __init__(self, app):
        self.app = app

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    def _continue_job_command(self, action, values):
        """Continue a job command after an asynchronous modal closes."""
        if self.app._closing or not values:
            return
        job_id, name, owner = str(values[0]), str(values[1]), str(values[2])
        if owner.casefold() != self.server.username.casefold():
            return
        if action == "cancel":
            context = OperationContext(self.app, remote=True)
            def worker():
                try:
                    context.check()
                    self.server.cancel_job(job_id)
                    context.post(0, self.app._refresh_jobs_now)
                except Exception as exc:
                    context.post(0, self.view.show_error,
                                    "Cancel Job", str(exc))
            handle = self.app._submit_background("cancel-job", worker)
            context.report_rejection(handle, self.view.show_error, "Cancel Job")

    def _job_modal_command(self, action, values):
        """Open job modals only after the context popup has closed."""
        if self.app._closing or not values:
            return
        values = tuple(values)
        job_id, name, owner = str(values[0]), str(values[1]), str(values[2])
        if owner.casefold() != self.server.username.casefold():
            return
        context = OperationContext(self.app, remote=True)
        if action == "edit":
            def apply_edit(settings):
                if settings is None or not context.current():
                    return
                self.app._job_edit_settings[job_id] = settings
                self.app._schedule_job_deletion(job_id, name, settings)
            self.view.edit_job(values, self.app._job_edit_settings.get(job_id), apply_edit)
        elif action == "cancel":
            self.view.confirm_action_async(
                "Cancel Job",
                "Are you sure you want to cancel job {}?".format(job_id),
                lambda confirmed: self._continue_job_command(action, values)
                if confirmed and context.current() else None,
            )

    def job_command(self, action):
        if self.app._closing:
            return
        context = OperationContext(self.app, remote=True)
        # Context-menu callbacks run while Dear PyGui is closing the popup.
        # Opening a modal in that same callback can silently fail. Queue modal
        # actions so popup teardown completes first.
        if action in ("edit", "cancel"):
            values = self.app._selected_job_values()
            if not values:
                return
            context.post(0, self._job_modal_command, action, tuple(values))
            return
        if action == "refresh":
            self.app._refresh_jobs_now()
            return
        if action in ("job_check_odb", "job_extract_odb"):
            values = self.app._selected_job_values()
            if not values:
                return
            self.app._job_odb_command(action, tuple(values))
            return
        if action == "job_plots":
            values = self.app._selected_job_values()
            if not values:
                return
            job_id = str(values[0])
            # Plots is a checkable command: clicking an already checked row
            # hides/stops that plot; clicking an unchecked row opens it.
            if self.view.get_job_plots(job_id) is not None:
                context.post(0, self.view.close_job_plots, job_id)
            else:
                # Context-menu callbacks run while the popup is being
                # destroyed; defer creation until popup teardown completes.
                context.post(0, self.app._open_job_plots, tuple(values))
            return
        values = self.app._selected_job_values()
        if not values:
            return
        job_id, name, owner = str(values[0]), str(values[1]), str(values[2])
        if action in ("check", "edit", "cancel", "open_temp", "hot_download", "job_plots") and owner.casefold() != self.server.username.casefold():
            return
        hot_download_dialog = None
        hot_download_cancel = None
        local_folder = None
        # A progress window belongs to this operation even if its SSH session
        # changes. Allow its terminal notification while suppressing old data.
        completion = OperationContext(self.app)
        if action == "hot_download":
            local_folder = Path(self.view.left.current_path)
            hot_download_cancel = threading.Event()
            hot_download_dialog = self.view.show_transfer_progress(
                "Hot Download", hot_download_cancel)

            def hot_download_progress(file_name, current_done, current_total,
                                      overall_done, overall_total):
                if not context.current():
                    hot_download_cancel.set()
                context.post(
                    0, hot_download_dialog.update_progress, file_name,
                    current_done, current_total, overall_done, overall_total)

        def worker():
            try:
                context.check()
                if action == "check":
                    response = self.server.read_job_status(job_id, name)
                    context.post(0, self.view.show_message,
                                    "Job Status", response or "Job is available")
                elif action == "details":
                    response = self.server.job_details(job_id)
                    context.post(0, self.view.show_message,
                                    "Job Details", response or "No details returned")
                elif action == "cancel":
                    response = self.server.cancel_job(job_id)
                    if response:
                        context.post(0, self.view.show_message,
                                        "Cancel Job", response)
                    context.post(1000, self.app._refresh_jobs_now)
                elif action == "open_temp":
                    folder = self.server.find_job_temp_folder(job_id, name)
                    context.post(0, self.app.open_path, self.view.right, folder)
                elif action == "hot_download":
                    target = self.server.hot_download(
                        job_id, name, local_folder, cancel=hot_download_cancel,
                        progress=hot_download_progress,
                        abaqus_commands=AbaqusVersionPreferences().ordered_commands())
                    context.check()
                    completion.post(0, hot_download_dialog.complete)
                    context.post(0, self.app.open_path, self.view.left,
                                    local_folder, False)
                    context.post(0, self.app._select_path, self.view.left, target)
            except Exception as exc:
                if hot_download_dialog is not None:
                    if str(exc) == "Operation cancelled":
                        completion.post(0, hot_download_dialog.complete)
                    else:
                        completion.post(0, hot_download_dialog.fail, str(exc))
                else:
                    context.post(0, self.view.show_error,
                                    "Job command failed", str(exc))

        handle = self.app._submit_background("job-command", worker)
        if hot_download_dialog is not None:
            completion.report_rejection(handle, hot_download_dialog.fail)
        else:
            context.report_rejection(handle, self.view.show_error, "Job command failed")

