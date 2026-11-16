"""Settings is an owned dialog, not a workspace/workflow tab.

abaqus python tests/test_digitizer_settings_dialog_ui.py
abaqus python tests/test_digitizer_settings_dialog_ui.py --floating
"""
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
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.plotdigitizer.ui.settings import PlotDigitizerSettingsDialog
from WinUx.preferences.plot_digitizer import PlotDigitizerPreferences
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-settings-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        floating = '--floating' in sys.argv
        runtime = view = dialog = None
        try:
            if floating:
                runtime = FloatingDialogRuntime(Mock(), iter(()), {
                    'kind': 'plotdigitizer', 'title': 'Plot Digitizer', 'visible': True,
                    'payload': {}, 'width': 1240, 'height': 780})
                runtime.gui.createContext(manual_callbacks=True)
                runtime._publish_requested = runtime._commit_requested = True
                runtime._build()
                dialog = runtime.form

                def pump(count=14):
                    for _ in range(count):
                        runtime._drain_form_callbacks()
                        runtime.view.drain()
                        runtime.gui.renderFrame()
                        runtime.view.mark_presented()
                        time.sleep(.01)
            else:
                view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
                view._gui_runtime.show()
                dialog = PlotDigitizerDialog(view)
                dialog.show()

                def pump(count=14):
                    for _ in range(count):
                        view.update()
                        time.sleep(.01)

            pump(35)
            settings = dialog._settings_dialog
            assert isinstance(settings, PlotDigitizerSettingsDialog)
            assert settings.parent is dialog and settings.tag != dialog.tag
            assert not settings.isVisible(), 'Settings opened during parent construction'
            assert 'settings' not in dialog._tool_pages
            dialog.engine.apply_image(Image.new('RGB', (140, 100), 'white'), 'settings-test.png')
            dialog._load_texture(dialog.engine.image)
            dialog._show_tool('extract')
            pump()
            workflow = dialog._active_tool
            dialog._open_settings()
            pump()
            assert settings.isVisible() and settings.modal
            assert dialog._active_tool == workflow and dialog.tool_list.currentKey() == workflow
            assert not dialog._accepts_edit_shortcut()
            for tag in (dialog.tolerance, dialog._preference_controls['show_crosshair']):
                assert tag in settings._control_wrappers
            check = settings._control_wrappers[dialog._preference_controls['show_crosshair']]
            check.setChecked(False)
            assert not dialog._plot_preferences['show_crosshair']
            assert not PlotDigitizerPreferences().load()['show_crosshair']
            # End the initial numeric editor's active text draft before
            # injecting an equivalent committed value change.
            settings.focus_control(settings._default_button)
            pump(4)
            settings._control_wrappers[dialog.tolerance].setValue(77)
            settings._control_wrappers[dialog.tolerance]._changed(dialog.tolerance, 77)
            pump()
            assert dialog.engine.active_dataset.settings.tolerance == 77, (
                dialog.engine.active_dataset.settings, dialog.control_value(dialog.tolerance))
            assert dialog.control_value(dialog.tolerance) == 77
            revision = dialog.engine.revision
            for key, value in (('preview_zoom', 9), ('preview_size', 200), ('wheel_zoom_percent', 25)):
                tag = dialog._preference_controls[key]
                spinner = settings._control_wrappers[tag]
                spinner.setValue(value)
                spinner._changed(tag, value)
                pump(3)
                assert dialog._plot_preferences[key] == value
                assert PlotDigitizerPreferences().load()[key] == value
            preview_crosshair = settings._control_wrappers[dialog._preference_controls['preview_crosshair']]
            preview_crosshair.setChecked(False)
            painter = Mock()
            dialog._paint_preview(painter)
            assert painter.drawText.call_args.args[1] == '9x'
            assert painter.drawLine.call_count == 0
            first, last = painter.drawRect.call_args.args[:2]
            assert last[0] - first[0] == 202 and last[1] - first[1] == 202
            assert dialog.engine.revision == revision, 'Display settings mutated project data'
            with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                    patch.object(dialog, '_zoom_at') as zoom:
                dialog._mouse_wheel(None, 1)
                assert zoom.call_args.args[0] == 1.25
                dialog._mouse_wheel(None, -1)
                assert zoom.call_args.args[0] == .8
            settings._close_from_escape()
            pump()
            assert not settings.isVisible() and dialog.winfo_exists()
            assert dialog._active_tool == workflow
            dialog._open_settings()
            pump()
            assert dialog._settings_dialog is settings and not check.isChecked()
            assert settings.control_value(dialog._preference_controls['preview_zoom']) == 9
            dialog._reset_plot_preferences()
            assert check.isChecked() == PlotDigitizerPreferences.DEFAULTS['show_crosshair']
            assert preview_crosshair.isChecked()
            for key in ('preview_zoom', 'preview_size', 'wheel_zoom_percent'):
                assert settings.control_wrapper(dialog._preference_controls[key]).value() == PlotDigitizerPreferences.DEFAULTS[key]
            settings._close_from_native()
            pump()
            assert not settings.isVisible() and dialog.winfo_exists()
            # Explicit destruction is used here; a production retained host
            # may replace the root's public destroy method with hide/recycle.
            PlotDigitizerDialog.destroy(dialog)
            pump(20)
            assert not settings.winfo_exists(), 'Owner teardown left Settings alive'
            dialog = None
            print('PASS:', 'floating' if floating else 'in-process',
                  'owned Settings dialog; preserved workflow, live/persisted preferences, engine sync, reopen and cleanup', flush=True)
        finally:
            if runtime is not None:
                runtime.view._dispatcher.close()
                if runtime.native:
                    runtime.native.set_visible(False)
                    runtime.native.restore_close_handler()
                    runtime.native.close_activation_guard()
                runtime.gui.destroy()
            elif view is not None:
                if dialog is not None:
                    dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
