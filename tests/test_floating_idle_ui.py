"""Real floating-host idle CPU and hidden timer/worker wake regression."""
import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--unpaced', action='store_true')
    parser.add_argument('--seconds', type=float, default=3)
    args = parser.parse_args()
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-floating-idle-', dir=root) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        runtime = FloatingDialogRuntime(Mock(), iter(()), {
            'kind': 'blocking', 'title': 'Idle floating test', 'visible': True,
            'payload': {'title': 'Idle floating test', 'message': 'Timer and worker wake test'},
        })
        runtime.gui.createContext(manual_callbacks=True)
        # This test owns both ends of the presentation acknowledgement.
        runtime._publish_requested = runtime._commit_requested = True
        try:
            runtime._build()
            runtime.view._frame_clock.last_input = float('-inf')
            runtime.view._frame_clock.last_work = float('-inf')
            runtime.view._frame_clock.presented()
            frames = 0
            start, cpu = time.perf_counter(), time.process_time()
            while time.perf_counter() - start < args.seconds:
                if args.unpaced:
                    runtime._drain_form_callbacks()
                    runtime.view.drain()
                else:
                    assert runtime._wait_for_frame()
                runtime.gui.renderFrame()
                runtime.view._frame_clock.presented()
                runtime.view.mark_presented()
                frames += 1
            elapsed = time.perf_counter() - start
            used = time.process_time() - cpu
            print('FLOATING {} wall={:.3f}s cpu={:.3f}s one_core={:.2f}% frames={}'.format(
                'unpaced' if args.unpaced else 'paced', elapsed, used, used / elapsed * 100, frames), flush=True)

            runtime.hide()
            delivered = []
            start = time.monotonic()
            runtime.view.after(40, lambda: delivered.append(time.monotonic() - start))
            with patch.object(runtime.form, 'winfo_exists', side_effect=lambda: not delivered):
                assert not runtime._wait_for_frame()
            assert delivered[0] < .2, delivered

            delivered.clear()
            start = time.monotonic()
            def worker():
                time.sleep(.05)
                runtime.view.after(0, lambda: delivered.append(threading.get_ident()))
            thread = threading.Thread(target=worker)
            thread.start()
            with patch.object(runtime.form, 'winfo_exists', side_effect=lambda: not delivered):
                assert not runtime._wait_for_frame()
            thread.join()
            assert delivered == [threading.get_ident()], delivered
            assert time.monotonic() - start < .3
            runtime.show()
            assert runtime.native.visible
            assert runtime._wait_for_frame()
            runtime.gui.renderFrame()
            print('PASS: real floating presentation, hidden timer, worker wake and reactivation', flush=True)
        finally:
            runtime.view._dispatcher.close()
            if runtime.native:
                runtime.native.set_visible(False)
                runtime.native.restore_close_handler()
                runtime.native.close_activation_guard()
            runtime.gui.destroy()


if __name__ == '__main__':
    main()
