"""Aligned export options, axis combo and actual CSV output on the UI."""
import csv
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
from DearUIQt.widgets import QRetainedItem
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-export-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile,
                                   'WINUX_LOG_DIR': str(temp / 'digitizer-export-options-logs')}):
        view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None
        try:
            view._gui_runtime.show()
            dialog = PlotDigitizerDialog(view)
            dialog.show()

            def pump(count=18):
                for _ in range(count):
                    view.update()
                    time.sleep(.01)

            pump(30)
            dialog._show_tool('data')
            dialog.set_control_value(dialog._disclosures['reduction'], True)
            dialog._schedule_data_layout()
            pump(30)
            controls = [QRetainedItem(dialog.control_wrapper(dialog.reduction_error).container).globalGeometry(),
                        dialog.control_wrapper(dialog.export_scope).globalGeometry(),
                        dialog.control_wrapper(dialog.export_sort).globalGeometry()]
            assert max(rect.x() for rect in controls) - min(rect.x() for rect in controls) <= 1
            assert max(rect.width() for rect in controls) - min(rect.width() for rect in controls) <= 1, controls
            assert controls[0].bottom() < controls[1].top() < controls[2].top()
            assert dialog.control_value(dialog.export_sort) == 'Original order'
            dialog.engine.apply_image(Image.new('RGB', (100, 100), 'white'), 'test.png')
            for key, x, y, value in (('x1', 0, 0, 0), ('x2', 99, 0, 99),
                                      ('y1', 0, 0, 99), ('y2', 0, 99, 0)):
                dialog.engine.set_anchor(key, x, y, value)
            for point in ((30, 80), (10, 20), (20, 50)):
                dialog.engine.add_manual_point(*point)
            pump()
            dialog._show_tool('data')
            for label, axis, expected in (('Sort by X', 'x', [10, 20, 30]), ('Sort by Y', 'y', [30, 20, 10])):
                dialog.set_control_value(dialog.export_sort, label)
                pump(4)
                saved = dialog._capture_project_view()
                assert saved['export_sort'] == axis
                path = Path(profile) / (axis + '.csv')
                dialog._export_csv(str(path))
                with path.open(newline='', encoding='utf-8') as file:
                    assert [round(float(row['X'])) for row in csv.DictReader(file)] == expected
                dialog.set_control_value(dialog.export_sort, 'Original order')
                dialog._restore_project_view(saved, dialog._project_load_generation, 0)
                pump()
                assert dialog.control_value(dialog.export_sort) == label
            print('PASS: aligned Options controls; X/Y CSV sorting and workspace restore', flush=True)
        finally:
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
