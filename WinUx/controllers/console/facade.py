"""SSH console callbacks exposed by the application controller."""
from __future__ import annotations

from ...diagnostics import log_event


def _record_user_activity(controller):
    method = getattr(controller, "user_activity", None)
    if callable(method):
        return method()
    # Preserve support for tests/integrations invoking facade methods as
    # unbound WinUXController methods on light-weight proxy objects.
    from ...app.controller import WinUXController
    return WinUXController.user_activity(controller)


class ConsoleFacadeMixin:
    def console_command(self, command):
        _record_user_activity(self)
        if str(command).strip() == "--help":
            from ...services.abaqus_console_help import ABAQUS_LINUX_HELP
            self.server.append_console_message(ABAQUS_LINUX_HELP, command="--help")
            return True
        if not self._ensure_server_online():
            return False
        try:
            self.server.send_shell_command(command)
            # Preserve a best-effort cwd specifically for asynchronous Tab
            # completion, then invalidate the stricter navigation cache so the
            # next Server Files navigation still re-synchronises the PTY.
            note_command = getattr(self.server, "note_shell_command", None)
            if callable(note_command):
                note_command(command)
            self.server.invalidate_shell_directory()
            # Console commands can submit/cancel jobs directly or through site
            # scripts. Recover polling now and keep checking while they run.
            from ..jobs.polling import JobPollingController
            if JobPollingController.console_may_change_jobs(command):
                self._refresh_jobs_now()
            return True
        except Exception as exc:
            self.view.show_error("Console", str(exc))
            return False

    def console_complete(self, draft, cursor, callback):
        """Resolve one SSH Console Tab completion without blocking the UI."""
        if not callable(callback):
            return False
        draft = str(draft or "")
        cursor = max(0, min(len(draft), int(cursor)))

        def worker():
            try:
                result = self.server.complete_shell_input(draft, cursor)
            except Exception as exc:
                log_event("SSH Console completion failed: {}".format(exc))
                result = {"start": cursor, "end": cursor, "candidates": []}
            if getattr(self, "_closing", False):
                return
            try:
                self.view.after(0, callback, result)
            except Exception:
                pass

        handle = self._submit_background(
            "ssh-console-complete", worker, key="ssh-console-complete",
            replace=True)
        if handle.state == "rejected":
            try:
                self.view.after(0, callback, {
                    "start": cursor, "end": cursor, "candidates": []})
            except Exception:
                pass
            return False
        return True

    def console_completion_list(self, draft, candidates, columns=80):
        """Display an ambiguous completion list without sending it to SSH."""
        if not self.server.connected:
            return False
        try:
            return bool(self.server.append_shell_completion_listing(
                draft, candidates, columns=columns))
        except Exception as exc:
            log_event("SSH Console completion list failed: {}".format(exc))
            return False

    def console_input(self, data):
        """Forward exact terminal input to the live SSH PTY for TUI programs."""
        _record_user_activity(self)
        if not self.server.connected:
            return False
        try:
            return bool(self.server.send_shell_input(data))
        except Exception as exc:
            self.view.show_error("Console", str(exc))
            return False

    def console_resize(self, columns, rows):
        if not self.server.connected:
            return False
        try:
            return bool(self.server.resize_shell_pty(columns, rows))
        except Exception:
            return False

    def console_refresh(self):
        """Confirm and restart the interactive shell off the GUI thread."""
        _record_user_activity(self)
        if self._closing or getattr(self, '_console_refresh_active', False):
            return False
        if not self._ensure_server_online():
            return False
        self._console_refresh_active = True
        generation = self._connection_generation
        client = self.server.client
        folder = self._server_current_path

        def finished(error=None):
            self._console_refresh_active = False
            if error and not self._closing:
                self.view.show_error('Refresh SSH Console', str(error))

        def confirmed(accepted):
            if not accepted or self._closing:
                finished()
                return
            def worker():
                error = None
                try:
                    if self._closing or generation != self._connection_generation:
                        return
                    self.server.refresh_shell(folder, expected_client=client)
                except Exception as exc:
                    error = str(exc)
                finally:
                    self.view.after(0, finished, error)

            try:
                handle = self._submit_background(
                    'ssh-console-refresh', worker, key='ssh-console-refresh', coalesce=True)
            except Exception as exc:
                finished(str(exc))
                return
            if getattr(handle, 'state', None) == 'rejected':
                finished('Background queue is busy. Please try again.')

        try:
            self.view.confirm_action_async(
                'Refresh SSH Console',
                'Clear the console and restart its interactive shell?\n\n'
                'Programs running in this terminal and unsaved input may be lost. '
                'The SSH connection and file transfers will remain open.', confirmed)
        except Exception as exc:
            finished(str(exc))
            return False
        return True

    def console_interrupt(self):
        _record_user_activity(self)
        if not self.server.connected:
            return False
        try:
            self.server.interrupt_shell()
            self._refresh_jobs_now()
            return True
        except Exception as exc:
            self.view.show_error("Console", str(exc))
            return False
