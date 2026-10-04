"""Portable repeated-viewport tag-write comparison; no Tk rendering timings."""
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.services.server_notepad_highlight import ServerNotepadHighlighter


class TextBoundary:
    def __init__(self):
        self.sample = "for i in range(10): # comment\n    print('value', i)\n" * 100
        self.writes = 0

    def index(self, value):
        return "100.0" if value == "@0,0" else "130.0"

    def winfo_height(self):
        return 400

    def get(self, start, end):
        return self.sample

    def tag_remove(self, *args):
        self.writes += 1

    def tag_add(self, *args):
        self.writes += 1


def measure(cached):
    text = TextBoundary()
    doc = SimpleNamespace(text=text, loaded=True, language="Python", index_generation=0,
                          highlight_after=None, highlight_snapshot=None)
    highlighter = ServerNotepadHighlighter(SimpleNamespace())
    start = time.perf_counter()
    for _ in range(100):
        if not cached:
            doc.highlight_snapshot = None
        highlighter._highlight_document(doc)
    return time.perf_counter() - start, text.writes


def main():
    report = {"scope": "100 repeated identical viewport passes; Python boundary, no Tk render/IPC"}
    for name, cached in (("without_snapshot_cache", False), ("with_snapshot_cache", True)):
        samples = [measure(cached) for _ in range(3)]
        report[name] = {"median_seconds": statistics.median(s[0] for s in samples),
                        "tag_writes": samples[0][1]}
    report["write_reduction_percent"] = 100 * (1 - report["with_snapshot_cache"]["tag_writes"] / report["without_snapshot_cache"]["tag_writes"])
    payload = json.dumps(report, indent=2)
    Path(__file__).with_suffix(".json").write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
