"""Verify the real WinUx menu routes use retained native tools, not IPC."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-deps", type=Path)
    parser.add_argument("--use-saved-references", action="store_true",
                        help="Read real saved references without writing profile data")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from winux_native_runtime import native_runtime_path
    runtime_path = str(args.native_deps.resolve()) if args.native_deps else native_runtime_path(str(root))
    if not runtime_path:
        raise RuntimeError("Install the native DearUIQt runtime before this acceptance test")
    if args.native_deps:
        sys.path.insert(0, runtime_path)
        import dearpygui.dearpygui
    else:
        # Exercise the installed application's own bootstrap precedence, not a
        # test-only injected backend path.
        import WinUx
    from WinUx.controllers import REQUIRED_CALLBACK_KEYS
    from WinUx.view import WinUXView
    from WinUx.ui.behaviors.plot_docking import PlotDockingMixin

    if args.use_saved_references:
        from WinUx.services.reference_charts import ReferenceChartLibrary
        saved_library = ReferenceChartLibrary()
        library = SimpleNamespace(snapshot=saved_library.snapshot, replace=Mock())
    else:
        library = SimpleNamespace(snapshot=lambda: [], replace=Mock())
    callbacks = {name: Mock(return_value=[]) for name in REQUIRED_CALLBACK_KEYS}
    errors, timings = [], []
    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowEnabled.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.SetFocus.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    pending = []
    with patch.object(PlotDockingMixin, "_get_reference_chart_library", lambda self: library), \
            patch("subprocess.Popen", side_effect=AssertionError("Native tools must not spawn a dialog process")):
        startup_started = time.perf_counter()
        view = WinUXView(callbacks)
        startup_ms = (time.perf_counter() - startup_started) * 1000
        assert startup_ms < 3000, "Reference tool preparation blocked main-window construction"
        assert view._native_dialogs, "WinUx did not enable its native dialog route"
        view.show_error = lambda *values: errors.append(AssertionError(str(values)))
        view._handle_ui_callback_error = lambda callback, info: errors.append(info[1])
        chart, digitizer = view._reference_chart_dialog, view._plot_digitizer_dialog
        assert chart and digitizer, "Reference tools were not prepared during startup"
        assert not chart.isVisible() and not digitizer.isVisible(), "Startup exposed a hidden tool"
        table = chart.data_table
        # Startup constructs an empty default draft only: the default sheet is
        # 20 blank rows and native materialization stays deferred.
        assert table.model.row_count <= 20, "Startup restored a saved XY worksheet"
        assert table.materialized_row_count() <= table.POPULATE_MAX_BATCH, \
            "Startup synchronously materialized native rows"

        def scenario():
            for cycle in range(3):
                for kind, open_tool, dialog in (
                        ("reference_chart", view._show_reference_chart_dialog, chart),
                        ("plotdigitizer", view._show_plot_digitizer_dialog, digitizer)):
                    started = time.perf_counter()
                    open_tool()
                    callback_ms = (time.perf_counter() - started) * 1000
                    yield kind + "-visible", lambda: dialog.winId() and user32.IsWindowVisible(dialog.winId())
                    visible_ms = (time.perf_counter() - started) * 1000
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(dialog.winId(), ctypes.byref(pid))
                    assert pid.value == os.getpid(), "Dialog still belongs to a worker process"
                    assert not hasattr(dialog, "_process"), "Menu still created a floating IPC adapter"
                    assert callback_ms < 250, "Menu callback rebuilt a heavy dialog ({:.1f} ms)".format(callback_ms)
                    timings.append({"kind": kind, "cycle": cycle,
                                    "callback_ms": round(callback_ms, 2), "visible_ms": round(visible_ms, 2)})
                    if kind == "reference_chart" and cycle == 0:
                        editor = dialog.control_wrapper(dialog.name_edit)
                        previous = str(dialog.control_value(dialog.name_edit, ""))
                        input_skipped = []
                        # Loaded worksheets schedule their initial cell focus.
                        # Let that complete before explicitly focusing/typing in
                        # the name editor, just as a user clicks after first show.
                        def focus_then_type():
                            user32.SetForegroundWindow(dialog.winId())
                            user32.SetFocus(dialog.winId())
                            if user32.GetForegroundWindow() != dialog.winId():
                                # Windows can deny foreground activation to a
                                # background automation process. Do not treat
                                # desktop focus policy as an editor failure.
                                input_skipped.append(True)
                                return
                            editor.setFocus()
                            view.after_render(lambda: user32.PostMessageW(dialog.winId(), 0x0102, ord("Z"), 1))
                        view.after_render(focus_then_type)
                        yield "reference-native-text-input", lambda: input_skipped or str(dialog.control_value(dialog.name_edit, "")) != previous
                        timings[-1]["native_input"] = "skipped_foreground_unavailable" if input_skipped else "verified"
                    if kind == "reference_chart" and cycle == 1:
                        dialog.finish([])
                        library.replace.assert_called_with([])
                    else:
                        dialog.reject()
                    yield kind + "-hidden", lambda: not dialog.isVisible() and user32.IsWindowEnabled(view._find_main_viewport_hwnd())
                    assert dialog.winfo_exists(), "Close destroyed the retained tool"
                    assert view._reference_chart_dialog is chart and view._plot_digitizer_dialog is digitizer

        steps = scenario()

        def advance():
            try:
                if errors:
                    raise errors[0]
                if pending:
                    name, predicate, deadline = pending[0]
                    if not predicate():
                        if time.monotonic() >= deadline:
                            if name == "reference-native-text-input":
                                backend = view._gui_runtime.backend
                                print("REFERENCE_INPUT_DIAGNOSTIC " + json.dumps({
                                    "expected": chart.name_edit,
                                    "focused": backend.get_focused_item(),
                                    "editor_state": backend.get_item_state(chart.name_edit),
                                    "editor_shown": backend.is_item_shown(chart.name_edit),
                                    "window": chart.winId(),
                                    "foreground": user32.GetForegroundWindow(),
                                    "enabled": bool(user32.IsWindowEnabled(chart.winId())),
                                }, default=str), flush=True)
                            raise AssertionError("Main-window dialog stalled at " + name)
                        view.after(1, advance)
                        return
                    pending.clear()
                name, predicate = next(steps)
                pending.append((name, predicate, time.monotonic() + 3))
                view.after(1, advance)
            except StopIteration:
                view.request_shutdown()
            except Exception as exc:
                errors.append(exc)
                view.request_shutdown()

        view.after(250, advance)
        view.run()
    if errors:
        raise errors[0]
    assert len(timings) == 6
    print("WINUX_NATIVE_STARTUP_MS {:.2f}".format(startup_ms), flush=True)
    print("WINUX_NATIVE_MENU_DIALOGS_OK " + json.dumps(timings), flush=True)


if __name__ == "__main__":
    main()
