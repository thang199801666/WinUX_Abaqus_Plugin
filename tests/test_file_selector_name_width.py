"""Cold Details geometry must never shrink all filenames to a 1 px clip."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from WinUx.dialogs.local_folder_form import FolderListView
from WinUx.dialogs.folder_browser_style import METRICS


class FilenameWidthTests(unittest.TestCase):
    def setUp(self):
        self.view = FolderListView.__new__(FolderListView)
        self.view.details_mode = True
        self.view._values = [SimpleNamespace(key='file', text='Test-Plotdigitizer-02.png')]
        self.view.items = {'file': 'filename'}
        self.view._details_header_cells = ['name_header']
        self.view._name_column_width = None
        self.view.backend = Mock()
        self.positions = {'filename': (124, 140), 'name_header': (100, 100)}
        self.sizes = {'filename': (160, 26), 'name_header': (300, 30)}
        self.view.backend.get_item_rect_min.side_effect = self.positions.__getitem__
        self.view.backend.get_item_rect_size.side_effect = self.sizes.__getitem__
        metrics = SimpleNamespace(horizontalAdvance=lambda text: len(text) * 7)
        patcher = patch('WinUx.dialogs.local_folder_form.QFontMetrics', return_value=metrics)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_details_starts_with_readable_width(self):
        self.assertGreater(FolderListView._initial_name_width(self.view), 32)

    def test_zero_initial_header_does_not_elide_filenames(self):
        self.sizes['name_header'] = (0, 0)
        self.view._fit_name_column()
        self.view.backend.configure_item.assert_not_called()
        self.assertIsNone(self.view._name_column_width)

    def test_mixed_frame_coordinates_are_ignored(self):
        for position in ((0, 0), (500, 0)):
            self.positions['filename'] = position
            self.view._fit_name_column()
        self.view.backend.configure_item.assert_not_called()

    def test_unrendered_filename_does_not_commit_geometry(self):
        self.sizes['filename'] = (0, 0)
        self.view._fit_name_column()
        self.view.backend.configure_item.assert_not_called()

    def test_rendered_header_restores_full_name_after_cold_frame(self):
        self.sizes['name_header'] = (0, 0)
        self.view._fit_name_column()
        self.sizes['name_header'] = (300, 30)
        self.view._fit_name_column()
        self.view.backend.configure_item.assert_called_once_with(
            'filename', width=276 - METRICS.details_cell_padding_x,
            label='Test-Plotdigitizer-02.png')


if __name__ == '__main__':
    unittest.main()
