"""Focused calibration UI smoke test: abaqus python tests/test_digitizer_multipoint_ui.py."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.core import DigitizerEngine
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-multipoint-', dir=root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            dialog = PlotDigitizerDialog(view)

            def pump():
                for _ in range(12):
                    view.update()
                    time.sleep(.01)

            def click_image(px, py):
                with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                        patch.object(dialog, '_canvas_to_image', return_value=(px, py)):
                    dialog._mouse_left()
                pump()

            def add(axis, px, py, value):
                dialog.set_control_value(dialog.calibration_axis, axis.upper())
                dialog._calibration_axis_changed()
                dialog.set_control_value(dialog.calibration_point_value, str(value))
                dialog._begin_add_calibration_point()
                assert dialog._pick_mode == 'calibration_' + axis
                click_image(px, py)

            try:
                dialog.show()
                dialog.engine.apply_image(Image.new('RGB', (201, 201), 'white'), 'multipoint.png')
                pump()
                for pixel, value in ((20, 0), (100, 5), (180, 10)):
                    add('x', pixel, 180, value)
                for pixel, value in ((180, 0), (100, 50), (20, 100)):
                    add('y', 20, pixel, value)
                assert dialog.engine.calibration_ready()
                assert dialog.engine.pixel_to_data(100, 100) == (5, 50)
                assert len(list(dialog._calibration_markers())) == 6
                assert len(dialog.calibration_grid.rows) == 3
                assert len(dialog.engine.calibration_points('y')) == 3

                dialog.set_control_value(dialog.calibration_axis, 'X')
                dialog._calibration_axis_changed()
                dialog.calibration_grid.setCurrentKey('x:1', select=True)
                assert dialog.control_value(dialog.calibration_point_value) == '5'
                dialog.set_control_value(dialog.calibration_point_value, '6')
                dialog._update_calibration_point_value()
                pump()
                assert dialog.engine.calibration.points_x[1].value == 6
                assert len(dialog.engine.calibration.points_x) == 3
                dialog._repick_calibration_point()
                click_image(110, 180)
                assert dialog.engine.calibration.points_x[1].px == 110
                assert dialog.engine.calibration.points_x[1].value == 6
                assert dialog._nearest_anchor(110, 180) == 'x2'

                dialog._remove_calibration_point()
                pump()
                assert len(dialog.calibration_grid.rows) == 2
                assert dialog.engine.calibration_ready()
                dialog.engine.undo()
                pump()
                assert len(dialog.calibration_grid.rows) == 3
                click_image(180, 180)
                assert dialog._anchor_drag_target == 'x3'
                dialog._anchor_drag_preview = (175, 180)
                with patch.object(dialog, '_canvas_to_image', return_value=(175, 180)):
                    dialog._mouse_left_up()
                pump()
                assert dialog.engine.calibration.points_x[2].px == 175
                assert len(dialog.engine.calibration.points_x) == 3

                project = str(Path(profile) / 'multipoint.pdg')
                dialog.engine.save_project(project)
                restored = DigitizerEngine()
                restored.load_project(project)
                assert dialog.engine.calibration.to_dict() == restored.calibration.to_dict()
                assert dialog.engine.pixel_to_data(100, 100) == restored.pixel_to_data(100, 100)
                print('PASS: multi-point X/Y picking, table editing, re-pick, removal, Undo, markers and PDG round trip')
            finally:
                dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
