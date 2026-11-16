"""Python-only dirty tree selection cost and deterministic native write counts."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_tree_batches import Backend, QTreeWidget, QTreeWidgetItem


class SelectionTree(QTreeWidget):
    def _render_item(self, item, depth):
        # Selection-only fake rows: decoration creation/cleanup is deliberately
        # outside this measurement. The library selection method is unchanged.
        native = self.backend.add_selectable(parent=self.tag, default_value=False)
        self._rendered[item] = {'selectable': native}
        self._item_by_native[native] = item


def previous_sync(tree):
    for item, visual in tuple(tree._rendered.items()):
        selected = item is tree._current
        item._selected = selected
        tree.backend.set_value(visual['selectable'], selected)


def measure(tree, items, sync, iterations):
    writes = 0
    start = time.perf_counter()
    for index in range(iterations):
        tree._current = items[-1000 + index]
        sync(tree)
        writes += len(tree.backend.writes)
        tree.backend.writes.clear()
    return (time.perf_counter() - start) * 1000, writes


def main():
    backend = Backend()
    tree = SelectionTree(backend=backend)
    items = [QTreeWidgetItem(str(i)) for i in range(30000)]
    try:
        tree.addTopLevelItems(items)
        backend.writes.clear()
        before, old_writes = measure(tree, items, previous_sync, 500)
        tree._selection_visual_full_sync = True
        tree._sync_selection()
        backend.writes.clear()
        after, new_writes = measure(tree, items, lambda view: view._sync_selection(), 500)
        assert old_writes == 30000 * 500
        assert new_writes == 1000
        print('30,000 visible nodes / 500 selection syncs: %.2f -> %.2f ms' % (before, after))
        print('Native selection writes: %d -> %d' % (old_writes, new_writes))
        print('Selection-only fake renderer; not GPU/FPS, build time or total RAM.')
    finally:
        tree.delete()


if __name__ == '__main__':
    main()
