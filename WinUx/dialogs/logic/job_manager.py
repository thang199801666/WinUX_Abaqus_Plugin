"""UI-neutral behavior shared by Abaqus Job Manager front ends."""
from __future__ import annotations

from datetime import datetime, timedelta
import re

from ...job_manager_preferences import JobManagerPreferences


class JobManagerLogic:
    """Submission/scheduling behavior independent of Tk/DPG/floating UI."""

    SCHEDULE_OPTIONS = ("Now", "Run After", "Run At")
    RUN_AT_FORMAT = "%Y-%m-%d %H:%M:%S"

    @staticmethod
    def _input_file_sort_key(path):
        name = str(path.name)
        return tuple(
            int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", name)
        )

    @staticmethod
    def _parse_run_after(value):
        text = str(value or "").strip()
        parts = text.split(":")
        if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
            raise ValueError("Run After must use HH:MM:SS")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2]) if len(parts) == 3 else 0
        if minutes > 59 or seconds > 59:
            raise ValueError("Run After must use HH:MM:SS")
        if hours == 0 and minutes == 0 and seconds == 0:
            raise ValueError("Run After must be greater than 00:00:00")
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)

    @classmethod
    def _resolve_run_at_clock(cls, value, now=None, live=False):
        now = now or datetime.now()
        text = str(value or "").strip()

        if live:
            # Keep live scheduling safely in the future even on a second edge.
            return now + timedelta(seconds=1)

        try:
            target = datetime.strptime(text, cls.RUN_AT_FORMAT)
        except ValueError:
            raise ValueError("Run At must use YYYY-MM-DD HH:MM:SS")

        if target <= now:
            raise ValueError(
                "Run At must be later than current date/time ({})".format(
                    now.strftime(cls.RUN_AT_FORMAT)))
        return target

    def _request_core_estimates(self):
        if not self.winfo_exists():
            return
        self.compute_callback(self, self.paths)

    def _submit_from_native(self, jobs):
        if not self.winfo_exists() or not jobs:
            return
        first = jobs[0]
        JobManagerPreferences().save(
            first["version"], first["cpus"],
            first["precision"], first["overwrite"])
        self.run_callback(self, jobs)

    def core_suggestions_ready(self, suggestions, settings):
        if isinstance(settings, dict):
            formula = str(settings.get("formula", "legacy_tiers"))
            factor = int(settings.get("dof_per_core", 5000))
            label = "adaptive DOF/core" if formula == "adaptive" else "legacy tier"
            message = "Core estimates updated ({} formula, {:,} DOF/core).".format(
                label, factor)
        else:
            message = "Core estimates updated (factor {}).".format(settings)
        self.post("core_suggestions_ready", suggestions, message)

    def core_suggestions_failed(self, error):
        self.post("core_suggestions_failed", str(error))

    def submission_started(self, path):
        # Keep Run disabled for the entire active submission window.  The
        # form already disables it before dispatch; posting this state again
        # makes the worker/UI boundary authoritative as well and prevents a
        # delayed UI update from re-enabling Run while a submit is in flight.
        self.post("run_enabled", False)
        self.post("status", "Submitting {}...".format(path.name))

    def submission_job_complete(self, path, output):
        del output
        self._successful_job_names.add(str(path.stem).casefold())
        self.post("status", "Submitted {}".format(path.name))

    def submission_job_failed(self, path, error):
        self.post("status", "{} failed: {}".format(path.name, error))

    def submission_scheduled(self, path, run_at):
        self._successful_job_names.add(str(path.stem).casefold())
        self.post(
            "status",
            "{} scheduled for {}".format(
                path.name, run_at.strftime(self.RUN_AT_FORMAT)))

    def submission_finished(self, attempted, failed):
        if failed == 0:
            self._submission_finished = True
            self.post("status", "Waiting for submitted jobs in Job Viewer...")
        else:
            self.post(
                "status",
                "Finished: {} attempted, {} failed".format(attempted, failed))
            self.post("run_enabled", True)

    def job_view_updated(self, jobs):
        if (not self._submission_finished or self._close_requested
                or not self.winfo_exists()):
            return
        visible_names = {
            str(getattr(job, "name", "")).casefold() for job in jobs
        }
        if self._successful_job_names <= visible_names:
            self._close_requested = True
            self.view.after_render(self.destroy)
