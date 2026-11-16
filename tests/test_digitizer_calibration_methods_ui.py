"""Calibration inspector, direct Add/Auto commands and legacy advanced tools."""
from concurrent.futures import Future
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
from DearUIQt.core import QPoint
from DearUIQt.core import Qt
from DearUIQt.widgets import QRetainedItem
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from test_digitizer_tick_auto_calibration import make_chart
from test_digitizer_tick_background import _detection


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='calibration-methods-', dir=temp) as profile, \
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
            from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
            from WinUx.view import WinUXView
            view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            dialog = PlotDigitizerDialog(view)
            dialog.show()

        def pump(frames=14):
            for _ in range(frames):
                if runtime is not None:
                    runtime._drain_form_callbacks()
                    view.drain()
                    runtime.gui.renderFrame()
                    view.mark_presented()
                else:
                    view.update()
                time.sleep(.01)

        def mouse(point, phase):
            with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                    patch.object(dialog, '_canvas_to_image', return_value=point), \
                    patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=QPoint(0, 0)):
                getattr(dialog, '_mouse_left' if phase == 'down' else '_mouse_left_up')()

        def choose(method):
            revision, calibration = dialog.engine.revision, dialog.engine.calibration.to_dict()
            dialog._set_calibration_method(method)
            pump()
            assert dialog._calibration_method == method
            assert dialog.engine.revision == revision
            assert dialog.engine.calibration.to_dict() == calibration

        def add(axis, value, point):
            dialog.set_control_value(dialog.calibration_axis, axis)
            dialog._calibration_axis_changed()
            dialog.set_control_value(dialog.new_calibration_value, str(value))
            dialog.control_wrapper(dialog.add_calibration_button).click()
            assert dialog._pick_mode == 'calibration_' + axis.lower()
            mouse(point, 'down')
            pump()

        try:
            pump(25)
            for removed in ('calibration_method_buttons', 'select_region_button', 'reread_ticks_button',
                            'calibration_info', 'smart_calibration_info', '_manual_calibration_intro',
                            'calibration_selection_hint', 'calibration_fit_info'):
                assert not hasattr(dialog, removed), removed
            assert not dialog.control_value(dialog._disclosures['axes'])
            assert dialog.control_value(dialog.snap_to_axes) is True
            snap_bounds = QRetainedItem(dialog.snap_to_axes).globalGeometry()
            axis_bounds = QRetainedItem(dialog.calibration_axis).globalGeometry()
            assert axis_bounds.y() >= snap_bounds.y() + snap_bounds.height() + 6, (snap_bounds, axis_bounds)
            image, rect = make_chart()
            dialog.engine.apply_image(image, 'methods.png')
            dialog._load_texture(image)
            pump()
            dialog._fit_view()
            assert not dialog._calibration_editor.isVisible()
            choose('manual')
            dialog.set_control_value(dialog._disclosures['axes'], True)
            pump()
            sidebar = QRetainedItem(dialog.settings_panel)
            sidebar.setVerticalScrollValue(10000)
            pump()
            value_bounds = QRetainedItem(dialog.new_calibration_value).globalGeometry()
            pick_bounds = QRetainedItem(dialog.add_calibration_button).globalGeometry()
            assert pick_bounds.y() >= value_bounds.y() + value_bounds.height() + 6, (value_bounds, pick_bounds)
            with patch.object(dialog._tick_calibration_runner, 'submit', side_effect=AssertionError('Manual started OCR')):
                add('X', 0, (rect[0], rect[3]))
                add('X', 3.2, (rect[2], rect[3]))
                add('Y', 0, (rect[0], rect[3]))
                add('Y', 2000, (rect[0], rect[1]))
            assert dialog.engine.calibration_ready()
            assert dialog.engine.pixel_to_data(360, 225) == (1.6, 1000)
            assert dialog._calibration_editor.isVisible()
            assert len(dialog.calibration_grid.columns) == 3
            revision = dialog.engine.revision
            dialog.set_control_value(dialog.new_calibration_value, 'not a number')
            dialog._begin_manual_calibration_point()
            assert dialog._pick_mode is None and dialog.engine.revision == revision

            choose('smart')
            dialog.set_control_value(dialog._disclosures['axes'], False)
            before_region = dialog.engine._snapshot()
            history_count = len(dialog.engine._undo_stack)
            dialog.ribbon._button_clicked('box')
            mouse(rect[:2], 'down')
            mouse(rect[2:], 'up')
            deadline = time.monotonic() + 20
            while dialog._tick_calibration_runner.busy and time.monotonic() < deadline:
                pump(4)
            pump()
            assert not dialog._tick_calibration_runner.busy
            assert dialog._calibration_method == 'smart'
            assert [p.value for p in dialog.engine.calibration.points_x] == [0, .8, 1.6, 2.4, 3.2]
            assert [p.value for p in dialog.engine.calibration.points_y] == [2000, 1500, 1000, 500, 0]
            assert len(dialog.engine._undo_stack) == history_count + 1
            after_region = dialog.engine._snapshot()
            with patch.object(dialog, '_accepts_edit_shortcut', return_value=True):
                assert dialog._edit_key(None, key=Qt.Key_Z, modifiers=Qt.ControlModifier)
                pump()
                assert dialog.engine._snapshot() == before_region
                assert dialog._edit_key(None, key=Qt.Key_Z, modifiers=Qt.ControlModifier | Qt.ShiftModifier)
                pump()
                assert dialog.engine._snapshot() == after_region
            assert not dialog._calibration_editor.isVisible(), 'Inspector should be hidden until a tick is selected'
            choose('manual')
            dialog.set_control_value(dialog.calibration_axis, 'X')
            dialog._calibration_axis_changed()
            dialog.calibration_grid.setCurrentKey('x:1', select=True)
            pump()
            assert dialog._calibration_editor.isVisible()
            dialog.set_control_value(dialog.calibration_point_value, '.9')
            dialog._update_calibration_point_value()
            pump()
            assert dialog.engine.calibration.points_x[1].value == .9
            assert dialog.engine.calibration.mapping_x == 'ticks'
            choose('smart')

            # Switching to Manual must stop pending OCR before any manual edit.
            late = Future()
            late.set_running_or_notify_cancel()
            with patch.object(dialog._tick_calibration_runner, '_submitter', return_value=late):
                dialog._reread_calibration_ticks()
            assert dialog._tick_calibration_runner.busy
            choose('manual')
            assert not dialog._tick_calibration_runner.busy
            assert dialog._tick_calibration_runner._cancel_event.is_set()
            assert not dialog._progress_jobs
            calibration, revision = dialog.engine.calibration.to_dict(), dialog.engine.revision
            late.set_result(_detection(dialog.engine.plot_rect))
            pump()
            assert dialog.engine.revision == revision and dialog.engine.calibration.to_dict() == calibration

            late_undo = Future()
            late_undo.set_running_or_notify_cancel()
            with patch.object(dialog._tick_calibration_runner, '_submitter', return_value=late_undo):
                dialog._reread_calibration_ticks()
            with patch.object(dialog, '_accepts_edit_shortcut', return_value=True):
                dialog._edit_key(None, key=Qt.Key_Z, modifiers=Qt.ControlModifier)
            assert not dialog._tick_calibration_runner.busy
            assert dialog._tick_calibration_runner._cancel_event.is_set()
            assert not dialog._progress_jobs
            after_undo = dialog.engine._snapshot()
            late_undo.set_result(_detection(dialog.engine.plot_rect))
            pump()
            assert dialog.engine._snapshot() == after_undo
            with patch.object(dialog, '_accepts_edit_shortcut', return_value=True):
                dialog._edit_key(None, key=Qt.Key_Y, modifiers=Qt.ControlModifier)
            pump()

            # The same minimal table layout remains in both persisted modes.
            dialog.resize(1100, 700)
            dialog.set_control_value(dialog._disclosures['axes'], False)
            QRetainedItem(dialog.settings_panel).setVerticalScrollValue(0)
            pump(25)
            for method in ('smart', 'manual'):
                choose(method)
                panel = QRetainedItem(dialog.settings_panel).globalGeometry()
                for tag in (dialog.calibration_axis,):
                    bounds = QRetainedItem(tag).globalGeometry()
                    assert panel.x() <= bounds.x() and bounds.x() + bounds.width() <= panel.x() + panel.width(), (tag, panel, bounds)
            project = str(Path(profile) / 'methods.pdg')
            dialog.control_wrapper(dialog.snap_to_axes).setChecked(False)
            pump()
            assert not dialog.engine.calibration.snap_to_axes
            calibration = dialog.engine.calibration.to_dict()
            dialog._save_project(project)
            dialog.control_wrapper(dialog.snap_to_axes).setChecked(True)
            choose('smart')
            dialog._load_project(project)
            pump(35)
            assert dialog._calibration_method == 'manual', str(dialog.control_value(dialog.status))
            assert dialog.control_value(dialog.snap_to_axes) is False
            assert dialog.engine.calibration.to_dict() == calibration
            from test_digitizer_formatted_labels import real_label_chart
            from WinUx.plotdigitizer.core.models import AxisScale
            image, rect = real_label_chart()
            dialog.engine.apply_image(image, 'formatted-labels.png')
            dialog._load_texture(image)
            dialog.engine.set_plot_rect(rect)
            choose('smart')
            dialog._start_tick_calibration(rect)
            deadline = time.monotonic() + 20
            while dialog._tick_calibration_runner.busy and time.monotonic() < deadline:
                pump(4)
            pump()
            assert not dialog._tick_calibration_runner.busy
            assert dialog.engine.calibration.scale_x == AxisScale.DATETIME
            assert dialog.engine.calibration.scale_y == AxisScale.LOG10
            assert dialog.control_value(dialog.scale_x) == 'Date/Time'
            assert dialog.control_value(dialog.scale_y) == 'Log10'
            # A setting change during OCR must replace the job, not apply an
            # obsolete aligned rectangle after the checkbox has been cleared.
            jobs = []
            def submitter(fn, *args, **kwargs):
                future = Future()
                future.set_running_or_notify_cancel()
                jobs.append((kwargs, future))
                return future
            dialog.control_wrapper(dialog.snap_to_axes).setChecked(True)
            with patch.object(dialog._tick_calibration_runner, '_submitter', side_effect=submitter):
                dialog._start_tick_calibration(rect)
                assert jobs[-1][0]['align_axes'] is True
                dialog.control_wrapper(dialog.snap_to_axes).setChecked(False)
                assert len(jobs) == 2 and jobs[-1][0]['align_axes'] is False
            assert jobs[0][0]['cancelled']()
            jobs[0][1].set_result(_detection(rect))
            jobs[1][1].set_result(_detection(rect))
            pump()
            assert not dialog._tick_calibration_runner.busy
            assert tuple(dialog.engine.plot_rect) == tuple(rect)
            assert dialog.engine.calibration.box_rect == tuple(rect)
            assert dialog.control_value(dialog.snap_to_axes) is False
            # Failed OCR opens all four endpoint fields with no guessed values.
            from WinUx.plotdigitizer.core import tick_detection as td
            from dataclasses import replace
            image, rect = make_chart()
            dialog.engine.apply_image(image, 'missing-axes.png')
            dialog._load_texture(image)
            dialog.engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
            empty = td.TickCalibrationDetection(
                td.AxisTickDetection('x', (), 0, AxisScale.LINEAR),
                td.AxisTickDetection('y', (), 0, AxisScale.LINEAR))
            dialog._tick_calibration_finished(empty, rect, None)
            pump()
            assert dialog.control_value(dialog._disclosures['axes'])
            assert dialog._manual_bounds_axes == {'x', 'y'}
            assert all(dialog.control_value(editor) == '' for editor in dialog.anchor_value.values())
            panel = QRetainedItem(dialog.settings_panel).globalGeometry()
            for editor in dialog.anchor_value.values():
                bounds = QRetainedItem(editor).globalGeometry()
                assert panel.y() <= bounds.y() < panel.y() + panel.height(), (panel, bounds)
            assert not dialog.engine.calibration_ready()
            before = dialog.engine.calibration.to_dict()
            dialog.calibration_grid.setFocus()
            pump(2)
            dialog.set_control_value(dialog.anchor_value['x1'], '0')
            dialog._anchor_value_changed('x1', '0')
            dialog._apply_calibration_values()
            pump()
            assert dialog.engine.calibration.to_dict() == before
            assert not dialog.engine.auto_tick_verified_axes
            assert dialog.control_value(dialog.anchor_value['x1']) == '0', (
                dialog.control_value(dialog.anchor_value['x1']), dialog._manual_bounds_axes,
                str(dialog.control_value(dialog.status)))
            for key, value in dict(x1=0, x2=3.2, y1=0, y2=2000).items():
                dialog.set_control_value(dialog.anchor_value[key], str(value))
            dialog._apply_calibration_values()
            pump()
            assert dialog.engine.calibration_ready()
            assert not dialog._manual_bounds_axes

            # One failed axis must not erase the successfully measured tick fit.
            full = td.detect_calibration_ticks(image, rect)
            dialog.engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
            partial = replace(full, y=empty.y)
            dialog._tick_calibration_finished(partial, rect, None)
            pump()
            assert dialog._manual_bounds_axes == {'y'}
            assert dialog.control_value(dialog.anchor_value['y1']) == ''
            assert dialog.control_value(dialog.anchor_value['y2']) == ''
            points_x = list(dialog.engine.calibration.points_x)
            mapping_x = dialog.engine.calibration.mapping_x
            for key, value in dict(y1=0, y2=2000).items():
                dialog.set_control_value(dialog.anchor_value[key], str(value))
            dialog._apply_calibration_values()
            pump()
            assert dialog.engine.calibration_ready()
            assert dialog.engine.calibration.points_x == points_x
            assert dialog.engine.calibration.mapping_x == mapping_x
            dialog.engine.undo()
            pump()
            assert not dialog.engine.calibration_ready()
            assert dialog.engine.auto_tick_verified_axes == {'x'}
            # Cancelled/stale jobs must not open the manual fallback.
            dialog.set_control_value(dialog._disclosures['axes'], False)
            dialog._tick_calibration_finished(empty, rect, 'discarded')
            assert not dialog.control_value(dialog._disclosures['axes'])
            dialog._tick_calibration_finished(empty, (0, 0, 10, 10), None)
            assert not dialog.control_value(dialog._disclosures['axes'])
            print('PASS: calibration panel, advanced manual tools, ribbon Smart Region OCR, selected-tick editing, cancellation and workspace compatibility')
        finally:
            if runtime is not None:
                view._dispatcher.close()
                if runtime.native:
                    runtime.native.set_visible(False)
                    runtime.native.restore_close_handler()
                    runtime.native.close_activation_guard()
                dialog.destroy()
                runtime.gui.destroy()
            else:
                dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
