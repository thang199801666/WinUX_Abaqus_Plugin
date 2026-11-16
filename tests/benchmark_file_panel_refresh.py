"""Full file-panel metadata reconciliation, with rendering replaced by a collector."""
import argparse
from dataclasses import replace
from pathlib import PurePosixPath
import statistics
import time
from test_file_panel_refresh import FilePanel, TemporaryRowPanel, FileItem, make_panel, fingerprint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=30000)
    parser.add_argument('--changed', type=int, default=1)
    parser.add_argument('--repeat', type=int, default=5)
    args = parser.parse_args()
    if args.rows < 1 or not 1 <= args.changed <= args.rows or args.repeat < 1:
        parser.error('rows/repeat must be positive and changed must be between 1 and rows')
    sources = [FileItem('job%05d.inp' % row, PurePosixPath('/work/job%05d.inp' % row),
                        False, row + 1024, 1700000000, uid=1000, mode=0o100644) for row in range(args.rows)]
    incoming = [replace(source, size=source.size + (1 if row < args.changed else 0))
                for row, source in enumerate(sources)]
    samples = {TemporaryRowPanel: [], FilePanel: []}
    for _ in range(args.repeat):
        for kind in samples:
            panel = make_panel(kind, sources)
            original = list(panel._source_items)
            started = time.perf_counter()
            panel.refresh_directory(panel.current_path, incoming)
            elapsed = (time.perf_counter() - started) * 1000
            assert all(row is old for row, old in zip(panel._source_items, original))
            assert all(fingerprint(row) == fingerprint(FilePanel._convert(source))
                       for row, source in zip(panel._source_items, incoming))
            panel._render_items.assert_called_once()
            samples[kind].append(elapsed)
    reference, current = (statistics.median(samples[kind]) for kind in (TemporaryRowPanel, FilePanel))
    print('%d listed files, %d changed; median of %d:' % (args.rows, args.changed, args.repeat))
    print('temporary-row reference %.3f ms; current %.3f ms; ratio %.2fx' % (reference, current, reference / current))
    print('PASS: row identity, all display/detail fields, latest source snapshots and one incremental render request.')
    print('Python refresh/signature/filter bookkeeping only; setup/validation excluded; no filesystem/SSH or native GUI/FPS claim.')


if __name__ == '__main__':
    main()
