"""Python-only view/model selection synchronization and notification counts."""
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_selection_sync import Model, QtListView, ListBackend


def previous_sync(view):
    selection = view.selectionModel()
    selection.clearSelection()
    for key in view._state.keys:
        if key in view.selected:
            selection.select(view._model_index_for_key(key), view._selection_model_command())
    current = view._model_index_for_key(view.current)
    if current.isValid():
        selection.setCurrentIndex(current)


def main():
    with patch('DearUIQt.modelview.list.qt_item_row_theme', return_value=0):
        view = QtListView(backend=ListBackend(), multiple=True)
        try:
            view.setModel(Model(2000))
            view.selected = set(range(2000))
            notifications = [0]
            def changed(*args):
                notifications[0] += 1
            view.selectionModel().selectionChanged.connect(changed)
            started = time.perf_counter()
            previous_sync(view)
            before = (time.perf_counter() - started) * 1000
            old_notifications = notifications[0]
            view.selectionModel().clearSelection()
            notifications[0] = 0
            started = time.perf_counter()
            view._sync_model_selection()
            after = (time.perf_counter() - started) * 1000
            assert len(view.selectionModel().selectedIndexes()) == 2000
            assert old_notifications == 2000 and notifications[0] == 1
            print('2,000 selected rows, view -> model: %.2f -> %.2f ms' % (before, after))
            print('selectionChanged notifications: %d -> %d' % (old_notifications, notifications[0]))
            print('Python-only selection work; excludes native rendering and application observers.')
        finally:
            view.delete()


if __name__ == '__main__':
    main()
