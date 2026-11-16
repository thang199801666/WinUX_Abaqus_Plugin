"""Isolated 30k-row filtering benchmark; not whole-application CPU/RAM."""
from pathlib import Path
from statistics import median
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from WinUx.services.file_filter import compile_file_filter
from WinUx.ui.components.explorer_list_model import ListViewItem


def main():
    rows = [ListViewItem('job{:05d}.inp'.format(i), '/work/job{:05d}.inp'.format(i),
                         item_type='Input File') for i in range(30000)]
    def old_match(item, query):
        query = str(query or '').strip().casefold()
        values = (item.name, item.item_type, item.path)
        return any(query in str(value or '').casefold() for value in values)
    def sample(callback):
        durations = []
        for _ in range(7):
            start = time.perf_counter()
            result = callback()
            durations.append((time.perf_counter() - start) * 1000)
            assert len(result) == len(rows)
        return median(durations)
    predicate = compile_file_filter('job')
    baseline = sample(lambda: [row for row in rows if old_match(row, 'job')])
    current = sample(lambda: [row for row in rows if predicate(row)])
    masks = compile_file_filter('*.inp;*.odb|*.bak')
    masked = sample(lambda: [row for row in rows if masks(row)])
    print('Isolated 30,000-row median: previous substring {:.2f} ms; compiled/cached-text {:.2f} ms; mask {:.2f} ms'.format(baseline, current, masked))


if __name__ == '__main__':
    main()
