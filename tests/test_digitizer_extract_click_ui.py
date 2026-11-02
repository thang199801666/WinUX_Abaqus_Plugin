"""Pick color and activate Extract via pointer events in the public launcher."""
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image
from DearUIQt.core import QPoint, Qt
from DearUIQt.widgets import QApplication, QRetainedItem
from WinUx.plotdigitizer import standalone
from test_digitizer_color_extraction import chart


def main():
    errors, finished, activations = [], [], []
    original = standalone.PlotDigitizerDialog
    source = sys.argv[1] if len(sys.argv) > 1 else None

    def build(view, *args, **kwargs):
        dialog = original(view, *args, **kwargs)
        image = Image.open(source).convert('RGB') if source else chart()
        dialog.engine.apply_image(image, source or 'extract-pointer.png')
        dialog._load_texture(image)
        if source:
            dialog.engine.set_plot_rect_with_corner_anchors((136, 79, 496, 368), detect_ticks=False)
        sample = (250, 111) if source else (100, 150)

        def fail(exc):
            traceback.print_exception(type(exc), exc, exc.__traceback__)
            errors.append(repr(exc))
            dialog.destroy()

        def click_extract():
            try:
                button = dialog.control_wrapper(dialog.extract_button)
                button.clicked.connect(lambda: activations.append(True))
                bounds = QRetainedItem(dialog.extract_button).globalGeometry()
                point = (bounds.x() + bounds.width() / 2, bounds.y() + bounds.height() / 2)
                app = QApplication.instance()
                assert app._pointer_target_at(QPoint(*point)) is dialog
                with patch.object(app._input_backend, 'get_mouse_pos', return_value=point):
                    assert app._native_pointer_pressed(user_data=Qt.LeftButton), (
                        'press', point, QRetainedItem(dialog.tag).globalGeometry(),
                        app._pointer_target_at(QPoint(*point)), dialog.hitTest(QPoint(*point)),
                        app.activeModalWidget(), app.activePopupWidget(),
                        button.isVisible(), button.isEnabled(),
                        dialog._button_contains_global_point(button, point),
                        app._legacy_pointer_input_blocked())

                def release():
                    try:
                        with patch.object(app._input_backend, 'get_mouse_pos', return_value=point):
                            assert app._native_pointer_released(user_data=Qt.LeftButton), ('release', point)
                        # A late renderer notification for the same physical
                        # gesture must not submit a second extraction.
                        button._clicked(button.tag, None, None)
                        assert len(activations) == 1, activations
                        view.after(20, verify, time.monotonic() + 15)
                    except Exception as exc:
                        fail(exc)
                view.after(30, release)
            except Exception as exc:
                fail(exc)

        def verify(deadline):
            try:
                if dialog._smart_runner.busy:
                    assert time.monotonic() < deadline, 'Extraction timed out'
                    view.after(20, verify, deadline)
                    return
                ds = dialog.engine.active_dataset
                assert len(ds.extracted_pixels) >= 150, (
                    len(ds.extracted_pixels), QRetainedItem(dialog.status).value())
                assert len(activations) == 1
                # The canvas overlay's last button must be fully visible and
                # routed once through the same native press/release bridge.
                zoom_button = dialog.control_wrapper(dialog._canvas_view_buttons['zoom_in'])
                bounds = zoom_button.globalGeometry()
                point = (bounds.x() + bounds.width() / 2, bounds.y() + bounds.height() / 2)
                app = QApplication.instance()
                assert app._pointer_target_at(QPoint(*point)) is dialog
                zoom = dialog._zoom
                snapshot = dialog.engine._snapshot()
                with patch.object(app._input_backend, 'get_mouse_pos', return_value=point):
                    assert app._native_pointer_pressed(user_data=Qt.LeftButton)
                    assert zoom_button._pointer_pressed
                    assert app._native_pointer_released(user_data=Qt.LeftButton)
                zoom_button._clicked(zoom_button.tag, None, None)  # Late renderer callback.
                assert abs(dialog._zoom - zoom * 1.15) < 1e-8
                assert dialog.engine._snapshot() == snapshot
                finished.append(len(ds.extracted_pixels))
                dialog.destroy()
            except Exception as exc:
                fail(exc)

        def pick():
            try:
                dialog.ribbon._button_clicked('pick_color')
                with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                        patch.object(dialog, '_canvas_to_image', return_value=sample):
                    dialog._mouse_left()
                assert dialog.engine.active_dataset.curve_rgb is not None
                assert dialog._pick_mode is None
                view.after(80, click_extract)
            except Exception as exc:
                fail(exc)

        view.after(400, pick)
        return dialog

    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='extract-pointer-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}), \
            patch.object(standalone, 'PlotDigitizerDialog', side_effect=build):
        result = standalone.main([])
    assert result == 0 and finished and not errors, (result, finished, errors)
    print('PASS public launcher: picked color -> pointer bridge press/release ->', finished, 'points; one activation')


if __name__ == '__main__':
    main()
