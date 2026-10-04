"""Check scrollbar/status separation in the real main layout after resizing.

Run with abaqus python. Optional --output-dir saves a screenshot to an existing
directory. Callback stubs keep the check independent of servers and file jobs.
"""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
import dearpygui.dearpygui as dpg
from WinUx.view import WinUXView
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.components.explorer_list_view import ListViewItem
from WinUx.components.shared_scroller import dpg_window_rect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir is not None and not args.output_dir.is_dir():
        parser.error("--output-dir must be an existing directory")
    view = WinUXView({key: lambda *args, **kwargs: "" for key in REQUIRED_CALLBACK_KEYS})
    try:
        for panel in view.panels:
            panel.listview.set_items([ListViewItem("Model_%02d.inp" % n) for n in range(30)])
            panel.listview.set_pinned_item(ListViewItem("..", is_dir=True))
            panel.status.set("30 items")
        dpg.configure_viewport(0, height=900)
        dpg.show_viewport()

        def frames(count=6):
            for _ in range(count):
                # Reproduce frame-callback contention without mouse movement.
                dpg.set_frame_callback(dpg.get_frame_count()+1, lambda: None)
                view.update()

        def check():
            status_rect = dpg_window_rect(dpg, view.file_status_region)
            assert status_rect is not None
            for panel in view.panels:
                overlay = panel.listview._scroller_arrow_overlay
                rect = panel.listview._body_viewport_rect()
                assert rect is not None
                assert rect[3] <= status_rect[1], (rect, status_rect)
                for tag in list(overlay._parts.values()) + list(overlay._rects.values()):
                    config = dpg.get_item_configuration(tag)
                    if config["show"]:
                        assert config["pmax"][1] + overlay._origin[1] <= status_rect[1], (tag, config, status_rect)
                track = dpg.get_item_configuration(overlay._parts["h_track"])
                assert dpg.get_item_configuration(overlay._parts["h_thumb"])["show"]
                assert track["pmax"][1] + overlay._origin[1] == rect[3], (track, rect)
                text = dpg.get_item_state(panel.status_tag)
                assert text["visible"]
                assert text["rect_min"][1] >= rect[3]

        frames(20)
        check()
        before = view.left.listview._body_viewport_rect()
        view._top_ratio = 0.4
        view._layout_dirty = True
        frames()
        check()
        after = view.left.listview._body_viewport_rect()
        assert after[3] < before[3], (before, after)
        dpg.configure_viewport(0, height=620)
        frames(12)
        check()

        # Expanded chrome must also stay above the status text.
        for panel in view.panels:
            overlay = panel.listview._scroller_arrow_overlay
            rect = panel.listview._body_viewport_rect()
            overlay._pointer = lambda rect=rect: (rect[2]-3, rect[3]-3)
        for _ in range(5):
            for panel in view.panels:
                panel.listview._scroller_arrow_overlay._last_time = time.monotonic()-0.05
            frames(1)
        check()
        if args.output_dir is not None:
            dpg.output_frame_buffer(str(args.output_dir / "scroller_status.png"))
            frames()
        print("PASS: both file scrollers stay above visible status text after splitter")
        print("      and viewport resizing, even when frame callbacks are replaced.")
    finally:
        view.destroy()
        view._destroy_components()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
