import unittest
from unittest.mock import Mock, patch

from WinUx.view import WinUXView
from WinUx.ui.behaviors.plot_docking import PlotDockingMixin


class NativeReferenceStartupTests(unittest.TestCase):
    def test_hidden_tools_never_restore_saved_xy_cells_during_startup(self):
        library = Mock()
        library.snapshot.side_effect = AssertionError("Saved XY cells must not be restored during main startup")
        view = object.__new__(WinUXView)
        with patch.object(PlotDockingMixin, "_get_reference_chart_library", staticmethod(lambda _view: library)), \
                patch("WinUx.dialogs.native_reference_tools.ReferenceChartDialog") as chart, \
                patch("WinUx.dialogs.native_reference_tools.PlotDigitizerDialog") as digitizer:
            view._prepare_native_reference_tools()
        self.assertEqual(chart.call_args.args[1], [])
        library.snapshot.assert_not_called()
        chart.return_value.hide.assert_called_once_with()
        digitizer.assert_called_once_with(view, reference_library=library)
        digitizer.return_value.hide.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
