"""Microbenchmark for DearUIQt live-DPI lifecycle bookkeeping.

This measures Python-side polling/dispatch with a fake backend. It does not
measure Win32 GetDpiForWindow, Dear ImGui theme upload, GPU rendering or
WM_DPICHANGED latency.
"""
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from tests.test_dearuiqt_live_dpi import LiveDpiBackend, TrackingRoot
from DearUIQt.gui.dpi import clear_backend_dpi_state, sync_backend_dpi
from DearUIQt.widgets.buttons import ImGuiPushButton


def main():
    backend = LiveDpiBackend(96)
    root = TrackingRoot(backend=backend)
    with patch('DearUIQt.widgets.buttons._bind_focus_state_handlers', return_value=None), \
         patch('DearUIQt.widgets.buttons.bind_theme', return_value=True):
        buttons = [ImGuiPushButton(str(index), parent=root, backend=backend)
                   for index in range(1000)]
        try:
            backend.dpi = 144
            backend.dpi_calls = 0
            started = time.perf_counter()
            changed = sync_backend_dpi(backend)
            transition_ms = (time.perf_counter() - started) * 1000.0

            backend.dpi_calls = 0
            count = 100_000
            started = time.perf_counter()
            for _ in range(count):
                sync_backend_dpi(backend)
            unchanged_ms = (time.perf_counter() - started) * 1000.0

            print('transition_widgets={}'.format(changed))
            print('transition_ms={:.3f}'.format(transition_ms))
            print('root_layout_invalidations={}'.format(root.geometry_updates))
            print('unchanged_100k_ms={:.3f}'.format(unchanged_ms))
            print('unchanged_us_per_call={:.3f}'.format(unchanged_ms * 1000.0 / count))
            print('unchanged_backend_dpi_queries={}'.format(backend.dpi_calls))
        finally:
            for button in buttons:
                button.delete()
    root.delete()
    clear_backend_dpi_state()


if __name__ == '__main__':
    main()
