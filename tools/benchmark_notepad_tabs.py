"""Hidden Tk microbenchmark: full tab recreation versus retained reconciliation."""
import json
from pathlib import Path
import statistics
import sys
import time
import tkinter as tk
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.components.server_notepad_tabs import _EditorTabStrip


def main():
    root = tk.Tk()
    root.withdraw()
    docs = [SimpleNamespace(path='file{}.inp'.format(n)) for n in range(12)]
    owner = SimpleNamespace(_tab_title=lambda doc, **kwargs: doc.path,
        _close_doc=lambda doc: None, _select_doc=lambda doc: None,
        _show_tab_context_menu=lambda *args: None, _active_doc=lambda: None)
    iterations = 20
    samples = {}
    try:
        for mode in ('recreate', 'retained'):
            durations = []
            for repeat in range(5):
                strip = _EditorTabStrip(owner, root)
                strip.rebuild(docs, docs[0].path)
                started = time.perf_counter()
                for i in range(iterations):
                    if mode == 'recreate':
                        for item in strip._items.values():
                            item['cell'].destroy()
                        strip._items, strip._order = {}, ()
                    strip.rebuild(docs, docs[i % len(docs)].path)
                durations.append((time.perf_counter() - started) * 1000)
                strip.frame.destroy()
            samples[mode] = statistics.median(durations)
    finally:
        root.destroy()
    report = dict(scope='hidden Tk widget microbenchmark; no visible frame-rate or SSH claim',
        tabs=len(docs), rebuilds=iterations, repeats=5, median_ms=samples,
        speedup=samples['recreate'] / samples['retained'])
    output = Path(__file__).with_suffix('.json')
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
