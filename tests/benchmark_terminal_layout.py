"""Compare full-history copying with indexable viewport layout on the same data."""
import gc
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.runtime.terminal_buffer import TerminalBuffer


def measure(buffer, method, iterations=1000):
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    for _ in range(iterations):
        rows, cursor_row, cursor_col = method(100)
        assert rows[100:132] == ['row'] * 32
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print('{} iterations={} seconds={:.4f} transient_peak={:.2f}KiB'.format(
        method.__name__, iterations, elapsed, peak / 1024), flush=True)


def main():
    buffer = TerminalBuffer()
    buffer.set_output('row\n' * 60000)
    buffer.layout(100)  # Build the same retained prefix before both measurements.
    measure(buffer, buffer.layout)
    measure(buffer, buffer.layout_view)


if __name__ == '__main__':
    main()
