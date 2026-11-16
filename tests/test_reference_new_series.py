"""New reference series UI: abaqus python tests/test_reference_new_series.py."""
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

from DearUIQt.backends import dpg
from DearUIQt.gui.placement import item_screen_rect
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_reference_tools import ReferenceChartDialog
from WinUx.services.reference_charts import validate_reference
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-series-new-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            source = validate_reference({'name': 'Original', 'points': [[0, 1], [1, 2]]})
            dialog = ReferenceChartDialog(view, [source], lambda value: None)

            def pump():
                for _ in range(12):
                    view.update()
                    time.sleep(.01)

            def new_series():
                dialog._control_wrappers[dialog.new_series_button].click()
                pump()

            try:
                dialog.show()
                pump()
                labels = [widget.text() for widget in dialog._control_wrappers.values()
                          if callable(getattr(widget, 'text', None))]
                assert 'Save' in labels and 'Save & Close' not in labels
                assert 'Save XY' not in labels and 'Save Formula' not in labels
                assert dpg.is_item_visible(dialog.new_series_button)
                new_rect = item_screen_rect(dpg, dialog.new_series_button)
                delete_rect = item_screen_rect(dpg, dialog.delete_series_button)
                assert new_rect[2] <= delete_rect[0], (new_rect, delete_rect)
                assert dialog._editing_id == source['id']
                new_series()
                draft_id = dialog._editing_id
                assert draft_id and draft_id != source['id'] and not dialog.data_table.has_data()
                assert dialog._selected_name == 'Reference 1' and len(dialog._series) == 2
                assert 'Reference 1' in dialog._series_items
                assert dpg.is_item_visible(dialog._series_selectables['Reference 1'])
                dialog.set_control_value(dialog.name_edit, 'New XY')
                dialog.data_table.paste_text('0\t10\n1\t20')
                assert dialog._commit_editor(refocus=False)
                assert len(dialog._series) == 2 and dialog._series[0] == source
                assert dialog._editing_id == draft_id and not dialog._series[1].get('_draft')
                xy_id = dialog._editing_id
                # Valid dirty edits are committed before opening the next draft.
                dialog.set_control_value(dialog.name_edit, 'Updated XY')
                dialog._editor_dirty = True
                new_series()
                assert dialog._series[1]['id'] == xy_id
                assert dialog._series[1]['name'] == 'Updated XY'
                formula_draft_id = dialog._editing_id
                assert formula_draft_id and len(dialog._series) == 3
                dialog._reference_type_changed(value='Formula')
                assert dialog._editing_id == formula_draft_id and len(dialog._series) == 3
                dialog.set_control_value(dialog.formula_edit, 'regex(".*U3.*")')
                dialog.set_control_value(dialog.name_edit, 'New Formula')
                assert dialog._save_formula_rule(refocus=False)
                assert len(dialog._series) == 3 and dialog._series[-1]['kind'] == 'formula'
                assert dialog._editing_id == formula_draft_id
                # Invalid edits must not be discarded by New.
                formula_id = dialog._editing_id
                dialog.set_control_value(dialog.formula_edit, 'combine(')
                dialog._editor_dirty = True
                new_series()
                assert dialog._editing_id == formula_id
                assert dialog.control_value(dialog.formula_edit) == 'combine('
                assert len(dialog._series) == 3 and dialog._series[0] == source
                dialog._load_item(dialog._series[0])
                new_series()
                first_blank = dialog._editing_id
                first_name = dialog._selected_name
                new_series()
                assert len(dialog._series) == 5
                assert dialog._editing_id != first_blank and dialog._selected_name != first_name
                assert first_name in dialog._series_items
                assert dialog._selected_name in dialog._series_items
                # Empty placeholders remain editable, never silently persisted.
                dialog._save()
                assert not dialog._finished
                dialog._remove_selected()
                pump()
                assert len(dialog._series) == 4
                # The single footer Save commits the current editor as well
                # as the library, for both XY and Formula modes.
                dialog._series = dialog._series[:3]
                dialog._load_item(dialog._series[1])
                dialog.data_table.paste_text('0\t100\n1\t200')
                with patch.object(dialog, 'finish') as finish:
                    dialog._save()
                    finish.assert_called_once()
                    saved = finish.call_args[0][0]
                    assert saved[1]['points'] == [[0.0, 100.0], [1.0, 200.0]]
                dialog._load_item(dialog._series[2])
                dialog.set_control_value(dialog.formula_edit, '2*regex(".*U3.*")')
                dialog._editor_dirty = True
                with patch.object(dialog, 'finish') as finish:
                    dialog._save()
                    finish.assert_called_once()
                    assert finish.call_args[0][0][2]['formula'] == '2*regex(".*U3.*")'
                print('PASS: visible New button, non-overlapping header, new XY/Formula series, '
                      'immediate selected list entries, repeat creation/deletion, '
                      'single Save for XY/Formula and dirty/invalid edit protection')
            finally:
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
