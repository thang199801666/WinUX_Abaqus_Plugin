"""Old visibility acknowledgements cannot override a newer show/hide intent."""
import json
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.ui.hosting.floating_dialog import FloatingDialogController
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


class VisibilityEventOrderTests(unittest.TestCase):
    def controller(self, visible=True):
        dialog = object.__new__(FloatingDialogController)
        dialog._closed = False
        dialog._visible = visible
        dialog._visibility_revision = 2
        dialog._confirm_visibility = Mock()
        return dialog

    def test_late_user_close_cannot_cancel_a_newer_reopen(self):
        dialog = self.controller()
        dialog._deliver_event({"event": "visibility", "visible": False,
                               "user_close": True, "visibility_revision": 1})
        self.assertTrue(dialog._visible)
        dialog._confirm_visibility.assert_not_called()

    def test_late_show_cannot_reacquire_input_after_a_newer_hide(self):
        dialog = self.controller(visible=False)
        dialog._deliver_event({"event": "visibility", "visible": True,
                               "visibility_revision": 1})
        dialog._confirm_visibility.assert_not_called()

    def test_current_user_close_still_hides(self):
        dialog = self.controller()
        dialog._deliver_event({"event": "visibility", "visible": False,
                               "user_close": True, "visibility_revision": 2})
        self.assertFalse(dialog._visible)
        dialog._confirm_visibility.assert_called_once_with(False, return_focus=False)

    def test_older_child_without_revision_remains_compatible(self):
        dialog = self.controller()
        dialog._deliver_event({"event": "visibility", "visible": False, "user_close": True})
        self.assertFalse(dialog._visible)
        dialog._confirm_visibility.assert_called_once()

    def test_stale_startup_visibility_still_marks_host_ready(self):
        dialog = self.controller()
        dialog._ready = False
        dialog._startup_generation = 0
        dialog._native_prepared = True
        dialog._refill_prewarm_pool = Mock()
        dialog._accept_native_hwnd = Mock()
        dialog._deliver_event({"event": "ready", "visible": False, "visibility_revision": 1})
        self.assertTrue(dialog._ready)
        self.assertTrue(dialog._visible)
        dialog._confirm_visibility.assert_not_called()

    def test_stale_prepared_event_still_completes_publish_handshake(self):
        dialog = self.controller(visible=False)
        dialog.modal = False
        dialog._accept_native_hwnd = Mock()
        dialog.post = Mock()
        dialog._deliver_event({"event": "prepared", "visibility_revision": 1})
        dialog.post.assert_called_once_with("publish")

    def test_stale_staged_event_still_completes_commit_handshake(self):
        dialog = self.controller(visible=False)
        dialog.modal = False
        dialog._accept_native_hwnd = Mock()
        dialog.post = Mock()
        dialog._deliver_event({"event": "staged", "visibility_revision": 1})
        dialog.post.assert_called_once_with("publish_commit")

    def test_visibility_commands_have_increasing_revisions_not_other_commands(self):
        dialog = self.controller()
        dialog._lease = "lease"
        dialog._outgoing = queue.Queue()
        for command in ("activate", "open_file_selector", "hide", "activate"):
            self.assertTrue(dialog.post(command))
        messages = [dialog._outgoing.get_nowait() for _ in range(4)]
        self.assertEqual([m.get("visibility_revision") for m in messages], [3, None, 4, 5])
        self.assertTrue(all(m["lease"] == "lease" for m in messages))


class RuntimeVisibilityOrderTests(unittest.TestCase):
    def runtime(self):
        runtime = object.__new__(FloatingDialogRuntime)
        runtime._emit_lock = threading.Lock()
        runtime.lease = "lease"
        runtime._visibility_revision = 2
        runtime.show, runtime.hide = Mock(), Mock()
        runtime.desired_visible = False
        return runtime

    def test_runtime_discards_old_visibility_commands(self):
        runtime = self.runtime()
        runtime._handle_command({"command": "activate", "lease": "lease", "visibility_revision": 1})
        runtime.show.assert_not_called()

    def test_current_command_updates_acknowledgement_revision(self):
        runtime = self.runtime()
        runtime._handle_command({"command": "activate", "lease": "lease", "visibility_revision": 3})
        self.assertEqual(runtime._visibility_revision, 3)
        runtime.show.assert_called_once_with()

    def test_preparing_visibility_commands_also_update_revision(self):
        runtime = self.runtime()
        runtime._handle_command({"command": "activate", "lease": "lease", "visibility_revision": 3},
                                preparing=True)
        self.assertTrue(runtime.desired_visible)
        self.assertEqual(runtime._visibility_revision, 3)
        runtime.show.assert_not_called()

    def test_other_lease_does_not_change_visibility_revision(self):
        runtime = self.runtime()
        runtime._handle_command({"command": "activate", "lease": "old", "visibility_revision": 50})
        self.assertEqual(runtime._visibility_revision, 2)
        runtime.show.assert_not_called()

    def test_visibility_and_startup_events_echo_revision(self):
        runtime = self.runtime()
        runtime.connection = SimpleNamespace(sendall=Mock())
        runtime.reusable = True
        for event in ("visibility", "prepared", "staged", "ready"):
            runtime.emit(event, visible=True)
            message = json.loads(runtime.connection.sendall.call_args.args[0])
            self.assertEqual(message["visibility_revision"], 2)
            self.assertEqual(message["lease"], "lease")


if __name__ == "__main__":
    unittest.main()
