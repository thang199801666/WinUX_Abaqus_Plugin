"""Actual project Save/Save As and Ctrl+S in the standalone Digitizer host."""
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
from DearUIQt.core import Qt
from WinUx.plotdigitizer.core import DigitizerEngine
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-save-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile, 'WINUX_LOG_DIR': str(temp / 'digitizer-save-logs')}):
        runtime = FloatingDialogRuntime(Mock(), iter(()), {
            'kind': 'plotdigitizer', 'title': 'Plot Digitizer', 'visible': True,
            'payload': {}, 'width': 1240, 'height': 780})
        runtime.gui.createContext(manual_callbacks=True)
        runtime._publish_requested = runtime._commit_requested = True
        try:
            runtime._build()

            def pump(count=18):
                for _ in range(count):
                    runtime._drain_form_callbacks()
                    runtime.view.drain()
                    runtime.gui.renderFrame()
                    runtime.view.mark_presented()
                    time.sleep(.01)

            dialog = runtime.form
            pump(40)
            dialog.engine.apply_image(Image.new('RGB', (120, 100), 'white'), 'chart.png')
            pump()
            original = Path(profile) / 'original.pdg'
            dialog._save_project(str(original))
            assert original.is_file() and dialog._project_path == str(original.resolve())
            dialog._load_project(str(original))
            pump(35)
            assert dialog._project_path == str(original.resolve())
            dialog.engine.add_manual_point(10, 20)
            pump()
            with patch.object(dialog, '_file_picker') as picker, \
                    patch.object(dialog, '_accepts_edit_shortcut', return_value=True), \
                    patch('WinUx.plotdigitizer.ui.dialog.QKeyboard.modifiers', return_value=Qt.ControlModifier):
                dialog._edit_key(None, key=Qt.Key_S)
                picker.assert_not_called()
            saved = DigitizerEngine()
            saved.load_project(str(original))
            assert len(saved.active_dataset.manual_points) == 1
            before = original.read_bytes()
            with patch.object(dialog, '_file_picker') as picker, \
                    patch.object(dialog, '_accepts_edit_shortcut', return_value=True), \
                    patch('WinUx.plotdigitizer.ui.dialog.QKeyboard.modifiers',
                          return_value=Qt.ControlModifier | Qt.ShiftModifier):
                dialog._edit_key(None, key=Qt.Key_S)
                picker.assert_called_once()
                assert dialog._project_path == str(original.resolve())
                another = Path(profile) / 'save_as.pdg'
                picker.call_args.kwargs['callback'](str(another))
            assert another.is_file() and dialog._project_path == str(another.resolve())
            dialog.engine.add_manual_point(30, 40)
            pump()
            dialog._choose_save_project()
            saved.load_project(str(another))
            assert len(saved.active_dataset.manual_points) == 2
            assert original.read_bytes() == before, 'Save As continued overwriting the old project'
            print('PASS: .pdg load/restore, Ctrl+S overwrite without picker, Ctrl+Shift+S/Save As and subsequent saves', flush=True)
        finally:
            runtime.view._dispatcher.close()
            if runtime.native:
                runtime.native.set_visible(False)
                runtime.native.restore_close_handler()
                runtime.native.close_activation_guard()
            runtime.gui.destroy()


if __name__ == '__main__':
    main()
