"""Micro-benchmark for Explorer incremental row lookup/reconciliation.

Measures Python bookkeeping only; excludes renderer/native draw cost.
"""
from __future__ import annotations

import statistics
import time

ROWS = 30_000
REPEATS = 40

rows = [dict(index=i, content_changed=False) for i in range(ROWS)]
registry = {i: row for i, row in enumerate(rows)}
topology = tuple(f"item-{i}" for i in range(ROWS))


def legacy_target_scan(indices):
    count = 0
    for row in rows:
        if row["index"] not in indices:
            continue
        count += 1
    return count


def registry_target_lookup(indices):
    requested = {i for i in indices if 0 <= i < ROWS}
    selected = tuple(registry[i] for i in sorted(requested) if i in registry)
    return len(selected)


def legacy_stable_reconcile():
    previous = {key: registry[index] for index, key in enumerate(topology)}
    rebound = []
    for index, key in enumerate(topology):
        row = previous.pop(key, None)
        if row["index"] != index:
            row["index"] = index
        rebound.append(row)
    return rebound


def stable_reconcile_fastpath():
    for index, row in enumerate(rows):
        if row["index"] != index:
            row["index"] = index
    return rows


def median_ms(fn, repeats=REPEATS):
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples)


def main():
    one = {ROWS // 2}
    ten = set(range(1000, 1010))
    results = {
        "target-1 legacy scan": median_ms(lambda: legacy_target_scan(one)),
        "target-1 registry lookup": median_ms(lambda: registry_target_lookup(one)),
        "target-10 legacy scan": median_ms(lambda: legacy_target_scan(ten)),
        "target-10 registry lookup": median_ms(lambda: registry_target_lookup(ten)),
        "stable reconcile legacy map": median_ms(legacy_stable_reconcile, 20),
        "stable reconcile fastpath": median_ms(stable_reconcile_fastpath, 20),
    }
    for label, value in results.items():
        print(f"{label}: {value:.6f} ms")


if __name__ == "__main__":
    main()
