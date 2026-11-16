"""Measure FilePanel watcher-signature cold vs steady-state no-op cost."""
import argparse
from dataclasses import replace
import statistics
import time
from test_file_panel_refresh import FilePanel, FileItem, PurePosixPath, make_panel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=30000)
    parser.add_argument('--repeat', type=int, default=7)
    args = parser.parse_args()
    if min(args.rows, args.repeat) < 1:
        parser.error('rows/repeat must be positive')

    sources = [
        FileItem('job%05d.inp' % row, PurePosixPath('/work/job%05d.inp' % row),
                 False, row + 1024, 1700000000 + row % 100,
                 uid=1000, mode=0o100644)
        for row in range(args.rows)
    ]
    incoming = [replace(source) for source in reversed(sources)]
    cold, steady = [], []
    for _ in range(args.repeat):
        panel = make_panel(FilePanel, sources)
        started = time.perf_counter()
        panel.refresh_directory(panel.current_path, incoming)
        cold.append((time.perf_counter() - started) * 1000)
        assert panel._render_items.call_count == 0

        started = time.perf_counter()
        panel.refresh_directory(panel.current_path, incoming)
        steady.append((time.perf_counter() - started) * 1000)
        assert panel._render_items.call_count == 0

    cold_median = statistics.median(cold)
    steady_median = statistics.median(steady)
    print('%d rows, median of %d:' % (args.rows, args.repeat))
    print('cold no-op %.3f ms; steady cached no-op %.3f ms; ratio %.2fx' %
          (cold_median, steady_median, cold_median / steady_median))
    print('PASS: both refreshes remain render-free; steady state reuses current-side signature.')
    print('Python metadata/signature path only; native rendering/filesystem/SSH excluded.')


if __name__ == '__main__':
    main()
