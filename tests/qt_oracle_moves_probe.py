"""Custom flat/tree move transactions against Qt, not invented standard-item moves."""
import argparse
import json
import random
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=('qt', 'dearuiqt'), required=True)
    parser.add_argument('--root', default='.')
    args = parser.parse_args()
    if args.engine == 'qt':
        from PySide6.QtCore import QAbstractTableModel, QAbstractItemModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel, QItemSelection, qVersion
        from PySide6.QtGui import QStandardItemModel
        version = qVersion()
    else:
        sys.path.insert(0, str(Path(args.root).resolve()))
        from DearUIQt.QtCore import QAbstractTableModel, QAbstractItemModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel, QItemSelection
        from DearUIQt.QtGui import QStandardItemModel
        version = 'Qt-6.8-subset'
    flags = getattr(QItemSelectionModel, 'SelectionFlag', QItemSelectionModel)
    trace = []

    class Flat(QAbstractTableModel):
        def __init__(self):
            super().__init__()
            self.values = [['%d:%d' % (r, c) for c in range(4)] for r in range(5)]
        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.values)
        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.values[0])
        def data(self, index, role=0):
            return self.values[index.row()][index.column()] if index.isValid() and int(role) == 0 else None
        def moveRows(self, sourceParent, sourceRow, count, destinationParent, destinationChild):
            if (sourceParent.isValid() or destinationParent.isValid() or count <= 0 or sourceRow < 0
                    or sourceRow + count > self.rowCount() or not 0 <= destinationChild <= self.rowCount()):
                return False
            if not self.beginMoveRows(sourceParent, sourceRow, sourceRow + count - 1, destinationParent, destinationChild):
                return False
            block = self.values[sourceRow:sourceRow + count]
            del self.values[sourceRow:sourceRow + count]
            target = destinationChild - count if destinationChild > sourceRow else destinationChild
            self.values[target:target] = block
            self.endMoveRows()
            return True
        def moveColumns(self, sourceParent, sourceColumn, count, destinationParent, destinationChild):
            if (sourceParent.isValid() or destinationParent.isValid() or count <= 0 or sourceColumn < 0
                    or sourceColumn + count > self.columnCount() or not 0 <= destinationChild <= self.columnCount()):
                return False
            if not self.beginMoveColumns(sourceParent, sourceColumn, sourceColumn + count - 1, destinationParent, destinationChild):
                return False
            target = destinationChild - count if destinationChild > sourceColumn else destinationChild
            for row in self.values:
                block = row[sourceColumn:sourceColumn + count]
                del row[sourceColumn:sourceColumn + count]
                row[target:target] = block
            self.endMoveColumns()
            return True

    def key(index):
        path = []
        while index.isValid():
            path.append([index.row(), index.column()])
            index = index.parent()
        return path[::-1] if path else None
    def keys(indexes):
        return sorted((key(index) for index in indexes), key=lambda value: json.dumps(value))

    def observe(model, selection, watched, contents):
        events = []
        def state():
            return {'current': key(selection.currentIndex()), 'data': selection.currentIndex().data(),
                    'selected': keys(selection.selectedIndexes()),
                    'persistent': [[key(index), index.data()] for index in watched],
                    'contents': json.loads(json.dumps(contents()))}
        for name in ('rowsAboutToBeMoved', 'rowsMoved', 'columnsAboutToBeMoved', 'columnsMoved'):
            getattr(model, name).connect(lambda source, first, last, destination, child, name=name: events.append({
                'signal': name, 'source': key(source), 'first': first, 'last': last,
                'destination': key(destination), 'child': child, 'state': state()}))
        selection.selectionChanged.connect(lambda added, removed: events.append({
            'signal': 'selection', 'added': keys(added.indexes()), 'removed': keys(removed.indexes())}))
        selection.currentChanged.connect(lambda current, old: events.append({'signal': 'current'}))
        def record(name, action):
            events.clear()
            result = action()
            trace.append({'name': name, 'result': result, 'state': state(), 'events': list(events)})
        return record

    model = Flat()
    selection = QItemSelectionModel(model)
    selection.select(QItemSelection(model.index(1, 1), model.index(3, 2)), flags.ClearAndSelect)
    selection.setCurrentIndex(model.index(2, 1), flags.NoUpdate)
    watched = [QPersistentModelIndex(model.index(r, c)) for r, c in ((0, 0), (2, 1), (4, 3))]
    record = observe(model, selection, watched, lambda: model.values)
    # Snapshot mutable model storage deeply: later moves must not edit history.
    def record_flat(name, action):
        record(name, action)
        trace[-1] = json.loads(json.dumps(trace[-1]))
    root = QModelIndex()
    record_flat('move-row-block-down', lambda: model.moveRows(root, 1, 2, root, 5))
    record_flat('move-row-block-up', lambda: model.moveRows(root, 3, 2, root, 0))
    record_flat('move-column-block-right', lambda: model.moveColumns(root, 0, 2, root, 4))
    record_flat('move-column-left', lambda: model.moveColumn(root, 3, root, 0))
    record_flat('reject-overlapping-row-destination', lambda: model.moveRows(root, 1, 2, root, 2))
    record_flat('reject-row-noop', lambda: model.moveRow(root, 1, root, 2))
    record_flat('current-after-move-keeps-layer', lambda: selection.select(model.index(0, 0), flags.ToggleCurrent))
    rng = random.Random(68071)
    for number in range(100):
        rows = bool(rng.randrange(2))
        size = model.rowCount() if rows else model.columnCount()
        first = rng.randrange(size)
        count = rng.randrange(1, size - first + 1)
        destination = rng.randrange(size + 1)
        method = model.moveRows if rows else model.moveColumns
        record_flat('seed-%03d' % number, lambda method=method, first=first, count=count, destination=destination:
                    method(root, first, count, root, destination))

    class Node:
        def __init__(self, text, parent=None):
            self.text, self.owner, self.children = text, parent, []
            if parent is not None:
                parent.children.append(self)
    class Tree(QAbstractItemModel):
        def __init__(self):
            super().__init__()
            self.root = Node('root')
        def node(self, index):
            return index.internalPointer() if index.isValid() else self.root
        def indexForNode(self, node):
            return self.createIndex(node.owner.children.index(node), 0, node) if node.owner else QModelIndex()
        def index(self, row, column, parent=QModelIndex()):
            children = self.node(parent).children
            return self.createIndex(row, column, children[row]) if column == 0 and 0 <= row < len(children) else QModelIndex()
        def parent(self, index):
            return self.indexForNode(self.node(index).owner) if index.isValid() else QModelIndex()
        def rowCount(self, parent=QModelIndex()):
            return len(self.node(parent).children)
        def columnCount(self, parent=QModelIndex()):
            return 1
        def data(self, index, role=0):
            return self.node(index).text if index.isValid() and int(role) == 0 else None
        def moveRows(self, sourceParent, sourceRow, count, destinationParent, destinationChild):
            source, destination = self.node(sourceParent), self.node(destinationParent)
            if count <= 0 or sourceRow < 0 or sourceRow + count > len(source.children) or not 0 <= destinationChild <= len(destination.children):
                return False
            if not self.beginMoveRows(sourceParent, sourceRow, sourceRow + count - 1, destinationParent, destinationChild):
                return False
            block = source.children[sourceRow:sourceRow + count]
            del source.children[sourceRow:sourceRow + count]
            target = destinationChild - count if source is destination and destinationChild > sourceRow else destinationChild
            destination.children[target:target] = block
            for node in block:
                node.owner = destination
            self.endMoveRows()
            return True
    tree = Tree()
    a, b, c = [Node(text, tree.root) for text in ('A', 'B', 'C')]
    a0, a1, a2 = [Node(text, a) for text in ('a0', 'a1', 'a2')]
    grand = Node('grand', a1)
    Node('b0', b)
    Node('b1', b)
    selection = QItemSelectionModel(tree)
    selection.setCurrentIndex(tree.indexForNode(grand), flags.ClearAndSelect)
    watched = [QPersistentModelIndex(tree.indexForNode(node)) for node in (a, b, a1, grand)]
    def contents():
        def descend(node):
            return [node.text, [descend(child) for child in node.children]]
        return descend(tree.root)
    record = observe(tree, selection, watched, contents)
    record('cross-parent-move-subtree', lambda: tree.moveRows(tree.indexForNode(a), 1, 1, tree.indexForNode(b), 1))
    record('move-root-ancestor-down', lambda: tree.moveRow(root, 0, root, 3))
    record('move-subtree-to-root', lambda: tree.moveRow(tree.indexForNode(b), 1, root, 1))
    record('move-root-ancestor-up', lambda: tree.moveRow(root, 3, root, 0))
    record('reject-move-under-self', lambda: tree.moveRow(root, 0, tree.indexForNode(a), 0))
    record('move-root-under-shifting-destination', lambda: tree.moveRow(root, 0, tree.indexForNode(c), 0))
    record('move-child-before-shifting-source-parent', lambda: tree.moveRow(tree.indexForNode(a), 0, root, 0))
    standard = QStandardItemModel(3, 3)
    trace.append({'name': 'standard-item-default-moves-unsupported',
                  'rows': standard.moveRows(root, 0, 1, root, 3),
                  'columns': standard.moveColumns(root, 0, 1, root, 3)})
    print('QT_ORACLE_JSON:' + json.dumps({'version': version, 'trace': trace, 'ranges': {}}, sort_keys=True))


if __name__ == '__main__':
    main()
