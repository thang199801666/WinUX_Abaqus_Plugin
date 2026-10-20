"""Exercise the shared controls and image-to-CSV workflow with the native UI."""
import sys
import time
import csv

import pytest
from PIL import Image, ImageDraw


@pytest.mark.windows_native
@pytest.mark.skipif(sys.platform != "win32", reason="Requires the Windows DearPyGui runtime")
def test_shared_form_image_extraction_and_value_edits(tmp_path):
    import dearpygui.dearpygui as dpg
    from WinUx.ui import StandaloneUiHost, configure_ui_context
    from WinUx.runtime.dpg_callbacks import run_callback_jobs
    from WinUx.plotdigitizer.ui import PlotDigitizerDialog

    image = Image.new("RGB", (121, 121), "white")
    ImageDraw.Draw(image).line((10, 100, 110, 20), fill=(220, 30, 50), width=1)
    path = tmp_path / "curve.png"
    image.save(path)
    dpg.create_context()
    dialog = None
    try:
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        dpg.create_viewport(title="Plot Digitizer regression", width=1180, height=720)
        dpg.setup_dearpygui()
        dialog = PlotDigitizerDialog(host)
        dpg.set_primary_window(dialog.tag, True)
        dpg.show_viewport()
        dpg.render_dearpygui_frame()
        for _ in range(3):
            run_callback_jobs(dpg.get_callback_queue() or [])
            host.pump()
            dpg.render_dearpygui_frame()
        assert host.ui_font_family == "Segoe UI"
        assert host.ui_font_size == 14
        row = dialog.dataset_list.items[0]
        assert dpg.get_item_rect_size(row)[0] > 100
        assert dpg.get_item_state(row)["visible"]
        dialog._open_image(str(path))
        for key, px, py, value in (
            ("x1", 10, 110, 0), ("x2", 110, 110, 10),
            ("y1", 10, 110, 0), ("y2", 10, 10, 100),
        ):
            dialog.engine.set_anchor(key, px, py, value)
        host.pump()
        dialog.engine.sample_curve_color(60, 60)
        dialog._setting_changed("smoothing", 0)
        dialog._refresh_all()
        dialog._extract_curve()
        deadline = time.monotonic() + 5
        while dialog._smart_runner.busy:
            host.pump()
            assert time.monotonic() < deadline
            time.sleep(.005)
        host.pump()
        assert len(dialog.engine.active_dataset.extracted_data) == 101
        assert "X [0 .. 10]" in dpg.get_value(dialog.calibration_info)
        dialog._anchor_value_changed("x2", "20")
        host.pump()
        assert dialog.engine.active_dataset.extracted_data[50] == pytest.approx((10, 50))
        assert dpg.get_value(dialog.anchor_value["x2"]) == "20"
        dialog._export_csv(str(tmp_path / "result.csv"))
        assert (tmp_path / "result.csv").exists()
        assert dpg.get_value(dialog.status) == "CSV exported."
        dialog._add_dataset()
        host.pump()
        assert dpg.get_value(dialog.smoothing) == 3
        dialog.engine.set_active_dataset(0)
        host.pump()
        assert dpg.get_value(dialog.smoothing) == 0
        dpg.render_dearpygui_frame()
        before = dpg.get_item_configuration(dialog.canvas)["width"]
        dpg.set_viewport_width(1440)
        for _ in range(5):
            run_callback_jobs(dpg.get_callback_queue() or [])
            host.pump()
            dpg.render_dearpygui_frame()
        assert dpg.get_item_configuration(dialog.canvas)["width"] > before
        dialog._begin_pick("manual")
        dialog.reject()
        assert dialog._pick_mode is None
        assert dialog.winfo_exists()
    finally:
        if dialog is not None:
            dialog.reject()
        dpg.destroy_context()


