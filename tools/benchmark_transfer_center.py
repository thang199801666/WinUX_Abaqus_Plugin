"""Measure native Transfer Center cold display and prepared/resident reveal."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_winux import _configure_bundled_dependencies
_configure_bundled_dependencies(str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=6)
    args = parser.parse_args()
    if args.iterations < 3:
        parser.error("at least 3 iterations are required")
    from test_all_floating_dialogs import AllFloatingIntegrationTests
    from WinUx.dialogs.floating_adapters import TransferCenterDialog
    host = AllFloatingIntegrationTests()
    host.setUp()
    try:
        def create():
            with patch("WinUx.dialogs.floating_dialog.find_process_window", return_value=host.owner):
                center = TransferCenterDialog(host.view)
            host.instances.append(center)
            return center

        def show(center):
            start = time.perf_counter()
            center.show()
            host.wait_for(lambda: center._ready and center._native_visible
                          and host.user32.IsWindowVisible(center._hwnd))
            return (time.perf_counter() - start) * 1000

        def hide(center):
            center.hide()
            host.wait_for(lambda: not center._native_visible
                          and not host.user32.IsWindowVisible(center._hwnd))

        start = time.perf_counter()
        cold = create()
        show(cold)
        cold_ms = (time.perf_counter() - start) * 1000
        cold.destroy()
        host.wait_for(lambda: cold._host_returned if cold._reuse_host
                      else cold._process.poll() is not None)
        start = time.perf_counter()
        center = create()
        host.wait_for(lambda: center._ready)
        prepared_ms = (time.perf_counter() - start) * 1000
        assert not host.user32.IsWindowVisible(center._hwnd)
        pid, hwnd = center._process.pid, center._hwnd
        first_show = show(center)
        hide(center)
        samples = []
        for _ in range(args.iterations):
            samples.append(show(center))
            assert (center._process.pid, center._hwnd) == (pid, hwnd)
            hide(center)
        print(json.dumps({
            "cold_request_to_visible_ms": round(cold_ms, 2),
            "hidden_preparation_ms": round(prepared_ms, 2),
            "prepared_first_show_ms": round(first_show, 2),
            "resident_show_p50_ms": round(statistics.median(samples), 2),
            "resident_show_max_ms": round(max(samples), 2),
            "iterations": args.iterations,
            "same_process_and_hwnd": True,
            "scope": "native visibility ACK; 10ms parent pump; no network I/O or row construction",
        }, indent=2))
    finally:
        host.tearDown()
        host.doCleanups()


if __name__ == "__main__":
    main()
