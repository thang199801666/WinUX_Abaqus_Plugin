"""Real native dock clients, without starting SSH or an ODB worker."""
import os
import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import test_all_floating_dialogs as support
from WinUx.dialogs.native_dock_hosts import ConsoleDockHost, PlotDockHost
from WinUx.platform.dialog_focus import owner_has_keyboard_focus
from WinUx.runtime.terminal_buffer import TerminalBuffer


@unittest.skipUnless(os.name == "nt", "Native dock hosts require Windows")
class NativeDockTests(unittest.TestCase):
    setUp = support.AllFloatingIntegrationTests.setUp
    tearDown = support.AllFloatingIntegrationTests.tearDown
    tick = support.AllFloatingIntegrationTests.tick
    wait_for = support.AllFloatingIntegrationTests.wait_for
    create = support.AllFloatingIntegrationTests.create
    activate = support.AllFloatingIntegrationTests.activate

    def assert_native_modeless(self, host):
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))
        self.assertFalse(self.user32.GetWindowLongPtrW(host._hwnd, -16) & 0x40000000)
        self.user32.SetWindowPos(host._hwnd, None, 1000, 120, 0, 0, 0x0001 | 0x0004)
        from WinUx.platform.floating_viewport import window_rect
        self.assertEqual(window_rect(host._hwnd)[0], 1000)

    def test_console_native_dock_preserves_draft_and_history_and_close_returns_focus(self):
        buffer = TerminalBuffer()
        buffer.draft, buffer.cursor = "echo unfinished", 5
        buffer.history = ["pwd", "ls"]
        buffer.history_index = 2
        panel = SimpleNamespace(buffer=buffer, _clear_base=None, _clear_prompt="",
            output_callback=lambda: "connected\n$ ", command_callback=lambda value: True,
            interrupt_callback=lambda: True, error_callback=None)
        docked, closed = [], []
        host = self.create(lambda: ConsoleDockHost(self.view, panel, docked.append, closed.append))
        self.assert_native_modeless(host)
        self.activate(host)
        self.user32.PostMessageW(host._hwnd, 0x00a3, 2, 0)  # native title double-click
        self.wait_for(lambda: docked == [host])
        self.assertEqual((buffer.draft, buffer.cursor, buffer.history),
                         ("echo unfinished", 5, ["pwd", "ls"]))
        self.activate(host)
        self.user32.PostMessageW(host._hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: closed == [host])
        self.wait_for(lambda: owner_has_keyboard_focus(self.owner))
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))

    def test_native_title_drag_shows_preview_and_drop_requests_dock_without_button(self):
        from WinUx.platform.floating_viewport import window_rect
        from WinUx.platform.native_dock_gesture import cursor_position, gesture_mode
        snapshot = {"catalog": [], "selected": [], "series": [], "references": []}
        panel = SimpleNamespace(job_id="drag", job_name="Drag", label="Plots - Drag",
            _native_revision=0, native_snapshot=lambda: snapshot, exists=lambda: True)
        docked = []
        self.view._set_plot_dock_preview = Mock()
        self.view._hide_dock_drop_preview = Mock()
        self.view._plot_dock_target_at_pointer = lambda: "right" if (
            0 <= self.view._native_dock_pointer_candidates[0][0] < 240 and
            0 <= self.view._native_dock_pointer_candidates[0][1] < 180) else None
        host = self.create(lambda: PlotDockHost(self.view, panel, docked.append, lambda host: None))
        self.activate(host)
        previous = cursor_position()
        u = self.user32
        u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        u.mouse_event.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                 ctypes.c_ulong, ctypes.c_size_t]
        rect = window_rect(host._hwnd)
        try:
            u.SetCursorPos(rect[0] + 120, rect[1] + 20)
            u.mouse_event(0x0002, 0, 0, 0, 0)
            self.wait_for(lambda: gesture_mode(host._hwnd) == 1, timeout=5)
            owner = window_rect(self.owner)
            u.SetCursorPos(owner[0] + 80, owner[1] + 70)
            self.wait_for(lambda: window_rect(host._hwnd) != rect, timeout=5)
            self.wait_for(lambda: self.view._set_plot_dock_preview.called, timeout=5)
            self.view._set_plot_dock_preview.assert_called_with(True, "right")
            u.mouse_event(0x0004, 0, 0, 0, 0)
            try:
                self.wait_for(lambda: docked == [host], timeout=5)
            except AssertionError:
                self.fail(str({"gesture": getattr(host, "_last_native_dock_gesture", None),
                    "rect": window_rect(host._hwnd), "origin": rect,
                    "mode": gesture_mode(host._hwnd), "cursor": cursor_position(),
                    "foreground": int(u.GetForegroundWindow() or 0)}))
            self.assertEqual(host._requested_dock_area, "right")
            self.assertEqual(gesture_mode(host._hwnd), 0)
            self.assertFalse(getattr(host, "_native_preview_active", False))
        finally:
            u.mouse_event(0x0004, 0, 0, 0, 0)
            if previous is not None:
                u.SetCursorPos(*previous)
        self.assertTrue(self.user32.IsWindowEnabled(self.owner))

    def test_plot_native_dock_streams_new_snapshot_and_selection_to_retained_model(self):
        snapshot = {"catalog": [{"id": "a", "output": "ALLIE", "displayName": "Energy"}],
                    "selected": ["a"], "series": [{"id": "a", "points": [[0, 1]], "reset": True}],
                    "references": [], "status": "Live"}
        panel = SimpleNamespace(job_id="job", job_name="Test", label="Plots - Test",
            _native_revision=0, native_snapshot=lambda: snapshot, exists=lambda: True,
            set_selected_ids=Mock(), _set_reference_enabled=Mock(), _manage_references=Mock())
        docked, closed = [], []
        host = self.create(lambda: PlotDockHost(self.view, panel, docked.append, closed.append))
        self.assert_native_modeless(host)
        self.wait_for(lambda: getattr(host, "_rendered_plot_state", None) == (1, 1))
        snapshot["series"] = [{"id": "a", "points": [[0, 1], [1, 2]], "reset": True}]
        panel._native_revision += 1
        self.wait_for(lambda: host._rendered_plot_state == (1, 2))
        host.handle_event("selection", {"ids": []})
        panel.set_selected_ids.assert_called_once_with([])
        self.activate(host)
        self.user32.PostMessageW(host._hwnd, 0x00a3, 2, 0)
        self.wait_for(lambda: docked == [host])
        self.activate(host)
        self.user32.PostMessageW(host._hwnd, 0x0010, 0, 0)
        self.wait_for(lambda: closed == [host])
        self.wait_for(lambda: owner_has_keyboard_focus(self.owner))