@pytest.mark.windows_native
@pytest.mark.skipif(sys.platform != "win32", reason="Requires the Windows DearPyGui runtime")
def test_dataset_refresh_and_active_sorted_csv_controls(tmp_path):
    import dearpygui.dearpygui as dpg
    from WinUx.ui import StandaloneUiHost, configure_ui_context
    from WinUx.plotdigitizer.ui import PlotDigitizerDialog
    from WinUx.runtime.dpg_callbacks import run_callback_jobs

    dpg.create_context()
    dialog = None
    try:
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        dpg.create_viewport(title="Dataset and CSV workflow", width=1240, height=820)
        dpg.setup_dearpygui()
        dialog = PlotDigitizerDialog(host)
        dpg.set_primary_window(dialog.tag, True)
        dpg.show_viewport()

        def pump():
            for _ in range(3):
                run_callback_jobs(dpg.get_callback_queue() or [])
                host.pump()
                dpg.render_dearpygui_frame()
                time.sleep(.01)

        image_path = tmp_path / "chart.png"
        Image.new("RGB", (121, 121), "white").save(image_path)
        dialog._open_image(str(image_path))
        for key, px, py, value in (("x1", 10, 110, 0), ("x2", 110, 110, 10),
                                   ("y1", 10, 110, 0), ("y2", 10, 10, 100)):
            dialog.engine.set_anchor(key, px, py, value)
        dialog.engine.add_manual_point(90, 20)
        dialog.engine.add_manual_point(30, 80)
        pump()
        dialog._point_selected("manual:0")
        dialog._sample_pixel = (90, 20)
        dialog.engine.update_dataset(locked=True)
        dialog.engine.duplicate_dataset()
        assert dialog.engine.active_dataset.name == "Serie-1 (copy)"
        pump()
        assert dialog.engine.active_dataset.name == "Serie-1 (copy)", dialog.engine.to_result_dict()
        assert dialog.dataset_list.currentKey() == 1
        assert dpg.get_value(dialog.dataset_name) == "Serie-1 (copy)"
        assert not dialog.engine.active_dataset.locked
        assert dialog._selected_point is None
        assert dialog._sample_pixel is None
        assert len(dialog.result_grid.rows) == 2
        dialog._show_tool("data")
        pump()
        assert dpg.get_item_state(dialog.export_scope)["visible"]
        dpg.set_value(dialog.export_scope, "Active dataset")
        dpg.set_value(dialog.export_sort_x, True)
        path = tmp_path / "active.csv"
        dialog._export_csv(str(path))
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert {row["Dataset"] for row in rows} == {"Serie-1 (copy)"}
        assert [float(row["X"]) for row in rows] == [2, 8]
        assert dpg.get_value(dialog.status) == "CSV exported."
        dialog._undo()
        pump()
        assert dialog.dataset_list.currentKey() == 0
        assert dialog.engine.active_dataset.locked
        assert not dpg.get_item_configuration(dialog.dataset_name)["enabled"]
        assert len(dialog.engine.datasets) == 1
    finally:
        if dialog is not None:
            dialog.destroy()
        dpg.destroy_context()


