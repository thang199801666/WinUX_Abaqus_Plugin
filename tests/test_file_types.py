"""Shell Type labels without file access or GUI dependencies."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import ctypes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_winux
run_winux._configure_bundled_dependencies(str(Path(__file__).resolve().parents[1]))
from WinUx.services import file_types as types
from WinUx.models.items import FileItem
from WinUx.ui.components.explorer_list_model import ListViewItem
from WinUx.ui.components.file_panel import FilePanel


class FileTypeTests(unittest.TestCase):
    def setUp(self):
        types.clear_file_type_cache()

    def test_normalized_extension_cache_and_remote_names(self):
        with patch.object(types, '_read_shell_type', return_value='Text Document') as query:
            for name in ('sample.LOG', '/remote/logs/sample.log', r'\\server\share\sample.Log'):
                self.assertEqual(types.file_type_name(name), 'Text Document')
            query.assert_called_once_with('.log', False)

    def test_expiry_clear_and_bounded_cache(self):
        with patch.object(types, '_read_shell_type', return_value='Type') as query:
            with patch.object(types.time, 'monotonic', return_value=60):
                types.file_type_name('a.log')
                types.file_type_name('b.log')
            with patch.object(types.time, 'monotonic', return_value=120):
                types.file_type_name('a.log')
            self.assertEqual(query.call_count, 2)
            types.clear_file_type_cache()
            for i in range(600):
                types.file_type_name('a.ext' + str(i))
            self.assertEqual(types._cached_type.cache_info().currsize, 512)

    def test_fallback_and_directories(self):
        with patch.object(types, '_read_shell_type', return_value=''):
            for name, expected in [('a.xyz', 'XYZ File'), ('README', 'File'), ('a.', 'File')]:
                self.assertEqual(types.file_type_name(name), expected)
            self.assertEqual(types.file_type_name('folder.log', True), 'File folder')

    def test_models_use_shell_and_preserve_explicit_labels(self):
        with patch.object(types, '_read_shell_type', return_value='Shell label'):
            item = FileItem('example.com', Path('example.com'), False, 12, 0)
            self.assertEqual(item.type_text, 'Shell label')
            self.assertEqual(ListViewItem('example.com').item_type, item.type_text)
            self.assertEqual(FilePanel._convert(item).item_type, item.type_text)
            self.assertEqual(ListViewItem._guess_type('example.com'), item.type_text)
            for label in ('Parent folder', 'Job'):
                self.assertEqual(ListViewItem('row', item_type=label).item_type, label)

    @unittest.skipUnless(types.os.name == 'nt', 'Windows Shell required')
    def test_flags_attributes_and_synthetic_probe(self):
        def query(probe, attributes, ptr, size, flags):
            self.assertEqual(probe, 'file.com')
            self.assertEqual(attributes, types._FILE_ATTRIBUTE_NORMAL)
            self.assertEqual(flags, types._SHGFI_TYPENAME | types._SHGFI_USEFILEATTRIBUTES)
            self.assertEqual(size, ctypes.sizeof(types._SHFILEINFOW))
            ctypes.cast(ptr, ctypes.POINTER(types._SHFILEINFOW)).contents.szTypeName = 'Shell result'
            return 1
        from unittest.mock import Mock
        with patch.object(types, '_shell_type_query', return_value=Mock(side_effect=query)):
            self.assertEqual(types._read_shell_type('.com', False), 'Shell result')

    @unittest.skipUnless(types.os.name == 'nt', 'Windows Shell required')
    def test_actual_shell(self):
        shared_query = ctypes.windll.shell32.SHGetFileInfoW
        shared_signature = shared_query.argtypes
        for name in ('a.com', 'a.log', 'a.msg', 'a.res', 'a.xlsx', 'a.unknown_ext_123', 'README'):
            extension = types.ntpath.splitext(name)[1]
            self.assertEqual(types.file_type_name(name), types._read_shell_type(extension, False))
        self.assertEqual(types.file_type_name('folder', True), types._read_shell_type('', True))
        self.assertIs(shared_query.argtypes, shared_signature)
        self.assertIsNot(types._shell_type_query(), shared_query)


if __name__ == '__main__':
    unittest.main(verbosity=2)
