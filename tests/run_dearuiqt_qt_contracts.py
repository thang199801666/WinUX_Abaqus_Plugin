"""Run the implemented Qt contract subset; this is not a Qt runtime oracle."""
import importlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MODULES = (
    'test_dearuiqt_qt_selection_lifecycle',
    'test_dearuiqt_qt_selection_current',
    'test_dearuiqt_qt_selection_queries',
    'test_dearuiqt_qt_shared_selection',
    'test_dearuiqt_qt_model_transactions',
    'test_dearuiqt_qt_persistent_indexes',
    'test_dearuiqt_qt_selection_structure',
    'test_dearuiqt_qt_item_lifecycle',
    'test_dearuiqt_qt_columns',
    'test_dearuiqt_qt_headers',
    'test_dearuiqt_qt_moves',
    'test_dearuiqt_qt_column_moves',
    'test_dearuiqt_qt_model_reset',
    'test_dearuiqt_qt_sort',
    'test_dearuiqt_qt_model_conformance',
    'test_dearuiqt_selection_range_fastpath',
    'test_dearuiqt_selection_expansion_fastpath',
    'test_dearuiqt_selection_corners',
    'test_dearuiqt_section_queries_fastpath',
    'test_dearuiqt_selection_membership',
    'test_dearuiqt_range_validation',
    'test_dearuiqt_range_intersections',
    'test_dearuiqt_item_row_count',
)


def main():
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for name in MODULES:
        suite.addTests(loader.loadTestsFromModule(importlib.import_module(name)))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
