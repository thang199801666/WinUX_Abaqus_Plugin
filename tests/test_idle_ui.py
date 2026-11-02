"""Real native idle wait: timers and worker wake without continuous frames."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.view import WinUXView
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-idle-test-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            try:
                view._gui_runtime.show()
                for _ in range(35):
                    view.update()
                view._frame_clock.last_input = float('-inf')
                view._frame_clock.last_work = float('-inf')
                view._frame_clock.presented()
                delivered = []
                start = time.monotonic()
                view.after(40, lambda: delivered.append(time.monotonic() - start))
                while not delivered and time.monotonic() - start < .3:
                    view._wait_for_ui_frame()
                assert delivered and delivered[0] < .2, delivered
                timer_elapsed = delivered[0]

                delivered.clear()
                view._frame_clock.last_input = float('-inf')
                view._frame_clock.presented()
                start = time.monotonic()
                def worker():
                    time.sleep(.05)
                    view.after(0, lambda: delivered.append(threading.get_ident()))
                thread = threading.Thread(target=worker)
                thread.start()
                while not delivered and time.monotonic() - start < .4:
                    view._wait_for_ui_frame()
                thread.join()
                elapsed = time.monotonic() - start
                assert delivered == [threading.get_ident()], delivered
                assert elapsed < .3, elapsed
                print('PASS: idle timer delivered in {:.3f}s; worker woke GUI in {:.3f}s'.format(
                    timer_elapsed, elapsed), flush=True)
            finally:
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
