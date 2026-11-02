"""Python-only old/new table selection cost; no WinUx/GPU or FPS claims."""
from pathlib import Path
import sys
from contextlib import ExitStack
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_table_updates import make_table
from benchmark_dearuiqt_lists import elapsed


def previous_reconcile(table):
    for key, item in tuple(table.items.items()):
        state = (key in table.selected, not bool(table.row_enabled.get(key, True)),
                 key == table.current, table._has_focus)
        if table._row_visual_state.get(key) == state:
            continue
        table.backend.set_value(item, state[0])
        table.backend.bind_item_theme(item, 'row')
        for cell in table._cell_text_items.get(key, ()):
            table.backend.bind_item_theme(cell, 'text')
        table._row_visual_state[key] = state


def main():
    with ExitStack() as stack:
        for name, value in [('qt_item_view_theme', 'table'),
                            ('qt_item_row_theme', 'row'), ('qt_item_text_theme', 'text')]:
            stack.enter_context(patch('DearUIQt.modelview.table.' + name, return_value=value))
        backend, table = make_table(30000)
        try:
            table.setCurrentKey(0)
            def reconcile(i, callback):
                table._state.select(29000 + i % 500)
                callback(table)
            before = elapsed(lambda i: reconcile(i, previous_reconcile), 500)
            table._row_visual_full_sync = True
            table._sync_selection_visuals()
            backend.writes.clear()
            backend.themes.clear()
            after = elapsed(lambda i: reconcile(i, lambda view: view._sync_selection_visuals()), 500)
            print('30,000 rows x 3 columns / 500 selection reconciliations: %.2f -> %.2f ms' % (before, after))
            print('Optimized row writes: %d; cell/row theme writes: %d' %
                  (len(backend.writes), len(backend.themes)))
            print('Full metadata/focus changes and spreadsheet overlay work are not excluded from their own normal paths.')
        finally:
            table.delete()


if __name__ == '__main__':
    main()
