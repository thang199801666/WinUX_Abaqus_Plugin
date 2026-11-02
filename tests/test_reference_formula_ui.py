"""Real formula palette/save path: abaqus python tests/test_reference_formula_ui.py.

Includes a physical palette double-click; does not send keyboard input.
"""
import ctypes
import faulthandler
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.core import Qt
from DearUIQt.backends import dpg
from DearUIQt.gui.placement import item_screen_rect
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_reference_tools import ReferenceChartDialog
from WinUx.services.reference_charts import make_formula_reference, evaluate_reference_formula, resolve_reference_formula_ids
from WinUx.view import WinUXView


def main():
    faulthandler.enable()
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-formula-ui-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            source = make_formula_reference('combine(.*U3.*, .*RF3.*)', 'Existing')
            results = []
            dialog = ReferenceChartDialog(view, [source], results.append)
            dialog.show()
            owner = wintypes.HWND(view._find_main_viewport_hwnd())

            def pump(frames=12):
                for _ in range(frames):
                    view.update()
                    assert ctypes.windll.user32.IsWindowVisible(owner), 'Formula editor hid main window'
                    time.sleep(.01)

            try:
                pump()
                assert dialog._formula_mode
                assert not dialog._formula_builder_open
                assert dpg.is_item_shown(dialog._formula_functions_view.tag)
                assert not dpg.is_item_shown(dialog._formula_builder_widget.tag)
                editor_width, editor_height = dpg.get_item_rect_size(dialog.formula_edit)
                assert editor_width > dpg.get_item_rect_size(dialog.saved_list)[0]
                assert 70 <= editor_height <= 105
                assert 'regex(' in dialog.control_value(dialog.formula_edit)
                assert source['formula'] == 'combine(.*U3.*, .*RF3.*)'
                assert dpg.is_item_shown(dialog.formula_functions)
                assert dpg.get_item_rect_size(dialog.formula_functions)[1] >= 100
                examples_bottom = dpg.get_item_pos(dialog.formula_functions)[1] + dpg.get_item_rect_size(dialog.formula_functions)[1]
                assert examples_bottom <= dpg.get_item_rect_size(dialog.formula_group)[1] + 2
                labels = [item.text() for item in dialog._formula_function_items]
                assert 'combine(X, Y)' in labels and 'sin(A)' in labels and 'cos(A)' in labels
                assert 'A ** B' in labels and 'regex("pattern")' in labels
                original_text = dialog.control_value(dialog.formula_edit)
                entry = next(item for item in dialog._formula_function_items if item.data(Qt.UserRole)[0] == 'regex')
                native = dialog._formula_functions_view.items[entry.key]
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
                pump(3)
                assert int(user32.GetForegroundWindow() or 0) == hwnd, (
                    'Formula dialog did not take foreground', hwnd,
                    int(user32.GetForegroundWindow() or 0))
                left, top, right, bottom = item_screen_rect(dpg, native)
                user32.SetCursorPos(int((left + right) / 2), int((top + bottom) / 2))
                pump(2)
                for _ in range(2):
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                    pump(1)
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                    pump(3)
                pump(3)
                assert dialog.control_value(dialog.formula_edit) == original_text + 'regex("pattern")', (
                    dialog.control_value(dialog.formula_edit), original_text,
                    dialog._formula_functions_view.currentItem().text() if dialog._formula_functions_view.currentItem() else None)

                def edit_formula(text):
                    dialog.focus_control(dialog.name_edit)
                    pump(2)
                    dialog.set_control_value(dialog.formula_edit, text)

                def use_function(name):
                    dialog.focus_control(dialog.name_edit)
                    pump(2)
                    entry = next(item for item in dialog._formula_function_items if item.data(Qt.UserRole)[0] == name)
                    dialog._formula_functions_view.itemDoubleClicked.emit(entry)
                    pump(2)

                edit_formula('')
                use_function('combine')
                assert dialog.control_value(dialog.formula_edit) == 'combine(regex(".*U3.*"), regex(".*RF3.*"))', dialog.control_value(dialog.formula_edit)
                edit_formula('combine(')
                use_function('regex')
                assert dialog.control_value(dialog.formula_edit) == 'combine(regex("pattern")'
                edit_formula('combine(regex(".*U3.*"),')
                use_function('minus')
                assert dialog.control_value(dialog.formula_edit) == 'combine(regex(".*U3.*"), - '
                use_function('regex')
                assert dialog.control_value(dialog.formula_edit) == 'combine(regex(".*U3.*"), - regex("pattern")'
                expected = 'combine(regex(".*U3.*"), -regex(".*RF3.*"))'
                edit_formula(expected)
                assert dialog._save_series()
                assert len(dialog._series) == 1 and dialog._series[0]['id'] == source['id']
                assert dialog._series[0]['formula'] == expected
                assert source['formula'] == 'combine(.*U3.*, .*RF3.*)', 'Draft changed the source rule'
                dialog._save()
                pump()
                saved = results[-1][0]
                assert saved['formula'] == expected
                history = [{'name': 'U3', 'points': [[0, 2], [1, 4]]},
                           {'name': 'RF3', 'points': [[0, 30], [1, 50]]}]
                assert evaluate_reference_formula(saved['formula'], history)[0]['points'] == [[2, -30], [4, -50]]
                # Exercise the generator controls against the exact label style
                # shown by Abaqus, without requiring live point downloads.
                history = []
                for axis in (1, 2, 3):
                    for component, title in (('U', 'Spatial displacement'), ('RF', 'Reaction force')):
                        history.append({
                            'id': '{}{}'.format(component, axis), 'step': 'Load',
                            'historyRegion': 'Node ASSEMBLY.1',
                            'output': '{}{}_ANTIALIASING'.format(component, axis),
                            'displayName': '{} (FILTERED): {}{}_ANTIALIASING PI: rootAssembly Node 1 in NSET POINTLOAD'.format(title, component, axis),
                        })
                dialog.begin_session([], results.append, history_outputs=history)
                dialog.show()
                assert dialog._open_formula_dialog()
                pump()
                dialog.control_wrapper(dialog.formula_builder_button).click()
                pump(2)
                assert dialog._formula_builder_open
                assert dpg.is_item_shown(dialog.formula_functions)
                assert dpg.get_item_rect_size(dialog.formula_functions)[1] >= 100
                assert dpg.is_item_shown(dialog._formula_builder_widget.tag)

                def generate():
                    # A real Generate click leaves InputText first; preserving
                    # active text while changing it programmatically is not the
                    # native button interaction being tested here.
                    dialog.focus_control(dialog.generate_formula_button)
                    pump(3)
                    assert dialog.control_wrapper(dialog.generate_formula_button).click()
                    pump(4)

                generate()
                assert len(dialog._series) == 1 and 'U3' in dialog._series[0]['formula']
                assert set(resolve_reference_formula_ids(dialog._series[0]['formula'], history)) == {'U3', 'RF3'}
                generate()
                assert len(dialog._series) == 1, (
                    'Repeated Generate added duplicate rules', [(item['name'], item['formula']) for item in dialog._series])
                dialog.set_control_value(dialog.generate_direction, 'All directions')
                generate()
                assert len(dialog._series) == 3
                dialog.set_control_value(dialog.generate_reverse_rf, False)
                dialog.set_control_value(dialog.generate_direction, 'U3 / RF3')
                generate()
                assert len(dialog._series) == 4 and 'combine(regex(' in dialog._series[-1]['formula']
                dialog._save()
                pump()
                assert len(results[-1]) == 4, 'Generated formulas did not persist through Save & Close'
                assert source['formula'] == 'combine(.*U3.*, .*RF3.*)'
                committed = results[-1]
                committed_formulas = [item['formula'] for item in committed]
                dialog.begin_session(committed, results.append, history_outputs=history)
                dialog.show()
                pump(4)
                dialog.set_control_value(dialog.generate_direction, 'U1 / RF1')
                generate()  # Positive RF1 is a new rule; committed RF1 is negative.
                assert len(dialog._series) == 5
                dialog.finish(None)
                assert results[-1] is None
                assert [item['formula'] for item in committed] == committed_formulas, 'Cancel changed saved rules'
                print('PASS: physical palette double-click appends, function/operator fragments, existing rule update, Save Formula, '
                      'U/RF generator controls/deduplication and Save & Close', flush=True)
            finally:
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
