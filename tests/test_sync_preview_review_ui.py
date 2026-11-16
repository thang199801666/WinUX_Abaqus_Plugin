"""Real Sync Preview rows/status and review-only transfer gating, fixture data."""
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.controllers.sync_preview import SyncPreviewController
from WinUx.dialogs.sync_preview_form import SyncPreviewDialog
from WinUx.models.items import FileItem
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=temp) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None
        def pump(count=15):
            for _ in range(count):
                view.update()
                time.sleep(.01)
        try:
            view._gui_runtime.show()
            app = SimpleNamespace(view=view, server=SimpleNamespace(normalize=PurePosixPath),
                                  _ensure_server_online=Mock(return_value=True), _process_queued_drop=Mock())
            controller = SyncPreviewController(app)
            def item(name, **kwargs):
                return FileItem(name, Path(profile) / name, kwargs.pop('is_dir', False), 42, 100, **kwargs)
            rows = controller.build_rows(
                [item('upload.inp'), item('conflict'), item('folder', is_dir=True), item('link', is_symlink=True)],
                [item('conflict', is_dir=True)], Path(profile), PurePosixPath('/remote'))
            dialog = SyncPreviewDialog(view, rows, profile, '/remote', lambda: None, controller.transfer_rows)
            view.sync_preview_dialog = dialog
            dialog.show()
            pump()
            displayed = {values[0]: values for _, values in dialog.table.rows}
            assert displayed['conflict'][1] == 'File/folder conflict'
            assert displayed['conflict'][3] == 'Folder'
            assert displayed['folder'][1] == 'Directory not compared'
            assert displayed['link'][2] == 'Link'
            assert dpg.get_value(dialog.status) == '4 result(s) | 1 recommended transfer(s) | 3 review/not compared'
            review_key = next(index for index, row in enumerate(rows) if row['name'] == 'conflict')
            dialog.table.setCurrentKey(review_key)
            dialog._transfer_selected()
            pump()
            app._process_queued_drop.assert_not_called()
            app._ensure_server_online.assert_not_called()
            assert 'require review' in dpg.get_value(dialog.status)
            upload_key = next(index for index, row in enumerate(rows) if row['name'] == 'upload.inp')
            dialog.table.setCurrentKey(upload_key)
            dialog._transfer_selected()
            pump()
            app._process_queued_drop.assert_called_once()
            assert app._process_queued_drop.call_args.args[-1] == [Path(profile) / 'upload.inp']
            dialog.refresh(list(reversed(rows)), profile, '/remote')
            assert not dialog.table.selected
            dialog.begin_scan(profile, '/remote')
            dialog._transfer_selected()
            pump()
            assert app._process_queued_drop.call_count == 1
            assert 'Wait for the current scan' in dpg.get_value(dialog.status)
            print('PASS: real Sync Preview conflict/folder/link rows, counts, review-only gating, regular upload routing and scan/selection guards')
        finally:
            if dialog is not None:
                dialog.destroy()
                view.sync_preview_dialog = None
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
