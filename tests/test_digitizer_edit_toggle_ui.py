"""Unified ribbon Edit: add/select/delete, read-only off state and project restore."""
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
from DearUIQt.core import QPoint, Qt
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-edit-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile, 'WINUX_LOG_DIR': str(temp / 'digitizer-edit-logs')}):
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

            def pointer(point, release=False):
                with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                        patch.object(dialog, '_canvas_to_image', return_value=point), \
                        patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=QPoint(40, 50)):
                    if release:
                        dialog._mouse_left_up()
                    else:
                        dialog._mouse_left()
                        dialog._mouse_left_up()

            def key(value, modifiers=0, inside=True):
                with patch.object(dialog, '_mouse_in_canvas', return_value=inside), \
                        patch.object(dialog, '_accepts_edit_shortcut', return_value=True), \
                        patch('WinUx.plotdigitizer.ui.dialog.QKeyboard.modifiers', return_value=modifiers):
                    dialog._edit_key(None, key=value)

            pump(30)
            assert not hasattr(dialog, 'add_point_button')
            assert not hasattr(dialog, 'edit_points_button')
            assert not dialog.ribbon._buttons['edit']['enabled']
            assert not dialog.ribbon.is_button_checked('edit')
            assert not hasattr(dialog, 'delete_point_button')
            delete_button = dialog._data_actions['delete']
            assert not delete_button.isEnabled()
            dialog.engine.apply_image(Image.new('RGB', (200, 160), 'white'), 'chart.png')
            dialog._load_texture(dialog.engine.image)
            pump()
            dataset = dialog.engine.active_dataset
            assert dialog.ribbon._buttons['edit']['enabled'], 'Edit must work on an empty dataset'
            pointer((20, 30))
            assert not dataset.manual_points, 'Edit-off canvas click added a point'
            dialog.ribbon._button_clicked('edit')
            assert dialog._edit_enabled and dialog.ribbon.is_button_checked('edit')
            assert dialog._pick_mode is None
            assert not delete_button.isEnabled(), 'Del must require a selection'
            pointer((20, 30))
            assert len(dataset.manual_points) == 1
            assert dialog._selected_point == ('manual', 0)
            assert delete_button.isEnabled()
            pointer((20, 30))
            pointer((20, 30), release=True)
            assert len(dataset.manual_points) == 1, 'Clicking a marker duplicated it'
            assert dialog._selected_point == ('manual', 0)
            key(Qt.Key_Delete, inside=False)
            pump()
            assert not dataset.manual_points and dialog._selected_point is None
            assert not delete_button.isEnabled()
            assert dialog._edit_enabled and dialog.ribbon.is_button_checked('edit')
            key(Qt.Key_Z, Qt.ControlModifier)
            pump()
            dataset = dialog.engine.active_dataset
            assert len(dataset.manual_points) == 1, 'Undo did not restore deleted point'
            pointer((100, 90))
            assert len(dataset.manual_points) == 2
            assert delete_button.isEnabled()
            key(Qt.Key_Delete)
            pump()
            assert len(dataset.manual_points) == 1
            assert dialog._pick_mode is None and dialog._edit_enabled
            assert not delete_button.isEnabled()
            key(Qt.Key_Z, Qt.ControlModifier)
            pump()
            dataset = dialog.engine.active_dataset
            assert len(dataset.manual_points) == 2
            dataset.extracted_pixels = [(150, 110)]
            dialog._refresh_all()
            pointer((150, 110))
            assert dialog._selected_point == ('auto', 0)
            assert len(dataset.manual_points) == 2, 'Selecting an automatic marker added a point'
            pointer((150, 110), release=True)
            key(Qt.Key_Delete)
            pump()
            assert not dataset.extracted_pixels and len(dataset.manual_points) == 2
            dialog._begin_pick('area')
            assert not dialog._edit_enabled and not dialog.ribbon.is_button_checked('edit')
            assert dialog._pick_mode == 'area'
            dialog.ribbon._button_clicked('edit')
            assert dialog._edit_enabled and dialog._pick_mode is None
            pointer((20, 30))
            pointer((20, 30), release=True)
            assert delete_button.isEnabled()
            state = dialog._capture_project_view()
            assert state['edit_enabled']
            dialog._close_from_escape()
            assert dialog.winfo_exists() and dialog._edit_enabled
            assert dialog.ribbon.is_button_checked('edit')
            assert dialog._selected_point is None and not dialog.result_grid.selectedKeys()
            assert not delete_button.isEnabled()
            dialog.result_grid.selected = {'manual:0', 'manual:1'}
            dialog._refresh_point_editor()
            assert delete_button.isEnabled()
            key(Qt.Key_Escape, inside=False)
            assert dialog._edit_enabled and dialog.ribbon.is_button_checked('edit')
            assert not dialog.result_grid.selectedKeys()
            assert not delete_button.isEnabled()
            dialog._close_from_escape()
            assert dialog.winfo_exists() and not dialog._edit_enabled
            assert not dialog.ribbon.is_button_checked('edit')
            key(Qt.Key_Delete, inside=False)
            assert len(dataset.manual_points) == 2, 'Edit-off Delete removed canvas points'
            pointer((170, 130))
            assert len(dataset.manual_points) == 2
            key(Qt.Key_S)
            assert dialog._edit_enabled and dialog.ribbon.is_button_checked('edit')
            key(Qt.Key_S)
            assert not dialog._edit_enabled and not dialog.ribbon.is_button_checked('edit')
            dialog._restore_project_view(state, dialog._project_load_generation, 0)
            pump()
            assert dialog._edit_enabled and dialog.ribbon.is_button_checked('edit')
            dialog.result_grid.selected = {'manual:0', 'manual:1'}
            dialog._refresh_point_editor()
            assert delete_button.isEnabled()
            key(Qt.Key_Delete)
            pump()
            assert not dialog.engine.active_dataset.manual_points
            assert dialog._edit_enabled and dialog._pick_mode is None
            key(Qt.Key_Z, Qt.ControlModifier)
            pump()
            dataset = dialog.engine.active_dataset
            assert len(dataset.manual_points) == 2
            dialog.engine.update_dataset(locked=True)
            pump()
            assert not dialog._edit_enabled and not dialog.ribbon.is_button_checked('edit')
            assert not dialog.ribbon._buttons['edit']['enabled']
            pointer((170, 130))
            assert len(dataset.manual_points) == 2
            print('PASS: Edit -> select -> Esc deselect -> Delete/Del, including multiple points; no click-delete mode; '
                  'off/locked guards; manual/automatic points; Undo, Escape and workspace restore; no OS mouse movement', flush=True)
        finally:
            runtime.view._dispatcher.close()
            if runtime.native:
                runtime.native.set_visible(False)
                runtime.native.restore_close_handler()
                runtime.native.close_activation_guard()
            runtime.gui.destroy()


if __name__ == '__main__':
    main()
