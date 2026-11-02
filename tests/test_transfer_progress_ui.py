"""Real per-frame progress commits without network I/O or physical input."""
from collections import deque
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.runtime.transfer_progress import TransferProgressDelivery
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        queued = deque()
        def after(delay, callback, *args):
            queued.append((callback, args))
        def drain():
            while queued:
                callback, args = queued.popleft()
                callback(*args)
        def pump(count=8):
            for _ in range(count):
                view.update()
                time.sleep(.005)
        try:
            view._gui_runtime.show()
            center = view._get_transfer_center()
            task = center.add_task('Upload', threading.Event(), ['large.odb'])
            center.show()
            pump(18)
            delivery = TransferProgressDelivery(after, task.update_progress)
            task.set_progress_delivery(delivery)
            def produce():
                for i in range(10001):
                    delivery.progress('large.odb', i, 20000, i, 20000)
            worker = threading.Thread(target=produce)
            worker.start()
            worker.join()
            assert len(queued) == 1
            row = center.row_widgets[task.rows[0].row_id]
            assert center._progress_font is not None
            assert dpg.get_item_font(row['percentage']) == center._progress_font.nativeId()
            def assert_centered():
                pump(3)
                config = dpg.get_item_configuration(row['percentage'])
                assert config['width'] == -1 and config['height'] == center.PROGRESS_HEIGHT
                assert tuple(dpg.get_item_pos(row['percentage'])) == (0, 0)
                assert not config['enabled'], 'Percentage overlay must not be interactive'
                theme = dpg.get_item_theme(row['percentage'])
                assert theme in ('winux.transfer.percentage.overlay',
                                 dpg.get_alias_id('winux.transfer.percentage.overlay'))
            assert_centered()
            # Deliberately do not drain worker/UI callbacks. The pre-render
            # data path must commit the latest actual byte count in this frame.
            view._gui_runtime.renderFrame()
            assert dpg.get_value(row['progress']) == .5
            assert dpg.get_item_configuration(row['percentage'])['label'] == '50.0%'
            delivery.finish(task.complete)
            view._gui_runtime.renderFrame()
            assert task.state == 'running', 'Terminal callback ran inside renderer submission'
            assert dpg.get_value(row['progress']) == .5, 'Progress invented unreceived bytes'
            drain()
            view._gui_runtime.renderFrame()
            assert task.state == 'completed'
            assert dpg.get_value(row['progress']) == 1
            center.clear_finished()
            pump()

            task = center.add_task('Download', threading.Event(), ['a.inp', 'b.odb', 'c.log'])
            pump(14)
            delivery = TransferProgressDelivery(after, task.update_progress)
            task.set_progress_delivery(delivery)
            delivery.progress('a.inp', 100, 100, 100, 300)
            delivery.progress('b.odb', 30, 100, 130, 300)
            delivery.finish(task.fail, 'Simulated network failure')
            view._gui_runtime.renderFrame()
            assert [row.state for row in task.rows] == ['completed', 'running', 'queued']
            drain()
            pump(5)
            assert [row.state for row in task.rows] == ['completed', 'failed', 'skipped']
            assert center.isVisible()
            center.hide()
            assert center._progress_render_token is None
            center.show()
            pump(4)
            assert center._progress_render_token is not None
            center.clear_finished()
            pump()
            assert not center.isVisible()
            assert center._progress_render_token is None
            print('PASS: real latest-byte progress in same submitted frame, 10001 samples/one wake, no fabricated bytes, terminal outside render, exact failure row and hook cleanup')
        finally:
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
