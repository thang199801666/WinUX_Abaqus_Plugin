"""Micro-benchmark for dirty-row propagation in stable Explorer topology."""
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.components.explorer.row_registry import ExplorerRowRegistryMixin as Registry

COUNT = 30000
rows = [dict(index=i, content_changed=False) for i in range(COUNT)]
topology = tuple(("path", f"C:/tmp/file-{i}.inp") for i in range(COUNT))
host = SimpleNamespace(_row_items=rows)

def bind(row, index, preserve_geometry=False):
    # Approximate the Python-side dispatch/check work done before native draws.
    row["content_changed"] = (index == 17777)
    _ = row.get("index"), row.get("content_changed"), preserve_geometry

host._bind_body_row = bind


def baseline():
    Registry._reconcile_body_rows(host, topology, topology, changed_indices=None)


def targeted():
    Registry._reconcile_body_rows(host, topology, topology, changed_indices={17777})


def measure(fn, loops):
    best = float("inf")
    for _ in range(loops):
        t0 = time.perf_counter()
        fn()
        best = min(best, (time.perf_counter() - t0) * 1000.0)
    return best

base = measure(baseline, 8)
fast = measure(targeted, 50)
print(f"rows={COUNT}")
print(f"full_rebind_dispatch_ms={base:.3f}")
print(f"one_dirty_row_dispatch_ms={fast:.6f}")
print(f"speedup={base / fast:.1f}x")
