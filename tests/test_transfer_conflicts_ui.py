"""Real serialized overwrite-review dialogs with synthetic metadata (no SSH)."""
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.services.transfer_conflicts import ConflictReview, TransferItemState
from WinUx.view import WinUXView
from DearUIQt.backends import dpg


def review():
    paths = tuple(Path(name) for name in ('newer.inp', 'older.odb', 'folder', 'new.txt'))
    regular, directory = stat.S_IFREG | 0o644, stat.S_IFDIR | 0o755
    left = {str(path): TransferItemState(100, 200, regular) for path in paths}
    right = {str(path): TransferItemState(200, 100, regular) for path in paths}
    right['older.odb'] = TransferItemState(200, 300, regular)
    left['folder'] = TransferItemState(0, 300, directory)
    right['folder'] = TransferItemState(0, 100, directory)
    right['new.txt'] = None
    return ConflictReview(paths, left, right, '/frozen/destination', 'local', 'server', 1)


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        def pump(frames=16):
            for _ in range(frames):
                view.update()
                time.sleep(.005)
        try:
            view._gui_runtime.show()
            data = review()
            for policy, expected in [('newer', ['newer.inp', 'new.txt']),
                                     ('skip', ['new.txt']),
                                     ('replace', [path.name for path in data.sources])]:
                callback, following = Mock(), Mock()
                view.confirm_transfer_conflicts_async(data, callback)
                pump()
                dialog = view._async_confirm_dialog
                assert dialog.isVisible()
                assert dialog.review is data
                assert dialog._default_button is None, 'Enter must not silently overwrite a batch'
                assert len(dialog.decision_buttons) == 3
                assert len(dialog._row_combos) == 3
                assert all(combo.currentText() == 'Skip' for combo in dialog._row_combos.values())
                assert not dpg.get_item_configuration(dialog.table.tag)['scrollX']
                action_column = dpg.get_item_children(dialog.table.tag, 0)[2]
                action_config = dpg.get_item_configuration(action_column)
                assert action_config['width_fixed'] and action_config['no_resize']
                assert dialog.table.columns[2].width == 110
                for index, combo in dialog._row_combos.items():
                    theme = dpg.get_item_theme(dialog.table.items[index])
                    assert theme in ('winux.transfer_conflict.row', dpg.get_alias_id('winux.transfer_conflict.row')), theme
                    children = dpg.get_item_children(dialog.table._row_tags[index], 1)
                    assert len(children) == 3 and children[2] == combo.tag
                    assert dpg.is_item_visible(combo._choice_field.button), 'Action combo must render in its table cell'
                    assert dpg.get_item_rect_size(combo.tag)[0] > 80
                    text = dialog._size_cells[index][0]
                    text_mid = dpg.get_item_rect_min(text)[1] + dpg.get_item_rect_size(text)[1] / 2
                    button = combo._choice_field.button
                    combo_mid = dpg.get_item_rect_min(button)[1] + dpg.get_item_rect_size(button)[1] / 2
                    assert abs(text_mid - combo_mid) <= 2, (text_mid, combo_mid)
                assert not hasattr(dialog, 'set_selected_button'), 'Choices must not need a Save button'
                view.confirm_action_async('Following confirmation', 'Must wait for review teardown', following)
                assert view._async_confirm_dialog is dialog
                dialog._finish(policy)
                dialog._finish(policy)
                pump()
                callback.assert_called_once()
                accepted, decision = callback.call_args.args
                assert accepted
                assert [path.name for path in decision.sources] == expected
                assert decision.review.destination == '/frozen/destination'
                assert view._async_confirm_dialog is not dialog
                view._async_confirm_dialog.reject()
                pump()
                following.assert_called_once_with(False)
            for close in ('escape', 'destroy'):
                callback = Mock()
                view.confirm_transfer_conflicts_async(data, callback)
                pump()
                dialog = view._async_confirm_dialog
                if close == 'escape':
                    dialog.reject()
                else:
                    dialog.destroy()
                pump()
                callback.assert_called_once_with(False, False)
                assert view._async_confirm_active is None
            callback = Mock()
            view.confirm_transfer_conflicts_async(data, callback)
            pump()
            dialog = view._async_confirm_dialog
            dialog._row_combos[1].setCurrentText('Replace')
            assert dialog._overrides['older.odb'] == ('replace', None)
            dialog._row_combos[1].setCurrentText('Skip')
            assert dialog._overrides['older.odb'] == ('skip', None)
            dialog.table.setCurrentKey(0)
            assert dialog._editing_index == 0
            dialog.set_control_value(dialog.item_action, 'Rename file')
            dialog.set_control_value(dialog.item_name, '../outside')
            dialog._finish('custom')
            assert dialog.isVisible() and not callback.called
            dialog.set_control_value(dialog.item_name, 'newer-copy.inp')
            dialog.table.setCurrentKey(1)
            assert dialog._editing_index == 1
            dialog.set_control_value(dialog.item_action, 'Replace')
            dialog.table.setCurrentKey(2)
            dialog.set_control_value(dialog.item_action, 'Rename file')
            dialog.set_control_value(dialog.item_name, 'folder-copy')
            dialog._finish('custom')
            assert dialog.isVisible() and not callback.called, 'Folder rename must require a separate workflow'
            dialog.set_control_value(dialog.item_action, 'Skip')
            dialog._finish('custom')
            pump()
            callback.assert_called_once()
            accepted, decision = callback.call_args.args
            assert accepted
            assert [path.name for path in decision.sources] == ['newer.inp', 'older.odb', 'new.txt']
            assert decision.target_names == {'newer.inp': 'newer-copy.inp'}

            # All conflicts remain editable, with no more than 200 native rows
            # at once. Unreviewed entries default to Skip, not Replace.
            paths = tuple(Path('file{:03d}.inp'.format(i)) for i in range(215))
            states = {str(path): TransferItemState(100, 200, stat.S_IFREG | 0o644) for path in paths}
            many = ConflictReview(paths, states, dict(states), '/dest', 'local', 'server', 1)
            callback = Mock()
            view.confirm_transfer_conflicts_async(many, callback)
            pump()
            dialog = view._async_confirm_dialog
            dialog.table.setCurrentKey(0)
            assert len(dialog.table.rows) == 200
            dialog.set_control_value(dialog.item_action, 'Rename file')
            dialog.set_control_value(dialog.item_name, 'first-copy.inp')
            dialog._change_page(1)
            assert dialog._editing_index == 200 and len(dialog.table.rows) == 15
            dialog.set_control_value(dialog.item_action, 'Replace')
            dialog._change_page(-1)
            assert dialog.control_value(dialog.item_name) == 'first-copy.inp'
            dialog._finish('custom')
            pump()
            decision = callback.call_args.args[1]
            assert decision.sources == (paths[0], paths[200])
            assert decision.target_names == {str(paths[0]): 'first-copy.inp'}
            print('PASS: native batch/per-item conflict review, safe rename validation, retained paged decisions, source timestamps, no unsafe Enter default, serialized modals and single cancellation callbacks')
        finally:
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
