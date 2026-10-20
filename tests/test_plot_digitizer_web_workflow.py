"""Guided XY calibration and contextual acquisition tools, like the web workflow."""
import sys
from unittest.mock import patch

import pytest
from PIL import Image

from WinUx.plotdigitizer.core import DigitizerEngine


def calibrated_engine(tmp_path):
    path = tmp_path / 'plot.png'
    Image.new('RGB', (121, 121), 'white').save(path)
    engine = DigitizerEngine()
    engine.load_image(str(path))
    for key, x, y, value in (('x1', 10, 110, 0), ('x2', 110, 110, 1),
                              ('y1', 10, 110, 0), ('y2', 10, 10, 1)):
        engine.set_anchor(key, x, y, value)
    return engine, path


def test_axis_value_commit_is_atomic_and_undoable(tmp_path):
    engine, _ = calibrated_engine(tmp_path)
    # X1 may equal the old X2 value, provided both new values are committed
    # together. Per-anchor updates would incorrectly reject this valid edit.
    engine.set_anchor_values({'x1': 1, 'x2': 11, 'y1': 0, 'y2': 100})
    assert engine.pixel_to_data(60, 60) == pytest.approx((6, 50))
    assert engine.undo()
    assert engine.pixel_to_data(60, 60) == pytest.approx((.5, .5))
    assert engine.redo()
    assert engine.pixel_to_data(60, 60) == pytest.approx((6, 50))
    before = engine.calibration.to_dict()
    with pytest.raises(ValueError):
        engine.set_anchor_values({'x1': 2, 'x2': 2, 'y1': 0, 'y2': 100})
    assert engine.calibration.to_dict() == before


@pytest.mark.windows_native
@pytest.mark.skipif(sys.platform != 'win32', reason='requires native Dear PyGui')
def test_context_pages_guided_calibration_manual_delete_and_nudge(tmp_path):
    import dearpygui.dearpygui as dpg
    from WinUx.ui import StandaloneUiHost, configure_ui_context, item_rect
    from WinUx.runtime.dpg_callbacks import run_callback_jobs
    from WinUx.plotdigitizer.ui import PlotDigitizerDialog

    _, path = calibrated_engine(tmp_path)
    dpg.create_context()
    dialog = None
    try:
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        dpg.create_viewport(title='Web-like digitizer workflow', width=1240, height=820)
        dpg.setup_dearpygui()
        dialog = PlotDigitizerDialog(host)
        dpg.set_primary_window(dialog.tag, True)
        dpg.show_viewport()

        def pump():
            for _ in range(3):
                run_callback_jobs(dpg.get_callback_queue() or [])
                host.pump()
                dpg.render_dearpygui_frame()

        dialog._open_image(str(path))
        pump()
        assert dialog._active_tool == 'axes'
        assert dpg.get_item_rect_size(dialog.canvas)[0] > 500
        for tool in ('manual', 'automatic', 'data', 'axes'):
            dialog._show_tool(tool)
            pump()
            assert [name for name, page in dialog._tool_pages.items()
                    if dpg.get_item_configuration(page)['show']] == [tool]
            target = {'axes': dialog.calibrate_button,
                      'manual': dialog.add_point_button,
                      'automatic': dialog.extract_button,
                      'data': dialog.coordinate_mode}[tool]
            assert dpg.get_item_state(target)['visible']
            x, y, right, bottom = item_rect(target)
            panel_bounds = item_rect(dialog.settings_panel)
            assert right > x and bottom > y
            assert right <= panel_bounds[2]
            if tool == 'data':
                assert dpg.get_item_state(dialog.result_grid.tag)['visible']
        assert dialog.active_table is None
        dialog._start_calibration()

        def mouse_at(px, py):
            (ox, oy), _ = dialog._canvas_rect()
            cx, cy = dialog._image_to_canvas(px, py)
            return ox + cx, oy + cy

        for key, px, py in (('x1', 10, 110), ('x2', 110, 110), ('y1', 10, 110), ('y2', 10, 10)):
            assert dialog._pick_mode == key
            with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                    patch.object(dpg, 'get_mouse_pos', return_value=mouse_at(px, py)):
                dialog._mouse_left()
            pump()
        assert dialog._pick_mode is None
        assert not dialog._calibration_sequence
        for key, value in (('x1', '1'), ('x2', '11'), ('y1', '0'), ('y2', '100')):
            dpg.set_value(dialog.anchor_value[key], value)
        dialog._apply_calibration_values()
        pump()
        assert dialog.engine.pixel_to_data(60, 60) == pytest.approx((6, 50))
        assert 'Apply Calibration' not in dpg.get_value(dialog.status)

        dialog.engine.add_manual_point(60, 60)
        pump()
        dialog._selected_point = ('manual', 0)
        with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                patch.object(dpg, 'get_focused_item', return_value=0), \
                patch.object(dpg, 'is_key_down', return_value=False):
            dialog._edit_key(None, dpg.mvKey_Right)
        assert dialog.engine.point_pixels('manual', 0) == pytest.approx((61, 60))

        edit_button = dialog._control_wrappers[dialog.edit_points_button]
        assert edit_button.isCheckable()
        edit_button.setChecked(True)
        assert dialog._edit_enabled and dialog._pick_mode is None
        drag_position = [mouse_at(61, 60)]
        with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                patch.object(dpg, 'get_mouse_pos', side_effect=lambda **_: drag_position[0]):
            dialog._mouse_left()
            assert dialog._drag_target == ('manual', 0)
            drag_position[0] = mouse_at(70, 65)
            dialog._mouse_move()
            dialog._mouse_left_up()
        assert dialog.engine.point_pixels('manual', 0) == pytest.approx((70, 65))
        assert dialog._edit_enabled
        edit_button.setChecked(False)
        assert not dialog._edit_enabled

        dialog._begin_pick('delete')
        assert dialog._active_tool == 'manual'
        with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                patch.object(dpg, 'get_mouse_pos', return_value=mouse_at(70, 65)):
            dialog._mouse_left()
        assert not dialog.engine.active_dataset.manual_points
        dialog._undo()
        pump()
        assert len(dialog.engine.active_dataset.manual_points) == 1
        dialog._show_tool('data')
        assert dialog.active_table is dialog.result_grid
        assert len(dialog.result_grid.rows) == 1
        dialog._start_calibration()
        dialog._cancel_pick()
        assert dialog._pick_mode is None and not dialog._calibration_sequence
    finally:
        if dialog is not None:
            dialog.destroy()
        dpg.destroy_context()
