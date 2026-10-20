"""Check actual file/folder selector sidebar rendering with Abaqus Python.

Run each mode in a separate process to isolate native GUI contexts.
"""
import argparse
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_local_folder_browser import FolderBrowserTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', action='store_true')
    parser.add_argument('--capture', type=Path, help='Save a rendered selector preview PNG')
    parser.add_argument('--select-first', action='store_true', help='Preview the Qt-style active row')
    args = parser.parse_args()
    if args.capture:
        from tests.test_local_folder_browser import dpg
        fixture = FolderBrowserTests()
        from WinUx.dialogs.local_file_form import LocalFileDialog
        from WinUx.dialogs.local_folder_form import LocalFolderDialog
        with patch('tests.test_local_folder_browser.LocalFolderDialog',
                   LocalFileDialog if args.file else LocalFolderDialog):
            fixture.setUp()
        try:
            if args.select_first and fixture.dialog.listbox._values:
                fixture.dialog.listbox.setCurrentKey(fixture.dialog.listbox._values[0].key, select=True)
            for _ in range(4):
                fixture.frame()
            args.capture.parent.mkdir(parents=True, exist_ok=True)
            dpg.output_frame_buffer(str(args.capture))
            for _ in range(4):
                fixture.frame()
            assert args.capture.is_file(), 'Renderer did not save the preview'
            print('WINUX_SELECTOR_PREVIEW_OK ' + str(args.capture), flush=True)
        finally:
            fixture.tearDown()
        return
    suite = unittest.TestSuite(FolderBrowserTests(name) for name in (
        'test_sidebar_rows_have_visible_full_width_hit_targets',
        'test_sidebar_has_compact_qt_icon_and_label_geometry',
        'test_compact_qt_selector_layout_and_size_column',
        'test_folder_list_and_address_use_windows_shell_folder_icon',
        'test_selector_control_geometry_stays_aligned_after_resize',
        'test_selector_state_themes_restore_focus_disabled_and_provider_removal',
        'test_qt_location_field_remains_editable_and_offers_parent_locations'))
    if args.file:
        from WinUx.dialogs.local_file_form import LocalFileDialog
        with patch('tests.test_local_folder_browser.LocalFolderDialog', LocalFileDialog):
            result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print('WINUX_SELECTOR_SIDEBAR_OK ' + ('file' if args.file else 'folder'), flush=True)


if __name__ == '__main__':
    main()
