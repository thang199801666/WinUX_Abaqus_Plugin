import unittest

from WinUx.controllers.jobs import plot


class JobViewerOdbCompletionImportTests(unittest.TestCase):
    def test_job_plot_controller_has_completion_helper_imported(self):
        self.assertTrue(callable(plot.submit_with_completion))

    def test_odb_command_references_imported_completion_helper(self):
        names = set(plot.JobPlotController.odb_command.__code__.co_names)
        self.assertIn('submit_with_completion', names)
        self.assertTrue(hasattr(plot, 'submit_with_completion'))


if __name__ == '__main__':
    unittest.main()
