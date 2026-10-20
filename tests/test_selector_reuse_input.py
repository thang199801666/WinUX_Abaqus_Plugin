"""Real GLFW row clicks/selection after Esc across recycled selector leases."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import tempfile
import time
import unittest
from unittest.mock import patch

from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


@unittest.skipUnless(os.name == "nt", "Requires native GLFW/Win32 input")
class SelectorReuseInputTests(unittest.TestCase):
    def test_escape_then_click_file_and_folder_in_reused_context(self):
        self._exercise_reused_selector(require_foreground=True)

    def test_stale_imgui_pointer_recovery_in_reused_context(self):
        # Deterministic recovery-path coverage, not a physical-input claim.
        self._exercise_reused_selector(require_foreground=False)

    def _exercise_reused_selector(self, require_foreground):
        import dearpygui.dearpygui as dpg

        commands = queue.Queue()
        events = []
        errors = []
        user32 = ctypes.windll.user32
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        user32.GetFocus.restype = wintypes.HWND
        old_cursor = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(old_cursor))
        prepared = None
        runtime = None

        class Connection:
            def sendall(self, data):
                message = json.loads(data.decode("utf-8"))
                events.append(message)
                replies = {"prepared": "publish", "staged": "publish_commit",
                           "closing": "owner_handoff_ready"}
                if message.get("event") in replies:
                    commands.put({"command": replies[message["event"]],
                                  "lease": message["lease"]})

        connection = Connection()
        # Keep the same IPC reader and DPG context across every lease, exactly
        # as the reusable host does. Only native messages inject UI input.
        messages = iter(commands.get, None)
        temporary_root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="winux-selector-reuse-", dir=temporary_root) as folder:
            root = Path(folder)
            (root / "Folder").mkdir()
            (root / "chart.csv").write_text("1,2\n")
            try:
                for cycle, operation in enumerate(("escape", "file", "folder", "escape", "file")):
                    kind = "local_folder" if operation == "folder" else "local_file"
                    initial = {"command": "init", "kind": kind, "title": "Selector reuse check",
                               "payload": {"initial": folder, "extensions": [".csv"]},
                               "width": 840, "height": 540, "owner_hwnd": 0,
                               "visible": True, "reuse_host": True, "lease": str(cycle)}
                    runtime = FloatingDialogRuntime(connection, messages, initial, prepared=prepared)
                    if not require_foreground:
                        original_pointer = runtime._browser_pointer_pressed

                        def pointer(event, point):
                            # Only simulate the foreground predicate for targeted
                            # native messages; retain real HWND, geometry and
                            # GLFW event/callback dispatch across recycled leases.
                            with patch.object(runtime.native, "is_foreground", return_value=True):
                                original_pointer(event, point)

                        runtime._browser_pointer_pressed = pointer
                    original_build = runtime._build
                    deadline = time.monotonic() + 5

                    def check(callback):
                        try:
                            callback()
                        except Exception as exc:
                            errors.append(exc)
                            runtime.form.destroy()

                    def drive():
                        form = runtime.form
                        if dpg.get_value(form.status) == "Loading...":
                            if time.monotonic() >= deadline:
                                raise AssertionError("Selector listing did not finish")
                            runtime.view.after(10, lambda: check(drive))
                            return
                        hwnd = runtime.native.hwnd
                        if operation == "escape":
                            user32.PostMessageW(hwnd, 0x0100, 27, 0x00010001)
                            user32.PostMessageW(hwnd, 0x0101, 27, 0xc0010001)
                            return
                        key = str(root / ("Folder" if operation == "folder" else "chart.csv"))
                        form.listbox.clearSelection()
                        dpg.set_value(form.folder_edit, "")
                        self.assertNotIn(key, form.listbox.selected)
                        row = form.listbox.items[key]
                        x, y = dpg.get_item_rect_min(row)
                        width, height = dpg.get_item_rect_size(row)
                        x, y = round(x + min(30, width / 2)), round(y + height / 2)
                        position = (y << 16) | (x & 0xffff)
                        point = wintypes.POINT(x, y)
                        self.assertTrue(user32.ClientToScreen(hwnd, ctypes.byref(point)))
                        user32.SetCursorPos(point.x, point.y)
                        user32.PostMessageW(hwnd, 0x0007, 0, 0)  # WM_SETFOCUS
                        user32.PostMessageW(hwnd, 0x0200, 0, position)  # WM_MOUSEMOVE
                        runtime.view.after(40, lambda: user32.PostMessageW(
                            hwnd, 0x0201, 1, position))  # WM_LBUTTONDOWN
                        runtime.view.after(80, lambda: user32.PostMessageW(
                            hwnd, 0x0202, 0, position))  # WM_LBUTTONUP

                        def selected():
                            self.assertIn(key, form.listbox.selected,
                                          "A visible reused selector ignored its row click")
                            form.accept()
                        runtime.view.after(160, lambda: check(selected))

                    def build_and_drive():
                        original_build()
                        if require_foreground and not runtime.native.is_foreground():
                            self.skipTest("Windows did not grant foreground for native row-input testing")
                        # Focus only this test's own UI-thread window. Targeted
                        # PostMessage input does not require stealing another
                        # application's foreground or attaching its input queue.
                        user32.SetActiveWindow(runtime.native.hwnd)
                        user32.SetFocus(runtime.native.hwnd)
                        if int(user32.GetFocus() or 0) != runtime.native.hwnd:
                            self.skipTest("Windows did not grant test-thread keyboard focus")
                        runtime.view.after(20, lambda: check(drive))
                        # Keep failures bounded even if Esc/input stops working.
                        def timeout():
                            if runtime.form.winfo_exists():
                                errors.append(AssertionError("Selector did not respond to input"))
                                runtime.form.destroy()
                        runtime.view.after(5000, timeout)

                    with patch.object(runtime, "_build", side_effect=build_and_drive):
                        runtime.run()
                    if errors:
                        raise errors[0]
                    result = next(message for message in reversed(events)
                                  if message.get("event") == "result" and message["lease"] == str(cycle))
                    expected = None if operation == "escape" else str(
                        root / ("Folder" if operation == "folder" else "chart.csv"))
                    self.assertEqual(result["value"], expected)
                    self.assertTrue(runtime.reusable)
                    prepared = runtime.prepared
            finally:
                user32.SetCursorPos(old_cursor.x, old_cursor.y)
                commands.put(None)
                if prepared is not None and runtime.reusable:
                    prepared.native.restore_close_handler()
                    dpg.destroy_context()


if __name__ == "__main__":
    unittest.main()
