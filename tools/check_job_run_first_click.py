"""Exercise the first physical Run click through the full WinUx event loop.

No server connection or submission is made; the submission callback is a spy.
"""
import ctypes
import argparse
from collections import deque
from ctypes import wintypes
from pathlib import Path, PurePosixPath
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "--native-deps" in sys.argv:
    sys.path.insert(0, sys.argv[sys.argv.index("--native-deps") + 1])
    import dearpygui.dearpygui
import WinUx
from WinUx.controllers import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.ui.behaviors.plot_docking import PlotDockingMixin
from DearUIQt.input_gate import native_background_input_blocked
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.core import QEvent, QMouseEvent, Qt
from WinUx.runtime.dpg_callbacks import invoke_callback_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--immediate", action="store_true")
    parser.add_argument("--direct", action="store_true", help="Move onto Run and press within one render frame")
    parser.add_argument("--natural", action="store_true", help="Do not force activation of the dialog")
    parser.add_argument("--hardware", action="store_true", help="Use native desktop mouse injection")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--trace-focus", action="store_true")
    parser.add_argument("--no-initial-focus", action="store_true")
    parser.add_argument("--native-deps")
    parser.add_argument("--control", choices=("run", "button", "checkbox", "editor"), default="run")
    parser.add_argument("--manual", action="store_true", help="Wait for one real user click; no remote submission")
    parser.add_argument("--bridge", action="store_true", help="Deliver pointer events via the real QApplication on rendered controls")
    parser.add_argument("--simulate-native", action="store_true", help="Also deliver duplicate native callbacks in bridge mode")
    args = parser.parse_args()
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    for name in ("SetFocus", "SetForegroundWindow", "BringWindowToTop"):
        getattr(user32, name).argtypes = [wintypes.HWND]
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    old = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old))
    errors, submitted = [], []
    with patch.object(PlotDockingMixin, "_get_reference_chart_library",
                      lambda self: SimpleNamespace(snapshot=lambda: [], replace=Mock())), \
            patch("WinUx.dialogs.logic.job_manager.JobManagerPreferences.save"):
        view = WinUXView({name: Mock(return_value=[]) for name in REQUIRED_CALLBACK_KEYS})
        view._handle_ui_callback_error = lambda callback, info: errors.append(info[1])
        backend = view._gui_runtime.backend
        from DearUIQt.backends import get_backend
        native_input_state = getattr(get_backend().internal_dpg, "dearuiqt_native_input_state", lambda: {})
        trace = deque(maxlen=200)
        observed = {"form": None, "releases": 0}
        def capture_frame():
            form = observed["form"]
            if form is not None and form.winfo_exists():
                clicked = backend.is_mouse_button_clicked(0)
                released = backend.is_mouse_button_released(0)
                observed["releases"] += int(released)
                trace.append({"frame": backend.get_frame_count(), "pressed": clicked,
                              "released": released, "input": native_input_state(),
                              "button": backend.get_item_state(form.run_button),
                              "payloads": len(submitted), "gate": native_background_input_blocked()})
            if view.winfo_exists():
                view.after_render(capture_frame)
        view.after_render(capture_frame)
        initial_focus_patch = None
        if args.no_initial_focus:
            initial_focus_patch = patch.object(QtDialog, "_focus_initial", lambda self: False)
            initial_focus_patch.start()
        focus_patch = None
        if args.trace_focus:
            from DearUIQt.backends import get_backend
            native_backend = get_backend()
            original_focus = native_backend.focus_item
            def traced_focus(item):
                import traceback
                print("FOCUS", backend.get_frame_count(), item,
                      " > ".join(line.name for line in traceback.extract_stack(limit=5)[:-1]), flush=True)
                return original_focus(item)
            focus_patch = patch.object(native_backend, "focus_item", traced_focus)
            focus_patch.start()

        def scenario():
            for attempt in range(args.repeat):
                if args.control == "run":
                    view.show_job_manager([PurePosixPath("/work/first-click.inp")],
                                          lambda dialog, jobs: submitted.append(jobs), lambda *_: None)
                    form = view.job_manager_dialog
                else:
                    form = QtDialog(view, "First click " + args.control, 560, 250)
                    form._submitting = False
                    form.status = form.status_text()
                    def changed(*_):
                        form._submitting = True
                        submitted.append(args.control)
                    if args.control == "button":
                        form.run_button = form.action("Test button", changed, parent=form.content)
                    elif args.control == "checkbox":
                        form.run_button = form.checkbox("Test checkbox", checked=False, parent=form.content)
                        form.control_wrapper(form.run_button).toggled.connect(changed)
                    else:
                        form.run_button = form.line_edit("", callback=changed, width=220, parent=form.content)
                    other_button = form.action("Other focus", lambda: None)
                    form.set_initial_focus(other_button)
                yield "button ready", lambda: (form.winId() and not form.isConstructing()
                                                and backend.get_item_state(form.run_button).get("visible"))
                observed["form"] = form
                if args.bridge:
                    assert args.control in ("run", "button"), "Bridge test targets push buttons"
                    before = len(submitted)
                    x, y = backend.get_item_rect_min(form.run_button)
                    width, height = backend.get_item_rect_size(form.run_button)
                    point = (x + width / 2, y + height / 2)
                    callback = backend.get_item_configuration(form.run_button)["callback"]
                    if args.simulate_native:
                        invoke_callback_job((callback, form.run_button, None, None))
                    assert view._qapplication.dispatchPointerEvent(QMouseEvent(
                        QEvent.MouseButtonPress, point, button=Qt.LeftButton, buttons=Qt.LeftButton))
                    assert len(submitted) == before, "Button activated before release"
                    assert view._qapplication.dispatchPointerEvent(QMouseEvent(
                        QEvent.MouseButtonRelease, point, button=Qt.LeftButton))
                    if args.simulate_native:
                        invoke_callback_job((callback, form.run_button, None, None))
                    until = time.monotonic() + .15
                    yield "bridge callback drained", lambda: time.monotonic() >= until
                    assert len(submitted) == before + 1, "Shared dialog route did not dispatch exactly once"
                    print("DIALOG_POINTER_ONCE_OK", args.control, attempt,
                          "duplicate native" if args.simulate_native else "no native activation", flush=True)
                    observed["form"] = None
                    form.destroy()
                    until = time.monotonic() + .08
                    yield "bridge closed", lambda: time.monotonic() >= until
                    continue
                if args.manual:
                    releases = observed["releases"]
                    before = len(submitted)
                    print("MANUAL_TEST_READY: click Run ONCE in the test Job Manager. No remote job is sent.", flush=True)
                    yield "manual first release", lambda: observed["releases"] > releases
                    until = time.monotonic() + .4
                    yield "manual callback drained", lambda: time.monotonic() >= until
                    for entry in trace:
                        print("CLICK_FRAME", entry, flush=True)
                    print("MANUAL_FIRST_CLICK_RESULT", len(submitted) - before, flush=True)
                    assert len(submitted) == before + 1, "Real first click did not dispatch exactly once"
                    observed["form"] = None
                    form.destroy()
                    continue
                hwnd = form.winId()
                other = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                own = ctypes.windll.kernel32.GetCurrentThreadId()
                if not args.natural:
                    user32.AttachThreadInput(own, other, True)
                    try:
                        user32.BringWindowToTop(hwnd)
                        user32.SetForegroundWindow(hwnd)
                        user32.SetFocus(hwnd)
                    finally:
                        user32.AttachThreadInput(own, other, False)
                until = time.monotonic() + (0 if args.immediate else .2)
                yield "activation settled", lambda: time.monotonic() >= until
                if not args.hardware:
                    assert int(user32.GetForegroundWindow() or 0) == hwnd, "Native click test blocked: Windows denied foreground"
                x, y = backend.get_item_rect_min(form.run_button)
                width, height = backend.get_item_rect_size(form.run_button)
                point = wintypes.POINT(round(x + width / 2), round(y + height / 2))
                user32.SetCursorPos(point.x, point.y)
                user32.ScreenToClient(hwnd, ctypes.byref(point))
                packed = (point.y << 16) | (point.x & 0xffff)
                user32.PostMessageW(hwnd, 0x0200, 0, packed)
                until = time.monotonic() + (0 if args.immediate else .1)
                if not args.direct:
                    yield "hover", lambda: time.monotonic() >= until
                before = len(submitted)
                print("BEFORE_PRESS", attempt, "gate", native_background_input_blocked(),
                      "button", backend.get_item_state(form.run_button), "input", native_input_state(), flush=True)
                if args.hardware:
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                else:
                    user32.PostMessageW(hwnd, 0x0201, 1, packed)
                until = time.monotonic() + .1
                yield "pressed", lambda: time.monotonic() >= until
                print("PRESSED", backend.get_item_state(form.run_button), "input", native_input_state(), flush=True)
                if args.hardware:
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                else:
                    user32.PostMessageW(hwnd, 0x0202, 0, packed)
                if args.control == "editor":
                    user32.PostMessageW(hwnd, 0x0102, ord("x"), 0)
                until = time.monotonic() + .3
                yield "released", lambda: time.monotonic() >= until
                print("AFTER_RELEASE", "submitting", form._submitting, "payloads", len(submitted),
                      "status", form.control_value(form.status), "gate", native_background_input_blocked(),
                      "foreground", int(user32.GetForegroundWindow() or 0), "hwnd", hwnd,
                      "mouse", backend.get_mouse_pos(local=False), flush=True)
                assert len(submitted) == before + 1, "First {} click did not dispatch exactly once".format(args.control)
                form.destroy()
                until = time.monotonic() + .15
                yield "closed", lambda: time.monotonic() >= until

        steps, pending = scenario(), []
        def advance():
            try:
                if errors:
                    raise errors[0]
                if pending:
                    label, predicate, deadline = pending[0]
                    if not predicate():
                        assert time.monotonic() < deadline, "Timeout: " + label
                        view.after(10, advance)
                        return
                    pending.clear()
                label, predicate = next(steps)
                pending.append((label, predicate, time.monotonic() + (90 if args.manual else 5)))
                view.after(10, advance)
            except StopIteration:
                view.request_shutdown()
            except Exception as exc:
                errors.append(exc)
                view.request_shutdown()
        view.after(250, advance)
        try:
            view.run()
        finally:
            user32.SetCursorPos(old.x, old.y)
            if focus_patch is not None:
                focus_patch.stop()
            if initial_focus_patch is not None:
                initial_focus_patch.stop()
        if errors:
            raise errors[0]
    print("FIRST_CLICK_OK", args.control, "initial open and reopen; no remote submission")


if __name__ == "__main__":
    main()
