"""Regression and Win32 integration tests for process-isolated DPG dialogs.

Main-window dialogs (including SSH Login) are in-process Qt-like QDialogs by
default (:mod:`tests.test_native_dialogs` asserts that split).  These tests keep
the guarantees of the still-supported explicit process-isolated hosting in
``WinUx.dialogs.floating_adapters`` + ``WinUx/ui/hosting/floating_dialog.py``:
the child viewport owns a real top-level HWND that can leave the main window's
rectangle, only the owner is disabled while a modal dialog is open, and closing
always restores the owner and balances the modal/input gates exactly once.
"""

from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import queue
import time
import unittest
from unittest.mock import patch, Mock

import dearpygui.dearpygui as dpg
from WinUx.dialogs.floating_adapters import BlockingDialog
from WinUx.dialogs.floating_dialog import FloatingDialogController, floating_dialog_command
from WinUx.dialogs.login_form import LoginForm


class View:
    def __init__(self):
        self.queue = queue.Queue()
        self.errors = []

    def after(self, delay, callback, *args):
        self.queue.put((callback, args))

    def drain(self):
        for _ in range(100):
            try:
                callback, args = self.queue.get_nowait()
            except queue.Empty:
                break
            callback(*args)

    def show_error(self, *args):
        self.errors.append(args)


class LoginFormTests(unittest.TestCase):
    def test_history_is_in_the_editable_field_not_two_extra_rows(self):
        dpg.create_context()
        try:
            view = View()
            form = LoginForm(view, lambda *args: None, initial={
                "host": "cluster", "hosts": ["cluster", "other"],
                "username": "user", "usernames": ["user", "other-user"], "port": "22"})
            self.assertEqual(len(form._combos), 2)
            self.assertEqual(form.host, form.host_combo.input)
            self.assertEqual(form.username, form.username_combo.input)
            self.assertEqual(form.host_combo.items, ["cluster", "other"])
            self.assertEqual(dpg.get_value(form.host), "cluster")
            self.assertFalse(dpg.get_item_configuration(form.host)["on_enter"])
            with patch.object(form.preferences, "password_for", return_value="saved"):
                form.username_combo.set_current_text("other-user", emit=True)
            self.assertEqual(dpg.get_value(form.password), "saved")
            form.destroy()
            view.drain()
        finally:
            dpg.destroy_context()


class FloatingLifecycleTests(unittest.TestCase):
    def controller(self):
        controller = object.__new__(FloatingDialogController)
        controller.view = View()
        controller.modal = True
        controller._closed = controller._finalized = controller._ready = False
        controller._owner_acquired = False
        controller._child_pid = None
        controller._close_return_focus = False
        controller._reuse_host = False
        controller._visible = True
        controller._owner_hwnd = 101
        controller._hwnd = None
        controller._startup_timer = None
        controller._connection = None
        controller._host_lease = None
        controller._startup_generation = 0
        controller._listener = Mock()
        controller.post = lambda *args, **kwargs: True
        return controller

    def test_ready_then_close_balances_owner_and_input_gate_exactly_once(self):
        controller = self.controller()
        with patch("WinUx.dialogs.floating_dialog._acquire_modal_owner", return_value=True) as acquire, \
             patch("WinUx.dialogs.floating_dialog._release_modal_owner") as release, \
             patch("WinUx.dialogs.floating_dialog.register_native_pointer_surface") as register, \
             patch("WinUx.dialogs.floating_dialog.unregister_native_pointer_surface") as unregister, \
             patch("WinUx.dialogs.floating_dialog.release_native_modal_input") as input_release:
            controller._deliver_event({"event": "ready", "hwnd": 202})
            controller._deliver_event({"event": "closed"})
            controller._finish()
            acquire.assert_called_once_with(101)
            release.assert_called_once_with(101, restore_focus=False)
            register.assert_called_once_with(202)
            unregister.assert_called_once_with(202)
            input_release.assert_called_once_with(controller)

    def test_late_submit_after_close_cannot_start_an_ssh_connection(self):
        controller = self.controller()
        received = []
        controller.handle_event = lambda *args: received.append(args)
        controller._closed = True
        controller._deliver_event({"event": "submit", "values": {"host": "late"}})
        self.assertEqual(received, [])

    def test_parent_finish_captures_focus_from_its_owned_child(self):
        parent = self.controller()
        parent._hwnd = 202
        child = self.controller()
        child._hwnd = 303
        child.destroy = Mock()
        parent._owned_dialogs = [child]
        parent._queue_owner_focus = Mock()
        with patch("WinUx.dialogs.floating_dialog._foreground_hwnd", return_value=303), \
             patch("WinUx.dialogs.floating_dialog._owner_has_keyboard_focus", return_value=False), \
             patch("WinUx.dialogs.floating_dialog.unregister_native_pointer_surface"), \
             patch("WinUx.dialogs.floating_dialog.release_native_modal_input"):
            parent._finish()
        parent._queue_owner_focus.assert_called_once_with(force=True)
        child.destroy.assert_called_once_with()

    def test_child_command_prepares_abaqus_python_and_does_not_launch_smapython_directly(self):
        with patch.dict(os.environ, {"WINUX_ABAQUS_COMMAND": "abaqus"}):
            command = floating_dialog_command("C:/path with spaces/dialog.py")
        text = " ".join(command)
        self.assertIn("abaqus", text)
        self.assertIn("python", text)
        self.assertNotIn("SMAPython.exe", text)


