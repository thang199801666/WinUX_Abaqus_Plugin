"""Real Dear PyGui/Explorer smoke check; run with ``abaqus python``.

Optional --output-dir saves collapsed/expanded screenshots to an existing
directory. This check opens a short-lived viewport and requires a desktop.
"""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx  # Set up the bundled native backend before importing Dear PyGui.
import dearpygui.dearpygui as dpg
from WinUx.components.explorer_list_view import ExplorerListView, ListViewItem
from WinUx.components.shared_scroller import SharedScrollerMetrics, SharedScrollerPalette


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir is not None and not args.output_dir.is_dir():
        parser.error("--output-dir must be an existing directory")

    dpg.create_context()
    dpg.configure_app(manual_callback_management=True)
    dpg.create_viewport(title="WinUx scroller render check", width=660, height=440)
    view = None
    try:
        with dpg.window(tag="scroller_check_window", pos=(20, 20), width=600, height=360):
            with dpg.child_window(tag="scroller_check_parent", width=560, height=300):
                view = ExplorerListView(
                    "scroller_check_parent", width=530, height=265,
                    items=[ListViewItem("Model_%02d.inp" % index,
                                        path="D:/Project/Model_%02d.inp" % index,
                                        size=4096, mtime=1700000000) for index in range(30)],
                    preserve_column_widths_on_startup=True)
                view.set_pinned_item(ListViewItem("..", path="D:/Project", is_dir=True))
        overlay = view._scroller_arrow_overlay
        dpg.setup_dearpygui()
        dpg.show_viewport()

        def frame():
            overlay.update()
            dpg.render_dearpygui_frame()
            dpg.run_callbacks(dpg.get_callback_queue())

        for _ in range(12):
            frame()
        assert dpg.get_y_scroll_max(view.body_window) > 0
        assert dpg.get_x_scroll_max(view.body_window) > 0
        assert "visible" not in dpg.get_item_state(view.body_window)
        rect = view._body_viewport_rect()
        assert rect is not None and overlay._target_rect() == rect
        original_pointer = overlay._pointer

        # Native tooltips use IsItemHovered() on the last rendered item.
        # Each tooltip must immediately follow its row-canvas group in the
        # SAME window; attaching after EndChild loses hover on nested content.
        for parts, anchor, canvas, host, item in (
                (view._body_item_tooltip, view.body_tooltip_anchor, view.body_canvas,
                 view.body_window, view.items[0]),
                (view._pinned_item_tooltip, view.pinned_tooltip_anchor, view.pinned_canvas,
                 view.window_tag, view._pinned_item)):
            assert dpg.get_item_parent(parts["tag"]) == host
            assert dpg.get_item_parent(anchor) == host
            assert dpg.get_item_parent(canvas) == anchor
            children = dpg.get_item_children(host, 1)
            assert children.index(dpg.get_alias_id(parts["tag"])) == children.index(dpg.get_alias_id(anchor))+1
            assert dpg.get_item_info(anchor)["hover_handler_applicable"]
            assert dpg.get_item_rect_min(anchor) == dpg.get_item_rect_min(canvas)
            before = {tag: dpg.get_item_configuration(tag) for tag in overlay._parts.values()}
            view._show_tooltip_parts(parts, item)
            overlay.update()
            title, details, path = view._item_tooltip_content(item)
            assert dpg.get_value(parts["title"]) == title
            assert dpg.get_value(parts["details"]) == details
            assert dpg.get_value(parts["path"]) == path
            assert {tag: dpg.get_item_configuration(tag) for tag in overlay._parts.values()} == before
            view._hide_tooltip_parts(parts)
        assert "Date modified:" in view._item_tooltip_content(view.items[0])[1]
        assert "Size:" in view._item_tooltip_content(view.items[0])[1]
        assert view._item_tooltip_content(view._pinned_item)[0] == "Parent folder"

        def capture(name):
            if args.output_dir is not None:
                dpg.output_frame_buffer(str(args.output_dir / (name + ".png")))
                for _ in range(5):
                    frame()

        overlay._pointer = lambda: (-100, -100)
        for _ in range(5):
            overlay._last_time = time.monotonic() - 0.05
            frame()
        collapsed = dpg.get_item_configuration(overlay._parts["v_track"])
        assert not collapsed["show"]
        for axis in ("v", "h"):
            assert not dpg.get_item_configuration(overlay._parts[axis+"_mask"])["show"]
            assert not dpg.get_item_configuration(overlay._parts[axis+"_track"])["show"]
            assert dpg.get_item_configuration(overlay._parts[axis+"_thumb"])["show"]
        assert not dpg.get_item_configuration(overlay._parts["corner"])["show"]
        assert collapsed["pmax"][0] - collapsed["pmin"][0] == SharedScrollerMetrics.COLLAPSED_THICKNESS
        for direction in ("up", "down", "left", "right"):
            assert not dpg.get_item_configuration(overlay._rects[direction])["show"]
            assert not dpg.get_item_configuration(overlay._arrows[direction])["show"]
        capture("scroller_collapsed")
        collapsed_pixels = []
        dpg.output_frame_buffer(callback=lambda sender, app_data: collapsed_pixels.append(app_data))
        for _ in range(5):
            frame()
        assert collapsed_pixels
        for x, y in ((int(rect[2]-9), int(rect[1]+40)),
                     (int(rect[0]+40), int(rect[3]-9)),
                     (int(rect[2]-5), int(rect[3]-5))):
            index = (y*dpg.get_viewport_client_width()+x)*4
            pixel = [collapsed_pixels[0][index+channel]*255 for channel in range(3)]
            assert all(abs(a-b) < 3 for a, b in zip(pixel, view.theme_config["background"])), pixel

        overlay._pointer = lambda: (rect[2]-8, rect[3]-8)
        for _ in range(5):
            overlay._last_time = time.monotonic() - 0.05
            frame()
        expanded = dpg.get_item_configuration(overlay._parts["v_track"])
        assert expanded["pmax"][0] - expanded["pmin"][0] == SharedScrollerMetrics.THICKNESS
        for direction in ("up", "down", "left", "right"):
            assert dpg.get_item_configuration(overlay._rects[direction])["show"]
            assert dpg.get_item_configuration(overlay._arrows[direction])["show"]
        assert dpg.get_item_info(overlay.layer)["type"].endswith("::mvDrawlist")
        assert tuple(dpg.get_item_rect_min(overlay.layer)) == overlay._origin
        assert dpg.get_item_configuration(view.body_window)["no_scrollbar"]
        baseline_pixels = []
        dpg.output_frame_buffer(callback=lambda sender, app_data: baseline_pixels.append(app_data))
        for _ in range(5):
            frame()
        assert baseline_pixels, "framebuffer callback did not run"
        for axis in ("v", "h"):
            thumb = dpg.get_item_configuration(overlay._parts[axis+"_thumb"])
            x = int((thumb["pmin"][0]+thumb["pmax"][0])/2+overlay._origin[0])
            y = int((thumb["pmin"][1]+thumb["pmax"][1])/2+overlay._origin[1])
            index = (y*dpg.get_viewport_client_width()+x)*4
            pixel = [baseline_pixels[0][index+channel]*255 for channel in range(3)]
            assert all(abs(a-b) < 3 for a, b in zip(pixel, SharedScrollerPalette.THUMB_HOVER)), pixel
        capture("scroller_expanded")

        # Scroll position changes must not move the viewport-space chrome.
        dpg.set_y_scroll(view.body_window, 120)
        for _ in range(3):
            frame()
        assert view._body_viewport_rect() == rect

        # A popup over both gutters must naturally cover the component skin.
        # Check actual framebuffer pixels, not just draw-item visibility.
        chrome_before = {tag: dpg.get_item_configuration(tag) for tag in overlay._parts.values()}
        popup_color = (255, 255, 220)
        with dpg.theme() as popup_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (*popup_color, 255))
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0)
        with dpg.window(tag="scroller_check_popup", pos=(rect[2]-80, rect[3]-60),
                        width=140, height=130, min_size=(1, 1), show=False,
                        no_title_bar=True, no_resize=True, no_saved_settings=True):
            dpg.add_text("Popup above scroller")
        dpg.bind_item_theme("scroller_check_popup", popup_theme)
        dpg.show_item("scroller_check_popup")
        for _ in range(5):
            frame()
        for axis in ("v", "h"):
            assert dpg.get_item_configuration(overlay._parts[axis+"_mask"])["show"]
            assert dpg.get_item_configuration(overlay._parts[axis+"_track"])["show"]
        for tag, config in chrome_before.items():
            assert dpg.get_item_configuration(tag) == config, tag
        pixels = []
        dpg.output_frame_buffer(callback=lambda sender, app_data: pixels.append(app_data))
        for _ in range(5):
            frame()
        assert pixels, "framebuffer callback did not run"
        width = dpg.get_viewport_client_width()
        for x, y in ((int(rect[2]-4), int(rect[3]-30)),
                     (int(rect[2]-40), int(rect[3]-4))):
            index = (y*width+x)*4
            pixel = [pixels[0][index+channel] for channel in range(3)]
            if max(pixel) <= 1.0:
                pixel = [channel*255 for channel in pixel]
            assert all(abs(a-b) < 3 for a, b in zip(pixel, popup_color)), pixel
        capture("scroller_popup")
        dpg.hide_item("scroller_check_popup")
        for _ in range(4):
            frame()
        assert dpg.get_item_configuration(overlay._parts["v_track"])["show"]
        assert dpg.get_item_configuration(overlay._parts["h_track"])["show"]

        dpg.hide_item("scroller_check_parent")
        frame()
        assert not dpg.get_item_configuration(overlay._parts["v_track"])["show"]
        overlay._pointer = original_pointer
        print("PASS: real Explorer renders track, thumb and all end buttons;")
        print("      hover expands 6 -> 11 px; nested/scrolled geometry stays fixed.")
        print("      Popup pixels are unobstructed; scrollbar state never changes.")
        print("      Body/pinned tooltips have native hover anchors and retain name, metadata and path.")
    finally:
        if view is not None:
            view.destroy()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
