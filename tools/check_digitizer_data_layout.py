"""Render Plot Digitizer and inspect real View Data visibility/scroll ranges."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.runtime.dpg_callbacks import run_callback_jobs


def main():
    dpg.create_context()
    dialog = None
    try:
        NativeWindowBackend(dpg).enable()
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        dpg.create_viewport(title="Digitizer data layout check", width=1280, height=820)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dialog = PlotDigitizerDialog(host)

        def pump(frames=12):
            for _ in range(frames):
                run_callback_jobs(dpg.get_callback_queue() or [])
                host.pump()
                dpg.render_dearpygui_frame()
                time.sleep(.004)

        dialog.engine.active_dataset.extracted_pixels = [(i, i * 2) for i in range(80)]
        dialog._refresh_all()
        dialog._show_tool("data")
        pump()
        assert len(dialog.result_grid.rows) == 80
        cell = next(iter(dialog.result_grid._cell_text_items.values()))[0]
        assert dpg.get_item_state(cell)["visible"], "View Data's first row is clipped below the panel"
        assert dpg.get_item_state(dialog.reduce_samples_button)["visible"]
        assert dialog.result_grid.rows[0][1] == (1, "0", "0"), dialog.result_grid.rows[0]
        assert dpg.get_y_scroll_max(dialog.dataset_panel) == 0
        if dpg.get_y_scroll_max(dialog.settings_panel) >= 30:
            from WinUx.ui.workspace import item_rect
            print("LAYOUT_DIAGNOSTIC", "grid_height=", dialog._data_grid_height,
                  "panel=", item_rect(dialog.settings_panel), "tail=", item_rect(dialog.point_info),
                  "export=", item_rect(dialog.export_data_button),
                  "scroll=", dpg.get_y_scroll_max(dialog.settings_panel))
        assert dpg.get_y_scroll_max(dialog.settings_panel) < 30
        print("DIGITIZER_VIEW_DATA_OK", "rows=", len(dialog.result_grid.rows),
              "first_row_visible=", dpg.get_item_state(cell)["visible"])
        assert "80 points" in dialog.control_value(dialog.data_summary)
        assert "px" in dialog.control_value(dialog.data_summary)
        initial_height = dialog._data_grid_height
        dpg.configure_item(dialog.tag, width=1240, height=940)
        pump(24)
        assert dialog._data_grid_height > initial_height, (initial_height, dialog._data_grid_height)
        assert dpg.get_y_scroll_max(dialog.settings_panel) < 30
        dialog.result_grid.setCurrentKey("auto:12", select=True)
        pump()
        assert dialog._selected_point == ("auto", 12)
        assert dpg.get_item_state(dialog.apply_point_button)["visible"]
        assert "1 selected" in dialog.control_value(dialog.data_summary)
        dialog._select_all_data_points()
        assert len(dialog.result_grid.selectedKeys()) == 80
        assert "80 selected" in dialog.control_value(dialog.data_summary)
        dialog._clear_data_selection()
        pump()
        assert not dialog.result_grid.selectedKeys()
        assert dialog._selected_point is None
        dialog.result_grid.setCurrentKey("auto:0", select=True)
        dialog._delete_points()
        pump()
        assert len(dialog.result_grid.rows) == 79
        assert dialog.engine.undo()
        pump()
        assert len(dialog.result_grid.rows) == 80
        dialog.engine.active_dataset.locked = True
        dialog._refresh_all()
        dialog._select_all_data_points()
        assert not dpg.get_item_configuration(dialog.delete_points_button)["enabled"]
        dialog.engine.active_dataset.locked = False
        dialog._clear_data_selection()
        dialog._refresh_all()
        pump()
        print("DIGITIZER_DATA_ACTIONS_OK", "selection/delete/undo/lock/resize")
        assert not dpg.get_item_configuration(dialog.export_data_button)["enabled"]
        for key, px, py, value in (("x1", 0, 0, 0), ("x2", 79, 0, 7.9),
                                    ("y1", 0, 0, 0), ("y2", 0, 158, 15.8)):
            dialog.engine.set_anchor(key, px, py, value)
        pump()
        assert dpg.get_item_configuration(dialog.export_data_button)["enabled"]
        assert "X/Y" in dialog.control_value(dialog.data_summary)
        import csv
        import tempfile
        temporary_root = Path.home() / "AppData/Local/Temp/opencode"
        with tempfile.TemporaryDirectory(dir=str(temporary_root)) as temporary:
            path = str(Path(temporary) / "digitizer.csv")
            dialog._export_csv(path)
            with open(path, encoding="utf-8", newline="") as stream:
                exported = list(csv.reader(stream))
            assert len(exported) == 81, len(exported)
            assert exported[0] == ["Dataset", "Index", "X", "Y", "PixelX", "PixelY", "Source"]
        dialog.engine.add_dataset("Empty series")
        pump()
        assert not dialog.result_grid.rows
        assert "No points" in dialog.control_value(dialog.data_summary)
        assert not dpg.get_item_configuration(dialog.select_all_points_button)["enabled"]
        print("DIGITIZER_CSV_EMPTY_STATE_OK")
        dialog._show_tool("automatic")
        pump(5)
        maximum = dpg.get_y_scroll_max(dialog.settings_panel)
        assert maximum == 0, ("Automatic Extraction should fit without outer scrolling", maximum)
        print("DIGITIZER_AUTOMATIC_LAYOUT_OK", "outer_scroll_max=", maximum)
    finally:
        if dialog is not None:
            dialog.destroy()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