@pytest.mark.windows_native
@pytest.mark.skipif(sys.platform != "win32", reason="Requires the Windows DearPyGui runtime")
def test_area_color_point_editor_history_and_cursor_zoom(tmp_path):
    from unittest.mock import patch
    import dearpygui.dearpygui as dpg
    from WinUx.ui import StandaloneUiHost, configure_ui_context
    from WinUx.plotdigitizer.ui import PlotDigitizerDialog
    from WinUx.runtime.dpg_callbacks import run_callback_jobs

    image = Image.new("RGB", (201, 121), "white")
    draw = ImageDraw.Draw(image)
    draw.line((21, 100, 179, 30), fill=(220, 30, 50), width=3)
    draw.line((21, 80, 179, 20), fill=(30, 100, 220), width=1)
    path = tmp_path / "curves.png"
    image.save(path)
    dpg.create_context()
    host = StandaloneUiHost(dpg)
    configure_ui_context(host)
    dialog = None
    try:
        dpg.create_viewport(title="Digitizer editing check", width=1240, height=820)
        dpg.setup_dearpygui()
        dialog = PlotDigitizerDialog(host)
        dpg.set_primary_window(dialog.tag, True)
        dpg.show_viewport()
        dialog._open_image(str(path))

        def frame():
            run_callback_jobs(dpg.get_callback_queue() or [])
            host.pump()
            dpg.render_dearpygui_frame()

        for _ in range(4):
            frame()
        assert not dpg.get_item_configuration(dialog.palette_combo)["show"]
        assert not dpg.get_item_configuration(dialog.point_editor_container)["show"]
        picker_config = dpg.get_item_configuration(dialog.curve_color.swatch)
        assert dpg.get_item_info(dialog.curve_color.swatch)["type"].endswith("::mvColorEdit")
        assert not picker_config["no_picker"]

        def mouse_at(px, py):
            (ox, oy), _ = dialog._canvas_rect()
            x, y = dialog._image_to_canvas(px, py)
            return ox + x, oy + y

        position = [mouse_at(20, 10)]
        with patch.object(dialog, "_mouse_in_canvas", return_value=True), \
                patch.object(dpg, "get_mouse_pos", side_effect=lambda **_: position[0]):
            dialog._begin_pick("area")
            dialog._mouse_left()
            position[0] = mouse_at(180, 110)
            dialog._mouse_move()
            dialog._mouse_left_up()
        assert dialog.engine.plot_rect == (20, 10, 180, 110)
        for key, value in (("x1", "0"), ("x2", "3.2"), ("y1", "0"), ("y2", "2000")):
            dpg.set_value(dialog.anchor_value[key], value)
        dialog._calibrate_area()
        frame()
        assert dialog.engine.pixel_to_data(100, 60) == pytest.approx((1.6, 1000))
        assert "2000" in dpg.get_value(dialog.calibration_info)
        dialog._auto_color()
        assert len(dialog._palette) == 2
        picker_config["callback"](dialog.curve_color.swatch, [30.0, 100.0, 220.0, 255.0], None)
        frame()
        assert dpg.get_value(dialog.curve_color.editor.tag) == "#1E64DC"
        dialog._extract_curve()
        deadline = time.monotonic() + 5
        while dialog._smart_runner.busy:
            frame()
            assert time.monotonic() < deadline
            time.sleep(.005)
        frame()
        assert dialog.engine.active_dataset.curve_rgb == (30, 100, 220)
        assert dialog.engine.active_dataset.extracted_pixels[0][1] == 80
        original_count = len(dialog.engine.active_dataset.extracted_pixels)
        dialog.result_grid.setCurrentKey("auto:70", select=True)
        assert dpg.get_item_configuration(dialog.point_editor_container)["show"]
        dpg.set_value(dialog.point_x, "1.6")
        dpg.set_value(dialog.point_y, "1000")
        dialog._apply_point()
        frame()
        assert dialog.engine.point_pixels("auto", 70) == pytest.approx((100, 60))
        dpg.set_value(dialog.coordinate_mode, "Image pixels")
        dialog._refresh_grid()
        assert dpg.get_value(dialog.point_x) == "100"
        dialog._delete_points()
        frame()
        assert len(dialog.engine.active_dataset.extracted_pixels) == original_count - 1
        dialog._undo()
        frame()
        assert dpg.get_item_configuration(dialog.point_editor_container)["show"]
        assert not dpg.get_item_configuration(dialog.point_fields)["show"]
        assert len(dialog.engine.active_dataset.extracted_pixels) == original_count
        assert dialog.engine.point_pixels("auto", 70) == pytest.approx((100, 60))
        dialog.result_grid.setCurrentKey("auto:70", select=True)
        assert dialog._selected_point == ("auto", 70)
        dialog._clear_points()
        frame()
        assert not dialog.engine.active_dataset.extracted_pixels
        dialog._undo()
        frame()
        assert len(dialog.engine.active_dataset.extracted_pixels) == original_count
        cursor = mouse_at(100, 60)
        before = dialog._canvas_to_image(cursor)
        dialog._zoom_at(1.5, mouse=cursor)
        assert dialog._canvas_to_image(cursor) == pytest.approx(before)
        dialog._begin_pick("manual")
        dialog._cursor_pixel = (100, 60)
        dialog._paint_pointer()
        assert len(dpg.get_item_children(dialog._pointer_layer, 2)) >= 5
        dialog._cancel_pick()
        dialog.engine.update_dataset(locked=True)
        frame()
        assert not dpg.get_item_configuration(dialog.extract_button)["enabled"]
        assert not dpg.get_item_configuration(dialog.curve_color.swatch)["enabled"]
        picker_config["callback"](dialog.curve_color.swatch, [255, 0, 0, 255], None)
        assert dialog.engine.active_dataset.curve_rgb == (30, 100, 220)
        dialog._begin_pick("edit")
        assert dialog._pick_mode is None
        dialog.engine.add_dataset("Curve 1")
        frame()
        assert len(dialog.dataset_list.items) == 2
        dialog.dataset_list.setCurrentKey(0, select=True)
        frame()
        dialog.dataset_list.setCurrentKey(1, select=True)
        frame()
        assert dialog.engine.active_dataset_index == 1
    finally:
        if dialog is not None:
            dialog.destroy()
        dpg.destroy_context()
