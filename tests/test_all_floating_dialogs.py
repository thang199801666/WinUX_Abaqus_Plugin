"""Real HWND coverage for all public dialogs, plus transport/service contracts."""
from datetime import datetime
from pathlib import Path, PurePosixPath
import ctypes
from ctypes import wintypes
import heapq
import itertools
import os
import queue
import socket
import threading
import time
import unittest
from unittest.mock import patch

from WinUx import dialogs
from WinUx.dialogs.floating_dialog import FloatingDialogController, close_floating_dialogs
from WinUx.dialogs.floating_forms import FORM_KINDS
from WinUx.services.floating_protocol import encode_message, read_messages
from WinUx.platform.floating_viewport import centered_position, window_rect, work_area


class View:
    def __init__(self):
        self.incoming = queue.Queue()
        self.pending = []
        self.sequence = itertools.count()
        self.errors = []

    def after(self, delay, callback, *args):
        self.incoming.put((time.monotonic() + delay/1000, next(self.sequence), callback, args))

    def after_render(self, callback, *args):
        self.after(0, callback, *args)

    def drain(self):
        for _ in range(256):
            try:
                heapq.heappush(self.pending, self.incoming.get_nowait())
            except queue.Empty:
                break
        for _ in range(256):
            if not self.pending or self.pending[0][0] > time.monotonic():
                break
            _, _, callback, args = heapq.heappop(self.pending)
            callback(*args)

    def winfo_exists(self):
        return True

    def show_error(self, *args):
        self.errors.append(args)


class ProtocolTests(unittest.TestCase):
    def test_centering_preserves_negative_monitor_coordinates_and_clamps_to_work_area(self):
        self.assertEqual(centered_position((-1600, 100, -800, 700), (400, 300), (-1920, 0, 0, 1080)), (-1400, 250))
        self.assertEqual(centered_position((0, 0, 100, 100), (400, 300), (0, 0, 1920, 1080)), (0, 0))
    def test_preserves_remote_paths_datetime_keys_and_unicode_user_data(self):
        source = {"jobs": [{"path": PurePosixPath("/scratch/cafe.inp"), "_run_at": datetime(2030, 1, 2, 3, 4, 5)}],
                  "cores": {Path("job.inp"): 8}, "name": "cafe"}
        # Use escaped Unicode at the transport boundary; UI-owned captions are
        # ASCII, while user paths/content must remain lossless.
        source["name"] = "caf" + chr(233)
        source["jobs"][0]["path"] = PurePosixPath("/scratch/" + source["name"] + ".inp")
        sender, receiver = socket.socketpair()
        try:
            sender.sendall(encode_message(source))
            self.assertEqual(next(read_messages(receiver)), source)
        finally:
            sender.close()
            receiver.close()

    def test_odb_payload_larger_than_old_64k_limit_is_not_truncated(self):
        source = {"result": {"text": "history data " * 10000}}
        sender, receiver = socket.socketpair()
        thread = threading.Thread(target=lambda: sender.sendall(encode_message(source)))
        try:
            thread.start()
            self.assertEqual(next(read_messages(receiver)), source)
        finally:
            receiver.close()
            thread.join(timeout=2)
            sender.close()

    def test_owned_dialog_captions_have_no_special_unicode_symbols(self):
        root = Path(__file__).resolve().parents[1] / "WinUx" / "dialogs"
        for name in ("login_form", "blocking_form", "bookmarks_form", "site_manager_form", "sync_preview_form",
                     "server_path_form", "progress_form", "job_edit_form", "job_manager_form", "job_schedule_form",
                     "settings_form", "diagnostics_form", "odb_check_form", "odb_extract_form", "console_form",
                     "transfer_center_form", "modern"):
            source = (root / (name + ".py")).read_text(encoding="utf-8")
            self.assertTrue(source.isascii(), name)


