"""Rendered unified Samples dialog and real engine operations."""
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
from DearUIQt.widgets import QRetainedItem
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.plotdigitizer.core.models import DataPoint


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-samples-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None

        def pump(count=15):
            for _ in range(count):
                view.update()
                time.sleep(.01)

        def count():
            ds = dialog.engine.active_dataset
            return len(ds.manual_points) + len(ds.extracted_pixels)

        def open_samples(mode='count'):
            prompt = dialog._open_samples_dialog(mode)
            pump()
            assert prompt is dialog._sample_count_dialog and prompt.isVisible()
            assert prompt.windowTitle() == 'Resample Curve'
            bounds = QRetainedItem(prompt.tag).globalGeometry()
            for tag in (prompt.operation, prompt.target_editor.tag, prompt.factor_editor.tag,
                        prompt.error_editor.tag, prompt.apply_button, prompt.cancel_button):
                rect = QRetainedItem(tag).globalGeometry()
                assert rect.width() > 0 and rect.height() > 0, (tag, rect)
                assert rect.y() >= bounds.y() and rect.y() + rect.height() <= bounds.y() + bounds.height(), (rect, bounds)
            return prompt

        try:
            view._gui_runtime.show()
            dialog = PlotDigitizerDialog(view)
            dialog.show()
            dialog.engine.apply_image(Image.new('RGB', (200, 200), 'white'), 'samples.png')
            dialog.engine.active_dataset.manual_points = [DataPoint(x, x) for x in range(10, 70, 10)]
            dialog._refresh_point_actions()
            pump()
            assert dialog.ribbon._buttons['samples']['enabled']
            prompt = open_samples()
            prompt.factor_editor.setText('2')
            prompt._factor_changed()
            assert prompt.target_editor.text() == '12'
            prompt._accept()
            pump()
            assert count() == 12, count()
            assert dialog._sample_count_dialog is None

            prompt = open_samples()
            prompt.target_editor.setText('6')
            prompt._target_changed()
            assert float(prompt.factor_editor.text()) == .5
            prompt._accept()
            pump()
            assert count() == 6, count()

            prompt = open_samples('simplify')
            assert not prompt.target_editor.isEnabled()
            assert prompt.error_editor.isEnabled()
            prompt.error_editor.setText('nan')
            assert not prompt._validate()
            assert not prompt.control_wrapper(prompt.apply_button).isEnabled()
            prompt.error_editor.setText('0')
            prompt._accept()
            pump()
            assert count() == 2, count()

            prompt = open_samples()
            prompt._close_from_escape()
            pump()
            assert count() == 2 and dialog._sample_count_dialog is None
            dialog.engine.active_dataset.locked = True
            dialog._refresh_point_actions()
            assert not dialog.ribbon._buttons['samples']['enabled']
            assert dialog._open_samples_dialog() is None
            print('PASS Samples GUI: linked factor/count, increase, reduce, simplify, invalid error, Esc and locked dataset')
        finally:
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
