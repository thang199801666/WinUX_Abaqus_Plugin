"""Main-view and isolated-dialog bridge for persistent reference curves."""
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.dialogs.floating_adapters import ReferenceChartDialog
from WinUx.dialogs.floating_dialog import FloatingDialogController
from WinUx.services.reference_charts import ReferenceChartLibrary, parse_reference_text
from WinUx.ui.behaviors.plot_docking import PlotDockingMixin


class ReferenceChartIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = ReferenceChartLibrary(root=self.temp.name)
        self.view = SimpleNamespace(_reference_chart_library=self.library,
                                    winfo_exists=lambda: True, show_error=Mock())

    def test_reference_library_can_be_created_before_any_plot_is_open(self):
        view = SimpleNamespace(_reference_chart_library=None)
        with patch("WinUx.services.reference_charts.ReferenceChartLibrary") as factory:
            library = PlotDockingMixin._get_reference_chart_library(view)
        self.assertIs(library, factory.return_value)
        self.assertIs(view._reference_chart_library, library)

    def test_result_saves_independently_of_open_job(self):
        with patch("WinUx.dialogs.reference_chart_dialog.ReferenceChartDialog") as factory:
            PlotDockingMixin._show_reference_chart_dialog(self.view)
            on_result = factory.call_args.args[2]
        references = parse_reference_text("X,A,B\n0,1,2\n1,3,4")
        on_result(references)
        self.assertEqual(ReferenceChartLibrary(root=self.temp.name).snapshot(), references)

    def test_repeated_manage_click_focuses_existing_dialog(self):
        with patch("WinUx.dialogs.reference_chart_dialog.ReferenceChartDialog") as factory:
            PlotDockingMixin._show_reference_chart_dialog(self.view)
            PlotDockingMixin._show_reference_chart_dialog(self.view)
        factory.assert_called_once()
        factory.return_value.focus.assert_called_once_with()

    def test_profile_failure_reports_error_and_keeps_saved_data(self):
        with patch("WinUx.dialogs.reference_chart_dialog.ReferenceChartDialog") as factory:
            PlotDockingMixin._show_reference_chart_dialog(self.view)
            callback = factory.call_args.args[2]
        with patch.object(self.library.store, "save", side_effect=OSError("Access denied")):
            callback(parse_reference_text("0,1"))
        self.view.show_error.assert_called_once()
        self.assertEqual(self.library.snapshot(), [])

    def test_adapter_uses_reference_kind_and_delivers_only_after_close(self):
        result = Mock()
        series = parse_reference_text("0,1", "Reference")
        with patch.object(FloatingDialogController, "__init__", autospec=True, return_value=None) as init:
            dialog = ReferenceChartDialog(self.view, series, result)
        self.assertEqual(init.call_args.args[2], "reference_chart")
        self.assertEqual(init.call_args.args[4], {"series": series})
        self.assertTrue(init.call_args.kwargs["modal"])
        dialog.view = SimpleNamespace(after=Mock())
        dialog.handle_event("result", {"value": series})
        result.assert_not_called()
        dialog._notify_result()
        dialog.view.after.assert_called_once_with(dialog.ASYNC_RESULT_DELAY_MS, result, series)


if __name__ == "__main__":
    unittest.main()
