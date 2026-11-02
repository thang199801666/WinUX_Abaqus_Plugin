"""Real asynchronous recursive-review UI, using disk-backed fake SFTP (no SSH)."""
import os
from pathlib import Path
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
from test_recursive_transfer import Model, make_review
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.controllers.transfer import TransferController
from WinUx.services.transfer_tree import TreeReview, TreeDecision
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        base = Path(temporary)
        source, remote, profile = base / 'project', base / 'remote', base / 'profile'
        source.mkdir()
        remote.mkdir()
        for child in ('one', 'two'):
            (source / child).mkdir()
            (source / child / 'result.odb').write_bytes(b'NEW')
            (remote / 'dest' / 'project' / child).mkdir(parents=True)
            (remote / 'dest' / 'project' / child / 'result.odb').write_bytes(b'OLD')
        with patch.dict(os.environ, {'APPDATA': str(profile)}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            model, workers = Model(remote), []
            app = SimpleNamespace(view=view, server=model, _closing=False, _connection_generation=1)
            def submit(name, worker):
                thread = threading.Thread(target=worker, daemon=True)
                workers.append(thread)
                thread.start()
                return SimpleNamespace(state='queued')
            app._submit_background = submit
            controller = TransferController(app)
            original = make_review(model, [source], '/dest')
            def pump(count=8):
                for _ in range(count):
                    view.update()
                    time.sleep(.005)
            def wait_until(predicate):
                deadline = time.monotonic() + 10
                while not predicate() and time.monotonic() < deadline:
                    pump(2)
                assert predicate(), 'Asynchronous recursive review did not finish'
            gate = threading.Event()
            try:
                view._gui_runtime.show()
                callback = Mock()
                view.confirm_transfer_conflicts_async(original, callback,
                    on_review_contents=lambda dialog: controller._review_contents(original, dialog, lambda: True))
                pump(18)
                dialog = view._async_confirm_dialog
                dialog._start_contents()
                wait_until(lambda: isinstance(dialog.review, TreeReview))
                assert not dialog._scanning and not callback.called
                assert [values[0] for _, values in dialog.table.rows] == [
                    'project/one/result.odb', 'project/two/result.odb']
                dialog.table.setCurrentKey(0)
                dialog.set_control_value(dialog.item_action, 'Replace')
                dialog.table.setCurrentKey(1)  # Store first choice; second defaults to Skip.
                dialog._finish('custom')
                pump(12)
                decision = callback.call_args.args[1]
                assert isinstance(decision, TreeDecision)
                assert [decision.review.display_name(path) for path in decision.sources] == ['project/one/result.odb']
                assert (remote / 'dest' / 'project' / 'one' / 'result.odb').read_bytes() == b'OLD'

                # Tree progress uses complete relative paths, not ambiguous leaf names.
                all_files = decision.review.choose('replace')
                center = view._get_transfer_center()
                task = center.add_task('Upload', threading.Event(),
                    controller._progress_names(all_files.sources, all_files))
                pump(12)
                assert [row.name for row in task.rows] == ['project/one/result.odb', 'project/two/result.odb']
                center.remove_task(task)
                center._hide_if_idle()
                pump(4)

                # Hold one server listing in flight, then cancel the native
                # dialog. A late worker result must not resurrect it or copy.
                entered = threading.Event()
                listing = model.sftp.listdir_iter
                def delayed(folder, read_aheads=1):
                    entered.set()
                    gate.wait(5)
                    yield from listing(folder, read_aheads)
                model.sftp.listdir_iter = delayed
                callback = Mock()
                view.confirm_transfer_conflicts_async(original, callback,
                    on_review_contents=lambda dialog: controller._review_contents(original, dialog, lambda: True))
                pump(14)
                dialog = view._async_confirm_dialog
                dialog._start_contents()
                wait_until(entered.is_set)
                assert dialog._scanning
                dialog._finish('replace')
                callback.assert_not_called()
                dialog.reject()
                gate.set()
                wait_until(lambda: not any(thread.is_alive() for thread in workers))
                pump(12)
                callback.assert_called_once_with(False, False)
                assert view._async_confirm_dialog is None
                assert model.open_sessions == 0
                assert (remote / 'dest' / 'project' / 'one' / 'result.odb').read_bytes() == b'OLD'
                print('PASS: asynchronous folder review, relative child paths, individual choices, unique progress rows, Cancel during scan, no late resurrection, scan-channel cleanup and no preview writes')
            finally:
                gate.set()
                app._closing = True
                for thread in workers:
                    thread.join(6)
                view.request_shutdown()
                view._destroy_components()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
