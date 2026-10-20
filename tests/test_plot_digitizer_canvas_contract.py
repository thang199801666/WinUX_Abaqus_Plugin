from pathlib import Path


DIALOG = Path(__file__).resolve().parents[1] / "WinUx" / "plotdigitizer" / "ui" / "dialog.py"


def test_canvas_is_persistent_and_blank_before_image_load():
    source = DIALOG.read_text(encoding="utf-8")
    assert "canvas_info" not in source
    assert "self.image_bar" not in source
    assert '"Open an image to start digitizing."' not in source
    assert 'if self._auto_fit and self.engine.image is not None:' in source
    assert 'else:\n            self._redraw()' in source


def test_blank_canvas_is_a_real_framed_child_surface():
    source = DIALOG.read_text(encoding="utf-8")
    assert "self.canvas_frame = dpg.add_child_window(" in source
    assert "style_image_canvas(self.canvas_frame)" in source
    assert "parent=self.canvas_frame" in source
    assert "dpg.configure_item(self.canvas_frame, width=frame_size[0], height=frame_size[1])" in source
