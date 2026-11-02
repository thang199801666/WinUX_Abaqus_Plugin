"""Rendered Smart Region gestures, live preview, Escape and background OCR."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.core import QPoint
from WinUx.plotdigitizer import standalone
from test_digitizer_tick_auto_calibration import make_chart
import test_plotdigitizer as launcher


def main():
    original = standalone.PlotDigitizerDialog
    finished, errors, aligned_events = [], [], []

    def build(view, *args, **kwargs):
        dialog = original(view, *args, **kwargs)
        expected_aligned = None
        if len(sys.argv) > 1:
            dialog.engine.load_image(sys.argv[1])
            if Path(sys.argv[1]).stem.endswith('-03'):
                rect = (140, 65, 345, 286)  # Deliberately off both physical axes.
                expected_aligned = (132, 65, 345, 276)
                expected_x = [0, .2, .4, .6, .8, 1, 1.2, 1.4]
                expected_y = [4000, 3500, 3000, 2500, 2000, 1000, 500, 0]
            else:
                rect = (136, 79, 496, 368)
                expected_x = [0, .4, .8, 1.2, 1.6, 2, 2.4, 2.8, 3.2]
                expected_y = [32000, 28000, 24000, 20000, 16000, 12000, 8000, 4000, 0]
        else:
            image, rect = make_chart()
            dialog.engine.apply_image(image, '')
            expected_x, expected_y = [0, .8, 1.6, 2.4, 3.2], [2000, 1500, 1000, 500, 0]
        dialog._load_texture(dialog.engine.image)
        callback = dialog._tick_calibration_finished
        on_region = dialog._region_aligned

        def aligned(region):
            on_region(region)
            aligned_events.append((tuple(region), dialog.engine.plot_rect))
            assert dialog._region_alignment_preview == tuple(region)

        def fail(exc):
            errors.append(repr(exc))
            dialog.destroy()

        def mouse(point, phase):
            origin, _ = dialog._canvas_rect()
            local = dialog._image_to_canvas(*point)
            position = QPoint(round(origin[0] + local[0]), round(origin[1] + local[1]))
            with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                    patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=position):
                getattr(dialog, {'down': '_mouse_left', 'move': '_mouse_move', 'up': '_mouse_left_up'}[phase])()

        def click(point):
            mouse(point, 'down')
            mouse(point, 'up')

        def activate():
            assert dialog.ribbon._buttons['box']['label'] == 'Select Plot'
            dialog.ribbon._button_clicked('box')
            assert dialog._pick_mode == 'area'

        def begin():
            try:
                dialog._fit_view()
                activate()
                revision = dialog.engine.revision
                click(rect[:2])
                assert dialog._region_first_corner is not None
                assert dialog.engine.revision == revision and dialog.engine.plot_rect is None
                assert not dialog._tick_calibration_runner.busy and not dialog._progress_jobs
                mouse(rect[2:], 'move')
                assert dialog._drag_preview is not None and dialog._pointer_layer.exists()
                assert dialog._drag_preview[0] > dialog._drag_start[0]
                dialog._close_from_escape()
                assert dialog._pick_mode is None and dialog._region_first_corner is None
                assert dialog._drag_start is None and dialog.engine.revision == revision
                activate()
                click(rect[:2])
                mouse(rect[2:], 'move')
                click(rect[2:])
                assert dialog._pick_mode is None and dialog._region_first_corner is None
                assert dialog.engine.plot_rect is not None
            except Exception as exc:
                fail(exc)

        def drag():
            try:
                activate()
                mouse(rect[2:], 'down')
                mouse(rect[:2], 'move')
                mouse(rect[:2], 'up')
                assert dialog._pick_mode is None and dialog._drag_start is None
            except Exception as exc:
                fail(exc)

        def done(detection, box, error, **kwargs):
            try:
                callback(detection, box, error, **kwargs)
                assert error is None, error
                assert len(aligned_events) == len(finished) + 1
                assert aligned_events[-1][0] == detection.aligned_rect
                assert aligned_events[-1][1] == tuple(box)  # Preview does not mutate the worker's source.
                assert [t.value for t in detection.x.ticks] == expected_x, detection.x
                assert [t.value for t in detection.y.ticks] == expected_y, detection.y
                assert all(abs(a - b) <= 1 for a, b in zip(box, rect)), (box, rect)
                if expected_aligned is not None:
                    assert detection.aligned_rect == expected_aligned, detection.aligned_rect
                    actual = dialog.engine.plot_rect
                    assert actual[1:3] == rect[1:3], actual  # Top/right are not guessed.
                    assert abs(actual[0] - expected_aligned[0]) <= 1, actual
                    assert abs(actual[3] - expected_aligned[3]) <= 1, actual
                    c = dialog.engine.calibration
                    assert (c.x1.px, c.x1.py) == (c.y1.px, c.y1.py)
                    assert detection.y.unread_positions  # 1500 is reported, never invented.
                assert not dialog._progress_jobs
                assert dialog._drag_start is None and dialog._region_first_corner is None
                finished.append(box)
                if len(finished) == 1:
                    view.after(80, drag)
                else:
                    assert finished[0] == finished[1]
                    view.after(80, dialog.destroy)
            except Exception as exc:
                fail(exc)

        def timeout():
            if len(finished) != 2 and not errors:
                fail(TimeoutError('Smart Region OCR did not finish'))

        dialog._tick_calibration_finished = done
        dialog._region_aligned = aligned
        view.after(400, begin)
        view.after(25000, timeout)
        return dialog

    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='smart-region-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}), \
            patch.object(standalone, 'PlotDigitizerDialog', side_effect=build):
        result = launcher.main(['--width', '1240', '--height', '780'])
    assert result == 0 and len(finished) == 2 and not errors, (result, finished, errors)
    print('PASS Smart Region: two clicks, reverse drag, preview, Escape and background OCR:', finished)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
