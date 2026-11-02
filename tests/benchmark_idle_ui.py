"""Isolated idle UI benchmark; reports one-core CPU, not Task Manager %."""
import argparse
import cProfile
import os
import pstats
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.ui.components.explorer_list_view import ListViewItem
from WinUx.view import WinUXView


def memory_snapshot(view):
    """Current-process Windows memory, including native renderer allocations."""
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    current = ctypes.windll.kernel32.GetCurrentProcess
    current.restype = wintypes.HANDLE
    measure = ctypes.windll.psapi.GetProcessMemoryInfo
    measure.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    measure.restype = wintypes.BOOL
    if measure(current(), ctypes.byref(counters), counters.cb):
        print('MEMORY private={:.2f}MiB working_set={:.2f}MiB native_items={}'.format(
            counters.PrivateUsage / 2**20, counters.WorkingSetSize / 2**20,
            view._gui_runtime.itemCount()), flush=True)


def main():
    args_parser = argparse.ArgumentParser()
    args_parser.add_argument('--seconds', type=float, default=5)
    args_parser.add_argument('--paced', action='store_true')
    args_parser.add_argument('--profile', action='store_true')
    args_parser.add_argument('--controller', action='store_true',
                             help='Include real disconnected controller, local watcher and scheduler')
    args_parser.add_argument('--timer-ms', type=float, default=0,
                             help='Exercise a recurring passive GUI timer')
    args = args_parser.parse_args()
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-idle-benchmark-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile, 'WINUX_STANDALONE_PROCESS': '0',
                                     'WINUX_DISABLE_HARD_EXIT': '1'}):
            controller = None
            if args.controller:
                from WinUx.controller import WinUXController
                controller = WinUXController()
                controller.initial_local = Path(profile)
                view = controller.view
            else:
                view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            try:
                view._gui_runtime.show()
                if controller is None:
                    for panel in view.panels:
                        panel.listview.set_items([
                            ListViewItem(name='File {}.txt'.format(i), path='C:/test/{}.txt'.format(i),
                                         is_dir=False, item_type='File') for i in range(100)])
                settle_until = time.perf_counter() + (4 if args.controller else .5)
                while time.perf_counter() < settle_until:
                    view.update()
                    time.sleep(.01)
                timer_calls = [0]
                def passive_timer():
                    timer_calls[0] += 1
                    view.after(args.timer_ms, passive_timer)
                if args.timer_ms > 0:
                    view.after(args.timer_ms, passive_timer)
                profiler = cProfile.Profile()
                frames = 0
                start, cpu = time.perf_counter(), time.process_time()
                if args.profile:
                    profiler.enable()
                while time.perf_counter() - start < args.seconds:
                    if args.paced:
                        view._wait_for_ui_frame()
                    view.update()
                    frames += 1
                if args.profile:
                    profiler.disable()
                elapsed, used = time.perf_counter() - start, time.process_time() - cpu
                print('IDLE mode={} wall={:.3f}s cpu={:.3f}s one_core={:.1f}% frames={} fps={:.1f}'.format(
                    'paced' if args.paced else 'unpaced', elapsed, used, used / elapsed * 100,
                    frames, frames / elapsed), flush=True)
                if args.controller or args.timer_ms:
                    print('CONTROLLER={} TIMER_CALLBACKS={}'.format(args.controller, timer_calls[0]), flush=True)
                memory_snapshot(view)
                if args.profile:
                    pstats.Stats(profiler).sort_stats('cumtime').print_stats(20)
            finally:
                if controller is not None:
                    controller._finish_close()
                else:
                    view.request_shutdown()
                view._destroy_components()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