@unittest.skipUnless(os.name == "nt", "Native floating-window integration requires Windows")
class FloatingViewportIntegrationTests(unittest.TestCase):
    def test_floating_dialog_has_owned_top_level_hwnd_and_moves_outside_main_window(self):
        # A real test owner, without starting another DPG context or Abaqus/CAE.
        # Login joined the in-process dialog set; the explicit process-isolated
        # hosting path is exercised through its BlockingDialog adapter, which
        # follows the identical controller/runtime/native-host contracts.
        user32 = ctypes.windll.user32
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        user32.IsWindowEnabled.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                       wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        def pump_owner():
            message = wintypes.MSG()
            while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        owner = user32.CreateWindowExW(0, "STATIC", "WinUx Floating Test Owner",
                                      0x10cf0000, 600, 300, 240, 180, None, None, None, None)
        self.assertTrue(owner)
        dialog = None
        view = View()
        try:
            dialog = BlockingDialog(view, "Floating Test",
                                    "Owned top-level without process-window lookup.",
                                    owner_hwnd=int(owner), on_result=lambda *args: None)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not dialog._ready and dialog.winfo_exists():
                # Owned-window style changes send cross-thread Win32 messages.
                # The real WinUx render loop pumps them; this test owner must too.
                pump_owner()
                view.drain()
                time.sleep(.05)
            view.drain()
            self.assertFalse(view.errors, str(view.errors))
            self.assertTrue(dialog._ready, "Floating viewport never completed the handshake")
            self.assertTrue(dialog._hwnd)
            # The compact message client must fit its dedicated viewport and
            # only the pinned footer may reach it.
            client = dialog._client_layout["client"]
            self.assertGreater(client[0], 0)
            self.assertGreater(client[1], 0)
            footer = dialog._client_layout["footer"]
            self.assertLessEqual(footer[3], client[1], "Footer is clipped vertically")
            getter = user32.GetWindowLongPtrW
            getter.argtypes = [wintypes.HWND, ctypes.c_int]
            getter.restype = ctypes.c_ssize_t
            self.assertEqual(getter(dialog._hwnd, -8), int(owner), "Must be owned, not parented as WS_CHILD")
            self.assertFalse(getter(dialog._hwnd, -16) & 0x40000000, "Floating dialog must not use WS_CHILD")
            self.assertFalse(user32.IsWindowEnabled(owner), "Only main owner is disabled during a modal dialog")
            self.assertTrue(user32.IsWindowEnabled(dialog._hwnd), "Dialog must remain interactive")
            user32.SetWindowPos(dialog._hwnd, None, 80, 100, 0, 0, 0x0001 | 0x0004)
            time.sleep(.15)
            rectangle = wintypes.RECT()
            user32.GetWindowRect(dialog._hwnd, ctypes.byref(rectangle))
            self.assertEqual(rectangle.left, 80)
            self.assertLess(rectangle.left, 600, "Window can leave its owner's rectangle")
            dialog.destroy()
            self.assertTrue(user32.IsWindowEnabled(owner), "Close must restore the owner")
            dialog._process.wait(timeout=8)
        finally:
            if dialog:
                dialog.destroy()
            user32.DestroyWindow(owner)


if __name__ == "__main__":
    unittest.main()
