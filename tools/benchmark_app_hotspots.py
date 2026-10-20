"""Audit current hot paths; timings exclude live SSH and GPU frame rendering.

Run with: abaqus python tools/benchmark_app_hotspots.py --native
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from WinUx.runtime.terminal_buffer import TerminalBuffer
from WinUx.services.odb_history_live import merge_series_delta


def median_ms(callback, repeats=5):
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        callback()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 3)


def python_hotspots():
    report = {"plot_delta_and_xy_preparation": {}, "console_cached_row_preparation": {}}
    for count in (10000, 100000, 500000):
        existing = [[i * 0.01, float(i % 100)] for i in range(count)]
        update = {"reset": False, "points": [[count + i, i] for i in range(10)]}

        def prepare():
            points = merge_series_delta(existing, update)
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            assert len(xs) == len(ys) == count + 10

        report["plot_delta_and_xy_preparation"][str(count)] = {
            "existing_points": count, "new_points": 10, "median_ms": median_ms(prepare)}
    for count in (1000, 12000):
        buffer = TerminalBuffer()
        buffer.set_output("\n".join("Row {}".format(i) for i in range(count)))
        buffer.styled_layout(80)  # Warm the same layout cache used by paint().

        def prepare_rows():
            styled, _, _ = buffer.styled_layout(80)
            rows = ["".join(text for _, text in segments) for segments in styled]
            assert len(rows) >= count

        report["console_cached_row_preparation"][str(count)] = {
            "rows": count, "median_ms": median_ms(prepare_rows, repeats=20)}
    return report


def native_hotspots():
    import WinUx
    import dearpygui.dearpygui as dpg
    from WinUx.ui.components.job_plots import JobPlotsWindow
    from WinUx.dialogs.floating_runtime import ChildView, configure_context
    from WinUx.dialogs.local_folder_form import LocalFolderDialog

    report = {"folder_selector_full_rebuild": {}}
    dpg.create_context()
    plot = folder = None
    try:
        view = ChildView()
        configure_context(view)
        root = dpg.add_window(label="Hot-path audit", width=1000, height=700)
        dpg.create_viewport(title="WinUx optimization audit", width=1000, height=700)
        dpg.set_primary_window(root, True)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        plot = JobPlotsWindow(root, "audit", "Audit")
        for _ in range(3):
            dpg.render_dearpygui_frame()
        iterations = 60
        with patch.object(dpg, "configure_item", wraps=dpg.configure_item) as configure:
            started = time.perf_counter()
            for _ in range(iterations):
                plot.sync_layout()
            elapsed = (time.perf_counter() - started) * 1000
            report["plot_idle_layout"] = {
                "unchanged_layout_passes": iterations,
                "configure_item_calls": configure.call_count,
                "calls_per_pass": round(configure.call_count / iterations, 2),
                "ms_per_pass": round(elapsed / iterations, 3),
            }
        plot.close()
        plot = None
        folder = LocalFolderDialog(view, Path.cwd(), lambda result: None)
        for _ in range(3):
            dpg.render_dearpygui_frame()
        # Only UI/model data is synthetic; no thousands of real dirs are made.
        for count in (100, 1000, 5000):
            folder._listing = [("folder{:05d}".format(i), "Folder{:05d}".format(i),
                                str(Path(folder._current_path) / "Folder{:05d}".format(i)))
                               for i in range(count)]
            started = time.perf_counter()
            folder._filter_entries()
            elapsed = (time.perf_counter() - started) * 1000
            report["folder_selector_full_rebuild"][str(count)] = {
                "folders": count, "native_build_ms": round(elapsed, 3)}
    finally:
        if plot is not None:
            plot.close()
        if folder is not None:
            folder.finish(None)
        dpg.destroy_context()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    report = {"scope": "Current Python/native widget hot paths; no live SSH, GPU FPS or RSS measurement"}
    report.update(python_hotspots())
    if args.native:
        report.update(native_hotspots())
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
