"""One right sidebar, expanded canvas, workflow/datasets and scroll persistence."""
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
from DearUIQt.widgets import QRetainedItem
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.plotdigitizer.ui.checklist import CHECKBOX_ROUNDING, TEXT_HIGHLIGHT_ROUNDING
from WinUx.view import WinUXView
from test_digitizer_tick_auto_calibration import make_chart


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='unified-sidebar-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
        view._gui_runtime.show()
        dialog = PlotDigitizerDialog(view)
        dialog.show()

        def pump(frames=20):
            for _ in range(frames):
                view.update()
                time.sleep(.01)

        try:
            pump()
            assert len(dialog.workspace.panels) == 2
            assert dialog.dataset_panel == dialog.settings_panel
            assert not hasattr(dialog, 'project_info')
            assert dialog.windowTitle() == 'Plot Digitizer'
            image, _ = make_chart()
            dialog.engine.apply_image(image, 'sidebar.png')
            dialog._load_texture(image)
            dialog._refresh_all()
            assert dialog.windowTitle() == 'Plot Digitizer - sidebar.png'
            def checks():
                listing = dialog.tool_list
                listing._paint_rows()
                for key, surface in listing._row_surfaces.items():
                    paint = listing.backend.get_item_configuration(surface['paint'])
                    assert paint['rounding'] == TEXT_HIGHLIGHT_ROUNDING
                    color = paint['fill']
                    checked = listing.itemForKey(key).checked
                    assert color[1] > color[0] if checked else color[0] > color[1], (
                        key, checked, color, surface['parent'].globalGeometry(),
                        listing.backend.get_item_state(surface['parent'].tag),
                        listing.globalGeometry(), listing.backend.get_item_state(listing.tag),
                        surface['canvas'].exists(), listing._deleted, surface['state'],
                        listing.backend.get_item_state(surface['canvas'].tag))
                    children = listing.backend.get_item_children(surface['parent'].tag, 1)
                    assert children.index(surface['canvas'].tag) < children.index(listing.checkboxes[key])
                    assert children.index(listing.checkboxes[key]) < children.index(listing.nativeItem(key))
                return tuple(dialog.tool_list.itemForKey(key).checked for key in ('axes', 'extract', 'data'))

            assert checks() == (False, False, False)
            assert not hasattr(dialog, 'dataset_name')
            assert not hasattr(dialog, 'dataset_summary')
            assert not hasattr(dialog, 'rename_dataset_button')
            assert not hasattr(dialog, 'apply_point_button')
            assert not hasattr(dialog, 'delete_point_button')
            assert dialog.control_wrapper(dialog.add_dataset_button).text() == 'New'
            assert dialog.control_wrapper(dialog.delete_dataset_button).text() == 'Delete'
            assert not dialog.ribbon._buttons['delete_points']['enabled']
            assert QRetainedItem(dialog.dataset_list.tag).height() == dialog.dataset_list.rowHeight() + 2
            assert '0 pts' in dialog.dataset_list.itemForKey(0).text
            # Checkbox clicks navigate, but cannot manually claim completion.
            dialog.tool_list._check_clicked(dialog.tool_list.checkboxes['extract'], True, 'extract')
            pump()
            assert dialog._active_tool == 'extract' and checks() == (False, False, False)
            for key, px, py, value in (('x1', 110, 390, 0), ('x2', 600, 390, 10)):
                dialog.engine.set_anchor(key, px, py, value)
            pump()
            assert not checks()[0], 'One calibrated axis must not complete calibration'
            for key, px, py, value in (('y1', 110, 390, 0), ('y2', 110, 60, 20)):
                dialog.engine.set_anchor(key, px, py, value)
            pump()
            assert checks() == (True, False, False)
            dialog.engine.set_calibration_points('y', [])
            pump()
            assert not checks()[0]
            dialog.engine.undo()
            pump()
            assert checks()[0]
            dialog.engine.add_manual_point(200, 200)
            pump()
            assert checks() == (True, True, False)
            dialog._show_tool('data')
            pump()
            assert checks() == (True, True, True)
            dialog._show_tool('axes')
            dialog.engine.add_manual_point(220, 220)
            pump()
            assert checks() == (True, True, False), 'Changed data must be reviewed again'
            dialog._show_tool('extract')
            dialog.set_control_value(dialog.coordinate_mode, 'Image pixels')
            dialog.result_grid.setCurrentKey('manual:0', select=True)
            dialog._point_selected('manual:0')
            pump()
            dialog.set_control_value(dialog.point_y, '214')
            dialog.set_control_value(dialog.point_x, '212')
            editor = dialog.control_wrapper(dialog.point_x)
            assert editor.backend.get_item_configuration(editor.tag)['on_enter']
            # Deliver the native on-enter editor callback, with no Apply button.
            editor._changed(editor.tag, '212')
            pump()
            assert dialog.engine.point_pixels('manual', 0) == (212.0, 214.0), (
                dialog._selected_point, dialog.engine.point_pixels('manual', 0),
                dialog.control_value(dialog.point_x), dialog.control_value(dialog.point_y),
                dialog.control_value(dialog.status))
            assert not hasattr(dialog, 'apply_point_button')
            assert not dialog._edit_enabled
            assert dialog.ribbon._buttons['delete_points']['enabled']
            dialog.ribbon._button_clicked('delete_points')
            pump()
            assert len(dialog.engine.active_dataset.manual_points) == 1
            assert not dialog.ribbon._buttons['delete_points']['enabled']
            dialog.engine.undo()
            pump()
            assert len(dialog.engine.active_dataset.manual_points) == 2
            # Mixed automatic/manual multi-selection uses the same Delete
            # command, with no Edit-mode prerequisite for an explicit click.
            dialog.engine.active_dataset.extracted_pixels = [(180, 180), (190, 190)]
            dialog.engine.recompute_all_data()
            dialog._refresh_all()
            dialog.result_grid.selected = {'auto:0', 'manual:1'}
            dialog._selected_point = None
            dialog._refresh_point_actions()
            dialog.ribbon._button_clicked('delete_points')
            pump()
            assert dialog.engine.active_dataset.extracted_pixels == [(190, 190)]
            assert len(dialog.engine.active_dataset.manual_points) == 1
            assert dialog.engine.point_pixels('manual', 0) == (212.0, 214.0)
            dialog.engine.undo()
            pump()
            assert len(dialog.engine.active_dataset.extracted_pixels) == 2
            assert len(dialog.engine.active_dataset.manual_points) == 2
            dialog._dataset_visibility_changed(0, False)
            pump()
            assert not dialog.engine.active_dataset.visible
            assert not dialog.dataset_list.itemForKey(0).checked
            dialog.engine.update_dataset(locked=True)
            pump()
            assert not dialog.control_wrapper(dialog.delete_dataset_button).isEnabled()
            dialog.result_grid.selected = {'manual:0'}
            dialog._refresh_point_actions()
            assert not dialog.ribbon._buttons['delete_points']['enabled']
            dialog.ribbon._button_clicked('delete_points')
            assert len(dialog.engine.active_dataset.manual_points) == 2
            dialog.engine.update_dataset(locked=False)
            pump()
            for width, height in ((1100, 700), (1380, 860)):
                dialog.resize(width, height)
                pump()
                sidebar = QRetainedItem(dialog.settings_panel).globalGeometry()
                canvas = QRetainedItem(dialog.canvas_panel).globalGeometry()
                assert canvas.x() < sidebar.x()
                assert canvas.x() + canvas.width() <= sidebar.x()
                assert canvas.width() >= 650, canvas
                assert 270 <= sidebar.width() <= dialog.RIGHT_WIDTH + 2, sidebar
                for tool in ('extract', 'data', 'axes'):
                    dialog.tool_list.setCurrentKey(tool, select=True)
                    pump()
                    assert dialog._active_tool == tool
                    for key, page in dialog._tool_pages.items():
                        assert QRetainedItem(page).isVisible() == (key == tool)
                    for widget in (dialog.tool_list.tag, dialog.dataset_list.tag):
                        bounds = QRetainedItem(widget).globalGeometry()
                        assert sidebar.x() <= bounds.x()
                        assert bounds.x() + bounds.width() <= sidebar.x() + sidebar.width()
                    for listing in (dialog.tool_list, dialog.dataset_list):
                        for key, tag in listing.checkboxes.items():
                            check = QRetainedItem(tag).globalGeometry()
                            row = QRetainedItem(listing.nativeItem(key)).globalGeometry()
                            assert row.x() >= check.x() + check.width() + 4, (check, row)
                            theme = listing.backend.get_item_theme(tag)
                            rounding = []
                            for component in listing.backend.get_item_children(theme, 1):
                                for item in listing.backend.get_item_children(component, 1):
                                    config = listing.backend.get_item_configuration(item)
                                    if config.get('target') == listing.backend.mvStyleVar_FrameRounding:
                                        rounding.append(listing.backend.get_value(item)[0])
                            assert rounding and all(value == CHECKBOX_ROUNDING for value in rounding), rounding
                    listing = QRetainedItem(dialog.dataset_list.tag).globalGeometry()
                    new = QRetainedItem(dialog.add_dataset_button).globalGeometry()
                    delete = QRetainedItem(dialog.delete_dataset_button).globalGeometry()
                    assert listing.y() >= new.y() + new.height() + 6, (listing, new)
                    assert delete.x() >= new.x() + new.width() + 4, (new, delete)
                    workflow = QRetainedItem(dialog.tool_list.tag).globalGeometry()
                    assert workflow.y() > listing.y() + listing.height(), (listing, workflow)
            dialog._add_dataset()
            pump()
            assert len(dialog.engine.datasets) == 2
            assert checks() == (True, False, False), 'Workflow completion follows the active dataset'
            scroll = QRetainedItem(dialog.settings_panel)
            dialog.set_control_value(dialog._disclosures['axes'], True)
            pump()
            scroll.setVerticalScrollValue(100)
            pump()
            saved_scroll = scroll.verticalScrollValue()
            assert saved_scroll > 0
            path = str(Path(profile) / 'sidebar.pdg')
            dialog._save_project(path)
            scroll.setVerticalScrollValue(0)
            dialog._load_project(path)
            pump(45)
            assert abs(scroll.verticalScrollValue() - saved_scroll) <= 2
            assert len(dialog.engine.datasets) == 2
            dialog.engine.clean_markers()
            pump()
            assert checks() == (False, False, False)
            print('PASS: list/New/Delete only, visibility/lock, automatic workflow checkboxes, calibration validity, review invalidation and sidebar scroll restoration')
        finally:
            dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
