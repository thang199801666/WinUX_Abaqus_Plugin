"""Bounded DearUIQt test helper, NOT an implementation of Qt's full model tester."""


def assert_model_consistent(model, invalid_index, max_nodes=1000, max_depth=20):
    """Check index/parent/count/bounds/sibling invariants, without structural writes.

    Works with Qt and DearUIQt primitives. Bounds stop malformed cyclic models
    from hanging the test suite. Index lookup may cache private empty-cell
    identities; the helper does not deliberately edit model data or dimensions.
    Return the number of visited indexes.
    """
    visited = 0
    flags = model.CheckIndexOption
    assert not model.parent(invalid_index).isValid(), 'invalid index must have invalid parent'

    def walk(parent, ancestors, depth):
        nonlocal visited
        assert depth <= max_depth, 'model exceeds depth budget or has a parent cycle'
        rows, columns = model.rowCount(parent), model.columnCount(parent)
        assert isinstance(rows, int) and rows >= 0, 'rowCount must be a nonnegative integer'
        assert isinstance(columns, int) and columns >= 0, 'columnCount must be a nonnegative integer'
        for row, column in ((-1, 0), (0, -1), (rows, 0), (0, columns)):
            assert not model.hasIndex(row, column, parent), 'hasIndex accepts an out-of-range coordinate'
            assert not model.index(row, column, parent).isValid(), 'index accepts an out-of-range coordinate'
        for row in range(rows):
            for column in range(columns):
                visited += 1
                assert visited <= max_nodes, 'model exceeds node budget or has a child cycle'
                index = model.index(row, column, parent)
                assert index.isValid(), 'in-range index is invalid'
                assert index.model() is model, 'index belongs to another model'
                assert (index.row(), index.column()) == (row, column), 'wrong index coordinates'
                assert index.parent() == parent, 'index/parent round trip failed'
                assert index not in ancestors, 'index is its own ancestor'
                assert model.checkIndex(index, flags.IndexIsValid), 'checkIndex rejected a valid child'
                assert model.index(row, column, parent) == index, 'repeated index lookup changed identity'
                assert index.sibling(row, column) == index, 'sibling identity failed'
                walk(index, ancestors + [index], depth + 1)
    walk(invalid_index, [], 0)
    return visited
