"""Chart preview/layout/formula tools: abaqus python tests/test_reference_chart_preview.py."""
import copy
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.core import Qt
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_reference_tools import ReferenceChartDialog
from WinUx.services.reference_charts import validate_reference, make_formula_reference
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-chart-preview-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            sources = [{'id': 'u3', 'output': 'U3', 'displayName': 'U3',
                        'points': [[0, 1], [1, 3], [2, 2]]}]
            xy = validate_reference({'name': 'XY', 'points': [[0, 0], [1, 4], [2, 1]]})
            formula = make_formula_reference('2*regex(".*U3.*")', 'Formula')
            original = copy.deepcopy([xy, formula])
            dialog = ReferenceChartDialog(view, [xy, formula], lambda result: None,
                                          history_outputs=sources)

            def pump(frames=14):
                for _ in range(frames):
                    view.update()
                    time.sleep(.01)

            try:
                dialog.show()
                pump()
                assert len(dialog._preview_series) == 1, 'Selecting an XY series must show its preview automatically'
                assert dialog._refresh_preview()
                assert dpg.get_value(dialog._preview_series[0].tag)[:2] == [[0, 1, 2], [0, 4, 1]]
                assert dialog._series == original and not dialog._editor_dirty
                pump()
                assert dpg.is_item_visible(dialog._preview_plot.tag)
                library = dialog._saved_list_view.globalGeometry()
                editor = dialog._editor_panel_widget.globalGeometry()
                preview = dialog._preview_frame.globalGeometry()
                assert library.x() + library.width() < editor.x()
                assert editor.x() + editor.width() < preview.x()
                assert library.height() >= 300 and preview.height() >= 400
                dpg.set_axis_limits(dialog._preview_x_axis.tag, 100, 200)
                dpg.set_axis_limits(dialog._preview_y_axis.tag, 100, 200)
                view.update()
                dialog._control_wrappers[dialog.preview_fit_button].click()
                pump()
                x_limits = dpg.get_axis_limits(dialog._preview_x_axis.tag)
                assert x_limits[0] <= 0 and x_limits[1] >= 2, x_limits
                dialog.data_table.paste_text('0\t9\n1\t8')
                assert not dialog._preview_series
                assert dialog._refresh_preview()
                assert dpg.get_value(dialog._preview_series[0].tag)[1][:2] == [9, 8]
                assert xy == original[0], 'Preview mutated library points'
                dialog._editor_dirty = False
                dialog._load_item(formula)
                assert not dialog._preview_series
                dialog.focus_control(dialog.name_edit)
                pump()
                dialog.set_control_value(dialog.formula_edit, 'combine(')
                dialog._formula_changed()
                stale_generation = dialog._formula_check_generation
                pump(50)
                assert 'Syntax error:' in dialog._formula_feedback.text()
                dialog.set_control_value(dialog.formula_edit, '2*regex(".*U3.*")')
                dialog._formula_changed()
                dialog._check_formula_feedback(stale_generation)
                assert 'Syntax error:' in dialog._formula_feedback.text(), 'Stale validation should not overwrite feedback'
                pump(50)
                assert 'Syntax OK' in dialog._formula_feedback.text()
                provider = Mock(return_value=sources)
                dialog._preview_history_provider = provider
                assert dialog._refresh_preview()
                provider.assert_called_once()
                assert dpg.get_value(dialog._preview_series[0].tag)[:2] == [[0, 1, 2], [2, 6, 4]]
                dialog.set_control_value(dialog.formula_edit, 'combine(')
                assert not dialog._refresh_preview() and not dialog._preview_series
                assert dialog._preview_message.text()
                dialog._preview_history_provider = lambda: []
                dialog.set_control_value(dialog.formula_edit, 'regex(".*U3.*")')
                assert not dialog._refresh_preview()
                assert 'No Plot data' in dialog._preview_message.text()
                dialog._filter_formula_functions(value='square')
                assert dialog._formula_functions_view.count() >= 1
                item = dialog._formula_functions_view.currentItem()
                dialog.set_control_value(dialog.formula_edit, '')
                dialog._control_wrappers[dialog.insert_formula_button].click()
                assert dialog.control_value(dialog.formula_edit) == item.data(Qt.UserRole)[1]
                dialog._filter_formula_functions(value='no such operator xyz')
                assert dialog._formula_functions_view.count() == 0
                dialog._insert_selected_function()
                dialog._filter_formula_functions(value='')
                assert dialog._formula_functions_view.count() == len(dialog._formula_function_items)
                large = {'points': [[i, i % 7] for i in range(5001)]}
                assert dialog._render_preview([large])
                rendered = dpg.get_value(dialog._preview_series[0].tag)[0]
                assert len(rendered) <= 2000 and rendered[0] == 0 and rendered[-1] == 5000
                assert len(large['points']) == 5001
                pump()
                assert dpg.get_item_rect_size(dialog.formula_functions)[1] >= 100, {
                    'functions': dpg.get_item_rect_size(dialog.formula_functions),
                    'formula': dpg.get_item_rect_size(dialog.formula_group),
                    'help': dpg.get_item_rect_size(dialog._formula_function_help.tag),
                    'feedback': dpg.get_item_rect_size(dialog._formula_feedback.tag)}
                dialog.set_control_value(dialog.formula_edit, '2*regex(".*U3.*")')
                dialog._preview_history_provider = lambda: sources
                assert dialog._refresh_preview()
                pump()
                if '--screenshot' in sys.argv:
                    from PIL import ImageGrab
                    hwnd = dialog._native_window_backend.winId(dialog.tag)
                    user32 = ctypes.windll.user32
                    user32.GetForegroundWindow.restype = wintypes.HWND
                    thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                    current = ctypes.windll.kernel32.GetCurrentThreadId()
                    attached = user32.AttachThreadInput(current, thread, True)
                    try:
                        user32.SetForegroundWindow(wintypes.HWND(hwnd))
                    finally:
                        if attached:
                            user32.AttachThreadInput(current, thread, False)
                    pump()
                    bounds = wintypes.RECT()
                    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(bounds))
                    ImageGrab.grab(bbox=(bounds.left, bounds.top, bounds.right, bounds.bottom)).save(
                        temp_root / 'reference_chart_preview.png')
                print('PASS: automatic bounded XY preview, Fit, debounced syntax/stale-check guards, '
                      'lazy Formula preview, non-mutating edits, compact layout and searchable Insert palette')
            finally:
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
