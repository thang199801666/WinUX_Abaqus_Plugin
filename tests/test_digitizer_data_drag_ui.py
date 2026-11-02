"""Dragging Data ranges must not refocus, redraw the canvas or resize the grid."""
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
    with tempfile.TemporaryDirectory(prefix='data-drag-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None

        def pump(count=12):
            for _ in range(count):
                view.update()
                time.sleep(.01)

        try:
            view._gui_runtime.show()
            dialog = PlotDigitizerDialog(view)
            dialog.show()
            dialog.engine.apply_image(Image.new('RGB', (400, 300), 'white'), 'drag.png')
            dialog._load_texture(dialog.engine.image)
            dialog.engine.active_dataset.manual_points = [DataPoint(i, i / 2) for i in range(300)]
            dialog._refresh_all()
            dialog._show_tool('data')
            pump(30)
            grid, sheet = dialog.result_grid, dialog.data_worksheet
            sheet.select_range((1, 0), focus=False)
            pump()
            assert QRetainedItem(dialog.point_editor_container).isVisible()
            initial = QRetainedItem(grid.tag).globalGeometry()
            ids = dict(grid.items)
            completed = []
            sheet.selectionFinished.connect(completed.append)
            with patch.object(dialog, '_redraw', wraps=dialog._redraw) as redraw, \
                    patch.object(grid, 'setFocus', wraps=grid.setFocus) as focus:
                with patch.object(sheet, '_hit', return_value=(1, 0)):
                    sheet._press()
                for row in (2, 3, 5, 5, 4, 2, 6):
                    with patch.object(sheet, '_hit', return_value=(row, 1)):
                        for _ in range(4):
                            sheet._drag()
                        pump(3)
                    assert sheet.isDragging()
                    assert sheet.selected_range.bounds == (1, 0, row, 1)
                    assert grid.items == ids, 'Dragging rebuilt native rows'
                    assert QRetainedItem(grid.tag).globalGeometry() == initial, 'Grid moved during drag'
                    assert QRetainedItem(dialog.point_editor_container).isVisible(), 'Editor toggled during drag'
                    assert grid.backend.get_y_scroll(grid.tag) == 0, 'Native focus scrolled the table'
                redraw.assert_not_called()
                focus.assert_not_called()
                with patch.object(sheet, '_hit', return_value=(6, 1)):
                    sheet._release()
                pump()
                assert not sheet.isDragging()
                assert len(completed) == 1
                assert redraw.call_count == 1, redraw.call_count
                assert grid.selectedKeys() == ['manual:{}'.format(i) for i in range(1, 7)]
                assert sheet.selected_range.bounds == (1, 0, 6, 1)
                assert not QRetainedItem(dialog.point_editor_container).isVisible()
            print('PASS Data drag: stable geometry/rows/scroll, no focus or canvas redraw while held; one final refresh')
        finally:
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
