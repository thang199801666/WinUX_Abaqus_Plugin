"""Pure selection-policy coverage for the four public selector modes."""
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from WinUx.dialogs.path_selection import PathSelectionOptions
from WinUx.dialogs.local_folder_form import LocalFolderDialog, LocalPathDialog
from WinUx.dialogs.local_file_form import LocalFileDialog
from WinUx.ui.file_dialog import FileSelector


class PathSelectionTests(unittest.TestCase):
    def setUp(self):
        temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        self.directory = tempfile.TemporaryDirectory(dir=temp)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ('first folder', 'second folder'):
            (self.root / name).mkdir()
        for name in ('one model.inp', 'two.inp', 'other.txt'):
            (self.root / name).write_text('test')

    def test_selectors_are_siblings_with_one_shared_implementation(self):
        self.assertEqual(LocalFileDialog.__bases__, (LocalPathDialog,))
        self.assertEqual(LocalFolderDialog.__bases__, (LocalPathDialog,))
        self.assertIs(LocalFileDialog._build_selection_fields, LocalFolderDialog._build_selection_fields)
        self.assertIs(LocalFileDialog._select_folder, LocalFolderDialog._select_folder)

    def test_single_file_and_folder_keep_string_results(self):
        for kind, name in (('file', 'one model.inp'), ('folder', 'first folder')):
            options = PathSelectionOptions(kind)
            self.assertEqual(options.resolve(self.root, name), str(self.root / name))

    def test_multiple_files_and_folders_round_trip_spaces_and_order(self):
        for kind, names in (('file', ['one model.inp', 'two.inp']),
                            ('folder', ['first folder', 'second folder'])):
            options = PathSelectionOptions(kind, multiple=True)
            paths = [str(self.root / name) for name in names]
            text = options.format_paths(paths)
            self.assertEqual(options.resolve(self.root, text), paths)

    def test_multiple_with_one_item_still_returns_list(self):
        self.assertEqual(PathSelectionOptions('file', True).resolve(self.root, 'two.inp'),
                         [str(self.root / 'two.inp')])

    def test_multiple_deduplicates_and_rejects_malformed_quotes(self):
        options = PathSelectionOptions('file', True)
        self.assertEqual(options.resolve(self.root, '"two.inp" "two.inp"'),
                         [str(self.root / 'two.inp')])
        with self.assertRaises(ValueError):
            options.resolve(self.root, '"two.inp" leftover')

    def test_file_and_folder_results_never_mix(self):
        for options, text in ((PathSelectionOptions('file'), 'first folder'),
                              (PathSelectionOptions('folder'), 'two.inp')):
            with self.assertRaises(ValueError):
                options.resolve(self.root, text)

    def test_reject_missing_and_empty_inputs(self):
        for kind in ('file', 'folder'):
            for text in ('', 'missing'):
                with self.assertRaises(ValueError):
                    PathSelectionOptions(kind).resolve(self.root, text)

    def test_extension_filter_and_all_files(self):
        options = PathSelectionOptions('file', extensions=('*.INP', 'inp', '.inp'))
        self.assertEqual(options.extensions, ('.inp',))
        with self.assertRaises(ValueError):
            options.resolve(self.root, 'other.txt')
        self.assertEqual(options.resolve(self.root, 'other.txt', show_all=True),
                         str(self.root / 'other.txt'))

    def test_filters_keep_folders_navigable_and_exclude_other_files(self):
        with os.scandir(self.root) as entries:
            entries = {entry.name: entry for entry in entries}
        files = PathSelectionOptions('file', extensions=('inp',))
        folders = PathSelectionOptions('folder')
        self.assertTrue(files.includes(entries['first folder'], True))
        self.assertTrue(files.includes(entries['two.inp'], False))
        self.assertFalse(files.includes(entries['other.txt'], False))
        self.assertTrue(files.includes(entries['other.txt'], False, show_all=True))
        self.assertTrue(folders.includes(entries['first folder'], True))
        self.assertFalse(folders.includes(entries['two.inp'], False))

    def test_save_extension_and_destination_validation(self):
        options = PathSelectionOptions('file', extensions=('inp',), save=True)
        self.assertEqual(options.resolve(self.root, 'new model'), str(self.root / 'new model.inp'))
        with self.assertRaises(ValueError):
            options.resolve(self.root, 'missing/new.inp')

    def test_invalid_modes_fail_before_starting_dialog(self):
        for kind, multiple in (('file', True), ('folder', False), ('folder', True)):
            with self.assertRaises(ValueError):
                PathSelectionOptions(kind, multiple, save=True)
        with self.assertRaises(ValueError):
            PathSelectionOptions('mixed')
        with self.assertRaises(ValueError):
            FileSelector(view=None, accepted=None, save=True, multiple=True)

    def test_facade_delivers_list_unchanged_and_cancel_separately(self):
        results, cancelled = [], []
        selector = FileSelector(view=None, accepted=results.append, multiple=True,
                                cancelled=lambda: cancelled.append(True))
        paths = [str(self.root / 'two.inp')]
        selector._result(paths)
        selector._result(None)
        self.assertEqual(results, [paths])
        self.assertEqual(cancelled, [True])

    def test_public_options_reach_both_host_adapters(self):
        for native in (False, True):
            for directory in (False, True):
                module = 'floating_adapters' if native else 'inprocess_adapters'
                name = 'LocalFolderDialog' if directory else 'LocalFileDialog'
                with self.subTest(native=native, directory=directory), patch(
                        'WinUx.dialogs.' + module + '.' + name,
                        return_value=Mock(tag='selector')) as factory:
                    selector = FileSelector(
                        view=SimpleNamespace(use_native_file_selectors=native), accepted=None,
                        directory=directory, multiple=True, show_hidden=True, title='Pick paths')
                    selector.open()
                    self.assertTrue(factory.call_args.kwargs['multiple'])
                    self.assertTrue(factory.call_args.kwargs['show_hidden'])
                    self.assertEqual(factory.call_args.kwargs['title'], 'Pick paths')

    def test_floating_factory_preserves_mode_options_and_list_results(self):
        from WinUx.dialogs.floating_forms import create_form
        for kind, name in (('folder', 'LocalFolderDialog'), ('file', 'LocalFileDialog')):
            module = 'local_folder_form' if kind == 'folder' else 'local_file_form'
            with self.subTest(kind=kind), patch(
                    'WinUx.dialogs.' + module + '.' + name) as factory:
                emit = Mock()
                create_form('local_' + kind, {
                    'initial': str(self.root), 'multiple': True,
                    'show_hidden': True, 'title': 'Pick paths'}, None, emit)
                kwargs = factory.call_args.kwargs
                self.assertTrue(kwargs['multiple'])
                self.assertTrue(kwargs['show_hidden'])
                self.assertEqual(kwargs['title'], 'Pick paths')
                paths = [str(self.root / ('two.inp' if kind == 'file' else 'first folder'))]
                kwargs['on_result'](paths)
                emit.assert_called_once_with('result', value=paths)


if __name__ == '__main__':
    unittest.main()
