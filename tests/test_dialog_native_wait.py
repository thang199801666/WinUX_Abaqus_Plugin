"""IPC waits must keep the UI thread responsive to synchronous Win32 sends."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


class NestedDialogInputTests(unittest.TestCase):
    def test_escape_does_not_close_digitizer_behind_native_selector(self):
        from DearUIQt.dialogs import base
        close_digitizer = Mock()
        backend = SimpleNamespace(does_item_exist=lambda tag: True,
                                  is_item_shown=lambda tag: True)
        with patch.object(base, "dpg", backend), \
                patch.object(base, "_ESCAPE_TARGETS", [(42, close_digitizer)]), \
                patch("DearUIQt.input_gate.native_modal_input_active", return_value=True):
            base._dispatch_escape()
        close_digitizer.assert_not_called()

    def test_escape_still_closes_selector_when_it_has_no_nested_modal(self):
        from DearUIQt.dialogs import base
        close_selector = Mock()
        backend = SimpleNamespace(does_item_exist=lambda tag: True,
                                  is_item_shown=lambda tag: True)
        with patch.object(base, "dpg", backend), \
                patch.object(base, "_ESCAPE_TARGETS", [(42, close_selector)]), \
                patch("DearUIQt.input_gate.native_modal_input_active", return_value=False):
            base._dispatch_escape()
        close_selector.assert_called_once_with()

    def test_child_runtime_drops_disabled_owner_callbacks_not_ipc_or_layout(self):
        runtime = object.__new__(FloatingDialogRuntime)
        callback = Mock()
        with patch("WinUx.ui.hosting.floating_runtime.dpg.get_callback_queue",
                   return_value=[(callback,)]), \
                patch("WinUx.ui.hosting.floating_runtime.native_background_input_blocked",
                      return_value=True), \
                patch("WinUx.ui.hosting.floating_runtime.release_pointer_input") as release:
            runtime._drain_form_callbacks()
        callback.assert_not_called()
        release.assert_called_once_with()

    def test_child_runtime_dispatches_again_after_nested_selector_releases_input(self):
        runtime = object.__new__(FloatingDialogRuntime)
        callback = Mock()
        with patch("WinUx.ui.hosting.floating_runtime.dpg.get_callback_queue",
                   return_value=[(callback,)]), \
                patch("WinUx.ui.hosting.floating_runtime.native_background_input_blocked",
                      return_value=False):
            runtime._drain_form_callbacks()
        callback.assert_called_once_with()

    def test_opening_selector_in_callback_drops_remaining_escape_from_same_batch(self):
        runtime = object.__new__(FloatingDialogRuntime)
        state = {"blocked": False}
        open_selector = Mock(side_effect=lambda: state.update(blocked=True))
        stale_escape = Mock()
        with patch("WinUx.ui.hosting.floating_runtime.dpg.get_callback_queue",
                   return_value=[(open_selector,), (stale_escape,)]), \
                patch("WinUx.ui.hosting.floating_runtime.native_background_input_blocked",
                      side_effect=lambda: state["blocked"]), \
                patch("WinUx.ui.hosting.floating_runtime.release_pointer_input"):
            runtime._drain_form_callbacks()
        open_selector.assert_called_once_with()
        stale_escape.assert_not_called()

    def test_native_modal_blocks_owner_from_request_not_only_after_prepared(self):
        from DearUIQt import input_gate
        from WinUx.ui.hosting.floating_dialog import FloatingDialogController
        base = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as folder:
            lease = SimpleNamespace(host=object(), from_prewarm=False, reused=False,
                                    lease="test", reusable=False, listener=None, token="test",
                                    process=Mock(), log_path=str(Path(folder) / "dialog.log"),
                                    close_channel=Mock(), retire=Mock())
            manager = SimpleNamespace(pool=Mock(), acquire=Mock(return_value=lease), refill=Mock())
            view = SimpleNamespace(after=Mock(), _find_main_viewport_hwnd=lambda: 0)
            with patch("WinUx.ui.hosting.floating_dialog.find_process_window", return_value=0), \
                    patch("WinUx.ui.hosting.floating_dialog.dialog_host_manager", return_value=manager), \
                    patch("WinUx.ui.hosting.floating_dialog._DIALOG_IPC_POOL.start"), \
                    patch.multiple(input_gate, _native_modal_tokens=set(),
                                   _native_modal_release_pending=False,
                                   _native_modal_release_guard_until_frame=-1):
                dialog = FloatingDialogController(view, "local_file", "Open File", modal=True)
                try:
                    self.assertFalse(dialog._native_prepared)
                    self.assertTrue(input_gate.native_modal_input_active())
                finally:
                    dialog.destroy()
                self.assertFalse(input_gate.native_modal_input_active())

    def test_windows_quit_cancels_startup_without_waiting_for_timeout(self):
        runtime = object.__new__(FloatingDialogRuntime)
        runtime.form = SimpleNamespace(winfo_exists=lambda: True, destroy=Mock())
        runtime._commit_requested = False
        runtime.reusable = True
        with patch("WinUx.ui.hosting.floating_runtime.pump_native_messages", return_value=False):
            self.assertFalse(runtime._wait_for_publish_commit())
        self.assertFalse(runtime.reusable)
        runtime.form.destroy.assert_called_once_with()

    def test_fresh_escape_is_not_lost_in_selector_mouse_release_guard(self):
        from DearUIQt.dialogs import base
        runtime = object.__new__(FloatingDialogRuntime)
        scheduled = []
        runtime.view = SimpleNamespace(after=lambda delay, callback: scheduled.append(callback))
        closed = Mock()
        with patch.object(base, "dpg", SimpleNamespace(does_item_exist=lambda tag: True,
                                                      is_item_shown=lambda tag: True)), \
                patch.object(base, "_ESCAPE_TARGETS", [(42, closed)]), \
                patch("WinUx.ui.hosting.floating_runtime.dpg.get_callback_queue",
                      return_value=[(base._dispatch_escape,)]), \
                patch("WinUx.ui.hosting.floating_runtime.native_background_input_blocked",
                      return_value=True), \
                patch("DearUIQt.input_gate.native_modal_input_active", return_value=False), \
                patch("WinUx.ui.hosting.floating_runtime.release_pointer_input"):
            runtime._drain_form_callbacks()
            for callback in scheduled:
                callback()
        closed.assert_called_once_with()


@unittest.skipUnless(os.name == "nt", "Requires Windows message queues")
class NativeHandshakeWaitTests(unittest.TestCase):
    def test_commit_wait_services_cross_thread_windows_message_before_ack(self):
        self._assert_wait_pumps()

    def test_escape_close_handoff_wait_services_cross_thread_windows_message(self):
        self._assert_wait_pumps(owner_handoff=True)

    def _assert_wait_pumps(self, *, owner_handoff=False):
        user32 = ctypes.windll.user32
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        hwnd = user32.CreateWindowExW(0, "STATIC", "Handshake pump regression", 0,
                                      0, 0, 100, 100, None, None, None, None)
        self.assertTrue(hwnd)
        runtime = object.__new__(FloatingDialogRuntime)
        runtime.incoming = queue.Queue()
        runtime.form = SimpleNamespace(winfo_exists=lambda: True)
        runtime.view = SimpleNamespace(drain=Mock())
        runtime.lease = "test-lease"
        runtime._commit_requested = False
        sent = threading.Event()
        success = []

        def send_then_ack():
            user32.SendMessageTimeoutW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
            user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
            result = ctypes.c_size_t()
            sent.set()
            # The IPC ACK depends on a native send finishing, just as enabling
            # an owner/activating an owned GLFW window can during publication.
            success.append(bool(user32.SendMessageTimeoutW(
                hwnd, 0, 0, 0, 0x0001 | 0x0002, 300, ctypes.byref(result))))
            if success[-1]:
                runtime.incoming.put({
                    "command": "owner_handoff_ready" if owner_handoff else "publish_commit",
                    "lease": runtime.lease})

        worker = threading.Thread(target=send_then_ack, daemon=True)
        try:
            worker.start()
            self.assertTrue(sent.wait(1))
            with patch("WinUx.ui.hosting.floating_runtime.PUBLISH_HANDSHAKE_TIMEOUT", .5):
                committed = (runtime._wait_for_owner_handoff(timeout=.5) if owner_handoff
                             else runtime._wait_for_publish_commit())
            worker.join(timeout=1)
            self.assertEqual(success, [True], "The UI wait blocked a synchronous Win32 send")
            self.assertTrue(committed, "The commit ACK could not reach the waiting UI")
        finally:
            worker.join(timeout=1)
            user32.DestroyWindow(hwnd)


if __name__ == "__main__":
    unittest.main()
