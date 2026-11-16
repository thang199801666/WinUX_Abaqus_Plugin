"""In-memory ancestor lookup cost; not SSH throughput or filesystem latency."""
from pathlib import Path, PurePosixPath
from statistics import median
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from WinUx.services.transfer_conflicts import TransferItemState
from WinUx.services.transfer_tree_copy import DirectoryChecks


def main():
    parent = PurePosixPath('/tree/a/b/c/d/e')
    guards = {str(path): TransferItemState(0, 0, stat.S_IFDIR | 0o755, identity=(1, i))
              for i, path in enumerate((parent, *parent.parents))}
    cancelled = lambda: None
    state = lambda path, local: guards[path]
    def previous(child):
        for path in (str(path) for path in child.parents):
            expected = guards.get(path)
            if expected is None:
                continue
            cancelled()
            actual = state(path, True)
            if not actual.directory or actual.identity != expected.identity:
                raise RuntimeError('changed')
    checks = DirectoryChecks(guards, local=True, state=state, cancelled=cancelled)
    files = [parent / 'file{}.inp'.format(i) for i in range(5000)]
    def sample(callback):
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            for path in files:
                callback(path)
                callback(path)  # Before copy and before publication.
            samples.append((time.perf_counter() - start) * 1000)
        return median(samples)
    print('Isolated 5,000-file/two-check median: ancestor rebuild {:.2f}ms; cached lookup chain {:.2f}ms; '
          'metadata calls unchanged ({} per pass).'.format(sample(previous), sample(checks.check), len(guards) * 10000))


if __name__ == '__main__':
    main()
