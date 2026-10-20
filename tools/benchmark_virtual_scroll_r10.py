"""Headless opt-in virtual-scroll benchmark (run from project root).

python tools/benchmark_virtual_scroll_r10.py

This uses a fake backend, so numbers are NOT Windows render-frame times or
native Dear PyGui allocation measurements.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from DearUIQt.core import Qt
from DearUIQt.widgets import QScrollBar
from DearUIQt.modelview import (
    QTableView, QtGridRow, ReadOnlyTableViewport, LogicalTableScrollBridge,
    capture_view_resources, capture_view_memory,
)
from tests.test_dearuiqt_modelview_r79 import FakeBackend


class InstrumentedBackend(FakeBackend):
    created_rows = 0
    def add_vslider_int(self, **kwargs):
        return self._new(**kwargs)
    def add_table_row(self, **kwargs):
        self.created_rows += 1
        return super().add_table_row(**kwargs)


def main():
    backend = InstrumentedBackend()
    view = QTableView(columns=['Index', 'Value'], multiple=True, backend=backend)
    slider = QScrollBar(Qt.Vertical, backend=backend)
    rows = [QtGridRow(i, (str(i), i)) for i in range(100_000)]
    viewport = ReadOnlyTableViewport(view, rows, row_height=24, overscan=6)
    bridge = LogicalTableScrollBridge(viewport, slider, viewport_height=480)
    initial = capture_view_resources(view, verify_native=True)
    positions = list(range(0, 100_000, 500)) + [99_980]
    start = time.perf_counter()
    max_native = initial.tracked_native_rows
    for top in positions:
        bridge.scrollToRow(top, alignment='start')
        current = capture_view_resources(view)
        max_native = max(max_native, current.tracked_native_rows)
    elapsed_ms = (time.perf_counter() - start) * 1000
    memory = capture_view_memory(view, verify_native=True)
    results = {
        'kind': 'FAKE BACKEND, NOT WINDOWS NATIVE FPS',
        'logical_rows': len(rows),
        'scroll_positions': len(positions),
        'max_native_rows': max_native,
        'native_rows_at_end': memory.resources.tracked_native_rows,
        'native_rows_created_over_all_scrolls': backend.created_rows,
        'missing_native_items': memory.resources.missing_native_items,
        'elapsed_ms_all_positions': round(elapsed_ms, 2),
        'process_rss_bytes': memory.process_rss_bytes,
        'signal_connections_after_detach': None,
    }
    bridge.detach()
    results['signal_connections_after_detach'] = len(slider.valueChanged._slots)
    viewport.detach()
    slider.delete()
    view.delete()
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
