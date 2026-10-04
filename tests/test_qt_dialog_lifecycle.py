"""Regression tests for the centralized Qt-like native dialog lifecycle."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from WinUx.platform.native_dialog_host import NativeDialogController


class _FocusTarget:
    def __init__(self, calls):
        self.calls = calls

    def focus_set(self):
        self.calls.append("target.focus_set")


class _FakeWindow:
    def __init__(self):
        self.calls = []
        self.target = _FocusTarget(self.calls)
        self._state = "normal"

    def deiconify(self):
        self.calls.append("deiconify")

    def lift(self):
        self.calls.append("lift")

    def focus_set(self):
        self.calls.append("focus_set")

    def focus_force(self):
        self.calls.append("focus_force")

    def grab_set(self):
        self.calls.append("grab_set")

    def grab_release(self):
        self.calls.append("grab_release")

    def withdraw(self):
        self.calls.append("withdraw")
        self._state = "withdrawn"

    def iconify(self):
        self.calls.append("iconify")
        self._state = "iconic"

    def state(self, value=None):
        if value is None:
            return self._state
        self.calls.append("state:" + str(value))
        self._state = str(value)
        return self._state

    def resizable(self):
        return True, True

    def after_idle(self, callback):
        self.calls.append("after_idle")
        callback()

    def qt_focus_target(self):
        return self.target

    def qt_after_focus(self):
        self.calls.append("qt_after_focus")

    def qt_after_show(self, command):
        self.calls.append("qt_after_show:" + str(command))

    def qt_after_hide(self):
        self.calls.append("qt_after_hide")


class QtDialogLifecycleTests(unittest.TestCase):
    def _controller(self, modal):
        controller = object.__new__(NativeDialogController)
        controller.modal = bool(modal)
        controller._closed = threading.Event()
        controller._owner_hwnd = 100
        controller._parent_hwnd = 100
        controller._modal_owner_hwnd = None
        controller._owner_acquired = False
        controller._window = None
        controller._geometry_after_id = None
        controller.restore_calls = 0
        controller.restore_owner_focus_async = (
            lambda delay=0: setattr(
                controller, "restore_calls", controller.restore_calls + 1))
        controller.restore_owner_foreground_async = (
            lambda delay=0: setattr(
                controller, "restore_calls", controller.restore_calls + 1))
        return controller

    def test_modal_show_uses_one_shared_qdialog_lifecycle(self):
        controller = self._controller(modal=True)
        window = _FakeWindow()
        acquired = []
        with patch(
            "WinUx.platform.native_dialog_host.resolve_native_dialog_parent",
            return_value=100,
        ), patch(
            "WinUx.platform.native_dialog_host._acquire_modal_owner",
            side_effect=lambda hwnd: acquired.append(hwnd) or True,
        ):
            self.assertTrue(controller._handle_window_lifecycle(window, "show"))

        self.assertEqual(acquired, [100])
        self.assertTrue(controller._owner_acquired)
        self.assertIn("deiconify", window.calls)
        self.assertIn("lift", window.calls)
        self.assertIn("grab_set", window.calls)
        self.assertIn("focus_set", window.calls)
        self.assertIn("target.focus_set", window.calls)
        self.assertIn("qt_after_focus", window.calls)
        self.assertIn("qt_after_show:show", window.calls)
        self.assertNotIn("focus_force", window.calls)


    def test_show_reasserts_dialog_hwnd_enabled_for_mouse_input(self):
        controller = self._controller(modal=True)
        window = _FakeWindow()
        checks = []
        with patch(
            "WinUx.platform.native_dialog_host.resolve_native_dialog_parent",
            return_value=100,
        ), patch(
            "WinUx.platform.native_dialog_host._acquire_modal_owner",
            return_value=True,
        ), patch(
            "WinUx.platform.native_dialog_host.ensure_native_dialog_interactive",
            side_effect=lambda target: checks.append(target) or True,
        ):
            self.assertTrue(controller._handle_window_lifecycle(window, "show"))
        self.assertGreaterEqual(len(checks), 2)
        self.assertTrue(all(target is window for target in checks))

    def test_activate_uses_explicit_focus_without_reacquiring_modal_owner(self):
        controller = self._controller(modal=True)
        controller._owner_acquired = True
        controller._modal_owner_hwnd = 100
        window = _FakeWindow()
        with patch(
            "WinUx.platform.native_dialog_host._acquire_modal_owner"
        ) as acquire:
            self.assertTrue(controller._handle_window_lifecycle(window, "activate"))
        acquire.assert_not_called()
        self.assertIn("focus_force", window.calls)
        self.assertIn("target.focus_set", window.calls)

    def test_hiding_modal_releases_grab_and_owner(self):
        controller = self._controller(modal=True)
        controller._owner_acquired = True
        controller._modal_owner_hwnd = 100
        window = _FakeWindow()
        released = []
        with patch(
            "WinUx.platform.native_dialog_host.is_native_window_foreground",
            return_value=True,
        ), patch(
            "WinUx.platform.native_dialog_host._release_modal_owner",
            side_effect=lambda hwnd, restore_focus=False: released.append(
                (hwnd, restore_focus)),
        ):
            self.assertTrue(controller._handle_window_lifecycle(window, "hide"))

        self.assertEqual(released, [(100, False)])
        self.assertFalse(controller._owner_acquired)
        self.assertIn("grab_release", window.calls)
        self.assertIn("withdraw", window.calls)
        self.assertIn("qt_after_hide", window.calls)
        self.assertEqual(controller.restore_calls, 1)

    def test_modeless_hide_does_not_steal_owner_focus_when_not_foreground(self):
        controller = self._controller(modal=False)
        window = _FakeWindow()
        with patch(
            "WinUx.platform.native_dialog_host.is_native_window_foreground",
            return_value=False,
        ):
            self.assertTrue(controller._handle_window_lifecycle(window, "hide"))
        self.assertNotIn("grab_release", window.calls)
        self.assertEqual(controller.restore_calls, 0)

    def test_maximize_restore_and_minimize_are_centralized(self):
        controller = self._controller(modal=False)
        window = _FakeWindow()
        saved = []
        scheduled = []
        controller._save_geometry_now = lambda: saved.append(True) or True
        controller._schedule_geometry_save = (
            lambda _event=None: scheduled.append(True))

        self.assertTrue(controller._handle_window_lifecycle(window, "maximize"))
        self.assertEqual(window.state(), "zoomed")
        self.assertEqual(len(scheduled), 1)

        self.assertTrue(
            controller._handle_window_lifecycle(window, "toggle_maximize"))
        self.assertEqual(window.state(), "normal")
        self.assertIn("focus_force", window.calls)

        self.assertTrue(controller._handle_window_lifecycle(window, "minimize"))
        self.assertEqual(window.state(), "iconic")
        self.assertEqual(saved, [True])

    def test_fixed_size_window_ignores_maximize_command(self):
        controller = self._controller(modal=False)
        window = _FakeWindow()
        window.resizable = lambda: (False, False)
        scheduled = []
        controller._schedule_geometry_save = (
            lambda _event=None: scheduled.append(True))
        self.assertTrue(controller._handle_window_lifecycle(window, "maximize"))
        self.assertEqual(window.state(), "normal")
        self.assertEqual(scheduled, [])

    def test_domain_command_is_not_consumed_by_lifecycle(self):
        controller = self._controller(modal=False)
        window = _FakeWindow()
        self.assertFalse(controller._handle_window_lifecycle(window, "refresh"))
        self.assertEqual(window.calls, [])


if __name__ == "__main__":
    unittest.main()
