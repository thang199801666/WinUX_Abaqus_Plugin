"""Filename captions on both the dialog surface and the actual native window."""
import ctypes
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
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-title-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        runtime = FloatingDialogRuntime(Mock(), iter(()), {
            'kind': 'plotdigitizer', 'title': 'Plot Digitizer', 'visible': True,
            'payload': {}, 'width': 1240, 'height': 800})
        runtime.gui.createContext(manual_callbacks=True)
        runtime._publish_requested = runtime._commit_requested = True
        try:
            runtime._build()
            dialog = runtime.form

            def pump(count=18):
                for _ in range(count):
                    runtime._drain_form_callbacks()
                    runtime.view.drain()
                    runtime.gui.renderFrame()
                    runtime.view.mark_presented()
                    time.sleep(.01)

            def caption(expected):
                pump()
                assert dialog.windowTitle() == expected
                buffer = ctypes.create_unicode_buffer(1024)
                ctypes.windll.user32.GetWindowTextW(ctypes.c_void_p(runtime.native.hwnd), buffer, len(buffer))
                assert buffer.value == expected, (buffer.value, expected)

            caption('Plot Digitizer')
            first = Path(profile) / 'Test-Plotdigitizer-04.png'
            Image.new('RGB', (100, 80), 'white').save(first)
            dialog.engine.load_image(str(first))
            caption('Plot Digitizer - Test-Plotdigitizer-04.png')
            project = Path(profile) / 'caption.pdg'
            dialog.engine.save_project(str(project))
            second = Path(profile) / 'Another chart.png'
            Image.new('RGB', (100, 80), 'white').save(second)
            dialog.engine.load_image(str(second))
            caption('Plot Digitizer - Another chart.png')
            dialog.engine.load_project(str(project))
            caption('Plot Digitizer - Test-Plotdigitizer-04.png')
            dialog.engine.clean_project()
            caption('Plot Digitizer')
            print('PASS: native/dialog captions on image open, replacement, project restore and Clean Project')
        finally:
            runtime.view._dispatcher.close()
            if runtime.native:
                runtime.native.set_visible(False)
                runtime.native.restore_close_handler()
                runtime.native.close_activation_guard()
            runtime.gui.destroy()


if __name__ == '__main__':
    main()
