"""Measure real HWND cold/warm/reused startup with the native regression host.

Run with abaqus python; numbers include the harness's 10 ms parent UI pump.
"""
import argparse
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_winux import _configure_bundled_dependencies
_configure_bundled_dependencies(str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def summarize(samples):
    ordered = sorted(samples)
    return {"n": len(samples), "p50_ms": round(statistics.median(samples), 2),
            "p95_ms": round(ordered[math.ceil(.95 * len(ordered)) - 1], 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--kind", choices=("blocking", "local_folder", "local_file", "settings"), default="local_folder")
    parser.add_argument("--conservative", action="store_true", help="disable cached-host startup shortcuts")
    parser.add_argument("--pool-size", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    if os.name != "nt" or args.iterations < 3:
        parser.error("requires Windows and at least 3 reused iterations")
    from test_all_floating_dialogs import AllFloatingIntegrationTests
    from WinUx.dialogs.floating_dialog import FloatingDialogController
    from WinUx.dialogs.prewarm_pool import DialogPrewarmPool
    from WinUx.ui.hosting.host import QDialogHostManager
    host = AllFloatingIntegrationTests()
    temporary_root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="winux-dialog-benchmark-", dir=temporary_root) as directory:
        for index in range(50):
            (Path(directory) / ("Folder-%03d" % index)).mkdir()
        payload = ({"initial": directory} if args.kind != "blocking" else
                   {"title": "WinUx startup benchmark", "message": "Benchmark", "kind": "confirm"})
        host.setUp()
        try:
            def open_dialog():
                return host.create(lambda: FloatingDialogController(
                    host.view, args.kind, "WinUx startup benchmark", payload=payload,
                    modal=True, owner_hwnd=host.owner, fast_startup=not args.conservative))

            cold = open_dialog()
            cold_ms = cold._open_elapsed_ms
            cold.destroy()
            host.wait_for(lambda: cold._host_returned if cold._reuse_host
                          else cold._process.poll() is not None, timeout=8)
            host.view._dialog_host_manager.close()
            pool = host.view._dialog_prewarm_pool = DialogPrewarmPool(capacity=args.pool_size, reusable=True,
                                                                    signature_cache=not args.conservative)
            host.view._dialog_host_pool = pool
            host.view._dialog_host_manager = QDialogHostManager(host.view, pool)
            host.wait_for(lambda: len(pool._workers) == args.pool_size
                          and all(worker.ready.is_set() for worker in pool._workers))
            samples, stages, frames = [], {}, []
            warm_ms, pid, hwnd = None, None, None
            warm_stages = {}
            for index in range(args.iterations + 1):
                dialog = open_dialog()
                if index == 0:
                    warm_ms, pid, hwnd = dialog._open_elapsed_ms, dialog._process.pid, dialog._hwnd
                    warm_stages = dialog._startup_timings
                else:
                    assert (dialog._process.pid, dialog._hwnd) == (pid, hwnd), "host was unexpectedly retired"
                    samples.append(dialog._open_elapsed_ms)
                    frames.append(len(dialog._startup_frames))
                    for name, value in dialog._startup_timings.items():
                        stages.setdefault(name, []).append(value)
                dialog.destroy()
                host.wait_for(lambda: dialog._host_returned)
            print(json.dumps({"kind": args.kind, "pool_size": args.pool_size,
                               "fast_startup": not args.conservative, "cold_ms": round(cold_ms, 2),
                               "warm_ms": round(warm_ms, 2), "reused": summarize(samples),
                               "warm_stages_ms": warm_stages,
                              "source_cache": {"enabled": pool._source_cache is not None,
                                  "failed": bool(pool._source_cache and pool._source_cache.failed)},
                              "stage_stats": {name: summarize(values) for name, values in stages.items()},
                              "startup_frames": frames, "scope": "native harness; 10 ms parent pump; 50 folders"}, indent=2))
        finally:
            host.tearDown()


if __name__ == "__main__":
    main()
