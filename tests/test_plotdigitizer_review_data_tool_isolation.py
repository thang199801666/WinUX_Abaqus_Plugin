import unittest
from types import SimpleNamespace

from WinUx.plotdigitizer.ui.controllers.data import DataController


class _Worksheet:
    def isDragging(self):
        return False


class _Grid:
    def __init__(self):
        self.focused = False

    def setFocus(self):
        self.focused = True


class ReviewDataToolIsolationTests(unittest.TestCase):
    def _owner(self, active_tool):
        calls = []
        owner = SimpleNamespace(
            _selected_point=None,
            _active_tool=active_tool,
            data_worksheet=_Worksheet(),
            result_grid=_Grid(),
            _key_point=lambda key: ('auto', 0) if key else None,
            _show_tool=lambda tool: calls.append(tool),
            _refresh_point_editor=lambda: None,
            _redraw=lambda: None,
        )
        return owner, calls

    def test_grid_current_change_does_not_navigate_out_of_review_data(self):
        owner, calls = self._owner('data')
        DataController(owner)._point_selected('auto:0')
        self.assertEqual([], calls)
        self.assertTrue(owner.result_grid.focused)

    def test_replayed_grid_current_change_does_not_force_extract(self):
        owner, calls = self._owner('axes')
        DataController(owner)._point_selected('auto:0')
        self.assertEqual([], calls)
        self.assertFalse(owner.result_grid.focused)


if __name__ == '__main__':
    unittest.main()