class DeferredFocusTests(unittest.TestCase):
    def controller(self):
        class QueueView:
            def __init__(self):
                self.pending = []
                self._floating_dialogs = set()
            def after(self, delay, callback, *args):
                self.pending.append((callback, args))
            def tick(self):
                callback, args = self.pending.pop(0)
                callback(*args)
        controller = object.__new__(FloatingDialogController)
        controller.view = QueueView()
        controller._owner_hwnd = 1
        controller._hwnd = 2
        controller._owned_dialogs = []
        controller._focus_return_generation = 0
        return controller

    def test_focus_waits_for_child_to_disappear_before_activating_parent(self):
        controller = self.controller()
        state = {"child_visible": True, "foreground": 2}
        def window(hwnd):
            return (True, True, True) if hwnd == 1 else (True, state["child_visible"], True)
        def focus(hwnd):
            state["foreground"] = hwnd
        with patch("WinUx.dialogs.floating_dialog._window_state", side_effect=window), \
             patch("WinUx.dialogs.floating_dialog._foreground_hwnd", side_effect=lambda: state["foreground"]), \
             patch("WinUx.dialogs.floating_dialog.restore_owner_foreground", side_effect=focus) as restore:
            controller._queue_owner_focus()
            controller.view.tick()
            restore.assert_not_called()
            state["child_visible"] = False
            controller.view.tick()
            restore.assert_called_once_with(1)

    def test_focus_return_never_enables_an_owner_disabled_by_another_modal(self):
        controller = self.controller()
        with patch("WinUx.dialogs.floating_dialog._foreground_hwnd", return_value=2), \
             patch("WinUx.dialogs.floating_dialog._window_state", return_value=(True, True, False)), \
             patch("WinUx.dialogs.floating_dialog.restore_owner_foreground") as restore:
            controller._queue_owner_focus()
            controller.view.tick()
            restore.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Real floating dialogs require Windows")
class AllFloatingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.user32 = ctypes.windll.user32
        u = self.user32
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u.CreateWindowExW.restype = wintypes.HWND
        u.DestroyWindow.argtypes = [wintypes.HWND]
        u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.IsWindowEnabled.argtypes = [wintypes.HWND]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetFocus.argtypes = []
        u.GetFocus.restype = wintypes.HWND
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.SetFocus.argtypes = [wintypes.HWND]
        u.SetFocus.restype = wintypes.HWND
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.owner = u.CreateWindowExW(0, "STATIC", "WinUx Dialog Test Owner", 0x10cf0000,
                                      600, 300, 240, 180, None, None, None, None)
        self.assertTrue(self.owner)
        # The harness may run on a non-input desktop: foreground HWND is then
        # always NULL. Keyboard focus still has a real per-thread Win32 state.
        self.foreground_available = bool(u.GetForegroundWindow())
        self.view = View()
        self.instances = []

    def tearDown(self):
        close_floating_dialogs(self.view)
        for instance in self.instances:
            deadline = time.monotonic() + 5
            while instance._process.poll() is None and time.monotonic() < deadline:
                self.tick()
        self.user32.DestroyWindow(self.owner)

    def tick(self):
        message = wintypes.MSG()
        while self.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))
        self.view.drain()
        time.sleep(.01)

    def wait_for(self, predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.tick()
        self.assertTrue(predicate(), str(self.view.errors))
        self.assertFalse(self.view.errors, str(self.view.errors))

    def create(self, constructor):
        with patch("WinUx.dialogs.floating_dialog.find_process_window", return_value=int(self.owner)):
            instance = constructor()
        self.instances.append(instance)
        self.assertIsInstance(instance, FloatingDialogController)
        self.wait_for(lambda: instance._ready or not instance.winfo_exists())
        self.assertTrue(instance._ready, str(self.view.errors))
        return instance

    def activate(self, instance):
        from WinUx.platform.native_dialog_host import restore_owner_focus
        restore_owner_focus(instance._hwnd)
        if self.foreground_available:
            self.wait_for(lambda: self.user32.GetForegroundWindow() == instance._hwnd, timeout=5)

    def test_every_dialog_is_a_real_floatable_modal_or_modeless_window(self):
        noop = lambda *args: None
        constructors = [
            ("login", lambda: dialogs.LoginDialog(self.view, noop)),
            ("blocking", lambda: dialogs.BlockingDialog(self.view, "Confirm", "Continue?", kind="confirm", on_result=noop)),
            ("bookmarks", lambda: dialogs.BookmarksDialog(self.view, [], noop, noop, noop)),
            ("sites", lambda: dialogs.SiteManagerDialog(self.view, [], noop, noop, noop)),
            ("sync", lambda: dialogs.SyncPreviewDialog(self.view, [], "/local", "/remote", noop, noop)),
            ("server_path", lambda: dialogs.ServerPathDialog(self.view, "/", lambda p: ["/test"])),
            ("progress", lambda: dialogs.ProgressDialog(self.view, "Upload", threading.Event())),
            ("job_edit", lambda: dialogs.JobEditDialog(self.view, ["1", "test", "user", "4", "Running", "1s"])),
            ("job_manager", lambda: dialogs.JobManagerDialog(self.view, [PurePosixPath("/scratch/job.inp")], noop, noop)),
            ("job_schedule", lambda: dialogs.JobScheduleDialog(self.view, lambda: [("test", "Run", "2030", "1h", "Waiting", "run", "key")], noop)),
            ("settings", lambda: dialogs.SettingsDialog(self.view)),
            ("diagnostics", lambda: dialogs.DiagnosticsDialog(self.view)),
            ("odb_check", lambda: dialogs.ODBCheckDialog(self.view, {})),
            ("odb_extract", lambda: dialogs.ODBExtractDialog(self.view, {}, noop)),
            ("odb_xy", lambda: dialogs.ODBXYResultDialog(self.view, {"curves": [{"name": "curve", "points": [[0, 1]]}]})),
            ("console", lambda: dialogs.ConsoleDialog(self.view, lambda: "connected", lambda c: True, lambda: True)),
            ("transfer_center", lambda: dialogs.TransferCenterDialog(self.view)),
        ]
        self.assertEqual({kind for kind, constructor in constructors}, set(FORM_KINDS))
        for kind, constructor in constructors:
            with self.subTest(dialog=kind):
                instance = self.create(constructor)
                hwnd = instance._hwnd
                startup = instance._startup_layout
                prepared = next(event for event in startup if event["stage"] == "prepared")
                published = next(event for event in startup if event["stage"] == "published")
                self.assertTrue(prepared["cloaked"], kind + " warm-up must not be visible")
                self.assertFalse(published["cloaked"], kind)
                for event in startup:
                    if event["stage"] == "initial_show":
                        self.assertTrue(event["cloaked"], kind + " flashed during initial ShowWindow")
                self.assertEqual(prepared["rect"], published["rect"], kind + " moved while revealed")
                left, top, right, bottom = published["rect"]
                expected = centered_position(window_rect(self.owner), (right-left, bottom-top), work_area(self.owner))
                self.assertEqual((left, top), expected, kind + " first visible frame is not centered")
                self.assertEqual(instance._initial_reveal_count, int(published["visible"]), kind)
                self.assertEqual(self.user32.GetWindowLongPtrW(hwnd, -8), int(self.owner), kind)
                self.assertFalse(self.user32.GetWindowLongPtrW(hwnd, -16) & 0x40000000, kind)
                self.assertEqual(bool(self.user32.IsWindowEnabled(self.owner)), not instance.modal, kind)
                self.assertTrue(self.user32.IsWindowEnabled(hwnd), kind)
                width, height = instance._client_layout["client"]
                self.assertFalse(instance._client_layout["shell_scrollbar"], kind + " native shell must not scroll")
                left, top, right, bottom = instance._client_layout["footer"]
                self.assertGreaterEqual(left, 0, kind)
                self.assertGreaterEqual(top, 0, kind)
                self.assertLessEqual(right, width + 1, kind + " footer is clipped horizontally")
                self.assertLessEqual(bottom, height + 1, kind + " footer is clipped vertically")
                if kind == "job_manager":
                    self.assertLess(height, 240, "One input file must not open a mostly empty tall window")
                    for name, (left, top, right, bottom) in instance._client_layout["widgets"].items():
                        self.assertLessEqual(right, width, name)
                        self.assertLessEqual(bottom, height, name)
                self.user32.SetWindowPos(hwnd, None, 80, 100, 0, 0, 0x0001 | 0x0004)
                rectangle = wintypes.RECT()
                self.user32.GetWindowRect(hwnd, ctypes.byref(rectangle))
                self.assertEqual(rectangle.left, 80, kind)
                instance.destroy()
                self.wait_for(lambda: instance._process.poll() is not None, timeout=8)
                self.assertTrue(self.user32.IsWindowEnabled(self.owner), kind)

    def test_native_close_reports_cancel_before_result_dialog_disappears(self):
        received = []
        instance = self.create(lambda: dialogs.BlockingDialog(self.view, "Confirm", "Continue?", kind="confirm", on_result=received.append))
        self.user32.PostMessageW(instance._hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: instance.result["done"] and received == [False])
        self.assertFalse(instance.winfo_exists())
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))

    def test_close_returns_foreground_and_keyboard_focus_for_modal_and_modeless(self):
        for constructor in (
            lambda: dialogs.BlockingDialog(self.view, "Focus", "Close this prompt", kind="confirm"),
            lambda: dialogs.BookmarksDialog(self.view, [], lambda *a: None, lambda *a: None, lambda *a: None),
        ):
            with self.subTest(constructor=constructor):
                instance = self.create(constructor)
                if self.foreground_available:
                    self.activate(instance)
                self.user32.SetFocus(None)
                self.user32.PostMessageW(instance._hwnd, 0x0010, 0, 0)
                self.wait_for(lambda: not instance.winfo_exists()
                    and (not self.foreground_available or self.user32.GetForegroundWindow() == self.owner)
                    and self.user32.GetFocus() == self.owner, timeout=5)

    def test_enter_activates_default_action_in_a_modeless_window(self):
        received = []
        entry = {"panel_id": "server", "path": "/test", "label": "Test"}
        second = {"panel_id": "server", "path": "/second", "label": "Second"}
        instance = self.create(lambda: dialogs.BookmarksDialog(self.view, [entry, second], received.append, lambda *a: None, lambda *a: None))
        from WinUx.platform.native_dialog_host import restore_owner_focus
        restore_owner_focus(instance._hwnd)
        self.user32.PostMessageW(instance._hwnd, 0x0007, 0, 0)  # WM_SETFOCUS
        self.user32.PostMessageW(instance._hwnd, 0x0100, 40, 0x01500001)  # Down
        self.user32.PostMessageW(instance._hwnd, 0x0101, 40, 0xc1500001)
        for _ in range(10):
            self.tick()
        self.user32.PostMessageW(instance._hwnd, 0x0100, 13, 0x001c0001)  # Return down
        self.user32.PostMessageW(instance._hwnd, 0x0101, 13, 0xc01c0001)  # Return up
        self.wait_for(lambda: bool(received), timeout=5)
        self.assertEqual(received, [second])
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))

    def test_transfer_native_close_hides_without_cancelling_task_and_show_restores(self):
        center = self.create(lambda: dialogs.TransferCenterDialog(self.view))
        event = threading.Event()
        task = center.add_task("Upload", event, ["job.inp"])
        self.wait_for(lambda: bool(self.user32.IsWindowVisible(center._hwnd)))
        self.activate(center)
        # A stalled main UI must not enqueue one IPC packet per worker sample.
        for done in range(1000):
            task.update_progress("job.inp", done, 2000, done, 2000)
        self.assertLessEqual(center._outgoing.qsize(), 4)
        self.user32.PostMessageW(center._hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: not self.user32.IsWindowVisible(center._hwnd))
        self.wait_for(lambda: (not self.foreground_available or self.user32.GetForegroundWindow() == self.owner)
                      and self.user32.GetFocus() == self.owner, timeout=5)
        self.assertTrue(center.winfo_exists())
        self.assertTrue(task.winfo_exists())
        self.assertFalse(event.is_set())
        center.show()
        self.wait_for(lambda: bool(self.user32.IsWindowVisible(center._hwnd)))
        center.cancel_all()
        self.assertTrue(event.is_set())
        task.complete()
        center.clear_finished()

    def test_nested_rename_modal_is_owned_by_the_modeless_bookmark_window(self):
        bookmarks = self.create(lambda: dialogs.BookmarksDialog(self.view, [], lambda *a: None, lambda *a: None, lambda *a: None))
        bookmarks.handle_event("rename_prompt", {"entry": {"label": "test", "path": "/test", "panel_id": "server"}})
        nested = bookmarks._owned_dialogs[-1]
        self.instances.append(nested)
        self.wait_for(lambda: nested._ready)
        self.assertEqual(self.user32.GetWindowLongPtrW(nested._hwnd, -8), bookmarks._hwnd)
        published = next(event for event in nested._startup_layout if event["stage"] == "published")
        left, top, right, bottom = published["rect"]
        self.assertEqual((left, top), centered_position(window_rect(bookmarks._hwnd),
            (right-left, bottom-top), work_area(bookmarks._hwnd)))
        self.assertFalse(self.user32.IsWindowEnabled(bookmarks._hwnd))
        if self.foreground_available:
            self.activate(nested)
        nested.destroy()
        self.assertTrue(self.user32.IsWindowEnabled(bookmarks._hwnd))
        from WinUx.dialogs.floating_dialog import _owner_has_keyboard_focus
        self.wait_for(lambda: _owner_has_keyboard_focus(bookmarks._hwnd)
            and (not self.foreground_available or self.user32.GetForegroundWindow() == bookmarks._hwnd), timeout=5)

    def test_background_close_does_not_take_focus_from_another_dialog(self):
        constructor = lambda: dialogs.BookmarksDialog(self.view, [], lambda *a: None, lambda *a: None, lambda *a: None)
        first = self.create(constructor)
        second = self.create(constructor)
        if self.foreground_available:
            self.activate(second)
            first.destroy()
            self.wait_for(lambda: first._process.poll() is not None, timeout=8)
            self.assertEqual(self.user32.GetForegroundWindow(), second._hwnd)
        else:
            # Exercise the foreground ownership guard deterministically while
            # still closing a real background HWND on the non-input desktop.
            with patch("WinUx.dialogs.floating_dialog._foreground_hwnd", return_value=second._hwnd), \
                 patch("WinUx.dialogs.floating_dialog.restore_owner_foreground") as restore:
                first.destroy()
                self.wait_for(lambda: first._process.poll() is not None, timeout=8)
                restore.assert_not_called()

    def test_shutdown_closes_modal_and_modeless_windows_and_releases_registry(self):
        self.create(lambda: dialogs.BookmarksDialog(self.view, [], lambda *a: None, lambda *a: None, lambda *a: None))
        self.create(lambda: dialogs.BlockingDialog(self.view, "Shutdown", "Confirm?", kind="confirm"))
        self.assertFalse(self.user32.IsWindowEnabled(self.owner))
        close_floating_dialogs(self.view)
        self.assertFalse(self.view._floating_dialogs)
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))


if __name__ == "__main__":
    unittest.main()
