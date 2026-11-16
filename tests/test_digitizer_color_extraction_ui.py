"""Real Pick Color -> background Extract Points must ignore neutral plot axes."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.core import QPoint, QEvent, QMouseEvent, Qt
from DearUIQt.widgets import QApplication, QRetainedItem
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime
from test_digitizer_color_extraction import chart, GREEN


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='extract-color-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile, 'WINUX_LOG_DIR': str(temp / 'extract-color-logs')}):
        runtime = FloatingDialogRuntime(Mock(), iter(()), {
            'kind': 'plotdigitizer', 'title': 'Plot Digitizer', 'visible': True,
            'payload': {}, 'width': 1240, 'height': 800})
        runtime.gui.createContext(manual_callbacks=True)
        runtime._publish_requested = runtime._commit_requested = True
        try:
            runtime._build()
            dialog = runtime.form

            def pump(count=12):
                for _ in range(count):
                    runtime._drain_form_callbacks()
                    runtime.view.drain()
                    runtime.gui.renderFrame()
                    runtime.view.mark_presented()
                    time.sleep(.01)

            def click(tag):
                rect = QRetainedItem(tag).globalGeometry()
                point = (rect.x() + rect.width() / 2, rect.y() + rect.height() / 2)
                application = QApplication.instance()
                if application is None:
                    assert dialog.control_wrapper(tag).click()
                    return
                assert application.dispatchPointerEvent(QMouseEvent(
                    QEvent.MouseButtonPress, point, button=Qt.LeftButton, buttons=Qt.LeftButton))
                pump(2)
                assert application.dispatchPointerEvent(QMouseEvent(
                    QEvent.MouseButtonRelease, point, button=Qt.LeftButton, buttons=Qt.NoButton))

            pump(30)
            dialog.engine.apply_image(chart(), 'green-red-blue-with-black-axes.png')
            dialog._load_texture(dialog.engine.image)
            pump()
            dialog._show_tool('extract')
            click(dialog.pick_color_button)
            with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                    patch.object(dialog, '_canvas_to_image', return_value=(100, 150)), \
                    patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=QPoint(10, 10)):
                dialog._mouse_left()
            pump()
            assert dialog.engine.active_dataset.curve_rgb == GREEN
            click(dialog.extract_button)
            deadline = time.monotonic() + 20
            while dialog._smart_runner.busy and time.monotonic() < deadline:
                pump(1)
            assert not dialog._smart_runner.busy, 'Background extraction did not finish'
            pump()
            dataset = dialog.engine.active_dataset
            assert dataset.curve_rgb == GREEN, 'Selected color was replaced by auto detection'
            assert len(dataset.extracted_pixels) >= 170
            for x, y in dataset.extracted_pixels:
                assert 20 <= x <= 200 and abs(y - (200 - int(x) // 2)) <= 1, (x, y)
            assert not dataset.manual_points
            assert dialog._pick_color_rgb == GREEN
            print('PASS: actual color picking and background extraction follow the green curve, '
                  'not black/gray axes or red/blue strokes; selected color preserved', flush=True)
        finally:
            runtime.view._dispatcher.close()
            if runtime.native:
                runtime.native.set_visible(False)
                runtime.native.restore_close_handler()
                runtime.native.close_activation_guard()
            runtime.gui.destroy()


if __name__ == '__main__':
    main()
