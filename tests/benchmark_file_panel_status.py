"""File-panel selection/status bookkeeping, without native renderer or IO."""
import argparse
import statistics
import time
from test_file_panel_refresh import FilePanel, FileItem, PurePosixPath, make_panel


class RefilterStatusPanel(FilePanel):
    """Reference: preceding status query repeats filtering/visibility scans."""
    def _update_item_status(self, filtered=None):
        if not self.has_status:
            return
        visible = len(self._filtered_items() if filtered is None else filtered)
        total = len(self._visible_source_items())
        prefix = '{} | '.format(self.status_prefix) if self.status_prefix else ''
        if self._filter_query.strip():
            self.status.set(f'{prefix}{visible} of {total} items')
        else:
            self.status.set(f'{prefix}{total} items')


class Sink:
    def __init__(self):
        self.values = []
    def set(self, value):
        self.values.append(value)


def status_panel(kind, sources, query='', show_hidden=False):
    panel = make_panel(kind, sources)
    panel.has_status = True
    panel._show_hidden_files = show_hidden
    panel._filter_query = query
    panel.status_prefix = 'Local'
    panel.status, panel.selected_status = Sink(), Sink()
    panel.selected_transfer_paths = lambda: ['selected.inp']
    return panel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=30000)
    parser.add_argument('--updates', type=int, default=30)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--query', default='')
    parser.add_argument('--show-hidden', action='store_true')
    args = parser.parse_args()
    if min(args.rows, args.updates, args.repeat) < 1:
        parser.error('rows/updates/repeat must be positive')
    sources = [FileItem('job%05d.inp' % row, PurePosixPath('/work/job%05d.inp' % row),
                        False, 2048, 1700000000, is_hidden=row % 10 == 0) for row in range(args.rows)]
    samples = {RefilterStatusPanel: [], FilePanel: []}
    expected = None
    for _ in range(args.repeat):
        for kind in samples:
            panel = status_panel(kind, sources, args.query, args.show_hidden)
            started = time.perf_counter()
            for update in range(args.updates):
                panel._selection_changed()
            elapsed = (time.perf_counter() - started) * 1000
            result = panel.status.values, panel.selected_status.values
            if expected is None:
                expected = result
            assert result == expected and len(panel.status.values) == args.updates
            samples[kind].append(elapsed)
    reference, current = (statistics.median(samples[kind]) for kind in (RefilterStatusPanel, FilePanel))
    print('%d rows, %d selection/status updates, query=%r, show-hidden=%s, median of %d:' %
          (args.rows, args.updates, args.query, args.show_hidden, args.repeat))
    print('refilter reference %.3f ms; current %.3f ms; ratio %.2fx' % (reference, current, reference / current))
    print('PASS: identical complete item/selection status histories.')
    print('Python callback only; selection lookup/native rendering/setup/validation excluded; no GUI/FPS or IO claim.')


if __name__ == '__main__':
    main()
