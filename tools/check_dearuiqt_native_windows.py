"""Real HWND acceptance test, run only with the isolated custom backend.

abaqus python tools/check_dearuiqt_native_windows.py --native-deps PATH
Add --winux-forms to construct the real Reference Chart and Plot Digitizer.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-deps", required=True, type=Path)
    parser.add_argument("--winux-forms", action="store_true")
    parser.add_argument("--hold-seconds", type=float, default=0,
                        help="Keep the verified windows open for a manual preview")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(args.native_deps.resolve()))
    import dearpygui.dearpygui as backend
    from DearUIQt.runtime import QGuiRuntime, StandaloneUiHost
    from DearUIQt.widgets import QMainWindow, QNativeWindow, QLabel, QLineEdit

    gui = QGuiRuntime(backend)
    gui.createContext()
    gui.enableNativeWindows()
    host = StandaloneUiHost(backend)
    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.IsWindowEnabled.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    windows = []

    def frames(count=8):
        for _ in range(count):
            host.pump()
            gui.renderFrame()
            jobs = gui.callbackQueue()
            if jobs:
                backend.run_callbacks(jobs)

    try:
        root = QMainWindow("DearUIQt native multi-window acceptance", width=640, height=420)
        QLabel("One process, one renderer context, independent OS windows.", parent=root)
        gui.createViewport(title="DearUIQt Native Test", width=660, height=460, vsync=False)
        gui.setPrimaryWindow(root, True)
        gui.setup()
        gui.show()
        frames()
        with patch("subprocess.Popen", side_effect=AssertionError("Dialogs must not spawn processes")):
            started = time.perf_counter()
            if args.winux_forms:
                from WinUx.dialogs.reference_chart_form import ReferenceChartDialog
                from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
                first = ReferenceChartDialog(host, [], lambda *values: None)
                second = PlotDigitizerDialog(host)
            else:
                first = QNativeWindow("Reference-like native window", owner=root, width=420, height=260)
                second = QNativeWindow("Digitizer-like native window", width=480, height=320)
                QLabel("No worker process or IPC", parent=first)
                editor = QLineEdit("", parent=second)
            windows.extend((first, second))
            frames()
            handles = [window.winId() for window in windows]
            assert all(handles) and len(set(handles)) == 2, "Missing independent HWNDs"
            for handle in handles:
                pid = wintypes.DWORD()
                thread = user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
                assert pid.value == os.getpid(), "A dialog belongs to another process"
                assert thread == ctypes.windll.kernel32.GetCurrentThreadId(), "A dialog has a separate GUI thread"
                assert user32.IsWindowVisible(handle), "Dialog was not visible"
            first_open_ms = (time.perf_counter() - started) * 1000
            if not args.winux_forms:
                editor.setFocus()
                frames()
                user32.PostMessageW(handles[1], 0x0102, ord("Z"), 1)  # WM_CHAR
                frames()
                assert "Z" in editor.text(), "Native text input was not routed to its editor"
            # Real owned top-levels can move outside the main viewport bounds.
            user32.SetWindowPos(handles[1], None, 1000, 120, 0, 0, 0x0001 | 0x0004)
            frames()
            retained_tag = second.tag
            second.hide()
            frames()
            started = time.perf_counter()
            second.show()
            frames()
            assert second.tag == retained_tag and second.winId(), "Reopen rebuilt/lost the retained widget"
            if not args.winux_forms:
                assert "Z" in editor.text(), "Reopen lost retained editor contents"
            reopen_ms = (time.perf_counter() - started) * 1000
            # Test owner-specific native modality without global process gates.
            modal = QNativeWindow("Owned native modal", owner=second, modal=True, width=300, height=180)
            windows.append(modal)
            frames()
            assert not user32.IsWindowEnabled(second.winId()), "Native modal did not disable its owner"
            assert user32.IsWindowEnabled(modal.winId()), "Native modal was itself disabled"
            assert user32.GetWindow(modal.winId(), 4) == second.winId(), "Wrong native owner"
            from DearUIQt.backends.native_windows import NativeWindowBackend
            try:
                NativeWindowBackend(backend).configure(second, owner=modal)
            except ValueError:
                pass
            else:
                raise AssertionError("Backend allowed a native owner cycle")
            modal.hide()
            frames()
            assert user32.IsWindowEnabled(second.winId()), "Closing modal did not release owner"
            # Native caption close must retain the widget and synchronize Qt
            # visibility, rather than leaving show() a cached no-op.
            modal.show()
            frames()
            user32.PostMessageW(modal.winId(), 0x0010, 0, 0)
            frames()
            assert modal.isHidden() and not modal._deleted, "OS Close did not retain/hide the widget"
            modal.show()
            frames()
            assert modal.winId() and modal.isVisible(), "Native widget could not reopen after OS Close"
            modal.hide()
            frames()
        result = {
            "pid": os.getpid(), "hwnds": handles, "winux_forms": args.winux_forms,
            "first_open_ms": round(first_open_ms, 1), "reopen_ms": round(reopen_ms, 1),
            "backend": backend.internal_dpg.__file__, "processes_per_dialog": 0,
        }
        if args.hold_seconds > 0:
            print("DEARUIQT_NATIVE_PREVIEW_READY", flush=True)
            until = time.monotonic() + args.hold_seconds
            while gui.isRunning() and time.monotonic() < until:
                frames(1)
                time.sleep(.008)
    finally:
        for window in reversed(windows):
            destroy = getattr(window, "destroy", None) or window.delete
            destroy()
        host.pump()
        gui.destroy()
    print("DEARUIQT_NATIVE_WINDOWS_OK " + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
