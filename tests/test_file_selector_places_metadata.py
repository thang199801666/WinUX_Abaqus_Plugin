from __future__ import annotations

import unittest
from unittest.mock import patch

from WinUx.dialogs.selectors.local_folder_form import LocalFolderDialog


class FileSelectorPlacesMetadataTests(unittest.TestCase):
    def test_place_shell_metadata_is_scheduled_per_row(self):
        dialog = LocalFolderDialog.__new__(LocalFolderDialog)
        dialog._finished = False
        dialog._place_items = {
            r"C:\\Users\\tester": ("home", False),
            r"C:\\": ("c", True),
            r"Z:\\": ("z", True),
        }
        dialog.winfo_exists = lambda: True
        applied = []
        dialog._apply_place_icon = lambda *args: applied.append(args)
        scheduled = []

        def run_async(callback, *, on_result=None, **_kwargs):
            scheduled.append(callback)
            result = callback()
            if on_result is not None:
                on_result(result)

        dialog.runAsync = run_async
        with patch(
            "WinUx.dialogs.selectors.local_folder_form.WindowsIconRegistry.read_path_info",
            side_effect=lambda path: ("image:" + path, "shell:" + path),
        ), patch(
            "WinUx.dialogs.selectors.local_folder_form.drive_display_name",
            side_effect=lambda path: "Data (%s)" % path[:2],
        ):
            LocalFolderDialog._load_place_icons(dialog)

        self.assertEqual(len(scheduled), 3)
        self.assertEqual(len(applied), 3)
        self.assertEqual(applied[0][3], r"shell:C:\\Users\\tester")
        self.assertEqual(applied[1][3], "Data (C:)")
        self.assertEqual(applied[2][3], "Data (Z:)")

    def test_drive_shell_failure_does_not_prevent_other_rows_being_scheduled(self):
        dialog = LocalFolderDialog.__new__(LocalFolderDialog)
        dialog._finished = False
        dialog._place_items = {
            r"C:\\": ("c", True),
            r"D:\\": ("d", True),
        }
        dialog.winfo_exists = lambda: True
        dialog._apply_place_icon = lambda *_args: None
        scheduled = []
        dialog.runAsync = lambda callback, **kwargs: scheduled.append(callback)

        LocalFolderDialog._load_place_icons(dialog)
        self.assertEqual(len(scheduled), 2)
        self.assertIsNot(scheduled[0], scheduled[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
