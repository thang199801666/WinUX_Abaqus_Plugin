"""Compare portable row-refresh reconciliation before/after model extraction."""
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.components.explorer_item_model import ExplorerItemModel, stable_item_identity as identity
from WinUx.components.explorer_list_model import ListViewItem


def original(old, items, selected, anchor, current):
    old = list(old)
    selected_keys = {identity(old[i]) for i in selected if 0 <= i < len(old)}
    anchor_key = identity(old[anchor]) if anchor is not None and 0 <= anchor < len(old) else None
    current_key = identity(old[current]) if current is not None and 0 <= current < len(old) else None
    old_topology = [identity(item) for item in old]
    def sort_value(item):
        return getattr(item, "cached_name_sort", item.name.casefold())
    parents = [i for i in items if i.is_dir and i.name == ".."]
    folders = sorted((i for i in items if i.is_dir and i.name != ".."), key=sort_value)
    files = sorted((i for i in items if not i.is_dir), key=sort_value)
    items = parents + folders + files
    topology = [identity(item) for item in items]
    selected = {i for i, item in enumerate(items) if identity(item) in selected_keys}
    anchor = next((i for i, item in enumerate(items) if anchor_key is not None and identity(item) == anchor_key), None)
    current = next((i for i, item in enumerate(items) if current_key is not None and identity(item) == current_key), None)
    if current is None and selected:
        current = min(selected)
    return items, (old_topology, topology, selected, anchor, current)


def main():
    report = {"scope": "portable metadata refresh, no native rendering or SSH", "cases": {}}
    for count in (1000, 20000):
        old = [ListViewItem("row{:06d}".format(i), "/rows/{}".format(i)) for i in range(count)]
        new = [ListViewItem(i.name, i.path, size=1) for i in reversed(old)]
        selected, anchor, current = set(range(0, count, 5)), count - 1, count - 2
        _, expected = original(old, new, selected, anchor, current)
        model = ExplorerItemModel()
        model.items = old
        result = model.replace(new, selected, anchor, current)
        assert expected == (result.old_topology, result.new_topology, result.selected, result.anchor, result.current)
        samples = {}
        for name in ("original", "model"):
            timings = []
            for _ in range(5):
                start = time.perf_counter()
                for _ in range(10):
                    if name == "original":
                        original(old, new, selected, anchor, current)
                    else:
                        model.items = old
                        model.replace(new, selected, anchor, current)
                timings.append((time.perf_counter() - start) / 10)
            samples[name] = statistics.median(timings)
        report["cases"][str(count)] = {"median_seconds": samples, "speedup": samples["original"] / samples["model"]}
    payload = json.dumps(report, indent=2)
    Path(__file__).with_name("benchmark_explorer_model.json").write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
