"""Measure cold/warm prompt latency and validate one-shot worker ownership."""
import os
import time
import unittest
from unittest.mock import patch
from pathlib import PurePosixPath

import test_all_floating_dialogs as support
from WinUx import dialogs
from WinUx.dialogs.prewarm_pool import DialogPrewarmPool, runtime_source_signature
from WinUx.platform.floating_viewport import centered_position, window_rect, work_area, cloaked


@unittest.skipUnless(os.name == "nt", "DPG worker prewarming requires Windows")
class DialogPrewarmTests(unittest.TestCase):
    def setUp(self):
        support.AllFloatingIntegrationTests.setUp(self)

    def tearDown(self):
        support.AllFloatingIntegrationTests.tearDown(self)

    tick = support.AllFloatingIntegrationTests.tick
    wait_for = support.AllFloatingIntegrationTests.wait_for
    create = support.AllFloatingIntegrationTests.create

    def test_reused_modal_close_restores_keyboard_focus_and_releases_input_tokens(self):
        from WinUx.platform.dialog_focus import owner_has_keyboard_focus
        from DearUIQt.input_gate import native_modal_input_active
        self.view._dialog_prewarm_pool = DialogPrewarmPool(capacity=1, reusable=True)
        pool = self.view._dialog_prewarm_pool
        self.wait_for(lambda: len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        identity = None
        for _ in range(3):
            dialog = self.create(lambda: dialogs.BlockingDialog(
                self.view, "Focus lifecycle", "Close this dialog", kind="confirm"))
            current = (dialog._process.pid, dialog._hwnd)
            if identity is not None:
                self.assertEqual(current, identity)
            identity = current
            support.AllFloatingIntegrationTests.activate(self, dialog)
            self.assertFalse(self.user32.IsWindowEnabled(self.owner))
            self.assertTrue(native_modal_input_active())
            self.user32.PostMessageW(dialog._hwnd, 0x0010, 0, 0)
            self.wait_for(lambda: dialog._host_returned)
            self.assertTrue(self.user32.IsWindowEnabled(self.owner))
            self.assertFalse(native_modal_input_active())
            self.wait_for(lambda: int(self.user32.GetForegroundWindow() or 0) == self.owner
                          and owner_has_keyboard_focus(self.owner))

    def prepare_pool(self):
        self.view._dialog_prewarm_pool = DialogPrewarmPool(capacity=2)
        self.wait_for(lambda: sum(worker.ready.is_set() and not worker.closed
            for worker in self.view._dialog_prewarm_pool._workers) == 2)
        self.assertTrue(all(worker.hwnd and cloaked(worker.hwnd)
                            for worker in self.view._dialog_prewarm_pool._workers))
        for worker in self.view._dialog_prewarm_pool._workers:
            ex_style = self.user32.GetWindowLongPtrW(worker.hwnd, -20)
            self.assertTrue(ex_style & 0x80, "Idle worker must be a shell-hidden tool window")
            self.assertFalse(ex_style & 0x40000, "Idle worker must not force a taskbar button")

    def test_exit_warning_uses_ready_worker_and_is_faster_than_cold_start(self):
        cold = self.create(lambda: dialogs.BlockingDialog(self.view, "Confirm Close App", "Exit WinUx?", kind="confirm"))
        cold_ms = cold._open_elapsed_ms
        cold.destroy()
        self.wait_for(lambda: cold._process.poll() is not None, timeout=8)
        self.prepare_pool()
        received = []
        warm = self.create(lambda: dialogs.BlockingDialog(self.view, "Confirm Close App", "Exit WinUx?", kind="confirm", on_result=received.append))
        self.assertTrue(warm._from_prewarm)
        ex_style = self.user32.GetWindowLongPtrW(warm._hwnd, -20)
        self.assertFalse(ex_style & (0x80 | 0x40000),
                         "Claimed worker must regain a normal owned dialog caption")
        print("\nExit-warning click-to-ready: cold={:.1f}ms warm={:.1f}ms".format(cold_ms, warm._open_elapsed_ms))
        print("Warm startup phases (ms):", warm._startup_timings)
        print("Warm startup frames:", warm._startup_frames)
        self.assertLess(warm._open_elapsed_ms, cold_ms * .7)
        self.assertLess(warm._open_elapsed_ms, 500)
        self.assertFalse(any(frame['stage'] in ('prepared-handshake', 'commit-handshake')
                             for frame in warm._startup_frames))
        published = next(event for event in warm._startup_layout if event["stage"] == "published")
        left, top, right, bottom = published["rect"]
        self.assertEqual((left, top), centered_position(window_rect(self.owner), (right-left, bottom-top), work_area(self.owner)))
        self.user32.PostMessageW(warm._hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: received == [False])
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))

    def test_workers_are_usable_for_different_dialog_types_and_replenished(self):
        self.prepare_pool()
        job = self.create(lambda: dialogs.JobManagerDialog(self.view, [PurePosixPath("/scratch/job.inp")], lambda *a: None, lambda *a: None))
        bookmarks = self.create(lambda: dialogs.BookmarksDialog(self.view, [], lambda *a: None, lambda *a: None, lambda *a: None))
        self.assertTrue(job._from_prewarm)
        self.assertTrue(bookmarks._from_prewarm)
        self.assertNotEqual(job._process.pid, bookmarks._process.pid)
        job.destroy()
        bookmarks.destroy()
        self.wait_for(lambda: sum(worker.ready.is_set() and not worker.closed
            for worker in self.view._dialog_prewarm_pool._workers) == 2)

    def test_digitizer_host_prewarm_serves_selectors_and_remains_bounded(self):
        from pathlib import Path
        from types import SimpleNamespace
        from WinUx.dialogs.floating_runtime import FloatingDialogRuntime
        from WinUx.dialogs.floating_adapters import LocalFileDialog

        cold = self.create(lambda: LocalFileDialog(self.view, str(Path.cwd()), lambda *args: None))
        cold_ms = cold._open_elapsed_ms
        cold.destroy()
        self.wait_for(lambda: cold._process.poll() is not None, timeout=8)
        runtime = object.__new__(FloatingDialogRuntime)
        runtime.initial = {"kind": "plotdigitizer"}
        runtime.form = SimpleNamespace(winfo_exists=lambda: True)
        runtime.view = self.view
        runtime._start_selector_prewarm()
        pool = self.view._dialog_prewarm_pool
        self.assertEqual(pool.capacity, 1)
        self.wait_for(lambda: len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        warm = self.create(lambda: LocalFileDialog(self.view, str(Path.cwd()), lambda *args: None))
        self.assertTrue(warm._from_prewarm)
        self.assertTrue(warm._reuse_host)
        print("\nFile-selector click-to-ready: cold={:.1f}ms warm={:.1f}ms".format(
            cold_ms, warm._open_elapsed_ms))
        self.assertLess(warm._open_elapsed_ms, cold_ms)
        host_pid, host_hwnd = warm._process.pid, warm._hwnd
        old_lease = warm._lease
        warm.destroy()
        self.assertTrue(warm._closed)
        self.wait_for(lambda: len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        self.assertIsNone(warm._process.poll())
        reopened = self.create(lambda: dialogs.LocalFolderDialog(self.view, str(Path.cwd()), lambda *args: None))
        self.assertTrue(reopened._reuse_host)
        self.assertEqual(reopened._process.pid, host_pid)
        self.assertEqual(reopened._hwnd, host_hwnd)
        self.assertNotEqual(reopened._lease, old_lease)
        # A late close from the old controller must not close the new form.
        from WinUx.services.floating_protocol import encode_message
        reopened._connection.sendall(encode_message({"command": "close", "lease": old_lease}))
        for _ in range(10):
            self.tick()
        self.assertTrue(reopened.winfo_exists())
        self.assertIsNone(reopened._process.poll())
        print("Reused folder host click-to-ready: {:.1f}ms (same PID/HWND)".format(reopened._open_elapsed_ms))
        self.user32.PostMessageW(reopened._hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: reopened._closed and len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        item_count = reopened._idle_item_count
        for _ in range(3):
            repeated = self.create(lambda: dialogs.LocalFolderDialog(self.view, str(Path.cwd()), lambda *args: None))
            self.assertEqual(repeated._process.pid, host_pid)
            repeated.destroy()
            self.wait_for(lambda: repeated._host_returned)
            self.assertEqual(repeated._idle_item_count, item_count,
                             "Repeated selector leases must not accumulate DPG resources")
        idle = pool._workers[0]
        self.assertGreaterEqual(idle.reuse_count, 5)
        pool.close()
        self.wait_for(lambda: idle.process.poll() is not None, timeout=8)

    def test_shell_hidden_worker_becomes_a_normal_owned_plot_digitizer(self):
        from WinUx.plotdigitizer.integration import open_plot_digitizer
        self.prepare_pool()
        idle_hwnds = {worker.hwnd for worker in self.view._dialog_prewarm_pool._workers}
        digitizer = self.create(lambda: open_plot_digitizer(self.view))
        self.assertTrue(digitizer._from_prewarm)
        self.assertIn(digitizer._hwnd, idle_hwnds)
        self.assertEqual(self.user32.GetWindowLongPtrW(digitizer._hwnd, -8), self.owner)
        self.assertFalse(self.user32.GetWindowLongPtrW(digitizer._hwnd, -20) & (0x80 | 0x40000))
        self.assertTrue(self.user32.IsWindowVisible(digitizer._hwnd))
        self.assertFalse(cloaked(digitizer._hwnd))
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))
        style = self.user32.GetWindowLongPtrW(digitizer._hwnd, -16)
        self.assertEqual(style & 0x00070000, 0x00070000)  # resize + minimize + maximize
        self.user32.ShowWindow.argtypes = [support.wintypes.HWND, support.ctypes.c_int]
        self.user32.IsIconic.argtypes = [support.wintypes.HWND]
        self.user32.IsIconic.restype = support.wintypes.BOOL
        self.user32.IsZoomed.argtypes = [support.wintypes.HWND]
        self.user32.IsZoomed.restype = support.wintypes.BOOL
        self.user32.ShowWindow(digitizer._hwnd, 3)  # SW_SHOWMAXIMIZED
        self.wait_for(lambda: bool(self.user32.IsZoomed(digitizer._hwnd)))
        self.user32.ShowWindow(digitizer._hwnd, 6)  # SW_MINIMIZE
        self.wait_for(lambda: bool(self.user32.IsIconic(digitizer._hwnd)))
        digitizer.show()
        self.wait_for(lambda: not self.user32.IsIconic(digitizer._hwnd))
        self.user32.ShowWindow(digitizer._hwnd, 9)  # SW_RESTORE
        self.wait_for(lambda: not self.user32.IsZoomed(digitizer._hwnd))
        digitizer.destroy()
        self.wait_for(lambda: digitizer._process.poll() is not None, timeout=8)

    def test_reusable_host_switches_between_form_types_and_reports_each_result_once(self):
        self.view._dialog_prewarm_pool = DialogPrewarmPool(capacity=1, reusable=True)
        pool = self.view._dialog_prewarm_pool
        self.wait_for(lambda: len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        results = []
        first = self.create(lambda: dialogs.BlockingDialog(
            self.view, "First confirmation", "First payload", kind="confirm", on_result=results.append))
        pid, hwnd = first._process.pid, first._hwnd
        self.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: first._host_returned and results == [False])
        second = self.create(lambda: dialogs.BookmarksDialog(
            self.view, [], lambda *args: None, lambda *args: None, lambda *args: None))
        self.assertEqual((second._process.pid, second._hwnd), (pid, hwnd))
        second.destroy()
        self.wait_for(lambda: second._host_returned)
        third = self.create(lambda: dialogs.BlockingDialog(
            self.view, "Another confirmation", "Different payload", kind="confirm", on_result=results.append))
        self.assertEqual((third._process.pid, third._hwnd), (pid, hwnd))
        self.assertFalse(third.result["done"])
        self.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: third._host_returned and results == [False, False])
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))
    def test_source_changed_workers_are_retired_before_plot_digitizer_imports_new_ui(self):
        from WinUx.plotdigitizer.integration import open_plot_digitizer
        self.prepare_pool()
        old_workers = list(self.view._dialog_prewarm_pool._workers)
        for worker in old_workers:
            worker.source_signature = (("ui/__init__.py", 0, 0),)
        digitizer = self.create(lambda: open_plot_digitizer(self.view))
        self.assertFalse(digitizer._from_prewarm)
        self.assertTrue(all(worker.closed for worker in old_workers))
        self.wait_for(lambda: all(worker.process.poll() is not None for worker in old_workers), timeout=8)
        self.assertTrue(digitizer._ready)
        self.assertIsNone(digitizer._process.poll())
        digitizer.destroy()
        self.wait_for(lambda: digitizer._process.poll() is not None, timeout=8)

    def test_legacy_parent_cannot_disable_plot_digitizer_window_controls_in_a_warm_worker(self):
        from WinUx.dialogs.floating_dialog import FloatingDialogController
        self.prepare_pool()
        digitizer = self.create(lambda: FloatingDialogController(
            self.view, "plotdigitizer", "Plot Digitizer", resizable=False,
            allow_minimize=False, allow_maximize=False))
        self.assertTrue(digitizer._from_prewarm)
        self.assertEqual(self.user32.GetWindowLongPtrW(digitizer._hwnd, -16) & 0x00070000, 0x00070000)
        self.assertFalse(self.user32.GetWindowLongPtrW(digitizer._hwnd, -20) & 0x80)
        digitizer.destroy()
        self.wait_for(lambda: digitizer._process.poll() is not None, timeout=8)

    def test_settings_and_login_use_the_fast_prepared_path(self):
        self.prepare_pool()
        for title, constructor in (
                ('Settings', lambda: dialogs.SettingsDialog(self.view)),
                ('Login', lambda: dialogs.LoginDialog(self.view, lambda *args: None))):
            instance = self.create(constructor)
            self.assertTrue(instance._from_prewarm)
            self.assertLess(instance._open_elapsed_ms, 500)
            self.assertFalse(any(frame['stage'] in ('prepared-handshake', 'commit-handshake')
                                 for frame in instance._startup_frames))
            print('\n{} warm click-to-ready: {:.1f}ms'.format(title, instance._open_elapsed_ms))
            instance.destroy()
            self.wait_for(lambda: instance._process.poll() is not None, timeout=8)

    def test_reusable_login_and_odb_forms_release_their_resources(self):
        from WinUx.dialogs.floating_dialog import FloatingDialogController
        self.view._dialog_prewarm_pool = DialogPrewarmPool(capacity=1, reusable=True)
        pool = self.view._dialog_prewarm_pool
        self.wait_for(lambda: len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        pid = None
        for kind in ("login", "odb_check"):
            counts = []
            for _ in range(3):
                instance = self.create(lambda: FloatingDialogController(
                    self.view, kind, "Reusable " + kind,
                    payload={"initial": {"host": "example.invalid", "username": "test", "port": "22"}},
                    modal=True))
                self.assertTrue(instance._reuse_host)
                if pid is None:
                    pid = instance._process.pid
                self.assertEqual(instance._process.pid, pid)
                self.user32.PostMessageW(instance._hwnd, 0x0010, 0, 0)
                self.wait_for(lambda: instance._host_returned)
                counts.append(instance._idle_item_count)
                self.assertTrue(self.user32.IsWindowEnabled(self.owner))
            self.assertEqual(len(set(counts)), 1, (kind, counts))

    def test_form_without_reuse_capability_retires_host_without_waiting_for_idle_ack(self):
        from WinUx.dialogs.floating_dialog import FloatingDialogController
        self.view._dialog_prewarm_pool = DialogPrewarmPool(capacity=1, reusable=True)
        pool = self.view._dialog_prewarm_pool
        self.wait_for(lambda: len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        instance = self.create(lambda: FloatingDialogController(
            self.view, "plotdigitizer", "Plot Digitizer", resizable=False,
            allow_minimize=False, allow_maximize=False))
        self.assertTrue(instance._from_prewarm)
        self.assertFalse(instance._reuse_host)
        instance.destroy()
        self.wait_for(lambda: instance._process.poll() is not None, timeout=8)
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))
        self.wait_for(lambda: len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        self.assertNotEqual(pool._workers[0].process.pid, instance._process.pid)
        self.assertFalse(pool._leased)

    def test_completion_callback_opens_next_dialog_on_the_returned_host(self):
        self.view._dialog_prewarm_pool = DialogPrewarmPool(capacity=1, reusable=True)
        pool = self.view._dialog_prewarm_pool
        self.wait_for(lambda: len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        following, finished = [], []

        def on_result(value):
            next_dialog = dialogs.BlockingDialog(
                self.view, "Next dialog", "Next payload", kind="confirm", owner_hwnd=self.owner)
            self.instances.append(next_dialog)
            following.append(next_dialog)

        first = self.create(lambda: dialogs.BlockingDialog(
            self.view, "First dialog", "First payload", kind="confirm", on_result=on_result))
        first.finished.connect(lambda code: finished.append((
            code, bool(self.user32.IsWindowEnabled(self.owner)),
            len(pool._workers) == 1 and pool._workers[0].ready.is_set())))
        pid, hwnd = first._process.pid, first._hwnd
        self.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: bool(following) and following[0]._ready)
        second = following[0]
        self.assertEqual(finished, [(first.Rejected, True, True)])
        self.assertTrue(second._from_reused_host)
        self.assertEqual((second._process.pid, second._hwnd), (pid, hwnd))
        second.done(second.Accepted, "")
        self.wait_for(lambda: second._host_returned)
        self.assertEqual(second.dialogResult(), second.Accepted)
        self.assertEqual(len(following), 1)
        accepted = []
        third = self.create(lambda: dialogs.BlockingDialog(
            self.view, "Validated acceptance", "Accept through the form", kind="confirm"))
        third.accepted.connect(lambda: accepted.append(True))
        self.assertTrue(third.accept())
        self.wait_for(lambda: third._host_returned and bool(accepted))
        self.assertEqual(third.result["value"], True)
        self.assertEqual(accepted, [True])
        self.assertEqual((third._process.pid, third._hwnd), (pid, hwnd))

    def test_fast_repeated_file_dialog_preserves_clip_rects_and_hidden_host_contract(self):
        from pathlib import Path
        from WinUx.dialogs.floating_adapters import LocalFileDialog
        self.view._dialog_prewarm_pool = DialogPrewarmPool(capacity=1, reusable=True)
        pool = self.view._dialog_prewarm_pool
        self.wait_for(lambda: len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        bounds = None
        for index in range(3):
            dialog = self.create(lambda: LocalFileDialog(self.view, str(Path.cwd()), lambda *args: None))
            width, height = dialog._client_layout["client"]
            widgets = dialog._client_layout["widgets"]
            for name, (left, top, right, bottom) in widgets.items():
                self.assertGreater(right, left, name)
                self.assertGreater(bottom, top, name)
                self.assertGreaterEqual(left, 0, name)
                self.assertGreaterEqual(top, 0, name)
                self.assertLessEqual(right, width + 1, name)
                self.assertLessEqual(bottom, height + 1, name)
            if index:
                self.assertEqual(widgets, bounds)
                self.assertEqual(len(dialog._startup_frames), 2)
                self.assertNotIn("prepared-handshake", dialog._startup_timings)
            bounds = widgets
            self.assertEqual(dialog._initial_reveal_count, 1)
            dialog.destroy()
            self.wait_for(lambda: dialog._host_returned)
            self.assertFalse(self.user32.IsWindowVisible(dialog._hwnd))
            self.assertTrue(cloaked(dialog._hwnd))
            self.assertEqual(self.user32.GetWindowLongPtrW(dialog._hwnd, -8), 0)

    def test_schedule_timer_is_stopped_before_returning_host_and_reopen_has_fresh_provider(self):
        self.view._dialog_prewarm_pool = DialogPrewarmPool(capacity=1, reusable=True)
        pool = self.view._dialog_prewarm_pool
        self.wait_for(lambda: len(pool._workers) == 1 and pool._workers[0].ready.is_set())
        calls = [0, 0]

        def provider(index):
            calls[index] += 1
            return []

        first = self.create(lambda: dialogs.JobScheduleDialog(
            self.view, lambda: provider(0), lambda *args: None))
        self.assertTrue(first._reuse_host)
        self.wait_for(lambda: calls[0] >= 3, timeout=5)
        pid, hwnd = first._process.pid, first._hwnd
        first.destroy()
        self.wait_for(lambda: first._host_returned)
        previous_count = calls[0]
        second = self.create(lambda: dialogs.JobScheduleDialog(
            self.view, lambda: provider(1), lambda *args: None))
        self.assertEqual((second._process.pid, second._hwnd), (pid, hwnd))
        self.wait_for(lambda: calls[1] >= 3, timeout=5)
        self.assertEqual(calls[0], previous_count, "old lease timer/provider must not fire")
        second.destroy()
        self.wait_for(lambda: second._host_returned)
        self.assertEqual(second._idle_item_count, first._idle_item_count)

    def test_pool_claim_never_waits_on_preparation_lock_and_close_retires_idle_workers(self):
        self.prepare_pool()
        pool = self.view._dialog_prewarm_pool
        workers = list(pool._workers)
        pool._lock.acquire()
        try:
            started = time.perf_counter()
            self.assertIsNone(pool.claim())
            self.assertLess(time.perf_counter()-started, .05)
        finally:
            pool._lock.release()
        pool.close()
        self.wait_for(lambda: all(worker.process.poll() is not None for worker in workers), timeout=8)
        self.assertIsNone(pool.claim())


def test_source_signature_tracks_exports_and_modules_but_ignores_generated_files(tmp_path):
    package = tmp_path / "WinUx"
    shared = package / "ui"
    shared.mkdir(parents=True)
    exports = shared / "__init__.py"
    exports.write_text("from .workspace import ToolWorkspace\n", encoding="utf-8")
    before = runtime_source_signature(package)
    exports.write_text("from .workspace import ToolWorkspace, style_tool_surface\n", encoding="utf-8")
    after_export = runtime_source_signature(package)
    assert after_export != before
    workspace = shared / "workspace.py"
    workspace.write_text("def style_tool_surface(item): pass\n", encoding="utf-8")
    after_module = runtime_source_signature(package)
    assert after_module != after_export
    cache = shared / "__pycache__"
    cache.mkdir()
    (cache / "workspace.pyc").write_bytes(b"generated bytecode")
    resources = package / "Resources"
    resources.mkdir()
    (resources / "icon.png").write_bytes(b"resource pixels")
    assert runtime_source_signature(package) == after_module
    workspace.unlink()
    assert runtime_source_signature(package) != after_module
    assert runtime_source_signature(tmp_path / "missing") is None


if __name__ == "__main__":
    unittest.main()
