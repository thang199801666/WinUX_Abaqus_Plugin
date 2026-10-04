"""Dependency-free console microbenchmarks; run before and after a change."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from WinUx.runtime.text_buffer import BoundedTextBuffer
from WinUx.runtime.terminal_buffer import TerminalBuffer


def append_stream():
    buffer = BoundedTextBuffer(1_000_000)
    chunk = "output line\n" * 100
    for _ in range(10_000):
        buffer.append(chunk)
    assert len(buffer) == 1_000_000


def edit_console():
    buffer = TerminalBuffer()
    buffer.set_output("Warning: remote output\n" * 5_000 + "host$ ")
    buffer.styled_layout(100)
    for _ in range(100):
        buffer.type_text("x")
        buffer.styled_layout(100)
        buffer.backspace()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = {}
    for name, operation in (("append_stream", append_stream), ("edit_console", edit_console)):
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            operation()
            samples.append(time.perf_counter() - start)
        report[name] = {"median_seconds": statistics.median(samples), "samples": samples}
    payload = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
