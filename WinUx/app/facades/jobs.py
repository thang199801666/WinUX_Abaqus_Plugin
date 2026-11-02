"""Job polling, scheduling, plotting and submission facade methods."""
from __future__ import annotations



def _record_user_activity(controller):
    method = getattr(controller, "user_activity", None)
    if callable(method):
        return method()
    from ..controller import WinUXController
    return WinUXController.user_activity(controller)


class JobsFacadeMixin:
    @staticmethod
    def _job_poll_signature(jobs):
        from ...controllers.jobs.polling import JobPollingController
        return JobPollingController.signature(jobs)
    @staticmethod
    def _configure_job_poll_policy(policy, settings):
        from ...controllers.jobs.polling import JobPollingController
        return JobPollingController.configure_policy(policy, settings)
    def _start_job_polling(self):
        return self._job_polling_controller().start()
    def _stop_job_polling(self):
        return self._job_polling_controller().stop()
    def _schedule_loop(self):
        return self._schedule_execution_controller().loop()
    def _execute_scheduled_run(self, task):
        return self._schedule_execution_controller().execute_run(task)
    def _execute_scheduled_delete(self, task):
        return self._schedule_execution_controller().execute_delete(task)
    def _schedule_status_message(self, message):
        return self._schedule_execution_controller().status_message(message)
    def _apply_job_update(self, cancel, jobs):
        return self._job_polling_controller().apply_update(cancel, jobs)
    def _reconcile_job_deletions(self, jobs):
        return self._schedule_execution_controller().reconcile_deletions(jobs)
    def _selected_job_values(self):
        return self.view.selected_job_values()
    def _job_actions_controller(self):
        component = getattr(self, "_job_actions", None)
        if component is None:
            from ...controllers.jobs.actions import JobActionsController
            component = JobActionsController(self)
            self._job_actions = component
        return component
    def _continue_job_command(self, action, values):
        return self._job_actions_controller()._continue_job_command(action, values)
    def _job_modal_command(self, action, values):
        return self._job_actions_controller()._job_modal_command(action, values)
    def _job_plot_controller(self):
        component = getattr(self, "_job_plots", None)
        if component is None:
            from ...controllers.jobs.plot import JobPlotController
            component = JobPlotController(self)
            self._job_plots = component
        return component
    def _job_plot_selection_changed(self, job_id, items):
        return self._job_plot_controller().selection_changed(job_id, items)
    def _job_plot_closed(self, job_id):
        return self._job_plot_controller().closed(job_id)
    def _stop_all_job_plots(self):
        job_plots = getattr(self, "_job_plots", None)
        if job_plots is not None:
            return job_plots.stop_all()
        return None
    def _apply_job_plot_payload(self, job_id, payload):
        return self._job_plot_controller().apply_payload(job_id, payload)
    def _job_plot_selection_snapshot(self, job_id):
        return self._job_plot_controller().selection_snapshot(job_id)
    @staticmethod
    def _odb_adaptive_settings():
        from ...controllers.jobs.plot import JobPlotController
        return JobPlotController.adaptive_settings()
    def _odb_discovery_delay(self, policy, started_at, settings):
        return self._job_plot_controller().discovery_delay(policy, started_at, settings)
    def _remember_odb_appearance_wait(self, seconds, settings):
        return self._job_plot_controller().remember_appearance_wait(seconds, settings)
    def _job_plot_watch_loop(self, job_id, job_name, cancel):
        return self._job_plot_controller().watch_loop(job_id, job_name, cancel)
    def _open_job_plots(self, values):
        return self._job_plot_controller().open(values)
    def _job_odb_failed(self, title, message):
        return self._job_plot_controller().odb_failed(title, message)
    def _job_odb_resolved(self, action, job_id, job_name, path):
        return self._job_plot_controller().odb_resolved(action, job_id, job_name, path)
    def _job_odb_command(self, action, values):
        return self._job_plot_controller().odb_command(action, values)
    def job_command(self, action):
        return self._job_actions_controller().job_command(action)
    def user_activity(self, *_args):
        """Wake remote pollers when WinUx becomes interactive again."""
        policy = getattr(self, "_inactivity_policy", None)
        if policy is None:
            return False
        previous = policy.note_activity()
        if previous == policy.ACTIVE:
            return False
        # Resume should feel immediate: collapse scheduler backoff and interrupt
        # the current wait.  The normal query-token budget still prevents an
        # input storm from generating a qstat storm.
        force_fast = getattr(self, "_job_poll_force_fast", None)
        wakeup = getattr(self, "_job_poll_wakeup", None)
        if force_fast is not None:
            force_fast.set()
        if wakeup is not None:
            wakeup.set()
        return True
    def _refresh_jobs_now(self):
        _record_user_activity(self)
        return self._job_polling_controller().refresh_now()
    def _schedule_job_deletion(self, job_id, job_name, settings):
        return self._schedule_execution_controller().schedule_deletion(
            job_id, job_name, settings)
    def _finish_job_deletion(self, task):
        return self._schedule_execution_controller().finish_deletion(task)
    def _pending_job_deletions(self):
        return self._schedule_execution_controller().pending_deletions()
    def job_schedules(self, *, blocking=True):
        return self._schedule_execution_controller().rows(blocking=blocking)
    def _record_schedule_status(self, task, kind, status):
        return self._schedule_execution_controller().record_status(
            task, kind, status)
    @staticmethod
    def _remaining_time(target, now):
        from ...services.presentation import remaining_time
        return remaining_time(target, now)
    def _schedule_manifest_controller(self):
        component = getattr(self, "_schedule_manifest", None)
        if component is None:
            from ...controllers.jobs.manifest import ScheduleManifestController
            component = ScheduleManifestController(self)
            self._schedule_manifest = component
        return component
    def _schedule_manifest_entry(self, task, kind):
        return self._schedule_manifest_controller().manifest_entry(task, kind)
    def _persist_schedule_recovery_queue(self):
        return self._schedule_manifest_controller().persist_recovery_queue()
    def _flush_schedule_manifest_async(self):
        return self._schedule_manifest_controller().flush_async()
    def _save_shared_schedule(self, task, kind):
        return self._schedule_manifest_controller().save(task, kind)
    def _remove_shared_schedule(self, schedule_id):
        return self._schedule_manifest_controller().remove(schedule_id)
    def _restore_shared_schedules(self):
        return self._schedule_manifest_controller().restore()
    def _install_shared_schedules(self, entries):
        return self._schedule_execution_controller().install_shared(entries)
    def job_schedule_command(self, action, kind, key):
        _record_user_activity(self)
        return self._schedule_execution_controller().command(action, kind, key)
    def _refresh_schedule_dialog(self):
        return self._schedule_execution_controller().refresh_dialog()
    def _cancel_job_schedule(self, kind, key):
        return self._schedule_execution_controller().cancel(kind, key)
    def _apply_job_schedule_edit(
            self, kind, key, original_task, is_after, value):
        return self._schedule_execution_controller().apply_edit(
            kind, key, original_task, is_after, value)
    def _job_submission_controller(self):
        component = getattr(self, "_job_submission", None)
        if component is None:
            from ...controllers.jobs.submission import JobSubmissionController
            component = JobSubmissionController(self)
            self._job_submission = component
        return component
    def run_job(self, panel):
        return self._job_submission_controller().run_job(panel)
    def _compute_job_cores(self, dialog, paths):
        return self._job_submission_controller()._compute_job_cores(dialog, paths)
    def _submit_jobs(self, dialog, jobs):
        return self._job_submission_controller()._submit_jobs(dialog, jobs)
