"""Standalone Plot Digitizer using the same GUI-thread/dialog policy as WinUx."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .application import reference_candidate
from .ui import PlotDigitizerDialog
from DearUIQt import QApplication, StandaloneUiHost, QGuiRuntime
from DearUIQt.widgets import QRetainedItem
from ..ui import configure_ui_context, viewport_icon_options, apply_tool_cursor
from ..platform.floating_viewport import ViewportCreationGuard, NativeViewport
from ..runtime.dpg_callbacks import run_callback_jobs
from ..dialogs.floating_dialog import close_floating_dialogs


StandaloneView = StandaloneUiHost  # backward-compatible local name


class FileReferenceSink:
    """Cross-process sink; WinUx imports candidates from this JSON-lines file."""

    def __init__(self, path: str | None):
        self.path = Path(path).resolve() if path else None

    @property
    def available(self):
        return self.path is not None

    def add_dataset(self, dataset):
        if self.path is None:
            raise RuntimeError("Reference bridge is unavailable.")
        candidate = reference_candidate(dataset, ())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(candidate, ensure_ascii=False) + "\n")
        return candidate


def _open_startup_path(dialog, raw_path):
    """Open a project/image after the first viewport frame.

    The direct runner accepts one positional path for fast iteration from an
    Abaqus command prompt. Project formats use the normal project loader;
    everything else follows the same asynchronous image-load path as the UI.
    """
    if not raw_path:
        return False
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        dialog._set_status("File not found: {}".format(path))
        return False
    if path.suffix.lower() in (".pdg", ".json"):
        dialog._load_project(str(path))
    else:
        dialog._open_image(str(path))
    return True


def _configure_standalone_qt_runtime(runtime, view, *, native_dialogs=True):
    """Mirror WinUx's GUI-thread/input/native-dialog startup contract.

    Dear PyGui's default callback worker is intentionally never used here.
    Native HWND operations and all retained widget callbacks must execute on the
    thread that created the renderer context, exactly like the WinUx main view.
    """
    runtime.createContext(manual_callbacks=True)
    configure_ui_context(view)

    application = QApplication.instance()
    if application is None:
        application = QApplication(after=view.after)
    view._qapplication = application

    native_enabled = False
    if native_dialogs and runtime.supportsNativeWindows():
        runtime.enableNativeWindows()
        native_enabled = True
    view._native_dialogs = native_enabled

    # One application-wide input bridge replaces DPG's callback worker.  It is
    # safe to install only after a live context exists and before UI creation.
    try:
        application.installInputBackend(runtime.backend)
    except Exception:
        # Widget-local bindings remain usable as a compatibility fallback.
        pass
    return application, native_enabled


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Open Plot Digitizer directly without the WinUx main window.")
    parser.add_argument("path", nargs="?", default="",
                        help="Optional image or .pdg/.json project to open at startup.")
    parser.add_argument("--reference-bridge", default="")
    parser.add_argument("--width", type=int, default=1240)
    parser.add_argument("--height", type=int, default=820)
    parser.add_argument(
        "--embedded-dialogs", action="store_true",
        help="Keep child dialogs inside the viewport even when native DearUIQt windows are available.")
    args = parser.parse_args(argv)

    runtime = QGuiRuntime()
    view = StandaloneUiHost(backend=runtime.backend)
    native = None
    dialog = None
    application = None
    try:
        application, native_dialogs = _configure_standalone_qt_runtime(
            runtime, view, native_dialogs=not args.embedded_dialogs)
        runtime.createViewport(
            title="Plot Digitizer",
            width=max(1100, args.width),
            height=max(720, args.height),
            min_width=1100,
            min_height=720,
            resizable=True,
            **viewport_icon_options(),
        )
        runtime.setup()
        sink = FileReferenceSink(args.reference_bridge) if args.reference_bridge else None

        # The process viewport itself is the Plot Digitizer top-level. Native
        # multi-window support stays enabled for Settings, confirmations,
        # sample-count and file-selector dialogs, but the root tool must remain
        # embedded in the primary viewport rather than allocate a second HWND.
        dialog = PlotDigitizerDialog(view, reference_sink=sink, native=False)
        view.on_error = dialog._set_status
        # Use the same in-process WinUx file/folder selector implementation.
        # With native windows enabled it becomes an owned Qt-style HWND; without
        # that capability it gracefully remains an in-viewport modal.
        view.use_native_file_selectors = False
        dialog._defer_visual_destroy = True
        try:
            QRetainedItem(dialog.tag).configure(
                modal=False, no_title_bar=True, no_move=True,
                no_resize=True, no_collapse=True)
            runtime.setPrimaryWindow(dialog.tag, True)
        except Exception:
            pass

        with ViewportCreationGuard() as guard:
            runtime.show()
        native = NativeViewport(guard.hwnd, True)
        native.configure(0, allow_minimize=True, allow_maximize=True)
        view._native_hwnd = native.hwnd
        native.install_close_handler(view, dialog._close_from_native)

        # Publish a few complete frames before centering/opening an optional
        # file. This keeps first-show geometry and native child ownership stable.
        for _ in range(3):
            run_callback_jobs(runtime.callbackQueue())
            view.pump()
            runtime.renderFrame()
            apply_tool_cursor(view)
        native.center(0)
        native.stage_publish(True)
        native.commit_publish(True)
        native.activate()
        if args.path:
            view.after(0, _open_startup_path, dialog, args.path)

        while runtime.isRunning() and dialog.winfo_exists():
            # Manual callback management is mandatory here. Every callback is
            # dispatched on this owning GUI thread before the next render.
            run_callback_jobs(runtime.callbackQueue())
            view.pump()
            runtime.renderFrame()
            apply_tool_cursor(view)
        return 0
    finally:
        close_floating_dialogs(view)
        if native is not None:
            native.set_visible(False)
            native.restore_close_handler()
        if dialog is not None:
            dialog.destroy()
            dialog._finalize_visual_destroy()
        if application is not None:
            try:
                application.delete()
            except Exception:
                pass
        try:
            view.close()
        except Exception:
            pass
        try:
            runtime.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
