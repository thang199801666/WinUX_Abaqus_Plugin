"""Retained Formula editing across frames: abaqus python tests/test_reference_formula_editing.py."""
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
from DearUIQt.core import Qt
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_reference_tools import ReferenceChartDialog
from WinUx.services.reference_charts import make_formula_reference
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-formula-edit-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            source = make_formula_reference('regex(".*U3.*")', 'Formula')
            results = []
            dialog = ReferenceChartDialog(view, [source], results.append)

            def pump(frames=8):
                for _ in range(frames):
                    view.update()
                    time.sleep(.015)

            def edit(text):
                dialog.focus_control(dialog.name_edit)
                pump(3)
                dialog.set_control_value(dialog.formula_edit, text)
                pump(3)
                assert dialog.control_value(dialog.formula_edit) == text

            def insert(name, frames=8):
                item = next(item for item in dialog._formula_function_items
                            if item.data(Qt.UserRole)[0] == name)
                dialog._formula_functions_view.setCurrentItem(item)
                dialog.control_wrapper(dialog.insert_formula_button).click()
                pump(frames)

            try:
                dialog.show()
                pump(24)
                edit('')
                insert('combine')
                assert dialog.control_value(dialog.formula_edit) == 'combine(regex(".*U3.*"), regex(".*RF3.*"))'
                edit('combine(')
                insert('regex')
                assert dialog.control_value(dialog.formula_edit) == 'combine(regex("pattern")'
                edit('combine(regex(".*U3.*"),')
                insert('minus')
                insert('regex')
                assert dialog.control_value(dialog.formula_edit) == 'combine(regex(".*U3.*"), - regex("pattern")', repr(dialog.control_value(dialog.formula_edit))
                insert('plus', frames=0)
                insert('regex')
                assert dialog.control_value(dialog.formula_edit) == 'combine(regex(".*U3.*"), - regex("pattern") + regex("pattern")'
                insert('plus', frames=0)
                dialog._load_item(source)
                pump(12)
                assert dialog.control_value(dialog.formula_edit) == source['formula'], 'Stale insertion changed a newly loaded series'
                assert not dialog._editor_dirty, 'Loading a series must not create a dirty edit'
                expected = 'combine(regex(".*U3.*"), -regex(".*RF3.*"))'
                edit(expected)
                dialog._editor_dirty = True
                dialog._save()
                assert results[-1][0]['formula'] == expected
                assert source['formula'] == 'regex(".*U3.*")'
                print('PASS: Formula Insert persists across frames/focus changes, rapid clicks compose, '
                      'series switching cancels stale inserts and Save preserves the source')
            finally:
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
