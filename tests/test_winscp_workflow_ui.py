"""Real masks, stable selection/scroll, saved headers and Retry/Skip UI."""
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from WinUx.models.items import FileItem
from WinUx.preferences.navigation import NavigationPreferences
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.controllers.transfer import TransferController
from WinUx.dialogs.inprocess.transfer_center import TransferCenterDialog
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        center = None
        def pump(count=12):
            for _ in range(count):
                view.update()
                time.sleep(.01)
        try:
            view._gui_runtime.show()
            pump()
            for panel in view.panels:
                folder = PurePosixPath('/workflow') if panel.panel_id == 'server' else Path(profile)
                sources = [FileItem('job{:03d}.{}'.format(i, 'inp' if i % 2 else 'odb'),
                                    folder / 'job{:03d}.{}'.format(i, 'inp' if i % 2 else 'odb'), False, i + 1, 100)
                           for i in range(200)]
                sources.append(FileItem('backup.bak', folder / 'backup.bak', False, 1, 100))
                panel.display(folder, sources)
                pump()
                listing = panel.listview
                index = next(i for i, row in enumerate(listing.items) if row.name == 'job025.inp')
                listing.select_indices([index])
                dpg.set_y_scroll(listing.body_window, 100)
                pump()
                assert panel.status.get().endswith('201 items')
                assert panel.selected_status.get() == '1 selected'
                panel.apply_filter('*.inp;*.odb|*.bak')
                pump()
                assert len(listing.items) == 200
                assert panel.status.get().endswith('200 of 201 items')
                assert panel.selected_status.get() == '1 selected'
                assert [row.name for row in listing.get_selected()] == ['job025.inp']
                assert dpg.get_y_scroll(listing.body_window) > 0
                panel.apply_filter('')
                pump()
                assert len(listing.items) == 201
                assert panel.status.get().endswith('201 items')
                assert [row.name for row in listing.get_selected()] == ['job025.inp']
                # A pending typed query must not return after Close/Clear.
                panel.toolbar._on_search_text('*.inp')
                panel.toolbar.clear_search(apply=True)
                pump(20)
                assert len(listing.items) == 201
                panel.toolbar._on_search_text('*.odb')
                pump(20)
                assert len(listing.items) == 100
                assert panel.status.get().endswith('100 of 201 items')
                assert panel.selected_status.get() == '0 selected'
                assert all(row.name.endswith('.odb') for row in listing.items)
                panel.toolbar.clear_search(apply=True)
                listing.set_auto_width(False)
                listing.set_column_visible('owner', True)
                listing.set_column_width('owner', 143)
                state = NavigationPreferences().load_columns(panel.panel_id)
                assert state['auto_width'] is False
                assert next(c for c in state['columns'] if c['key'] == 'owner')['width'] == 143
                callback, listing.on_columns_change = listing.on_columns_change, None
                listing.reset_columns()
                assert listing.restore_column_state(state)
                listing.on_columns_change = callback
                assert listing.get_column('owner')['visible']
                assert listing._column_widths['owner'] == 143
                listing._on_header_menu_triggered('reset-columns')
                pump()
                assert len(listing._visible_columns()) == 4

            center = TransferCenterDialog(view)
            task = center.add_task('Upload', threading.Event(), ['one.inp', 'two.odb'])
            retry = Mock()
            task.set_retry(retry)
            task.fail('Simulated connection failure; no file I/O')
            pump(24)
            action = center.row_widgets[task.rows[0].row_id]['action']
            assert dpg.get_item_configuration(action)['label'] == 'Retry'
            center._handle_row_action(task.rows[0].row_id)
            center._handle_row_action(task.rows[1].row_id)
            retry.assert_called_once_with(task)
            task.retry_ready()
            pump()
            assert dpg.get_item_configuration(action)['enabled']
            center.clear_finished()
            pump()
            controller = TransferController(SimpleNamespace(view=view))
            decision = Mock()
            controller._confirm_conflicts(['existing.inp'], decision)
            pump(24)
            confirmation = view._async_confirm_dialog
            assert confirmation.option_checkbox is not None
            confirmation.set_control_value(confirmation.option_checkbox, True)
            confirmation.accept()
            pump(12)
            decision.assert_called_once_with(True, True)
            print('PASS: real masks/debounce, preserved selection/scroll, independent saved columns, Reset Columns, Retry and Skip confirmation')
        finally:
            if center is not None:
                center.destroy()
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
