"""Isolated Python list reconciliation/lookup cost, not GUI FPS or total RAM."""
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_list_updates import make_list


def previous_reconcile(listing):
    enabled = {value.key: bool(value.enabled) for value in listing._values}
    for key, item in tuple(listing.items.items()):
        state = (key in listing.selected, not enabled.get(key, True),
                 key == listing.current, listing._has_focus)
        if listing._row_visual_state.get(key) != state:
            listing.backend.set_value(item, state[0])
            listing.backend.bind_item_theme(item, 0)
            listing._row_visual_state[key] = state


def elapsed(callback, count):
    start = time.perf_counter()
    for i in range(count):
        callback(i)
    return (time.perf_counter() - start) * 1000


def main():
    with patch('DearUIQt.modelview.list.qt_item_row_theme', return_value=0):
        backend, listing = make_list(30000)
        try:
            listing.setCurrentKey(0)
            def reconcile(i, callback):
                listing._state.select(29000 + i % 500)
                callback(listing)
            before = elapsed(lambda i: reconcile(i, previous_reconcile), 500)
            # Refresh the optimized snapshot after the legacy measurement.
            listing._row_visual_full_sync = True
            listing._sync_selection_visuals()
            after = elapsed(lambda i: reconcile(i, lambda view: view._sync_selection_visuals()), 500)
            old_lookup = elapsed(lambda i: next(value for value in listing._values if value.key == 29999), 2000)
            new_lookup = elapsed(lambda i: listing.itemForKey(29999), 2000)
            print('30,000 rows / 500 selection reconciliations: %.2f -> %.2f ms' % (before, after))
            print('2,000 last-row payload lookups: %.2f -> %.2f ms' % (old_lookup, new_lookup))
            print('No additional per-row lookup dictionary; existing state index reused.')
        finally:
            listing.delete()


if __name__ == '__main__':
    main()
