from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import Qt
from DearUIQt.gui import QFontMetrics


class Backend:
    def __init__(self):
        self.calls = 0

    def get_text_size(self, text, **_kwargs):
        self.calls += 1
        return len(text) * 8, 20


def main():
    backend = Backend()
    metrics = QFontMetrics(backend=backend)
    text = 'A long engineering label that must be elided without repeated renderer measurements'
    start = time.perf_counter()
    for _ in range(20000):
        metrics.elidedText(text, Qt.ElideMiddle, 240)
    elapsed = time.perf_counter() - start
    print('20k cached elisions: {:.3f} ms'.format(elapsed * 1000))
    print('backend measurements:', backend.calls)

    start = time.perf_counter()
    for _ in range(10000):
        metrics.wrappedLines(text, 160)
    elapsed = time.perf_counter() - start
    print('10k cached wraps: {:.3f} ms'.format(elapsed * 1000))
    print('backend measurements total:', backend.calls)


if __name__ == '__main__':
    main()
