"""Plot Digitizer inspector layout: abaqus python tests/test_digitizer_data_layout.py."""
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
from DearUIQt.backends import dpg
from DearUIQt.core import Qt, QEvent, QMouseEvent
from DearUIQt.widgets import QRetainedItem
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-digitizer-layout-', dir=root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            dialog = PlotDigitizerDialog(view)

            def pump(frames=18):
                for _ in range(frames):
                    view.update()
                    time.sleep(.01)

            def rect(item):
                widget = dialog.control_wrapper(item)
                if widget is not None:
                    geometry = widget.globalGeometry()
                    return geometry.x(), geometry.y(), geometry.width(), geometry.height()
                return (*dpg.get_item_rect_min(item), *dpg.get_item_rect_size(item))

            try:
                dialog.show()
                pump(30)
                assert not hasattr(dialog, 'calibrate_button')
                assert dialog.control_value(dialog.calibration_axis) == 'X'
                assert not dialog.calibration_grid.rows
                grid = rect(dialog.calibration_grid.tag)
                assert grid[2] > 100 and grid[3] >= 150, grid
                add = rect(dialog.add_calibration_button)
                update = rect(dialog.update_calibration_button)
                assert abs(add[1] - update[1]) <= 1, (add, update)
                assert add[2] > 60 and update[2] > 60, (add, update)
                for key in ('x1', 'x2', 'y1', 'y2'):
                    assert not dialog.control_wrapper(dialog.anchor_value[key]).isEnabled()
                dialog.engine.apply_image(Image.new('RGB', (120, 90), 'white'), 'anchors.png')
                dialog.engine.set_anchor('x1', 10, 80, 0)
                pump()
                assert dialog.control_wrapper(dialog.anchor_value['x1']).isEnabled()
                assert dialog.control_value(dialog.anchor_value['x1']) == '0'
                for key in ('x2', 'y1', 'y2'):
                    assert not dialog.control_wrapper(dialog.anchor_value[key]).isEnabled()
                    assert dialog.control_value(dialog.anchor_value[key]) == ''
                dialog._show_tool('manual')
                pump()
                assert not hasattr(dialog, 'add_point_button')
                assert not hasattr(dialog, 'edit_points_button')
                assert dialog.ribbon._buttons['edit']['checkable']
                dialog._show_tool('automatic')
                pump()
                def page_buttons(native):
                    result = []
                    for children in (dpg.get_item_children(native) or {}).values():
                        for child in children:
                            if dpg.get_item_type(child).endswith(('mvButton', 'mvImageButton')):
                                result.append(child)
                            result.extend(page_buttons(child))
                    return result
                extraction_buttons = {dialog.delete_point_button, dialog.pick_curve_button,
                                      dialog.pick_color_button, dialog.extract_button}
                assert set(page_buttons(dialog._tool_pages['extract'])) == extraction_buttons
                assert 'manual' not in dialog._tool_pages and 'automatic' not in dialog._tool_pages
                assert dialog._active_tool == 'extract'
                pick_color, pick_label, extract = (rect(item) for item in (
                    dialog.pick_curve_button, dialog.pick_color_button, dialog.extract_button))
                assert pick_color[2:] == (28, 28), pick_color
                assert abs(pick_color[1] - pick_label[1]) <= 1
                assert pick_label[0] - (pick_color[0] + pick_color[2]) >= 4
                assert extract[1] - (pick_label[1] + pick_label[3]) >= 6
                assert dpg.get_item_configuration(dialog.pick_curve_button)['label'] == ''
                dialog._show_tool('settings')
                pump()
                assert QRetainedItem(dialog.tolerance).isVisible()
                dialog._show_tool('automatic')
                pump()
                assert set(page_buttons(dialog._tool_pages['extract'])) == extraction_buttons
                dialog._show_tool('data')
                pump(30)
                for size in ((1240, 780), (1380, 880)):
                    dialog.resize(*size)
                    pump()
                    name, add, delete = (rect(item) for item in (
                        dialog.dataset_name, dialog.add_dataset_button, dialog.delete_dataset_button))
                    assert max(name[1], add[1], delete[1]) - min(name[1], add[1], delete[1]) <= 1, (name, add, delete)
                    assert max(name[3], add[3], delete[3]) - min(name[3], add[3], delete[3]) <= 1, (name, add, delete)
                    assert add[3] == delete[3] == 26
                    assert add[2] == delete[2] == 26
                    assert name[2] >= 90
                    assert 4 <= add[0] - (name[0] + name[2]) <= 10, (name, add)
                    assert 4 <= delete[0] - (add[0] + add[2]) <= 10, (add, delete)
                    datasets = dialog.dataset_list.globalGeometry()
                    workflow = dialog.tool_list.globalGeometry()
                    assert abs(name[0] - datasets.x()) <= 1
                    assert abs(name[0] - workflow.x()) <= 1
                    assert abs(delete[0] + delete[2] - (datasets.x() + datasets.width())) <= 7
                    a = rect(dialog.coordinate_mode)
                    group = QRetainedItem(dialog.coordinate_mode).parentItem().globalGeometry()
                    assert abs(a[0] - group.x()) <= 2
                    assert abs((a[0] + a[2]) - (group.x() + group.width())) <= 4
                    assert not QRetainedItem(dialog.point_editor_container).isVisible()
                    assert dpg.get_item_configuration(dialog.result_grid.tag)['height'] >= 300
                assert not dialog.control_wrapper(dialog.delete_dataset_button).isEnabled()
                dialog.control_wrapper(dialog.add_dataset_button).click()
                pump()
                assert len(dialog.engine.datasets) == 2
                assert dialog.control_wrapper(dialog.delete_dataset_button).isEnabled()
                dialog.control_wrapper(dialog.delete_dataset_button).click()
                pump()
                assert len(dialog.engine.datasets) == 1
                options = dialog._disclosures['reduction']
                assert not dpg.get_value(options)
                # Native combo widgets keep their own show flag while their
                # disclosure is collapsed; the disclosure controls visibility.
                assert not dialog.control_value(options)
                dpg.set_value(options, True)
                dialog._schedule_data_layout()
                pump(30)
                assert dialog.control_value(options) and dialog.control_wrapper(dialog.export_sort).isVisible()
                assert dpg.get_item_configuration(dialog.result_grid.tag)['height'] >= 100
                dpg.set_value(options, False)
                dialog._schedule_data_layout()
                pump()

                dialog.engine.apply_image(Image.new('RGB', (200, 150), 'white'), str(Path(profile) / 'chart.png'))
                for x, y in ((10, 20), (30, 40), (50, 60)):
                    dialog.engine.add_manual_point(x, y)
                dialog._show_tool('automatic')
                pump()
                dialog.control_wrapper(dialog.pick_curve_button).click()
                assert dialog._pick_mode == 'curve'
                dialog._cancel_pick()
                with patch.object(dialog, '_start_extraction') as extract_curve:
                    dialog.control_wrapper(dialog.extract_button).click()
                    extract_curve.assert_called_once_with(auto_detect=True)
                dialog.engine.active_dataset.curve_rgb = (200, 30, 40)
                with patch.object(dialog, '_start_extraction') as extract_curve:
                    dialog.control_wrapper(dialog.extract_button).click()
                    extract_curve.assert_called_once_with(auto_detect=False)
                dialog._show_tool('data')
                pump()
                # Existing .pdg projects use the stable "reduction" panel id.
                # Loading them must not queue a KeyError from deferred restore.
                dpg.set_value(options, True)
                saved_view = dialog._capture_project_view()
                assert saved_view['disclosures']['reduction'] is True
                assert 'data_options' not in saved_view['disclosures']
                project = str(Path(profile) / 'legacy-options.pdg')
                dialog.engine.save_project(project, view_state=saved_view)
                dpg.set_value(options, False)
                with patch.object(view, 'show_error') as errors:
                    dialog._load_project(project)
                    pump(55)
                    errors.assert_not_called()
                assert dpg.get_value(options) is True
                assert len(dialog.engine.active_dataset.manual_points) == 3
                dialog._save_project(str(Path(profile) / 'roundtrip.pdg'))
                assert (Path(profile) / 'roundtrip.pdg').is_file()
                dpg.set_value(options, False)
                dialog._schedule_data_layout()
                pump()
                dialog._data_actions['select_all'].trigger()
                dialog.resize(1240, 780)
                pump()
                assert len(dialog.result_grid.selectedKeys()) == 3
                assert dialog._data_actions['delete'].isEnabled()
                assert not dpg.is_item_shown(dialog.point_editor_container), (
                    'Multi-selection must not show the single-point editor', dialog._active_tool,
                    dialog.result_grid.selectedKeys(), dialog._selected_point)
                multi_height = dpg.get_item_configuration(dialog.result_grid.tag)['height']
                assert multi_height >= 300, ('Multi-selection must leave room for the data table', multi_height)
                dialog.result_grid.setCurrentKey('manual:0')
                pump()
                assert dpg.is_item_shown(dialog.point_editor_container)
                x, y = rect(dialog.point_x), rect(dialog.point_y)
                assert abs(x[1] - y[1]) <= 1 and x[0] + x[2] < y[0], (x, y)
                assert dpg.get_item_configuration(dialog.result_grid.tag)['height'] < multi_height
                dialog.engine.update_dataset(locked=True)
                pump()
                for action in ('delete', 'clear', 'reduce'):
                    assert not dialog._data_actions[action].isEnabled()
                    assert not dialog._data_actions[action].trigger()
                assert len(dialog.engine.active_dataset.manual_points) == 3
                dialog.engine.update_dataset(locked=False)
                pump()
                dialog._data_actions['deselect'].trigger()
                pump()
                assert not dialog.result_grid.selectedKeys()
                assert not dpg.is_item_shown(dialog.point_editor_container)
                dialog._data_actions['select_all'].trigger()
                dialog._data_actions['delete'].trigger()
                pump()
                assert not dialog.engine.active_dataset.manual_points
                dialog._show_tool('extract')
                old_theme = dpg.get_item_theme(dialog.pick_curve_button)
                dialog.engine.set_curve_color((10, 70, 130))
                pump()
                assert dialog._pick_color_rgb == (10, 70, 130)
                assert not dpg.does_item_exist(old_theme), 'Old swatch theme was not released'
                swatch_theme = dpg.get_item_theme(dialog.pick_curve_button)
                first_component = dpg.get_item_children(swatch_theme, 1)[0]
                fills = [dpg.get_value(item) for item in dpg.get_item_children(first_component, 1)
                         if dpg.get_item_type(item).endswith('mvThemeColor') and
                         dpg.get_item_configuration(item)['target'] == dpg.mvThemeCol_Button]
                assert fills == [[10.0, 70.0, 130.0, 255.0]]
                dialog.engine.add_manual_point(10, 20)
                with patch('WinUx.plotdigitizer.core.engine.extract_curve', return_value=[(20, 30), (40, 50)]):
                    assert dialog.engine.extract()
                dialog.engine.add_manual_point(60, 70)
                pump()
                assert len(dialog.engine.active_dataset.manual_points) == 2
                assert len(dialog.engine.active_dataset.extracted_pixels) == 2
                assert dialog._active_tool == 'extract', 'Point creation/extraction changed workflow pages'
                navigation = [rect(item) for item in (
                    dialog.previous_point_button, dialog.apply_point_button, dialog.next_point_button)]
                assert max(r[1] for r in navigation) - min(r[1] for r in navigation) <= 1
                assert max(r[2] for r in navigation) - min(r[2] for r in navigation) <= 2
                assert all(r[3] == 26 and r[2] >= 65 for r in navigation), navigation

                def click_navigation(tag):
                    x, y, width, height = rect(tag)
                    point = (x + width / 2, y + height / 2)
                    assert dialog.event(QMouseEvent(QEvent.MouseButtonPress, point,
                                                   button=Qt.LeftButton, buttons=Qt.LeftButton))
                    assert dialog.event(QMouseEvent(QEvent.MouseButtonRelease, point,
                                                   button=Qt.LeftButton, buttons=Qt.NoButton))
                    pump(4)

                # Direct engine mutations do not simulate a canvas Edit click.
                # Establish the navigation selection explicitly before comparing
                # positions (the old fixture could call keys.index(None)).
                dialog.result_grid.setCurrentKey('manual:1')
                pump()
                keys = [('auto', 0), ('auto', 1), ('manual', 0), ('manual', 1)]
                for position in (2, 1, 0, 1, 2, 3):
                    click_navigation(dialog.previous_point_button if position < keys.index(dialog._selected_point)
                                     else dialog.next_point_button)
                    assert dialog._selected_point == keys[position]
                    assert dialog.result_grid.selectedKeys() == ['{}:{}'.format(*keys[position])]
                    assert dialog.data_worksheet.selected_range.bounds == (position, 0, position, 1)
                    px, py = dialog.engine.point_pixels(*keys[position])
                    assert abs(float(dialog.control_value(dialog.point_x)) - px) <= 1e-6
                    assert abs(float(dialog.control_value(dialog.point_y)) - py) <= 1e-6
                    assert dialog.control_wrapper(dialog.previous_point_button).isEnabled() == (position > 0)
                    assert dialog.control_wrapper(dialog.next_point_button).isEnabled() == (position < len(keys) - 1)
                dialog.set_control_value(dialog.point_x, '62')
                dialog.set_control_value(dialog.point_y, '72')
                click_navigation(dialog.apply_point_button)
                assert dialog.engine.point_pixels('manual', 1) == (62.0, 72.0)
                assert dialog._capture_project_view()['tool'] == 'extract'
                print('PASS: combined manual/automatic Extract Data page, live square color swatch, '
                      'routed Previous/Next/Apply across mixed point sources, project compatibility and compact inspector')
            finally:
                dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
