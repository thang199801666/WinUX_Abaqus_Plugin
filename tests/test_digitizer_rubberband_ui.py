"""Canvas rubberband and real shortcut scope/event routing, without OS mouse movement."""
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
from DearUIQt.core import QPoint, Qt, QEvent, QKeyEvent
from DearUIQt.backends import dpg
from DearUIQt.widgets import QRetainedItem, QApplication
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='rubberband-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile, 'WINUX_LOG_DIR': str(temp / 'rubberband-logs')}):
        runtime = None
        if '--inprocess' in sys.argv:
            from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
            from WinUx.view import WinUXView
            from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
        else:
            runtime = FloatingDialogRuntime(Mock(), iter(()), {
                'kind': 'plotdigitizer', 'title': 'Plot Digitizer', 'visible': True,
                'payload': {}, 'width': 1240, 'height': 800})
            runtime.gui.createContext(manual_callbacks=True)
            runtime._publish_requested = runtime._commit_requested = True
        try:
            if runtime is not None:
                runtime._build()
                dialog = runtime.form
            else:
                dialog = PlotDigitizerDialog(view)
                dialog.show()

            def pump(count=12):
                for _ in range(count):
                    if runtime is not None:
                        runtime._drain_form_callbacks()
                        runtime.view.drain()
                        runtime.gui.renderFrame()
                        runtime.view.mark_presented()
                    else:
                        view.update()
                    time.sleep(.01)

            def mouse(point, phase, modifiers=0):
                origin, _ = dialog._canvas_rect()
                local = dialog._image_to_canvas(*point)
                position = QPoint(round(origin[0] + local[0]), round(origin[1] + local[1]))
                with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                        patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=position), \
                        patch('WinUx.plotdigitizer.ui.dialog.QKeyboard.modifiers', return_value=modifiers):
                    getattr(dialog, {'down': '_mouse_left', 'move': '_mouse_move', 'up': '_mouse_left_up'}[phase])()

            def click(point):
                mouse(point, 'down')
                mouse(point, 'up')

            def delete_event(key):
                event = QKeyEvent(QEvent.KeyPress, key)
                application = QApplication.instance()
                return application.dispatchKeyEvent(event) if application is not None else dialog.sendEvent(event)

            def band(start, end, modifiers=0):
                before = len(dialog.engine.active_dataset.manual_points)
                revision, roi = dialog.engine.revision, dialog.engine.plot_rect
                mouse(start, 'down', modifiers)
                mouse(end, 'move', modifiers)
                assert dialog._rubberband_active
                assert dialog._pointer_layer.exists()
                mouse(end, 'up', modifiers)
                assert not dialog._rubberband_active and dialog._point_press is None
                assert len(dialog.engine.active_dataset.manual_points) == before, 'Selection drag added a point'
                assert dialog.engine.revision == revision and dialog.engine.plot_rect == roi, 'Selection mutated plot data'

            pump(30)
            dialog.engine.apply_image(Image.new('RGB', (240, 180), 'white'), 'points.png')
            dialog._load_texture(dialog.engine.image)
            for point in ((20, 20), (60, 50), (130, 100)):
                dialog.engine.add_manual_point(*point)
            dialog.engine.active_dataset.extracted_pixels = [(70, 70), (180, 140)]
            pump()
            dialog._refresh_all()
            dialog.ribbon._button_clicked('edit')
            dialog._auto_fit = False
            dialog._fit_scale, dialog._zoom, dialog._pan = 2., 1.25, [35., -18.]
            dialog._redraw()
            hwnd = dialog._native_window_backend.winId(dialog.tag) if dialog._native_window_backend is not None else 0
            if not hwnd:
                hwnd = dialog.view._find_main_viewport_hwnd()
            # Only the external desktop foreground is injected. Do not bypass
            # _accepts_edit_shortcut or the actual retained focus/parent walk.
            with patch('WinUx.ui.native.dialog_focus.foreground_hwnd', return_value=hwnd):
                click((20, 20))
                focused = QRetainedItem.focusedItem()
                assert dialog._accepts_edit_shortcut(), (
                    'Canvas shortcut rejected', dialog.tag, focused.tag if focused else None,
                    focused.itemType() if focused else None)
                assert delete_event(Qt.Key_Delete)
                assert len(dialog.engine.active_dataset.manual_points) == 2
                dialog.engine.undo()
                pump()
                click((20, 20))
                with patch('WinUx.plotdigitizer.ui.dialog.QKeyboard.modifiers', return_value=0):
                    assert dialog.shortcuts[(dpg.mvKey_Delete, False)]()
                assert len(dialog.engine.active_dataset.manual_points) == 2
                dialog.engine.undo()
                pump()
                band((10, 10), (100, 90))
                expected = {'manual:0', 'manual:1', 'auto:0'}
                assert set(dialog.result_grid.selectedKeys()) == expected
                assert dialog._selected_point is None
                assert dialog.control_value(dialog.point_info) == '3 points selected'
                assert dialog._data_actions['delete'].isEnabled()
                assert delete_event(dpg.mvKey_Delete)
                assert len(dialog.engine.active_dataset.manual_points) == 1
                assert len(dialog.engine.active_dataset.extracted_pixels) == 1
                assert dialog._edit_enabled
                dialog.engine.undo()
                pump()
                band((100, 90), (10, 10))
                assert set(dialog.result_grid.selectedKeys()) == expected
                band((110, 90), (150, 120), Qt.ControlModifier)
                assert set(dialog.result_grid.selectedKeys()) == expected | {'manual:2'}
                band((160, 120), (200, 160), Qt.ShiftModifier)
                assert len(dialog.result_grid.selectedKeys()) == 5
                dialog._plot_preferences['show_automatic_points'] = False
                band((10, 10), (230, 170))
                assert set(dialog.result_grid.selectedKeys()) == {'manual:0', 'manual:1', 'manual:2'}
                dialog._plot_preferences['show_automatic_points'] = True
                band((200, 10), (225, 30))
                assert not dialog.result_grid.selectedKeys()
                before = len(dialog.engine.active_dataset.manual_points)
                mouse((215, 25), 'down')
                assert len(dialog.engine.active_dataset.manual_points) == before
                mouse((215, 25), 'up')
                assert len(dialog.engine.active_dataset.manual_points) == before + 1
                dialog.engine.undo()
                pump()
                mouse((10, 10), 'down')
                mouse((100, 90), 'move')
                dialog._close_from_escape()
                assert dialog._point_press is None and dialog._edit_enabled
                assert len(dialog.engine.active_dataset.manual_points) == 3
                click((20, 20))
                dialog.focus_control(dialog.point_x)
                pump(2)
                count = len(dialog.engine.active_dataset.manual_points)
                delete_event(Qt.Key_Delete)
                assert len(dialog.engine.active_dataset.manual_points) == count, 'Delete in text editor removed points'
                dialog._settings_dialog.show()
                delete_event(Qt.Key_Delete)
                assert len(dialog.engine.active_dataset.manual_points) == count, 'Delete passed through Settings'
                dialog._settings_dialog.hide()
            print('PASS: real Delete key scope/routing, pan/zoom rubberband in both directions, '
                  'mixed/multiple selection, Ctrl-add, click-to-add on release, Escape and editor/modal guards', flush=True)
        finally:
            if runtime is not None:
                runtime.view._dispatcher.close()
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
