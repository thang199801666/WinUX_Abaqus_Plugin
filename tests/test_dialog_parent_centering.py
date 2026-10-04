"""Regression tests for stable Qt-like native dialog parenting/centering."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from WinUx.platform.native_dialog_host import (
    NativeDialogController, resize_native_dialog_to_minimum,
)


class _DummyWindow:
    def __init__(self):
        self.idle = []
        self.updated = 0

    def update_idletasks(self):
        self.updated += 1

    def after_idle(self, callback):
        self.idle.append(callback)
        return "idle-1"

    def winfo_width(self):
        return 420

    def winfo_height(self):
        return 240


class _SizingWindow:
    def __init__(self, minimum=(320, 180), requested=(460, 250)):
        self._minimum = tuple(minimum)
        self._requested = tuple(requested)
        self.geometry_calls = []

    def update_idletasks(self):
        pass

    def minsize(self, *args):
        if args:
            self._minimum = (int(args[0]), int(args[1]))
        return self._minimum

    def winfo_reqwidth(self):
        return self._requested[0]

    def winfo_reqheight(self):
        return self._requested[1]

    def winfo_x(self):
        return 100

    def winfo_y(self):
        return 80

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def geometry(self, value):
        self.geometry_calls.append(str(value))


class NativeDialogMinimumLaunchTests(unittest.TestCase):
    def test_minimum_launch_size_uses_layout_size_hint(self):
        window = _SizingWindow(minimum=(320, 180), requested=(460, 250))
        with patch(
            "WinUx.platform.native_dialog_host._monitor_work_area",
            return_value=(0, 0, 1920, 1040),
        ):
            size = resize_native_dialog_to_minimum(window, owner_hwnd=111)

        self.assertEqual(size, (460, 250))
        self.assertEqual(window.minsize(), (460, 250))
        self.assertTrue(window.geometry_calls[-1].startswith("460x250+"))

    def test_controller_defaults_to_minimum_size_launch(self):
        controller = NativeDialogController.__new__(NativeDialogController)
        self.assertTrue(controller._open_at_minimum_size_enabled())



class NativeDialogStableParentTests(unittest.TestCase):
    def _controller(self, parent=111, owner=999):
        controller = NativeDialogController.__new__(NativeDialogController)
        controller._parent_hwnd = parent
        controller._owner_hwnd = owner
        controller._owner_acquired = False
        controller._window = None
        return controller

    def test_live_parent_is_never_re_resolved_from_foreground(self):
        controller = self._controller(parent=111)
        window = _DummyWindow()
        with patch(
            "WinUx.platform.native_dialog_host._is_native_window",
            return_value=True,
        ), patch(
            "WinUx.platform.native_dialog_host.resolve_native_dialog_parent"
        ) as resolver, patch(
            "WinUx.platform.native_dialog_host.attach_native_owner"
        ) as attach:
            self.assertEqual(controller._refresh_parent_for_show(window), 111)
            resolver.assert_not_called()
            attach.assert_not_called()

    def test_destroyed_parent_falls_back_to_main_owner(self):
        controller = self._controller(parent=111, owner=999)
        window = _DummyWindow()
        with patch(
            "WinUx.platform.native_dialog_host._is_native_window",
            return_value=False,
        ), patch(
            "WinUx.platform.native_dialog_host.attach_native_owner"
        ) as attach:
            self.assertEqual(controller._refresh_parent_for_show(window), 999)
            self.assertEqual(controller._parent_hwnd, 999)
            attach.assert_called_once_with(window, 999)

    def test_center_prefers_native_frame_of_fixed_parent(self):
        controller = self._controller(parent=111)
        window = _DummyWindow()
        with patch.object(
            controller, "_center_on_parent_enabled", return_value=True,
        ), patch.object(
            controller, "_refresh_parent_for_show", return_value=111,
        ), patch(
            "WinUx.platform.native_dialog_host.center_native_dialog_over_owner",
            return_value=True,
        ) as native_center, patch(
            "WinUx.platform.native_dialog_host.center_over_owner"
        ) as tk_center:
            self.assertTrue(controller._center_window_on_parent(window))
            native_center.assert_called_once_with(window, 111)
            tk_center.assert_not_called()

    def test_after_map_center_is_scheduled_on_idle(self):
        controller = self._controller(parent=111)
        window = _DummyWindow()
        with patch.object(
            controller, "_center_on_parent_enabled", return_value=True,
        ), patch.object(controller, "_center_window_on_parent") as center:
            controller._center_window_after_map(window)
            self.assertEqual(len(window.idle), 1)
            center.assert_not_called()
            window.idle[0]()
            center.assert_called_once_with(window)


if __name__ == "__main__":
    unittest.main()
