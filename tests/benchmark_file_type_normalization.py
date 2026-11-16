"""Measure file-type extension normalization used by large Explorer listings."""
import argparse
import ntpath
from pathlib import PurePosixPath
import statistics
import time


def legacy_extension(name, is_dir=False):
    return '' if is_dir else ntpath.splitext(ntpath.basename(str(name or '')))[1].casefold()


def current_extension(name, is_dir=False):
    return '' if is_dir else ntpath.splitext(str(name or ''))[1].casefold()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=30000)
    parser.add_argument('--repeat', type=int, default=7)
    args = parser.parse_args()
    if min(args.rows, args.repeat) < 1:
        parser.error('rows/repeat must be positive')
    names = [PurePosixPath('/remote/project/job%05d.INP' % row) for row in range(args.rows)]
    expected = [legacy_extension(name) for name in names]
    samples = {legacy_extension: [], current_extension: []}
    for _ in range(args.repeat):
        for callback in samples:
            started = time.perf_counter()
            result = [callback(name) for name in names]
            elapsed = (time.perf_counter() - started) * 1000.0
            assert result == expected
            samples[callback].append(elapsed)
    before = statistics.median(samples[legacy_extension])
    after = statistics.median(samples[current_extension])
    print('%d names, median of %d:' % (args.rows, args.repeat))
    print('legacy basename+splitext %.3f ms; current splitext %.3f ms; ratio %.2fx' %
          (before, after, before / after))
    print('PASS: extension normalization is identical for the benchmark corpus.')
    print('Python string/path normalization only; Shell lookup, rendering and filesystem IO excluded.')


if __name__ == '__main__':
    main()
