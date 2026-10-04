"""Check startup overflow without mouse movement or an extra layout call.

Run with abaqus python. Optional --output-dir saves a screenshot to an existing
directory. Seeds a stale, narrow body canvas while the column headers overflow.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
import dearpygui.dearpygui as dpg
from WinUx.components.explorer_list_view import ExplorerListView


def check_main_startup(output_dir):
    from WinUx.view import WinUXView
    from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
    from WinUx.components.explorer_list_view import ListViewItem

    view = WinUXView({key: lambda *a, **k: "" for key in REQUIRED_CALLBACK_KEYS})
    try:
        dpg.show_viewport()
        for panel, count in ((view.left, 7), (view.right, 5)):
            lv = panel.listview
            lv.set_items([ListViewItem(name) for name in ("C.inp", "A.inp", "B.inp")])
            # Exercise the real native draw-item contract in both directions,
            # including hiding the previous column's sort marker.
            for key, ascending in (("name", True), ("name", False), ("date", True)):
                # Match header-click dispatch, rather than set_sort(), which
                # bypasses the immediate indicator update that once crashed.
                lv.sort_key = key
                lv.sort_ascending = ascending
                lv._update_header_sort_indicator()
                indicator = lv._header_items[key]["indicator"]
                assert dpg.get_item_info(indicator)["type"] == "mvAppItemType::mvDrawTriangle"
                config = dpg.get_item_configuration(indicator)
                assert config["show"]
                assert abs(config["p3"][1] - config["p1"][1]) == 5.0
                assert (config["p3"][1] < config["p1"][1]) == ascending
                for other_key, parts in lv._header_items.items():
                    if other_key != key:
                        assert not dpg.get_item_configuration(parts["indicator"])["show"]
                lv._schedule_sort_refresh()
                for _ in range(2):
                    dpg.render_dearpygui_frame()
                    dpg.run_callbacks(dpg.get_callback_queue())
                if key == "name":
                    expected = sorted(("C.inp", "A.inp", "B.inp"), reverse=not ascending)
                    assert [item.name for item in lv.items] == expected
            lv.set_sort("name", ascending=True)
            lv.preserve_column_widths_on_startup = True
            lv._column_widths.update(name=500, date=180, type=120, size=80)
            lv.set_items([ListViewItem("Model_%02d.inp" % n) for n in range(count)])
            lv.set_pinned_item(ListViewItem("..", is_dir=True))
            panel.status.set("%d items" % count)
            dpg.configure_item(lv.body_canvas, width=180, height=lv.ROW_HEIGHT)
            lv._resize_layout_pending = False
        # Match WinUXView.run(): resolve native viewport dimensions, fit the
        # main layout, then commit that geometry before normal UI iterations.
        dpg.render_dearpygui_frame()
        view._pending_viewport_size = None
        view._resize_last_event = 0.0
        view._layout_dirty = True
        view._apply_split_layout(force=True)
        dpg.render_dearpygui_frame()
        for _ in range(5):
            dpg.set_frame_callback(dpg.get_frame_count()+1, lambda: None)
            view.update()
            for panel in view.panels:
                lv = panel.listview
                assert sum(lv._column_widths.values()) > dpg.get_item_rect_size(lv.body_window)[0]
                overlay = lv._scroller_arrow_overlay
                assert dpg.get_item_configuration(overlay._parts["h_thumb"])["show"], (
                    panel.panel_id, overlay._content_extent, overlay._target_rect(),
                    overlay._target_is_shown(), dpg.get_item_rect_size(lv.body_window),
                    dpg.get_item_state(lv.window_tag))
        pixels = []
        dpg.output_frame_buffer(callback=lambda sender, data: pixels.append(data))
        for _ in range(5):
            view.update()
        assert pixels
        for panel in view.panels:
            overlay = panel.listview._scroller_arrow_overlay
            thumb = dpg.get_item_configuration(overlay._parts["h_thumb"])
            x = int((thumb["pmin"][0]+thumb["pmax"][0])/2+overlay._origin[0])
            y = int((thumb["pmin"][1]+thumb["pmax"][1])/2+overlay._origin[1])
            index = (y*dpg.get_viewport_client_width()+x)*4
            pixel = [pixels[0][index+c]*255 for c in range(3)]
            assert all(110 <= c <= 165 for c in pixel), (panel.panel_id, pixel)
        if output_dir is not None:
            dpg.output_frame_buffer(str(output_dir / "scroller_main_startup.png"))
            for _ in range(5):
                view.update()
        print("PASS: both Local/Server horizontal thumbs are visible on cold startup;")
        print("      checked real pixels with 7/5 rows and no mouse movement or manual relayout.")
    finally:
        view.destroy()
        view._destroy_components()
        dpg.destroy_context()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--main-layout", action="store_true")
    args = parser.parse_args()
    if args.output_dir is not None and not args.output_dir.is_dir():
        parser.error("--output-dir must be an existing directory")
    if args.main_layout:
        check_main_startup(args.output_dir)
        return
    dpg.create_context()
    dpg.configure_app(manual_callback_management=True)
    dpg.create_viewport(title="WinUx startup overflow check", width=660, height=440)
    view = None
    try:
        with dpg.window(tag="startup_window", pos=(20, 20), width=600, height=360):
            view = ExplorerListView("startup_window", width=550, height=290,
                                    preserve_column_widths_on_startup=True)
        view._column_widths.update(name=500, date=180, type=120, size=80)
        view._layout_all()
        # Header geometry is wide; stale initial content measurement says fit.
        dpg.configure_item(view.body_canvas, width=180, height=view.ROW_HEIGHT)
        view._resize_layout_pending = False
        overlay = view._scroller_arrow_overlay
        overlay._pointer = lambda: (-100, -100)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        for _ in range(5):
            dpg.set_frame_callback(dpg.get_frame_count()+1, lambda: None)
            dpg.render_dearpygui_frame()
            dpg.run_callbacks(dpg.get_callback_queue())
            overlay.update()
            viewport = dpg.get_item_rect_size(view.body_window)
            assert sum(view._column_widths.values()) > viewport[0]
            assert dpg.get_item_configuration(overlay._parts["h_thumb"])["show"], (
                "startup columns overflow but horizontal thumb is hidden", viewport,
                dpg.get_x_scroll_max(view.body_window))
        assert dpg.get_item_configuration(view.body_canvas)["width"] == 880
        pixels = []
        dpg.output_frame_buffer(callback=lambda sender, data: pixels.append(data))
        for _ in range(5):
            dpg.render_dearpygui_frame()
            dpg.run_callbacks(dpg.get_callback_queue())
            overlay.update()
        assert pixels
        thumb = dpg.get_item_configuration(overlay._parts["h_thumb"])
        x = int((thumb["pmin"][0]+thumb["pmax"][0])/2+overlay._origin[0])
        y = int((thumb["pmin"][1]+thumb["pmax"][1])/2+overlay._origin[1])
        index = (y*dpg.get_viewport_client_width()+x)*4
        pixel = [pixels[0][index+c]*255 for c in range(3)]
        assert all(110 <= c <= 165 for c in pixel), pixel
        if args.output_dir is not None:
            dpg.output_frame_buffer(str(args.output_dir / "scroller_startup.png"))
            for _ in range(5):
                dpg.render_dearpygui_frame()
                dpg.run_callbacks(dpg.get_callback_queue())
        print("PASS: overflowing startup columns show a visible horizontal thumb,")
        print("      even with zero rows, stale initial canvas size and replaced callbacks.")
    finally:
        if view is not None:
            view.destroy()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
