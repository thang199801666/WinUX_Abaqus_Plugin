"""Query-local metadata fallback reuse keeps file listing signatures exact."""
from dataclasses import replace
from pathlib import PureWindowsPath
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from benchmark_file_panel_signatures import FilePanel, FileItem, PurePosixPath, RepeatedMetadataPanel
from WinUx.ui.components.explorer_list_model import FILE_METADATA_KEYS


class FilePanelSignatureTests(unittest.TestCase):
    def source(self, **changes):
        return replace(FileItem('sample.inp', PurePosixPath('/work/sample.inp'), False, 42, 100,
                                mode=0o100640, uid=1000), **changes)

    def same(self, item):
        self.assertEqual(FilePanel._item_signature(item), RepeatedMetadataPanel._item_signature(item))

    def test_loaded_sources_and_render_rows_match_full_reference(self):
        for source in (self.source(), self.source(is_dir=True), self.source(is_hidden=True),
                       self.source(size=0, modified=0), self.source(is_symlink=True, attributes=0x400)):
            self.same(source)
            self.same(FilePanel._convert(source))

    def test_data_property_is_read_once_for_fallbacks_plus_hidden_check(self):
        class Snapshot(SimpleNamespace):
            @property
            def data(self):
                self.reads += 1
                return self.metadata
        item = Snapshot(name='sample.inp', path=PurePosixPath('/work/sample.inp'),
                        is_dir=False, size=42, modified=100, is_hidden=False,
                        reads=0, metadata={'uid': 1000})
        expected = RepeatedMetadataPanel._item_signature(item)
        self.assertEqual(item.reads, len(FILE_METADATA_KEYS) + 2)
        item.reads = 0
        self.assertEqual(FilePanel._item_signature(item), expected)
        self.assertEqual(item.reads, 2)

    def test_explicit_attribute_none_overrides_metadata_fallback(self):
        item = SimpleNamespace(name='a', path='/work/a', size=1, modified=10,
                               mode=None, uid=0, data={'mode': 0o100755, 'uid': 99})
        self.same(item)
        values = dict(zip(FILE_METADATA_KEYS, FilePanel._item_signature(item)[-1]))
        self.assertIsNone(values['mode'])
        self.assertEqual(values['uid'], 0)

    def test_missing_empty_and_none_data_keep_previous_defaults(self):
        for data in ({}, None):
            # Existing hidden helper short-circuits on an explicit hidden flag;
            # this exercise concerns the signature's nullable fallback only.
            self.same(SimpleNamespace(name='a', path='', is_dir=False, is_hidden=data is None,
                                      size=None, mtime=1.25, data=data))
        self.same(SimpleNamespace(name='a', size=0, modified=None, mtime=100))
        for kind in (FilePanel, RepeatedMetadataPanel):
            with self.assertRaises(AttributeError):
                kind._item_signature(SimpleNamespace(name='a', data=None))

    def test_data_path_override_and_remote_case_identity_are_unchanged(self):
        item = SimpleNamespace(name='a', path='/ignored', size=1, modified=0,
                               data={'path': PurePosixPath('/work/A')})
        self.same(item)
        upper = FilePanel._item_signature(item)
        item.data['path'] = PurePosixPath('/work/a')
        self.same(item)
        self.assertNotEqual(upper, FilePanel._item_signature(item))
        item.data['path'] = PureWindowsPath('C:/work/a')
        self.same(item)

    def test_mutating_metadata_between_calls_is_not_cached(self):
        row = FilePanel._convert(self.source())
        before = FilePanel._item_signature(row)
        row.data['uid'] = 99
        self.assertNotEqual(before, FilePanel._item_signature(row))
        self.same(row)
        row.data['is_hidden'] = True
        self.assertTrue(FilePanel._item_signature(row)[4])

    def test_all_fallback_metadata_fields_still_affect_signature(self):
        for key in FILE_METADATA_KEYS:
            row = FilePanel._convert(self.source())
            before = FilePanel._item_signature(row)
            row.data[key] = 'changed'
            self.assertNotEqual(before, FilePanel._item_signature(row), key)
            self.same(row)

    def test_signature_is_loaded_metadata_only(self):
        source = self.source()
        with patch('os.stat', side_effect=AssertionError('signature probed filesystem')):
            self.same(source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
