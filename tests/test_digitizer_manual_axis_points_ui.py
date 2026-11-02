"""Place -> drag -> enter value for manual axis ticks, alongside automatic OCR."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image
from DearUIQt.core import QPoint
from DearUIQt.widgets import QRetainedItem
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.plotdigitizer.core import AxisScale
from WinUx.plotdigitizer.core.axis_labels import parse_axis_value_input
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='manual-axis-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        runtime = None
        if '--standalone' in sys.argv:
            from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime
            runtime = FloatingDialogRuntime(Mock(), iter(()), {
                'kind': 'plotdigitizer', 'title': 'Plot Digitizer', 'visible': True,
                'payload': {}, 'width': 1240, 'height': 800})
            runtime.gui.createContext(manual_callbacks=True)
            runtime._publish_requested = runtime._commit_requested = True
            runtime._build()
            dialog, view = runtime.form, runtime.view
        else:
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            dialog = PlotDigitizerDialog(view)
            dialog.show()

        def pump(count=12):
            for _ in range(count):
                if runtime is not None:
                    runtime._drain_form_callbacks()
                    view.drain()
                    runtime.gui.renderFrame()
                    view.mark_presented()
                else:
                    view.update()
                time.sleep(.01)

        def mouse(point, method):
            with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                    patch.object(dialog, '_canvas_to_image', return_value=point), \
                    patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=QPoint(0, 0)):
                getattr(dialog, method)()

        def draft(axis, start, end):
            dialog.set_control_value(dialog.calibration_axis, axis.upper())
            dialog._calibration_axis_changed()
            revision = dialog.engine.revision
            points = len(dialog.engine.calibration_points(axis))
            dialog.control_wrapper(dialog.add_axis_point_button).click()
            assert dialog._pick_mode == 'calibration_' + axis
            mouse(start, '_mouse_left')
            pump(3)
            assert dialog._selected_calibration_point == (axis, 'draft')
            assert dialog._calibration_editor.isVisible()
            assert dialog.control_value(dialog.calibration_point_value) == ''
            assert dialog.engine.revision == revision
            assert len(dialog.engine.calibration_points(axis)) == points
            mouse(start, '_mouse_left')
            assert dialog._anchor_drag_target == axis + 'draft'
            mouse(end, '_mouse_move')
            mouse(end, '_mouse_left_up')
            pump(3)
            assert (dialog._calibration_draft['px'], dialog._calibration_draft['py']) == end
            assert dialog.engine.revision == revision, 'Unconfirmed tick changed calibration'

        def apply(text):
            dialog.set_control_value(dialog.calibration_point_value, text)
            dialog.control_wrapper(dialog.update_calibration_button).click()
            pump()
            assert dialog._calibration_draft is None

        try:
            pump(25)
            assert not dialog.control_wrapper(dialog.add_axis_point_button).isEnabled()
            dialog.engine.apply_image(Image.new('RGB', (400, 300), 'white'), 'manual-axis.png')
            dialog._load_texture(dialog.engine.image)
            dialog.engine.set_axis_scale(AxisScale.DATETIME, AxisScale.LINEAR)
            pump()
            assert not dialog.control_value(dialog._disclosures['axes'])
            assert QRetainedItem(dialog.add_axis_point_button).isVisible()
            assert QRetainedItem(dialog.auto_detect_ticks_button).isVisible()
            with patch.object(dialog._tick_calibration_runner, 'submit', side_effect=AssertionError('Manual ran OCR')):
                draft('x', (80, 250), (95, 250))
                revision = dialog.engine.revision
                dialog.set_control_value(dialog.calibration_point_value, 'not a date')
                dialog._update_calibration_point_value()
                assert dialog._calibration_draft is not None and dialog.engine.revision == revision
                apply('2020-01-22')
                draft('x', (210, 250), (220, 250))
                apply('2020-01-24')
                draft('y', (60, 250), (60, 240))
                apply('0')
                draft('y', (60, 80), (60, 70))
                apply('100')
            assert dialog.engine.calibration_ready()
            assert dialog.engine.calibration.points_x[0].value == parse_axis_value_input('2020-01-22', AxisScale.DATETIME)
            draft('x', (300, 250), (310, 250))
            revision = dialog.engine.revision
            dialog._close_from_escape()
            assert dialog._calibration_draft is None and dialog._pick_mode is None
            assert dialog.engine.revision == revision and len(dialog.engine.calibration.points_x) == 2
            mouse((95, 250), '_mouse_left')
            mouse((105, 250), '_mouse_move')
            mouse((105, 250), '_mouse_left_up')
            pump()
            assert dialog.engine.calibration.points_x[0].px == 105
            assert dialog.engine.undo()
            pump()
            assert dialog.engine.calibration.points_x[0].px == 95
            dialog.control_wrapper(dialog.auto_detect_ticks_button).click()
            assert dialog._pick_mode == 'area', 'Auto Detect must still offer region selection'
            dialog._cancel_pick()
            print('PASS manual axis ticks: visible Add/Auto, draft placement/drag, date and numeric values, invalid input, Esc, Undo and existing tick drag')
        finally:
            if runtime is not None:
                view._dispatcher.close()
                if runtime.native:
                    runtime.native.set_visible(False)
                    runtime.native.restore_close_handler()
                    runtime.native.close_activation_guard()
                runtime.gui.destroy()
            else:
                dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
