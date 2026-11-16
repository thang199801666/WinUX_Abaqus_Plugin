"""Isolated Python allocations for bounded Console scrollback and clear."""
import gc
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.runtime.terminal_buffer import TerminalBuffer


def main():
    tracemalloc.start()
    buffer = TerminalBuffer()
    text = ''.join('Job {:05d}: running analysis step 123456789\n'.format(i) for i in range(6000))
    buffer.set_output(text)
    del text
    gc.collect()
    initial = tracemalloc.get_traced_memory()[0]
    started = time.perf_counter()
    rows, _, _ = buffer.styled_layout_slice(100, 100, 132)
    elapsed = time.perf_counter() - started
    del rows
    gc.collect()
    rendered, peak = tracemalloc.get_traced_memory()
    buffer.clear_output()
    gc.collect()
    cleared = tracemalloc.get_traced_memory()[0]
    print('TERMINAL output={:.2f}MiB viewport={:.2f}MiB peak={:.2f}MiB '
          'after_clear={:.2f}MiB first_viewport_ms={:.2f}'.format(
              initial / 2**20, rendered / 2**20, peak / 2**20, cleared / 2**20, elapsed * 1000))
    tracemalloc.stop()


if __name__ == '__main__':
    main()
