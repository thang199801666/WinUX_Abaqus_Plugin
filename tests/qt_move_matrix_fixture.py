"""Shared, engine-injected hierarchical matrix fixture for column-move tests.

The oracle runner prepends this source to its isolated Qt probe, avoiding any
workspace imports in the PySide interpreter. This is test storage, not runtime API.
"""


def make_matrix_model(QAbstractItemModel, QModelIndex):
    class Cell:
        def __init__(self, text, owner=None):
            self.text, self.owner, self.grid = text, owner, []

        def populate(self, rows, columns):
            self.grid = [[Cell('%s-%d:%d' % (self.text, row, column), self)
                          for column in range(columns)] for row in range(rows)]

    class MatrixModel(QAbstractItemModel):
        def __init__(self):
            super().__init__()
            self.root = Cell('root')
            self.root.grid = [[Cell(text, self.root) for text in ('A', 'B', 'C')]]
            self.a, self.b, self.c = self.root.grid[0]
            self.a.populate(2, 3)
            self.b.populate(2, 3)
            self.c.populate(1, 2)
            self.branch = self.a.grid[1][1]
            self.branch.populate(1, 1)
            self.grandchild = self.branch.grid[0][0]

        def cell(self, index):
            return index.internalPointer() if index.isValid() else self.root

        def indexForCell(self, cell):
            if cell.owner is not None:
                for row, values in enumerate(cell.owner.grid):
                    for column, candidate in enumerate(values):
                        if candidate is cell:
                            return self.createIndex(row, column, cell)
            return QModelIndex()

        def index(self, row, column, parent=QModelIndex()):
            grid = self.cell(parent).grid
            return (self.createIndex(row, column, grid[row][column])
                    if 0 <= row < len(grid) and 0 <= column < len(grid[row]) else QModelIndex())

        def parent(self, index):
            return self.indexForCell(self.cell(index).owner) if index.isValid() else QModelIndex()

        def rowCount(self, parent=QModelIndex()):
            return len(self.cell(parent).grid)

        def columnCount(self, parent=QModelIndex()):
            grid = self.cell(parent).grid
            return len(grid[0]) if grid else 0

        def data(self, index, role=0):
            return self.cell(index).text if index.isValid() and int(role) == 0 else None

        def moveColumns(self, sourceParent, sourceColumn, count, destinationParent, destinationChild):
            if any(index.isValid() and index.model() is not self for index in (sourceParent, destinationParent)):
                return False
            source, target = self.cell(sourceParent), self.cell(destinationParent)
            if (len(source.grid) != len(target.grid) or count <= 0 or sourceColumn < 0
                    or sourceColumn + count > self.columnCount(sourceParent)
                    or not 0 <= destinationChild <= self.columnCount(destinationParent)):
                return False
            if not self.beginMoveColumns(sourceParent, sourceColumn, sourceColumn + count - 1,
                                         destinationParent, destinationChild):
                return False
            destination = destinationChild - count if source is target and destinationChild > sourceColumn else destinationChild
            for source_row, target_row in zip(source.grid, target.grid):
                block = source_row[sourceColumn:sourceColumn + count]
                del source_row[sourceColumn:sourceColumn + count]
                target_row[destination:destination] = block
                for cell in block:
                    cell.owner = target
            self.endMoveColumns()
            return True

        def contents(self):
            def descend(cell):
                return [cell.text, [[descend(child) for child in row] for row in cell.grid]]
            return descend(self.root)

    return MatrixModel
