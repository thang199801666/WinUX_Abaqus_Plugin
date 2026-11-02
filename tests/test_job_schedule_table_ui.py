"""Job Schedule centered headers survive updates, resizing and row commands."""
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
from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.job_schedule_form import JobScheduleDialog
from WinUx.dialogs.job_manager_form import JobManagerDialog
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None
        rows = []
        command = Mock()
        def pump():
            for _ in range(10):
                view.update()
                time.sleep(.005)
        try:
            view._gui_runtime.show()
            dialog = JobScheduleDialog(view, lambda blocking=False: list(rows), command)
            dialog.show()
            pump()
            header = dialog._header_row
            labels = list(dialog._header_cells)
            assert len(labels) == 6
            assert [dpg.get_item_configuration(item)['label'] for item in labels] == [c[0] for c in dialog._columns]
            assert all(not dpg.get_item_configuration(item)['enabled'] for item in labels)
            assert not dpg.get_item_configuration(dialog.table)['header_row']
            assert dpg.get_item_configuration(dialog.table)['freeze_rows'] == 1
            rows[:] = [('Sample job', 'Submit', '2026-10-27 14:00', '5 min', 'Waiting', 'submit', 'job-1'),
                       ('Completed job', 'Cancel', '2026-10-27 13:00', '-', 'Completed', 'cancel', 'job-2')]
            dialog.refresh()
            pump()
            assert dialog.table_widget.rowCount() == 2
            first_row = dialog.table_widget.nativeRow(0)
            dialog.set_rows(rows)
            assert dialog.table_widget.nativeRow(0) == first_row
            assert dpg.does_item_exist(header)
            for width in (940, 760):
                dialog.resize(width, 350)
                pump()
                assert all(dpg.get_item_rect_size(item)[0] > 40 for item in labels)
            dialog.request_action('edit', 'submit', 'job-1')
            pump()
            command.assert_called_once_with('edit', 'submit', 'job-1')
            rows.clear()
            dialog.refresh()
            pump()
            assert dialog.table_widget.rowCount() == 0
            assert dialog._header_cells == labels and dpg.does_item_exist(header)
            print('PASS: six centered noninteractive headers, frozen row, stable updates, resize, commands and empty-state retention')
            dialog.destroy()
            pump()
            paths = [Path(profile) / 'one.inp', Path(profile) / 'two.inp']
            run = Mock()
            dialog = JobManagerDialog(view, paths, run, Mock())
            dialog.show()
            pump()
            labels = list(dialog._header_cells)
            assert len(labels) == 8
            assert [dpg.get_item_configuration(item)['label'] for item in labels] == [
                'Run', 'Input file', 'Version', 'CPUs', 'Precision', 'Overwrite', 'Schedule', 'Time']
            assert all(not dpg.get_item_configuration(item)['enabled'] for item in labels)
            assert dialog.table_widget.rowCount() == 2
            assert not dpg.get_item_configuration(dialog.table)['borders_innerV']
            assert dpg.get_item_configuration(dialog.table)['freeze_rows'] == 1
            for width in (1100, 1010):
                dialog.resize(width, 340)
                pump()
                assert all(dpg.get_item_rect_size(item)[0] > 15 for item in labels)
            first, second = (dialog.rows_by_path[path] for path in paths)
            dialog.set_control_value(first['run'], False)
            dialog.set_control_value(second['cpus'], 6)
            dialog.set_control_value(second['precision'], 'double')
            dialog._run()
            pump()
            run.assert_called_once()
            jobs = run.call_args.args[1]
            assert len(jobs) == 1 and jobs[0]['path'] == paths[1]
            assert jobs[0]['cpus'] == 6 and jobs[0]['precision'] == 'double'
            print('PASS: matching eight-column Job Manager header, editable controls, resize and unchanged selected-job submission')
        finally:
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
