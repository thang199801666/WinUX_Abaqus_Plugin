"""Check crosshair draw primitives and native cursor modes on a real canvas."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from PIL import Image
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.core import QPoint
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.runtime.dpg_callbacks import run_callback_jobs


def main():
    dpg.create_context()
    dialog = None
    try:
        native = NativeWindowBackend(dpg)
        native.enable()
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        dpg.create_viewport(title="Digitizer cursor check", width=1280, height=820)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dialog = PlotDigitizerDialog(host)
        dialog.engine.image = Image.new("RGB", (200, 160), "white")
        dialog.engine.active_dataset.extracted_pixels = [(100, 80)]
        dialog._load_texture()
        dialog._refresh_all()
        for _ in range(8):
            run_callback_jobs(dpg.get_callback_queue() or [])
            host.pump()
            dpg.render_dearpygui_frame()
        dialog._fit_view()

        def primitives():
            children = dpg.get_item_children(dialog._pointer_layer.tag, 2) or []
            return [(dpg.get_item_info(tag)["type"], dpg.get_item_configuration(tag))
                    for tag in children]

        def move_to(px, py):
            (ox, oy), _ = dialog._canvas_rect()
            x, y = dialog._image_to_canvas(px, py)
            with patch.object(dialog, "_mouse_in_canvas", return_value=True), \
                    patch("WinUx.plotdigitizer.ui.dialog.QCursor.pos", return_value=QPoint(round(ox+x), round(oy+y))):
                dialog._mouse_move()

        def preview_image():
            images = [config for kind, config in primitives() if kind.endswith("mvDrawImage")]
            assert len(images) == 1, images
            return images[0]

        # An image has a preview before entering the canvas or selecting a tool.
        preview_image()
        move_to(20, 20)
        lines = [config for kind, config in primitives() if kind.endswith("mvDrawLine")]
        assert len(lines) == 4, primitives()
        _, (width, height) = dialog._canvas_rect()
        assert tuple(lines[0]["p1"])[:2] == (0, dialog._cursor_canvas[1])
        assert tuple(lines[0]["p2"])[:2] == (width, dialog._cursor_canvas[1])
        assert tuple(lines[1]["p2"])[:2] == (dialog._cursor_canvas[0], height)
        cursor = dialog._canvas_cursor
        assert cursor.mode == "blank" and cursor._handle
        assert cursor._hook_hwnd == native.winId(dialog.tag)
        before = preview_image()
        source_span = before["uv_max"][0] - before["uv_min"][0]
        dialog._zoom_at(2)
        after = preview_image()
        new_span = after["uv_max"][0] - after["uv_min"][0]
        assert abs(source_span / new_span - 2) < .001, (before, after)
        move_to(100, 80)
        assert dialog._cursor_over_marker
        rectangles = [config for kind, config in primitives() if kind.endswith("mvDrawRect")]
        assert any(abs(config["pmax"][0] - config["pmin"][0] - 8) < .1
                   for config in rectangles), rectangles

        with patch.object(dialog, "_mouse_in_canvas", return_value=True):
            dialog._mouse_middle_down()
        assert cursor.mode == "move" and cursor._handle
        preview_image()
        assert len([kind for kind, _ in primitives() if kind.endswith("mvDrawLine")]) == 2
        old_pan = list(dialog._pan)
        x, y = dialog._last_mouse
        with patch("WinUx.plotdigitizer.ui.dialog.QCursor.pos", return_value=QPoint(x+18, y+10)):
            dialog._mouse_move()
        assert dialog._pan == [old_pan[0]+18, old_pan[1]+10]
        assert cursor.mode == "move"
        with patch.object(dialog, "_mouse_in_canvas", return_value=False):
            dialog._mouse_middle_up()
        assert cursor.mode is None
        preview_image()
        assert len([kind for kind, _ in primitives() if kind.endswith("mvDrawLine")]) == 2
        dialog.destroy()
        assert cursor._hook_hwnd is None
        assert getattr(host, "_tool_cursor", None) is None
        dialog = None
        print("DIGITIZER_NATIVE_CURSOR_OK crosshair/marker-square/pan/leave/cleanup/preview-5x")
    finally:
        if dialog is not None:
            dialog.destroy()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
