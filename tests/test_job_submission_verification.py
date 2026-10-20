"""A qstat outage must not leave successful shell launches waiting forever."""
from pathlib import PurePosixPath
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.controllers.job_polling import JobPollingController
from WinUx.dialogs.logic.job_manager import JobManagerLogic


class Dialog(JobManagerLogic):
    def __init__(self):
        self._pending_queue_job_names = set()
        self._submission_finished = self._close_requested = False
        self.destroy = Mock()
        self.winfo_exists = Mock(return_value=True)
        self.post = Mock()
        self.view = SimpleNamespace(after=Mock(), after_render=Mock())


class SubmissionVerificationTests(unittest.TestCase):
    def waiting_dialog(self):
        dialog = Dialog()
        dialog.submission_job_complete(PurePosixPath("/work/model.inp"), "model (1234)")
        dialog.submission_finished(1, 0)
        return dialog

    def test_failed_qstat_is_not_reported_as_failed_submission_or_retried(self):
        dialog = self.waiting_dialog()
        dialog.job_view_failed("Connection refused\nqstat: cannot connect to server")
        message = dialog.post.call_args.args[1]
        self.assertIn("Sent", message)
        self.assertIn("PBS verification failed", message)
        self.assertIn("Connection refused", message)
        self.assertNotIn(unittest.mock.call("run_enabled", True), dialog.post.call_args_list)
        dialog.destroy.assert_not_called()

    def test_verification_wait_has_a_bounded_timeout(self):
        dialog = self.waiting_dialog()
        delay, callback, generation = dialog.view.after.call_args.args
        self.assertEqual(delay, 30000)
        callback(generation)
        self.assertIn("not confirmed", dialog.post.call_args.args[1])
        self.assertNotIn(unittest.mock.call("run_enabled", True), dialog.post.call_args_list)

    def test_polling_recovery_still_closes_manager_after_job_is_visible(self):
        dialog = self.waiting_dialog()
        dialog.job_view_failed("Connection refused")
        dialog.job_view_updated([SimpleNamespace(name="MODEL")])
        self.assertTrue(dialog._close_requested)
        dialog.view.after_render.assert_called_once_with(dialog.destroy)

    def test_error_during_submission_is_preserved_when_verification_starts(self):
        dialog = Dialog()
        dialog.job_view_failed("qstat unavailable")
        dialog.submission_job_complete(PurePosixPath("/work/model.inp"), "sent")
        dialog.submission_finished(1, 0)
        self.assertIn("qstat unavailable", dialog.post.call_args.args[1])

    def test_old_timeout_cannot_override_a_newer_batch(self):
        dialog = self.waiting_dialog()
        callback, generation = dialog.view.after.call_args.args[1:]
        dialog._queue_wait_generation += 1
        dialog.post.reset_mock()
        callback(generation)
        dialog.post.assert_not_called()

    def test_stale_connection_error_is_not_delivered_to_current_manager(self):
        current, old = threading.Event(), threading.Event()
        view = SimpleNamespace(winfo_exists=lambda: True, display_job_poll_error=Mock())
        controller = object.__new__(JobPollingController)
        controller.app = SimpleNamespace(_job_poll_cancel=current, _closing=False, view=view)
        controller.apply_error(old, "old connection failed")
        view.display_job_poll_error.assert_not_called()
        controller.apply_error(current, "Connection refused")
        view.display_job_poll_error.assert_called_once_with("Connection refused")


if __name__ == "__main__":
    unittest.main()
