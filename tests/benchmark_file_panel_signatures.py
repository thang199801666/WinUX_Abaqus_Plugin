"""Repeated metadata fallback lookup vs one per-signature local snapshot."""
import argparse
from dataclasses import replace
import statistics
import time
from test_file_panel_refresh import FilePanel, FileItem, PurePosixPath, make_panel
from WinUx.ui.components.explorer_list_model import FILE_METADATA_KEYS


class RepeatedMetadataPanel(FilePanel):
    @classmethod
    def _item_signature(cls, item):
        path = (getattr(item, 'data', None) or {}).get('path')
        if path is None:
            path = getattr(item, 'path', None)
        modified = getattr(item, 'modified', getattr(item, 'mtime', 0.0))
        return (cls._path_identity(path or getattr(item, 'name', '')),
                bool(getattr(item, 'is_dir', False)), int(getattr(item, 'size', 0) or 0),
                int(float(modified or 0.0) * 1_000_000), cls._is_hidden_item(item),
                tuple(getattr(item, key, (getattr(item, 'data', None) or {}).get(key))
                      for key in FILE_METADATA_KEYS))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=30000)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--mode', choices=('signatures', 'refresh'), default='signatures')
    parser.add_argument('--unchanged', action='store_true', help='Refresh no-op control')
    args = parser.parse_args()
    if min(args.rows, args.repeat) < 1:
        parser.error('rows/repeat must be positive')
    sources = [FileItem('job%05d.inp' % row, PurePosixPath('/work/job%05d.inp' % row),
                        False, row + 1024, 1700000000, uid=1000, mode=0o100644) for row in range(args.rows)]
    incoming = [replace(source, size=source.size + int(row == 0 and not args.unchanged))
                for row, source in enumerate(sources)]
    expected = tuple(RepeatedMetadataPanel._item_signature(item) for item in sources)
    samples = {RepeatedMetadataPanel: [], FilePanel: []}
    for _ in range(args.repeat):
        for kind in samples:
            panel = make_panel(kind, sources)
            original = list(panel._source_items)
            started = time.perf_counter()
            if args.mode == 'signatures':
                result = tuple(kind._item_signature(item) for item in sources)
            else:
                panel.refresh_directory(panel.current_path, incoming)
            elapsed = (time.perf_counter() - started) * 1000
            if args.mode == 'signatures':
                assert result == expected
            else:
                assert all(row is old for row, old in zip(panel._source_items, original))
                assert [row.size for row in panel._source_items] == [source.size for source in incoming]
                assert panel._render_items.call_count == (0 if args.unchanged else 1)
            samples[kind].append(elapsed)
    reference, current = (statistics.median(samples[kind]) for kind in samples)
    print('%d rows, %s%s, median of %d:' %
          (args.rows, args.mode, '/unchanged' if args.unchanged else '', args.repeat))
    print('repeated-fallback reference %.3f ms; current %.3f ms; ratio %.2fx' % (reference, current, reference / current))
    print('PASS: exact signatures or retained row identity/sizes and refresh render/no-op behavior.')
    print('Python only; setup/validation/native rendering excluded; no filesystem stat cache, SSH/FPS or RAM claim.')


if __name__ == '__main__':
    main()
