"""Undocked Console RMB placement: abaqus python tests/test_undocked_context_menu_position.py.

Runs only the production detached Console host. Temporarily moves the cursor.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.backends.dearpygui import dpg_window_rect
from DearUIQt.backends.native_windows import NativeTopLevelWindow, NativeWindowBackend
from DearUIQt.gui.palette import QtFusionPalette
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


def main():
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32 = ctypes.windll.gdi32
    gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.GetPixel.restype = wintypes.DWORD
    cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(cursor))
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='undocked-context-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        runtime = FloatingDialogRuntime(Mock(), iter(()), {
            'kind': 'console_dock', 'title': 'Undocked context placement', 'visible': True,
            'payload': {'output': 'Console context placement regression\n'},
            'width': 800, 'height': 500,
        })
        runtime.gui.createContext(manual_callbacks=True)
        runtime._publish_requested = runtime._commit_requested = True

        def pump(count=1):
            for _ in range(count):
                runtime._drain_form_callbacks()
                runtime.view.drain()
                runtime.gui.renderFrame()
                runtime.view.mark_presented()
                time.sleep(.016)

        try:
            runtime._build()
            pump(30)
            hwnd = runtime.native.hwnd
            window = NativeTopLevelWindow(hwnd)
            form = runtime.form
            for x, y in ((120, 120), (620, 270)):
                window.move(x, y)
                runtime.native.activate()
                thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, thread, True)
                try:
                    user32.SetForegroundWindow(wintypes.HWND(hwnd))
                finally:
                    if attached:
                        user32.AttachThreadInput(current, thread, False)
                user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, 0x0013)
                pump(8)
                point = wintypes.POINT(140, 100)
                assert user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(point))
                user32.SetCursorPos(point.x, point.y)
                pump(5)
                # Do not call native_context_release/native_right_click here:
                # the regression is the missing physical Win32-to-form route.
                user32.mouse_event(0x0008, 0, 0, 0, 0)
                pump(3)
                user32.mouse_event(0x0010, 0, 0, 0, 0)
                pump(12)
                menu = form._context_menu_obj
                assert menu.isVisible(), ('Physical RMB did not open Console context menu',
                    'foreground', int(user32.GetForegroundWindow() or 0), 'host', hwnd,
                    'point', (point.x, point.y), 'contains', form._terminal_rect_contains((point.x, point.y)),
                    'over', form._over_terminal(), 'viewport', dpg.get_viewport_pos())
                expected = (140, 100)
                actual = dpg_window_rect(dpg, menu.tag, clip=False)[:2]
                print('Host', (x, y), 'screen click', (point.x, point.y),
                      'native windows', NativeWindowBackend().isEnabled(),
                      'menu', actual, 'expected client', expected, flush=True)
                assert abs(actual[0] - expected[0]) <= 2 and abs(actual[1] - expected[1]) <= 2, (
                    'Context menu is not at the right-click point', actual, expected)
                assert menu.containsGlobalPoint((point.x + 10, point.y + 10)), 'Menu screen hit test is offset'
                ctypes.windll.dwmapi.DwmFlush()
                dc = user32.GetDC(None)
                try:
                    color = int(gdi32.GetPixel(dc, point.x + 170, point.y + 12))
                    painted = (color & 255, (color >> 8) & 255, (color >> 16) & 255)
                finally:
                    user32.ReleaseDC(None, dc)
                print('Desktop menu pixel', painted, flush=True)
                assert painted in (QtFusionPalette.MENU[:3], QtFusionPalette.MENU_HOVER[:3],
                                   QtFusionPalette.MENU_ACTIVE[:3]), ('Menu exists but is not painted above Console', painted)
                # A retained owner anchor must remain in screen coordinates,
                # while its renderer position stays relative to the host.
                menu.popupGlobal((point.x, point.y), owner=form.tag)
                window.move(x + 35, y + 25)
                pump(10)
                actual = dpg_window_rect(dpg, menu.tag, clip=False)[:2]
                assert abs(actual[0] - 140) <= 2 and abs(actual[1] - 100) <= 2, ('Move changed client anchor', actual)
                menu.hide()
                pump(5)
            client = wintypes.RECT()
            user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client))
            edge = wintypes.POINT(client.right - 20, client.bottom - 20)
            user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(edge))
            user32.SetCursorPos(edge.x, edge.y)
            pump(4)
            user32.mouse_event(0x0008, 0, 0, 0, 0)
            pump(3)
            user32.mouse_event(0x0010, 0, 0, 0, 0)
            pump(10)
            left, top, right, bottom = dpg_window_rect(dpg, form._context_menu_obj.tag, clip=False)
            assert 0 <= left < right <= client.right and 0 <= top < bottom <= client.bottom, (
                'Edge context menu extends outside the detached client', (left, top, right, bottom),
                (client.right, client.bottom))
            form._context_menu_obj.hide()
            print('PASS: undocked Console context stays at RMB after moving the host', flush=True)
        finally:
            user32.mouse_event(0x0010, 0, 0, 0, 0)
            user32.SetCursorPos(cursor.x, cursor.y)
            runtime.view._dispatcher.close()
            if runtime.native:
                runtime.native.set_visible(False)
                runtime.native.restore_close_handler()
                runtime.native.close_activation_guard()
            runtime.gui.destroy()


if __name__ == '__main__':
    main()
