from __future__ import annotations

from copy import deepcopy
from ..inp_preferences import INPPreferences
from ..inp_reader import INPReader
from ..runtime.operation_context import OperationContext


class JobSubmissionController:
    def __init__(self, app):
        self.app = app

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    def run_job(self, panel):
        if not self.app._ensure_server_online():
            return
        paths = [path for path in panel.selected_transfer_paths()
                 if path.suffix.casefold() == ".inp"]
        if not paths:
            self.view.show_error("Run Job", "Select one or more Abaqus .inp files.")
            return
        self.view.show_job_manager(
            paths, self.app._submit_jobs, self.app._compute_job_cores)

    def _compute_job_cores(self, dialog, paths):
        paths = list(paths)
        context = OperationContext(self.app, remote=True)

        def worker():
            try:
                context.check()
                settings = INPPreferences().load()
                suggestions = {}
                for path in paths:
                    context.check()
                    if not dialog.winfo_exists():
                        return
                    content = self.server.read_text(path)
                    suggestions[path] = INPReader(
                        content, settings).suggested_cores()
            except Exception as exc:
                context.post(
                    0, dialog.core_suggestions_failed, str(exc))
                return
            context.post(
                0, dialog.core_suggestions_ready, suggestions, settings)

        handle = self.app._submit_background("compute-job-cores", worker,
            key=("compute-job-cores", id(dialog), tuple(map(str, paths)), context.connection), coalesce=True)
        context.report_rejection(handle, dialog.core_suggestions_failed)

    def _submit_jobs(self, dialog, jobs):
        jobs = deepcopy(list(jobs))
        context = OperationContext(self.app, remote=True)

        def worker():
            failed = 0
            for job in jobs:
                if not context.current():
                    return
                job = dict(job)
                path = job["path"]
                run_at = job.pop("_run_at", None)
                schedule_mode = job.pop("_schedule_mode", "Run At")
                if self.app._schedule_execution_controller().schedule_run(
                        path, job, run_at, schedule_mode, dialog):
                    continue
                context.post(0, dialog.submission_started, path)
                try:
                    result = self.server.submit_abaqus_job(**job)
                except Exception as exc:
                    failed += 1
                    context.post(
                        0, dialog.submission_job_failed, path, str(exc))
                else:
                    context.post(
                        0, dialog.submission_job_complete, path, result)
            context.post(0, dialog.submission_finished, len(jobs), failed)
            # Ask qstat immediately after all submit commands have returned.
            # The Job Manager closes only from the resulting Job Viewer update.
            context.post(0, self.app._refresh_jobs_now)

        handle = self.app._submit_background("submit-jobs", worker)
        if getattr(handle, "state", None) == "rejected":
            for job in jobs:
                context.post(0, dialog.submission_job_failed, job["path"], "Background queue is full; try again")
            context.post(0, dialog.submission_finished, len(jobs), len(jobs))

