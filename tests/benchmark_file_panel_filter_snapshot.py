"""Measure fused FilePanel filtering/status snapshot work without renderer or IO."""
import argparse
import statistics
import time
from test_file_panel_refresh import FileItem, FilePanel, PurePosixPath, make_panel
from WinUx.services.file_filter import compile_file_filter


def reference_snapshot(panel):
    matches = compile_file_filter(panel._filter_query)
    if panel._show_hidden_files:
        source = panel._source_items
    else:
        source = [item for item in panel._source_items if not panel._is_hidden_item(item)]
    filtered = [item for item in source if matches(item)]
    # Previous render + status path rescanned visibility for the total.
    if panel._show_hidden_files:
        total = len(panel._source_items)
    else:
        total = len([item for item in panel._source_items if not panel._is_hidden_item(item)])
    return filtered, total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=30000)
    parser.add_argument('--repeat', type=int, default=9)
    parser.add_argument('--query', default='*.inp')
    args = parser.parse_args()
    sources = [
        FileItem('job%05d.inp' % row, PurePosixPath('/work/job%05d.inp' % row),
                 False, 2048, 1700000000, is_hidden=(row % 10 == 0))
        for row in range(args.rows)
    ]
    panel = make_panel(FilePanel, sources)
    panel._show_hidden_files = False
    panel._filter_query = args.query
    expected = reference_snapshot(panel)
    actual = panel._filtered_snapshot()
    assert [id(x) for x in actual[0]] == [id(x) for x in expected[0]] and actual[1] == expected[1]

    samples = {'reference': [], 'fused': []}
    for _ in range(args.repeat):
        start = time.perf_counter(); reference_snapshot(panel); samples['reference'].append((time.perf_counter()-start)*1000)
        start = time.perf_counter(); panel._filtered_snapshot(); samples['fused'].append((time.perf_counter()-start)*1000)
    ref = statistics.median(samples['reference'])
    fused = statistics.median(samples['fused'])
    print('%d rows, query=%r, median of %d:' % (args.rows, args.query, args.repeat))
    print('previous render+status snapshot %.3f ms; fused %.3f ms; speedup %.2fx' % (ref, fused, ref/fused))
    print('PASS: identical row identities and visible total; Python-only, renderer/IO excluded.')


if __name__ == '__main__':
    main()
