"""Standalone Plot Digitizer process with its own DearPyGui context/viewport."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .application import reference_candidate
from .ui import PlotDigitizerDialog
from DearUIQt import StandaloneUiHost, QGuiRuntime
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


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--reference-bridge", default="")
    parser.add_argument("--width", type=int, default=1240)
    parser.add_argument("--height", type=int, default=820)
    args = parser.parse_args(argv)

    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=False)
    view = StandaloneUiHost()
    native = None
    dialog = None
    try:
        configure_ui_context(view)
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
        dialog = PlotDigitizerDialog(view, reference_sink=sink)
        view.on_error = dialog._set_status
        view.use_native_file_selectors = True
        dialog._defer_visual_destroy = True
        # The process viewport itself is the tool window. Make the shared WinUx
        # dialog surface fill it instead of behaving like a child modal.
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
        for _ in range(3):
            run_callback_jobs(runtime.callbackQueue())
            view.pump()
            runtime.renderFrame()
            apply_tool_cursor(view)
        native.center(0)
        native.stage_publish(True)
        native.commit_publish(True)
        native.activate()

        while runtime.isRunning() and dialog.winfo_exists():
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
        try:
            runtime.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
