"""Rendered bottom-right progress and real background OCR, using the public launcher."""
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from concurrent.futures import Future
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.widgets import QRetainedItem
from DearUIQt.gui import QFontMetrics
from WinUx.plotdigitizer import standalone
from WinUx.plotdigitizer.core.models import SmartDetectionResult
from PIL import Image
from test_digitizer_tick_auto_calibration import make_chart
import test_plotdigitizer as launcher


def main():
    original = standalone.PlotDigitizerDialog
    errors, finished, updates, beats = [], [], [], []

    def build(view, *args, **kwargs):
        dialog = original(view, *args, **kwargs)
        if len(sys.argv) > 1:
            dialog.engine.load_image(sys.argv[1])
            rect = (136, 79, 496, 368)
            expected_x = [0, .4, .8, 1.2, 1.6, 2, 2.4, 2.8, 3.2]
            expected_y = [32000, 28000, 24000, 20000, 16000, 12000, 8000, 4000, 0]
        else:
            image, rect = make_chart()
            dialog.engine.apply_image(image, '')
            expected_x = [0, .8, 1.6, 2.4, 3.2]
            expected_y = [2000, 1500, 1000, 500, 0]
        dialog._load_texture(dialog.engine.image)
        dialog.engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        on_progress, on_done = dialog._tick_calibration_progress, dialog._tick_calibration_finished
        start = time.perf_counter()

        def fail(exc):
            traceback.print_exception(type(exc), exc, exc.__traceback__)
            errors.append(repr(exc))
            dialog.destroy()

        def geometry(*, settled=False):
            bar = QRetainedItem(dialog.status_bar.tag).globalGeometry()
            progress = QRetainedItem(dialog._status_progress_host.tag).globalGeometry()
            workspace = QRetainedItem(dialog._workspace_host.tag).globalGeometry()
            content = QRetainedItem(dialog.content).globalGeometry()
            assert bar.height() == dialog.STATUS_HEIGHT == 22, bar
            assert dialog._status_top_rule_canvas.exists()
            assert dialog._status_grip_canvas.exists()
            bottom_gap = content.y() + content.height() - bar.y() - bar.height()
            assert 0 <= bottom_gap <= 1, (content, bar, bottom_gap)
            assert workspace.y() + workspace.height() <= bar.y() + 2, (workspace, bar)
            message = QRetainedItem(dialog._status_message_host.tag).globalGeometry()
            grip = QRetainedItem(dialog._status_grip_canvas.tag).globalGeometry()
            text = QRetainedItem(dialog.status).globalGeometry()
            assert abs(text.y() + text.height() / 2 - (bar.y() + bar.height() / 2)) <= 2, (
                text, bar, message, dialog.status_bar.backend.get_item_state(dialog.status))
            assert grip.x() + grip.width() <= bar.x() + bar.width(), (grip, bar)
            if settled:
                window = QRetainedItem(dialog.tag).globalGeometry()
                assert bar.x() == window.x(), (bar, window)
                assert bar.x() + bar.width() == window.x() + window.width(), (bar, window)
                assert bar.y() + bar.height() == window.y() + window.height(), (bar, window)
                assert bar.x() + bar.width() - grip.x() - grip.width() == 2, (bar, grip)
                assert bar.y() + bar.height() - grip.y() - grip.height() == 2, (bar, grip)
            if not dialog._progress_jobs:
                assert not dialog._status_progress_host.isVisible()
                assert not dialog.cancel_process_button.isVisible()
                if settled:
                    assert message.width() >= bar.width() - 40, (message, bar)
                return
            assert dialog._status_progress_host.isVisible()
            assert dialog.cancel_process_button.isVisible()
            cancel = QRetainedItem(dialog.cancel_process_button.tag).globalGeometry()
            assert cancel.height() == dialog.STATUS_BUTTON_HEIGHT == 18, cancel
            assert dialog.progress_bar.backend.get_item_configuration(dialog.progress_bar.tag)['height'] == 14
            backend = dialog.cancel_process_button.backend
            styles = {}
            for component in backend.get_item_children(dialog.cancel_process_button.theme(), 1):
                for item in backend.get_item_children(component, 1):
                    if 'mvThemeStyle' in backend.get_item_info(item)['type']:
                        styles[backend.get_item_configuration(item)['target']] = backend.get_value(item)
            assert tuple(styles[backend.mvStyleVar_FramePadding]) == (6, 0), styles
            assert tuple(styles[backend.mvStyleVar_ButtonTextAlign]) == (.5, .5), styles
            assert QFontMetrics(backend=backend).height() <= cancel.height()
            assert bar.y() <= progress.y() < bar.y() + bar.height(), (bar, progress)
            assert progress.x() + progress.width() <= cancel.x(), (progress, cancel)
            assert 170 <= progress.width() <= 205, progress
            assert message.x() + message.width() <= progress.x(), (message, progress)
            backend = dialog._progress_text_canvas.backend
            metrics = QFontMetrics(backend=backend)
            text = backend.get_item_configuration(dialog._progress_text_draw)
            x, y = text['pos'][:2]
            assert backend.get_item_info(dialog._progress_text_draw)['parent'] == dialog._progress_text_canvas.tag
            assert dialog._progress_text_canvas.pos().toTuple() == (0, 2)
            center = x + metrics.horizontalAdvance(dialog._progress_text) / 2
            assert abs(center - (progress.width() - 1) / 2) <= 1, (center, progress)
            assert abs(y + metrics.height() / 2 - dialog.PROGRESS_HEIGHT / 2) <= 1
            assert dialog.progress_bar.backend.get_item_configuration(dialog.progress_bar.tag)['overlay'] == ''

        def progress(value, message):
            try:
                on_progress(value, message)
                updates.append((value, message))
                assert QRetainedItem(dialog.progress_bar.tag).value() < 1
            except Exception as exc:
                fail(exc)

        def done(detection, box, error):
            try:
                on_done(detection, box, error)
                assert error is None, error
                assert [t.value for t in detection.x.ticks] == expected_x, detection.x
                assert [t.value for t in detection.y.ticks] == expected_y, detection.y
                assert QRetainedItem(dialog.progress_bar.tag).value() == 1
                assert not dialog._progress_jobs
                assert updates and any(0 < value < 1 for value, _ in updates), updates
                assert len(beats) >= 3
                geometry()
                # Idle/error states and full warning text must also remain usable.
                with patch.object(dialog._tick_calibration_runner, '_submitter',
                                  side_effect=RuntimeError('test executor unavailable')):
                    dialog._start_tick_calibration(rect)
                assert not dialog._progress_jobs and not dialog._tick_calibration_runner.busy
                assert QRetainedItem(dialog.progress_bar.tag).value() == 0
                assert 'could not start' in QRetainedItem(dialog.status).value()
                dialog._tick_calibration_progress(.8, 'stale progress')
                assert QRetainedItem(dialog.progress_bar.tag).value() == 0
                dialog._set_status('Warning: ' + 'long status text ' * 80)
                assert QRetainedItem(dialog._status_help).value().startswith('Warning:')
                visible = QRetainedItem(dialog.status).value()
                assert visible.endswith('\u2026')
                assert len(QRetainedItem(dialog._status_help).value()) > len(visible)
                assert QFontMetrics(backend=dialog._status_message_host.backend).horizontalAdvance(visible) <= (
                    QRetainedItem(dialog._status_message_host.tag).globalGeometry().width() - 4)
                dialog._set_status('Calibration incomplete: Y not recognized.',
                                   details='Y axis missing. Initial anchors are placeholders, not measurements.')
                assert QRetainedItem(dialog.status).value() == 'Calibration incomplete: Y not recognized.'
                assert 'placeholders' in QRetainedItem(dialog._status_help).value()
                # A running worker cannot be Future.cancel()'d; the button
                # must signal it, hide the controls and ignore its late result.
                late = Future()
                late.set_running_or_notify_cancel()
                dialog.engine.set_curve_color((255, 0, 0))  # Extract requires a selected color.
                revision = dialog.engine.revision
                with patch.object(dialog._tick_calibration_runner, '_submitter', return_value=late):
                    dialog._start_tick_calibration(rect)
                def cancel_running():
                    try:
                        geometry()
                        dialog.cancel_process_button.click()
                        assert not dialog._tick_calibration_runner.busy
                        assert dialog._tick_calibration_runner._cancel_event.is_set()
                        assert not dialog._progress_jobs
                        geometry()
                        late.set_result(detection)
                        def verify_cancelled():
                            try:
                                assert dialog.engine.revision == revision
                                assert 'cancelled' in QRetainedItem(dialog.status).value()
                                geometry()
                                # Exercise the same button for extraction and
                                # image decoding, including their late results.
                                curve = Future()
                                curve.set_running_or_notify_cancel()
                                with patch.object(dialog._smart_runner, '_submitter', return_value=curve):
                                    dialog._start_extraction(auto_detect=False)
                                assert 'extract' in dialog._progress_jobs
                                dialog.cancel_process_button.click()
                                assert not dialog._smart_runner.busy
                                assert dialog._smart_runner._cancel_event.is_set()
                                curve.set_result(SmartDetectionResult(
                                    plot_rect=rect, curve_rgb=(255, 0, 0), extracted_pixels=[(1, 1), (2, 2)]))
                                callbacks = {}
                                decoder = Mock()
                                def run_async(fn, path, **kwargs):
                                    callbacks.update(kwargs)
                                    return decoder
                                source_image = dialog.engine.image
                                with patch.object(dialog, 'runAsync', side_effect=run_async):
                                    dialog._open_image('cancelled-load.png')
                                assert 'image' in dialog._progress_jobs
                                dialog.cancel_process_button.click()
                                decoder.cancel.assert_called_once()
                                callbacks['on_result']((Image.new('RGB', (20, 20)), 'cancelled-load.png'))
                                assert dialog.engine.image is source_image
                                geometry()
                                def verify_all():
                                    try:
                                        assert dialog.engine.revision == revision
                                        assert not dialog._progress_jobs
                                        geometry()
                                        finished.append(round(time.perf_counter() - start, 3))
                                        dialog.destroy()
                                    except Exception as exc:
                                        fail(exc)
                                view.after(80, verify_all)
                            except Exception as exc:
                                fail(exc)
                        view.after(80, verify_cancelled)
                    except Exception as exc:
                        fail(exc)
                view.after(80, cancel_running)
            except Exception as exc:
                fail(exc)

        def begin():
            try:
                geometry(settled=True)
                # Short glyphs can fit beyond 96 characters: elide by measured
                # pixels, not a character cap, and preserve the complete tooltip.
                long_fitting = 'i' * 110
                dialog._set_status(long_fitting)
                assert QRetainedItem(dialog.status).value() == long_fitting
                assert QRetainedItem(dialog._status_help).value() == long_fitting
                dialog._begin_progress('preview', 'Checking progress alignment...')
                active = QRetainedItem(dialog.status).value()
                dialog._set_status('Point selected.', quiet=True)
                assert QRetainedItem(dialog.status).value() == active
                view.after(80, sweep)
            except Exception as exc:
                fail(exc)

        def sweep(index=0):
            try:
                percent = (0, 10, 50, 69, 99, 100)[index]
                dialog.progress_bar.setValue(percent / 100)
                dialog._set_progress_text('{}%'.format(percent))

                def verify():
                    try:
                        geometry(settled=True)
                        if index < 5:
                            sweep(index + 1)
                        else:
                            dialog._finish_progress('preview')
                            dialog._start_tick_calibration(rect)
                    except Exception as exc:
                        fail(exc)

                # Retained widget updates commit at the event-loop boundary;
                # inspect the rendered percentage, not the previous frame.
                view.after(80, verify)
            except Exception as exc:
                fail(exc)

        def resize():
            try:
                geometry(settled=True)
                dialog.resize(1100, 700)
                view.after(300, begin)
            except Exception as exc:
                fail(exc)

        def heartbeat():
            if not finished and not errors:
                beats.append(True)
                view.after(40, heartbeat)

        def timeout():
            if not finished and not errors:
                fail(TimeoutError('OCR did not finish'))

        dialog._tick_calibration_progress = progress
        dialog._tick_calibration_finished = done
        view.after(10, heartbeat)
        view.after(400, resize)
        view.after(20000, timeout)
        return dialog

    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-statusbar-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}), \
            patch.object(standalone, 'PlotDigitizerDialog', side_effect=build):
        result = launcher.main(['--width', '1240', '--height', '780'])
    assert result == 0 and finished and not errors, (result, finished, errors)
    print('PASS statusbar UI/background:', finished, 'seconds;', len(updates), 'progress updates;', len(beats), 'heartbeats')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
