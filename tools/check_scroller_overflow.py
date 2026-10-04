"""Verify overflow bars after deferred column layout and content resizing.

Run with abaqus python. Requires a desktop; --output-dir optionally saves an
image to an existing directory. Uses callback stubs without server/file jobs.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
import dearpygui.dearpygui as dpg
from WinUx.view import WinUXView
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.components.explorer_list_view import ListViewItem
from WinUx.components.shared_scroller import SharedScrollerMetrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir is not None and not args.output_dir.is_dir():
        parser.error("--output-dir must be an existing directory")
    view = WinUXView({key: lambda *a, **k: "" for key in REQUIRED_CALLBACK_KEYS})
    try:
        dpg.configure_viewport(0, width=1040, height=760)
        view._top_ratio = 0.4
        view._layout_dirty = True
        for panel, count in ((view.left, 7), (view.right, 5)):
            lv = panel.listview
            lv.preserve_column_widths_on_startup = True
            lv._column_widths.update(name=180, date=100, type=80, size=60)
            lv.set_items([ListViewItem("Model_%02d.inp" % n) for n in range(count)])
            lv.set_pinned_item(ListViewItem("..", is_dir=True))
        dpg.show_viewport()

        def frames(count=6):
            for _ in range(count):
                # A competing component replaces the per-ListView callback.
                dpg.set_frame_callback(dpg.get_frame_count()+1, lambda: None)
                view.update()

        frames(20)
        for panel in view.panels:
            lv = panel.listview
            lv._layout_all()
        frames()
        for panel in view.panels:
            assert dpg.get_x_scroll_max(panel.listview.body_window) == 0

        # This flag is also set by FilePanel.resize(). If its frame callback is
        # lost, new column widths never reach the body canvas/scroll range.
        for panel in view.panels:
            lv = panel.listview
            lv._column_widths.update(name=500, date=180, type=120, size=80)
            lv._resize_layout_pending = True
            lv._queue_layout()
        frames()
        for panel in view.panels:
            lv = panel.listview
            assert not lv._resize_layout_pending
            assert dpg.get_x_scroll_max(lv.body_window) > 0, "wide columns lack horizontal scroll range"
            assert dpg.get_item_configuration(lv._scroller_arrow_overlay._parts["h_thumb"])["show"]
        assert dpg.get_y_scroll_max(view.left.listview.body_window) > 0
        assert dpg.get_y_scroll_max(view.right.listview.body_window) == 0

        # A generic resize of the native child must not let it cover the
        # separate scrollbar gutters. The wrapper owns the outer dimensions.
        for panel in view.panels:
            dpg.configure_item(panel.listview.body_window, height=-1, horizontal_scrollbar=False)
        frames()
        for panel in view.panels:
            config = dpg.get_item_configuration(panel.listview.body_window)
            assert config["height"] == -SharedScrollerMetrics.THICKNESS
            assert config["horizontal_scrollbar"]

        dpg.configure_viewport(0, width=860)
        view._layout_dirty = True
        frames(12)
        for panel in view.panels:
            assert dpg.get_x_scroll_max(panel.listview.body_window) > 0

        pixels = []
        dpg.output_frame_buffer(callback=lambda sender, data: pixels.append(data))
        frames()
        assert pixels
        width = dpg.get_viewport_client_width()
        for panel in view.panels:
            overlay = panel.listview._scroller_arrow_overlay
            for axis in ("v", "h"):
                thumb = dpg.get_item_configuration(overlay._parts[axis+"_thumb"])
                if not thumb["show"]:
                    continue
                x = int((thumb["pmin"][0]+thumb["pmax"][0])/2+overlay._origin[0])
                y = int((thumb["pmin"][1]+thumb["pmax"][1])/2+overlay._origin[1])
                index = (y*width+x)*4
                pixel = [pixels[0][index+c]*255 for c in range(3)]
                assert all(110 <= c <= 165 for c in pixel), (panel.panel_id, axis, pixel)
        if args.output_dir is not None:
            dpg.output_frame_buffer(str(args.output_dir / "scroller_overflow.png"))
            frames()
        for panel in view.panels:
            lv = panel.listview
            lv._column_widths.update(name=140, date=80, type=60, size=40)
            lv.set_items([ListViewItem("Model.inp")])
        frames()
        for panel in view.panels:
            lv = panel.listview
            overlay = lv._scroller_arrow_overlay
            assert dpg.get_x_scroll_max(lv.body_window) == 0
            assert dpg.get_y_scroll_max(lv.body_window) == 0
            assert not dpg.get_item_configuration(overlay._parts["h_thumb"])["show"]
            assert not dpg.get_item_configuration(overlay._parts["v_thumb"])["show"]
        print("PASS: deferred column overflow shows horizontal thumbs in both panels;")
        print("      vertical overflow is detected independently; gutters survive content resizing.")
        print("      Removing overflow hides the corresponding thumbs again.")
    finally:
        view.destroy()
        view._destroy_components()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
