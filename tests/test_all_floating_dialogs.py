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
                      "transfer_center_form", "reference_chart_form", "modern"):
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
        from DearUIQt import input_gate
        input_gate.reset_pointer_input_gate()
        # This fixture has a native STATIC owner, not a rendering DPG context.
        # Advance the release guards with its synthetic UI turns rather than
        # leaving them latched at DPG's absent/stale global frame counter.
        self.frame = 0
        frame_patch = patch("DearUIQt.input_gate._frame_count", side_effect=lambda: self.frame)
        frame_patch.start()
        self.addCleanup(frame_patch.stop)
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
        self.frame += 1
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
        if not predicate():
            from WinUx.ui.native.native_dialog_host import _MODAL_OWNER_COUNTS
            print("Dialog focus failure:", {
                "foreground": int(self.user32.GetForegroundWindow() or 0),
                "thread_focus": int(self.user32.GetFocus() or 0),
                "owner": int(self.owner),
                "owner_enabled": bool(self.user32.IsWindowEnabled(self.owner)),
                "modal_owners": dict(_MODAL_OWNER_COUNTS),
                "dialogs": [(item.kind if hasattr(item, "kind") else item.title,
                             item._hwnd, item._visible, item._native_visible, item._closed,
                             bool(self.user32.IsWindowEnabled(item._hwnd)))
                            for item in self.instances],
            }, flush=True)
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
        from WinUx.dialogs.floating_adapters import LocalFileDialog
        from WinUx.plotdigitizer.integration import open_plot_digitizer
        noop = lambda *args: None
        constructors = [
            ("login", lambda: dialogs.LoginDialog(self.view, noop)),
            ("blocking", lambda: dialogs.BlockingDialog(self.view, "Confirm", "Continue?", kind="confirm", on_result=noop)),
            ("bookmarks", lambda: dialogs.BookmarksDialog(self.view, [], noop, noop, noop)),
            ("sites", lambda: dialogs.SiteManagerDialog(self.view, [], noop, noop, noop)),
            ("sync", lambda: dialogs.SyncPreviewDialog(self.view, [], "/local", "/remote", noop, noop)),
            ("server_path", lambda: dialogs.ServerPathDialog(self.view, "/", lambda p: ["/test"])),
            ("local_folder", lambda: dialogs.LocalFolderDialog(self.view, str(Path.cwd()), noop)),
            ("local_file", lambda: LocalFileDialog(
                self.view, str(Path.cwd()), noop, extensions=(".png",))),
            ("plotdigitizer", lambda: open_plot_digitizer(self.view)),
            ("progress", lambda: dialogs.ProgressDialog(self.view, "Upload", threading.Event())),
            ("job_edit", lambda: dialogs.JobEditDialog(self.view, ["1", "test", "user", "4", "Running", "1s"])),
            ("job_manager", lambda: dialogs.JobManagerDialog(self.view, [PurePosixPath("/scratch/job.inp")], noop, noop)),
            ("job_schedule", lambda: dialogs.JobScheduleDialog(self.view, lambda: [("test", "Run", "2030", "1h", "Waiting", "run", "key")], noop)),
            ("settings", lambda: dialogs.SettingsDialog(self.view)),
            ("diagnostics", lambda: dialogs.DiagnosticsDialog(self.view)),
            ("odb_check", lambda: dialogs.ODBCheckDialog(self.view, {})),
            ("odb_extract", lambda: dialogs.ODBExtractDialog(self.view, {}, noop)),
            ("reference_chart", lambda: dialogs.ReferenceChartDialog(self.view, [], noop)),
            ("odb_xy", lambda: dialogs.ODBXYResultDialog(self.view, {"curves": [{"name": "curve", "points": [[0, 1]]}]})),
            ("console", lambda: dialogs.ConsoleDialog(self.view, lambda: "connected", lambda c: True, lambda: True)),
            ("console_dock", lambda: FloatingDialogController(self.view, "console_dock", "SSH Console")),
            ("plot_dock", lambda: FloatingDialogController(self.view, "plot_dock", "Job Plots")),
            ("transfer_center", lambda: dialogs.TransferCenterDialog(self.view)),
        ]
        self.assertEqual({kind for kind, constructor in constructors}, set(FORM_KINDS))
        for kind, constructor in constructors:
            with self.subTest(dialog=kind):
                # Report each dialog's own failure, not stale errors from an
                # earlier subtest that already failed.
                self.view.errors.clear()
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
                # Owned is not parented: move beyond the main viewport bounds.
                owner_right = window_rect(self.owner)[2]
                outside_x = owner_right + 30
                self.user32.SetWindowPos(hwnd, None, outside_x, 100, 0, 0, 0x0001 | 0x0004)
                rectangle = wintypes.RECT()
                self.user32.GetWindowRect(hwnd, ctypes.byref(rectangle))
                self.assertEqual(rectangle.left, outside_x, kind)
                instance.destroy()
                # A clean reusable host stays alive after its dialog closes.
                # Wait for the idle ACK, not process exit (which only occurs
                # when the pool retires it or the test tears down).
                self.wait_for(lambda: not instance.winfo_exists() and (
                    instance._host_returned if instance._reuse_host
                    else instance._process.poll() is not None), timeout=8)
                self.assertTrue(self.user32.IsWindowEnabled(self.owner), kind)

    def test_plotdigitizer_typography_workspace_and_native_file_selector(self):
        from WinUx.plotdigitizer.integration import open_plot_digitizer

        instance = self.create(lambda: open_plot_digitizer(self.view))
        self.assertFalse(instance.modal)
        style = self.user32.GetWindowLongPtrW(instance._hwnd, -16)
        self.assertEqual(style & 0x00070000, 0x00070000)
        self.assertEqual(instance._client_layout["footer"],
                         [0, instance._client_layout["client"][1], 0, instance._client_layout["client"][1]])
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))
        self.assertEqual(instance._client_layout["typography"], {"family": "Segoe UI", "size": 14})
        widgets = instance._client_layout["widgets"]
        self.assertGreater(widgets["canvas"][2] - widgets["canvas"][0], 400)
        self.assertGreater(widgets["canvas"][3] - widgets["canvas"][1], 300)
        width, height = instance._client_layout["client"]
        for name, (left, top, right, bottom) in widgets.items():
            self.assertGreaterEqual(left, 0, name)
            self.assertGreaterEqual(top, 0, name)
            self.assertLessEqual(right, width + 1, name)
            self.assertLessEqual(bottom, height + 1, name)

        instance.post("open_file_selector")
        file_windows = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]

        def find_selector():
            file_windows.clear()

            def visit(hwnd, _param):
                if self.user32.GetWindowLongPtrW(hwnd, -8) == int(instance._hwnd):
                    title = ctypes.create_unicode_buffer(256)
                    self.user32.GetWindowTextW(hwnd, title, 256)
                    if title.value == "Open File" and self.user32.IsWindowVisible(hwnd):
                        file_windows.append(hwnd)
                return True

            self.user32.EnumWindows(callback_type(visit), 0)
            return bool(file_windows)

        self.wait_for(lambda: find_selector() and not self.user32.IsWindowEnabled(instance._hwnd))
        selector = file_windows[0]
        self.assertFalse(self.user32.GetWindowLongPtrW(selector, -16) & 0x40000000)
        self.assertFalse(self.user32.IsWindowEnabled(instance._hwnd))
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))
        self.user32.SetWindowPos(selector, None, 30, 50, 0, 0, 0x0001 | 0x0004)
        self.assertEqual(window_rect(selector)[:2], (30, 50))
        self.user32.PostMessageW(selector, 0x0010, 0, 0)
        self.wait_for(lambda: not self.user32.IsWindowVisible(selector)
                      and self.user32.IsWindowEnabled(instance._hwnd))
        # Exercise the actual reported sequence, not just opening each form in
        # isolation: use a nested selector, return to WinUx with the modeless
        # digitizer still alive, then open unrelated application dialogs.
        for constructor in (
                lambda: dialogs.SettingsDialog(self.view),
                lambda: dialogs.BlockingDialog(self.view, "Confirm", "Continue?", kind="confirm")):
            other = self.create(constructor)
            self.assertTrue(self.user32.IsWindowVisible(other._hwnd))
            other.destroy()
            self.wait_for(lambda: not other.winfo_exists() and (
                other._host_returned if other._reuse_host
                else other._process.poll() is not None), timeout=8)
        instance.close()

    def test_legacy_parent_cannot_disable_plot_digitizer_window_controls_in_a_cold_worker(self):
        instance = self.create(lambda: FloatingDialogController(
            self.view, "plotdigitizer", "Plot Digitizer", resizable=False,
            allow_minimize=False, allow_maximize=False))
        self.assertFalse(instance._from_prewarm)
        self.assertEqual(self.user32.GetWindowLongPtrW(instance._hwnd, -16) & 0x00070000, 0x00070000)
        self.assertFalse(self.user32.GetWindowLongPtrW(instance._hwnd, -20) & 0x80)
        instance.destroy()
        self.wait_for(lambda: instance._process.poll() is not None, timeout=8)
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))

    def test_main_input_and_other_dialogs_work_with_digitizer_open_behind(self):
        from collections import deque
        from unittest.mock import Mock
        from DearUIQt import input_gate
        from WinUx.view import WinUXView
        from WinUx.plotdigitizer.integration import open_plot_digitizer

        digitizer = self.create(lambda: open_plot_digitizer(self.view))
        left, top, right, bottom = window_rect(digitizer._hwnd)
        # Independent native surface models returning to a window covering the
        # modeless tool. Keep its HWND alive/registered throughout this test.
        overlay = self.user32.CreateWindowExW(
            0, "BUTTON", "WinUx foreground input regression", 0x10cf0000,
            left + 80, top + 80, 240, 180, None, None, None, None)
        self.assertTrue(overlay)
        try:
            # Only this short-lived test cover is TOPMOST: native owned-window
            # activation would otherwise race the synthetic occlusion setup.
            self.user32.SetWindowPos(overlay, wintypes.HWND(-1), 0, 0, 0, 0,
                                     0x0001 | 0x0002 | 0x0010)
            self.tick()
            bounds = window_rect(overlay)
            point = ((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)
            view = object.__new__(WinUXView)
            view._alive = True
            view._dpg_callbacks = deque()
            from DearUIQt.runtime import QGuiRuntime
            view._gui_runtime = QGuiRuntime()
            opened = Mock()
            with patch.object(input_gate, "_native_cursor_position", return_value=point), \
                    patch.object(input_gate, "_mouse_button_down", return_value=False), \
                    patch.object(input_gate, "_frame_count", return_value=10), \
                    patch.object(view._gui_runtime, "callbackQueue", return_value=[(opened,)]):
                self.assertIsNone(input_gate._native_surface_under_pointer())
                view._drain_dpg_callbacks()
            opened.assert_called_once_with()
        finally:
            self.user32.DestroyWindow(overlay)

        # Different dialog types must publish while the digitizer stays alive,
        # then still publish after its host has been returned to the pool.
        for constructor in (
                lambda: dialogs.SettingsDialog(self.view),
                lambda: dialogs.BlockingDialog(self.view, "Confirm", "Continue?", kind="confirm"),
                lambda: dialogs.BookmarksDialog(self.view, [], lambda *a: None,
                                                lambda *a: None, lambda *a: None)):
            dialog = self.create(constructor)
            self.assertTrue(self.user32.IsWindowVisible(dialog._hwnd))
            dialog.destroy()
            self.wait_for(lambda: not dialog.winfo_exists() and (
                dialog._host_returned if dialog._reuse_host
                else dialog._process.poll() is not None), timeout=8)
        digitizer.close()
        self.wait_for(lambda: not digitizer._visible and not digitizer._native_visible
                      and not self.user32.IsWindowVisible(digitizer._hwnd), timeout=8)
        dialog = self.create(lambda: dialogs.SettingsDialog(self.view))
        self.assertTrue(self.user32.IsWindowVisible(dialog._hwnd))

    def test_repeated_digitizer_selector_escape_cycles_then_close_app(self):
        from types import MethodType
        from unittest.mock import Mock
        from WinUx.controller import WinUXController
        from WinUx.view import WinUXView
        from WinUx.plotdigitizer.integration import open_plot_digitizer

        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        enum_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.EnumWindows.argtypes = [enum_type, wintypes.LPARAM]

        def selector_window(owner):
            found = []
            def visit(hwnd, _param):
                if (self.user32.GetWindowLongPtrW(hwnd, -8) == owner
                        and self.user32.IsWindowVisible(hwnd)):
                    title = ctypes.create_unicode_buffer(128)
                    self.user32.GetWindowTextW(hwnd, title, 128)
                    if title.value == "Open File":
                        found.append(int(hwnd))
                return True
            self.user32.EnumWindows(enum_type(visit), 0)
            return found[0] if found else None

        def escape(hwnd, released_to=None):
            self.user32.PostMessageW(hwnd, 0x0100, 27, 0x00010001)
            self.tick()
            # Real Esc key-up can reach the newly activated owner, not the
            # hidden/recycled selector that received key-down.
            self.user32.PostMessageW(released_to or hwnd, 0x0101, 27, 0xc0010001)

        for reopen in range(2):
            digitizer = self.create(lambda: open_plot_digitizer(self.view))
            for cycle in range(4):
                with self.subTest(reopen=reopen, cycle=cycle):
                    digitizer.post("open_file_selector")
                    self.wait_for(lambda: selector_window(digitizer._hwnd)
                                  and not self.user32.IsWindowEnabled(digitizer._hwnd), timeout=8)
                    selector = selector_window(digitizer._hwnd)
                    escape(selector, released_to=digitizer._hwnd)
                    self.wait_for(lambda: not self.user32.IsWindowVisible(selector)
                                  and self.user32.IsWindowEnabled(digitizer._hwnd), timeout=8)
                    self.assertTrue(digitizer.winfo_exists(), "Esc closed the tool behind its selector")
                    self.assertTrue(self.user32.IsWindowEnabled(self.owner))
            escape(digitizer._hwnd)
            self.wait_for(lambda: not digitizer._visible and not digitizer._native_visible
                          and not self.user32.IsWindowVisible(digitizer._hwnd), timeout=8)

        self.view._alive = True
        self.view._find_main_viewport_hwnd = lambda: int(self.owner)
        for name in ("confirm_action_async", "_drain_async_confirm_requests"):
            setattr(self.view, name, MethodType(getattr(WinUXView, name), self.view))
        app = object.__new__(WinUXController)
        app._closing = app._close_confirmation_pending = False
        app.view = self.view
        app.job_schedules = Mock(return_value=[])
        app._finish_close = Mock()
        app.close()
        confirmation = self.view._async_confirm_dialog
        self.instances.append(confirmation)
        self.wait_for(lambda: confirmation._ready, timeout=8)
        self.assertTrue(self.user32.IsWindowVisible(confirmation._hwnd))
        confirmation.accept()
        self.wait_for(lambda: app._finish_close.called, timeout=8)

    def test_reference_chart_opens_native_modal_and_closes_cleanly(self):
        from WinUx.services.reference_charts import parse_reference_text
        received = []
        references = parse_reference_text("0,1\n1,2", "Measured")
        instance = self.create(lambda: dialogs.ReferenceChartDialog(self.view, references, received.append))
        self.assertTrue(self.user32.IsWindowVisible(instance._hwnd))
        self.assertFalse(self.user32.IsWindowEnabled(self.owner))
        width, height = instance._client_layout["client"]
        for name, bounds in instance._client_layout["widgets"].items():
            self.assertGreaterEqual(bounds[0], 0, name)
            self.assertGreaterEqual(bounds[1], 0, name)
            self.assertLessEqual(bounds[2], width + 1, name)
            self.assertLessEqual(bounds[3], height + 1, name)
        instance.destroy()
        self.wait_for(lambda: instance._process.poll() is not None, timeout=8)
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))
        self.assertEqual(received, [])

    def test_native_close_reports_cancel_before_result_dialog_disappears(self):
        received = []
        instance = self.create(lambda: dialogs.BlockingDialog(self.view, "Confirm", "Continue?", kind="confirm", on_result=received.append))
        self.user32.PostMessageW(instance._hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: instance.result["done"] and received == [False])
        self.assertFalse(instance.winfo_exists())
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))

    def test_close_app_confirmation_survives_an_existing_native_confirm(self):
        from types import MethodType
        from unittest.mock import Mock
        from WinUx.controller import WinUXController
        from WinUx.view import WinUXView

        self.view._alive = True
        self.view._find_main_viewport_hwnd = lambda: int(self.owner)
        for name in ("confirm_action_async", "_drain_async_confirm_requests"):
            setattr(self.view, name, MethodType(getattr(WinUXView, name), self.view))
        first = self.view.confirm_action_async("Existing Confirm", "Continue?", lambda value: None)
        self.instances.append(first)
        self.wait_for(lambda: first._ready)
        app = object.__new__(WinUXController)
        app._closing = app._close_confirmation_pending = False
        app.view = self.view
        app.job_schedules = Mock(return_value=[])
        app._finish_close = Mock()
        app.close()
        self.assertIs(self.view._async_confirm_dialog, first)
        self.user32.PostMessageW(first._hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: self.view._async_confirm_dialog is not None
                      and self.view._async_confirm_dialog is not first
                      and self.view._async_confirm_dialog._ready)
        confirmation = self.view._async_confirm_dialog
        self.instances.append(confirmation)
        self.assertEqual(confirmation.title, "Confirm Close App")
        self.assertTrue(self.user32.IsWindowVisible(confirmation._hwnd))
        # Cancel via native X, then verify a second Exit can be accepted.
        self.user32.PostMessageW(confirmation._hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: not app._close_confirmation_pending)
        app._finish_close.assert_not_called()
        app.close()
        confirmation = self.view._async_confirm_dialog
        self.instances.append(confirmation)
        self.wait_for(lambda: confirmation._ready)
        confirmation.accept()
        self.wait_for(lambda: app._finish_close.called)
        app._finish_close.assert_called_once_with()

    def test_close_returns_foreground_and_keyboard_focus_for_modal_and_modeless(self):
        if not self.foreground_available:
            self.skipTest("Windows has no interactive foreground desktop for focus assertions")
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
                self.wait_for(lambda: (not instance.winfo_exists() or (
                    instance._retain_on_close and not instance._visible
                    and not self.user32.IsWindowVisible(instance._hwnd)))
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

    def test_bookmarks_initial_current_row_activates_without_an_extra_click(self):
        received = []
        entry = {"panel_id": "server", "path": "/first", "label": "First"}
        instance = self.create(lambda: dialogs.BookmarksDialog(
            self.view, [entry], received.append, lambda *args: None, lambda *args: None))
        from WinUx.platform.native_dialog_host import restore_owner_focus
        restore_owner_focus(instance._hwnd)
        self.user32.PostMessageW(instance._hwnd, 0x0007, 0, 0)
        self.user32.PostMessageW(instance._hwnd, 0x0100, 13, 0x001c0001)
        self.user32.PostMessageW(instance._hwnd, 0x0101, 13, 0xc01c0001)
        self.wait_for(lambda: bool(received), timeout=5)
        self.assertEqual(received, [entry])

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
        with self.subTest(check="foreground-and-keyboard-return"):
            if not self.foreground_available:
                self.skipTest("No interactive foreground desktop; transfer lifecycle still checked")
            self.wait_for(lambda: self.user32.GetForegroundWindow() == self.owner
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
        with self.subTest(check="foreground-and-keyboard-return"):
            if not self.foreground_available:
                self.skipTest("No interactive foreground desktop; nested modality still checked")
            self.wait_for(lambda: _owner_has_keyboard_focus(bookmarks._hwnd)
                and self.user32.GetForegroundWindow() == bookmarks._hwnd, timeout=5)

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

    def test_closing_bookmark_parent_with_active_rename_returns_focus_to_main(self):
        from WinUx.platform.dialog_focus import owner_has_keyboard_focus
        from DearUIQt.input_gate import native_modal_input_active
        bookmarks = self.create(lambda: dialogs.BookmarksDialog(
            self.view, [], lambda *a: None, lambda *a: None, lambda *a: None))
        bookmarks.handle_event("rename_prompt", {"entry": {
            "label": "test", "path": "/test", "panel_id": "server"}})
        nested = bookmarks._owned_dialogs[-1]
        self.instances.append(nested)
        self.wait_for(lambda: nested._ready)
        self.activate(nested)
        self.assertFalse(self.user32.IsWindowEnabled(bookmarks._hwnd))
        bookmarks.destroy()
        self.wait_for(lambda: bookmarks._closed and nested._closed)
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))
        self.assertFalse(native_modal_input_active())
        with self.subTest(check="foreground-and-keyboard-return"):
            if not self.foreground_available:
                self.skipTest("No interactive foreground desktop; teardown and input release still checked")
            self.wait_for(lambda: int(self.user32.GetForegroundWindow() or 0) == self.owner
                           and owner_has_keyboard_focus(self.owner), timeout=5)

    def test_shutdown_closes_modal_and_modeless_windows_and_releases_registry(self):
        self.create(lambda: dialogs.BookmarksDialog(self.view, [], lambda *a: None, lambda *a: None, lambda *a: None))
        self.create(lambda: dialogs.BlockingDialog(self.view, "Shutdown", "Confirm?", kind="confirm"))
        self.assertFalse(self.user32.IsWindowEnabled(self.owner))
        close_floating_dialogs(self.view)
        self.assertFalse(self.view._floating_dialogs)
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))


if __name__ == "__main__":
    unittest.main()
